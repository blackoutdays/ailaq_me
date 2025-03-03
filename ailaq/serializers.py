from django.contrib.auth import get_user_model
from rest_framework import serializers
from ailaq.models import CustomUser, PsychologistApplication, PsychologistProfile, ClientProfile, PsychologistLevel, \
    Review, BuyRequest, Topic, QuickClientConsultationRequest
from django.conf import settings
from hashlib import sha256
import hmac
import time
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
import random

CustomUser = get_user_model()

class CustomUserCreationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = CustomUser
        fields = ['telegram_id', 'email', 'password', 'password_confirm', 'is_psychologist']

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

        return user

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        if not data.get("email") or not data.get("password"):
            raise serializers.ValidationError("Email и пароль обязательны.")
        return data

class PsychologistProfileSerializer(serializers.ModelSerializer):
    average_rating = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()
    catalog_description_ru = serializers.CharField(source='application.catalog_description_ru', read_only=True)
    session_price = serializers.DecimalField(source='application.session_price', max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = PsychologistProfile
        fields = [
            'id', 'user', 'catalog_description_ru', 'session_price',
            'is_in_catalog', 'is_verified', 'requests_count', 'average_rating', 'reviews',
        ]

    def get_average_rating(self, obj):
        return obj.get_average_rating()

    def get_reviews(self, obj):
        reviews = Review.objects.filter(session__psychologist=obj)
        return [
            {
                "id": review.id,
                "rating": review.rating,
                "text": review.text,
                "created_at": review.created_at,
            }
            for review in reviews
        ]

class PsychologistApplicationSerializer(serializers.ModelSerializer):
    user = serializers.ReadOnlyField(source="user.email")
    session_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = PsychologistApplication
        exclude = ['user']

    def create(self, validated_data):
        user = self.context['request'].user
        return PsychologistApplication.objects.create(user=user, **validated_data)

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

# Профиль клиента
class ClientProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientProfile
        fields = '__all__'

class PsychologistLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistLevel
        fields = '__all__'

# Отзыв от клиента психологу
class ReviewSerializer(serializers.ModelSerializer):
    psychologist_name = serializers.ReadOnlyField(source='psychologist_id.user.email')
    client_name = serializers.ReadOnlyField(source='client.user.email')
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

class CatalogSerializer(serializers.ModelSerializer):
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
            'id',
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

    def get_first_name_ru(self, obj) -> str | None:
        return getattr(obj.application, 'first_name_ru', None)

    def get_last_name_ru(self, obj) -> str | None:
        return getattr(obj.application, 'last_name_ru', None)

    def get_middle_name_ru(self, obj) -> str | None:
        return getattr(obj.application, 'middle_name_ru', None)

    def get_qualification(self, obj) -> str | None:
        return getattr(obj.application, 'qualification', None)

    def get_academic_degree(self, obj) -> str | None:
        return getattr(obj.application, 'academic_degree', None)

    def get_catalog_description_ru(self, obj) -> str | None:
        return getattr(obj.application, 'catalog_description_ru', None)

    def get_session_price(self, obj) -> float | None:
        return getattr(obj.application, 'session_price', None)

    def get_average_rating(self, obj) -> float | None:
        return obj.get_average_rating()

    def get_reviews_count(self, obj) -> int | None:
        return obj.get_reviews_count()

class BuyRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuyRequest
        fields = '__all__'

#для вьющек сериализаторы по форме/профилю психолога
class PersonalInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistApplication
        fields = [
            'first_name_ru',
            'last_name_ru',
            'middle_name_ru',
            'communication_language', 'gender', 'city', 'telegram_id', 'email',
            'about_me_ru', 'catalog_description_ru'
        ]

# Квалификация психолога
class QualificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistApplication
        fields = [
            'qualification', 'works_with', 'problems_worked_with', 'work_methods',
            'practice_start_date', 'academic_degree', 'psychologist_directions',
            'child_psychologist_directions', 'coach_directions', 'additional_specialization',
            'work_features', 'education', 'education_files'
        ]

class ServicePriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistApplication
        fields = [
            'session_duration', 'session_price', 'session_discount',
            'online_session_duration', 'online_session_price', 'online_session_discount',
            'couple_session_duration', 'couple_session_price', 'couple_session_discount',
            'couple_online_session_duration', 'couple_online_session_price', 'couple_online_session_discount',
            'office_address', 'office_photo'
        ]

# 1. faq вопрос/ы и ответ/ы
class FAQSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=255)
    answer = serializers.CharField(max_length=1000)

# 2. faq вопрос/ы и ответ/ы
class FAQListSerializer(serializers.Serializer):
    faqs = serializers.ListField(
        child=FAQSerializer(),
        required=False  # Чтобы поддерживать пустые списки
    )

#загрузка доков
class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PsychologistApplication
        fields = ['passport_document', 'education_files']

class TelegramAuthSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    first_name = serializers.CharField(required=False)
    username = serializers.CharField(required=False)
    auth_date = serializers.IntegerField()
    hash = serializers.CharField()

    def validate(self, data):
        """
        Проверяем Telegram авторизацию.
        """
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
        """
        Создание или обновление пользователя на основе Telegram ID.
        """
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

class TopicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topic
        fields = '__all__'

class QuickClientConsultationRequestSerializer(serializers.ModelSerializer):
    additional_topics = TopicSerializer(many=True, required=False, help_text="Список дополнительных тем")
    client_name = serializers.CharField(help_text="Имя клиента, как к вам обращаться")
    birth_date = serializers.DateField(help_text="Дата рождения клиента")
    gender = serializers.ChoiceField(
        choices=[('MALE', 'Мужской'), ('FEMALE', 'Женский')],
        help_text="Пол клиента"
    )
    psychologist_language = serializers.ChoiceField(
        choices=[('RU', 'Русский'), ('EN', 'Английский'), ('KZ', 'Казахский')],
        help_text="Предпочтительный язык общения"
    )
    verification_code = serializers.CharField(read_only=True, help_text="Код для привязки Telegram")

    class Meta:
        model = QuickClientConsultationRequest
        fields = [
            'client_name', 'birth_date', 'gender', 'psychologist_language',
            'preferred_psychologist_age', 'psychologist_gender', 'topic',
            'comments', 'additional_topics', 'verification_code'
        ]

    def create(self, validated_data):
        topics_data = validated_data.pop('additional_topics', [])
        verification_code = str(random.randint(1000, 9999))

        consultation_request = QuickClientConsultationRequest.objects.create(
            verification_code=verification_code, **validated_data
        )

        # Обработка списка: извлекаем ID, если переданы объекты
        topic_ids = []
        for topic in topics_data:
            if isinstance(topic, dict):  # Если передан объект, извлекаем ID
                topic_id = topic.get("id")
                if topic_id:
                    topic_ids.append(topic_id)
            else:  # Если передан ID, используем его напрямую
                topic_ids.append(topic)

        consultation_request.additional_topics.set(topic_ids)
        return consultation_request