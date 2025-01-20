from django.contrib import admin, messages
from django.utils.html import format_html
from .models import PsychologistApplication, PsychologistProfile, ClientProfile, CustomUser, PsychologistFAQ
from .services import process_psychologist_application, send_documents_request_email

import logging
logger = logging.getLogger(__name__)


# faq психолога вопрос/ы-ответ/ы
class PsychologistFAQInline(admin.TabularInline):
    model = PsychologistFAQ
    extra = 1  # Количество пустых строк для добавления новых объектов


@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ['email', 'whatsapp_id', 'telegram_id']


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ['email', 'is_psychologist']


# форма заявки на психолога, отображение в админке
@admin.register(PsychologistApplication)
class PsychologistApplicationAdmin(admin.ModelAdmin):
    actions = ['approve_application', 'reject_application', 'request_documents']

    def approve_application(self, request, queryset):
        for application in queryset.filter(status='PENDING'):
            try:
                application.status = 'APPROVED'
                application.save()

                # Автоматически создаёт профиль, если он отсутствует
                PsychologistProfile.objects.get_or_create(user=application.user)

                self.message_user(
                    request,
                    f"Application ID {application.id} approved.",
                    level=messages.SUCCESS
                )
            except Exception as e:
                logger.error(f"Error approving application {application.id}: {str(e)}")
                self.message_user(request, f"Error approving application {application.id}.", level=messages.ERROR)

    def reject_application(self, request, queryset):
        """Отклонение заявок администрацией."""
        for application in queryset.filter(status='PENDING'):
            try:
                application.status = 'REJECTED'
                application.save()
                process_psychologist_application(application.id)
                self.message_user(request, f"Application ID {application.id} rejected.")
            except Exception as e:
                logger.error(f"Error rejecting application {application.id}: {str(e)}")
                self.message_user(request, f"Error rejecting application {application.id}.", level=messages.ERROR)

    def request_documents(self, request, queryset):
        """Запрос документов для выбранных заявок."""
        for application in queryset.filter(status='PENDING', documents_requested=False):
            try:
                application.documents_requested = True
                application.status = 'DOCUMENTS_REQUESTED'
                application.save()
                send_documents_request_email(application)
                self.message_user(request, f"Document request sent for application ID {application.id}.")
            except Exception as e:
                logger.error(f"Error requesting documents for application ID {application.id}: {str(e)}")
                self.message_user(request, f"Error requesting documents for application ID {application.id}.",
                                  level=messages.ERROR)

    def view_documents(self, obj):
        """Отображение ссылок на документы."""
        passport_link = (
            f'<a href="{obj.passport_document.url}" target="_blank">Passport Document</a>'
            if obj.passport_document and hasattr(obj.passport_document, 'url')
            else 'No Passport Document'
        )
        office_photo_link = (
            f'<a href="{obj.office_photo.url}" target="_blank">Office Photo</a>'
            if obj.office_photo and hasattr(obj.office_photo, 'url')
            else 'No Office Photo'
        )
        return format_html(f"{passport_link} | {office_photo_link}")

    view_documents.short_description = "Documents"


#профиль психолога
@admin.register(PsychologistProfile)
class PsychologistProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_verified_display', 'is_in_catalog', 'requests_count', 'get_average_rating']
    search_fields = ['user__email']
    list_filter = ['is_in_catalog']

    def is_verified_display(self, obj):
        return obj.is_verified
    is_verified_display.boolean = True  # Отображать как галочку
    is_verified_display.short_description = "Verified"

    def get_average_rating(self, obj):
        return obj.get_average_rating()
    get_average_rating.short_description = "Average Rating"