from .models import PsychologistApplication, PsychologistProfile
from .emails import send_approval_email, send_rejection_email, send_documents_request_email
import logging

logger = logging.getLogger(__name__)

def process_psychologist_application(application_id):
    """Обрабатывает заявку на психолога."""
    try:
        application = PsychologistApplication.objects.get(id=application_id)

        if application.status == 'APPROVED':
            user = application.user
            user.is_psychologist = True
            user.save()

            # Создаем или обновляем профиль психолога
            profile, created = PsychologistProfile.objects.get_or_create(user=user)
            profile.is_verified = True
            profile.save()

            send_approval_email(application)

        elif application.status == 'REJECTED':
            send_rejection_email(application)

        elif application.status == 'DOCUMENTS_REQUESTED':
            send_documents_request_email(application)

    except PsychologistApplication.DoesNotExist:
        logger.error(f"Application with ID {application_id} not found.")
