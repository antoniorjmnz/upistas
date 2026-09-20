"""Ajustes de la web de Alberto (Django).

Todo lo que cambia entre el portátil y el servidor se lee del entorno (el `.env` de la raíz lo carga
`upistas.config`). Sin variables, la web arranca como en producción: sin DEBUG y pidiendo su clave.
Las variables están explicadas en `.env.example` y en docs/web.md («En producción»).
"""

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _si(nombre: str, por_defecto: str = "0") -> bool:
    return os.getenv(nombre, por_defecto).strip().lower() in {"1", "true", "si", "sí", "yes"}


# DEBUG apagado salvo que el .env diga DJANGO_DEBUG=1 (en el portátil, nunca en el servidor).
DEBUG = _si("DJANGO_DEBUG")

# La clave viene del entorno. Solo con DEBUG vale una de desarrollo; sin DEBUG y sin clave la web no arranca.
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
SECRET_KEY_GENERADA = False  # True cuando no vino del entorno: vale en el portátil, no en un servidor
if not SECRET_KEY:
    # Sin variable, una clave estable por máquina, guardada fuera de git: así arrancar en el portátil no exige nada.
    _fichero_clave = BASE_DIR / ".django_secret_key"
    try:
        SECRET_KEY = _fichero_clave.read_text(encoding="utf-8").strip()
    except OSError:
        SECRET_KEY = ""
    if len(SECRET_KEY) < 50:
        import secrets as _secrets

        SECRET_KEY = _secrets.token_urlsafe(60)
        try:
            _fichero_clave.write_text(SECRET_KEY, encoding="utf-8")
        except OSError:
            pass  # disco de solo lectura: la clave dura lo que dure el proceso
    SECRET_KEY_GENERADA = True

# Desde dónde se puede abrir la web: los dos locales, o lo que diga el entorno (lista separada por comas).
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]

# Orígenes de confianza para los formularios cuando la web se sirve desde un dominio (Cloudflare, previews...).
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

# Detrás de Cloudflare (o cualquier proxy que termine el TLS) la petición llega por http con esta cabecera:
# sin esto Django cree que la web va sin https y rechaza los formularios por CSRF.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "web.panel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # sirve el CSS, las letras y htmx también sin DEBUG
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "web.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "web.panel.contexto.panel",
            ],
        },
    },
]

WSGI_APPLICATION = "web.wsgi.application"

# Cuando un formulario llega sin su marca de seguridad (sesión caducada, otro dominio): página propia, no la de Django.
CSRF_FAILURE_VIEW = "web.panel.views.errores.csrf_fallo"


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

# La misma base de datos que el pipeline (DATABASE_URL en .env): SQLite en local, Postgres para escalar.
from upistas.config import base_de_datos_django, settings as upistas_settings  # noqa: E402

DATABASES = {"default": base_de_datos_django(upistas_settings.database_url)}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = "es-es"

TIME_ZONE = "Europe/Madrid"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = Path(os.getenv("STATIC_ROOT", BASE_DIR / "staticfiles"))  # donde deja los ficheros `collectstatic`; no se sube a git
try:
    STATIC_ROOT.mkdir(exist_ok=True)  # WhiteNoise avisa si la carpeta no existe; en un disco de solo lectura ya la creó el build
except OSError:
    pass
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
# WhiteNoise busca los ficheros donde están (como runserver con DEBUG), así que la web funciona con o sin collectstatic.
WHITENOISE_USE_FINDERS = True
WHITENOISE_MIMETYPES = {".webmanifest": "application/manifest+json"}

# Los PDF que suben por la web, guardados por su huella. Nunca se sube a git.
MEDIA_ROOT = Path(os.getenv("ALMACEN_DIR", BASE_DIR / "almacen"))
MEDIA_URL = "almacen/"
DATA_UPLOAD_MAX_NUMBER_FILES = 1000
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024


# La web no manda correo: se deja el MAILERS por defecto de Django (SMTP, que nunca se usa) y así
# `check --deploy` no avisa de un backend de desarrollo.


# Cabeceras seguras. Las de siempre van en todos los casos; las que exigen HTTPS, solo con DJANGO_HTTPS=1
# (cuando la web va detrás de Cloudflare o de otro proxy que termina el TLS y manda X-Forwarded-Proto).

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "SAMEORIGIN"  # el visor carga el PDF en un marco de la misma web
SILENCED_SYSTEM_CHECKS = ["security.W019", "mail.E001"]  # W019 pide DENY y SAMEORIGIN es a propósito (visor); la web no manda correos
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

HTTPS = _si("DJANGO_HTTPS")
if HTTPS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}
