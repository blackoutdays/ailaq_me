from django.utils.timezone import now, timedelta
from ailaq.emails import send_approval_email, send_rejection_email
from django.db.models import Avg
from django.conf import settings
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
import random

import logging
logger = logging.getLogger(__name__)

class CustomUserManager(BaseUserManager):
    def create_user(self, email=None, password=None, telegram_id=None, **extra_fields):
        if not email and not telegram_id:
            raise ValueError('Either Telegram ID or Email must be provided for registration.')

        # Генерация уникального кода при создании пользователя
        verification_code = self.generate_unique_verification_code()

        # Нормализация email
        email = self.normalize_email(email) if email else None

        user = self.model(
            email=email,
            telegram_id=telegram_id,
            verification_code=verification_code,
            **extra_fields
        )

        if password:
            user.set_password(password)
        user.save(using=self._db)

        # Создаем профиль автоматически
        if user.is_psychologist:
            PsychologistProfile.objects.get_or_create(user=user)
        else:
            ClientProfile.objects.get_or_create(user=user)

        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email=email, password=password, **extra_fields)

    @staticmethod
    def generate_unique_verification_code():
        for _ in range(10):  # Попытки до 10 раз
            code = str(random.randint(1000, 9999))
            if not CustomUser.objects.filter(verification_code=code).exists():
                return code
        raise ValueError("Could not generate a unique verification code")

class CustomUser(AbstractBaseUser):
    telegram_id = models.BigIntegerField(unique=True, null=True, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    verification_code = models.CharField(max_length=4, unique=True, null=True, blank=True)
    verification_code_expiration = models.DateTimeField(null=True, blank=True)  # Дата истечения

    is_psychologist = models.BooleanField(default=False)
    wants_to_be_psychologist = models.BooleanField(default=False)

    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def generate_verification_code(self):
        """Генерация нового кода и обновление срока действия."""
        self.verification_code = str(random.randint(1000, 9999))
        self.verification_code_expiration = now() + timedelta(minutes=10)
        self.save()  # Сохраняем изменения

    def generate_new_verification_code(self):
        """Генерация нового уникального кода."""
        for _ in range(10):  # Попытки до 10 раз
            new_code = str(random.randint(1000, 9999))
            if not CustomUser.objects.filter(verification_code=new_code).exists():
                self.verification_code = new_code
                self.verification_code_expiration = now() + timedelta(minutes=10)
                self.save()
                return new_code
        raise ValueError("Could not generate a new unique verification code")

    def __str__(self):
        return self.email or f"Telegram User {self.telegram_id}"

    @property
    def role(self):
        return 'PSYCHOLOGIST' if self.is_psychologist else 'CLIENT'

    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_superuser


class ClientProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='client_profile')

    def __str__(self):
        return f"ClientProfile for {self.user.email or self.user.telegram_id}"

    @property
    def telegram_id(self):
        return self.user.telegram_id


class QuickConsultationRequest(models.Model):
    client_name = models.CharField(max_length=255)
    client_age = models.PositiveIntegerField()
    preferred_psychologist_age = models.PositiveIntegerField(null=True, blank=True)
    psychologist_gender = models.CharField(
        max_length=10,
        choices=[('MALE', 'Male'), ('FEMALE', 'Female'), ('ANY', 'Any')],
        default='ANY'
    )
    psychologist_language = models.CharField(
        max_length=10,
        choices=[('RU', 'Russian'), ('EN', 'English'), ('KZ', 'Kazakh')],
        default='RU'
    )
    topic = models.CharField(max_length=255, help_text="Тема, например, депрессия, тревожность и т.д.")
    comments = models.TextField(null=True, blank=True)
    telegram_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Consultation request from {self.client_name}"


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


# форма заявки/профиль (только для психолога)
class PsychologistApplication(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)

    # Личная информация
    first_name_ru = models.CharField(max_length=50, null=True, blank=True)
    last_name_ru = models.CharField(max_length=50, null=True, blank=True)
    middle_name_ru = models.CharField(max_length=50, null=True, blank=True)

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

    # Каталоговое описание психолога (будет отображаться в каталоге)
    catalog_description_ru = models.TextField(null=True, blank=True)

    # Чем сможете помочь (текстовое поле)
    help_text_ru = models.TextField(null=True, blank=True)

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

#профиль психолога
class PsychologistProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="psychologist_profile", unique=True)
    application = models.OneToOneField(
        PsychologistApplication,
        on_delete=models.CASCADE,
        related_name='profile',
        null=True,
        blank=True
    )

    is_in_catalog = models.BooleanField(default=False)
    requests_count = models.PositiveIntegerField(default=0)
    is_verified = models.BooleanField(default=False)  # Поле базы данных

    def __str__(self):
        return f"PsychologistProfile for {self.user.email}"

    @property
    def telegram_id(self):
        return self.user.telegram_id

    def update_catalog_status(self):
        """Обновляет статус `is_in_catalog` на основе метода `can_be_in_catalog`."""
        self.is_in_catalog = self.can_be_in_catalog()
        self.save()

    @staticmethod
    def process_psychologist_application(application_id):
        """Обработка заявки психолога."""
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

    def get_reviews_count(self):
        """
        Возвращает количество отзывов для завершённых сессий психолога.
        """
        return Review.objects.filter(session__psychologist=self, session__status='COMPLETED').count()


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
        return f"Review by {self.client_name} for {self.psychologist_name} (Rating: {self.rating})"


class Specialization(models.Model):
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


#  faq вопрос/ы и ответ/ы психолога
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