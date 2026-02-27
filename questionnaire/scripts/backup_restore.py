# questionnaire/scripts/backup_restore.py
import json
import os
from django.core.management.base import BaseCommand
from questionnaire.models import User, Questionnaire, Response
from questionnaire.crypto_utils import SM4Field
from questionnaire.cache_manager import RedisCacheManager


class Command(BaseCommand):
    help = '备份和恢复加密数据'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['backup', 'restore'])
        parser.add_argument('--file', default='data_backup.json')

    def handle(self, *args, **options):
        action = options['action']
        filename = options['file']

        if action == 'backup':
            self.backup_data(filename)
        elif action == 'restore':
            self.restore_data(filename)

    def backup_data(self, filename):
        """备份数据（解密后存储）"""
        data = {
            'users': [],
            'questionnaires': [],
            'responses': []
        }

        # 备份用户数据
        for user in User.objects.all():
            user_data = RedisCacheManager.model_to_dict(user)
            data['users'].append(user_data)

        # 备份问卷数据
        for q in Questionnaire.objects.all():
            q_data = RedisCacheManager.model_to_dict(q)
            data['questionnaires'].append(q_data)

        # 保存到文件
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.stdout.write(self.style.SUCCESS(f'数据已备份到 {filename}'))

    def restore_data(self, filename):
        """恢复数据"""
        if not os.path.exists(filename):
            self.stdout.write(self.style.ERROR(f'文件 {filename} 不存在'))
            return

        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 恢复用户数据
        for user_data in data.get('users', []):
            # 跳过已存在的用户
            if not User.objects.filter(username=user_data['username']).exists():
                user = User(**user_data)
                user.save()

        self.stdout.write(self.style.SUCCESS(f'数据已从 {filename} 恢复'))