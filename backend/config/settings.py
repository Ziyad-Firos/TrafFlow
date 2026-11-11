from pathlib import Path
import os

import dj_database_url

BASE_DIR = Path(__file__).resolve().parents[2]
SECRET_KEY = os.getenv("SECRET_KEY", "local-development-only-change-me")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if host.strip()]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "corsheaders",
    "rest_framework",
    "backend.runs",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]
ROOT_URLCONF = "backend.config.urls"
WSGI_APPLICATION = "backend.config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

database_url = os.getenv("DATABASE_URL")
DATABASES = {
    "default": dj_database_url.parse(database_url, conn_max_age=600, ssl_require=not DEBUG)
    if database_url
    else {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "local.sqlite3"}
}

CORS_ALLOWED_ORIGINS = [
    origin.strip() for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if origin.strip()
]
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {"anon": "5/min"},
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}
