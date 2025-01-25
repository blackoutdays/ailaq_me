import logging
import os
import django
from django.contrib.auth import get_user_model

from config import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import nest_asyncio
nest_asyncio.apply()

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from ailaq.models import Session, Review, PsychologistProfile, ClientProfile

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

User = get_user_model()

# Команды для клиента
CLIENT_COMMANDS = [
    ["Назначить сессию"],
    ["Оставить отзыв"],
]

# Команды для психолога
PSYCHOLOGIST_COMMANDS = [
    ["Посмотреть активные заявки"],
    ["Посмотреть заявки на сессии"],
]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_chat.id  # Числовой Telegram ID
    email = context.args[0] if context.args else None  # Ожидаем email как аргумент

    try:
        if not email:
            await update.message.reply_text("Ошибка: Укажите email в формате /start your_email@example.com")
            return

        # Найти пользователя по email
        user = User.objects.get(email=email)

        # Сохранить Telegram ID в зависимости от роли
        if user.is_psychologist:
            if user.psychologist_profile.telegram_id:
                await update.message.reply_text("Ваш Telegram ID уже сохранён.")
            else:
                user.psychologist_profile.telegram_id = telegram_id
                user.psychologist_profile.save()
                await update.message.reply_text(
                    "Добро пожаловать, психолог!\nВаш Telegram ID сохранён.",
                    reply_markup=ReplyKeyboardMarkup(PSYCHOLOGIST_COMMANDS, one_time_keyboard=True),
                )
        else:
            if user.clientprofile.telegram_id:
                await update.message.reply_text("Ваш Telegram ID уже сохранён.")
            else:
                user.clientprofile.telegram_id = telegram_id
                user.clientprofile.save()
                await update.message.reply_text(
                    "Добро пожаловать, клиент!\nВаш Telegram ID сохранён.",
                    reply_markup=ReplyKeyboardMarkup(CLIENT_COMMANDS, one_time_keyboard=True),
                )
    except User.DoesNotExist:
        await update.message.reply_text("Ошибка: Пользователь с таким email не найден.")
    except Exception as e:
        logging.exception(e)
        await update.message.reply_text("Произошла ошибка. Попробуйте ещё раз.")

async def schedule_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Введите ID психолога для назначения сессии.")


async def process_session_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    psychologist_id = update.message.text  # Telegram ID психолога
    client_id = update.effective_chat.id  # Telegram ID клиента

    try:
        # Найти психолога по `telegram_id`
        psychologist_profile = PsychologistProfile.objects.get(telegram_id=int(psychologist_id))
        # Найти клиента по `telegram_id`
        client_profile = ClientProfile.objects.get(telegram_id=client_id)

        # Создать заявку на сессию
        Session.objects.create(
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
        client = User.objects.get(clientprofile__telegram_id=client_id)
        session = Session.objects.filter(client=client.clientprofile, status="COMPLETED").latest("end_time")
        Review.objects.create(session=session, text=review_text, rating=5)
        await update.message.reply_text("Спасибо за ваш отзыв! Он будет передан психологу.")
    except (User.DoesNotExist, Session.DoesNotExist):
        await update.message.reply_text("Ошибка: У вас нет завершённых сессий.")


async def view_active_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_chat.id
    try:
        psychologist = User.objects.get(psychologist_profile__telegram_id=telegram_id)
        active_sessions = psychologist.psychologist_profile.sessions.filter(status="SCHEDULED")
        if active_sessions.exists():
            message = "\n".join([f"Клиент: {s.client.email}, Дата: {s.start_time}" for s in active_sessions])
            await update.message.reply_text(f"Ваши активные заявки:\n{message}")
        else:
            await update.message.reply_text("У вас нет активных заявок.")
    except User.DoesNotExist:
        await update.message.reply_text("Ошибка: Профиль психолога не найден.")


async def view_completed_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_chat.id
    try:
        psychologist = User.objects.get(psychologist_profile__telegram_id=telegram_id)
        completed_sessions = psychologist.psychologist_profile.sessions.filter(status="COMPLETED")
        if completed_sessions.exists():
            message = "\n".join([f"Клиент: {s.client.email}, Отзыв: {s.review.text}" for s in completed_sessions])
            await update.message.reply_text(f"Ваши завершённые сессии:\n{message}")
        else:
            await update.message.reply_text("У вас нет завершённых сессий.")
    except User.DoesNotExist:
        await update.message.reply_text("Ошибка: Профиль психолога не найден.")


async def main() -> None:
    application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
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