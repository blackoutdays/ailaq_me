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
    Обрабатывает событие сохранения пользователя.
    Создаёт заявку и профиль для психолога, если указано желание стать психологом.
    """
    if created and instance.wants_to_be_psychologist:
        # Создайте заявку, если её нет
        PsychologistApplication.objects.get_or_create(user=instance)
        # Создайте профиль, если его нет
        PsychologistProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender=PsychologistApplication)
def handle_application_status_change(sender, instance, **kwargs):
    """
    Обрабатывает изменение статуса заявки психолога.
    """
    if instance.status == 'APPROVED':
        user = instance.user
        user.is_psychologist = True
        user.save()
        # Создайте профиль, если его нет
        PsychologistProfile.objects.get_or_create(user=user)
        send_approval_email(instance)
    elif instance.status == 'REJECTED':
        send_rejection_email(instance)