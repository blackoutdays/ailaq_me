import logging
from datetime import datetime, timezone, timedelta
import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import nest_asyncio
import asyncio
nest_asyncio.apply()

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes
from ailaq.models import QuickClientConsultationRequest, PsychologistSessionRequest
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

from ailaq.models import Review, PsychologistProfile, ClientProfile
bot = telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN)
logger = logging.getLogger(__name__)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

User = get_user_model()
pending_reviews = {}

def build_status_update_keyboard(session_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\ud83d\udcde Связался", callback_data=f"contact_{session_id}"),
            InlineKeyboardButton("\u274c Не удалось связаться", callback_data=f"not_contacted_{session_id}")
        ],
        [
            InlineKeyboardButton("\u2705 Сессия прошла", callback_data=f"complete_{session_id}"),
            InlineKeyboardButton("\u274c Сессия не состоялась", callback_data=f"not_completed_{session_id}")
        ]
    ])

async def handle_status_update_callback(update, context):
    query = update.callback_query
    await query.answer()

    data = query.data
    telegram_id = query.from_user.id

    try:
        action, session_id = data.rsplit("_", 1)
        session_id = int(session_id)
        session = await sync_to_async(PsychologistSessionRequest.objects.get)(id=session_id)

        if session.psychologist.user.telegram_id != telegram_id:
            await query.edit_message_text("\u26d4\ufe0f Вы не можете изменить статус этой заявки.")
            return

        status_message = ""

        if action == "contact":
            session.status = "CONTACTED"
            status_message = "\ud83d\udcde Вы отметили, что связались с клиентом."
        elif action == "not_contacted":
            session.status = "NOT_CONTACTED"
            status_message = "\u274c Вы отметили, что не удалось связаться с клиентом."
        elif action == "complete":
            session.status = "COMPLETED"
            status_message = "\u2705 Сессия завершена. Спасибо! Клиенту будет предложено оставить отзыв."
        elif action == "not_completed":
            session.status = "NOT_COMPLETED"
            status_message = "\u274c Вы отметили, что сессия не состоялась."
        else:
            await query.edit_message_text("\u26a0\ufe0f Неизвестное действие.")
            return

        await sync_to_async(session.save)()
        await query.edit_message_text(status_message)

    except Exception as e:
        logging.error(f"Ошибка обработки статуса: {e}")
        await query.edit_message_text("\u2757 Ошибка обработки действия. Попробуйте позже.")

async def handle_accept_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("accept_session_"):
        return

    session_id = int(data.split("_")[-1])
    try:
        session = await sync_to_async(PsychologistSessionRequest.objects.select_related("psychologist__user").get)(id=session_id)

        if session.taken_by:
            await bot.edit_message_reply_markup(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                reply_markup=None
            )
            await bot.send_message(
                chat_id=query.from_user.id,
                text="\u26d4\ufe0f Эта заявка уже была принята другим психологом."
            )
            return

        session.taken_by = session.psychologist
        session.status = "CONTACTED"
        await sync_to_async(session.save)()

        new_text = query.message.text + "\n\n\ud83c\udf89 Заявка принята!"
        await bot.edit_message_text(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text=new_text,
            parse_mode="Markdown"
        )

        await bot.send_message(
            chat_id=query.from_user.id,
            text=(
                f"\ud83d\udce2 Вы приняли заявку!\n"
                f"\ud83d\udc64 Клиент: {session.client_name}\n"
                f"\ud83c\udf10 Telegram ID: {session.telegram_id}\n"
                f"\ud83d\udc81\u200d\u2642\ufe0f Тема: {session.topic}\n"
                f"\ud83d\udcac {session.comments or 'нет'}"
            ),
            reply_markup=build_status_update_keyboard(session.id)
        )

    except Exception as e:
        logging.error(f"\u274c Ошибка в callback accept_session: {e}")
        await query.message.reply_text("\u26a0\ufe0f Ошибка при принятии заявки")


def send_telegram_message_sync(telegram_id, text):
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": telegram_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения Telegram ID {telegram_id}: {e}")

def matches_age(birth_date, preferred_age):
    if not birth_date:
        return False
    age = (datetime.today().date() - birth_date).days // 365
    if preferred_age == 'AGE_18_25':
        return 18 <= age <= 25
    elif preferred_age == 'AGE_26_35':
        return 26 <= age <= 35
    elif preferred_age == 'AGE_36_50':
        return 36 <= age <= 50
    elif preferred_age == 'AGE_50_PLUS':
        return age > 50
    return False

