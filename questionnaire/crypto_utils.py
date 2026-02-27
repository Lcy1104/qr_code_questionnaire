# questionnaire/crypto_utils.py
import json
import base64
from typing import Any, Dict, Union
from django.core.cache import cache
from django.db import models
from django.conf import settings
from .sm4 import sm4_encode, sm4_decode


class SM4Field:
    """SM4加密字段处理器"""

    @staticmethod
    def encrypt_data(data: Any) -> str:
        """加密数据"""
        if data is None:
            return None

        if isinstance(data, dict) or isinstance(data, list):
            data = json.dumps(data, ensure_ascii=False)
        else:
            data = str(data)

        return sm4_encode(data)

    @staticmethod
    def decrypt_data(encrypted_data: str) -> Any:
        """解密数据"""
        if encrypted_data is None:
            return None

        try:
            decrypted = sm4_decode(encrypted_data)
            # 尝试解析为JSON
            try:
                return json.loads(decrypted)
            except json.JSONDecodeError:
                return decrypted
        except Exception as e:
            # 记录错误但返回原始数据
            print(f"SM4解密失败: {e}")
            return encrypted_data


class EncryptedJSONField(models.JSONField):
    """加密的JSON字段"""

    def from_db_value(self, value, expression, connection):
        """从数据库读取时解密"""
        if value is None:
            return value
        return SM4Field.decrypt_data(value)

    def get_prep_value(self, value):
        """保存到数据库时加密"""
        if value is None:
            return value
        return SM4Field.encrypt_data(value)

    def value_to_string(self, obj):
        """序列化为字符串时解密"""
        value = self.value_from_object(obj)
        return json.dumps(value, ensure_ascii=False)


class EncryptedTextField(models.TextField):
    """加密的文本字段"""

    def from_db_value(self, value, expression, connection):
        """从数据库读取时解密"""
        if value is None:
            return value
        return SM4Field.decrypt_data(value)

    def get_prep_value(self, value):
        """保存到数据库时加密"""
        if value is None:
            return value
        return SM4Field.encrypt_data(value)


class EncryptedCharField(models.CharField):
    """加密的字符字段"""

    def from_db_value(self, value, expression, connection):
        """从数据库读取时解密"""
        if value is None:
            return value
        return SM4Field.decrypt_data(value)

    def get_prep_value(self, value):
        """保存到数据库时加密"""
        if value is None:
            return value
        return SM4Field.encrypt_data(value)