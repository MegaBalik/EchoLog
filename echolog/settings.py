from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-only-change-me')
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [u.strip() for u in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if u.strip()]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'outreach',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'echolog.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'echolog.wsgi.application'
ASGI_APPLICATION = 'echolog.asgi.application'

if os.environ.get('POSTGRES_DB'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ['POSTGRES_DB'],
            'USER': os.environ.get('POSTGRES_USER', 'echolog'),
            'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
            'HOST': os.environ.get('POSTGRES_HOST', '127.0.0.1'),
            'PORT': os.environ.get('POSTGRES_PORT', '5432'),
            'CONN_MAX_AGE': 60,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.environ.get('ECHOLOG_TIME_ZONE', 'Europe/Prague')
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'outreach:dashboard'
LOGOUT_REDIRECT_URL = 'login'

# EchoLog operational settings
ECHOLOG_DEFAULT_SENDER_DAILY_LIMIT = int(
    os.environ.get('ECHOLOG_DEFAULT_SENDER_DAILY_LIMIT', os.environ.get('ECHOLOG_DAILY_LIMIT', '30'))
)
# Backward-compatible alias used by older deployments and bootstrap migration.
ECHOLOG_DAILY_LIMIT = ECHOLOG_DEFAULT_SENDER_DAILY_LIMIT
ECHOLOG_SEND_WINDOW_START = os.environ.get('ECHOLOG_SEND_WINDOW_START', '08:30')
ECHOLOG_SEND_WINDOW_END = os.environ.get('ECHOLOG_SEND_WINDOW_END', '16:30')
ECHOLOG_SEND_WEEKDAYS_ONLY = os.environ.get('ECHOLOG_SEND_WEEKDAYS_ONLY', '1') == '1'
ECHOLOG_DEFAULT_FOLLOWUP_DAYS = int(os.environ.get('ECHOLOG_DEFAULT_FOLLOWUP_DAYS', '14'))
ECHOLOG_GOOGLE_CLIENT_SECRET_FILE = os.environ.get(
    'ECHOLOG_GOOGLE_CLIENT_SECRET_FILE', str(BASE_DIR / 'secrets' / 'google_client_secret.json')
)
ECHOLOG_GOOGLE_TOKEN_FILE = os.environ.get(
    'ECHOLOG_GOOGLE_TOKEN_FILE', str(BASE_DIR / 'secrets' / 'google_token.json')
)
ECHOLOG_GOOGLE_TOKEN_DIR = os.environ.get(
    'ECHOLOG_GOOGLE_TOKEN_DIR', str(Path(ECHOLOG_GOOGLE_TOKEN_FILE).parent)
)
# Legacy bootstrap values: migration 0003 converts the existing single-account setup
# into the first SenderAccount. New senders are configured in the EchoLog UI.
ECHOLOG_FROM_EMAIL = os.environ.get('ECHOLOG_FROM_EMAIL', 'info@rb-translations.cz')

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '3600'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = False
