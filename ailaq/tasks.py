#tasks.py
from . import models
from .models import PsychologistApplication, PsychologistLevel
from datetime import date
from celery import shared_task
import logging
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)

@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 60})
def send_email_async(self, subject, message, recipient_list):
    """
    Асинхронная отправка email через Celery.
    """
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list)
        logger.info(f" Email sent to {', '.join(recipient_list)} (async)")
    except Exception as e:
        logger.error(f" Error sending async email to {', '.join(recipient_list)}: {str(e)}")
        raise self.retry(exc=e)

def check_psychologist_level(user):
    """ Проверка уровня психолога на основе количества просроченных заявок. """
    profile = user.psychologist_profile
    expired_count = PsychologistApplication.objects.filter(
        user=user, status='EXPIRED'
    ).count()

    if expired_count > 0:
        new_level = PsychologistLevel.objects.get(name='LEVEL_1')
    else:
        new_level = PsychologistLevel.objects.get(name='LEVEL_2')

    profile.level = new_level
    profile.save()

def check_and_update_applications():
    """ Проверка просроченных заявок. """
    expiry_date = models.DateField(null=True, blank=True)
    applications = PsychologistApplication.objects.filter(status='PENDING')
    for application in applications:
        if application.expiry_date and application.expiry_date < date.today():
            application.status = 'EXPIRED'
            application.save()