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
        for _ in range(10):  # До 10 попыток генерации уникального кода
            new_code = str(random.randint(1000, 9999))  # 4-значный код
            if not CustomUser.objects.filter(verification_code=new_code).exists():
                self.verification_code = new_code
                self.verification_code_expiration = now() + timedelta(minutes=10)  # Устанавливаем срок
                self.save(update_fields=['verification_code', 'verification_code_expiration'])
                return new_code
        raise ValueError("Не удалось сгенерировать уникальный код подтверждения")

    def generate_new_verification_code(self):
        """
        Генерирует новый уникальный код подтверждения (4 цифры).
        Если сгенерированный код уже существует, метод делает до 10 попыток.
        Код действителен 10 минут.
        """
        for _ in range(10):  # До 10 попыток генерации уникального кода
            new_code = str(random.randint(1000, 9999))  # Генерируем 4-значный код
            if not CustomUser.objects.filter(verification_code=new_code).exists():  # Проверяем уникальность
                self.verification_code = new_code
                self.verification_code_expiration = now() + timedelta(minutes=10)  # Устанавливаем срок действия
                self.save(update_fields=['verification_code', 'verification_code_expiration'])  # Сохраняем изменения
                return new_code

        # Если после 10 попыток не удалось найти уникальный код, вызываем ошибку
        raise ValueError("Не удалось сгенерировать уникальный код подтверждения")

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

class Topic(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Название темы")

    def __str__(self):
        return self.name

class QuickClientConsultationRequest(models.Model):
    client_name = models.CharField(max_length=255, verbose_name="Как к вам обращаться?")
    birth_date = models.DateField(verbose_name="Дата рождения")
    gender = models.CharField(
        max_length=10,
        choices=[('MALE', 'Мужской'), ('FEMALE', 'Женский')],
        verbose_name="Пол"
    )
    preferred_psychologist_age = models.CharField(
        max_length=20,
        choices=[('18-25', 'От 18 до 25'), ('25-35', 'От 25 до 35'), ('35+', 'От 35')],
        verbose_name="Возраст специалиста"
    )
    psychologist_gender = models.CharField(
        max_length=10,
        choices=[('MALE', 'Мужской'), ('FEMALE', 'Женский')],
        verbose_name="Пол специалиста"
    )
    psychologist_language = models.CharField(
        max_length=10,
        choices=[('RU', 'Русский'), ('EN', 'Английский'), ('KZ', 'Казахский')],
        verbose_name="Язык общения"
    )
    topic = models.CharField(max_length=255, verbose_name="Основная тема")
    additional_topics = models.ManyToManyField(
        'Topic',
        related_name='consultations',
        verbose_name="Дополнительные темы"
    )
    comments = models.TextField(verbose_name="Комментарий")
    created_at = models.DateTimeField(default=now)
    verification_code = models.CharField(max_length=6, unique=True, blank=True, null=True,
                                         verbose_name="Код подтверждения")

    # 🔹 Добавляем telegram_id
    telegram_id = models.BigIntegerField(null=True, blank=True, verbose_name="Telegram ID клиента")

    def save(self, *args, **kwargs):
        if not self.verification_code:
            self.verification_code = str(random.randint(100000, 999999))
        super().save(*args, **kwargs)

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

    gender_choices = [
        ('MALE', 'Мужской'),
        ('FEMALE', 'Женский'),
        ('OTHER', 'Другой'),
    ]
    gender = models.CharField(max_length=6, choices=gender_choices, null=True, blank=True)

    language_choices = [
        ('RU', 'Русский'),
        ('EN', 'Английский'),
        ('KZ', 'Казахский'),
    ]
    communication_language = models.CharField(max_length=2, choices=language_choices, null=True, blank=True)

    # **Страна и город приема (список с фронта)**
    service_countries = models.JSONField(default=list, blank=True, help_text="Список стран приема")
    service_cities = models.JSONField(default=list, blank=True, help_text="Список городов приема")


    telegram_id = models.CharField(max_length=100, null=True, blank=True)  # Ник или ID в Telegram
    phone_number = models.CharField(max_length=15, null=True, blank=True)  # Номер телефона

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

        new_document = EducationDocument.objects.create(
            psychologist_application=self,
            document=document,
            year=year,
            title=title
        )
        self.education_files.add(new_document)
        self.save(update_fields=['education_files'])

    def remove_education_document(self, document_id):
        """
        Удаляет документ об образовании.
        """
        try:
            doc = self.education_files.get(id=document_id)
            doc.delete()
        except EducationDocument.DoesNotExist:
            pass

    def __str__(self):
        return f"Заявка психолога {self.user.email} (Стаж: {self.experience_years} лет)"

# **FAQ психолога**
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
        return f"Review by {self.client_name or 'Unknown'} for {self.psychologist_name or 'Unknown'} (Rating: {self.rating})"

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