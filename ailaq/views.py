#views
from rest_framework import status, viewsets
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from .filters import PsychologistProfileFilter
from .models import PsychologistProfile, PsychologistApplication, PurchasedRequest, ClientProfile, Review, CustomUser
from .serializers import (
    CustomUserCreationSerializer,
    LoginSerializer,
    PsychologistProfileSerializer,
    PsychologistApplicationSerializer, ClientProfileSerializer, ReviewSerializer, CatalogSerializer,
    BuyRequestSerializer,
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
        serializer = CustomUserCreationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()

            # Убедитесь, что заявка создаётся только если её нет
            if user.wants_to_be_psychologist:
                PsychologistApplication.objects.get_or_create(user=user)

            refresh = RefreshToken.for_user(user)
            return Response(
                {
                    "access_token": str(refresh.access_token),
                    "refresh_token": str(refresh),
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# Авторизация пользователя
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


class PsychologistReviewsView(APIView):
    @extend_schema(
        description="Retrieve a list of all reviews or reviews for a specific psychologist by their ID.",
        parameters=[
            OpenApiParameter(
                name="psychologist_id",
                description="ID of the psychologist to filter reviews (optional).",
                required=False,
                type=int,
            )
        ],
        responses={200: ReviewSerializer(many=True)},
    )
    def get(self, request):
        psychologist_id = request.query_params.get('psychologist_id')

        if psychologist_id:
            try:
                profile = PsychologistProfile.objects.get(pk=psychologist_id)
                reviews = Review.objects.filter(session__psychologist=profile)
            except PsychologistProfile.DoesNotExist:
                return Response(
                    {"error": "Psychologist profile not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            reviews = Review.objects.all()  # Retrieve all reviews

        serializer = ReviewSerializer(reviews, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


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
