import requests
from django.contrib.auth import get_user_model
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, filters
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Функция для обработки /start
def start(update: Update, context):
    update.message.reply_text("Пожалуйста, отправьте ваш email, чтобы связать вашу учетную запись с Telegram.")

# Функция для сохранения Telegram ID в базе данных
def save_telegram_id(update: Update, context):
    user_email = update.message.text  # Пользователь отправляет email
    telegram_id = update.message.from_user.id  # Получаем Telegram ID

    # Ищем пользователя по email
    user = get_user_model().objects.filter(email=user_email).first()

    if user:
        # Сохраняем Telegram ID в базе данных пользователя
        user.telegram_id = telegram_id
        user.save()

        # Отправляем сообщение пользователю
        update.message.reply_text("Ваш Telegram ID был успешно сохранен!")
    else:
        # Если пользователь не найден
        update.message.reply_text("Пользователь с таким email не найден. Пожалуйста, зарегистрируйтесь на сайте.")

# Функция для отправки данных на сервер для аутентификации
def send_login_request(telegram_id, email):
    url = 'http://localhost:8000/login/'  # URL для аутентификации
    data = {
        'telegram_id': telegram_id,
        'email': email,
        'auth_method': 'TELEGRAM'  # Указываем, что аутентификация через Telegram
    }

    response = requests.post(url, data=data)
    return response.json()

# Основная функция бота
def main():
    # Токен вашего бота
    updater = Updater(token='7591573688:AAFtWbtZ4v5UcS1Hyl121gJlxLA8riIuB4Q', use_context=True)
    dispatcher = updater.dispatcher

    # Обработчик команд /start
    dispatcher.add_handler(CommandHandler("start", start))

    # Обработчик получения email
    dispatcher.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_telegram_id))
    # Запуск бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()