# email.py
from django.core.mail import send_mail
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def send_email(subject, message, recipient_list):
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list)
        logger.info(f"Email sent to {', '.join(recipient_list)}")
    except Exception as e:
        logger.error(f"Error sending email to {', '.join(recipient_list)}: {str(e)}")


def send_approval_email(application):
    subject = "Your Psychologist Application Status"
    message = f"Dear {application.user.email},\n\nYour application has been approved.\n\nWelcome to our platform!"
    send_email(subject, message, [application.user.email])


def send_rejection_email(application):
    subject = "Your Psychologist Application Status"
    message = f"Dear {application.user.email},\n\nYour application has been rejected.\n\nReason: {application.previous_rejection_comment or 'Not provided.'}"
    send_email(subject, message, [application.user.email])


def send_documents_request_email(application):
    subject = "Documents Missing - Please Add Required Documents"
    message = (
        f"Dear {application.user.email},\n\n"
        "We noticed that your application is missing some documents. "
        "Please upload the required documents and resubmit your application.\n\nBest regards,\nAdmin"
    )
    send_email(subject, message, [application.user.email])