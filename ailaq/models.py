from datetime import timedelta
from django.utils.crypto import get_random_string
from django.utils.timezone import now
from django.db.models import Avg
from django.conf import settings
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
import logging
from ailaq.enums import (
    ClientGenderEnum, PsychologistAgeEnum, PsychologistGenderEnum,
    CommunicationLanguageEnum, PreferredPsychologistGenderEnum, LanguageEnum
)

logger = logging.getLogger(__name__)

class CustomUserManager(BaseUserManager):
    def create_user(self, email=None, password=None, telegram_id=None, **extra_fields):
        """Создаёт нового пользователя (email или Telegram)"""
        if not email and not telegram_id:
            raise ValueError('Необходимо указать email или Telegram ID')

        email = self.normalize_email(email) if email else None

        #  Если вход через Telegram → пользователь активен сразу
        is_active = bool(telegram_id)

        user = self.model(
            email=email,
            telegram_id=telegram_id,
            is_active=is_active,  #  Теперь Telegram-пользователи активны сразу
            **extra_fields
        )

        if password:
            user.set_password(password)
        user.save(using=self._db)

        #  Если регистрация через email — отправляем письмо подтверждения
        if email:
            verification_code = get_random_string(length=32)
            user.verification_code = verification_code
            user.verification_code_expiration = now() + timedelta(hours=24)
            user.save()

            confirmation_link = f"{settings.FRONTEND_URL}/confirm-email/{verification_code}"
            from ailaq.tasks import send_email_async
            send_email_async.delay("Подтверждение email", f"Подтвердите email: {confirmation_link}", [user.email])

        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if not extra_fields.get('is_staff'):
            raise ValueError('Superuser must have is_staff=True.')
        if not extra_fields.get('is_superuser'):
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email=email, password=password, **extra_fields)

class CustomUser(AbstractBaseUser):
    """Кастомная модель пользователя с подтверждением email"""
    telegram_id = models.BigIntegerField(null=True, blank=True, unique=True, verbose_name="Telegram ID", editable=False)
    email = models.EmailField(unique=True, null=True, blank=True)

    verification_code = models.CharField(max_length=64, unique=True, null=True, blank=True)  # Токен для подтверждения
    verification_code_expiration = models.DateTimeField(null=True, blank=True)  # Срок действия кода

    is_psychologist = models.BooleanField(default=False)  # Является ли психологом
    wants_to_be_psychologist = models.BooleanField(default=False)  # Хочет стать психологом

    is_staff = models.BooleanField(default=False)  # Доступ в админку
    is_superuser = models.BooleanField(default=False)  # Полный доступ

    is_active = models.BooleanField(default=False)  # Неактивен, пока не подтвердит email

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def get_username(self):
        """Получение имени пользователя (email или Telegram ID)"""
        return self.email if self.email else f"tg_{self.telegram_id}"

    def generate_verification_code(self):
        """Генерирует уникальный токен для подтверждения email"""
        self.verification_code = get_random_string(length=64)  # Уникальный токен
        self.verification_code_expiration = now() + timedelta(hours=24)  # Действует 24 часа
        self.save(update_fields=['verification_code', 'verification_code_expiration'])
        return self.verification_code  # Можно отправить по email

    def confirm_email(self):
        """Подтверждает email пользователя"""
        self.is_active = True
        self.verification_code = None
        self.verification_code_expiration = None
        self.save(update_fields=['is_active', 'verification_code', 'verification_code_expiration'])

    def __str__(self):
        return self.email or f"Telegram User {self.telegram_id}"

    @property
    def role(self):
        """Возвращает роль пользователя (психолог или клиент)"""
        return 'PSYCHOLOGIST' if self.is_psychologist else 'CLIENT'

    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_superuser

class ClientProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='client_profile'
    )

    # Основные поля профиля
    full_name = models.CharField(max_length=255, null=True, blank=True, verbose_name="Полное имя")
    age = models.PositiveIntegerField(null=True, blank=True, verbose_name="Возраст")
    gender = models.CharField(
        max_length=10,
        choices=[(tag.name, tag.value) for tag in ClientGenderEnum],
        null=True,
        blank=True,
        verbose_name="Пол"
    )
    communication_language = models.CharField(
        max_length=10,
        choices=[(tag.name, tag.value) for tag in LanguageEnum],
        null=True,
        blank=True,
        verbose_name="Язык общения"
    )
    country = models.CharField(max_length=100, null=True, blank=True, verbose_name="Страна")
    city = models.CharField(max_length=100, null=True, blank=True, verbose_name="Город")

    def __str__(self):
        return f"Client Profile: {self.full_name or self.user.email or self.user.telegram_id}"

    @property
    def telegram_id(self):
        return self.user.telegram_id

