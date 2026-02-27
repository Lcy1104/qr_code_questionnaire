from django.utils import timezone
from .models import Notification, NotificationSettings, Questionnaire, User, Response
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.conf import settings


class NotificationManager:
    """通知管理器，负责所有通知的创建和发送"""

    @staticmethod
    def create_notification(
            user,
            title,
            message,
            notification_type='system',
            related_questionnaire=None,
            priority='normal'
    ):
        """创建通知（存储到数据库）"""
        # 检查用户是否存在
        if not user or not user.is_active:
            return None

        try:
            # 检查用户是否接收此类通知
            settings_obj, created = NotificationSettings.objects.get_or_create(
                user=user,
                defaults={
                    'receive_questionnaire_updates': True,
                    'receive_system_notifications': True,
                    'receive_admin_notifications': True,
                    'receive_urgent_notifications': True,
                    'email_notifications': False,
                    'push_notifications': True,
                }
            )

            # 检查用户设置
            if not NotificationManager._check_notification_settings(settings_obj, notification_type, priority):
                return None

            # 创建通知记录
            notification = Notification.objects.create(
                user=user,
                title=title,
                message=message,
                notification_type=notification_type,
                related_questionnaire=related_questionnaire,
                priority=priority,
                delivery_status='pending'
            )

            # 立即尝试发送通知
            NotificationManager._send_notification_immediately(notification)

            # 发送WebSocket实时通知
            NotificationManager._send_websocket_notification(notification)

            return notification

        except Exception as e:
            print(f"创建通知失败: {e}")
            return None

    @staticmethod
    def _check_notification_settings(settings_obj, notification_type, priority):
        """检查用户通知设置"""
        # 紧急通知不受设置限制
        if priority == 'urgent':
            return True

        # 检查用户是否启用推送通知
        if not settings_obj.push_notifications:
            return False

        # 根据通知类型检查设置
        if notification_type == 'questionnaire_update':
            return settings_obj.receive_questionnaire_updates
        elif notification_type == 'admin':
            return settings_obj.receive_admin_notifications
        elif notification_type == 'system':
            return settings_obj.receive_system_notifications

        return True

    @staticmethod
    def _send_notification_immediately(notification):
        """立即发送通知（这里实现站内推送，邮件等可以异步）"""
        try:
            # 标记为已发送
            notification.mark_as_sent()

            return True

        except Exception as e:
            print(f"发送通知失败: {e}")
            notification.delivery_status = 'failed'
            notification.save()
            return False

    @staticmethod
    def _send_websocket_notification(notification):
        """通过WebSocket发送实时通知"""
        try:
            channel_layer = get_channel_layer()
            user_group_name = f"user_{notification.user.id}_notifications"

            # 构建通知数据
            notification_data = {
                'id': str(notification.id),
                'title': notification.title,
                'message': notification.message,
                'type': notification.notification_type,
                'priority': notification.priority,
                'created_at': notification.created_at.isoformat() if notification.created_at else None,
                'related_questionnaire': str(notification.related_questionnaire.id) if notification.related_questionnaire else None,
                'questionnaire_title': notification.related_questionnaire.title if notification.related_questionnaire else None
            }

            # 发送到用户的WebSocket组
            async_to_sync(channel_layer.group_send)(
                user_group_name,
                {
                    'type': 'send_notification',
                    'notification': notification_data
                }
            )

            print(f"WebSocket通知已发送给用户 {notification.user.username}")
            return True

        except Exception as e:
            print(f"发送WebSocket通知失败: {e}")
            # WebSocket发送失败不影响主流程，只记录日志
            return False

    @staticmethod
    def send_questionnaire_update_notification(questionnaire, updated_fields=None):
        """发送问卷更新通知给所有填写过的用户"""
        try:
            # 获取所有填写过该问卷的已登录用户
            responses = Response.objects.filter(
                questionnaire=questionnaire,
                user__isnull=False  # 只选择已登录用户
            ).select_related('user')

            users = set([response.user for response in responses])

            title = f"问卷更新通知：{questionnaire.title}"
            # 修改消息：去掉修改者信息，只描述更新事实
            message = f"您填写过的问卷《{questionnaire.title}》已更新"

            # 如果有更新字段详情，添加进去
            if updated_fields and len(updated_fields) > 0:
                # 优化字段显示名称
                field_display_map = {
                    'title': '标题',
                    'description': '描述',
                    'questions': '问题',
                    'options': '选项',
                    'settings': '设置'
                }
                display_fields = [field_display_map.get(field, field) for field in updated_fields]
                message += f"，更新了：{', '.join(display_fields)}"

            # 添加版本信息
            message += f"。当前版本：v{questionnaire.version}"

            notifications = []
            for user in users:
                # 确保用户是活跃用户
                if user and user.is_active:
                    notification = NotificationManager.create_notification(
                        user=user,
                        title=title,
                        message=message,
                        notification_type='questionnaire_update',
                        related_questionnaire=questionnaire,
                        priority='normal'
                    )
                    if notification:
                        notifications.append(notification)

            return notifications

        except Exception as e:
            print(f"发送问卷更新通知失败: {e}")
            return []

    @staticmethod
    def send_system_notification_to_all(title, message, priority='normal', exclude_users=None):
        """发送系统通知给所有活跃用户"""
        try:
            users = User.objects.filter(is_active=True)

            if exclude_users:
                users = users.exclude(id__in=[u.id for u in exclude_users])

            notifications = []
            for user in users:
                notification = NotificationManager.create_notification(
                    user=user,
                    title=title,
                    message=message,
                    notification_type='system',
                    priority=priority
                )
                if notification:
                    notifications.append(notification)

            return notifications

        except Exception as e:
            print(f"发送系统通知失败: {e}")
            return []

    @staticmethod
    def send_admin_notification(users, title, message, priority='normal'):
        """发送管理员通知给指定用户"""
        notifications = []
        for user in users:
            if user and user.is_active:
                notification = NotificationManager.create_notification(
                    user=user,
                    title=title,
                    message=message,
                    notification_type='admin',
                    priority=priority
                )
                if notification:
                    notifications.append(notification)

        return notifications

    @staticmethod
    def send_urgent_notification(users, title, message):
        """发送紧急通知（不受设置限制）"""
        notifications = []
        for user in users:
            if user and user.is_active:
                notification = NotificationManager.create_notification(
                    user=user,
                    title=title,
                    message=message,
                    notification_type='system',
                    priority='urgent'
                )
                if notification:
                    notifications.append(notification)

        return notifications

    @staticmethod
    def get_user_unread_count(user):
        """获取用户未读通知数量"""
        if not user or not user.is_authenticated:
            return 0

        return Notification.objects.filter(
            user=user,
            is_read=False,
            delivery_status='sent'
        ).count()

    @staticmethod
    def get_user_notifications(user, limit=None, unread_only=False):
        """获取用户通知"""
        if not user or not user.is_authenticated:
            return []

        queryset = Notification.objects.filter(
            user=user,
            delivery_status='sent'
        ).order_by('-created_at')

        if unread_only:
            queryset = queryset.filter(is_read=False)

        if limit:
            queryset = queryset[:limit]

        return queryset

    @staticmethod
    def cleanup_old_notifications(days=30):
        """清理旧通知"""
        from datetime import timedelta
        cutoff_date = timezone.now() - timedelta(days=days)

        # 删除30天前的已读通知
        deleted_count, _ = Notification.objects.filter(
            created_at__lt=cutoff_date,
            is_read=True
        ).delete()

        return deleted_count

    @staticmethod
    def mark_all_as_read_for_user(user):
        """标记用户所有通知为已读"""
        try:
            notifications = Notification.objects.filter(
                user=user,
                is_read=False,
                delivery_status='sent'
            )
            count = notifications.count()

            for notification in notifications:
                notification.mark_as_read()

            # 发送WebSocket更新
            try:
                channel_layer = get_channel_layer()
                user_group_name = f"user_{user.id}_notifications"

                async_to_sync(channel_layer.group_send)(
                    user_group_name,
                    {
                        'type': 'send_notification',
                        'notification': {
                            'type': 'marked_all_read',
                            'count': count
                        }
                    }
                )
            except Exception as e:
                print(f"发送WebSocket更新失败: {e}")

            return count
        except Exception as e:
            print(f"标记所有通知为已读失败: {e}")
            return 0