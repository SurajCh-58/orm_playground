"""
Django settings for orm_playground project.
"""
from pathlib import Path
import os
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

SECRET_KEY = 'django-insecure-%f5$g$jvz_q5ygg+6!)c+^&7kw3*g%c5514=c57tk0&6iyacz6'

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'playground',
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

ROOT_URLCONF = 'orm_playground.urls'

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

WSGI_APPLICATION = 'orm_playground.wsgi.application'

# ── Database ────────────────────────────────────────────────────────────────
# Single Postgres database for everything — ORM queries, sessions, admin,
# and the raw-SQL playground mode all use the same connection.
# The 'postgres' alias is kept as an alias to the same DB so views.py
# _run_pgsql() continues to work without changes.
_PG = {
    'ENGINE':   'django.db.backends.postgresql',
    'NAME':     env('PG_NAME',     default='orm_playground'),
    'USER':     env('PG_USER',     default='postgres'),
    'PASSWORD': env('PG_PASSWORD', default=''),
    'HOST':     env('PG_HOST',     default='localhost'),
    'PORT':     env('PG_PORT',     default='5432'),
}
DATABASES = {
    'default':  _PG,
    'postgres': _PG,   # alias used by _run_pgsql() in views.py
}

# ── Sessions ───────────────────────────────────────────────────────────────
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# ── Internationalisation ───────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
