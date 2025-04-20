import base64
import uuid
from typing import Optional
from django.contrib.auth import get_user_model, authenticate
from django.core.files.base import ContentFile
from rest_framework import serializers
from ailaq.models import CustomUser, PsychologistApplication, PsychologistProfile, ClientProfile, PsychologistLevel, \
    Review, BuyRequest, Topic, QuickClientConsultationRequest, EducationDocument, PsychologistSessionRequest
from hashlib import sha256
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
import hmac

from .enums import CommunicationLanguageEnum, PreferredPsychologistGenderEnum
from .tasks import send_email_async
import time
from drf_extra_fields.fields import Base64ImageField, Base64FileField
from datetime import timedelta
from django.utils.crypto import get_random_string
from django.utils.timezone import now
from datetime import date

from config import settings

User = get_user_model()
CustomUser = get_user_model()

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
        """Создание или обновление пользователя — без логики wants_to_be_psychologist"""
        telegram_id = validated_data['id']
        username = validated_data.get('username', f"user_{telegram_id}")
        first_name = validated_data.get('first_name', "")

        user, created = CustomUser.objects.get_or_create(
            telegram_id=telegram_id,
            defaults={
                'email': f"{telegram_id}@telegram.local",
                'username': username,
                'is_active': True
            }
        )

        if not created:
            user.username = username
            user.first_name = first_name
            user.save()

        return user

class CustomUserCreationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = CustomUser
        fields = ['email', 'password', 'password_confirm', 'wants_to_be_psychologist']

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

class RegisterSerializer(serializers.ModelSerializer):
    """Сериализатор для регистрации пользователей (клиентов и психологов)"""
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=True)
    wants_to_be_psychologist = serializers.BooleanField(default=False)

    class Meta:
        model = CustomUser
        fields = ['email', 'password', 'password_confirm', 'wants_to_be_psychologist']

    def validate(self, attrs):
        """ Проверяем совпадение паролей """
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password_confirm": "Пароли не совпадают."})
        return attrs

    def create(self, validated_data):
        """ Создаёт нового пользователя """
        validated_data.pop('password_confirm')  # убираем повтор пароля
        wants_to_be_psychologist = validated_data.pop("wants_to_be_psychologist")

        user = CustomUser.objects.create(
            email=validated_data['email'],
            wants_to_be_psychologist=wants_to_be_psychologist,
            is_active=False
        )
        user.set_password(validated_data['password'])
        user.verification_code = get_random_string(length=32)
        user.verification_code_expiration = now() + timedelta(hours=24)
        user.save()

        # Если пользователь хочет стать психологом, создаем заявку и профиль
        if wants_to_be_psychologist:
            PsychologistApplication.objects.get_or_create(user=user)
            # Профиль создастся автоматически в процессе создания заявки

        return user

class LoginSerializer(serializers.Serializer):
    """ Сериализатор для входа пользователя (клиент или психолог) """
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        """ Проверяем email и пароль """
        email = attrs.get("email")
        password = attrs.get("password")

        user = authenticate(email=email, password=password)
        if not user:
            raise serializers.ValidationError({"error": "Неверные учетные данные."})

        if not user.is_active:
            raise serializers.ValidationError({"error": "Ваш email не подтвержден."})

        attrs["user"] = user
        return attrs

class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)
    confirm_new_password = serializers.CharField(required=True, min_length=8)

    def validate(self, data):
        if data["new_password"] != data["confirm_new_password"]:
            raise serializers.ValidationError({"confirm_new_password": "Пароли не совпадают."})
        return data

class PsychologistLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistLevel
        fields = '__all__'

class BuyRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuyRequest
        fields = '__all__'

class ClientProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    current_password = serializers.CharField(write_only=True, required=False)
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    confirm_password = serializers.CharField(write_only=True, required=False, min_length=8)
    telegram_id = serializers.CharField(source="user.telegram_id", read_only=True)
    communication_language = serializers.ListField(
        child=serializers.ChoiceField(choices=[tag.name for tag in CommunicationLanguageEnum]),
        required=False
    )

    class Meta:
        model = ClientProfile
        fields = [
            'full_name', 'age', 'gender', 'communication_language', 'country', 'city',
            'email', 'current_password', 'password', 'confirm_password', 'telegram_id',
        ]

    def validate(self, data):
        """ Проверка паролей только если переданы. """
        password = data.get("password")
        confirm_password = data.get("confirm_password")

        if password or confirm_password:
            if not password or not confirm_password:
                raise serializers.ValidationError({"password": "Укажите и пароль, и подтверждение пароля."})
            if password != confirm_password:
                raise serializers.ValidationError({"password": "Пароли не совпадают."})

        return data

    def update(self, instance, validated_data):
        user = instance.user
        email = validated_data.pop("email", None)
        password = validated_data.pop("password", None)
        current_password = validated_data.pop("current_password", None)

        # Обновление email, если пользователь телеграмный и ещё не вводил
        if email:
            if user.email:
                raise serializers.ValidationError({"email": "Изменение email запрещено."})
            user.email = email
            user.is_active = False
            user.verification_code = get_random_string(length=32)
            user.verification_code_expiration = now() + timedelta(hours=24)
            user.save()

            confirmation_link = f"{settings.FRONTEND_URL}/confirm-email/{user.verification_code}"
            send_email_async.delay("Подтверждение email", f"Подтвердите email: {confirmation_link}", [user.email])

        # Обновление пароля, если указан
        if password:
            if not current_password or not user.check_password(current_password):
                raise serializers.ValidationError({"password": "Неверный текущий пароль."})
            user.set_password(password)
            user.save()

        return super().update(instance, validated_data)

class NormalizeListFieldsMixin:
    list_fields_to_normalize = []
    int_fields_to_normalize = []

    def to_internal_value(self, data):
        for field in self.list_fields_to_normalize:
            if field in data and isinstance(data[field], str):
                data[field] = [item.strip() for item in data[field].split(',') if item.strip()]

        for field in self.int_fields_to_normalize:
            if field in data and isinstance(data[field], str) and data[field].isdigit():
                data[field] = int(data[field])

        return super().to_internal_value(data)

class QuickClientConsultationRequestSerializer(NormalizeListFieldsMixin, serializers.ModelSerializer):
    list_fields_to_normalize = ['psychologist_language', 'psychologist_gender', 'topic']
    int_fields_to_normalize = ['preferred_psychologist_age_min', 'preferred_psychologist_age_max']

    psychologist_language = serializers.ListField(
        child=serializers.ChoiceField(choices=[tag.name for tag in CommunicationLanguageEnum]),
        required=False
    )
    psychologist_gender = serializers.ListField(
        child=serializers.ChoiceField(choices=[tag.name for tag in PreferredPsychologistGenderEnum]),
        required=False
    )
    topic = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )
    preferred_psychologist_age_min = serializers.IntegerField(required=False, allow_null=True)
    preferred_psychologist_age_max = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = QuickClientConsultationRequest
        fields = [
            'client_name', 'age', 'gender', 'psychologist_language',
            'preferred_psychologist_age_min', 'preferred_psychologist_age_max',
            'psychologist_gender', 'topic', 'comments'
        ]

    def validate(self, data):
        user = self.context.get("request").user if self.context.get("request") else None

        if not user or not user.is_authenticated:
            required_fields = [
                'client_name', 'age', 'gender', 'psychologist_language',
                'preferred_psychologist_age_min', 'preferred_psychologist_age_max',
                'psychologist_gender', 'topic'
            ]
            for field in required_fields:
                if not data.get(field):
                    raise serializers.ValidationError({field: "Это поле обязательно."})
        return data

