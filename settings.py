# survey_system/settings.py 新增配置
import os
from pathlib import Path
import secrets

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent


# 从环境变量读取密钥
def get_secret_key():
    """获取或生成安全的密钥"""
    secret_file = BASE_DIR / ".secret_key"

    if secret_file.exists():
        with open(secret_file, "r") as f:
            key = f.read().strip()
    else:
        # 生成256位密钥
        key = secrets.token_urlsafe(50)
        with open(secret_file, "w") as f:
            f.write(key)
        os.chmod(secret_file, 0o400)  # 只读权限

    return key


# 安全密钥
SECRET_KEY = get_secret_key()

# SM4加密密钥（必须16字节）
SM4_SECRET_KEY = os.environ.get("SM4_SECRET_KEY", "0123456789abcdef")
if len(SM4_SECRET_KEY) != 16:
    raise ValueError("SM4_SECRET_KEY must be 16 characters")

# 安全头配置
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# HTTPS配置（生产环境）
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "False") == "True"
SECURE_HSTS_SECONDS = 31536000  # 1年
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# 会话安全
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "False") == "True"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = os.environ.get("CSRF_COOKIE_SECURE", "False") == "True"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")

# 密码哈希配置
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

# 密码策略
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": 12,
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# 数据库配置（MySQL）
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("DB_NAME", "survey_system"),
        "USER": os.environ.get("DB_USER", "survey_user"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'",
            "ssl": (
                {
                    "ca": os.environ.get("MYSQL_SSL_CA", None),
                }
                if os.environ.get("MYSQL_SSL", "False") == "True"
                else {}
            ),
        },
        "CONN_MAX_AGE": 600,  # 连接池
        "CONN_HEALTH_CHECKS": True,
    }
}

# 缓存配置（Redis）
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "PASSWORD": os.environ.get("REDIS_PASSWORD", None),
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
            "CONNECTION_POOL_KWARGS": {
                "max_connections": 100,
                "retry_on_timeout": True,
            },
            "COMPRESSOR": "django_redis.compressors.zlib.ZlibCompressor",
        },
        "KEY_PREFIX": "survey",
        "VERSION": 1,
    }
}

# 会话使用Redis
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# 文件上传限制
DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB
FILE_UPLOAD_PERMISSIONS = 0o644
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o755

# 日志配置
LOGGING_DIR = BASE_DIR / "logs"
LOGGING_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
        "audit": {
            "format": "{asctime} - {user} - {ip} - {action} - {details}",
        },
    },
    "filters": {
        "require_debug_false": {
            "()": "django.utils.log.RequireDebugFalse",
        },
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "filters": ["require_debug_true"],
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file": {
            "level": "WARNING",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGGING_DIR / "django.log",
            "maxBytes": 1024 * 1024 * 10,  # 10MB
            "backupCount": 10,
            "formatter": "verbose",
        },
        "security_file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGGING_DIR / "security.log",
            "maxBytes": 1024 * 1024 * 5,  # 5MB
            "backupCount": 5,
            "formatter": "verbose",
        },
        "audit_file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGGING_DIR / "audit.log",
            "maxBytes": 1024 * 1024 * 5,  # 5MB
            "backupCount": 5,
            "formatter": "audit",
        },
        "mail_admins": {
            "level": "ERROR",
            "filters": ["require_debug_false"],
            "class": "django.utils.log.AdminEmailHandler",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file", "mail_admins"],
            "level": "INFO",
            "propagate": True,
        },
        "django.security": {
            "handlers": ["security_file"],
            "level": "INFO",
            "propagate": False,
        },
        "survey.audit": {
            "handlers": ["audit_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
