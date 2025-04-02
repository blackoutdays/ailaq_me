# ailaq/telegram_notify.py
import logging

from telegram import Bot
from django.conf import settings
from asgiref.sync import sync_to_async

from ailaq.models import PsychologistProfile

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

async def get_approved_psychologists():
    psychologists = await sync_to_async(
        lambda: list(PsychologistProfile.objects.filter(user__telegram_id__isnull=False).select_related('user', 'application'))
    )()

    approved_psychologists = [
        p for p in psychologists if p.application and p.application.status == 'APPROVED'
    ]
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
        except Exception as e:
            print(f"[TELEGRAM] Ошибка отправки психологу {p.user_id}: {e}")