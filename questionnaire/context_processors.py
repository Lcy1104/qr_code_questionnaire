# questionnaire/context_processors.py
from django.db.models import Q
from .notification_manager import NotificationManager

def notifications_processor(request):
    """为所有模板提供通知相关的上下文变量"""
    context = {}

    if request.user.is_authenticated:
        try:
            # 使用相对导入避免循环引用
            from .models import Notification

            # 获取用户的最近5条通知
            recent_notifications = Notification.objects.filter(
                user=request.user,
                delivery_status='sent'
            ).order_by('-created_at')[:5]

            # 获取用户未读通知数量
            notification_unread_count = Notification.objects.filter(
                user=request.user,
                is_read=False,
                delivery_status='sent'
            ).count()

            context.update({
                'recent_notifications': recent_notifications,
                'notification_unread_count': notification_unread_count,
            })

        except Exception as e:
            # 如果出错，返回空值
            print(f"通知上下文处理器错误: {e}")
            context.update({
                'recent_notifications': [],
                'notification_unread_count': 0,
            })
    else:
        # 未登录用户
        context.update({
            'recent_notifications': [],
            'notification_unread_count': 0,
        })

    return context