async def get_psychologist_profile(telegram_id):
    return await sync_to_async(PsychologistProfile.objects.get)(user__telegram_id=telegram_id)

async def get_client_profile(telegram_id):
    return await sync_to_async(ClientProfile.objects.get)(user__telegram_id=telegram_id)

async def send_welcome_message(telegram_id):
    """Бот отправляет приветственное сообщение, когда получает Telegram ID"""
    await bot.send_message(telegram_id, "👋 Привет! Теперь я могу писать вам первым.")

async def link_telegram_user(update, context):
    telegram_id = update.effective_chat.id
    username = update.effective_chat.username or f"user_{telegram_id}"

    user = await sync_to_async(User.objects.filter(telegram_id=telegram_id).first)()

    if user:
        await update.message.reply_text("✅ Вы уже привязаны к системе.")
    else:
        await update.message.reply_text(
            "👤 Мы не нашли вас в системе.\n"
            "Если вы хотите пользоваться платформой как клиент или психолог, пожалуйста, зарегистрируйтесь: "
            f"{settings.FRONTEND_URL}/register"
        )

async def send_telegram_message(telegram_id, text):
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": telegram_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()

async def notify_psychologist_telegram(session_request):
    try:
        session_request = await sync_to_async(
            lambda: PsychologistSessionRequest.objects.select_related("psychologist__user").get(id=session_request.id)
        )()

        telegram_id = session_request.psychologist.user.telegram_id
        if not telegram_id:
            return
        text = (
            f"📥 Новая заявка от клиента!\n"
            f"👤 Имя: {session_request.client_name}\n"
            f"🧠 Тема: {session_request.topic}\n"
            f"📅 Возраст: {session_request.age}, Пол: {session_request.gender}\n"
            f"💬 Комментарий: {session_request.comments or 'нет'}"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Принять", callback_data=f"accept_session_{session_request.id}")]
        ])

        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            reply_markup=keyboard
        )

    except Exception as e:
        logging.error(f"❌ Ошибка уведомления психолога: {e}")

# Callback-хендлер для обработки "Принято"
async def handle_accept_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("accept_session_"):
        return

    session_id = int(data.split("_")[-1])
    try:
        session = await sync_to_async(PsychologistSessionRequest.objects.select_related("psychologist__user").get)(id=session_id)

        # Уже принято
        if session.taken_by:
            await bot.edit_message_reply_markup(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                reply_markup=None
            )
            await bot.send_message(
                chat_id=query.from_user.id,
                text="⛔️ Эта заявка уже была принята другим психологом."
            )
            return

        # Помечаем заявку
        session.taken_by = session.psychologist
        session.status = "CONTACTED"
        await sync_to_async(session.save)()

        # Скрыть кнопку и обновить текст
        new_text = query.message.text + "\n\n🎉 Заявка принята!"
        await bot.edit_message_text(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text=new_text,
            parse_mode="Markdown"
        )

        # Сенд данные клиента
        await bot.send_message(
            chat_id=query.from_user.id,
            text=(
                f"📢 Вы приняли заявку!"
                f"👤 Клиент: {session.client_name}"
                f"🌐 Telegram ID: {session.telegram_id}"
                f"🧠 Тема: {session.topic}"
                f"💬 {session.comments or 'нет'}"
            )
        )

    except Exception as e:
        logging.error(f"❌ Ошибка в callback accept_session: {e}")
        await query.message.reply_text("⚠️ Ошибка при принятии заявки")

async def process_session_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    psychologist_id = update.message.text
    client_id = update.effective_chat.id

    try:
        psychologist_profile = await get_psychologist_profile(int(psychologist_id))
        client_profile = await get_client_profile(client_id)

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

async def notify_client_to_leave_review(request_obj):
    if request_obj.telegram_id:
        try:
            text = (
                f"🙏 Пожалуйста, оцените вашу сессию с психологом "
                f"{request_obj.taken_by.user.get_full_name() if request_obj.taken_by else 'специалистом'}.\n"
                "Введите оценку от 1 до 5 и добавьте отзыв."
            )
            send_telegram_message(request_obj.telegram_id, text)
            request_obj.review_requested = True
            request_obj.save(update_fields=["review_requested"])
        except Exception as e:
            logging.error(f"Ошибка отправки отзыва: {e}")