class Topic(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Название темы")

    def __str__(self):
        return self.name

class QuickClientConsultationRequest(models.Model):
    client_name = models.CharField(max_length=255, verbose_name="Как к вам обращаться?")
    age = models.PositiveIntegerField(null=True, blank=True, verbose_name="Возраст")
    gender = models.CharField(
        max_length=10,
        choices=[(tag.name, tag.value) for tag in ClientGenderEnum],
        verbose_name="Пол клиента"
    )
    preferred_psychologist_age = models.CharField(
        max_length=20,
        choices=[(tag.name, tag.value) for tag in PsychologistAgeEnum],
        verbose_name="Возраст специалиста"
    )
    psychologist_gender = models.CharField(
        max_length=10,
        choices=[(tag.name, tag.value) for tag in PreferredPsychologistGenderEnum],
        verbose_name="Пол специалиста"
    )
    psychologist_language = models.CharField(
        max_length=10,
        choices=[(tag.name, tag.value) for tag in CommunicationLanguageEnum],
        verbose_name="Язык общения"
    )
    topic = models.CharField(max_length=255, verbose_name="Тема")
    comments = models.TextField(verbose_name="Комментарий")
    client_token = models.CharField(max_length=64, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(default=now)
    telegram_id = models.BigIntegerField(null=True, blank=True, verbose_name="Telegram ID", editable=False)

    def __str__(self):
        return f"Заявка от {self.client_name} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"

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
    year = models.PositiveIntegerField(null=True, blank=True, help_text="Год получения документа")
    title = models.CharField(max_length=255, null=True, blank=True, help_text="Название документа")
    file_signature = models.CharField(max_length=255, null=True, blank=True, help_text="Подпись к файлу")

    def __str__(self):
        return f"{self.year} - {self.title}"

# форма заявки/профиль (только для психолога)
class PsychologistApplication(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)

    # Личная информация
    first_name_ru = models.CharField(max_length=50, null=True, blank=True)
    last_name_ru = models.CharField(max_length=50, null=True, blank=True)
    middle_name_ru = models.CharField(max_length=50, null=True, blank=True)

    birth_date = models.DateField(null=True, blank=True)  # Дата рождения

    gender = models.CharField(
        max_length=10,
        choices=[(tag.name, tag.value) for tag in PsychologistGenderEnum],
        null=True, blank=True
    )
    communication_language = models.CharField(
        max_length=10,
        choices=[(tag.name, tag.value) for tag in CommunicationLanguageEnum],
        null=True, blank=True
    )
    # **Страна и город приема (список с фронта)**
    service_countries = models.JSONField(default=list, blank=True, help_text="Список стран приема")
    service_cities = models.JSONField(default=list, blank=True, help_text="Список городов приема")

    telegram_id = models.CharField(max_length=100, null=True, blank=True)  # Ник или ID в Telegram

    # О себе
    about_me_ru = models.TextField(null=True, blank=True)

    # Каталоговое описание (для отображения в каталоге)
    catalog_description_ru = models.TextField(null=True, blank=True)

    # Квалификация (специализация)
    qualification = models.CharField(max_length=100, null=True, blank=True)  # Например "Психолог"

    # С кем работает (список)
    works_with_choices = [
        ('ADULTS', 'Взрослые'),
        ('TEENAGERS', 'Подростки'),
        ('CHILDREN', 'Дети'),
        ('FAMILY', 'Семья'),
    ]
    works_with = models.CharField(max_length=50, choices=works_with_choices, null=True, blank=True)

    # С какими проблемами работает
    problems_worked_with = models.TextField(null=True, blank=True)

    # Методы работы
    work_methods = models.TextField(null=True, blank=True)

    # Стаж работы (в годах)
    experience_years = models.PositiveIntegerField(null=True, blank=True, verbose_name="Стаж работы (в годах)")

    # Научная степень
    academic_degree = models.CharField(max_length=100, null=True, blank=True)

    # Дополнительная специализация
    additional_specialization = models.TextField(null=True, blank=True)

    # Дополнительные направления
    additional_psychologist_directions = models.TextField(null=True, blank=True)

    # Образование (JSON: Год + Название)
    education = models.JSONField(default=list, blank=True, null=True)

    # Документы об образовании
    education_files = models.ManyToManyField('EducationDocument', blank=True, related_name='applications')

    # Адрес офиса
    country = models.CharField(max_length=100, null=True, blank=True, verbose_name="Страна")
    city = models.CharField(max_length=100, null=True, blank=True, verbose_name="Город")
    office_address = models.TextField(null=True, blank=True, verbose_name="Полный адрес офиса")

    # Фото офиса
    office_photo = models.ImageField(upload_to='office_photos/', null=True, blank=True)

    # **Приемы (сессии)**
    SESSION_TYPES = [
        ('INDIVIDUAL', 'Индивидуальная консультация'),
        ('COUPLE', 'Парная консультация'),
        ('GROUP', 'Групповая консультация'),
    ]

    ONLINE_OFFLINE_CHOICES = [
        ('ONLINE', 'Онлайн'),
        ('OFFLINE', 'Оффлайн'),
    ]

    CURRENCY_CHOICES = [
        ('KZT', 'Тенге'),
        ('RUB', 'Рубли'),
        ('USD', 'Доллары'),
        ('EUR', 'Евро'),
    ]

    service_sessions = models.JSONField(default=list, blank=True)

    # **Рейтинги и заявки**
    is_verified = models.BooleanField(default=False)
    is_in_catalog = models.BooleanField(default=False)

    purchased_applications = models.IntegerField(default=0)
    expired_applications = models.IntegerField(default=0)
    active_applications = models.IntegerField(default=0)
    paid_applications = models.IntegerField(default=0)
    unpaid_applications = models.IntegerField(default=0)

    rating_system = models.FloatField(default=0.0)
    internal_rating = models.FloatField(default=0.0)

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('DOCUMENTS_REQUESTED', 'Documents Requested'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    documents_requested = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        """
        При изменении статуса заявки на `APPROVED` создаём `PsychologistProfile`
        """
        # 🔹 Получаем старый статус заявки до сохранения
        if self.pk:
            old_status = PsychologistApplication.objects.filter(pk=self.pk).values_list("status", flat=True).first()
        else:
            old_status = None

        super().save(*args, **kwargs)

        # 🔹 Если статус изменился с `PENDING` на `APPROVED`, создаём профиль
        if old_status == "PENDING" and self.status == "APPROVED":
            PsychologistProfile.process_psychologist_application(self.id)

    # **Методы**
    def add_service_session(self, session_type, online_offline, country, city, duration, price, currency):
        """Добавляет новый прием (сессию)."""
        session_data = {
            "session_type": session_type,
            "online_offline": online_offline,
            "country": country,
            "city": city,
            "duration": duration,
            "price": price,
            "currency": currency
        }
        new_sessions = self.service_sessions[:]  # Создаем копию списка
        new_sessions.append(session_data)
        self.service_sessions = new_sessions
        self.save(update_fields=['service_sessions'])

    def remove_service_session(self, index):
        """Удаляет прием (сессию) по индексу."""
        if 0 <= index < len(self.service_sessions):
            new_sessions = self.service_sessions[:]
            del new_sessions[index]
            self.service_sessions = new_sessions
            self.save(update_fields=['service_sessions'])

    def add_education_document(self, document, year, title):
        """Добавляет документ об образовании."""
        if not document:
            raise ValueError("Документ не может быть пустым")

        new_document = EducationDocument(document=document, year=year, title=title)
        new_document.save()
        self.education_files.add(new_document)
        self.save(update_fields=['education_files'])

    def remove_education_document(self, document_id):
        """Удаляет документ об образовании"""
        try:
            doc = self.education_files.get(id=document_id)
            doc.delete()
        except EducationDocument.DoesNotExist:
            pass

    def __str__(self):
        return f"Заявка психолога {self.user.email} (Стаж: {self.experience_years} лет)"

# FAQ психолога
class PsychologistFAQ(models.Model):
    application = models.ForeignKey(
        'PsychologistApplication',
        related_name='faqs',
        on_delete=models.CASCADE
    )
    question = models.CharField(max_length=255)
    answer = models.TextField()

    def __str__(self):
        return f"FAQ: {self.question[:50]}..."

# Профиль психолога
class PsychologistProfile(models.Model):
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='psychologist_profile'
    )
    application = models.OneToOneField(
        PsychologistApplication,
        on_delete=models.CASCADE,
        related_name='profile',
        null=True,
        blank=True
    )

    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Баланс психолога"
    )

    is_in_catalog = models.BooleanField(default=False)
    requests_count = models.PositiveIntegerField(default=0)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"Психолог: {self.user.email} (Баланс: {self.balance})"

    @property
    def telegram_id(self):
        return self.user.telegram_id

    def update_catalog_status(self):
        """Обновляет статус `is_in_catalog` на основе метода `can_be_in_catalog`."""
        self.is_in_catalog = self.can_be_in_catalog()
        self.save()

    @staticmethod
    def process_psychologist_application(application_id: int) -> None:
        """Обрабатывает заявку психолога"""
        try:
            application = PsychologistApplication.objects.get(id=application_id)
            user = application.user

            if application.status == 'APPROVED':
                user.is_psychologist = True  #  Статус "психолог"
                user.save()

                #  Создаём профиль, если его нет
                profile, created = PsychologistProfile.objects.get_or_create(user=user, application=application)

                profile.is_verified = True
                profile.update_catalog_visibility()  #  Проверяем, может ли он быть в каталоге
                profile.save()

                from ailaq.emails import send_approval_email
                send_approval_email(application)

            elif application.status == 'REJECTED':
                from ailaq.emails import send_rejection_email
                send_rejection_email(application)

        except PsychologistApplication.DoesNotExist:
            logger.error(f"Application with ID {application_id} not found.")

    def get_average_rating(self) -> float:
        """Возвращает средний рейтинг психолога на основе завершённых сессий."""
        average_rating = Review.objects.filter(
            psychologist=self, session__status='COMPLETED'
        ).aggregate(avg_rating=Avg('rating'))['avg_rating'] or 0.0

        return round(average_rating, 1)

    def is_ready_for_moderation(self) -> bool:
        """Проверяет, заполнены ли все обязательные поля."""
        required_fields = [
            self.first_name_ru, self.last_name_ru, self.birth_date, self.gender,
            self.communication_language, self.qualification, self.experience_years,
            self.service_countries, self.service_cities, self.education
        ]

        return all(bool(value) for value in required_fields)

    def get_reviews_count(self) -> int:
        """Возвращает количество завершённых отзывов"""
        return Review.objects.filter(psychologist=self, session__status='COMPLETED').count()

    def update_catalog_visibility(self):
        """Психолог попадает в каталог, если у него >=3 покупок и >=3 оценённых отзывов."""
        if self.application:
            self.is_in_catalog = (
                    self.is_verified and
                    self.application.purchased_applications >= 3 and
                    Review.objects.filter(psychologist=self, session__status='COMPLETED', rating__gt=0).count() >= 3
            )
            self.save(update_fields=["is_in_catalog"])

def get_default_cost():
    return settings.REQUEST_COST

def save(self, *args, **kwargs):
    """
    При изменении статуса заявки на `APPROVED` создаём `PsychologistProfile`
    """
    old_status = None
    if self.pk:
        old_status = PsychologistApplication.objects.filter(pk=self.pk).values_list("status", flat=True).first()

    super().save(*args, **kwargs)

    # Если это новая заявка и она сразу "APPROVED" → создаём профиль
    if self.pk and (old_status is None or old_status == "PENDING") and self.status == "APPROVED":
        PsychologistProfile.process_psychologist_application(self.id)

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
    STATUS_CHOICES = [
        ('SCHEDULED', 'Scheduled'),
        ('COMPLETED', 'Completed'),
        ('CANCELED', 'Canceled'),
    ]

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
    review_requested = models.BooleanField(default=False)
    review_submitted = models.BooleanField(default=False)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=[('SCHEDULED', 'Scheduled'), ('COMPLETED', 'Completed'), ('CANCELED', 'Canceled')], default='SCHEDULED')

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Session #{self.pk} [{self.status}]"

