import hmac
import uuid
from hashlib import sha256
from django.utils.decorators import method_decorator
from django.views import View
from django.contrib.auth import get_user_model
from django.views.decorators.csrf import csrf_exempt
from rest_framework.exceptions import NotFound, ValidationError, PermissionDenied
from rest_framework.serializers import Serializer, EmailField
from django.utils.crypto import get_random_string
from datetime import timedelta
from .serializers import RegisterSerializer, ChangePasswordSerializer, TelegramAuthSerializer, \
    AuthenticatedQuickClientConsultationRequestSerializer, \
    QuickClientConsultationRequestSerializer, QuickClientConsultationAnonymousSerializer, SessionItemSerializer
from datetime import datetime
from django.utils.timezone import now, make_aware
from django.shortcuts import get_object_or_404, render
from rest_framework import status, viewsets
from ailaq.tasks import send_email_async
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiTypes
from config import settings
from .emails import send_rejection_email, send_approval_email
from .models import PsychologistProfile, PsychologistApplication, ClientProfile, CustomUser, \
    PsychologistFAQ, Review, Session, QuickClientConsultationRequest, Topic, EducationDocument
from .serializers import (
    LoginSerializer, PsychologistApplicationSerializer, ClientProfileSerializer, ReviewSerializer, CatalogSerializer,
    PersonalInfoSerializer, QualificationSerializer, DocumentSerializer,
    FAQListSerializer, TopicSerializer,
    ServicePriceSerializer, SessionCreateSerializer, SessionSerializer, PsychologistProfileSerializer
)
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from rest_framework.viewsets import ReadOnlyModelViewSet
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser
import telegram
import logging

logger = logging.getLogger(__name__)
logger = logging.getLogger("telegram_auth")
User = get_user_model()
bot = telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN)

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
                # 🔹 Если хочет быть психологом → создаём только заявку
                PsychologistApplication.objects.get_or_create(user=user, defaults={"status": "PENDING"})
            else:
                # 🔹 Если обычный клиент → создаём профиль сразу
                ClientProfile.objects.create(user=user)

            # 🔹 Если через email → требуется подтверждение
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
    """
    Повторная отправка письма подтверждения email.
    """

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
    """
    Вход в систему (по email и паролю).
    """

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
                "telegram_linked": bool(user.telegram_id)
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name='dispatch')
class TelegramAuthView(APIView):
    def get(self, request):
        print(f" ПРИШЕЛ ЗАПРОС ОТ TELEGRAM: {request.query_params}")

        auth_data = request.query_params.dict()
        received_hash = auth_data.pop('hash', None)

        if not received_hash:
            return Response({"error": "Нет hash"}, status=400)

        auth_data_str = "\n".join(f"{k}={v}" for k, v in sorted(auth_data.items()))
        secret_key = sha256(settings.TELEGRAM_BOT_TOKEN.encode()).digest()
        calculated_hash = hmac.new(secret_key, auth_data_str.encode(), sha256).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return Response({"error": "Неверная подпись"}, status=400)

        telegram_id = int(auth_data['id'])
        first_name = auth_data.get('first_name', '')
        username = auth_data.get('username', f"user_{telegram_id}")

        email = f"{telegram_id}@telegram.local"

        user, created = User.objects.get_or_create(
            telegram_id=telegram_id,
            defaults={
                'username': username,
                'email': email,
                'is_active': True,
            }
        )

        if created:
            ClientProfile.objects.create(user=user, full_name=first_name)

        refresh = RefreshToken.for_user(user)

        return Response({
            'access_token': str(refresh.access_token),
            'refresh_token': str(refresh),
            'user_id': user.id,
            'message': "Авторизация успешна"
        })

class TelegramAuthPageView(View):
    def get(self, request):
        return render(request, 'telegram_auth.html')


class VerifyTelegramView(APIView):
    """
    Привязка Telegram после входа.
    """

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

class QuickClientConsultationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Клиент - быстрая консультация"],
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

        # Берем данные из профиля напрямую
        profile_data = {
            'client_name': profile.full_name,
            'age': profile.age,
            'gender': profile.gender,
        }

        serializer = AuthenticatedQuickClientConsultationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Сохраняем уже с профилем
        consultation = QuickClientConsultationRequest.objects.create(
            **serializer.validated_data,
            **profile_data,
            telegram_id=user.telegram_id
        )

        response_serializer = QuickClientConsultationRequestSerializer(consultation)
        return Response({
            "message": "Заявка успешно создана.",
            "consultation_request": response_serializer.data
        }, status=201)

class QuickClientConsultationAnonymousAPIView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Клиент - быстрая консультация"],
        summary="Создание заявки на консультацию (без Telegram, без аккаунта)",
        request=QuickClientConsultationAnonymousSerializer,
        responses={201: QuickClientConsultationAnonymousSerializer},
    )
    def post(self, request):
        serializer = QuickClientConsultationAnonymousSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        consultation = serializer.save()  # Без telegram_id

        # Генерируем токен (например, UUID)
        token = uuid.uuid4().hex
        consultation.client_token = token
        consultation.save()

        response_data = serializer.data
        response_data['client_token'] = token

        response = Response({
            "message": "Заявка успешно создана.",
            "consultation_request": response_data
        }, status=status.HTTP_201_CREATED)

        # Сохраняем токен в cookie (опционально)
        response.set_cookie("client_token", token, httponly=True, max_age=86400)

        return response

class TelegramAuthLinkConsultationAPIView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Клиент - Telegram привязка"],
        summary="Привязка Telegram к уже созданной заявке",
        request=TelegramAuthSerializer,
        responses={200: OpenApiTypes.OBJECT}
    )
    def get(self, request):
        auth_data = request.query_params.dict()
        received_hash = auth_data.pop('hash', None)

        if not received_hash:
            return Response({"error": "Нет hash"}, status=400)

        auth_data_str = "\n".join(f"{k}={v}" for k, v in sorted(auth_data.items()))
        secret_key = sha256(settings.TELEGRAM_BOT_TOKEN.encode()).digest()
        calculated_hash = hmac.new(secret_key, auth_data_str.encode(), sha256).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return Response({"error": "Неверная подпись"}, status=400)

        telegram_id = int(auth_data['id'])

        # Получаем токен из cookie
        client_token = request.COOKIES.get('client_token')

        if not client_token:
            return Response({"error": "Токен клиента не найден."}, status=400)

        try:
            consultation = QuickClientConsultationRequest.objects.get(client_token=client_token)
        except QuickClientConsultationRequest.DoesNotExist:
            return Response({"error": "Заявка с таким токеном не найдена."}, status=404)

        # Создаем пользователя
        user, created = CustomUser.objects.get_or_create(
            telegram_id=telegram_id,
            defaults={
                'email': f"{telegram_id}@telegram.local",
                'is_active': True,
                'username': auth_data.get('username', f"user_{telegram_id}"),
            }
        )

        # Привязываем Telegram к заявке
        consultation.telegram_id = telegram_id
        consultation.save()

        return Response({
            'message': "Telegram успешно привязан к заявке.",
            'consultation_id': consultation.id
        })

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

class ClientMeViewSet(viewsets.ViewSet):
    """
    ViewSet для работы с профилем текущего клиента без передачи ID в URL.
    """

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
            session = Session.objects.filter(
                client=client, status="COMPLETED", review_submitted=False
            ).latest("end_time")
        except Session.DoesNotExist:
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