class AuthenticatedQuickClientConsultationRequestSerializer(NormalizeListFieldsMixin, serializers.ModelSerializer):
    list_fields_to_normalize = ['psychologist_language', 'psychologist_gender', 'topic']
    int_fields_to_normalize = ['preferred_psychologist_age_min', 'preferred_psychologist_age_max']

    psychologist_language = serializers.ListField(
        child=serializers.ChoiceField(choices=[tag.name for tag in CommunicationLanguageEnum]),
        required=False
    )
    psychologist_gender = serializers.ListField(
        child=serializers.ChoiceField(choices=[tag.name for tag in PreferredPsychologistGenderEnum]),
        required=False
    )
    topic = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )
    preferred_psychologist_age_min = serializers.IntegerField(required=False, allow_null=True)
    preferred_psychologist_age_max = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = QuickClientConsultationRequest
        fields = [
            'psychologist_language',
            'preferred_psychologist_age_min', 'preferred_psychologist_age_max',
            'psychologist_gender', 'topic', 'comments'
        ]

class QuickClientConsultationAnonymousSerializer(NormalizeListFieldsMixin, serializers.ModelSerializer):
    list_fields_to_normalize = ['psychologist_language', 'psychologist_gender', 'topic']
    int_fields_to_normalize = ['preferred_psychologist_age_min', 'preferred_psychologist_age_max']

    preferred_psychologist_age_min = serializers.IntegerField(required=False, allow_null=True)
    preferred_psychologist_age_max = serializers.IntegerField(required=False, allow_null=True)
    psychologist_language = serializers.ListField(
        child=serializers.ChoiceField(choices=[tag.name for tag in CommunicationLanguageEnum]),
        required=False
    )
    psychologist_gender = serializers.ListField(
        child=serializers.ChoiceField(choices=[tag.name for tag in PreferredPsychologistGenderEnum]),
        required=False
    )
    topic = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )

    class Meta:
        model = QuickClientConsultationRequest
        fields = [
            'client_name', 'age', 'gender', 'psychologist_language',
            'preferred_psychologist_age_min', 'preferred_psychologist_age_max',
            'psychologist_gender', 'topic', 'comments'
        ]

    def validate(self, data):
        required_fields = [
            'client_name', 'age', 'gender', 'psychologist_language',
            'preferred_psychologist_age_min', 'preferred_psychologist_age_max',
            'psychologist_gender', 'topic'
        ]
        for field in required_fields:
            if not data.get(field):
                raise serializers.ValidationError({field: "Это поле обязательно."})
        return data

class AuthenticatedSessionRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistSessionRequest
        fields = ["psychologist", "topic", "comments"]

class AnonymousSessionRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistSessionRequest
        fields = ["psychologist", "client_name", "age", "gender", "topic", "comments"]

# Отзыв от клиента психологу
class ReviewSerializer(serializers.ModelSerializer):
    psychologist_name = serializers.SerializerMethodField()
    psychologist_id = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    client_id = serializers.SerializerMethodField()

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

    def get_psychologist_name(self, obj):
        psy = None
        if obj.consultation_request:
            psy = obj.consultation_request.taken_by
        elif obj.session_request:
            psy = obj.session_request.taken_by or obj.session_request.psychologist
        return psy.user.get_full_name() if psy else "Психолог"

    def get_psychologist_id(self, obj):
        psy = None
        if obj.consultation_request:
            psy = obj.consultation_request.taken_by
        elif obj.session_request:
            psy = obj.session_request.taken_by or obj.session_request.psychologist
        return psy.user.id if psy else None

    def get_client_name(self, obj):
        if obj.consultation_request:
            return obj.consultation_request.client_name
        elif obj.session_request:
            return obj.session_request.client_name
        return "Клиент"

    def get_client_id(self, obj):
        if obj.consultation_request:
            return obj.consultation_request.telegram_id
        elif obj.session_request:
            return obj.session_request.telegram_id
        return None

class PsychologistChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)
    confirm_new_password = serializers.CharField(required=True, min_length=8)

    def validate(self, data):
        if data["new_password"] != data["confirm_new_password"]:
            raise serializers.ValidationError({"confirm_new_password": "Пароли не совпадают."})

        user = self.context["request"].user
        if not user.check_password(data["current_password"]):
            raise serializers.ValidationError({"current_password": "Неверный текущий пароль."})

        return data

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user


class EducationBlockSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True)
    year = serializers.IntegerField(required=False, allow_null=True)
    document = Base64FileField(required=False, allow_null=True)
    file_signature = serializers.CharField(required=False, allow_blank=True)

class EducationDocumentSerializer(serializers.ModelSerializer):
    document = serializers.FileField(required=True)
    year = serializers.IntegerField(required=False, allow_null=True)
    title = serializers.CharField(required=False, allow_blank=True)
    file_signature = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = EducationDocument
        fields = ['document', 'year', 'title', 'file_signature']


class PsychologistProfileSerializer(serializers.ModelSerializer):
    profile_id = serializers.IntegerField(source="id", read_only=True)
    full_name = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()
    experience_years = serializers.IntegerField(source='application.experience_years', read_only=True)
    country = serializers.CharField(source='application.service_countries', read_only=True)
    city = serializers.CharField(source='application.service_cities', read_only=True)
    about_me = serializers.CharField(source='application.about_me_ru', read_only=True)
    qualification = serializers.CharField(source='application.qualification', read_only=True)
    profile_picture = serializers.ImageField(write_only=True, required=False)
    profile_picture_url = serializers.SerializerMethodField()

    class Meta:
        model = PsychologistProfile
        fields = [
            'profile_id', 'full_name', 'age', 'qualification',
            'experience_years', 'country', 'city', 'about_me',
            'profile_picture', 'profile_picture_url',
        ]

    def get_full_name(self, obj):
        if obj.application:
            parts = [
                obj.application.last_name_ru,
                obj.application.first_name_ru,
                obj.application.middle_name_ru
            ]
            return " ".join(part for part in parts if part)
        return ""

    def get_age(self, obj):
        """Вычисляет возраст психолога по дате рождения (если есть)"""
        if obj.application and obj.application.birth_date:
            today = date.today()
            bd = obj.application.birth_date
            return today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
        return None

    def get_profile_picture_url(self, obj):
        request = self.context.get('request')
        picture = obj.profile_picture

        if not picture and obj.application and obj.application.profile_picture:
            picture = obj.application.profile_picture

        if picture and request:
            return request.build_absolute_uri(picture.url)
        return None

class PsychologistApplicationSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    birth_date = serializers.DateField()
    gender = serializers.CharField()
    communication_language = serializers.ListField(child=serializers.CharField(), required=False)
    telegram_id = serializers.SerializerMethodField()
    service_countries = serializers.ListField(child=serializers.CharField())
    service_cities = serializers.ListField(child=serializers.CharField())
    about_me_ru = serializers.CharField()
    catalog_description_ru = serializers.CharField()
    qualification = serializers.ListField(child=serializers.CharField(), required=False)
    works_with = serializers.ListField(child=serializers.CharField(), required=False)
    problems_worked_with = serializers.ListField(child=serializers.CharField(), required=False)
    work_methods = serializers.ListField(child=serializers.CharField(), required=False)
    experience_years = serializers.IntegerField()
    academic_degree = serializers.CharField()
    additional_psychologist_directions = serializers.ListField(child=serializers.CharField(), required=False)
    additional_specialization = serializers.ListField(child=serializers.CharField(), required=False)
    associations_memberships = serializers.ListField(child=serializers.CharField(), required=False)
    education = serializers.ListField(child=serializers.CharField())
    education_files = EducationDocumentSerializer(many=True)
    country = serializers.CharField()
    city = serializers.CharField()
    district = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    street_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    building_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    office_address = serializers.CharField()
    office_photo_url = serializers.SerializerMethodField()
    service_sessions = serializers.ListField(child=serializers.DictField())
    is_verified = serializers.BooleanField()
    is_in_catalog = serializers.BooleanField()
    rating_system = serializers.FloatField()
    internal_rating = serializers.FloatField()
    status = serializers.CharField()
    profile_picture_url = serializers.SerializerMethodField()
    purchased_applications = serializers.IntegerField()
    created_at = serializers.DateTimeField(source='created', read_only=True)
    updated_at = serializers.DateTimeField(source='updated', read_only=True)

    class Meta:
        model = PsychologistApplication
        fields = [
            'id', 'full_name', 'telegram_id', 'purchased_applications',
            'first_name_ru', 'last_name_ru', 'middle_name_ru', 'birth_date', 'gender',
            'communication_language', 'service_countries', 'service_cities', 'about_me_ru',
            'catalog_description_ru', 'qualification', 'works_with', 'problems_worked_with',
            'work_methods', 'experience_years', 'academic_degree', 'additional_psychologist_directions',
            'additional_specialization', 'associations_memberships', 'education', 'education_files', 'country',
            'city', 'district', 'street_name', 'building_number', 'office_address', 'office_photo_url', 'service_sessions', 'is_verified',
            'is_in_catalog', 'rating_system', 'internal_rating', 'status', 'created_at', 'updated_at',
            'profile_picture_url'
        ]

    def get_profile_picture_url(self, obj):
        request = self.context.get('request')
        picture = obj.profile_picture

        if not picture and hasattr(obj, 'profile') and obj.profile.profile_picture:
            picture = obj.profile.profile_picture

        if picture and request:
            return request.build_absolute_uri(picture.url)
        return None

    def get_office_photo_url(self, obj):
        request = self.context.get('request')
        if obj.office_photo and request:
            return request.build_absolute_uri(obj.office_photo.url)
        return None

    def get_full_name(self, obj):
        parts = [obj.last_name_ru, obj.first_name_ru, obj.middle_name_ru]
        return " ".join(part for part in parts if part)

    def get_telegram_id(self, obj):
        return obj.user.telegram_id

class SessionItemSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    session_type = serializers.CharField()
    online_offline = serializers.CharField()
    country = serializers.CharField(max_length=100)
    city = serializers.CharField(max_length=100)
    duration = serializers.IntegerField(min_value=1)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    currency = serializers.CharField()

    def to_representation(self, instance):
        result = dict(instance)
        result["price"] = float(result.get("price", 0))
        result["location"] = f"{result.get('country', '')}, {result.get('city', '')}".strip(", ")
        return result

class ServicePriceSerializer(serializers.ModelSerializer):
    service_sessions = SessionItemSerializer(many=True)

    class Meta:
        model = PsychologistApplication
        fields = ['service_sessions']

    def update(self, instance, validated_data):
        new_sessions = validated_data.get('service_sessions', [])

        existing_sessions = instance.service_sessions if isinstance(instance.service_sessions, list) else []
        existing_sessions_dict = {str(s.get("id")): s for s in existing_sessions if "id" in s}

        updated_sessions = []

        for session in new_sessions:
            session_id = str(session.get("id") or uuid.uuid4())
            session["id"] = session_id
            session["price"] = float(session["price"])

            if session_id in existing_sessions_dict:
                existing_sessions_dict[session_id].update(session)
                updated_sessions.append(existing_sessions_dict[session_id])
            else:
                updated_sessions.append(session)

        instance.service_sessions = updated_sessions
        instance.save(update_fields=["service_sessions"])
        return instance

    def to_representation(self, instance):
        sessions = instance.service_sessions if isinstance(instance.service_sessions, list) else []
        return {
            "service_sessions": SessionItemSerializer(sessions, many=True).data
        }

