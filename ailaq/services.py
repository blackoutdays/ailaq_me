# ailaq/services.py
from .models import PsychologistApplication, PsychologistProfile, CustomUser
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

def handle_missing_documents(application_id):
    """
    Обрабатывает запрос на предоставление недостающих документов.
    """
    try:
        application = PsychologistApplication.objects.get(id=application_id)
        if not application.documents_requested:
            application.documents_requested = True
            application.status = 'DOCUMENTS_REQUESTED'
            application.save()
            send_documents_request_email(application)
            logger.info(f"Document request email sent for application ID {application_id}.")
    except PsychologistApplication.DoesNotExist:
        logger.error(f"Application with ID {application_id} not found.")

def link_telegram_user(request):
    # Получаем пользователя
    user = CustomUser.objects.get(telegram_id=request.data['telegram_id'])

    # Генерация кода, если он отсутствует
    if not user.verification_code:
        user.verification_code = CustomUser.objects.generate_unique_verification_code()

    # Сохраняем пользователя с установленным verification_code
    user.save()
    return user