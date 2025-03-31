from django.contrib import admin, messages
from django.utils.html import format_html
from .models import PsychologistApplication, PsychologistProfile, ClientProfile, CustomUser, PsychologistFAQ
from .services import process_psychologist_application, send_documents_request_email
import logging
logger = logging.getLogger(__name__)

# FAQ психолога: вопрос/ответ
class PsychologistFAQInline(admin.TabularInline):
    model = PsychologistFAQ
    extra = 1

# Админка для ClientProfile
@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'telegram_id', 'get_user_email']
    search_fields = ['user__email', 'user__telegram_id']  # Поиск по email и Telegram ID

    @admin.display(description='Telegram ID')
    def telegram_id(self, obj):
        return obj.user.telegram_id

    @admin.display(description='Email')
    def get_user_email(self, obj):
        return obj.user.email

# Админка для CustomUser
@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ['email', 'is_psychologist']

# Админка для заявок на психолога
@admin.register(PsychologistApplication)
class PsychologistApplicationAdmin(admin.ModelAdmin):
    actions = ['approve_application', 'reject_application', 'request_documents']

    def approve_application(self, request, queryset):
        for application in queryset.filter(status='PENDING'):
            try:
                application.status = 'APPROVED'
                application.save()
                PsychologistProfile.objects.get_or_create(user=application.user)  # Создаем профиль, если его нет
                self.message_user(request, f"Application ID {application.id} approved.", level=messages.SUCCESS)
            except Exception as e:
                logger.error(f"Error approving application {application.id}: {str(e)}")
                self.message_user(request, f"Error approving application {application.id}.", level=messages.ERROR)

    def reject_application(self, request, queryset):
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

    @admin.display(description='Documents')
    def view_documents(self, obj):
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

# Админка для профиля психолога
@admin.register(PsychologistProfile)
class PsychologistProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'telegram_id', 'is_verified_display', 'is_in_catalog', 'requests_count', 'get_average_rating']
    search_fields = ['user__email', 'user__telegram_id']  # Поиск по Telegram ID и email
    list_filter = ['is_in_catalog']

    @admin.display(description='Telegram ID')
    def telegram_id(self, obj):
        return obj.user.telegram_id

    @admin.display(boolean=True, description='Verified')
    def is_verified_display(self, obj):
        return obj.is_verified

    @admin.display(description='Average Rating')
    def get_average_rating(self, obj):
        return obj.get_average_rating()