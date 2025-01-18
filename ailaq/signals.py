# ailaq/signals.py
from django.core.mail import send_mail
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CustomUser, PsychologistProfile, PsychologistApplication, PsychologistLevel
from .emails import send_approval_email, send_rejection_email
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=CustomUser)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if instance.is_psychologist:
        if created:
            # Create profile and application for psychologists
            PsychologistProfile.objects.get_or_create(user=instance)
            PsychologistApplication.objects.create(user=instance)
        else:
            # Update profile if it exists
            if not hasattr(instance, 'psychologist_profile'):
                PsychologistProfile.objects.create(user=instance)
            else:
                instance.psychologist_profile.save()

# Email sending logic
def send_approval_email(application):
    subject = "Your Psychologist Application Status"
    message = f"Dear {application.user.username},\n\nYour application has been approved.\n\nWelcome to our platform!"
    recipient_list = [application.user.email]
    try:
        send_mail(subject, message, 'aruka.larksss@gmail.com', recipient_list)
        logger.info(f"Approval email sent to {application.user.email}")
    except Exception as e:
        logger.error(f"Error sending email to {application.user.email}: {str(e)}")

# Handle psychologist application approval/rejection
def process_psychologist_application(application_id):
    application = PsychologistApplication.objects.get(id=application_id)

    if application.status == 'APPROVED':
        # Create or update profile and send approval email
        user = application.user
        psychologist_level = PsychologistLevel.objects.get(name='1')
        psychologist_profile, created = PsychologistProfile.objects.get_or_create(user=user, level=psychologist_level)
        user.role = 'PSYCHOLOGIST'
        user.save()
        send_approval_email(application)

    elif application.status == 'REJECTED':
        send_rejection_email(application)

# Создание профиля и заявки на психолога при создании пользователя
@receiver(post_save, sender=CustomUser)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        if instance.is_psychologist:
            # Создаем профиль психолога, если это психолог
            PsychologistProfile.objects.create(user=instance)

            # Создаем заявку на психолога
            PsychologistApplication.objects.create(user=instance)

# Сохранение профиля психолога, если он уже существует
@receiver(post_save, sender=CustomUser)
def save_user_profile(sender, instance, **kwargs):
    if instance.is_psychologist:
        # Если психолог, сохраняем или создаем профиль
        if not hasattr(instance, 'psychologist_profile'):
            PsychologistProfile.objects.create(user=instance)
        else:
            instance.psychologist_profile.save()