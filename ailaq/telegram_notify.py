# ailaq/telegram_notify.py
import logging
import requests
import logging
from telegram import Bot
from django.conf import settings
from asgiref.sync import sync_to_async
from ailaq.models import PsychologistProfile

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

logger = logging.getLogger(__name__)

def send_telegram_message_sync(telegram_id, text):
    """Синхронная обертка для использования в сигнале (без async/await)"""
    try:
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": telegram_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Ошибка при отправке Telegram-сообщения: {e}")

async def get_approved_psychologists():
    psychologists = await sync_to_async(
        lambda: list(PsychologistProfile.objects.filter(user__telegram_id__isnull=False).select_related('user', 'application'))
    )()

    logging.info(f"Найдено психологов с Telegram ID: {len(psychologists)}")

    approved_psychologists = [
        p for p in psychologists if p.application and p.application.status == 'APPROVED'
    ]

    logging.info(f"Одобренных психологов: {len(approved_psychologists)}")

    return approved_psychologists

async def notify_all_psychologists(consultation):
    # Получаем одобренных психологов
    approved_psychologists = await get_approved_psychologists()

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

    for p in approved_psychologists:
        try:
            await bot.send_message(chat_id=p.user.telegram_id, text=message)
            logging.info(f"Уведомление отправлено психологу с ID {p.user.telegram_id}")
        except Exception as e:
            logging.error(f"[TELEGRAM] Ошибка отправки психологу {p.user_id}: {e}")