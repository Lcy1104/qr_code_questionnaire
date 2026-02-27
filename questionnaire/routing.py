# questionnaire/routing.py
from django.urls import re_path
from . import consumers

print("DEBUG: 加载 WebSocket 路由配置")

# 确保路径正确，可能前面需要加斜杠
websocket_urlpatterns = [
    re_path(r'^ws/notifications/$', consumers.NotificationConsumer.as_asgi()),
    re_path(r'^ws/questionnaire/(?P<questionnaire_id>[^/]+)/$', consumers.QuestionnaireQRCodeConsumer.as_asgi()),
]

print(f"DEBUG: WebSocket 路由配置: {websocket_urlpatterns}")