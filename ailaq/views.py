#views
import time
import hmac
from datetime import datetime
from asgiref.sync import async_to_sync
from django.http.multipartparser import MultiPartParser
from django.utils.timezone import now, make_aware
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from hashlib import sha256
from rest_framework import status, viewsets
from ailaq.tasks import send_email_async
from rest_framework.generics import GenericAPIView, ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from config import settings
from .emails import send_rejection_email, send_approval_email, send_email
from .models import PsychologistProfile, PsychologistApplication, ClientProfile, CustomUser, \
    PsychologistFAQ, Review, Session, QuickClientConsultationRequest, Topic, EducationDocument
from .serializers import (
    CustomUserCreationSerializer,
    LoginSerializer, PsychologistApplicationSerializer, ClientProfileSerializer, ReviewSerializer, CatalogSerializer,
    PersonalInfoSerializer, QualificationSerializer, DocumentSerializer,
    FAQListSerializer, TopicSerializer, QuickClientConsultationRequestSerializer, TelegramAuthSerializer,
    ServicePriceSerializer, EmptySerializer, SessionCreateSerializer, SessionSerializer, PsychologistProfileSerializer
)
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.pagination import PageNumberPagination
from django.views.decorators.csrf import csrf_exempt
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils.decorators import method_decorator
import telegram
import logging

logger = logging.getLogger(__name__)

bot = telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN)

