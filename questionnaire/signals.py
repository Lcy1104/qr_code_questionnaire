from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.db import transaction
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


@receiver(post_save, sender=User)
def handle_original_admin(sender, instance, created, **kwargs):
    """
    处理原始管理员逻辑：
    1. 新创建超级用户时，如果没有原始管理员，自动设为原始管理员
    2. 确保只有一个原始管理员
    3. 防止将非超级用户设为原始管理员
    """
    with transaction.atomic():
        # 获取更新后的用户实例（防止旧数据）
        try:
            user = User.objects.get(id=instance.id)
        except User.DoesNotExist:
            return

        # 情况1: 如果是原始管理员但不是超级用户，则移除原始管理员标记
        if user.is_original_admin and not user.is_superuser:
            User.objects.filter(id=user.id).update(is_original_admin=False)
            logger.info(f"用户 {user.username} 不是超级用户，已移除原始管理员标记")
            return

        # 情况2: 如果是新建的超级用户，检查是否需要设为原始管理员
        if created and user.is_superuser:
            # 检查是否已有原始管理员
            if not User.objects.filter(is_original_admin=True).exists():
                User.objects.filter(id=user.id).update(is_original_admin=True)
                logger.info(f"已将新创建的超级用户 {user.username} 设为原始管理员")

        # 情况3: 确保只有一个原始管理员
        original_admins = User.objects.filter(is_original_admin=True)
        count = original_admins.count()

        if count == 0:
            # 没有原始管理员，将第一个超级用户设为原始管理员
            first_superuser = User.objects.filter(is_superuser=True).order_by('date_joined').first()
            if first_superuser:
                User.objects.filter(id=first_superuser.id).update(is_original_admin=True)
                logger.info(f"将第一个超级用户 {first_superuser.username} 设为原始管理员")

        elif count > 1:
            # 有多个原始管理员，只保留第一个
            first_original = original_admins.order_by('date_joined').first()

            # 将其他用户设为非原始管理员
            for admin_user in original_admins:
                if admin_user.id != first_original.id:
                    User.objects.filter(id=admin_user.id).update(is_original_admin=False)
                    logger.info(f"已移除用户 {admin_user.username} 的原始管理员标记")