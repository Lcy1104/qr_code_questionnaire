# check_captcha.py
import os
import django
import sys

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qr_code_questionaire.settings')
django.setup()

print("=" * 60)
print("DJANGO-SIMPLE-CAPTCHA 诊断报告")
print("=" * 60)

# 1. 检查是否在 INSTALLED_APPS 中
from django.conf import settings

if 'captcha' in settings.INSTALLED_APPS:
    print("✅ captcha 在 INSTALLED_APPS 中")
else:
    print("❌ captcha 不在 INSTALLED_APPS 中")
    print("当前 INSTALLED_APPS:", settings.INSTALLED_APPS)
    sys.exit(1)

# 2. 尝试导入 captcha
try:
    import captcha

    print("✅ captcha 模块可以导入")

    # 3. 检查 captcha.urls
    from captcha import urls as captcha_urls

    print("✅ captcha.urls 可以导入")

    # 4. 列出 captcha 的 URL 模式
    from django.urls import get_resolver

    resolver = get_resolver()

    captcha_found = False
    for url_pattern in resolver.url_patterns:
        pattern_str = str(url_pattern.pattern)
        if 'captcha' in pattern_str:
            captcha_found = True
            print(f"✅ 找到 captcha URL 模式: {pattern_str}")
            # 尝试查看包含的模块
            if hasattr(url_pattern, 'urlconf_name'):
                print(f"   包含的模块: {url_pattern.urlconf_name}")

    if not captcha_found:
        print("❌ 在 URL 配置中找不到 captcha 模式")
        print("当前顶级 URL 模式:")
        for url_pattern in resolver.url_patterns:
            pattern_str = str(url_pattern.pattern)
            callback_info = url_pattern.callback if hasattr(url_pattern, 'callback') else 'N/A'
            print(f"  {pattern_str} -> {callback_info}")

except ImportError as e:
    print(f"❌ 导入失败: {e}")
    sys.exit(1)

# 5. 测试生成验证码
try:
    from captcha.models import CaptchaStore
    from captcha.helpers import captcha_image_url

    captcha_obj = CaptchaStore.objects.create()
    print("✅ 可以创建 CaptchaStore 对象")
    print(f"   挑战: {captcha_obj.challenge}")
    print(f"   响应: {captcha_obj.response}")
    print(f"   哈希键: {captcha_obj.hashkey}")
    print(f"   图片URL: {captcha_image_url(captcha_obj.hashkey)}")

except Exception as e:
    print(f"❌ 创建验证码失败: {e}")
    import traceback

    traceback.print_exc()

print("=" * 60)