class RegisterUserView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Авторизация/Регистрация"],
        request=CustomUserCreationSerializer,
        responses={201: OpenApiResponse(description="Пользователь успешно зарегистрирован.")},
    )
    def post(self, request):
        serializer = CustomUserCreationSerializer(data=request.data)

        if serializer.is_valid():
            password = serializer.validated_data["password"]
            password_confirm = serializer.validated_data["password_confirm"]

            # Проверяем совпадение паролей
            if password != password_confirm:
                return Response({"password_confirm": "Пароли не совпадают."}, status=status.HTTP_400_BAD_REQUEST)

            # Проверяем сложность пароля
            try:
                validate_password(password)
            except ValidationError as e:
                return Response({"password": list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

            user = serializer.save()
            if user.wants_to_be_psychologist:
                PsychologistApplication.objects.get_or_create(user=user)

            refresh = RefreshToken.for_user(user)
            return Response(
                {
                    "access_token": str(refresh.access_token),
                    "refresh_token": str(refresh),
                    "role": "психолог" if user.wants_to_be_psychologist else "клиент"
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# Авторизация
class LoginView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Авторизация/Регистрация"],
        request=LoginSerializer,
        responses={200: OpenApiResponse(description="Успешный вход в систему.")},
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)

        if serializer.is_valid():
            email = serializer.validated_data["email"]
            password = serializer.validated_data["password"]
            user = CustomUser.objects.filter(email=email).first()

            if not user:
                return Response({"error": "Пользователь с таким email не найден."}, status=status.HTTP_400_BAD_REQUEST)

            if not user.check_password(password):
                return Response({"error": "Неверный пароль."}, status=status.HTTP_400_BAD_REQUEST)

            refresh = RefreshToken.for_user(user)
            return Response(
                {
                    "access_token": str(refresh.access_token),
                    "refresh_token": str(refresh),
                    "role": "психолог" if user.is_psychologist else "клиент"
                },
                status=status.HTTP_200_OK,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class QuickClientConsultationAPIView(APIView):

    @extend_schema(
        tags=["Клиент - быстрая консультация"],
        request=QuickClientConsultationRequestSerializer,
        responses={201: QuickClientConsultationRequestSerializer},
        description="Создание запроса на быструю консультацию и генерация ссылки на виджет Telegram."
    )
    def post(self, request):
        serializer = QuickClientConsultationRequestSerializer(data=request.data)
        if serializer.is_valid():
            consultation_request = serializer.save()

            # вызов асинхронного метода в синхронном контексте
            bot_info = async_to_sync(self.get_bot_info)()
            redirect_url = f"https://t.me/{bot_info.username}?start=quick_{consultation_request.verification_code}"

            # Проверяем, есть ли telegram_id, и отправляем сообщение
            if consultation_request.telegram_id:
                async_to_sync(self.send_telegram_message)(consultation_request.telegram_id, consultation_request.pk)

            return JsonResponse(
                {
                    "message": "Заявка создана",
                    "redirect_url": redirect_url,
                    "verification_code": consultation_request.verification_code,
                    "consultation_request": serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        return JsonResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @staticmethod
    async def get_bot_info():
        return await bot.get_me()

    @staticmethod
    async def send_telegram_message(chat_id, consultation_id):
        await bot.send_message(
            chat_id=chat_id,
            text=f"Ваша заявка принята. ID заявки: {consultation_id}"
        )

# Список психологов с фильтрацией каталог
class CatalogPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

class CatalogViewSet(ReadOnlyModelViewSet):
    """Каталог психологов с фильтрацией, сортировкой и пагинацией """
    queryset = PsychologistProfile.objects.filter(is_in_catalog=True).select_related('application')
    serializer_class = CatalogSerializer
    pagination_class = CatalogPagination
    permission_classes = [AllowAny]

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = {
        'is_verified': ['exact'],
        'is_in_catalog': ['exact'],
        'requests_count': ['gte', 'lte'],
    }
    ordering_fields = ['application__id', 'requests_count']
    ordering = ['application__id']

    @extend_schema(
        tags=["Каталог психологов"],
        description="Получить список психологов с фильтрацией, сортировкой и пагинацией.",
        parameters=[
            OpenApiParameter("is_verified", description="Фильтр по верификации (true/false)", required=False, type=bool),
            OpenApiParameter("is_in_catalog", description="Фильтр по наличию в каталоге (true/false)", required=False, type=bool),
            OpenApiParameter("requests_count__gte", description="Минимальное количество запросов", required=False, type=int),
            OpenApiParameter("requests_count__lte", description="Максимальное количество запросов", required=False, type=int),
            OpenApiParameter("ordering", description="Сортировка (application__id, requests_count)", required=False, type=str),
            OpenApiParameter("page", description="Номер страницы", required=False, type=int),
            OpenApiParameter("page_size", description="Количество элементов на странице (по умолчанию 10)", required=False, type=int),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

class ClientProfileViewSet(viewsets.ModelViewSet):
    queryset = ClientProfile.objects.all()
    serializer_class = ClientProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Возвращает профиль только текущего пользователя."""
        return ClientProfile.objects.filter(user=self.request.user)

    @extend_schema(
        tags=["Клиент"],
        description="Получить профиль текущего клиента.",
        responses={200: ClientProfileSerializer},
    )
    def list(self, request, *args, **kwargs):
        """Возвращает профиль текущего аутентифицированного клиента."""
        profile = self.get_queryset().first()
        if profile:
            serializer = self.get_serializer(profile)
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response({"detail": "Профиль клиента не найден."}, status=status.HTTP_404_NOT_FOUND)

    @extend_schema(
        description="Создать или обновить профиль клиента.",
        request=ClientProfileSerializer,
        responses={200: ClientProfileSerializer},
    )
    def create(self, request, *args, **kwargs):
        """Создаёт профиль клиента или обновляет, если он уже существует."""
        profile, created = ClientProfile.objects.get_or_create(user=request.user)
        serializer = self.get_serializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(user=request.user)
            status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            return Response(serializer.data, status=status_code)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        description="Частичное обновление профиля клиента.",
        request=ClientProfileSerializer,
        responses={200: ClientProfileSerializer},
    )
    def partial_update(self, request, *args, **kwargs):
        """Обновляет профиль текущего клиента."""
        profile = self.get_queryset().first()
        if not profile:
            return Response({"detail": "Профиль клиента не найден."}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        description="Удалить профиль клиента.",
        responses={204: None},
    )
    def destroy(self, request, *args, **kwargs):
        """Удаляет профиль текущего клиента."""
        profile = self.get_queryset().first()
        if not profile:
            return Response({"detail": "Профиль не найден."}, status=status.HTTP_404_NOT_FOUND)
        profile.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class PublicPsychologistProfileView(APIView):
    """
    🔹 Публичный API для получения профиля психолога (для клиентов)
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Публичный профиль психолога"],
        description="Этот эндпоинт позволяет клиенту получить информацию о психологе по его ID.",
        responses={200: PsychologistProfileSerializer}
    )
    def get(self, request, psychologist_id: int):
        psychologist = get_object_or_404(PsychologistProfile, user_id=psychologist_id)
        serializer = PsychologistProfileSerializer(psychologist)
        return Response(serializer.data, status=status.HTTP_200_OK)

class PublicQualificationView(APIView):
    """
    🔹 Позволяет всем пользователям (и клиентам) получать квалификацию психолога.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Публичный профиль психолога"],
        summary="Получить публичную квалификацию психолога",
        responses={200: QualificationSerializer}
    )
    def get(self, request, psychologist_id: int):
        application = get_object_or_404(PsychologistApplication, user_id=psychologist_id)
        serializer = QualificationSerializer(application)
        return Response(serializer.data, status=status.HTTP_200_OK)

class PublicServicePriceView(APIView):
    """
    🔹 Позволяет всем пользователям видеть стоимость услуг психолога.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Публичный профиль психолога"],
        summary="Получить стоимость услуг психолога",
        responses={200: ServicePriceSerializer}
    )
    def get(self, request, psychologist_id: int):
        application = get_object_or_404(PsychologistApplication, user_id=psychologist_id)
        serializer = ServicePriceSerializer(application)
        return Response(serializer.data, status=status.HTTP_200_OK)

class PublicReviewListView(APIView):
    """
    🔹 Клиенты могут просматривать отзывы о психологе с пагинацией.
    """
    permission_classes = [AllowAny]  # Доступ для всех клиентов
    pagination_class = PageNumberPagination  # Используем стандартную пагинацию

    @extend_schema(
        tags=["Публичный профиль психолога"],
        summary="Получить список отзывов о психологе",
        responses={200: ReviewSerializer(many=True)}
    )
    def get(self, request, psychologist_id: int):
        psychologist = get_object_or_404(PsychologistProfile, user_id=psychologist_id)
        reviews = Review.objects.filter(psychologist=psychologist).order_by("-created_at")

        # Используем встроенную пагинацию APIView
        paginator = self.pagination_class()
        paginated_reviews = paginator.paginate_queryset(reviews, request, view=self)

        if paginated_reviews is not None:
            serializer = ReviewSerializer(paginated_reviews, many=True)
            return paginator.get_paginated_response(serializer.data)

        # Если пагинация не требуется, вернуть просто список отзывов
        serializer = ReviewSerializer(reviews, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class PublicFAQView(APIView):
    """
    🔹 Клиенты могут просматривать FAQ психолога.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Публичный профиль психолога"],
        summary="Получить список FAQ психолога",
        responses={200: FAQListSerializer}
    )
    def get(self, request, psychologist_id: int):
        application = get_object_or_404(PsychologistApplication, user_id=psychologist_id)
        faqs = application.faqs.all()
        serializer = FAQListSerializer({"faqs": faqs})
        return Response(serializer.data, status=status.HTTP_200_OK)

# Получение профиля психолога

class PsychologistSelfProfileView(APIView):
    """
    🔹 API для получения и редактирования личного профиля психолога
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Психолог"],
        description="Возвращает профиль текущего авторизованного психолога.",
        responses={200: PsychologistProfileSerializer}
    )
    def get(self, request):
        try:
            psychologist_profile = request.user.psychologist_profile
        except PsychologistProfile.DoesNotExist:
            return Response({"error": "Вы не зарегистрированы как психолог."}, status=status.HTTP_403_FORBIDDEN)

        serializer = PsychologistProfileSerializer(psychologist_profile)
        return Response(serializer.data, status=status.HTTP_200_OK)

# Получение полного профиля психолога
class PsychologistProfileView(APIView):
    """
    Получает весь профиль психолога, включая отзывы.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Психолог"],
        summary="Получить полный профиль заявки психолога",
        description="Возвращает данные заявки психолога, включая личную информацию, квалификацию, услуги, FAQ и отзывы.",
        responses={200: OpenApiResponse(description="Полная заявка психолога")}
    )
    def get(self, request):
        try:
            # Получаем заявку психолога
            application = PsychologistApplication.objects.filter(user=request.user).first()

            if not application:
                logger.error(f"Заявка психолога не найдена для пользователя {request.user.id}")
                return Response({"error": "Заявка психолога не найдена."}, status=status.HTTP_404_NOT_FOUND)

            # Получаем отзывы (если они привязаны к заявке)
            reviews = Review.objects.filter(psychologist__application=application).order_by("-created_at")
            reviews_serializer = ReviewSerializer(reviews, many=True)

            # Формируем данные для ответа
            data = {
                "personal_info": PersonalInfoSerializer(application).data,
                "qualification": QualificationSerializer(application).data,
                "service_price": ServicePriceSerializer(application).data,
                "faq": FAQListSerializer({"faqs": application.faqs.all()}).data,
                "reviews": reviews_serializer.data,
            }

            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Ошибка при получении профиля психолога: {str(e)}")
            return Response({"error": "Не удалось получить профиль психолога."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Сохранение и получение личной информации психолога
class PersonalInfoView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Психолог"],
        summary="Получить личную информацию психолога",
        responses={200: PersonalInfoSerializer}
    )
    def get(self, request):
        try:
            application = get_object_or_404(PsychologistApplication, user=request.user)
            serializer = PersonalInfoSerializer(application)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Ошибка при получении личной информации: {str(e)}")
            return Response({"error": "Не удалось получить личную информацию."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        tags=["Психолог"],
        summary="Сохранить личную информацию психолога",
        request=PersonalInfoSerializer,
        responses={200: PersonalInfoSerializer}
    )
    def post(self, request):
        try:
            # Проверяем, существует ли уже заявка
            application, created = PsychologistApplication.objects.get_or_create(user=request.user)

            if created:
                logger.info(f"Создана новая заявка для пользователя {request.user.id}")
            else:
                logger.info(f"Используется существующая заявка для пользователя {request.user.id}")

            # Сериализуем данные
            serializer = PersonalInfoSerializer(application, data=request.data, partial=True)

            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Ошибка при сохранении личной информации: {str(e)}")
            return Response({"error": "Не удалось сохранить личную информацию."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Сохранение и получение квалификации
class QualificationView(APIView):
    """
    Сохранение квалификации психолога, включая загрузку файлов.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        tags=["Психолог"],
        summary="Получить квалификацию психолога",
        responses={200: QualificationSerializer}
    )
    def get(self, request):
        try:
            application = get_object_or_404(PsychologistApplication, user=request.user)
            serializer = QualificationSerializer(application)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Ошибка при получении квалификации: {str(e)}")
            return Response({"error": "Не удалось получить квалификацию."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        tags=["Психолог"],
        summary="Сохранить квалификацию психолога",
        request=QualificationSerializer,
        responses={200: QualificationSerializer}
    )
    def post(self, request):
        try:
            application = get_object_or_404(PsychologistApplication, user=request.user)
            serializer = QualificationSerializer(application, data=request.data, partial=True)

            if serializer.is_valid():
                # Сохранение полей квалификации
                serializer.save()

                # Обработка загружаемых файлов
                office_photo = serializer.validated_data.get('office_photo')
                education_files = serializer.validated_data.get('education_files', [])

                # Сохранение фото офиса
                if office_photo:
                    application.office_photo = office_photo

                # Сохранение документов об образовании
                for file_data in education_files:
                    document = file_data.get('document')
                    year = file_data.get('year')
                    title = file_data.get('title') or document.name
                    file_signature = file_data.get('file_signature', "")

                    EducationDocument.objects.create(
                        psychologist_application=application,
                        document=document,
                        year=year,
                        title=title,
                        file_signature=file_signature
                    )

                application.save()

                return Response(serializer.data, status=status.HTTP_200_OK)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Ошибка при сохранении квалификации: {str(e)}")
            return Response(
                {"error": "Не удалось сохранить квалификацию.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# Сохранение и получение стоимости услуг
class ServicePriceView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Психолог"],
        summary="Получить стоимость услуг психолога",
        responses={200: ServicePriceSerializer}
    )
    def get(self, request):
        try:
            application = get_object_or_404(PsychologistApplication, user=request.user)
            serializer = ServicePriceSerializer(application)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Ошибка при получении стоимости услуг: {str(e)}")
            return Response({"error": "Не удалось получить стоимость услуг."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        tags=["Психолог"],
        summary="Сохранить стоимость услуг психолога",
        request=ServicePriceSerializer,
        responses={200: ServicePriceSerializer}
    )
    def post(self, request):
        try:
            application = get_object_or_404(PsychologistApplication, user=request.user)
            serializer = ServicePriceSerializer(application, data=request.data, partial=True)

            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Ошибка при сохранении стоимости услуг: {str(e)}")
            return Response({"error": "Не удалось сохранить стоимость услуг."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Сохранение и получение FAQ психолога
class FAQView(APIView):
    """
    Получение и сохранение FAQ психолога.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Психолог"],
        operation_id="get_faqs",
        summary="Получить список FAQ текущего психолога.",
        responses={200: FAQListSerializer, 404: {"description": "FAQ не найдены."}},
    )
    def get(self, request):
        try:
            application = get_object_or_404(PsychologistApplication, user=request.user)
            faqs = application.faqs.all()

            serializer = FAQListSerializer({"faqs": faqs})
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Ошибка при получении FAQ: {str(e)}")
            return Response({"error": "Не удалось получить FAQ."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        tags=["Психолог"],
        operation_id="update_faq",
        summary="Сохранить список FAQ (заменяет все старые вопросы).",
        request=FAQListSerializer,
        responses={200: {"description": "FAQ сохранены успешно."}, 400: {"description": "Ошибка валидации."}},
    )
    def post(self, request):
        try:
            application = get_object_or_404(PsychologistApplication, user=request.user)

            serializer = FAQListSerializer(data=request.data)
            if serializer.is_valid():
                application.faqs.all().delete()

                faqs_data = serializer.validated_data.get("faqs", [])
                new_faqs = [PsychologistFAQ(application=application, **faq) for faq in faqs_data]

                PsychologistFAQ.objects.bulk_create(new_faqs)

                return Response({"message": "FAQ сохранены успешно."}, status=status.HTTP_200_OK)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Ошибка при сохранении FAQ: {str(e)}")
            return Response({"error": "Не удалось сохранить FAQ."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Загрузка документов
class DocumentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Психолог"],
        request=DocumentSerializer,
        responses={200: DocumentSerializer}
    )
    def patch(self, request):
        try:
            application = get_object_or_404(PsychologistApplication, user=request.user)

            if not request.FILES:
                return Response({"error": "Не загружены файлы."}, status=status.HTTP_400_BAD_REQUEST)

            serializer = DocumentSerializer(application, data=request.data, partial=True)

            if serializer.is_valid():
                serializer.save()
                return Response({"message": "Документы обновлены успешно."}, status=status.HTTP_200_OK)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except PsychologistApplication.DoesNotExist:
            return Response({"error": "Профиль не найден."}, status=status.HTTP_404_NOT_FOUND)

class ReviewListView(APIView):
    """Получение списка отзывов о психологе"""
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Психолог"],
        summary="Получить список отзывов о психологе",
        description="Возвращает все отзывы, оставленные клиентами для конкретного психолога.",
        parameters=[
            OpenApiParameter(name="psychologist_id", description="ID психолога", required=True, type=int),
            OpenApiParameter(name="page", description="Номер страницы (пагинация)", required=False, type=int),
            OpenApiParameter(name="page_size", description="Количество отзывов на странице", required=False, type=int),
        ],
        responses={200: ReviewSerializer(many=True)}
    )
    def get(self, request):
        psychologist_id = request.query_params.get("psychologist_id")

        if not psychologist_id:
            return Response({"error": "Не указан ID психолога."}, status=status.HTTP_400_BAD_REQUEST)

        psychologist = get_object_or_404(PsychologistProfile, id=psychologist_id)
        reviews = Review.objects.filter(psychologist=psychologist).order_by("-created_at")

        paginator = PageNumberPagination()
        paginated_reviews = paginator.paginate_queryset(reviews, request)
        serializer = ReviewSerializer(paginated_reviews, many=True)

        return paginator.get_paginated_response(serializer.data)

class ReviewCreateView(APIView):
    """Оставить отзыв о психологе. Клиент может оставить отзыв только после завершённой сессии"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Клиент"],
        summary="Создать отзыв",
        description="Клиент может оставить отзыв о психологе только после завершённой сессии.",
        request=ReviewSerializer,
        responses={201: ReviewSerializer, 400: OpenApiResponse(description="Ошибка валидации")},
    )
    def post(self, request):
        client = request.user.clientprofile
        psychologist_id = request.data.get("psychologist_id")
        rating = request.data.get("rating")
        text = request.data.get("text", "")

        if not psychologist_id:
            return Response({"error": "Не указан ID психолога."}, status=status.HTTP_400_BAD_REQUEST)

        if rating is None or not (1 <= rating <= 5):
            return Response({"error": "Рейтинг должен быть от 1 до 5."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            completed_session = Session.objects.filter(
                client=client, psychologist_id=psychologist_id, status="COMPLETED"
            ).latest("end_time")
        except Session.DoesNotExist:
            return Response({"error": "Вы можете оставить отзыв только после завершённой сессии."}, status=status.HTTP_400_BAD_REQUEST)

        if Review.objects.filter(session=completed_session).exists():
            return Response({"error": "Вы уже оставили отзыв для этой сессии."}, status=status.HTTP_400_BAD_REQUEST)

        review = Review.objects.create(
            session=completed_session, client=client, psychologist_id=psychologist_id, rating=rating, text=text
        )

        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)

class PsychologistSessionView(APIView):
    """
    🔹 Психолог может видеть список всех записей клиентов к нему.
    """
    permission_classes = [IsAuthenticated]

    class CustomPagination(PageNumberPagination):
        page_size = 10  # Устанавливаем размер страницы

    @extend_schema(
        tags=["Психолог"],
        summary="Получить список записей клиентов к психологу",
        description="Позволяет психологу увидеть всех клиентов, которые записались к нему, включая дату, время и статус сеанса.",
        responses={
            200: OpenApiResponse(response=SessionSerializer(many=True), description="Список записей клиентов"),
            403: OpenApiResponse(description="Вы не зарегистрированы как психолог."),
        },
    )
    def get(self, request):
        """
        🔹 Получение всех записей клиентов к текущему психологу с пагинацией.
        """
        try:
            psychologist_profile = request.user.psychologist_profile
        except PsychologistProfile.DoesNotExist:
            return Response(
                {"error": "Вы не зарегистрированы как психолог."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Получаем все сессии, где психолог - текущий пользователь
        sessions = Session.objects.filter(psychologist=psychologist_profile).order_by('start_time')

        # Применяем пагинацию
        paginator = self.CustomPagination()
        paginated_sessions = paginator.paginate_queryset(sessions, request, view=self)
        serializer = SessionSerializer(paginated_sessions, many=True)

        return paginator.get_paginated_response(serializer.data)

#TELEGRAM LOGIC
class LinkTelegramView(GenericAPIView):
    serializer_class = TelegramAuthSerializer

    def post(self, request):
        verification_code = request.data.get("verification_code")
        telegram_id = request.data.get("telegram_id")

        if not verification_code or not telegram_id:
            return Response(
                {"error": "Verification code and Telegram ID are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Проверка уникальности Telegram ID
        if CustomUser.objects.filter(telegram_id=telegram_id).exists():
            return Response(
                {"error": "Telegram ID уже привязан к другому аккаунту."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = CustomUser.objects.filter(
            verification_code=verification_code,
            verification_code_expiration__gte=now()
        ).first()

        if user:
            user.telegram_id = telegram_id
            user.verification_code = None
            user.verification_code_expiration = None
            user.save(update_fields=['telegram_id', 'verification_code', 'verification_code_expiration'])

            return Response({"message": "Telegram ID linked successfully."}, status=200)

        consultation_request = QuickClientConsultationRequest.objects.filter(
            verification_code=verification_code
        ).first()

        if consultation_request:
            consultation_request.telegram_id = telegram_id
            consultation_request.verification_code = None
            consultation_request.save(update_fields=['telegram_id', 'verification_code'])

            return Response({"message": "Telegram ID linked successfully (Consultation Request)."}, status=200)

        return Response({"error": "Invalid or expired verification code."}, status=400)

class TelegramAuthView(GenericAPIView):
    serializer_class = TelegramAuthSerializer

    @staticmethod
    def validate_telegram_auth(auth_data: dict, bot_token: str) -> bool:
        check_string = "\n".join([f"{k}={v}" for k, v in sorted(auth_data.items()) if k != "hash"])
        secret_key = sha256(bot_token.encode()).digest()
        expected_hash = hmac.new(secret_key, check_string.encode(), sha256).hexdigest()
        return expected_hash == auth_data.get("hash") and time.time() - int(auth_data["auth_date"]) < 86400

    def post(self, request, *args, **kwargs):
        try:
            auth_data = request.data
            bot_token = settings.TELEGRAM_BOT_TOKEN

            if not self.validate_telegram_auth(auth_data, bot_token):
                return Response({"error": "Invalid Telegram authentication"}, status=400)

            telegram_id = auth_data["id"]
            username = auth_data.get("username", "")
            first_name = auth_data.get("first_name", "")
            role = request.data.get("role", "client")

            user, created = CustomUser.objects.get_or_create(
                telegram_id=telegram_id,
                defaults={
                    "username": username,
                    "first_name": first_name,
                    "is_psychologist": role == "psychologist",
                }
            )

            if not created:
                user.username = username
                user.first_name = first_name
                if role == "psychologist" and not user.is_psychologist:
                    user.is_psychologist = True
                user.save()

            if created:
                if not user.is_psychologist:
                    ClientProfile.objects.create(user=user)

            refresh = RefreshToken.for_user(user)
            return Response({
                "message": "Authenticated successfully",
                "access_token": str(refresh.access_token),
                "refresh_token": str(refresh),
                "is_psychologist": user.is_psychologist,
            })

        except Exception as e:
            logger.error(f"Telegram auth failed: {str(e)}")
            return Response({"error": "Ошибка авторизации через Telegram."}, status=500)

class VerificationCodeView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Код верификации"],
        summary="Get Current Verification Code",
        description="Получить текущий верификационный код пользователя.",
        responses={
            200: OpenApiResponse(description="Verification code retrieved successfully."),
            404: OpenApiResponse(description="Verification code is not available or has expired."),
        },
    )
    def get(self, request):
        user = request.user
        if user.verification_code and (not user.verification_code_expiration or now() <= user.verification_code_expiration):
            return Response({
                "verification_code": user.verification_code,
                "message": "This is your current verification code.",
                "expires_at": user.verification_code_expiration
            }, status=200)
        else:
            return Response({
                "message": "Verification code is not available or has expired. Request a new code if needed."
            }, status=404)

class NewVerificationCodeView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmptySerializer

    @extend_schema(
        tags=["Код верификации"],
        summary="Request New Verification Code",
        description="Сгенерировать новый уникальный верификационный код для текущего пользователя.",
        responses={
            200: OpenApiResponse(
                description="A new verification code has been generated successfully.",
                examples=[
                    {
                        "new_verification_code": "1234",
                        "message": "A new verification code has been generated successfully.",
                        "expires_at": "2025-02-02T12:00:00Z"
                    }
                ],
            ),
            500: OpenApiResponse(description="Internal server error."),
        },
    )
    def post(self, request):
        try:
            user = request.user
            new_code = user.generate_verification_code()
            return Response({
                "new_verification_code": new_code,
                "message": "A new verification code has been generated successfully.",
                "expires_at": user.verification_code_expiration
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AdminApprovePsychologistView(GenericAPIView):
    queryset = PsychologistApplication.objects.all()
    serializer_class = PsychologistApplicationSerializer
    permission_classes = [IsAdminUser]

    @extend_schema(
        tags=["Админ"],
        responses={
            200: PsychologistApplicationSerializer(many=True),
        },
    )
    def get(self, request):
        applications = PsychologistApplication.objects.all()
        serializer = PsychologistApplicationSerializer(applications, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        parameters=[
            OpenApiParameter("application_id", description="Application ID", required=True, type=int),
        ],
        responses={
            200: OpenApiResponse(description="Psychologist approved successfully."),
            400: OpenApiResponse(description="Invalid action."),
            404: OpenApiResponse(description="Application not found."),
        },
    )
    def post(self, request, application_id):
        try:
            application = PsychologistApplication.objects.get(id=application_id)

            if application.status != "PENDING":
                return Response(
                    {"error": "Application has already been reviewed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            action = request.data.get("action")

            if action == "APPROVE":
                application.status = "APPROVED"
                application.save()

                user = application.user
                user.is_psychologist = True
                user.save()

                profile, _ = PsychologistProfile.objects.get_or_create(user=user, application=application)
                profile.is_verified = True
                profile.update_catalog_visibility()  # важно обновить статус для отображения в каталоге

                send_approval_email(application)  # отправляем уведомление об одобрении

                return Response(
                    {"message": "Psychologist approved successfully."},
                    status=status.HTTP_200_OK,
                )

            elif action == "REJECT":
                application.status = "REJECTED"
                application.save()

                send_rejection_email(application)  # уведомление о отклонении

                return Response(
                    {"message": "Psychologist application rejected."},
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {"error": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST
                )

        except PsychologistApplication.DoesNotExist:
            return Response(
                {"error": "Application not found."}, status=status.HTTP_404_NOT_FOUND
            )

class TopicListView(APIView):
    def get(self, request):
        topics = Topic.objects.all()
        serializer = TopicSerializer(topics, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class ScheduleSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        🔹 Получение всех записей клиента
        """
        try:
            client_profile = request.user.client_profile
        except ClientProfile.DoesNotExist:
            logger.error(f"ScheduleSessionView: User {request.user.id} is not a client.")
            return Response(
                {"error": "Только клиент может просматривать свои записи."},
                status=status.HTTP_403_FORBIDDEN
            )

        sessions = Session.objects.filter(client=client_profile).order_by('start_time')
        serializer = SessionSerializer(sessions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        """
        🔹 Запись клиента на сеанс
        """
        try:
            client_profile = request.user.client_profile
        except ClientProfile.DoesNotExist:
            logger.error(f"ScheduleSessionView: User {request.user.id} is not a client.")
            return Response(
                {"error": "Только клиент может записываться на сеанс."},
                status=status.HTTP_403_FORBIDDEN
            )

        data = request.data.copy()
        psychologist_id = data.get("psychologist")

        if not psychologist_id:
            return Response({"error": "Параметр 'psychologist' (ID) обязателен."},
                            status=status.HTTP_400_BAD_REQUEST)

        psychologist_profile = get_object_or_404(PsychologistProfile, pk=psychologist_id)

        if not psychologist_profile.user.is_psychologist:
            return Response({"error": "Данный пользователь не является психологом."},
                            status=status.HTTP_400_BAD_REQUEST)

        if not psychologist_profile.is_verified:
            return Response({"error": "Психолог не верифицирован."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Парсим дату и время
        try:
            session_time = make_aware(datetime(
                int(data["year"]), int(data["month"]), int(data["day"]),
                int(data["hour"]), int(data["minute"])
            ))
        except (ValueError, KeyError):
            return Response({"error": "Некорректные данные даты или времени."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Проверка на занятость времени
        existing_session = Session.objects.filter(
            psychologist=psychologist_profile,
            start_time=session_time,
            status__in=["scheduled", "in_progress"]
        ).exists()

        if existing_session:
            return Response({"error": "Это время уже занято у психолога."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Создание записи
        serializer = SessionCreateSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            session_obj = serializer.save()
            logger.info(f"Session #{session_obj.id} created (client {client_profile.pk}, psych {psychologist_id}).")

            self.notify_client(client_profile, session_obj)
            self.notify_psychologist(psychologist_profile, session_obj)

            return Response(SessionCreateSerializer(session_obj).data, status=status.HTTP_201_CREATED)

        logger.error(f"SessionCreateSerializer invalid: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, session_id):
        """
        🔹 Клиент может отменить свою запись
        """
        try:
            client_profile = request.user.client_profile
        except ClientProfile.DoesNotExist:
            return Response({"error": "Только клиент может отменять свои записи."},
                            status=status.HTTP_403_FORBIDDEN)

        session = get_object_or_404(Session, id=session_id, client=client_profile)

        if session.status not in ["scheduled", "pending"]:
            return Response({"error": "Нельзя отменить сеанс, который уже прошел или находится в процессе."},
                            status=status.HTTP_400_BAD_REQUEST)

        session.status = "canceled"
        session.save()

        # Уведомляем клиента
        self.notify_cancellation(client_profile, session)

        return Response({"message": "Запись отменена."}, status=status.HTTP_200_OK)

    def notify_client(self, client_profile, session_obj):
        """🔹 Уведомление клиента через Telegram и Email"""
        telegram_id = getattr(client_profile.user, 'telegram_id', None)
        if telegram_id:
            try:
                bot.send_message(
                    chat_id=telegram_id,
                    text=f"Вы записаны на сеанс #{session_obj.id} (время: {session_obj.start_time})."
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления клиенту в Telegram: {str(e)}")

        email = client_profile.user.email
        if email:
            subject = "Запись на сеанс"
            body = (
                f"Вы успешно записались на сеанс #{session_obj.id}!\n"
                f"Дата/время: {session_obj.start_time}\n"
                f"Статус: {session_obj.status}\n\n"
                "С уважением,\nВаша компания."
            )
            send_email_async.delay(subject, body, [email])

    def notify_psychologist(self, psychologist_profile, session_obj):
        """🔹 Уведомление психолога через Telegram и Email"""
        telegram_id = getattr(psychologist_profile.user, 'telegram_id', None)
        if telegram_id:
            try:
                bot.send_message(
                    chat_id=telegram_id,
                    text=(
                        f"Новая запись на сеанс #{session_obj.id} "
                        f"от клиента #{session_obj.client.pk}.\n"
                        f"Время: {session_obj.start_time}."
                    )
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления психологу в Telegram: {str(e)}")

        email = psychologist_profile.user.email
        if email:
            subject = "Новая запись на сеанс"
            body = (
                f"У вас новая запись (Session #{session_obj.id})!\n"
                f"От клиента: #{session_obj.client.pk}.\n"
                f"Дата/время: {session_obj.start_time}\n"
                f"Статус: {session_obj.status}\n\n"
                "С уважением,\nВаша компания."
            )
            send_email_async.delay(subject, body, [email])

    def notify_cancellation(self, client_profile, session_obj):
        """🔹 Уведомление клиента об отмене записи"""
        telegram_id = getattr(client_profile.user, 'telegram_id', None)
        if telegram_id:
            try:
                bot.send_message(
                    chat_id=telegram_id,
                    text=f"Ваша запись #{session_obj.id} отменена."
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления клиенту в Telegram: {str(e)}")

        email = client_profile.user.email
        if email:
            subject = "Отмена записи"
            body = (
                f"Ваша запись #{session_obj.id} отменена.\n"
                f"Дата/время: {session_obj.start_time}\n"
                f"Статус: отменена.\n\n"
                "С уважением,\nВаша компания."
            )
            send_email_async.delay(subject, body, [email])