# загрузка доков
class EducationBlockUpdateSerializer(serializers.Serializer):
    education_block = serializers.ListField(child=EducationBlockSerializer())

    def update(self, instance, validated_data):
        education_block = validated_data.get("education_block", [])

        # Обновляем education (JSONField)
        json_edu = []
        for item in education_block:
            if "document" not in item:
                json_edu.append({"title": item.get("title"), "year": item.get("year")})
        instance.education = json_edu

        # Обновляем education_files (удаляем старые и добавляем новые)
        instance.education_files.clear()
        for item in education_block:
            if item.get("document"):
                format, data = item["document"].split(";base64,")
                ext = format.split("/")[-1]
                file = ContentFile(base64.b64decode(data), name=f"{item.get('title', 'file')}.{ext}")
                doc = EducationDocument.objects.create(
                    psychologist_application=instance,
                    document=file,
                    title=item.get("title", ""),
                    year=item.get("year"),
                    file_signature=item.get("file_signature", "")
                )
                instance.education_files.add(doc)

        instance.save()
        return instance

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

class TopicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topic
        fields = '__all__'

class CatalogSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    full_name = serializers.ReadOnlyField()
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
            'full_name',
            'qualification',
            'academic_degree',
            'catalog_description_ru',
            'session_price',
            'is_verified',
            'requests_count',
            'average_rating',
            'reviews_count',
        ]

    def get_qualification(self, obj) -> Optional[str]:
        return getattr(obj.application, 'qualification', None) if obj.application else None

    def get_academic_degree(self, obj) -> Optional[str]:
        return getattr(obj.application, 'academic_degree', None) if obj.application else None

    def get_catalog_description_ru(self, obj) -> Optional[str]:
        return getattr(obj.application, 'catalog_description_ru', None) if obj.application else None

    def get_session_price(self, obj) -> Optional[float]:
        if obj.application and isinstance(obj.application.service_sessions, list):
            for session in obj.application.service_sessions:
                if isinstance(session, dict) and 'price' in session:
                    return session['price']  # Возвращаем цену первого сеанса
        return None

    def get_average_rating(self, obj) -> Optional[float]:
        return obj.get_average_rating()

    def get_reviews_count(self, obj) -> Optional[int]:
        return obj.get_reviews_count()

#для вьющек сериализаторы по форме/профилю психолога
class PersonalInfoSerializer(serializers.ModelSerializer):
    profile_picture_url = serializers.SerializerMethodField()
    telegram_id = serializers.SerializerMethodField()

    class Meta:
        model = PsychologistApplication
        fields = [
            'first_name_ru', 'last_name_ru', 'middle_name_ru',
            'birth_date', 'gender', 'communication_language',
            'service_countries', 'service_cities', 'telegram_id',
            'about_me_ru', 'catalog_description_ru', 'profile_picture_url', 
            'profile_picture'
        ]

    def get_telegram_id(self, obj):
        return obj.user.telegram_id

    def get_profile_picture_url(self, obj):
        request = self.context.get('request')
        picture = obj.profile_picture

        if not picture and obj.application and obj.application.profile_picture:
            picture = obj.application.profile_picture

        if picture and request:
            return request.build_absolute_uri(picture.url)
        return None

    def update(self, instance, validated_data):
        profile_picture = validated_data.pop('profile_picture', None)
        if profile_picture:
            instance.profile_picture = profile_picture
        return super().update(instance, validated_data)

# Квалификация психолога
class EducationDocumentInputSerializer(serializers.Serializer):
    document = Base64FileField(required=True)
    year = serializers.IntegerField(required=False, allow_null=True)
    title = serializers.CharField(required=False, allow_blank=True)
    file_signature = serializers.CharField(required=False, allow_blank=True)

class OfficeInfoItemSerializer(serializers.Serializer):
    country = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True)
    district = serializers.CharField(required=False, allow_blank=True)
    street_name = serializers.CharField(required=False, allow_blank=True)
    building_number = serializers.CharField(required=False, allow_blank=True)
    office_phone = serializers.CharField(required=False, allow_blank=True)
    photo = serializers.URLField(required=False, allow_blank=True)

