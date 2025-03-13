import logging
from .tasks import send_email_async

logger = logging.getLogger(__name__)

def send_email(subject, message, recipient_list):
    """
    Запускает отправку email через Celery.
    """
    if not recipient_list:
        logger.warning("⚠️ send_email called with empty recipient_list.")
        return
    try:
        send_email_async.delay(subject, message, recipient_list)
        logger.info(f" send_email scheduled Celery task for {', '.join(recipient_list)}")
    except Exception as e:
        logger.error(f" Failed to schedule send_email_async: {str(e)}")

def send_approval_email(application):
    """ Отправляет email об одобрении заявки психолога. """
    subject = "Your Psychologist Application Status"
    message = (
        f"Dear {application.user.email},\n\n"
        "Your application has been approved.\n\n"
        "Welcome to our platform!"
    )
    send_email(subject, message, [application.user.email])

def send_rejection_email(application):
    """ Отправляет email об отклонении заявки психолога. """
    subject = "Your Psychologist Application Status"
    message = (
        f"Dear {application.user.email},\n\n"
        "Your application has been rejected.\n\n"
        f"Reason: {application.previous_rejection_comment or 'Not provided.'}"
    )
    send_email(subject, message, [application.user.email])

def send_documents_request_email(application):
    """ Отправляет email с просьбой загрузить недостающие документы. """
    subject = "Documents Missing - Please Add Required Documents"
    message = (
        f"Dear {application.user.email},\n\n"
        "We noticed that your application is missing some documents. "
        "Please upload the required documents and resubmit your application.\n\n"
        "Best regards,\nAdmin"
    )
    send_email(subject, message, [application.user.email])
