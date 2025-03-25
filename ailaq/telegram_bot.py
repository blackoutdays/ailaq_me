import logging
import asyncio
import os
import django
import nest_asyncio
import requests

nest_asyncio.apply()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model
from django.conf import settings
from asgiref.sync import sync_to_async
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import telegram

from ailaq.models import Session, Review, PsychologistProfile, ClientProfile
bot = telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

User = get_user_model()

async def get_psychologist_profile(telegram_id):
    return await sync_to_async(PsychologistProfile.objects.get)(telegram_id=telegram_id)

async def get_client_profile(telegram_id):
    return await sync_to_async(ClientProfile.objects.get)(telegram_id=telegram_id)

async def send_welcome_message(telegram_id):
    """Бот отправляет приветственное сообщение, когда получает Telegram ID"""
    await bot.send_message(telegram_id, "👋 Привет! Теперь я могу писать вам первым.")


async def link_telegram_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Привязывает Telegram ID к существующему пользователю, если он уже зарегистрирован.
    Если пользователя нет, создает нового клиента.
    """
    telegram_id = update.effective_chat.id
    username = update.effective_chat.username or f"user_{telegram_id}"

    # Проверяем, есть ли уже клиент с таким Telegram ID
    user = await sync_to_async(User.objects.filter(telegram_id=telegram_id).first)()

    if user:
        await update.message.reply_text(" Вы уже привязаны к системе!")
    else:
        # Создаём нового клиента
        user = await sync_to_async(User.objects.create)(
            telegram_id=telegram_id,
            email=f"{telegram_id}@telegram.local",
            username=username,
            is_active=True,
        )
        await sync_to_async(ClientProfile.objects.create)(user=user, full_name=username)

        await update.message.reply_text(" Ваш Telegram успешно привязан!")
        await send_welcome_message(telegram_id)

async def schedule_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Введите ID психолога для назначения сессии.")

async def send_telegram_message(telegram_id, text):
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": telegram_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()

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
        await bot.send_message(
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

def notify_client_to_leave_review(session: Session):
    if not session.review_requested and session.client.telegram_id:
        text = (
            f"🙏 Пожалуйста, оцените вашу сессию с психологом {session.psychologist.user.get_full_name()}.\n"
            "Введите оценку от 1 до 5 и добавьте ваш отзыв."
        )
        send_telegram_message(session.client.telegram_id, text)
        session.review_requested = True
        session.save()

pending_reviews = {}

async def process_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_chat.id
    client = await sync_to_async(User.objects.get)(clientprofile__telegram_id=telegram_id)

    try:
        session = await sync_to_async(Session.objects.filter)(
            client=client.clientprofile,
            status="COMPLETED",
            review_requested=True,
            review_submitted=False
        ).latest("end_time")

        text = update.message.text.strip()
        if text.isdigit() and 1 <= int(text) <= 5:
            pending_reviews[telegram_id] = {"rating": int(text)}
            await update.message.reply_text("Теперь введите текст отзыва.")
        elif telegram_id in pending_reviews:
            rating = pending_reviews[telegram_id]["rating"]
            review = await sync_to_async(Review.objects.create)(
                session=session,
                client=client.clientprofile,
                psychologist=session.psychologist,
                rating=rating,
                text=text
            )
            session.review_submitted = True
            await sync_to_async(session.save)()
            del pending_reviews[telegram_id]
            await update.message.reply_text("Спасибо! Ваш отзыв сохранён.")
        else:
            await update.message.reply_text("Введите сначала число от 1 до 5.")
    except Session.DoesNotExist:
        await update.message.reply_text("У вас нет завершённых сессий без отзыва.")

async def main() -> None:
    application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Команда для привязки Telegram ID (используется автоматически при авторизации)
    application.add_handler(CommandHandler("start", link_telegram_user))

    # Команды для клиентов
    application.add_handler(MessageHandler(filters.Regex("Назначить сессию"), schedule_session))
    application.add_handler(MessageHandler(filters.Regex("Оставить отзыв"), leave_review))

    # Обработка ввода текста
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_session_request))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_review))

    await application.run_polling()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())