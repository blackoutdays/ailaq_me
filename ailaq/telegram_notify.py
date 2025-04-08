# ailaq/telegram_notify.py
import logging
import requests
from telegram import Bot
from django.conf import settings
from asgiref.sync import sync_to_async

from ailaq.enums import LanguageEnum, ClientGenderEnum, ProblemEnum
from ailaq.models import PsychologistProfile

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
    approved_psychologists = await get_approved_psychologists()

    # Получаем язык клиента
    language = ', '.join([LanguageEnum[lang].value for lang in consultation.psychologist_language])

    # Получаем пол клиента
    gender = ', '.join([ClientGenderEnum[gen].value for gen in consultation.psychologist_gender])

    # Переводим тему с использованием ProblemEnum
    topic = ', '.join([ProblemEnum[item].value if item in ProblemEnum.__members__ else item for item in consultation.topic])

    # Проверяем возраст психолога
    preferred_min_age = getattr(consultation, 'preferred_psychologist_age_min', None)
    preferred_max_age = getattr(consultation, 'preferred_psychologist_age_max', None)
    age_info = f"Возраст психолога: от {preferred_min_age} до {preferred_max_age}" if preferred_min_age and preferred_max_age else "Возраст психолога не указан"

    message = (
        f"🆕 Новая заявка на быструю консультацию\n"
        f"Язык: {language}\n"
        f"Пол клиента: {gender}, возраст: {consultation.age}\n"
        f"Предпочтения: психолог {consultation.psychologist_gender}, {age_info}\n"
        f"Тема: {topic}\n"
        f"Комментарий: {consultation.comments or 'нет'}\n\n"
        f"Если вы подходите по критериям — отправьте /accept_{consultation.id}"
    )

    for p in approved_psychologists:
        try:
            dynamic_bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
            await dynamic_bot.send_message(chat_id=p.user.telegram_id, text=message)
            logging.info(f"Уведомление отправлено психологу с ID {p.user.telegram_id}")
        except Exception as e:
            logging.error(f"[TELEGRAM] Ошибка отправки психологу {p.user_id}: {e}")

def notify_client_about_direct_request(telegram_id, psychologist_name):
    text = (
        f"📩 Ваша заявка отправлена психологу *{psychologist_name}*.\n"
        "Он получит уведомление и скоро свяжется с вами в Telegram."
    )
    send_telegram_message_sync(telegram_id, text)

def notify_client_about_request_sent(telegram_id):
    text = (
        "✅ Ваша заявка отправлена психологам!\n"
        "Скоро один из них примет её и свяжется с вами в Telegram. Ожидайте сообщения."
    )
    send_telegram_message_sync(telegram_id, text)