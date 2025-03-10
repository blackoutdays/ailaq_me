from django.urls import path, include
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from ailaq.views import (
    LoginView, RegisterUserView, AdminApprovePsychologistView, PsychologistProfileView,
    QualificationView, PersonalInfoView, FAQView, DocumentView, ReviewCreateView,
    ReviewListView, TelegramAuthView, LinkTelegramView, VerificationCodeView,
    NewVerificationCodeView, QuickClientConsultationAPIView, CatalogViewSet,
    ClientProfileViewSet, ServicePriceView, ScheduleSessionView
)

router = DefaultRouter()
router.register(r'catalog', CatalogViewSet, basename='catalog')
router.register(r'clients', ClientProfileViewSet, basename='client-profiles')

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

    # Психологи (Профиль, Обновление)
    path('api/psychologist/profile/', PsychologistProfileView.as_view(), name='psychologist-profile'),
    path('api/psychologist/profile/personal-info/', PersonalInfoView.as_view(), name='personal-info'),
    path('api/psychologist/profile/qualification/', QualificationView.as_view(), name='qualification'),
    path('api/psychologist/profile/service_price/', ServicePriceView.as_view(), name='service-price'),
    path('api/psychologist/profile/faq/', FAQView.as_view(), name='faq'),
    path('api/psychologist/profile/documents/', DocumentView.as_view(), name='documents'),

    # Каталог и одобрение психологов
    path('api/admin/approve-psychologist/<int:psychologist_id>/', AdminApprovePsychologistView.as_view(), name='admin_approve_psychologist'),

    # Отзывы (Получение и создание)
    path('api/reviews/', ReviewListView.as_view(), name='reviews'),
    path('api/reviews/create/', ReviewCreateView.as_view(), name='review-create'),

    # Telegram API (Привязка и аутентификация)
    path('api/auth/telegram/', TelegramAuthView.as_view(), name='telegram_auth'),
    path('api/link-telegram/', LinkTelegramView.as_view(), name='link_telegram'),

    # Верификационный код
    path('api/verification-code/', VerificationCodeView.as_view(), name='verification_code'),
    path('api/new-verification-code/', NewVerificationCodeView.as_view(), name='new_verification_code'),

    # Быстрая консультация (Telegram)
    path('api/quick-consultation/', QuickClientConsultationAPIView.as_view(), name='quick_consultation_api'),

    # Запись на сеанс
    path('api/sessions/schedule/', ScheduleSessionView.as_view(), name='schedule-session'),

    path('api/', include(router.urls)),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Добавление обработки медиафайлов в режиме DEBUG
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)