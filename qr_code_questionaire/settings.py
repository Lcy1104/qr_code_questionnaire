import os
from pathlib import Path
import environ
import socket
import logging
from urllib.parse import quote

#彻底关掉 matplotlib 的字体日志
logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)
# 初始化环境变量
env = environ.Env()

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 指定 .env 文件路径
env_path = BASE_DIR / '.env'

print(f"DEBUG: 尝试从以下路径加载环境变量: {env_path}")

# 检查 .env 文件是否存在
if env_path.exists():
    print(f"DEBUG: .env 文件找到")
    try:
        # 读取 .env 文件
        environ.Env.read_env(env_path)
        print(f"DEBUG: .env 文件加载成功")

        # 读取配置
        SECRET_KEY = env('SECRET_KEY', default='django-insecure-development-key-only')
        DEBUG = env.bool('DEBUG', default=True)

        print(
            f"DEBUG: SECRET_KEY 读取成功: {SECRET_KEY[:20] if SECRET_KEY and len(SECRET_KEY) > 20 else SECRET_KEY}...")
        print(f"DEBUG: DEBUG 读取成功: {DEBUG}")

    except Exception as e:
        print(f"DEBUG: 读取 .env 文件失败: {e}")
        # 如果读取失败，使用默认值
        SECRET_KEY = 'django-insecure-development-key-only'
        DEBUG = True
else:
    print(f"DEBUG: .env 文件不存在于: {env_path}")
    # 如果文件不存在，使用默认值
    SECRET_KEY = 'django-insecure-development-key-only'
    DEBUG = True

try:
    hostname = socket.gethostname()
    LOCAL_IP = socket.gethostbyname(hostname)
    SERVER_URL = f"http://{LOCAL_IP}:8000"
except:
    SERVER_URL = 'http://localhost:8000'
# 允许的主机 - 从环境变量读取，确保是列表
#ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])
ALLOWED_HOSTS = ['*']
SM4_KEY = env('SM4_KEY', default='0123456789abcdeffedcba9876543210')
# 验证SM4密钥
if len(SM4_KEY) != 32:
    raise ValueError(f"SM4_KEY must be 32 hex characters (16 bytes), got {len(SM4_KEY)}")
try:
    bytes.fromhex(SM4_KEY)
except ValueError:
    raise ValueError("SM4_KEY must be a valid hex string")


AUTH_USER_MODEL = 'questionnaire.User'

# 应用定义
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sessions',

    # 第三方应用
    'rest_framework',
    'corsheaders',
    'django_filters',
    'axes',
    'django_rq',
    'channels',

    # 自定义应用
    'questionnaire',
]

# 中间件
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'axes.middleware.AxesMiddleware',
    'questionnaire.middleware.InviteSessionCleanupMiddleware',
    'questionnaire.middleware.NotificationPageMessagesMiddleware',
]

# 认证后端配置
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesBackend',
    'questionnaire.backends.EncryptedFieldBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Axes 配置（防暴力破解）
AXES_ENABLED = True
AXES_FAILURE_LIMIT = 5  # 5次失败后锁定
AXES_COOLOFF_TIME = 1  # 锁定1小时（可以用数字表示小时，或用timedelta）
AXES_RESET_ON_SUCCESS = True  # 成功登录后重置失败计数
AXES_LOCKOUT_PARAMETERS = [["username"], ["ip_address", "username"]]
AXES_LOCKOUT_CALLABLE = "questionnaire.views_auth.lockout_response"  # 自定义锁定响应
#AXES_USE_USER_AGENT = True  # 使用User-Agent追踪
AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT = True  # 锁定期间失败重置冷却时间
AXES_CACHE = 'default'  # 使用默认缓存（Redis）
AXES_HANDLER = 'axes.handlers.database.AxesDatabaseHandler'
AXES_LOCKOUT_TEMPLATE = 'registration/locked.html'  # 锁定页面模板
# Redis缓存配置（用于django-axes）
REDIS_URL = env('REDIS_URL', default='redis://:Password123@redis@localhost:6379/0')

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,  # 直接使用包含密码的URL
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 100,
                'retry_on_timeout': True,
            },
            # 注释掉或删除 PASSWORD 行，因为密码已经在 URL 中
            # 'PASSWORD': None,
            'SOCKET_CONNECT_TIMEOUT': 5,
            'SOCKET_TIMEOUT': 5,
        },
        'KEY_PREFIX': 'django_axes',
        'TIMEOUT': 86400,
    }
}

SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

RQ_QUEUES = {
    'default': {
        'HOST': 'localhost',
        'PORT': 6379,
        'DB': 0,
        'PASSWORD': 'Password123@redis',
    }
}

# 根URL配置
ROOT_URLCONF = 'qr_code_questionaire.urls'

# 模板配置
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'questionnaire.context_processors.notifications_processor',
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# WSGI应用
WSGI_APPLICATION = 'qr_code_questionaire.wsgi.application'

# settings.py - 数据库配置部分
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('DB_NAME', default='qr_code_questionnaire_db'),
        'USER': env('DB_USER', default='root'),
        'PASSWORD': env('DB_PASSWORD', default='root'),
        'HOST': env('DB_HOST', default='localhost'),
        'PORT': env('DB_PORT', default='3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        }
    }
}

# 密码验证
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 8,
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# 国际化
LANGUAGE_CODE = 'zh-hans'
USE_TZ = False
TIME_ZONE = env('TIME_ZONE', default='Asia/Shanghai')
USE_I18N = True

# 静态文件
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# 媒体文件
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# 默认主键
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 登录配置
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'

# 会话配置
SESSION_COOKIE_AGE = 1209600  # 2周
SESSION_SAVE_EVERY_REQUEST = True

# 安全配置
if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# CORS配置
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# 让业务日志打到控制台（开发环境）
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'questionnaire': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
    # 根logger，捕获所有日志
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}

try:
    from questionnaire.font_config import init_matplotlib_font
    init_matplotlib_font()
except ImportError:
    pass


# 添加 Channels 配置
ASGI_APPLICATION = 'qr_code_questionaire.asgi.application'

# 配置 Channels 层（使用 Redis 作为后端）
# 构建 Redis URL（确保使用编码后的密码）
REDIS_PASSWORD = env('REDIS_PASSWORD', default='Password123@redis')
REDIS_HOST = env('REDIS_HOST', default='localhost')
REDIS_PORT = env.int('REDIS_PORT', default=6379)
REDIS_DB = env.int('REDIS_DB', default=0)

# 对密码进行 URL 编码
encoded_password = quote(REDIS_PASSWORD, safe='') if REDIS_PASSWORD else ''

# 构建 Redis URL
if encoded_password:
    REDIS_URL = f"redis://:{encoded_password}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
else:
    REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

# Channels 层配置 - 使用统一的 Redis URL
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [REDIS_URL],  # 使用统一配置
        },
    },
}