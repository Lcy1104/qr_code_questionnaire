"""
ASGI config for qr_code_questionaire project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application

# 设置 Django 环境变量
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qr_code_questionaire.settings")

# 获取默认的 ASGI 应用
django_asgi_app = get_asgi_application()

print("=" * 50)
print("DEBUG: 正在加载 ASGI 应用")
print("=" * 50)

# 尝试导入 Channels 相关模块
try:
    from channels.routing import ProtocolTypeRouter, URLRouter
    from channels.auth import AuthMiddlewareStack

    print("DEBUG: Channels 模块导入成功")

    # 尝试导入 WebSocket 路由
    try:
        from questionnaire.routing import websocket_urlpatterns

        print(f"DEBUG: WebSocket 路由导入成功，路径: {websocket_urlpatterns}")

        # 创建 WebSocket 应用
        websocket_application = AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )

        # 创建完整的 ASGI 应用
        application = ProtocolTypeRouter({
            "http": django_asgi_app,
            "websocket": websocket_application,
        })

        print("DEBUG: ASGI 应用配置完成")
        print(f"DEBUG: WebSocket 路由数量: {len(websocket_urlpatterns)}")

    except ImportError as e:
        print(f"DEBUG: 导入 WebSocket 路由失败: {e}")
        import traceback

        traceback.print_exc()

        # 如果没有 WebSocket 路由，只使用 HTTP
        application = ProtocolTypeRouter({
            "http": django_asgi_app,
            "websocket": AuthMiddlewareStack(URLRouter([])),
        })
        print("DEBUG: 使用空 WebSocket 路由")

except ImportError as e:
    # 如果 Channels 没有安装，回退到纯 HTTP
    print(f"DEBUG: Channels 相关模块导入失败: {e}")
    import traceback

    traceback.print_exc()
    print("DEBUG: 使用纯 HTTP ASGI 应用")
    application = django_asgi_app

print("=" * 50)
print("DEBUG: ASGI 应用加载完成")
print("=" * 50)