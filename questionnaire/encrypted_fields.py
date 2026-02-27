# questionnaire/encrypted_fields.py
from django.db import models
import json
from .sm4 import sm4_encode, sm4_decode


class EncryptedTextField(models.TextField):
    """加密文本字段"""

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return sm4_decode(value)

    def get_prep_value(self, value):
        if value is None:
            return value
        return sm4_encode(value)

    def value_to_string(self, obj):
        value = self.value_from_object(obj)
        return sm4_decode(value) if value else ""


class EncryptedCharField(models.CharField):
    """加密字符字段"""

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return sm4_decode(value)

    def get_prep_value(self, value):
        if value is None:
            return value
        return sm4_encode(value)


class EncryptedJSONField(models.JSONField):
    """加密JSON字段"""

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        # 先解密，然后解析为JSON
        decrypted = sm4_decode(value)
        try:
            return json.loads(decrypted)
        except:
            return decrypted

    def get_prep_value(self, value):
        if value is None:
            return value
        # 先序列化为JSON字符串，再加密
        if isinstance(value, dict) or isinstance(value, list):
            json_str = json.dumps(value, ensure_ascii=False)
        else:
            json_str = str(value)
        return sm4_encode(json_str)