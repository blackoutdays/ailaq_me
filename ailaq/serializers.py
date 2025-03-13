from typing import Optional

import serializers
from django.contrib.auth import get_user_model
from rest_framework import serializers
from ailaq.models import CustomUser, PsychologistApplication, PsychologistProfile, ClientProfile, PsychologistLevel, \
    Review, BuyRequest, Topic, QuickClientConsultationRequest, EducationDocument, Session
from hashlib import sha256
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
import random
import hmac
import time
from django.utils import timezone
from datetime import datetime, date

from config import settings

CustomUser = get_user_model()

class CustomUserCreationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = CustomUser
        fields = ['email', 'password', 'password_confirm', 'wants_to_be_psychologist']  # Исправлено поле

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({"password_confirm": "Пароли не совпадают."})

        try:
            validate_password(data['password'])
        except ValidationError as e:
            raise serializers.ValidationError({"password": list(e.messages)})

        return data

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')

        user = CustomUser(**validated_data)
        user.set_password(password)
        user.verification_code = CustomUser._default_manager.generate_unique_verification_code()
        user.save()

        if user.wants_to_be_psychologist:
            PsychologistApplication.objects.get_or_create(user=user)

        return user

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        if not data.get("email") or not data.get("password"):
            raise serializers.ValidationError("Email и пароль обязательны.")
        return data

# Профиль клиента
class ClientProfileSerializer(serializers.ModelSerializer):
    email = serializers.SerializerMethodField()

    class Meta:
        model = ClientProfile
        fields = [
            'full_name',
            'age',
            'gender',
            'communication_language',
            'country',
            'city',
            'profile_image',
            'email',
        ]

    def get_email(self, obj) -> str:
        return obj.user.email if obj.user and obj.user.email else ""


class QuickClientConsultationRequestSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(help_text="Как к вам обращаться?")
    age = serializers.IntegerField(help_text="Возраст")
    gender = serializers.ChoiceField(
        choices=[('MALE', 'Мужской'), ('FEMALE', 'Женский')],
        help_text="Пол"
    )
    psychologist_language = serializers.ChoiceField(
        choices=[('RU', 'Русский'), ('EN', 'Английский'), ('KZ', 'Казахский')],
        help_text="Предпочтительный язык общения"
    )
    verification_code = serializers.CharField(read_only=True, help_text="Код для привязки Telegram")

    class Meta:
        model = QuickClientConsultationRequest
        fields = [
            'client_name', 'age', 'gender', 'psychologist_language',
            'preferred_psychologist_age', 'psychologist_gender', 'topic',
            'comments', 'verification_code'
        ]

    def create(self, validated_data):
        verification_code = str(random.randint(1000, 9999))

        consultation_request = QuickClientConsultationRequest.objects.create(
            verification_code=verification_code, **validated_data
        )

        return consultation_request

# Отзыв от клиента психологу
class ReviewSerializer(serializers.ModelSerializer):
    psychologist_name = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()

    def get_psychologist_name(self, obj):
        return obj.psychologist.user.email

    def get_client_name(self, obj):
        return obj.client.user.email

    class Meta:
        model = Review
        fields = [
            'id',
            'client_id',
            'psychologist_id',
            'client_name',
            'psychologist_name',
            'rating',
            'text',
            'created_at',
        ]

class PsychologistProfileSerializer(serializers.ModelSerializer):
    profile_id = serializers.IntegerField(source="id", read_only=True)  # ID профиля психолога
    full_name = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()
    experience_years = serializers.IntegerField(source='application.experience_years', read_only=True)
    country = serializers.CharField(source='application.service_countries', read_only=True)
    city = serializers.CharField(source='application.service_cities', read_only=True)
    about_me = serializers.CharField(source='application.about_me_ru', read_only=True)
    qualification = serializers.CharField(source='application.qualification', read_only=True)

    class Meta:
        model = PsychologistProfile
        fields = ['profile_id', 'full_name', 'age', 'qualification', 'experience_years', 'country', 'city', 'about_me']

    def get_full_name(self, obj):
        """Получает полное имя психолога"""
        if obj.application:
            first = obj.application.first_name_ru or ""
            last = obj.application.last_name_ru or ""
            return f"{first} {last}".strip() or obj.user.email
        return obj.user.email

    def get_age(self, obj):
        """Вычисляет возраст психолога по дате рождения (если есть)"""
        if obj.application and obj.application.birth_date:
            today = date.today()
            bd = obj.application.birth_date
            return today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
        return None

