from django.utils import timezone
from django.db.models import Q
from .models import Notification, NotificationSettings, Questionnaire, User, Response


def create_notification(
        user,
        title,
        message,
        notification_type='system',
        related_questionnaire=None
):
    """创建通知"""
    # 检查用户是否存在且是活跃用户
    if not user or not user.is_authenticated:
        return None

    # 检查用户是否接收此类通知
    try:
        settings, created = NotificationSettings.objects.get_or_create(
            user=user,
            defaults={
                'receive_questionnaire_updates': True,
                'receive_system_notifications': True,
                'receive_admin_notifications': True,
                'email_notifications': False,
            }
        )

        if notification_type == 'questionnaire_update' and not settings.receive_questionnaire_updates:
            return None
        elif notification_type == 'admin' and not settings.receive_admin_notifications:
            return None
        elif notification_type == 'system' and not settings.receive_system_notifications:
            return None
    except Exception as e:
        print(f"获取用户通知设置失败: {e}")
        # 如果获取设置失败，仍然创建通知
        pass

    try:
        # 创建通知
        notification = Notification.objects.create(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
            related_questionnaire=related_questionnaire
        )
        return notification
    except Exception as e:
        print(f"创建通知失败: {e}")
        return None


def send_questionnaire_update_notification(questionnaire, updated_fields=None):
    """发送问卷更新通知给所有填写过且登录的用户"""
    try:
        # 获取所有填写过该问卷的已登录用户（排除匿名用户）
        # 使用Response模型，只选择user字段不为空的记录
        responses_with_users = Response.objects.filter(
            questionnaire=questionnaire,
            user__isnull=False
            # 只选择已登录用户
        ).select_related('user').distinct('user')

        users = [response.user for response in responses_with_users]

        title = f"问卷更新通知：{questionnaire.title}"
        message = f"您填写过的问卷《{questionnaire.title}》已经更新。"
        if updated_fields and len(updated_fields) > 0:
            message += f" 更新内容：{', '.join(updated_fields)}"

        notifications = []
        for user in users:
            # 确保用户是活跃用户
            if user and user.is_active:
                notification = create_notification(
                    user=user,
                    title=title,
                    message=message,
                    notification_type='questionnaire_update',
                    related_questionnaire=questionnaire
                )
                if notification:
                    notifications.append(notification)

        return notifications
    except Exception as e:
        print(f"发送问卷更新通知失败: {e}")
        return []


def send_system_notification(users, title, message):
    """发送系统通知给多个用户"""
    notifications = []
    for user in users:
        # 确保用户是活跃用户
        if user and user.is_active:
            notification = create_notification(
                user=user,
                title=title,
                message=message,
                notification_type='system'
            )
            if notification:
                notifications.append(notification)

    return notifications


def send_admin_notification(user, title, message):
    """发送管理员通知"""
    if user and user.is_active:
        return create_notification(
            user=user,
            title=title,
            message=message,
            notification_type='admin'
        )
    return None


def send_broadcast_notification(title, message, notification_type='system', user_filter=None):
    """广播通知给所有用户"""
    try:
        # 获取所有活跃用户
        users = User.objects.filter(is_active=True)

        # 应用额外的用户过滤器
        if user_filter:
            users = users.filter(user_filter)

        notifications = []
        for user in users:
            notification = create_notification(
                user=user,
                title=title,
                message=message,
                notification_type=notification_type
            )
            if notification:
                notifications.append(notification)

        return notifications
    except Exception as e:
        print(f"广播通知失败: {e}")
        return []