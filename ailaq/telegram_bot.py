import logging
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.contrib.auth import get_user_model
from config import settings

import nest_asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import requests
from asgiref.sync import sync_to_async
from ailaq.models import Session, Review, PsychologistProfile, ClientProfile

nest_asyncio.apply()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

BACKEND_URL = "http://localhost:8000/link-telegram/"

User = get_user_model()

CLIENT_COMMANDS = [
    ["Назначить сессию"],
    ["Оставить отзыв"],
]

# Команды для психолога
PSYCHOLOGIST_COMMANDS = [
    ["Посмотреть активные заявки"],
    ["Посмотреть заявки на сессии"],
]

async def handle_verification_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_input = update.message.text.split(' ')

    if len(user_input) != 2:
        await update.message.reply_text("Пожалуйста, введите код в формате: /code <ваш_код>")
        return

    verification_code = user_input[1]
    telegram_id = update.effective_chat.id

    try:
        # Отправляем запрос на привязку Telegram ID
        response = requests.post(
            f"{BACKEND_URL}",
            json={
                "verification_code": verification_code,
                "telegram_id": telegram_id
            }
        )

        # Обрабатываем ответ
        if response.status_code == 200:
            await update.message.reply_text("Ваш Telegram ID успешно привязан!")
        else:
            error_message = response.json().get('error', 'Неправильный код')
            await update.message.reply_text(f"Ошибка: {error_message}")

    except Exception as e:
        logging.exception(e)
        await update.message.reply_text("Произошла ошибка при привязке Telegram ID. Попробуйте ещё раз.")


async def get_psychologist_profile(telegram_id):
    return await sync_to_async(PsychologistProfile.objects.get)(telegram_id=telegram_id)


async def get_client_profile(telegram_id):
    return await sync_to_async(ClientProfile.objects.get)(telegram_id=telegram_id)


async def schedule_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Введите ID психолога для назначения сессии.")


async def process_session_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    psychologist_id = update.message.text
    client_id = update.effective_chat.id

    try:
        psychologist_profile = await get_psychologist_profile(int(psychologist_id))
        client_profile = await get_client_profile(client_id)

        await sync_to_async(Session.objects.create)(
            psychologist=psychologist_profile,
            client=client_profile,
            status="SCHEDULED",
        )
        await update.message.reply_text("Сессия назначена. Психолог будет уведомлён.")
        await context.bot.send_message(
            chat_id=psychologist_profile.telegram_id,
            text="У вас новая заявка на сессию.",
        )
    except PsychologistProfile.DoesNotExist:
        await update.message.reply_text("Ошибка: Психолог с указанным Telegram ID не найден.")
    except ClientProfile.DoesNotExist:
        await update.message.reply_text("Ошибка: Клиент с указанным Telegram ID не найден.")
    except ValueError:
        await update.message.reply_text("Ошибка: Telegram ID должен быть числом.")


async def leave_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Введите текст отзыва после завершения сессии.")


async def process_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    review_text = update.message.text
    client_id = update.effective_chat.id

    try:
        client = await sync_to_async(User.objects.get)(clientprofile__telegram_id=client_id)
        session = await sync_to_async(Session.objects.filter)(
            client=client.clientprofile, status="COMPLETED"
        ).latest("end_time")
        await sync_to_async(Review.objects.create)(session=session, text=review_text, rating=5)
        await update.message.reply_text("Спасибо за ваш отзыв! Он будет передан психологу.")
    except (User.DoesNotExist, Session.DoesNotExist):
        await update.message.reply_text("Ошибка: У вас нет завершённых сессий.")


async def view_active_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_chat.id
    try:
        psychologist = await sync_to_async(User.objects.get)(psychologist_profile__telegram_id=telegram_id)
        active_sessions = await sync_to_async(list)(
            psychologist.psychologist_profile.sessions.filter(status="SCHEDULED")
        )
        if active_sessions:
            message = "\n".join([f"Клиент: {s.client.email}, Дата: {s.start_time}" for s in active_sessions])
            await update.message.reply_text(f"Ваши активные заявки:\n{message}")
        else:
            await update.message.reply_text("У вас нет активных заявок.")
    except User.DoesNotExist:
        await update.message.reply_text("Ошибка: Профиль психолога не найден.")


async def view_completed_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_chat.id
    try:
        psychologist = await sync_to_async(User.objects.get)(psychologist_profile__telegram_id=telegram_id)
        completed_sessions = await sync_to_async(list)(
            psychologist.psychologist_profile.sessions.filter(status="COMPLETED")
        )
        if completed_sessions:
            message = "\n".join([f"Клиент: {s.client.email}, Отзыв: {s.review.text}" for s in completed_sessions])
            await update.message.reply_text(f"Ваши завершённые сессии:\n{message}")
        else:
            await update.message.reply_text("У вас нет завершённых сессий.")
    except User.DoesNotExist:
        await update.message.reply_text("Ошибка: Профиль психолога не найден.")


async def main() -> None:
    application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("code", handle_verification_code))
    application.add_handler(MessageHandler(filters.Regex("Назначить сессию"), schedule_session))
    application.add_handler(MessageHandler(filters.Regex("Оставить отзыв"), leave_review))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_session_request))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_review))
    application.add_handler(MessageHandler(filters.Regex("Посмотреть активные заявки"), view_active_requests))
    application.add_handler(MessageHandler(filters.Regex("Посмотреть заявки на сессии"), view_completed_sessions))

    await application.run_polling()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())