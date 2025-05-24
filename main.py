import os

import telebot
import requests
import time
from telebot import types
from datetime import datetime
import threading
from dotenv import load_dotenv


load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')

bot = telebot.TeleBot(TOKEN)

cities = {
    'Минск': 'c625144',
    'Дятлово': 'c628658'
}

tracking_users = {}
monitoring_threads = {}


def generate_url(from_city, to_city, passengers, date, time):
    from_id = cities.get(from_city)
    to_id = cities.get(to_city)

    if not from_id or not to_id:
        return None

    return f'https://atlasbus.by/api/search?from_id={from_id}&to_id={to_id}&date={date}&time={time}:00&passengers={passengers}'


def check_free_seats(url, chat_id):
    x = requests.get(url)

    try:
        data = x.json()
    except ValueError:
        bot.send_message(chat_id, "Ошибка: не удалось распарсить JSON от сервера.")
        return None

    rides_list = data if isinstance(data, list) else data.get('rides', [])

    if not rides_list:
        bot.send_message(chat_id, "Нет доступных рейсов или изменился формат данных.")
        return None

    user_time = tracking_users.get(chat_id, {}).get('time')

    for rides in rides_list:
        out_time = rides.get('departure')
        arrival_time = rides.get('arrival')
        free_seats = rides.get('freeSeats')
        price = rides.get('price')

        if free_seats and user_time == out_time:
            return f"Время отправления: {out_time}\nВремя прибытия: {arrival_time}\nКоличество свободных мест: {free_seats}\nЦена билета: {price}"

    return None


def monitor(url, chat_id):
    while chat_id in monitoring_threads:
        free_seat_info = check_free_seats(url, chat_id)
        if free_seat_info:
            bot.send_message(chat_id, free_seat_info)
            del monitoring_threads[chat_id]  # Остановка мониторинга
            break
        time.sleep(60)


@bot.message_handler(commands=['start'])
def send_welcome_message(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True)
    markup.add(*cities.keys())
    bot.send_message(message.chat.id, 'Привет! Выберите город отправления:', reply_markup=markup)


@bot.message_handler(
    func=lambda message: message.text in cities and 'from_city' not in tracking_users.get(message.chat.id, {}))
def choose_from_city(message):
    tracking_users.setdefault(message.chat.id, {})['from_city'] = message.text
    to_cities = ['Дятлово'] if message.text == 'Минск' else ['Минск']

    markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True)
    markup.add(*to_cities)
    bot.send_message(message.chat.id, 'Теперь выберите город назначения:', reply_markup=markup)


@bot.message_handler(
    func=lambda message: message.text in cities and 'to_city' not in tracking_users.get(message.chat.id, {}))
def choose_to_city(message):
    tracking_users[message.chat.id]['to_city'] = message.text

    markup = types.ReplyKeyboardMarkup(row_width=3, one_time_keyboard=True)
    markup.add('1', '2', '3', '4', '5')
    bot.send_message(message.chat.id, 'Выберите количество пассажиров:', reply_markup=markup)


@bot.message_handler(
    func=lambda message: message.text.isdigit() and 'passengers' not in tracking_users.get(message.chat.id, {}))
def choose_passengers(message):
    tracking_users[message.chat.id]['passengers'] = int(message.text)
    bot.send_message(message.chat.id, 'Введите дату отправления (ГГГГ-ММ-ДД):')
    bot.register_next_step_handler(message, choose_date)


def choose_date(message):
    try:
        date = datetime.strptime(message.text, '%Y-%m-%d').strftime('%Y-%m-%d')
        tracking_users[message.chat.id]['date'] = date
        bot.send_message(message.chat.id, 'Введите время отправления (ЧЧ:ММ):')
        bot.register_next_step_handler(message, choose_time)
    except ValueError:
        bot.send_message(message.chat.id, 'Неверный формат даты. Используйте ГГГГ-ММ-ДД.')


def choose_time(message):
    try:
        datetime.strptime(message.text, '%H:%M')
        tracking_users[message.chat.id]['time'] = message.text

        user_data = tracking_users[message.chat.id]
        url = generate_url(user_data['from_city'], user_data['to_city'], user_data['passengers'], user_data['date'],
                           user_data['time'])

        if url:
            bot.send_message(message.chat.id, 'Начинаем отслеживание свободных мест...')
            monitoring_thread = threading.Thread(target=monitor, args=(url, message.chat.id))
            monitoring_threads[message.chat.id] = monitoring_thread
            monitoring_thread.start()
        else:
            bot.send_message(message.chat.id, 'Ошибка при формировании запроса.')

    except ValueError:
        bot.send_message(message.chat.id, 'Неверный формат времени. Используйте ЧЧ:ММ.')


@bot.message_handler(commands=['stop'])
def stop_tracking(message):
    chat_id = message.chat.id
    if chat_id in monitoring_threads:
        del monitoring_threads[chat_id]
        bot.send_message(chat_id, "🚫 Отслеживание остановлено.")
    else:
        bot.send_message(chat_id, "❌ Нет активного отслеживания.")


bot.polling(non_stop=True)