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

    return f'https://atlasbus.by/api/search?from_id={from_id}&to_id={to_id}&date={date}&time={time}&passengers={passengers}'



def check_free_seats(url, chat_id):
    try:
        response = requests.get(url)
        data = response.json()
    except ValueError:
        bot.send_message(chat_id, f"Ошибка: не удалось распарсить JSON.\nОтвет: {response.text}")
        return None
    except requests.RequestException as e:
        bot.send_message(chat_id, f"Ошибка запроса к API: {e}")
        return None

    rides_list = data.get('rides', [])
    if not rides_list:
        return None

    schedule = tracking_users.get(chat_id, {}).get('schedule', [])
    for ride in rides_list:
        departure_time = ride['rideStops']['Минск'][0]['datetime'][11:16]
        arrival_time = ride['rideStops']['Дятлово'][0]['datetime'][11:16]
        free_seats = ride.get('freeSeats', 0)
        price = ride.get('onlinePrice', 'не указано')

        for entry in schedule:
            if entry['time'] == departure_time:
                return (
                    f"Время отправления: {departure_time}\n"
                    f"Время прибытия: {arrival_time}\n"
                    f"Количество свободных мест: {free_seats}\n"
                    f"Цена билета: {price}"
                )
    return None




def monitor(chat_id):
    user_data = tracking_users[chat_id]
    schedule = user_data.get('schedule', [])

    while chat_id in monitoring_threads and schedule:
        for entry in schedule[:]:  # [:] чтобы можно было удалять проверенные
            date = entry['date']
            time_ = entry['time']
            url = generate_url(user_data['from_city'], user_data['to_city'], user_data['passengers'], date, time_)
            free_seat_info = check_free_seats(url, chat_id)
            if free_seat_info:
                bot.send_message(chat_id, free_seat_info)
                schedule.remove(entry)  # удаляем проверенный рейс
        time.sleep(60)


def choose_time(message):
    try:
        datetime.strptime(message.text, '%H:%M')
        chat_id = message.chat.id
        date = tracking_users[chat_id]['current_date']

        user_schedule = tracking_users[chat_id].setdefault('schedule', [])
        user_schedule.append({'date': date, 'time': message.text})

        # создаем клавиатуру с кнопками "Добавить ещё" и "Готово"
        markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True)
        markup.add('Добавить ещё', 'Готово')
        bot.send_message(chat_id, f"Дата и время добавлены: {date} {message.text}\nВыберите действие:", reply_markup=markup)

    except ValueError:
        bot.send_message(chat_id, 'Неверный формат времени. Используйте ЧЧ:ММ.')


@bot.message_handler(commands=['start'])
def send_welcome_message(message):
    chat_id = message.chat.id

    # Очистка старого состояния и остановка мониторинга
    if chat_id in monitoring_threads:
        del monitoring_threads[chat_id]
    if chat_id in tracking_users:
        del tracking_users[chat_id]

    markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True)
    markup.add(*cities.keys())
    bot.send_message(chat_id, 'Привет! Выберите город отправления:', reply_markup=markup)



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
        tracking_users[message.chat.id]['current_date'] = date  # сохраняем временно
        bot.send_message(message.chat.id, 'Введите время отправления (ЧЧ:ММ):')
        bot.register_next_step_handler(message, choose_time)
    except ValueError:
        bot.send_message(message.chat.id, 'Неверный формат даты. Используйте ГГГГ-ММ-ДД.')





@bot.message_handler(func=lambda message: message.text in ['Добавить ещё', 'Готово'])
def add_or_finish(message):
    chat_id = message.chat.id
    if message.text == 'Добавить ещё':
        bot.send_message(chat_id, 'Введите дату отправления (ГГГГ-ММ-ДД):')
        bot.register_next_step_handler(message, choose_date)
    else:  # 'Готово'
        if chat_id not in monitoring_threads:
            monitoring_thread = threading.Thread(target=monitor, args=(chat_id,))
            monitoring_threads[chat_id] = monitoring_thread
            monitoring_thread.start()
        bot.send_message(chat_id, '✅ Мониторинг запущен.')


@bot.message_handler(commands=['stop'])
def stop_tracking(message):
    chat_id = message.chat.id
    if chat_id in monitoring_threads:
        del monitoring_threads[chat_id]
        bot.send_message(chat_id, "🚫 Отслеживание остановлено.")
    else:
        bot.send_message(chat_id, "❌ Нет активного отслеживания.")


if __name__ == "__main__":
    while True:
        try:
            print("🚀 Bot polling started")
            bot.polling(
                non_stop=True,
                interval=3,
                timeout=20,
                long_polling_timeout=60
            )
        except Exception as e:
            print(f"⚠️ Polling crashed: {e}")
            time.sleep(5)
