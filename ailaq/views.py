import base64
import hmac
import uuid
from hashlib import sha256

from django.core.files.base import ContentFile
from rest_framework import generics
from rest_framework.decorators import action
from .serializers import UserIdSerializer
from asgiref.sync import async_to_sync
from django.utils.decorators import method_decorator
from django.views import View
from django.contrib.auth import get_user_model
from django.views.decorators.csrf import csrf_exempt
from rest_framework.exceptions import NotFound, ValidationError, PermissionDenied
from rest_framework.serializers import Serializer, EmailField
from django.utils.crypto import get_random_string
from datetime import timedelta
from django.db import transaction
from . import models
from .serializers import RegisterSerializer, ChangePasswordSerializer, TelegramAuthSerializer, \
    AuthenticatedQuickClientConsultationRequestSerializer, \
    QuickClientConsultationRequestSerializer, QuickClientConsultationAnonymousSerializer, SessionItemSerializer, \
    PsychologistChangePasswordSerializer
from django.utils.timezone import now
from django.shortcuts import get_object_or_404, render
from rest_framework import status, viewsets
from ailaq.tasks import send_email_async, notify_all_psychologists_task
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiTypes
from config import settings
from .models import PsychologistProfile, PsychologistApplication, ClientProfile, CustomUser, \
    PsychologistFAQ, Review, QuickClientConsultationRequest, Topic, EducationDocument
from .serializers import (
    LoginSerializer, PsychologistApplicationSerializer, ClientProfileSerializer, ReviewSerializer, CatalogSerializer,
    PersonalInfoSerializer, QualificationSerializer, DocumentSerializer,
    FAQListSerializer, TopicSerializer,
    ServicePriceSerializer, PsychologistProfileSerializer
)
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
import telegram
import logging

from .telegram_bot import send_telegram_message, notify_psychologist_telegram
from .models import PsychologistSessionRequest
from .serializers import AnonymousSessionRequestSerializer, AuthenticatedSessionRequestSerializer
from .telegram_notify import notify_client_about_request_sent, notify_client_about_direct_request

logger = logging.getLogger("telegram_auth")
User = get_user_model()
bot = telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN)

class TelegramAuthPageView(View):
    def get(self, request):
        return render(request, 'telegram_auth.html', {})

@method_decorator(csrf_exempt, name='dispatch')
class TelegramAuthView(APIView):
    def post(self, request):
        print(f"📥 ПРИШЕЛ ЗАПРОС ОТ TELEGRAM: {request.data}")

        # 1. Проверка подписи Telegram
        received_hash = request.data.get('hash')
        telegram_fields = ['id', 'first_name', 'last_name', 'username', 'photo_url', 'auth_date']
        auth_data = {k: request.data[k] for k in telegram_fields if k in request.data}

        if not received_hash:
            return Response({"error": "Нет hash"}, status=400)

        auth_data_str = "\n".join(f"{k}={v}" for k, v in sorted(auth_data.items()))
        secret_key = sha256(settings.TELEGRAM_BOT_TOKEN.encode()).digest()
        calculated_hash = hmac.new(secret_key, auth_data_str.encode(), sha256).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return Response({"error": "Неверная подпись"}, status=400)

        # 2. Данные пользователя
        telegram_id = int(auth_data['id'])
        username = auth_data.get('username', f"tg_{telegram_id}")
        wants_to_be_psychologist = str(request.data.get("wants_to_be_psychologist", "false")).lower() == "true"

        # 3. Поиск пользователя
        user = CustomUser.objects.filter(telegram_id=telegram_id).first()

        if not user:
            # РЕГИСТРАЦИЯ
            user = CustomUser.objects.create(
                telegram_id=telegram_id,
                username=username,
                is_active=True,
                wants_to_be_psychologist=wants_to_be_psychologist
            )

            try:
                with transaction.atomic():
                    if wants_to_be_psychologist:
                        application, _ = PsychologistApplication.objects.get_or_create(
                            user=user, defaults={"status": "PENDING"}
                        )
                        PsychologistProfile.objects.get_or_create(user=user, application=application)
                    else:
                        ClientProfile.objects.get_or_create(user=user)
            except Exception as e:
                logger.error(f"❌ Ошибка при создании заявки/профиля: {e}")
        else:
            # ВХОД — обновим имя или активность
            updated = False
            if user.username != username:
                user.username = username
                updated = True
            if not user.is_active:
                user.is_active = True
                updated = True
            if updated:
                user.save()

        # 4. Генерация токенов
        refresh = RefreshToken.for_user(user)

        # 5. Приветствие в Telegram
        try:
            async_to_sync(send_telegram_message)(
                telegram_id=telegram_id,
                text="🎉 Вы успешно вошли в систему через Telegram. Добро пожаловать!"
            )
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке Telegram-сообщения: {e}")

        # 6. Ответ клиенту
        return Response({
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
            "user_id": user.id,
            "role": user.role,
            "message": "Telegram успешно привязан"
        })

class QuickClientConsultationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Клиент - консультация"],
        summary="Быстрая консультация для зарегистрированных клиентов",
        request=AuthenticatedQuickClientConsultationRequestSerializer,
        responses={201: QuickClientConsultationRequestSerializer},
    )
    def post(self, request):
        user = request.user

        if not user.telegram_id:
            return Response({"error": "Привяжите Telegram через Web View перед записью."}, status=400)

        if not hasattr(user, 'client_profile'):
            return Response({"error": "Профиль клиента не найден."}, status=400)

        profile = user.client_profile

        profile_data = {
            'client_name': profile.full_name,
            'age': profile.age,
            'gender': profile.gender,
        }

        serializer = AuthenticatedQuickClientConsultationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        consultation = QuickClientConsultationRequest.objects.create(
            **serializer.validated_data,
            **profile_data,
            telegram_id=user.telegram_id
        )

        notify_all_psychologists_task.delay(consultation.id)
        notify_client_about_request_sent(user.telegram_id)

        response_serializer = QuickClientConsultationRequestSerializer(consultation)
        return Response({
            "message": "Заявка успешно создана.",
            "consultation_request": response_serializer.data
        }, status=201)

class QuickClientConsultationAnonymousAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Клиент - консультация"],
        summary="Быстрая консультация (Telegram WebApp — клиент вводит имя, возраст, пол)",
        request=QuickClientConsultationAnonymousSerializer,
        responses={201: QuickClientConsultationRequestSerializer},
    )
    def post(self, request):
        user = request.user

        if not user.telegram_id:
            return Response({"error": "Привяжите Telegram через Web View перед записью."}, status=400)

        serializer = QuickClientConsultationAnonymousSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        # Обновим или создадим профиль клиента
        profile, _ = ClientProfile.objects.get_or_create(user=user)

        # Сохраняем введённые данные в профиль
        profile.full_name = validated_data.get("client_name")
        profile.age = validated_data.get("age")
        profile.gender = validated_data.get("gender")
        profile.save()

        # Создание заявки
        consultation = QuickClientConsultationRequest.objects.create(
            **validated_data,
            telegram_id=user.telegram_id
        )

        notify_all_psychologists_task.delay(consultation.id)
        notify_client_about_request_sent(user.telegram_id)

        response_serializer = QuickClientConsultationRequestSerializer(consultation)
        return Response({
            "message": "Заявка успешно создана.",
            "consultation_request": response_serializer.data
        }, status=status.HTTP_201_CREATED)

class AuthenticatedPsychologistSessionRequestView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Клиент - консультация"],
        summary="Заявка к выбранному психологу (авторизован)",
        request=AuthenticatedSessionRequestSerializer,
        responses={201: AuthenticatedSessionRequestSerializer}
    )
    def post(self, request):
        user = request.user
        if not hasattr(user, "client_profile") or not user.telegram_id:
            return Response({"error": "Профиль клиента или Telegram не найден."}, status=400)

        profile = user.client_profile
        data = request.data.copy()
        data.update({
            "client_name": profile.full_name,
            "age": profile.age,
            "gender": profile.gender,
            "telegram_id": user.telegram_id
        })

        serializer = AuthenticatedSessionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session_request = PsychologistSessionRequest.objects.create(
            **serializer.validated_data,
            client=profile,
            client_name=profile.full_name,
            age=profile.age,
            gender=profile.gender,
            telegram_id=user.telegram_id
        )

        async_to_sync(notify_psychologist_telegram)(session_request)
        notify_client_about_direct_request(user.telegram_id, session_request.psychologist.user.full_name)

        return Response(serializer.data, status=201)