async def process_review(update, context):
    telegram_id = update.effective_chat.id
    message_text = update.message.text.strip()

    try:
        request_obj = await sync_to_async(PsychologistSessionRequest.objects.filter)(
            telegram_id=telegram_id, status="COMPLETED", review__isnull=True
        )
        request_obj = await sync_to_async(request_obj.latest)("created_at")
        review_type = "session"
    except PsychologistSessionRequest.DoesNotExist:
        try:
            request_obj = await sync_to_async(QuickClientConsultationRequest.objects.filter)(
                telegram_id=telegram_id, status="COMPLETED", review__isnull=True
            )
            request_obj = await sync_to_async(request_obj.latest)("created_at")
            review_type = "consultation"
        except QuickClientConsultationRequest.DoesNotExist:
            await update.message.reply_text("😔 У вас нет завершённых сессий без отзыва.")
            return

    if message_text.isdigit() and 1 <= int(message_text) <= 5:
        pending_reviews[telegram_id] = {
            "rating": int(message_text),
            "request_obj": request_obj,
            "review_type": review_type,
        }
        name = request_obj.taken_by.user.get_full_name() if request_obj.taken_by else "психолог"
        await update.message.reply_text(f"📝 Введите текст отзыва для {name}.", parse_mode="Markdown")
    elif telegram_id in pending_reviews:
        data = pending_reviews[telegram_id]
        request_obj = data["request_obj"]
        rating = data["rating"]

        review = Review(
            rating=rating,
            text=message_text,
            client_name=request_obj.client_name,
            psychologist_name=request_obj.taken_by.user.get_full_name() if request_obj.taken_by else "психолог"
        )

        if data["review_type"] == "consultation":
            review.consultation_request = request_obj
        else:
            review.session_request = request_obj

        await sync_to_async(review.save)()
        del pending_reviews[telegram_id]
        await update.message.reply_text("✅ Спасибо! Ваш отзыв сохранён и передан психологу.")
    else:
        await update.message.reply_text("❗ Сначала введите оценку от 1 до 5.")

def notify_all_psychologists(consultation):
    from .views import bot  # убедитесь, что это работает
    psychologists = PsychologistProfile.objects.filter(
        user__telegram_id__isnull=False,
        application__status='APPROVED'
    ).select_related('user', 'application')

    logger.info(f"[TELEGRAM] Рассылка заявки {consultation.id} — психологов найдено: {psychologists.count()}")

    message = (
        f"🆕 Новая заявка на быструю консультацию\n"
        f"Язык: {consultation.psychologist_language}\n"
        f"Пол клиента: {consultation.gender}, возраст: {consultation.age}\n"
        f"Предпочтения: психолог {consultation.psychologist_gender}, "
        f"возраст: {consultation.preferred_psychologist_age}\n"
        f"Тема: {consultation.topic}\n"
        f"Комментарий: {consultation.comments or 'нет'}\n\n"
        f"Если вы подходите по критериям — отправьте /accept_{consultation.id}"
    )

    for p in psychologists:
        try:
            bot.send_message(chat_id=p.user.telegram_id, text=message)
        except Exception as e:
            logger.error(f"[TELEGRAM] Ошибка отправки психологу {p.user_id}: {e}")

