# questionnaire/utils.py
import qrcode
import random
import string
from io import BytesIO
import base64
from django.core.cache import cache
import matplotlib
matplotlib.use('Agg')          # 无 GUI 环境必加
import matplotlib.pyplot as plt

def generate_qr_code(data, size=300):
    """生成二维码"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size, size))

    return img


def generate_short_code(length=6):
    """生成短码"""
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        # 检查是否已存在
        if not cache.get(f'shortcode_{code}'):
            cache.set(f'shortcode_{code}', True, timeout=3600)
            return code


def detect_browser(user_agent):
    """检测浏览器类型"""
    user_agent = user_agent.lower()
    if 'micromessenger' in user_agent:
        return 'wechat'
    elif 'alipay' in user_agent:
        return 'alipay'
    elif 'weibo' in user_agent:
        return 'weibo'
    elif 'qq' in user_agent:
        return 'qq'
    else:
        return 'browser'

def pie_base64(labels, sizes):
    """临时饼图 → base64，先保证不报错"""
    if not labels or not sizes:
        return ''
    plt.figure(figsize=(3, 3))
    plt.pie(sizes, labels=labels, autopct='%1.1f%%')
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    plt.close()
    return 'data:image/png;base64,' + b64