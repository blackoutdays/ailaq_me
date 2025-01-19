from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models
from django.contrib.auth.models import BaseUserManager
from ailaq.emails import send_approval_email, send_rejection_email
from django.db.models import Avg
from django.conf import settings
from django.utils.timezone import now

import logging
logger = logging.getLogger(__name__)

class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        if user.is_psychologist:
            # Если админ/код при создании сразу ставит is_psychologist=True
            PsychologistProfile.objects.create(user=user)
        else:
            # Если просто клиент
            ClientProfile.objects.create(email=user)

        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractBaseUser):
    email = models.EmailField(unique=True)
    is_psychologist = models.BooleanField(default=False)
    wants_to_be_psychologist = models.BooleanField(default=False)  # Ставится в True, если «кандидат»

    # Поля, нужные для админки
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)

    # Виртуальная валюта / баланс
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email

    @property
    def role(self):
        if self.is_psychologist:
            return 'PSYCHOLOGIST'
        return 'CLIENT'

    def has_perm(self, perm, obj=None):
        """Обеспечивает проверку наличия конкретного разрешения."""
        return self.is_superuser

    def has_module_perms(self, app_label):
        """Обеспечивает доступ к приложениям."""
        return self.is_superuser


class ClientProfile(models.Model):
    email = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    whatsapp_id = models.CharField(max_length=20, null=True, blank=True)
    telegram_id = models.BigIntegerField(null=True, blank=True)

    def __str__(self):
        return f"ClientProfile for {self.email.email}"


class PsychologistLevel(models.Model):
    name = models.CharField(max_length=50)
    can_see_catalog = models.BooleanField(default=False)
    can_see_quick_requests = models.BooleanField(default=False)
    can_accept_requests = models.BooleanField(default=False)
    can_edit_profile = models.BooleanField(default=False)
    can_change_block_status = models.BooleanField(default=False)
    duration_days = models.IntegerField(default=0)

    def __str__(self):
        return self.name


class EducationDocument(models.Model):
    psychologist_application = models.ForeignKey(
        'PsychologistApplication',
        related_name='education_documents',
        on_delete=models.CASCADE
    )
    document = models.FileField(upload_to='education_documents/')