# отзыв за проведенную сессию
class Review(models.Model):
    session = models.OneToOneField(
        Session,
        on_delete=models.CASCADE,
        related_name='review'
    )
    client = models.ForeignKey(
        ClientProfile,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    psychologist = models.ForeignKey(
        PsychologistProfile,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    client_name = models.CharField(max_length=255)  # ФИО клиента
    psychologist_name = models.CharField(max_length=255)  # ФИО психолога
    rating = models.PositiveIntegerField(default=0)  # Рейтинг от 1 до 5
    text = models.TextField(null=True, blank=True)  # Текст отзыва
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review by {self.client_name or 'Unknown'} for {self.psychologist_name or 'Unknown'} (Rating: {self.rating})"

    def save(self, *args, **kwargs):
        if not self.client_name:
            self.client_name = self.client.full_name
        if not self.psychologist_name:
            self.psychologist_name = self.psychologist.user.get_full_name()
        super().save(*args, **kwargs)

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

    def accept(self):
        if self.status != 'PENDING':
            raise ValueError("Заявка уже обработана.")

        self.status = 'ACCEPTED'
        self.save()

        # Получаем заявку психолога через профиль пользователя
        if self.psychologist and self.psychologist.application:
            application = self.psychologist.application
            application.purchased_applications += 1
            application.save(update_fields=['purchased_applications'])

            # Обновляем видимость психолога в каталоге
            self.psychologist.update_catalog_visibility()