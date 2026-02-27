# questionnaire/scripts/init_db.py
import os
import sys
from pathlib import Path

# ==============================
# 关键：正确设置项目路径
# ==============================

# 方法1：自动计算项目根目录（推荐）
# 获取当前脚本的目录（questionnaire/scripts/）
current_script_dir = Path(__file__).resolve().parent.parent.parent  # 三次 parent 回到项目根目录

# 方法2：手动指定项目根目录（如果自动计算不行）
# current_script_dir = Path(r"E:\qr_code\qr_code_questionnaire")

# 将项目根目录添加到 Python 路径
sys.path.insert(0, str(current_script_dir))

# 设置 Django 设置模块
# 注意：你的实际项目文件夹名称是 qr_code_questionaire（少一个 n）
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qr_code_questionaire.settings')

import django

django.setup()

from django.core.management import execute_from_command_line
from questionnaire.models import User  # 注意：应用名是 questionnaire
from django.conf import settings


def create_database():
    """创建数据库"""
    db_settings = settings.DATABASES['default']

    try:
        import mysql.connector

        conn = mysql.connector.connect(
            host=db_settings.get('HOST', 'localhost'),
            port=db_settings.get('PORT', '3306'),
            user=db_settings.get('USER', 'root'),
            password=db_settings.get('PASSWORD', ''),
            charset='utf8mb4'
        )

        cursor = conn.cursor()
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{db_settings['NAME']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        print(f"✓ 数据库 {db_settings['NAME']} 创建成功")

        cursor.close()
        conn.close()
        return True

    except Exception as e:
        print(f"✗ 创建数据库失败: {e}")
        print(f"  请手动创建数据库: {db_settings['NAME']}")
        return True  # 继续执行，可能数据库已存在


def main():
    print("开始初始化数据库...")

    # 检查 SECRET_KEY 是否设置
    if not settings.SECRET_KEY or settings.SECRET_KEY.startswith('your-secret-key'):
        print("✗ 错误: SECRET_KEY 未设置或使用默认值")
        print("  请在 .env 文件中设置 SECRET_KEY")
        print("  生成命令: python -c \"import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(50))\"")
        return

    # 创建数据库
    if not create_database():
        return

    # 运行迁移
    print("运行数据库迁移...")
    try:
        execute_from_command_line(['manage.py', 'makemigrations'])
        execute_from_command_line(['manage.py', 'migrate'])
    except Exception as e:
        print(f"✗ 迁移失败: {e}")
        return

    # 创建超级用户
    print("创建超级用户...")
    from django.contrib.auth import get_user_model
    User = get_user_model()

    admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_email = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
    admin_password = os.environ.get('ADMIN_PASSWORD', 'Admin@123456')

    if not User.objects.filter(username=admin_username).exists():
        User.objects.create_superuser(
            username=admin_username,
            email=admin_email,
            password=admin_password
        )
        print(f"✓ 超级用户 {admin_username} 创建成功")
        print(f"  用户名: {admin_username}")
        print(f"  密码: {admin_password}")
    else:
        print(f"✓ 超级用户 {admin_username} 已存在")

    print("\n数据库初始化完成！")
    print("\n访问信息:")
    print(f"  管理后台: http://127.0.0.1:8000/admin")


if __name__ == '__main__':
    main()