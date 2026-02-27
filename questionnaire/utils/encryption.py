# questionnaire/utils/encryption.py
from django.db import models
from gmssl import sm4

def get_sm4_encryptor():
    # 返回一个 SM4 加密器实例
    return sm4.CryptSM4()

class SM4EncryptedField(models.TextField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_prep_value(self, value):
        if value is None:
            return value
        encryptor = get_sm4_encryptor()
        return encryptor.crypt_ecb(value.encode(), sm4.SM4_ENCRYPT).hex()

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        decryptor = get_sm4_encryptor()
        return decryptor.crypt_ecb(bytes.fromhex(value), sm4.SM4_DECRYPT).decode()