class QualificationSerializer(serializers.ModelSerializer):
    qualification = serializers.CharField()
    works_with = serializers.ListField(child=serializers.CharField(), required=False)
    problems_worked_with = serializers.ListField(child=serializers.CharField(), required=False)
    work_methods = serializers.ListField(child=serializers.CharField(), required=False)
    experience_years = serializers.IntegerField()
    academic_degree = serializers.CharField(allow_null=True)
    additional_psychologist_directions = serializers.ListField(child=serializers.CharField(), required=False)
    additional_specialization = serializers.ListField(child=serializers.CharField(), required=False)
    associations_memberships = serializers.ListField(child=serializers.CharField(), required=False)
    education_block = serializers.ListField(child=EducationBlockSerializer(), required=False)
    office_photo = Base64ImageField(write_only=True, required=False)
    office_photo_url = serializers.SerializerMethodField()

    office_info = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField(), required=False),
        required=False
    )

    class Meta:
        model = PsychologistApplication
        fields = [
            'qualification', 'works_with', 'problems_worked_with', 'work_methods',
            'experience_years', 'academic_degree', 'additional_psychologist_directions', 'additional_specialization', 'associations_memberships',
            'education_block', 'office_info', "office_photo", "office_photo_url"
        ]

    def to_representation(self, instance):
        # Собираем education + education_files в единый список
        base = []

        # Из JSON поля
        for item in instance.education or []:
            if isinstance(item, dict):
                base.append({"title": item.get("title"), "year": item.get("year")})

        # Из файлов
        for doc in instance.education_files.all():
            base.append({
                "title": doc.title,
                "year": doc.year,
                "file_signature": doc.file_signature,
                "document": self.context.get("request").build_absolute_uri(doc.document.url)
                if doc.document and self.context.get("request") else None
            })

        rep = super().to_representation(instance)
        rep["education_block"] = base
        rep["office_info"] = instance.office_info
        return rep

    def update(self, instance, validated_data):
        education_block = validated_data.pop("education_block", [])
        office_info = validated_data.pop("office_info", None)
        office_photo = validated_data.pop("office_photo", None)
        if office_photo:
            instance.office_photo = office_photo
        if office_info is not None:
            instance.office_info = office_info

        # Обновляем education (JSONField)
        json_edu = []
        for item in education_block:
            if "document" not in item:
                json_edu.append({"title": item.get("title"), "year": item.get("year")})
        instance.education = json_edu

        # Обновляем education_files (удаляем старые и добавляем новые)
        instance.education_files.clear()
        for item in education_block:
            if item.get("document"):
                format, data = item["document"].split(";base64,")
                ext = format.split("/")[-1]
                file = ContentFile(base64.b64decode(data), name=f"{item.get('title', 'file')}.{ext}")
                doc = EducationDocument.objects.create(
                    psychologist_application=instance,
                    document=file,
                    title=item.get("title", ""),
                    year=item.get("year"),
                    file_signature=item.get("file_signature", "")
                )
                instance.education_files.add(doc)

        instance.save()
        return super().update(instance, validated_data)

    def get_office_photo_url(self, obj):
        request = self.context.get("request")
        if obj.office_photo and request:
            return request.build_absolute_uri(obj.office_photo.url)
        return None

class UserIdSerializer(serializers.ModelSerializer):
    telegram_id = serializers.CharField()
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'telegram_id', 'full_name', 'is_psychologist']

    def get_full_name(self, obj):
        parts = [
            getattr(obj, 'last_name_ru', None),
            getattr(obj, 'first_name_ru', None),
            getattr(obj, 'middle_name_ru', None)
        ]
        return " ".join(part for part in parts if part)

#admin
class UpdatePsychologistApplicationStatusSerializer(serializers.ModelSerializer):
    status = serializers.ChoiceField(choices=PsychologistApplication.STATUS_CHOICES)

    class Meta:
        model = PsychologistApplication
        fields = ['status']

    def update(self, instance, validated_data):
        instance.status = validated_data.get('status', instance.status)
        instance.save()
        return instance