class PsychologistApplication(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)

    # Личная информация
    first_name_ru = models.CharField(max_length=50, null=True, blank=True)
    first_name_en = models.CharField(max_length=50, null=True, blank=True)
    first_name_kz = models.CharField(max_length=50, null=True, blank=True)

    last_name_ru = models.CharField(max_length=50, null=True, blank=True)
    last_name_en = models.CharField(max_length=50, null=True, blank=True)
    last_name_kz = models.CharField(max_length=50, null=True, blank=True)

    middle_name_ru = models.CharField(max_length=50, null=True, blank=True)
    middle_name_en = models.CharField(max_length=50, null=True, blank=True)
    middle_name_kz = models.CharField(max_length=50, null=True, blank=True)

    age = models.IntegerField(null=True, blank=True)

    language_choices = [
        ('RU', 'Russian'),
        ('EN', 'English'),
        ('KZ', 'Kazakh'),
    ]
    communication_language = models.CharField(max_length=2, choices=language_choices, null=True, blank=True)

    telegram_id = models.CharField(max_length=100, null=True, blank=True)  # Ник или айди в Telegram
    city = models.CharField(max_length=100, null=True, blank=True)  # Город
    email = models.EmailField(null=True, blank=True)  # Электронный адрес

    # Пол
    gender_choices = [
        ('MALE', 'Male'),
        ('FEMALE', 'Female'),
        ('OTHER', 'Other'),
    ]
    gender = models.CharField(max_length=6, choices=gender_choices, null=True, blank=True)

    #обо мне
    about_me_ru = models.TextField(null=True, blank=True)
    about_me_en = models.TextField(null=True, blank=True)
    about_me_kz = models.TextField(null=True, blank=True)

    # Каталоговое описание психолога (будет отображаться в каталоге)
    catalog_description_ru = models.TextField(null=True, blank=True)
    catalog_description_en = models.TextField(null=True, blank=True)
    catalog_description_kz = models.TextField(null=True, blank=True)

    # Чем сможете помочь (текстовое поле)
    help_text_ru = models.TextField(null=True, blank=True)
    help_text_en = models.TextField(null=True, blank=True)
    help_text_kz = models.TextField(null=True, blank=True)

    # Видео презентация (ссылка для админа для проверки)
    video_presentation_link = models.URLField(null=True, blank=True)

    # Квалификация (специализация)
    qualification = models.CharField(max_length=100, null=True, blank=True)  # Например "Психолог"
    # С кем работаете? (Список)
    works_with_choices = [
        ('ADULTS', 'Взрослые'),
        ('TEENAGERS', 'Подростки'),
        ('CHILDREN', 'Дети'),
        ('FAMILY', 'Семья'),
    ]
    works_with = models.CharField(max_length=50, choices=works_with_choices, null=True, blank=True)

    # С какими проблемами работаете? (Список)
    problems_worked_with = models.TextField(null=True, blank=True)  # Список проблем, например "Тревожность, депрессия"

    # Методы работы (список)
    work_methods = models.TextField(null=True, blank=True)

    # Дата начала практики
    practice_start_date = models.DateField(null=True, blank=True)
    # Научная степень
    academic_degree = models.CharField(max_length=100, null=True, blank=True)

    # Направления для психологов, детских психологов, коучей (списки)
    psychologist_directions = models.TextField(null=True, blank=True)
    child_psychologist_directions = models.TextField(null=True, blank=True)
    coach_directions = models.TextField(null=True, blank=True)

    # Дополнительная специализация
    additional_specialization = models.TextField(null=True, blank=True)
    # Особенности работы (онлайн/офлайн)
    work_features = models.TextField(null=True, blank=True)

    education = models.TextField(null=True, blank=True)
    education_files = models.FileField(upload_to='education_documents/', null=True, blank=True)

    # Заявки и рейтинги
    is_verified = models.BooleanField(default=False)  # Подтвержден ли психолог
    is_in_catalog = models.BooleanField(default=False)  # В каталоге

    purchased_applications = models.IntegerField(default=0)  # Количество купленных заявок
    expired_applications = models.IntegerField(default=0)  # Количество просроченных заявок
    active_applications = models.IntegerField(default=0)  # Количество активных заявок
    paid_applications = models.IntegerField(default=0)  # Количество оплаченных заявок
    unpaid_applications = models.IntegerField(default=0)  # Количество неоплаченных заявок

    # Рейтинг системы
    rating_system = models.FloatField(default=0.0)  # Внешний рейтинг, высчитываемый на платформе
    internal_rating = models.FloatField(default=0.0)  # Внутренний рейтинг

    # Финансовая информация и стоимость услуг
    session_duration = models.IntegerField(null=True, blank=True)  # Длительность сессии в минутах
    session_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # Стоимость в тенге
    session_discount = models.DecimalField(max_digits=10, decimal_places=2, null=True,
                                           blank=True)  # Скидка на сессию в тенге

    online_session_duration = models.IntegerField(null=True, blank=True)  # Длительность онлайн сессии в минутах
    online_session_price = models.DecimalField(max_digits=10, decimal_places=2, null=True,
                                               blank=True)  # Стоимость онлайн сессии в тенге
    online_session_discount = models.DecimalField(max_digits=10, decimal_places=2, null=True,
                                                  blank=True)  # Скидка на онлайн сессию в тенге

    couple_session_duration = models.IntegerField(null=True, blank=True)  # Длительность парной личной сессии
    couple_session_price = models.DecimalField(max_digits=10, decimal_places=2, null=True,
                                               blank=True)  # Стоимость парной личной сессии
    couple_session_discount = models.DecimalField(max_digits=10, decimal_places=2, null=True,
                                                  blank=True)  # Скидка на парную личную сессию

    couple_online_session_duration = models.IntegerField(null=True, blank=True)  # Длительность парной онлайн сессии
    couple_online_session_price = models.DecimalField(max_digits=10, decimal_places=2, null=True,
                                                      blank=True)  # Стоимость парной онлайн сессии
    couple_online_session_discount = models.DecimalField(max_digits=10, decimal_places=2, null=True,
                                                         blank=True)  # Скидка на парную онлайн сессию

    office_address = models.TextField(null=True, blank=True)  # Адрес офиса
    office_photo = models.ImageField(upload_to='office_photos/', null=True, blank=True)  # Фото офиса
    passport_document = models.FileField(upload_to='documents/', null=True, blank=True)  # Паспорт

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('DOCUMENTS_REQUESTED', 'Documents Requested'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    documents_requested = models.BooleanField(default=False)

    # валидации перед сохранением
    def save(self, *args, **kwargs):
        if self.status not in ['PENDING', 'APPROVED', 'REJECTED', 'DOCUMENTS_REQUESTED']:
            raise ValueError("Invalid status value.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"PsychologistApplication for {self.user.email}"


class PsychologistProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="psychologist_profile", unique=True)
    application = models.OneToOneField(
        PsychologistApplication,
        on_delete=models.CASCADE,
        related_name='profile',
        null=True,  # или установите значение по умолчанию
        blank=True
    )

    is_in_catalog = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    requests_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"PsychologistProfile for {self.user.email}"

    def can_be_in_catalog(self):
        """
        Проверяет, может ли психолог быть включён в каталог.
        Условия:
        - Психолог верифицирован.
        - Количество заявок >= порога из настроек.
        """
        required_requests = settings.DEFAULT_CATALOG_REQUESTS_THRESHOLD
        return self.is_verified and self.requests_count >= required_requests

    def update_catalog_status(self):
        """
        Обновляет статус `is_in_catalog` на основе метода `can_be_in_catalog`.
        """
        self.is_in_catalog = self.can_be_in_catalog()
        self.save()

    @staticmethod
    def process_psychologist_application(application_id):
        """
        Обработка заявки психолога.
        """

        try:
            application = PsychologistApplication.objects.get(id=application_id)

            if application.status == 'APPROVED':
                user = application.user
                user.is_psychologist = True
                user.save()

                profile, created = PsychologistProfile.objects.get_or_create(user=user)
                profile.is_verified = True
                profile.save()

                send_approval_email(application)

            elif application.status == 'REJECTED':
                send_rejection_email(application)
        except PsychologistApplication.DoesNotExist:
            logger.error(f"Application with ID {application_id} not found.")

    def get_average_rating(self):
        """
        Рассчитывает средний рейтинг психолога на основе завершённых сессий.
        Возвращает 0.0, если нет завершённых сессий или отзывов.
        """
        sessions_qs = self.sessions.filter(status='COMPLETED')
        reviews_qs = Review.objects.filter(session__in=sessions_qs)
        average_rating = reviews_qs.aggregate(avg_rating=Avg('rating'))['avg_rating'] or 0.0
        return round(average_rating, 1)

def get_default_cost():
    return settings.REQUEST_COST

class PurchasedRequest(models.Model):
    psychologist = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=get_default_cost
    )
    created_at = models.DateTimeField(default=now)

    def __str__(self):
        return f"Purchase #{self.id} by {self.psychologist.email} on {self.created_at}"


