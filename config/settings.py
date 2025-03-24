from pathlib import Path
from datetime import timedelta
import os
import environ

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://91.147.92.219:8080")

env = environ.Env(
    DEBUG=(bool, False)
)

environ.Env.read_env()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = env('SECRET_KEY', default='change-me')

DEBUG = env.bool("DEBUG", default=True)

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=['*'])

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND')

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'

CELERY_TIMEZONE = 'Asia/Almaty'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'drf_spectacular',
    'corsheaders',
    'ailaq',
    'django_filters',
    'django_celery_results',
    'django_celery_beat',
]

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=7),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': env('JWT_SECRET_KEY', default='change-me'),
    'VERIFYING_KEY': None,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# CORS_ALLOWED_ORIGINS = [
#     "http://localhost:8001",
#     "http://127.0.0.1:8001",
#     "http://localhost:8000",
#     "http://127.0.0.1:8000",
#     "https://d6e4-94-247-135-103.ngrok-free.ap"
# ]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'corsheaders.middleware.CorsMiddleware',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.AllowAny',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],  # Указываем путь к шаблонам
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('POSTGRES_DB', default='ailaq'),
        'USER': env('POSTGRES_USER', default='aruka'),
        'PASSWORD': env('POSTGRES_PASSWORD', default='aruka'),
        'HOST': env('POSTGRES_HOST', default='db'),
        'PORT': env('POSTGRES_PORT', default='5432'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 8},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

DEBUG  = True

CORS_ALLOW_ALL_ORIGINS = True

CORS_ALLOW_CREDENTIALS = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, "static")]
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_HOST = 'smtp.gmail.com'
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='aruka.larksss@gmail.com')
# EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='taee xbjt arjo zjch')
# DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='aruka.larksss@gmail.com')

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'mail.ailaq.me'
EMAIL_PORT = 587
EMAIL_USE_TLS = False
EMAIL_USE_SSL = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', 'info@ailaq.me')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = 'info@ailaq.me'

# LOGGING = {
#     'version': 1,
#     'disable_existing_loggers': False,
#     'formatters': {
#         'verbose': {
#             'format': '{levelname} {asctime} {message}',
#             'style': '{',
#         },
#     },
#     'handlers': {
#         'console': {
#             'level': 'INFO',
#             'class': 'logging.StreamHandler',
#             'formatter': 'verbose',
#         },
#     },
#     'loggers': {
#         'django': {
#             'handlers': ['console'],
#             'level': 'INFO',
#             'propagate': True,
#         },
#         'django.request': {
#             'handlers': ['console'],
#             'level': 'WARNING',
#             'propagate': False,
#         },
#         'django.security': {
#             'handlers': ['console'],
#             'level': 'WARNING',
#             'propagate': False,
#         },
#         'telegram_auth': {  # ✅ Теперь внутри loggers
#             'handlers': ['console'],
#             'level': 'DEBUG',
#             'propagate': False,
#         },
#     },
# }

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'My API',
    'DESCRIPTION': 'API documentation for the project',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': True,
    'ENUM_NAME_OVERRIDES': {
        'ailaq.models.QuickClientConsultationRequest.gender': 'ailaq.enums.ClientGenderEnum',
        'ailaq.models.QuickClientConsultationRequest.psychologist_gender': 'ailaq.enums.PreferredPsychologistGenderEnum',
        'ailaq.models.QuickClientConsultationRequest.psychologist_language': 'ailaq.enums.CommunicationLanguageEnum',
        'ailaq.models.QuickClientConsultationRequest.preferred_psychologist_age': 'ailaq.enums.PsychologistAgeEnum',
        'ailaq.models.PsychologistApplication.gender': 'ailaq.enums.PsychologistGenderEnum',
        'ailaq.models.PsychologistApplication.communication_language': 'ailaq.enums.CommunicationLanguageEnum',
    }
}

TELEGRAM_BOT_TOKEN = env('TELEGRAM_BOT_TOKEN', default='7591573688:AAFtWbtZ4v5UcS1Hyl121gJlxLA8riIuB4Q')
AUTH_USER_MODEL = 'ailaq.CustomUser'

REQUEST_COST = env.float('REQUEST_COST', default=10.00)
ADMIN_EMAIL = env('ADMIN_EMAIL', default='info@ailaq.me')
DEFAULT_CATALOG_REQUESTS_THRESHOLD = env.int('DEFAULT_CATALOG_REQUESTS_THRESHOLD', default=3)
