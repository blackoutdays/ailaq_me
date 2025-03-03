from django.shortcuts import render
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularSwaggerView, SpectacularAPIView
from ailaq.views import LoginView, RegisterUserView, SubmitPsychologistApplicationView, AdminApprovePsychologistView, \
    UpdatePsychologistProfileView, CatalogView, BuyRequestsView, PsychologistProfileViewSet, PsychologistProfileView, \
    QualificationView, PersonalInfoView, FAQView, DocumentView, ReviewListCreateView, \
    ReviewDetailView, TelegramAuthView, LinkTelegramView, VerificationCodeView, NewVerificationCodeView, \
    QuickClientConsultationAPIView
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

router = DefaultRouter()
router.register(r'psychologists', PsychologistProfileViewSet)

urlpatterns = [
    path('api-token-auth/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api-token-refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('admin/', admin.site.urls),
    path('swagger/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('login/', LoginView.as_view(), name='login'),
    path('register/', RegisterUserView.as_view(), name='register'),
    path('submit-psychologist-application/', SubmitPsychologistApplicationView.as_view(), name='submit_psychologist_application'),
    path('update-psychologist-profile/', UpdatePsychologistProfileView.as_view(), name='update_psychologist_profile'),
    path('psychologist-profile/<int:psychologist_id>/', PsychologistProfileView.as_view(), name='psychologist-profile'),
    path('admin-approve-psychologist/<int:psychologist_id>/', AdminApprovePsychologistView.as_view(),
         name='admin_approve_psychologist'),
    path('catalog/', CatalogView.as_view(), name='catalog'),
    path('buy-request/', BuyRequestsView.as_view(), name='buy_request'),
    path('psychologist-application/personal-info/', PersonalInfoView.as_view()),
    path('psychologist-application/qualification/', QualificationView.as_view()),
    path('psychologist-application/faq/', FAQView.as_view()),
    path('psychologist-application/documents/', DocumentView.as_view()),
    path('reviews/', ReviewListCreateView.as_view(), name='review-list-create'),
    path('reviews/<int:pk>/', ReviewDetailView.as_view(), name='review-detail'),
    path('auth/telegram/', TelegramAuthView.as_view(), name='telegram_auth'),
    path('telegram-login/', lambda request: render(request, "telegram_auth.html"), name="telegram-login"),
    path('link-telegram/', LinkTelegramView.as_view(), name='link_telegram'),
    path('verification-code/', VerificationCodeView.as_view(), name='verification_code'),
    path('new-verification-code/', NewVerificationCodeView.as_view(), name='new_verification_code'),
    path('api/quick-consultation/', QuickClientConsultationAPIView.as_view(), name='quick_consultation_api'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)