class PsychologistApplicationSerializer(serializers.ModelSerializer):
    user = serializers.ReadOnlyField(source="user.email")

    class Meta:
        model = PsychologistApplication
        fields = [
         'user', 'first_name_ru', 'last_name_ru', 'gender', 'qualification', 'is_verified', 'is_in_catalog', 'status'
        ]
        read_only_fields = ['user', 'status']

    def create(self, validated_data):
        user = self.context['request'].user
        return PsychologistApplication.objects.create(user=user, **validated_data)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

class TopicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topic
        fields = '__all__'

class CatalogSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    first_name_ru = serializers.SerializerMethodField()
    last_name_ru = serializers.SerializerMethodField()
    middle_name_ru = serializers.SerializerMethodField()
    qualification = serializers.SerializerMethodField()
    academic_degree = serializers.SerializerMethodField()
    catalog_description_ru = serializers.SerializerMethodField()
    session_price = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    reviews_count = serializers.SerializerMethodField()

    class Meta:
        model = PsychologistProfile
        fields = [
            'user_id',
            'first_name_ru',
            'last_name_ru',
            'middle_name_ru',
            'qualification',
            'academic_degree',
            'catalog_description_ru',
            'session_price',
            'is_verified',
            'requests_count',
            'average_rating',
            'reviews_count',
        ]

    def get_first_name_ru(self, obj) -> Optional[str]:
        return getattr(obj.application, 'first_name_ru', None)

    def get_last_name_ru(self, obj) -> Optional[str]:
        return getattr(obj.application, 'last_name_ru', None)

    def get_middle_name_ru(self, obj) -> Optional[str]:
        return getattr(obj.application, 'middle_name_ru', None)

    def get_qualification(self, obj) -> Optional[str]:
        return getattr(obj.application, 'qualification', None)

    def get_academic_degree(self, obj) -> Optional[str]:
        return getattr(obj.application, 'academic_degree', None)

    def get_catalog_description_ru(self, obj) -> Optional[str]:
        return getattr(obj.application, 'catalog_description_ru', None)

    def get_session_price(self, obj) -> Optional[float]:
        return getattr(obj.application, 'session_price', None)

    def get_average_rating(self, obj) -> Optional[float]:
        return obj.get_average_rating()

    def get_reviews_count(self, obj) -> Optional[int]:
        return obj.get_reviews_count()


#для вьющек сериализаторы по форме/профилю психолога
class PersonalInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistApplication
        fields = [
            'first_name_ru', 'last_name_ru', 'middle_name_ru',
            'birth_date', 'gender', 'communication_language',
            'service_countries', 'service_cities',
            'phone_number', 'telegram_id', 'about_me_ru', 'catalog_description_ru'
        ]

class EducationDocumentSerializer(serializers.ModelSerializer):
    document = serializers.FileField(required=True)
    year = serializers.IntegerField(required=False, allow_null=True)
    title = serializers.CharField(required=False, allow_blank=True)
    file_signature = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = EducationDocument
        fields = ['document', 'year', 'title', 'file_signature']

# Квалификация психолога
class QualificationSerializer(serializers.ModelSerializer):
    office_photo = serializers.ImageField(required=False, allow_null=True)
    education_files = EducationDocumentSerializer(many=True, required=False)
    file_signature = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = PsychologistApplication
        fields = [
            'qualification', 'works_with', 'problems_worked_with', 'work_methods',
            'experience_years', 'academic_degree', 'education',
            'office_photo', 'education_files', 'file_signature'
        ]

class ServicePriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistApplication
        fields = ['service_sessions']

# загрузка доков
class DocumentSerializer(serializers.ModelSerializer):
    office_photo = serializers.ImageField(required=False, allow_null=True)
    education_files = serializers.ListField(
        child=serializers.FileField(),
        required=False,
        allow_empty=True
    )
    file_signature = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = PsychologistApplication
        fields = ['office_photo', 'education_files', 'file_signature']

# 1. faq вопрос/ы и ответ/ы
class FAQSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=255)
    answer = serializers.CharField(max_length=1000)

# 2. faq вопрос/ы и ответ/ы
class FAQListSerializer(serializers.Serializer):
    faqs = serializers.ListField(
        child=FAQSerializer(),
        required=False
    )

class TelegramAuthSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    first_name = serializers.CharField(required=False)
    username = serializers.CharField(required=False)
    auth_date = serializers.IntegerField()
    hash = serializers.CharField()

    def validate(self, data):
        """ Проверяем Telegram авторизацию """
        token = settings.TELEGRAM_BOT_TOKEN
        auth_data = {key: value for key, value in data.items() if key != 'hash'}
        check_string = "\n".join([f"{k}={v}" for k, v in sorted(auth_data.items())])
        secret_key = sha256(token.encode()).digest()
        expected_hash = hmac.new(secret_key, check_string.encode(), sha256).hexdigest()

        if data['hash'] != expected_hash:
            raise serializers.ValidationError("Неверные данные Telegram.")

        if time.time() - int(data['auth_date']) > 86400:
            raise serializers.ValidationError("Время авторизации истекло.")

        return data

    def create_or_update_user(self, validated_data):
        """Создание или обновление пользователя на основе Telegram ID. """
        telegram_id = validated_data['id']
        username = validated_data.get('username', f"user_{telegram_id}")
        first_name = validated_data.get('first_name', "")

        user, created = CustomUser.objects.get_or_create(
            telegram_id=telegram_id,
            defaults={'email': f"{telegram_id}@telegram.local", 'username': username}
        )

        if not created:
            user.username = username
            user.first_name = first_name
            user.save()

        return user

class PsychologistLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistLevel
        fields = '__all__'

class BuyRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuyRequest
        fields = '__all__'

class EmptySerializer(serializers.Serializer):
    pass

class SessionSerializer(serializers.ModelSerializer):
    psychologist_name = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = ['id', 'psychologist_name', 'start_time', 'status']

    def get_psychologist_name(self, obj):
        """ Получает имя психолога из `PsychologistApplication` """
        if obj.psychologist and hasattr(obj.psychologist, 'application'):
            application = obj.psychologist.application
            full_name = f"{application.first_name_ru or ''} {application.last_name_ru or ''}".strip()
            return full_name if full_name else "Неизвестный психолог"
        return "Неизвестный психолог"

class SessionCreateSerializer(serializers.ModelSerializer):
    """
    Сериализатор для создания записи на сессию.
    Пользователь передаёт день/месяц/год/часы/минуты,
    а в create() мы собираем это в один DateTimeField (start_time).
    """
    day = serializers.IntegerField(min_value=1, max_value=31, required=True, write_only=True)
    month = serializers.IntegerField(min_value=1, max_value=12, required=True, write_only=True)
    year = serializers.IntegerField(min_value=2023, max_value=2100, required=True, write_only=True)
    hour = serializers.IntegerField(min_value=0, max_value=23, required=True, write_only=True)
    minute = serializers.IntegerField(min_value=0, max_value=59, required=True, write_only=True)

    class Meta:
        model = Session
        fields = [
            'id',
            'psychologist',
            'day',
            'month',
            'year',
            'hour',
            'minute',
            'status',
            'start_time',
        ]
        read_only_fields = ['status', 'start_time']

    def validate(self, attrs):
        """
        Собираем дату-время в один объект datetime.
        Проверяем, что это не прошлая дата.
        """
        day = attrs['day']
        month = attrs['month']
        year = attrs['year']
        hour = attrs['hour']
        minute = attrs['minute']

        try:
            proposed_dt = datetime(year, month, day, hour, minute)
            proposed_dt = timezone.make_aware(proposed_dt)  # Делаем дату "offset-aware"
        except ValueError:
            raise serializers.ValidationError("Некорректная дата или время.")

        if proposed_dt < timezone.now():
            raise serializers.ValidationError("Нельзя записаться на прошедшее время.")

        # Сохраняем объект datetime для дальнейшего использования в create()
        attrs['proposed_dt'] = proposed_dt
        return attrs

    def create(self, validated_data):
        """
        Создаём Session c полем start_time=proposed_dt и status=SCHEDULED.
        Поле client берётся из авторизованного пользователя.
        """
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            raise serializers.ValidationError("Пользователь не авторизован.")

        proposed_dt = validated_data.pop('proposed_dt')

        # Убираем из validated_data поля, которых нет в модели
        for remove_field in ['day', 'month', 'year', 'hour', 'minute']:
            validated_data.pop(remove_field, None)

        # Получаем профиль клиента
        try:
            client_profile = request.user.client_profile
        except ClientProfile.DoesNotExist:
            raise serializers.ValidationError("У авторизованного пользователя нет профиля клиента.")

        session_obj = Session.objects.create(
            client=client_profile,
            start_time=proposed_dt,
            status='SCHEDULED',
            **validated_data
        )
        return session_obj