from django.core.mail import send_mail
import logging

logger = logging.getLogger(__name__)

# Функции для отправки email уведомлений
def send_approval_email(application):
    subject = "Your Psychologist Application Status"
    message = f"Dear {application.user.username},\n\nYour application has been approved.\n\nWelcome to our platform!"
    recipient_list = [application.user.email]
    try:
        send_mail(subject, message, 'aruka.larksss@gmail.com', recipient_list)
        logger.info(f"Approval email sent to {application.user.email}")
    except Exception as e:
        logger.error(f"Error sending email to {application.user.email}: {str(e)}")

def send_rejection_email(application):
    subject = "Your Psychologist Application Status"
    message = f"Dear {application.user.username},\n\nYour application has been rejected.\n\nReason: {application.previous_rejection_comment}"
    recipient_list = [application.user.email]
    try:
        send_mail(subject, message, 'aruka.larksss@gmail.com', recipient_list)
        logger.info(f"Rejection email sent to {application.user.email}")
    except Exception as e:
        logger.error(f"Error sending email to {application.user.email}: {str(e)}")

def send_documents_request_email(application):
    # Проверка наличия необходимых документов
    if not application.documents:
        subject = "Documents Missing - Please Add Required Documents"
        message = f"Dear {application.user.username},\n\nWe noticed that your application is missing some documents. Please upload the required documents and resubmit your application.\n\nBest regards,\nAdmin"
        recipient_list = [application.user.email]
        send_mail(subject, message, 'aruka.larksss@gmail.com', recipient_list)
