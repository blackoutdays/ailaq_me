#views
import time
import hmac
from asgiref.sync import async_to_sync
from django.http.multipartparser import MultiPartParser
from django.utils.timezone import now
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from hashlib import sha256
from rest_framework import status, viewsets
from rest_framework.generics import GenericAPIView, ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from config import settings
from .models import PsychologistProfile, PsychologistApplication, ClientProfile, CustomUser, \
    PsychologistFAQ, Review, Session, QuickClientConsultationRequest, Topic
from .serializers import (
    CustomUserCreationSerializer,
    LoginSerializer, PsychologistApplicationSerializer, ClientProfileSerializer, ReviewSerializer, CatalogSerializer,
    PersonalInfoSerializer, QualificationSerializer, DocumentSerializer,
    FAQListSerializer, TopicSerializer, QuickClientConsultationRequestSerializer, TelegramAuthSerializer,
    ServicePriceSerializer, EmptySerializer
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
                    "role": "психолог" if user.is_psychologist else "клиент"
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# 🔹 **Авторизация с русскими ошибками**
class LoginView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
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
        request=QuickClientConsultationRequestSerializer,
        responses={201: QuickClientConsultationRequestSerializer},
        description="Создание запроса на быструю консультацию и генерация ссылки на виджет Telegram."
    )
    def post(self, request):
        serializer = QuickClientConsultationRequestSerializer(data=request.data)
        if serializer.is_valid():
            consultation_request = serializer.save()

            # 🔹 Исправленный вызов асинхронного метода в синхронном контексте
            bot_info = async_to_sync(self.get_bot_info)()
            redirect_url = f"https://t.me/{bot_info.username}?start=quick_{consultation_request.verification_code}"

            # 🔹 Проверяем, есть ли telegram_id, и отправляем сообщение
            if consultation_request.telegram_id:
                async_to_sync(self.send_telegram_message)(consultation_request.telegram_id, consultation_request.pk)

            return JsonResponse(
                {
                    "message": "Заявка создана",
                    "redirect_url": redirect_url,
                    "verification_code": consultation_request.verification_code
                },
                status=status.HTTP_201_CREATED
            )

        return JsonResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # 🔹 Исправленный вызов бота (сделали статическим методом, так как внутри APIView)
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
    parser_classes = (MultiPartParser, FormParser)  # Добавить это

    def get_queryset(self):
        """Возвращает профиль только текущего пользователя."""
        return ClientProfile.objects.filter(user=self.request.user)

    @extend_schema(
        description="Получить профиль текущего клиента.",
        responses={200: ClientProfileSerializer},
    )
    def list(self, request, *args, **kwargs):
        """Возвращает профиль текущего аутентифицированного клиента."""
        try:
            profile = ClientProfile.objects.get(user=request.user)
            serializer = self.get_serializer(profile)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except ClientProfile.DoesNotExist:
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
        try:
            profile = ClientProfile.objects.get(user=request.user)
            serializer = self.get_serializer(profile, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except ClientProfile.DoesNotExist:
            return Response({"detail": "Профиль не найден."}, status=status.HTTP_404_NOT_FOUND)

    @extend_schema(
        description="Удалить профиль клиента.",
        responses={204: None},
    )
    def destroy(self, request, *args, **kwargs):
        """Удаляет профиль текущего клиента."""
        try:
            profile = ClientProfile.objects.get(user=request.user)
            profile.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except ClientProfile.DoesNotExist:
            return Response({"detail": "Профиль не найден."}, status=status.HTTP_404_NOT_FOUND)

# 🔹 Получение полного профиля психолога
class PsychologistProfileView(APIView):
    """
    Получает весь профиль психолога, включая отзывы.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
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
                "faq": FAQListSerializer(application.faqs.all(), many=True).data,
                "reviews": reviews_serializer.data,
            }

            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Ошибка при получении профиля психолога: {str(e)}")
            return Response({"error": "Не удалось получить профиль психолога."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
# 🔹 Сохранение личной информации (POST)
class PersonalInfoView(APIView):
    """
    Сохранение личной информации в заявке психолога.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
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

# 🔹 Сохранение квалификации (POST)
class QualificationView(APIView):
    """
    Сохранение квалификации психолога.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=QualificationSerializer,
        responses={200: QualificationSerializer}
    )
    def post(self, request):
        try:
            application = get_object_or_404(PsychologistApplication, user=request.user)
            serializer = QualificationSerializer(application, data=request.data, partial=True)

            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Ошибка при сохранении квалификации: {str(e)}")
            return Response({"error": "Не удалось сохранить квалификацию."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# 🔹 Сохранение стоимости услуг (POST)
class ServicePriceView(APIView):
    """
    Сохранение стоимости услуг психолога.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
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

# 🔹 Сохранение и получение FAQ психолога (POST)
class FAQView(APIView):
    """
    Получение и сохранение FAQ психолога.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="get_faqs",
        description="Получить список FAQ текущего пользователя.",
        responses={200: FAQListSerializer, 404: {"description": "FAQ не найдены."}},
    )
    def get(self, request):
        try:
            application = get_object_or_404(PsychologistApplication, user=request.user)
            faqs = application.faqs.all()
            serializer = FAQListSerializer(faqs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Ошибка при получении FAQ: {str(e)}")
            return Response({"error": "Не удалось получить FAQ."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @extend_schema(
        operation_id="update_faq",
        description="Сохранить список FAQ (заменяет все старые вопросы).",
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

# 🔹 Загрузка документов
class DocumentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
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
    """
    Получение списка отзывов о психологе.
    """
    permission_classes = [AllowAny]

    @extend_schema(
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

        # Пагинация
        paginator = PageNumberPagination()
        paginated_reviews = paginator.paginate_queryset(reviews, request)
        serializer = ReviewSerializer(paginated_reviews, many=True)

        return paginator.get_paginated_response(serializer.data)

class ReviewCreateView(APIView):
    """
    Оставить отзыв о психологе. Клиент может оставить отзыв только после завершённой сессии.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
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

#TELEGRAM LOGIC
class LinkTelegramView(GenericAPIView):
    serializer_class = TelegramAuthSerializer

    def post(self, request):
        try:
            verification_code = request.data.get("verification_code")
            telegram_id = request.data.get("telegram_id")

            if not verification_code or not telegram_id:
                return Response({"error": "Verification code and Telegram ID are required."}, status=400)

            # 🔹 Пробуем найти код в CustomUser
            user = CustomUser.objects.filter(verification_code=verification_code).first()
            if user:
                if user.verification_code_expiration and now() > user.verification_code_expiration:
                    return Response({"error": "Verification code has expired."}, status=400)

                user.telegram_id = telegram_id
                user.verification_code = None
                user.verification_code_expiration = None
                user.save()

                return Response({"message": "Telegram ID linked successfully (User)."}, status=200)

            # 🔹 Пробуем найти код в QuickClientConsultationRequest
            consultation_request = QuickClientConsultationRequest.objects.filter(
                verification_code=verification_code
            ).first()
            if consultation_request:
                consultation_request.telegram_id = telegram_id
                consultation_request.save()

                return Response({"message": "Telegram ID linked successfully (Consultation Request)."}, status=200)

            return Response({"error": "Invalid verification code."}, status=400)

        except Exception as e:
            logger.error(f"Error linking Telegram: {str(e)}")
            return Response({"error": "Internal server error."}, status=500)

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
                if user.is_psychologist:
                    PsychologistProfile.objects.create(user=user)
                else:
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
            return Response({"error": "Internal server error."}, status=500)

class VerificationCodeView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
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
            new_code = user.generate_new_verification_code()
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

                profile, _ = PsychologistProfile.objects.get_or_create(user=user)
                profile.is_verified = True
                profile.save()

                return Response(
                    {"message": "Psychologist approved successfully."},
                    status=status.HTTP_200_OK,
                )
            elif action == "REJECT":
                application.status = "REJECTED"
                application.save()
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