async def accept_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text.strip()
    chat_id = update.effective_chat.id

    if not message.startswith("/accept_"):
        return

    try:
        consultation_id = int(message.split("_", 1)[1])
        consultation = await sync_to_async(QuickClientConsultationRequest.objects.get)(id=consultation_id)
        if consultation.taken_by:
            await update.message.reply_text("⛔ Заявка уже была принята другим психологом.")
            return

        psychologist = await get_psychologist_profile(chat_id)
        app = psychologist.application

        if not (
            app.status == 'APPROVED' and
            app.gender == consultation.psychologist_gender and
            app.communication_language == consultation.psychologist_language and
            matches_age(app.birth_date, consultation.preferred_psychologist_age)
        ):
            await update.message.reply_text("❌ Вы не подходите по критериям для этой заявки.")
            return

        client_profile = await get_client_profile(consultation.telegram_id)

        # Помечаем заявку как принятую этим психологом
        consultation.taken_by = psychologist
        await sync_to_async(consultation.save)()

        # Уведомляем психолога с данными клиента
        await send_telegram_message(
            psychologist.user.telegram_id,
            f"✅ Вы приняли заявку от клиента: {consultation.client_name}\n"
            f"📩 Telegram ID клиента: {consultation.telegram_id}\n"
            f"👤 Возраст: {consultation.age}, Пол: {consultation.gender}\n"
            f"🧠 Тема: {consultation.topic}\n"
            f"💬 Комментарий: {consultation.comments}"
        )

        await send_telegram_message(
            psychologist.user.telegram_id,
            f"✅ Вы приняли заявку от клиента: {consultation.client_name}\n"
            f"Telegram: {consultation.telegram_id}\n"
            f"Тема: {consultation.topic}"
        )
        await send_telegram_message(
            consultation.telegram_id,
            "🤝 Вашу заявку принял психолог. Сессия скоро начнётся."
        )
        # asyncio.get_event_loop().call_later(1800, lambda: asyncio.run(remind_review(consultation)))

    except Exception as e:
        await update.message.reply_text("⚠️ Ошибка принятия заявки. Возможно, она уже обработана.")
        logging.error(str(e))

    except QuickClientConsultationRequest.DoesNotExist:
        await update.message.reply_text("⚠️ Заявка не найдена.")
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await update.message.reply_text("⚠️ Ошибка принятия заявки.")

async def leave_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Введите текст отзыва после завершения сессии.")

async def remind_psychologists_about_pending_sessions():
    threshold = timezone.now() - timedelta(hours=2)
    pending = PsychologistSessionRequest.objects.filter(
        status="PENDING",
        created_at__lt=threshold,
        psychologist__user__telegram_id__isnull=False
    )

    for session in pending:
        await send_telegram_message(
            session.psychologist.user.telegram_id,
            f"⏰ Напоминание: вы получили заявку от {session.client_name}, но ещё не отметили статус.\n"
            f"Пожалуйста, подтвердите в Telegram:\n"
            f"/contact_{session.id} — связался\n"
            f"/complete_{session.id} — сессия прошла"
        )

async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_chat.id
    psychologist = await get_psychologist_profile(telegram_id)
    active = PsychologistSessionRequest.objects.filter(psychologist=psychologist, status="PENDING")
    if not active.exists():
        await update.message.reply_text("У вас нет активных заявок.")
        return
    text = "📋 Ваши активные заявки:\n"
    for req in active:
        text += f"ID: {req.id}, Клиент: {req.client_name}, Тема: {req.topic}\n"
    await update.message.reply_text(text)

async def status_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text.strip()
    try:
        req_id = int(message.split("_", 1)[1])
        request = PsychologistSessionRequest.objects.get(id=req_id)
        status_text = f"📄 Статус заявки #{request.id}: {request.status}\nКлиент: {request.client_name}\nТема: {request.topic}"
        await update.message.reply_text(status_text)
    except Exception:
        await update.message.reply_text("❗Ошибка получения статуса заявки.")

async def remind_clients_about_reviews():
    completed = PsychologistSessionRequest.objects.filter(status="COMPLETED", review_submitted=False)
    for session in completed:
        if session.telegram_id:
            try:
                await send_telegram_message(
                    session.telegram_id,
                    f"💬 Пожалуйста, оставьте отзыв о сессии с психологом {session.psychologist.user.get_full_name()}"
                )
                session.review_requested = True
                session.save(update_fields=["review_requested"])
            except Exception as e:
                logging.error(f"Ошибка при отправке напоминания клиенту: {e}")

async def main() -> None:
    application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", link_telegram_user))

    application.add_handler(MessageHandler(filters.Regex("Оставить отзыв"), leave_review))
    application.add_handler(MessageHandler(filters.Regex("^/accept_\\d+$"), accept_request))

    application.add_handler(CommandHandler("my_requests", my_requests))
    application.add_handler(CommandHandler("status", status_request))
    application.add_handler(MessageHandler(filters.Regex("^/status_\\d+$"), status_request))

    application.add_handler(CallbackQueryHandler(handle_accept_callback))
    application.add_handler(CallbackQueryHandler(handle_status_update_callback))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_review))
    await application.run_polling()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())