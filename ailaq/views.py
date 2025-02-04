#views
import hmac
from django.utils.timezone import now
import time
from django.http import JsonResponse
from hashlib import sha256
from rest_framework import status, viewsets
from rest_framework.generics import GenericAPIView, ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.views import APIView
from django.db.models import Q
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from config import settings
from .models import PsychologistProfile, PsychologistApplication, PurchasedRequest, ClientProfile, CustomUser, \
    PsychologistFAQ, Review, Session, QuickConsultationRequest
from .serializers import (
    CustomUserCreationSerializer,
    LoginSerializer,
    PsychologistProfileSerializer,
    PsychologistApplicationSerializer, ClientProfileSerializer, ReviewSerializer, CatalogSerializer,
    BuyRequestSerializer, PersonalInfoSerializer, QualificationSerializer, DocumentSerializer,
    FAQSerializer, FAQListSerializer, TelegramAuthSerializer,
)
from .permissions import IsVerifiedPsychologist
from .pagination import StandardResultsSetPagination
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

import logging
logger = logging.getLogger(__name__)

# Регистрация пользователя
@method_decorator(csrf_exempt, name='dispatch')
class RegisterUserView(APIView):
    @extend_schema(
        operation_id="register_user",
        description="Регистрация нового пользователя.",
        request=CustomUserCreationSerializer,
        responses={
            201: OpenApiResponse(description="User registered successfully."),
            400: OpenApiResponse(description="Invalid data."),
        },
    )
    def post(self, request):
        try:
            serializer = CustomUserCreationSerializer(data=request.data)
            if serializer.is_valid():
                user = serializer.save()
                if user.wants_to_be_psychologist:
                    PsychologistApplication.objects.get_or_create(user=user)

                # Генерация токенов
                refresh = RefreshToken.for_user(user)
                return Response(
                    {
                        "access_token": str(refresh.access_token),
                        "refresh_token": str(refresh),
                        "verification_code": user.verification_code  # Отправляем код пользователю
                    },
                    status=status.HTTP_201_CREATED,
                )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Error during user registration: {str(e)}")
            return Response({"error": "Internal server error. Please try again later."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LoginView(APIView):
    @extend_schema(
        operation_id="login_user",
        description="Авторизация пользователя.",
        request=LoginSerializer,
        responses={
            200: OpenApiResponse(description="Login successful."),
            400: OpenApiResponse(description="Invalid credentials."),
        },
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data["email"]
            password = serializer.validated_data["password"]

            # Проверка пользователя
            user = CustomUser.objects.filter(email=email).first()
            if user and user.check_password(password):
                refresh = RefreshToken.for_user(user)
                return Response(
                    {
                        "access_token": str(refresh.access_token),
                        "refresh_token": str(refresh),
                    },
                    status=status.HTTP_200_OK,
                )
        return Response({"error": "Invalid credentials."}, status=status.HTTP_400_BAD_REQUEST)


class QuickConsultationView(APIView):
    def post(self, request):
        data = request.data
        existing_request = QuickConsultationRequest.objects.filter(
            telegram_id=request.user.telegram_id if request.user.is_authenticated else None,
            status='PENDING'
        ).first()

        if existing_request:
            return Response({"error": "You already have a pending consultation request."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            consultation = QuickConsultationRequest.objects.create(
                client_name=data['client_name'],
                client_age=data['client_age'],
                preferred_psychologist_age=data.get('preferred_psychologist_age'),
                psychologist_gender=data['psychologist_gender'],
                psychologist_language=data['psychologist_language'],
                topic=data['topic'],
                comments=data.get('comments'),
                telegram_id=request.user.telegram_id if request.user.is_authenticated else None
            )
            return Response({"message": "Consultation request saved successfully."}, status=status.HTTP_201_CREATED)
        except KeyError as e:
            return Response({"error": f"Missing field: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

class SubmitPsychologistApplicationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PsychologistApplicationSerializer,
        responses={
            201: OpenApiResponse(description="Application submitted successfully."),
            400: OpenApiResponse(description="Invalid data."),
        },
    )
    def post(self, request):
        # Проверка, хочет ли пользователь быть психологом
        if not request.user.wants_to_be_psychologist:
            return Response(
                {"error": "You are not eligible to submit an application."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Передаём данные для сериализатора
        serializer = PsychologistApplicationSerializer(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            # Сохраняем заявку
            serializer.save()
            return Response(
                {"message": "Application submitted successfully."},
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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


class UpdatePsychologistProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PsychologistProfileSerializer,
        responses={
            200: OpenApiResponse(description="Profile updated successfully."),
            404: OpenApiResponse(description="Profile not found."),
        },
    )
    def put(self, request):
        try:
            profile = PsychologistProfile.objects.get(user=request.user)
        except PsychologistProfile.DoesNotExist:
            return Response({"error": "Profile not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = PsychologistProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# Список психологов с фильтрацией каталог
class CatalogView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="list_psychologists",
        description="Получить список психологов с фильтрацией, сортировкой и пагинацией.",
        parameters=[
            OpenApiParameter("is_verified", description="Фильтр по верификации", required=False, type=bool),
            OpenApiParameter("is_in_catalog", description="Фильтр по отображению в каталоге", required=False, type=bool),
            OpenApiParameter("min_requests", description="Минимальное количество запросов", required=False, type=int),
            OpenApiParameter("max_price", description="Максимальная цена за сессию", required=False, type=float),
            OpenApiParameter("sort_by", description="Сортировка по полю", required=False, type=str,
                             default="application__id"),
        ],
        responses={
            200: CatalogSerializer(many=True),
            400: OpenApiResponse(description="Некорректные параметры запроса."),
            500: OpenApiResponse(description="Ошибка сервера."),
        },
    )
    def get(self, request):
        try:
            # Фильтры
            is_verified = request.query_params.get('is_verified')
            is_in_catalog = request.query_params.get('is_in_catalog')
            min_requests = request.query_params.get('min_requests')
            max_price = request.query_params.get('max_price')
            sort_by = request.query_params.get('sort_by', 'application__id')

            # Фильтрация профилей
            queryset = PsychologistProfile.objects.filter(is_in_catalog=True).select_related('application')
            if is_verified is not None:
                queryset = queryset.filter(is_verified=is_verified.lower() == 'true')
            if is_in_catalog is not None:
                queryset = queryset.filter(is_in_catalog=is_in_catalog.lower() == 'true')
            if min_requests:
                queryset = queryset.filter(requests_count__gte=int(min_requests))
            if max_price:
                queryset = queryset.filter(application__session_price__lte=float(max_price))

            # Сортировка
            queryset = queryset.order_by(sort_by)

            # Сериализация данных и Пагинация
            pagination = StandardResultsSetPagination()
            result_page = pagination.paginate_queryset(queryset, request)
            serializer = CatalogSerializer(result_page, many=True)
            return pagination.get_paginated_response(serializer.data)

        except ValueError as ve:
            logger.error(f"ValueError in CatalogView: {ve}")
            return Response({"error": "Некорректные параметры запроса."}, status=400)
        except Exception as e:
            logger.error(f"Unexpected error in CatalogView: {e}")
            return Response({"error": "Ошибка сервера. Попробуйте позже."}, status=500)


class BuyRequestsView(APIView):
    permission_classes = [IsAuthenticated, IsVerifiedPsychologist]
    serializer_class = BuyRequestSerializer

    @extend_schema(
        responses={
            200: OpenApiResponse(description="Request purchased successfully."),
            400: OpenApiResponse(description="Insufficient balance."),
        },
    )
    def post(self, request):
        user = request.user
        profile = user.psychologist_profile

        COST = 10.00

        if user.balance < COST:
            return Response(
                {"error": "Insufficient balance."}, status=status.HTTP_400_BAD_REQUEST
            )

        user.balance -= COST
        user.save()

        profile.requests_count += 1
        profile.save()

        purchase = PurchasedRequest.objects.create(psychologist=user, cost=COST)
        return Response(
            {
                "detail": "Request purchased successfully!",
                "remaining_balance": user.balance,
                "purchased_request_id": purchase.id,
                "requests_count": profile.requests_count,
            },
            status=status.HTTP_200_OK,
        )


class ClientProfileViewSet(viewsets.ModelViewSet):
    queryset = ClientProfile.objects.all()
    serializer_class = ClientProfileSerializer

    @extend_schema(description="Retrieve a client's profile.")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


class PsychologistProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: PsychologistProfileSerializer}
    )
    def get(self, request, psychologist_id):
        try:
            profile = PsychologistProfile.objects.get(pk=psychologist_id)
            serializer = PsychologistProfileSerializer(profile)
            return Response(serializer.data, status=200)
        except PsychologistProfile.DoesNotExist:
            return Response({"error": "Profile not found"}, status=404)


class PsychologistProfileViewSet(viewsets.ModelViewSet):
    queryset = PsychologistProfile.objects.all()
    serializer_class = PsychologistProfileSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [IsAuthenticated]

    @extend_schema(
        description="Получить список профилей психологов.",
        responses={200: PsychologistProfileSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        description="Обновить профиль психолога.",
        request=PsychologistProfileSerializer,
        responses={200: PsychologistProfileSerializer},
    )
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)


class PsychologistApplicationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: PsychologistApplicationSerializer(many=True)},
        description="Получить список всех заявок."
    )
    def get(self, request):
        applications = PsychologistApplication.objects.all()
        serializer = PsychologistApplicationSerializer(applications, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        request=PsychologistApplicationSerializer,
        responses={
            201: OpenApiResponse(description="Заявка создана успешно."),
            400: OpenApiResponse(description="Ошибка создания заявки."),
        },
    )
    def post(self, request):
        serializer = PsychologistApplicationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# эндпоинты для профиля/заявки психолога
class PersonalInfoView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="update_personal_info",
        description="Обновить личную информацию психолога.",
        request=PersonalInfoSerializer,
        responses={
            200: OpenApiResponse(description="Личная информация обновлена успешно."),
            400: OpenApiResponse(description="Ошибка валидации."),
        },
    )
    def post(self, request):
        app, created = PsychologistApplication.objects.get_or_create(user=request.user)
        serializer = PersonalInfoSerializer(app, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Личная информация обновлена успешно."}, status=200)
        return Response(serializer.errors, status=400)

class QualificationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="update_qualification",
        description="Обновить информацию о квалификации психолога.",
        request=QualificationSerializer,
        responses={
            200: OpenApiResponse(description="Квалификация обновлена успешно."),
            400: OpenApiResponse(description="Ошибка валидации."),
        },
    )
    def post(self, request):
        app, created = PsychologistApplication.objects.get_or_create(user=request.user)
        serializer = QualificationSerializer(app, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Квалификация обновлена успешно."}, status=200)
        return Response(serializer.errors, status=400)


class FAQView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="get_or_update_faq",
        description="Получить список FAQ, один FAQ или пусто, в зависимости от переданных данных.",
        request=FAQListSerializer,
        responses={
            200: FAQListSerializer,
            400: OpenApiResponse(description="Некорректные данные."),
        },
    )
    def post(self, request):
        """
        Обработка POST-запроса: сохранение списка FAQ или одного FAQ.
        """
        data = request.data.get("faqs", [])
        if isinstance(data, list):  # Если список FAQ
            serializer = FAQListSerializer(data={"faqs": data})
        else:  # Если это один FAQ
            serializer = FAQSerializer(data=request.data)

        if serializer.is_valid():
            faqs_data = serializer.validated_data.get("faqs", [])
            if faqs_data:  # Обработка списка
                # Сохраняем список FAQ
                for faq in faqs_data:
                    PsychologistFAQ.objects.create(
                        application=PsychologistApplication.objects.get(user=request.user),
                        question=faq["question"],
                        answer=faq["answer"],
                    )
                return Response({"message": "Список FAQ добавлен успешно."}, status=200)
            elif "question" in serializer.validated_data:  # Обработка одного FAQ
                faq = serializer.validated_data
                PsychologistFAQ.objects.create(
                    application=PsychologistApplication.objects.get(user=request.user),
                    question=faq["question"],
                    answer=faq["answer"],
                )
                return Response({"message": "FAQ добавлен успешно."}, status=200)
            else:  # Если ничего
                return Response({"message": "Нет данных для сохранения."}, status=204)
        return Response(serializer.errors, status=400)

    @extend_schema(
        operation_id="get_faqs",
        description="Получить список FAQ текущего пользователя.",
        responses={
            200: FAQListSerializer,
            404: OpenApiResponse(description="FAQ не найдены."),
        },
    )
    def get(self, request):
        """
        Получить список FAQ для текущего пользователя.
        """
        application = PsychologistApplication.objects.filter(user=request.user).first()
        if not application:
            return Response({"error": "Заявка не найдена."}, status=404)

        faqs = application.faqs.all()
        if not faqs.exists():
            return Response({"faqs": []}, status=200)

        serializer = FAQListSerializer({"faqs": [{"question": faq.question, "answer": faq.answer} for faq in faqs]})
        return Response(serializer.data, status=200)


class DocumentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="update_documents",
        description="Добавить или обновить документы психолога.",
        request=DocumentSerializer,
        responses={
            200: OpenApiResponse(description="Документы обновлены успешно."),
            400: OpenApiResponse(description="Ошибка валидации."),
        },
    )
    def post(self, request):
        app, created = PsychologistApplication.objects.get_or_create(user=request.user)
        serializer = DocumentSerializer(app, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Документы обновлены успешно."}, status=200)
        return Response(serializer.errors, status=400)


#Список отзывов (GET) и создание нового отзыва (POST)
class ReviewListCreateView(ListCreateAPIView):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Получить список отзывов",
        description="Возвращает список всех отзывов с данными о клиенте, психологе, сессии, рейтинге и тексте отзыва.",
        responses={200: ReviewSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Создать отзыв",
        description="Создаёт новый отзыв. Требуется указать ID сессии, рейтинг и текст отзыва.",
        request=ReviewSerializer,
        responses={201: ReviewSerializer},
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


#Подробный отзыв (GET, PUT, DELETE)
class ReviewDetailView(RetrieveUpdateDestroyAPIView):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Получить отзыв",
        description="Возвращает данные конкретного отзыва по его ID.",
        responses={200: ReviewSerializer},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Обновить отзыв",
        description="Обновляет существующий отзыв. Требуются права доступа и ID отзыва.",
        request=ReviewSerializer,
        responses={200: ReviewSerializer},
    )
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)

    @extend_schema(
        summary="Удалить отзыв",
        description="Удаляет отзыв по ID. Требуются права доступа.",
        responses={204: None},
    )
    def delete(self, request, *args, **kwargs):
        return super().delete(request, *args, **kwargs)


#	1.	Проверить, существует ли завершённая сессия между клиентом и психологом.
#   2.	Если такая сессия не найдена, отклонить запрос с сообщением об ошибке.
class ReviewCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # ID текущего пользователя (клиента)
        client = request.user.clientprofile
        psychologist_id = request.data.get("psychologist_id")  # ID психолога
        rating = request.data.get("rating")  # Рейтинг (1-5)
        text = request.data.get("text")  # Текст отзыва

        if not psychologist_id or not rating:
            return Response(
                {"error": "Пожалуйста, укажите ID психолога и рейтинг."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Проверяем наличие завершённой сессии между клиентом и психологом
            completed_session = Session.objects.filter(
                Q(client=client) & Q(psychologist_id=psychologist_id) & Q(status="COMPLETED")
            ).first()

            if not completed_session:
                return Response(
                    {"error": "Вы можете оставить отзыв только после завершённой сессии с этим психологом."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Проверяем, существует ли уже отзыв для этой сессии
            if Review.objects.filter(session=completed_session).exists():
                return Response(
                    {"error": "Вы уже оставили отзыв для этой сессии."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Создаём отзыв
            review = Review.objects.create(
                session=completed_session,
                client_id=client.id,
                psychologist_id=psychologist_id,
                client_name=request.user.email,  # Или другое поле для ФИО
                psychologist_name=completed_session.psychologist.user.email,  # Или другое поле для ФИО
                rating=rating,
                text=text,
            )

            serializer = ReviewSerializer(review)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)




class LinkTelegramView(APIView):
    def post(self, request):
        try:
            verification_code = request.data.get('verification_code')
            telegram_id = request.data.get('telegram_id')

            if not verification_code or not telegram_id:
                return Response({"error": "Verification code and Telegram ID are required."}, status=400)

            user = CustomUser.objects.get(verification_code=verification_code)

            # Проверяем срок действия кода
            if user.verification_code_expiration and now() > user.verification_code_expiration:
                return Response({"error": "Verification code has expired."}, status=400)

            # Привязываем Telegram ID и сбрасываем verification_code
            user.telegram_id = telegram_id
            user.verification_code = None
            user.verification_code_expiration = None
            user.save()

            return Response({"message": "Telegram ID linked successfully."}, status=200)

        except CustomUser.DoesNotExist:
            return Response({"error": "Invalid verification code."}, status=400)
        except Exception as e:
            logger.error(f"Error linking Telegram: {str(e)}")
            return Response({"error": "Internal server error."}, status=500)



class TelegramAuthView(APIView):
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
                return JsonResponse({"error": "Invalid Telegram authentication"}, status=400)

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
            return JsonResponse({
                "message": "Authenticated successfully",
                "access_token": str(refresh.access_token),
                "refresh_token": str(refresh),
                "is_psychologist": user.is_psychologist,
            })

        except Exception as e:
            logger.error(f"Telegram auth failed: {str(e)}")
            return JsonResponse({"error": "Internal server error"}, status=500)

class VerificationCodeView(APIView):
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


class NewVerificationCodeView(APIView):
    permission_classes = [IsAuthenticated]

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