from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CustomUser, PsychologistApplication, PsychologistProfile
from .emails import send_approval_email, send_rejection_email
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=CustomUser)
def create_psychologist_profile(sender, instance, created, **kwargs):
    if created and instance.wants_to_be_psychologist:
        PsychologistApplication.objects.get_or_create(user=instance)
        PsychologistProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender=PsychologistApplication)
def handle_application_status_change(sender, instance, **kwargs):
    if instance.status == 'APPROVED':
        user = instance.user
        user.is_psychologist = True
        user.save()
        PsychologistProfile.objects.get_or_create(user=user)
        send_approval_email(instance)
    elif instance.status == 'REJECTED':
        send_rejection_email(instance)


@receiver(post_save, sender=CustomUser)
def create_psychologist_profile(sender, instance, created, **kwargs):
    """
    Создаёт профиль и заявку, если пользователь указал желание стать психологом.
    """
    if created and instance.wants_to_be_psychologist:
        PsychologistApplication.objects.get_or_create(user=instance)
        PsychologistProfile.objects.get_or_create(user=instance)
