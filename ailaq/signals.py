from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CustomUser, PsychologistApplication, PsychologistProfile, PsychologistSessionRequest, \
    QuickClientConsultationRequest
from .emails import send_approval_email, send_rejection_email
import logging

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
    """
    Автоматически создаёт заявку и профиль для психолога, если пользователь хочет им быть.
    """
    if created and instance.wants_to_be_psychologist:
        PsychologistApplication.objects.get_or_create(user=instance)
        PsychologistProfile.objects.get_or_create(user=instance)
        logger.info(f"🧠 Созданы заявка и профиль для психолога {instance.id}")

@receiver(post_save, sender=PsychologistApplication)
def handle_application_status_change(sender, instance, **kwargs):
    """
    Обновляет статус пользователя и профиля, когда заявка психолога одобрена или отклонена.
    """
    user = instance.user
    profile, _ = PsychologistProfile.objects.get_or_create(user=user)

    if instance.status == 'APPROVED':
        user.is_psychologist = True
        user.save(update_fields=["is_psychologist"])
        profile.is_verified = True
        profile.save(update_fields=["is_verified"])
        send_approval_email(instance)
        logger.info(f"✅ Заявка психолога одобрена: user_id={user.id}")
    elif instance.status == 'REJECTED':
        user.is_psychologist = False
        user.save(update_fields=["is_psychologist"])
        profile.is_verified = False
        profile.save(update_fields=["is_verified"])
        send_rejection_email(instance)
        logger.info(f"❌ Заявка психолога отклонена: user_id={user.id}")