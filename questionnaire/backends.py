# questionnaire/backends.py
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth import get_user_model
from .sm4 import sm4_encode

User = get_user_model()


class EncryptedFieldBackend(BaseBackend):
    """支持加密字段查找的认证后端"""

    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            # 先尝试直接查找用户
            user = User.objects.get(username=username)
            if user.check_password(password):
                return user
        except User.DoesNotExist:
            # 如果找不到，可能是加密字段的问题
            pass

        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None