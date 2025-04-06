from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import (
    CustomUser, PsychologistApplication, PsychologistProfile,
    PsychologistSessionRequest, QuickClientConsultationRequest
)
from .telegram_bot import send_telegram_message
import logging
from asgiref.sync import async_to_sync

logger = logging.getLogger(__name__)

@receiver(post_save, sender=QuickClientConsultationRequest)
def update_consultation_count(sender, instance, **kwargs):
    if instance.status == 'COMPLETED' and instance.taken_by:
        instance.taken_by.update_requests_count()

@receiver(post_save, sender=PsychologistSessionRequest)
def update_session_count(sender, instance, **kwargs):
    if instance.status == 'COMPLETED' and instance.psychologist:
        instance.psychologist.update_requests_count()

@receiver(post_save, sender=CustomUser)
def handle_custom_user_post_save(sender, instance, created, **kwargs):
    """ Автоматически создаёт заявку и профиль для психолога, если пользователь хочет им быть """
    if created and instance.wants_to_be_psychologist:
        PsychologistApplication.objects.get_or_create(user=instance)
        PsychologistProfile.objects.get_or_create(user=instance)
        logger.info(f"🧠 Созданы заявка и профиль для психолога {instance.id}")

@receiver(post_save, sender=PsychologistApplication)
def handle_application_status_change(sender, instance, **kwargs):
    """ Обновляет статус пользователя и профиля, когда заявка психолога одобрена или отклонена """
    user = instance.user
    profile, _ = PsychologistProfile.objects.get_or_create(user=user)
    telegram_id = user.telegram_id

    if not telegram_id:
        logger.warning(f"🚫 Нет Telegram ID для user_id={user.id}, не удалось отправить уведомление.")
        return

    if instance.status == 'APPROVED':
        user.is_psychologist = True
        user.save(update_fields=["is_psychologist"])

        profile.is_verified = True
        profile.save(update_fields=["is_verified"])

        message = (
            "✅ Ваша заявка на роль психолога одобрена!\n\n"
            "Теперь вы можете принимать клиентов и быть видимым в системе после покупки 3 заявок и получения отзывов."
        )
        logger.info(f"✅ Заявка психолога одобрена: user_id={user.id}")
    elif instance.status == 'REJECTED':
        user.is_psychologist = False
        user.save(update_fields=["is_psychologist"])

        profile.is_verified = False
        profile.save(update_fields=["is_verified"])

        message = (
            "❌ К сожалению, ваша заявка на роль психолога была отклонена.\n"
            "Если хотите узнать причину — свяжитесь с поддержкой."
        )
        logger.info(f"❌ Заявка психолога отклонена: user_id={user.id}")
    else:
        return

    try:
        async_to_sync(send_telegram_message)(
            telegram_id=telegram_id,
            text=message
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке Telegram-сообщения: {e}")

@receiver(post_save, sender=CustomUser)
def create_application_and_profile_for_candidate(sender, instance, created, **kwargs):
    if instance.wants_to_be_psychologist:
        from ailaq.models import PsychologistApplication, PsychologistProfile
        app, _ = PsychologistApplication.objects.get_or_create(user=instance)
        PsychologistProfile.objects.get_or_create(user=instance, application=app)