class AnonymousPsychologistSessionRequestView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Клиент - консультация"],
        summary="Заявка к выбранному психологу (Telegram WebApp — клиент вводит имя, возраст, пол)",
        request=AnonymousSessionRequestSerializer,
        responses={201: AnonymousSessionRequestSerializer},
    )
    def post(self, request):
        user = request.user

        if not user.telegram_id:
            return Response({"error": "Привяжите Telegram через Web View перед записью."}, status=400)

        serializer = AnonymousSessionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        # Обновим или создадим профиль клиента
        profile, _ = ClientProfile.objects.get_or_create(user=user)
        profile.full_name = validated_data.get("client_name")
        profile.age = validated_data.get("age")
        profile.gender = validated_data.get("gender")
        profile.save()

        # Создание заявки
        session_request = PsychologistSessionRequest.objects.create(
            **validated_data,
            client=profile,
            telegram_id=user.telegram_id
        )

        async_to_sync(notify_psychologist_telegram)(session_request)
        notify_client_about_direct_request(user.telegram_id, session_request.psychologist.user.get_full_name())

        return Response(serializer.data, status=201)

class CatalogPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

# Представление каталога психологов
class CatalogViewSet(ReadOnlyModelViewSet):
    """Каталог психологов с фильтрацией, сортировкой и пагинацией"""
    queryset = PsychologistProfile.objects.filter(is_in_catalog=True).select_related('application')
    serializer_class = CatalogSerializer
    pagination_class = CatalogPagination
    permission_classes = [AllowAny]

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = {
        'requests_count': ['gte', 'lte'],
    }
    ordering_fields = ['application__id', 'requests_count']
    ordering = ['application__id']

    @extend_schema(
        tags=["Каталог психологов"],
        description="Получить список психологов с фильтрацией, сортировкой и пагинацией.",
        parameters=[
            OpenApiParameter("requests_count__gte", description="Минимальное количество запросов", required=False, type=int),
            OpenApiParameter("requests_count__lte", description="Максимальное количество запросов", required=False, type=int),
            OpenApiParameter("ordering", description="Сортировка (application__id, requests_count)", required=False, type=str),
            OpenApiParameter("page", description="Номер страницы", required=False, type=int),
            OpenApiParameter("page_size", description="Количество элементов на странице (по умолчанию 10)", required=False, type=int),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

class ClientMeViewSet(viewsets.ViewSet):
    """ ViewSet для работы с профилем текущего клиента без передачи ID в URL """

    permission_classes = [IsAuthenticated]

    def get_object(self):
        """
        Возвращает профиль, привязанный к текущему пользователю.
        """
        if self.request.user.is_psychologist or self.request.user.wants_to_be_psychologist:
            logger.warning(
                f"Психолог или кандидат (пользователь {self.request.user.id}) попытался получить профиль клиента.")
            raise PermissionDenied("Психологи или кандидаты в психологи не могут иметь клиентский профиль.")

        try:
            return ClientProfile.objects.get(user=self.request.user)
        except ClientProfile.DoesNotExist:
            logger.warning(f"Профиль не найден для пользователя {self.request.user.id}")
            raise NotFound("Профиль клиента не найден.")

    @extend_schema(
        tags=["Клиент"],
        summary="Получить текущий профиль клиента",
        responses={200: ClientProfileSerializer}
    )
    def retrieve(self, request):
        profile = self.get_object()
        serializer = ClientProfileSerializer(profile)
        return Response(serializer.data)

    @extend_schema(
        tags=["Клиент"],
        summary="Создать профиль клиента",
        responses={201: ClientProfileSerializer}
    )
    def create(self, request):
        if request.user.is_psychologist or request.user.wants_to_be_psychologist:
            logger.warning(f"Психолог или кандидат (пользователь {request.user.id}) попытался создать профиль клиента.")
            raise PermissionDenied("Психологи или кандидаты в психологи не могут создавать клиентские профили.")

        if ClientProfile.objects.filter(user=request.user).exists():
            logger.error(f"Попытка повторного создания профиля для пользователя {request.user.id}")
            raise ValidationError("Профиль уже существует.")

        serializer = ClientProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        logger.info(f"Профиль успешно создан для пользователя {request.user.id}")
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Клиент"],
        summary="Обновить профиль клиента",
        request=ClientProfileSerializer,
        responses={200: ClientProfileSerializer}
    )
    def update(self, request):
        profile = self.get_object()
        serializer = ClientProfileSerializer(profile, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info(f"Профиль обновлён для пользователя {request.user.id}")
        return Response(serializer.data)

    @extend_schema(
        tags=["Клиент"],
        summary="Частично обновить профиль клиента",
        request=ClientProfileSerializer,
        responses={200: ClientProfileSerializer}
    )
    def partial_update(self, request):
        profile = self.get_object()
        serializer = ClientProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info(f"Профиль частично обновлён для пользователя {request.user.id}")
        return Response(serializer.data)

    @extend_schema(exclude=True)
    def destroy(self, request):
        logger.warning(f"Попытка удаления профиля пользователем {request.user.id}")
        return Response({"detail": "Удаление профиля запрещено."}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

class PublicPsychologistProfileView(APIView):
    """ Публичный API для получения профиля психолога (для клиентов) """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Публичный профиль психолога"],
        description="Этот эндпоинт позволяет клиенту получить информацию о психологе по его ID.",
        responses={200: PsychologistProfileSerializer}
    )
    def get(self, request, psychologist_id: int):
        psychologist = get_object_or_404(
            PsychologistProfile.objects.select_related("application"),
            user_id=psychologist_id
        )
        serializer = PsychologistProfileSerializer(psychologist)
        return Response(serializer.data, status=status.HTTP_200_OK)

class PublicQualificationView(APIView):
    """ Позволяет всем пользователям (и клиентам) получать квалификацию психолога """
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
    """ Позволяет всем пользователям видеть стоимость услуг психолога """
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
    permission_classes = [AllowAny]
    pagination_class = PageNumberPagination

    @extend_schema(
        tags=["Публичный профиль психолога"],
        summary="Получить список отзывов о психологе",
        responses={200: ReviewSerializer(many=True)}
    )
    def get(self, request, psychologist_id: int):
        psychologist = get_object_or_404(PsychologistProfile, user_id=psychologist_id)
        reviews = Review.objects.filter(
            models.Q(consultation_request__taken_by=psychologist) |
            models.Q(session_request__taken_by=psychologist) |
            models.Q(session_request__psychologist=psychologist)
        ).order_by("-created_at")

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(reviews, request, view=self)
        serializer = ReviewSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

class PublicFAQView(APIView):
    """ Клиенты могут просматривать FAQ психолога """
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
    """ API для получения и редактирования личного профиля психолога """
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
    """ Получает весь профиль психолога, включая отзывы """
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

            # Получаем профиль психолога
            psychologist = PsychologistProfile.objects.filter(user=request.user).first()
            if not psychologist:
                logger.error(f"Профиль психолога не найден для пользователя {request.user.id}")
                return Response({"error": "Профиль психолога не найден."}, status=status.HTTP_404_NOT_FOUND)

            # Получаем отзывы по полю psychologist
            reviews = Review.objects.filter(psychologist=psychologist).order_by("-created_at")
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
    permission_classes = [IsAuthenticated]
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
                serializer.save()

                education_files = serializer.validated_data.get('education_files', [])

                for file_data in education_files:
                    document_base64 = file_data.get('document')
                    title = file_data.get('title', 'Документ')
                    year = file_data.get('year')
                    file_signature = file_data.get('file_signature', '')

                    if document_base64:
                        format, data = document_base64.split(';base64,')
                        ext = format.split('/')[-1]
                        file = ContentFile(base64.b64decode(data), name=f"{title}.{ext}")

                        EducationDocument.objects.create(
                            psychologist_application=application,
                            document=file,
                            title=title,
                            year=year,
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
        application = get_object_or_404(PsychologistApplication, user=request.user)
        serializer = ServicePriceSerializer(application)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Психолог"],
        summary="Добавить одну услугу (сессию)",
        request=SessionItemSerializer,
        responses={200: ServicePriceSerializer}
    )
    def post(self, request):
        application = get_object_or_404(PsychologistApplication, user=request.user)
        session_data = request.data

        if not isinstance(session_data, dict):
            return Response({"error": "Ожидалась одна сессия, как объект."}, status=status.HTTP_400_BAD_REQUEST)

        # Генерируем UUID
        if "id" not in session_data:
            session_data["id"] = str(uuid.uuid4())

        # Добавляем к текущим
        sessions = application.service_sessions or []
        sessions.append(session_data)

        application.service_sessions = sessions
        application.save(update_fields=["service_sessions"])

        serializer = ServicePriceSerializer(application)
        return Response(serializer.data, status=status.HTTP_200_OK)

class ServicePriceSessionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Психолог"],
        summary="Получить одну услугу по ID",
        responses={200: SessionItemSerializer}
    )
    def get(self, request, session_id):
        application = get_object_or_404(PsychologistApplication, user=request.user)
        sessions = application.service_sessions or []

        session = next((s for s in sessions if str(s.get("id")) == str(session_id)), None)
        if not session:
            return Response({"error": "Сессия не найдена"}, status=status.HTTP_404_NOT_FOUND)

        return Response(session, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Психолог"],
        summary="Обновить услугу по ID",
        request=SessionItemSerializer,
        responses={200: SessionItemSerializer}
    )
    def put(self, request, session_id):
        application = get_object_or_404(PsychologistApplication, user=request.user)
        sessions = application.service_sessions or []

        updated = False
        new_data = request.data

        for idx, session in enumerate(sessions):
            if str(session.get("id")) == str(session_id):
                sessions[idx] = {**session, **new_data, "id": session_id}
                updated = True
                break

        if not updated:
            return Response({"error": "Сессия не найдена"}, status=status.HTTP_404_NOT_FOUND)

        application.service_sessions = sessions
        application.save(update_fields=["service_sessions"])
        return Response(sessions[idx], status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Психолог"],
        summary="Удалить услугу по ID",
        responses={204: None}
    )
    def delete(self, request, session_id):
        application = get_object_or_404(PsychologistApplication, user=request.user)
        sessions = application.service_sessions or []

        # Приводим session_id к строке, т.к. id внутри сессий — строки
        session_id = str(session_id)

        new_sessions = [s for s in sessions if str(s.get("id")) != session_id]

        if len(new_sessions) == len(sessions):
            return Response({"error": "Сессия не найдена"}, status=status.HTTP_404_NOT_FOUND)

        application.service_sessions = new_sessions
        application.save(update_fields=["service_sessions"])
        return Response(status=status.HTTP_204_NO_CONTENT)

# Сохранение и получение FAQ психолога
class FAQView(APIView):
    """ Получение и сохранение FAQ психолога """
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
    def post(self, request):
        try:
            application = get_object_or_404(PsychologistApplication, user=request.user)

            if "document" not in request.FILES:
                return Response({"error": "Файл не загружен."}, status=status.HTTP_400_BAD_REQUEST)

            serializer = DocumentSerializer(application, data=request.data, partial=True)

            if serializer.is_valid():
                document = request.FILES["document"]
                EducationDocument.objects.create(
                    psychologist_application=application,
                    document=document,
                    title=document.name
                )
                return Response({"message": "Документ загружен."}, status=status.HTTP_201_CREATED)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except PsychologistApplication.DoesNotExist:
            return Response({"error": "Профиль не найден."}, status=status.HTTP_404_NOT_FOUND)

class ReviewListView(APIView):
    """ Получение списка отзывов о психологе """
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
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Клиент"],
        summary="Создать отзыв (только после завершённой сессии)",
        description="Отзыв можно оставить только после завершённой сессии, один раз на сессию.",
        request=ReviewSerializer,
        responses={201: ReviewSerializer}
    )
    def post(self, request):
        client = request.user.clientprofile
        rating = request.data.get("rating")
        text = request.data.get("text", "")

        if rating is None or not (1 <= int(rating) <= 5):
            return Response({"error": "Рейтинг должен быть от 1 до 5."}, status=400)

        try:
            session = PsychologistSessionRequest.objects.filter(
                client=client, status="COMPLETED", review_submitted=False
            ).latest("end_time")
        except PsychologistSessionRequest.DoesNotExist:
            return Response({"error": "У вас нет завершённой сессии для отзыва."}, status=400)

        review = Review.objects.create(
            session=session,
            client=client,
            psychologist=session.psychologist,
            rating=rating,
            text=text
        )

        session.review_submitted = True
        session.save()

        return Response(ReviewSerializer(review).data, status=201)

