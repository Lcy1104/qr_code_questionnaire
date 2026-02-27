"""
国密 SM4 ECB 加解密（gmssl 版）
"""
import base64
from gmssl.sm4 import CryptSM4, SM4_ENCRYPT, SM4_DECRYPT
from django.conf import settings

# 32 位 hex → 16 字节
_KEY = bytes.fromhex(settings.SM4_KEY)

_crypt = CryptSM4()
_crypt.set_key(_KEY, SM4_ENCRYPT)   # 加密模式
_crypt_dec = CryptSM4()
_crypt_dec.set_key(_KEY, SM4_DECRYPT)  # 解密模式


def _pkcs7_pad(data: bytes) -> bytes:
    pad = 16 - len(data) % 16
    return data + bytes([pad] * pad)


def _pkcs7_unpad(data: bytes) -> bytes:
    return data[:-data[-1]]


def sm4_encode(s: str) -> str:
    if not s:
        return ''
    data = s.encode('utf-8')
    padded = _pkcs7_pad(data)
    cipher = _crypt.crypt_ecb(padded)
    return base64.b64encode(cipher).decode()


def sm4_decode(s: str) -> str:
    if not s:
        return ''
    cipher = base64.b64decode(s)
    padded = _crypt_dec.crypt_ecb(cipher)
    return _pkcs7_unpad(padded).decode('utf-8')