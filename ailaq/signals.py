from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CustomUser, PsychologistApplication, PsychologistProfile, Session
from .emails import send_approval_email, send_rejection_email
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Session)
def update_requests_count(sender, instance, **kwargs):
    """
    Обновляет количество выполненных заявок у психолога, если сессия завершена.
    """
    if instance.status == 'COMPLETED':
        psychologist_profile = instance.psychologist
        psychologist_profile.requests_count = psychologist_profile.sessions.filter(status='COMPLETED').count()
        psychologist_profile.save()


@receiver(post_save, sender=CustomUser)
def handle_custom_user_post_save(sender, instance, created, **kwargs):
    """
    Создаёт заявку и профиль для психолога, если пользователь хочет быть психологом.
    """
    if created and instance.wants_to_be_psychologist:
        PsychologistApplication.objects.get_or_create(user=instance)
        PsychologistProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender=PsychologistApplication)
def handle_application_status_change(sender, instance, **kwargs):
    """
    Обрабатывает изменение статуса заявки психолога.
    """
    user = instance.user
    profile, _ = PsychologistProfile.objects.get_or_create(user=user)

    if instance.status == 'APPROVED':
        user.is_psychologist = True
        user.save()
        profile.is_verified = True
        profile.save()
        send_approval_email(instance)

    elif instance.status == 'REJECTED':
        user.is_psychologist = False
        user.save()
        profile.is_verified = False
        profile.save()
        send_rejection_email(instance)