from django.urls import path
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from ailaq.views import (
    LoginView, RegisterUserView, AdminApprovePsychologistView, PsychologistProfileView,
    QualificationView, PersonalInfoView, FAQView, DocumentView, ReviewCreateView,
    ReviewListView, TelegramAuthView, VerifyTelegramView, CatalogViewSet, ServicePriceView, ScheduleSessionView,
    PublicPsychologistProfileView,
    PsychologistSelfProfileView, PublicQualificationView, PublicReviewListView, PublicFAQView, PublicServicePriceView,
    PsychologistSessionView, ResendVerificationEmailView, ConfirmEmailView, ChangePasswordView,
    QuickClientConsultationAPIView, ClientMeViewSet, TelegramAuthPageView, QuickClientConsultationAnonymousAPIView,
    TelegramAuthLinkConsultationAPIView, ServicePriceSessionDetailView, PsychologistChangePasswordView
)

router = DefaultRouter()
router.register(r'catalog', CatalogViewSet, basename='catalog')

client_me = ClientMeViewSet.as_view({
    'get': 'retrieve',
    'post': 'create',
    'put': 'update',
    'patch': 'partial_update',
})

urlpatterns = [
    path('swagger/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),

    # Админка
    path('admin/', admin.site.urls),

    # Авторизация и токены
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Регистрация и логин
    path('api/register/', RegisterUserView.as_view(), name='register'),
    path('api/login/', LoginView.as_view(), name='login'),
    path("api/confirm-email/<str:verification_code>/", ConfirmEmailView.as_view(), name="confirm-email"),
    path("api/resend-verification/", ResendVerificationEmailView.as_view(), name="resend-verification"),
    path("psychologists/change-password/", PsychologistChangePasswordView.as_view(), name="psychologist-change-password"),

                  # Публичные эндпоинты для клиентов
    path('api/clients/me/', client_me, name='client-me'),

    path('api/psychologists/<int:psychologist_id>/qualification/', PublicQualificationView.as_view(), name='public-qualification'),
    path('api/psychologists/<int:psychologist_id>/service_price/', PublicServicePriceView.as_view(), name='public-service-price'),
    path("api/psychologist/service_sessions/<str:session_id>/", ServicePriceSessionDetailView.as_view(), name="service-session-detail"),
    path('api/psychologists/<int:psychologist_id>/reviews/', PublicReviewListView.as_view(), name='public-reviews'),
    path('api/psychologists/<int:psychologist_id>/faq/', PublicFAQView.as_view(), name='public-faq'),
    path('api/psychologists/<int:psychologist_id>/profile/', PublicPsychologistProfileView.as_view(), name='public-psychologist-profile'),
    path('api/change-password/', ChangePasswordView.as_view(), name='change-password'),

    # Психологи (Профиль, Обновление)
    path('api/psychologists/me/profile/', PsychologistSelfProfileView.as_view(), name='psychologist-self-profile'),
    path('api/psychologist/profile/', PsychologistProfileView.as_view(), name='psychologist-profile'),
    path('api/psychologist/profile/personal-info/', PersonalInfoView.as_view(), name='personal-info'),
    path('api/psychologist/profile/qualification/', QualificationView.as_view(), name='qualification'),
    path('api/psychologist/profile/service_price/', ServicePriceView.as_view(), name='service-price'),
    path('api/psychologist/profile/faq/', FAQView.as_view(), name='faq'),
    path('api/psychologist/profile/documents/', DocumentView.as_view(), name='documents'),
    path('api/psychologist/sessions/', PsychologistSessionView.as_view(), name='psychologist-sessions'),

    # Каталог и одобрение психологов
    path('api/admin/approve-psychologist/<int:psychologist_id>/', AdminApprovePsychologistView.as_view(), name='admin_approve_psychologist'),

    # Отзывы (Получение и создание)
    path('api/reviews/', ReviewListView.as_view(), name='reviews'),
    path('api/reviews/create/', ReviewCreateView.as_view(), name='review-create'),

    # Telegram API (Привязка и аутентификация)
    path('api/auth/telegram/', TelegramAuthView.as_view(), name='telegram_auth'),
    path('api/verify-telegram/', VerifyTelegramView.as_view(), name='link_telegram'),

    #  Запись на быструю консультацию (только для зарегистрированных пользователей)
    path("api/quick-consultation/", QuickClientConsultationAPIView.as_view(), name="quick_consultation"),

    path('api/quick-consultation-anonymous/', QuickClientConsultationAnonymousAPIView.as_view()),
    path('api/auth/telegram/link-consultation/', TelegramAuthLinkConsultationAPIView.as_view()),

    # Запись на сеанс
    path('api/sessions/schedule/', ScheduleSessionView.as_view(), name='schedule-session'),
    path('sessions/schedule/<int:session_id>/', ScheduleSessionView.as_view(), name='cancel_session'),

    path('telegram-auth/', TelegramAuthPageView.as_view(), name='telegram-auth-page'),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Добавление обработки медиафайлов в режиме DEBUG
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)