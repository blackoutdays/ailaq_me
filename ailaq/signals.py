from django.db.models.signals import post_save
from django.dispatch import receiver
from .telegram_notify import send_telegram_message_sync
from .models import (
    CustomUser, PsychologistApplication, PsychologistProfile,
    PsychologistSessionRequest, QuickClientConsultationRequest
)
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
    user = instance.user
    profile = PsychologistProfile.objects.filter(user=user).first()

    if not profile:
        logger.warning(f"⚠️ Нет профиля для user_id={user.id} — должно быть создано при регистрации.")
        return

    if profile.application != instance:
        profile.application = instance
        profile.save(update_fields=["application"])

    if instance.status == 'APPROVED':
        user.is_psychologist = True
        user.save(update_fields=["is_psychologist"])
        profile.is_verified = True
        profile.save(update_fields=["is_verified"])
        message = "✅ Ваша заявка на роль психолога одобрена!"
    elif instance.status == 'REJECTED':
        user.is_psychologist = False
        user.save(update_fields=["is_psychologist"])
        profile.is_verified = False
        profile.save(update_fields=["is_verified"])
        message = "❌ Ваша заявка отклонена. Свяжитесь с поддержкой."
    else:
        return

    if user.telegram_id:
        try:
            send_telegram_message_sync(user.telegram_id, message)
        except Exception as e:
            logger.error(f"Ошибка при отправке в Telegram: {e}")
    else:
        logger.warning(f"🚫 Нет Telegram ID для user_id={user.id}")