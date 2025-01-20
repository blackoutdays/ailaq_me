from django.contrib.auth import get_user_model
from rest_framework import serializers
from ailaq.models import CustomUser, PsychologistApplication, PsychologistProfile, ClientProfile, PsychologistLevel, \
    Review, BuyRequest

CustomUser = get_user_model()

class CustomUserCreationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    role = serializers.CharField(read_only=True)  # role доступно только для чтения

    class Meta:
        model = CustomUser
        fields = ['email', 'password', 'is_psychologist', 'role']

    def create(self, validated_data):
        is_psychologist = validated_data.get('is_psychologist', False)

        print(f"Received is_psychologist: {is_psychologist}")  # Лог для проверки

        # Создание пользователя
        user = CustomUser.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            is_psychologist=is_psychologist,
        )

        if is_psychologist:
            user.wants_to_be_psychologist = True
            user.save()

            # Проверяем существование заявки
            PsychologistApplication.objects.get_or_create(
                user=user,
                defaults={'status': 'PENDING'}
            )

            # Проверяем существование профиля
            PsychologistProfile.objects.get_or_create(
                user=user,
                defaults={'is_verified': False, 'is_in_catalog': False}
            )

        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        """
        Проверка наличия email и пароля.
        """
        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            raise serializers.ValidationError("Email and password are required.")

        return data

class PsychologistProfileSerializer(serializers.ModelSerializer):
    average_rating = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()
    catalog_description_ru = serializers.CharField(source='application.catalog_description_ru', read_only=True)
    session_price = serializers.DecimalField(source='application.session_price', max_digits=10, decimal_places=2, read_only=True)
    session_discount = serializers.DecimalField(source='application.session_discount', max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = PsychologistProfile
        fields = [
            'id',
            'user',
            'catalog_description_ru',
            'session_price',
            'session_discount',
            'is_in_catalog',
            'is_verified',
            'requests_count',
            'average_rating',
            'reviews',
        ]

    def get_average_rating(self, obj):
        """
        Рассчитывает средний рейтинг психолога.
        """
        return obj.get_average_rating()

    def get_reviews(self, obj):
        """
        Возвращает список отзывов психолога.
        """
        reviews_qs = obj.sessions.filter(status='COMPLETED').values_list('review', flat=True)
        reviews = Review.objects.filter(id__in=reviews_qs)
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
    class Meta:
        model = PsychologistApplication
        exclude = ['user']  # Поле user исключается из входящих данных

    def create(self, validated_data):
        """
        Создаёт заявку психолога, добавляя пользователя из контекста.
        """
        user = self.context['request'].user  # Получаем текущего пользователя из контекста
        return PsychologistApplication.objects.create(user=user, **validated_data)

    def update(self, instance, validated_data):
        """
        Обновляет существующую заявку психолога.
        """
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
    class Meta:
        model = Review
        fields = "__all__"


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

    def get_first_name_ru(self, obj):
        return getattr(obj.application, 'first_name_ru', None)

    def get_last_name_ru(self, obj):
        return getattr(obj.application, 'last_name_ru', None)

    def get_middle_name_ru(self, obj):
        return getattr(obj.application, 'middle_name_ru', None)

    def get_qualification(self, obj):
        return getattr(obj.application, 'qualification', None)

    def get_academic_degree(self, obj):
        return getattr(obj.application, 'academic_degree', None)

    def get_catalog_description_ru(self, obj):
        return getattr(obj.application, 'catalog_description_ru', None)

    def get_session_price(self, obj):
        return getattr(obj.application, 'session_price', None)

    def get_average_rating(self, obj):
        """
        Возвращает средний рейтинг психолога.
        """
        return obj.get_average_rating()

    def get_reviews_count(self, obj):
        """
        Возвращает количество отзывов для завершенных сессий психолога.
        """
        return Review.objects.filter(session__psychologist=obj, session__status='COMPLETED').count()

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