from asgiref.sync import async_to_sync

from .models import PsychologistApplication, PsychologistLevel, QuickClientConsultationRequest
from datetime import date
from celery import shared_task
import logging
from django.core.mail import send_mail
from django.conf import settings

from .telegram_bot import notify_all_psychologists

logger = logging.getLogger(__name__)


@shared_task
def notify_all_psychologists_task(consultation_id):
    consultation = QuickClientConsultationRequest.objects.get(id=consultation_id)
    async_to_sync(notify_all_psychologists)(consultation)


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 60})
def send_email_async(self, subject, message, recipient_list, html_message=None):
    """Асинхронная отправка email через Celery с поддержкой HTML"""
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            fail_silently=False,
            html_message=html_message
        )
        logger.info(f"📩 Email sent to {', '.join(recipient_list)} (async)")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки email: {str(e)}")
        raise self.retry(exc=e)

@shared_task
def check_psychologist_levels():
    """ Проверка уровней психологов на основе количества просроченных заявок. """
    psychologists = PsychologistApplication.objects.filter(status="APPROVED")

    for application in psychologists:
        expired_count = PsychologistApplication.objects.filter(user=application.user, status='EXPIRED').count()

        try:
            if expired_count > 0:
                new_level = PsychologistLevel.objects.get(name='LEVEL_1')
            else:
                new_level = PsychologistLevel.objects.get(name='LEVEL_2')

            profile = application.user.psychologist_profile
            profile.level = new_level
            profile.save()
            logger.info(f"🔄 Уровень обновлен для {application.user.email} -> {new_level.name}")
        except PsychologistLevel.DoesNotExist:
            logger.error(f"⚠️ Уровень для психолога {application.user.email} не найден!")

@shared_task
def check_and_update_applications():
    """ Проверка и обновление просроченных заявок. """
    applications = PsychologistApplication.objects.filter(status='PENDING')

    for application in applications:
        if application.expiry_date and application.expiry_date < date.today():
            application.status = 'EXPIRED'
            application.save()
            logger.info(f"🚨 Заявка {application.id} пользователя {application.user.email} помечена как просроченная.")