class TopicListView(APIView):
    def get(self, request):
        topics = Topic.objects.all()
        serializer = TopicSerializer(topics, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

### delete later
class RegisterUserView(APIView):
    """
    Регистрация пользователей:
    - Клиенты: email или Telegram.
    - Психологи: только email + создаётся заявка.
    """
    @extend_schema(
        tags=["Регистрация"],
        summary="Регистрация (клиент или психолог)",
        description="Регистрация через email (психолог) или email/Telegram (клиент).",
        request=RegisterSerializer,
        responses={
            201: OpenApiResponse(description="Пользователь зарегистрирован."),
            400: OpenApiResponse(description="Ошибка валидации."),
        },
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()

            if user.wants_to_be_psychologist:
                # Пользователь хочет быть психологом → сразу помечаем его так
                user.is_psychologist = True
                user.save(update_fields=["is_psychologist"])

                # Создаём заявку на модерацию
                PsychologistApplication.objects.get_or_create(user=user, defaults={"status": "PENDING"})

                # Создаём пустой профиль психолога (если у тебя есть отдельная модель)
                PsychologistProfile.objects.get_or_create(user=user)

            else:
                # Клиент → создаём профиль клиента
                ClientProfile.objects.create(user=user)

            # Если через email → требуется подтверждение
            if user.email:
                verification_code = get_random_string(length=32)
                user.verification_code = verification_code
                user.verification_code_expiration = now() + timedelta(hours=24)
                user.save()

                confirmation_link = f"{settings.FRONTEND_URL}/api/confirm-email/{verification_code}"
                subject = "Подтверждение вашего email"
                message = f"Пройдите по ссылке для подтверждения: {confirmation_link}"

                send_email_async.delay(subject, message, [user.email])

                return Response(
                    {"message": "На ваш email отправлена ссылка для подтверждения."},
                    status=status.HTTP_201_CREATED
                )

            return Response(
                {"message": "Регистрация успешно завершена."},
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ConfirmEmailView(APIView):
    def get(self, request, verification_code):
        user = CustomUser.objects.filter(verification_code=verification_code).first()

        if not user or user.verification_code_expiration < now():
            if user:
                user.verification_code = None
                user.verification_code_expiration = None
                user.save()
            return Response(
                {"error": "Ссылка недействительна или истек срок ее действия."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.is_active = True
        user.verification_code = None
        user.verification_code_expiration = None
        user.save()

        return Response(
            {"message": "Email успешно подтвержден. Теперь вы можете войти."},
            status=status.HTTP_200_OK
        )

class ResendVerificationSerializer(Serializer):
    """ Сериализатор для повторной отправки email-подтверждения """
    email = EmailField(required=True)

class ResendVerificationEmailView(APIView):
    """ Повторная отправка письма подтверждения email """
    @extend_schema(
        tags=["Авторизация"],
        summary="Повторная отправка email-подтверждения",
        description="Отправляет новую ссылку для подтверждения email.",
        request=ResendVerificationSerializer,  # Добавлен корректный request body
        responses={
            200: {"message": "Новое письмо отправлено."},
            400: {"error": "Email уже подтвержден или отправка слишком частая."},
            404: {"error": "Пользователь не найден."},
        },
    )
    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data["email"]

        user = CustomUser.objects.filter(email=email).first()

        if not user:
            return Response({"error": "Пользователь не найден."}, status=status.HTTP_404_NOT_FOUND)

        if user.is_active:
            return Response({"error": "Email уже подтвержден."}, status=status.HTTP_400_BAD_REQUEST)

        # Проверяем, не было ли отправки письма недавно (лимит: 5 минут)
        if user.verification_code_expiration and (now() - user.verification_code_expiration).seconds < 300:
            return Response({"error": "Пожалуйста, подождите 5 минут перед повторной отправкой."}, status=status.HTTP_400_BAD_REQUEST)

        # Генерируем новый код
        verification_code = get_random_string(length=32)
        user.verification_code = verification_code
        user.verification_code_expiration = now() + timedelta(hours=24)
        user.save()

        # Отправляем новое письмо
        confirmation_link = f"{settings.FRONTEND_URL}/api/confirm-email/{verification_code}"
        subject = "Подтверждение вашего email"
        message = f"""
        Здравствуйте! 
        Вы запросили повторное письмо для подтверждения email. 
        Пройдите по ссылке, чтобы подтвердить ваш аккаунт: 

        {confirmation_link}

        Если вы не запрашивали подтверждение, проигнорируйте это письмо.
        """

        send_email_async.delay(subject, message, [user.email])

        return Response({"message": "Новое письмо отправлено."}, status=status.HTTP_200_OK)

class LoginView(APIView):
    """ Вход в систему (по email и паролю) """

    @extend_schema(
        tags=["Авторизация"],
        summary="Вход в систему",
        description="Позволяет пользователю войти в систему по email и паролю.",
        request=LoginSerializer,
        responses={
            200: OpenApiResponse(description="Успешный вход."),
            400: OpenApiResponse(description="Неверные учетные данные."),
        },
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data["user"]
            refresh = RefreshToken.for_user(user)

            return Response({
                "message": "Вход выполнен успешно.",
                "access_token": str(refresh.access_token),
                "refresh_token": str(refresh),
                "telegram_linked": bool(user.telegram_id),
                "role": user.role
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class VerifyTelegramView(APIView):
    """ Привязка Telegram после входа в профиле """
    @extend_schema(
        tags=["Авторизация"],
        summary="Привязка Telegram",
        description="Позволяет привязать Telegram к аккаунту после входа через email.",
        request=None,
        responses={
            200: OpenApiResponse(description="Telegram привязан."),
            400: OpenApiResponse(description="Ошибка."),
        },
    )
    def post(self, request):
        auth_data = request.data
        telegram_id = auth_data["id"]
        user = request.user

        if user.telegram_id:
            return Response({"message": "Telegram уже привязан."}, status=status.HTTP_400_BAD_REQUEST)

        user.telegram_id = telegram_id
        user.save()
        return Response({"message": "Telegram привязан успешно."}, status=status.HTTP_200_OK)

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Смена пароля",
        description="Позволяет сменить пароль, указав текущий пароль.",
        request=ChangePasswordSerializer,
        responses={200: {"message": "Пароль успешно изменен"}},
    )
    def post(self, request):
        serializer = self.ChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user

            # Проверяем текущий пароль
            if not user.check_password(serializer.validated_data["current_password"]):
                return Response({"error": "Неверный текущий пароль."}, status=status.HTTP_400_BAD_REQUEST)

            # Устанавливаем новый пароль
            user.set_password(serializer.validated_data["new_password"])
            user.save()

            return Response({"message": "Пароль успешно изменен."}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class PsychologistChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Психолог"],
        summary="Смена пароля для психолога",
        request=PsychologistChangePasswordSerializer,
        responses={
            200: OpenApiResponse(description="Пароль успешно обновлён"),
            400: OpenApiResponse(description="Ошибки валидации, например: пароли не совпадают или текущий неверный"),
        }
    )
    def post(self, request):
        serializer = PsychologistChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Пароль успешно обновлён"}, status=status.HTTP_200_OK)

class UserListView(generics.ListAPIView):
    """ Эндпоинт для получения списка всех пользователей с их ID """
    queryset = User.objects.all()
    serializer_class = UserIdSerializer

class UploadProfilePhotoView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        # Получаем текущий профиль психолога
        try:
            profile = request.user.psychologist_profile
        except PsychologistProfile.DoesNotExist:
            return Response({"error": "Профиль психолога не найден."}, status=status.HTTP_404_NOT_FOUND)

        # Получаем файл из запроса
        file = request.FILES.get('profile_picture')
        if not file:
            return Response({"error": "Файл изображения не загружен."}, status=status.HTTP_400_BAD_REQUEST)

        # Сохраняем фото в профиль
        profile.profile_picture = file
        profile.save()

        # Возвращаем успешный ответ с URL фото
        return Response({
            "message": "Фото успешно загружено.",
            "profile_picture_url": profile.profile_picture.url
        }, status=status.HTTP_200_OK)


class PsychologistApplicationViewSet(viewsets.ModelViewSet):
    queryset = PsychologistApplication.objects.all()
    serializer_class = PsychologistApplicationSerializer
    permission_classes = [IsAdminUser]  # Доступ только для администратора

    @extend_schema(
        tags=["Psychologist Applications"],
        description="Изменяет статус заявки психолога на 'APPROVED' или 'REJECTED'.",
        parameters=[
            OpenApiParameter("status", type=str, description="Новый статус заявки (APPROVED/REJECTED)", required=True)
        ],
        responses={
            200: OpenApiResponse(
                description="Статус заявки успешно обновлен."
            ),
            400: OpenApiResponse(
                description="Неверный статус."
            ),
        },
    )
    @action(detail=True, methods=['post'], url_path='update-status')
    def update_status(self, request, pk=None):
        try:
            application = self.get_object()
            user = application.user

            new_status = request.data.get('status')
            rejection_comment = request.data.get('rejection_comment')  # из тела запроса

            if new_status not in ['APPROVED', 'REJECTED']:
                return Response({"detail": "Неверный статус."}, status=400)

            if new_status == 'REJECTED' and not rejection_comment:
                return Response(
                    {"detail": "При отклонении необходимо указать причину (rejection_comment)."},
                    status=400
                )

            # Обновление статуса и комментария
            application.status = new_status
            if new_status == 'REJECTED':
                application.previous_rejection_comment = rejection_comment
            application.save()

            # Создание профиля при одобрении
            if new_status == 'APPROVED':
                # Получаем профиль или создаем, если его нет
                profile, _ = PsychologistProfile.objects.get_or_create(user=user)

                # Обновляем заявку в профиле, если она ещё не привязана или изменилась
                if profile.application != application:
                    profile.application = application
                    profile.save(update_fields=["application"])

            # Telegram уведомление
            from asgiref.sync import async_to_sync

            if user.telegram_id:
                if new_status == 'APPROVED':
                    async_to_sync(send_telegram_message)(
                        telegram_id=user.telegram_id,
                        text="✅ Ваша заявка психолога одобрена! Добро пожаловать на платформу."
                    )
                elif new_status == 'REJECTED':
                    async_to_sync(send_telegram_message)(
                        telegram_id=user.telegram_id,
                        text=(
                            "❌ Ваша заявка на роль психолога была отклонена.\n\n"
                            f"Причина: {rejection_comment}"
                        )
                    )

            logger.info(f"Статус заявки обновлён на {new_status} для пользователя {user.id}")
            return Response({"detail": f"Статус заявки обновлен на {new_status}."}, status=200)

        except Exception as e:
            logger.error(f"Ошибка при обновлении статуса заявки психолога: {str(e)}")
            return Response({"detail": "Произошла ошибка при обновлении статуса."}, status=500)

    @extend_schema(
        tags=["Psychologist Applications"],
        description="Получить полную информацию о заявке психолога.",
        responses={
            200: PsychologistApplicationSerializer,
            404: OpenApiResponse(
                description="Заявка не найдена."
            ),
        },
    )
    @action(detail=True, methods=['get'], url_path='get-details')
    def get_details(self, request, pk=None):
        """Получить полную информацию о заявке психолога."""
        try:
            # Получаем заявку по pk
            application = self.get_object()

            # Возвращаем полную информацию о заявке
            serializer = self.get_serializer(application)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except PsychologistApplication.DoesNotExist:
            return Response({"detail": "Заявка не найдена."}, status=status.HTTP_404_NOT_FOUND)

class AdminApprovePsychologistView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, *args, **kwargs):
        psychologist_id = kwargs.get("psychologist_id")
        new_status_param = kwargs.get("status")  # "APPROVED" или "REJECTED"
        rejection_comment = request.data.get("rejection_comment")

        try:
            application = PsychologistApplication.objects.get(user_id=psychologist_id)
            user = application.user

            if new_status_param not in ["APPROVED", "REJECTED"]:
                return Response({"detail": "Неверный статус."}, status=status.HTTP_400_BAD_REQUEST)

            if new_status_param == "REJECTED" and not rejection_comment:
                return Response(
                    {"detail": "При отклонении необходимо указать rejection_comment."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            application.status = new_status_param
            if new_status_param == "REJECTED":
                application.previous_rejection_comment = rejection_comment
            application.save()

            if new_status_param == "APPROVED":
                # Создаём профиль, если его нет, или обновляем заявку
                profile = PsychologistProfile.objects.filter(user=user).first()
                if not profile:
                    profile = PsychologistProfile.objects.create(user=user, application=application)
                elif profile.application != application:
                    profile.application = application
                    profile.save(update_fields=["application"])

            # Telegram уведомление
            if user.telegram_id:
                if new_status_param == 'APPROVED':
                    async_to_sync(send_telegram_message)(
                        telegram_id=user.telegram_id,
                        text="✅ Ваша заявка психолога одобрена! Добро пожаловать на платформу."
                    )
                elif new_status_param == 'REJECTED':
                    async_to_sync(send_telegram_message)(
                        telegram_id=user.telegram_id,
                        text=(
                            "❌ Ваша заявка на роль психолога была отклонена.\n\n"
                            f"Причина: {rejection_comment}"
                        )
                    )

            return Response(
                {"detail": f"Статус заявки обновлён на {new_status_param}."},
                status=status.HTTP_200_OK
            )

        except PsychologistApplication.DoesNotExist:
            return Response({"detail": "Заявка не найдена."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"❌ Ошибка при обновлении статуса заявки: {str(e)}")
            return Response({"detail": "Ошибка сервера."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)