class Session(models.Model):
    psychologist = models.ForeignKey(
        PsychologistProfile,
        on_delete=models.CASCADE,
        related_name='sessions'
    )
    client = models.ForeignKey(
        ClientProfile,
        on_delete=models.CASCADE,
        related_name='sessions'
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    status_choices = [
        ('SCHEDULED', 'Scheduled'),
        ('COMPLETED', 'Completed'),
        ('CANCELED', 'Canceled'),
    ]
    status = models.CharField(max_length=10, choices=status_choices, default='SCHEDULED')


class Review(models.Model):
    session = models.OneToOneField(
        Session,
        on_delete=models.CASCADE,
        related_name='review'
    )
    rating = models.PositiveIntegerField(default=0)
    text = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review #{self.id} for session #{self.session.id}"

class Specialization(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name

class BuyRequest(models.Model):
    psychologist = models.ForeignKey(PsychologistProfile, on_delete=models.CASCADE, related_name='buy_requests')
    client = models.ForeignKey(ClientProfile, on_delete=models.CASCADE, related_name='buy_requests')
    request_date = models.DateTimeField(auto_now_add=True)
    status_choices = [
        ('PENDING', 'Pending'),
        ('ACCEPTED', 'Accepted'),
        ('DECLINED', 'Declined'),
    ]
    status = models.CharField(max_length=10, choices=status_choices, default='PENDING')

    def __str__(self):
        return f"BuyRequest from {self.client} to {self.psychologist}"