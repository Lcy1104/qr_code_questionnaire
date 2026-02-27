from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q
from .models import User, Notification, Questionnaire
from .notification_manager import NotificationManager


@login_required
def admin_send_notification(request):
    """管理员发送通知界面"""
    if not request.user.is_admin:
        return redirect('dashboard')

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        message = request.POST.get('message', '').strip()
        notification_type = request.POST.get('notification_type', 'system')
        target_type = request.POST.get('target_type', 'all')
        priority = request.POST.get('priority', 'normal')
        target_users = request.POST.getlist('target_users', [])
        questionnaire_id = request.POST.get('questionnaire_id', '')

        if not title or not message:
            return JsonResponse({'success': False, 'message': '标题和内容不能为空'})

        try:
            notifications = []
            related_questionnaire = None

            if questionnaire_id:
                related_questionnaire = Questionnaire.objects.get(id=questionnaire_id)

            if target_type == 'all':
                # 发送给所有用户
                notifications = NotificationManager.send_system_notification_to_all(
                    title=title,
                    message=message,
                    priority=priority
                )
                message_text = f"已向所有用户发送通知，成功发送 {len(notifications)} 条"

            elif target_type == 'selected':
                # 发送给选中的用户
                users = User.objects.filter(id__in=target_users, is_active=True)
                notifications = NotificationManager.send_admin_notification(
                    users=users,
                    title=title,
                    message=message,
                    priority=priority
                )
                message_text = f"已向 {len(notifications)} 个用户发送通知"

            elif target_type == 'admins':
                # 发送给所有管理员
                users = User.objects.filter(Q(is_superuser=True) | Q(user_type='admin'), is_active=True)
                notifications = NotificationManager.send_admin_notification(
                    users=users,
                    title=title,
                    message=message,
                    priority=priority
                )
                message_text = f"已向 {len(notifications)} 个管理员发送通知"

            elif target_type == 'questionnaire_users':
                # 发送给填写过特定问卷的用户
                if not related_questionnaire:
                    return JsonResponse({'success': False, 'message': '请选择问卷'})

                notifications = NotificationManager.send_questionnaire_update_notification(
                    questionnaire=related_questionnaire,
                    updated_fields=["管理员通知"]
                )
                message_text = f"已向 {len(notifications)} 个问卷填写用户发送通知"

            return JsonResponse({
                'success': True,
                'message': message_text,
                'sent_count': len(notifications)
            })

        except Exception as e:
            return JsonResponse({'success': False, 'message': f'发送失败: {str(e)}'})

    # GET请求，显示发送界面
    users = User.objects.filter(is_active=True).order_by('username')
    questionnaires = Questionnaire.objects.filter(status='published').order_by('-created_at')

    context = {
        'users': users,
        'questionnaires': questionnaires,
        'notification_types': Notification.NOTIFICATION_TYPES,
        'priority_choices': Notification.PRIORITY_CHOICES,
        'target_types': [
            ('all', '所有用户'),
            ('admins', '所有管理员'),
            ('selected', '指定用户'),
            ('questionnaire_users', '问卷填写用户'),
        ]
    }

    return render(request, 'notification/admin_send.html', context)


@login_required
def admin_notification_log(request):
    """管理员查看通知发送日志"""
    if not request.user.is_admin:
        return redirect('dashboard')

    # 获取所有通知（可以按时间、类型、用户过滤）
    notifications = Notification.objects.all().order_by('-created_at')

    # 过滤
    notification_type = request.GET.get('type', '')
    user_id = request.GET.get('user_id', '')
    priority = request.GET.get('priority', '')
    delivery_status = request.GET.get('status', '')
    search = request.GET.get('search', '')

    if notification_type:
        notifications = notifications.filter(notification_type=notification_type)
    if user_id:
        notifications = notifications.filter(user_id=user_id)
    if priority:
        notifications = notifications.filter(priority=priority)
    if delivery_status:
        notifications = notifications.filter(delivery_status=delivery_status)
    if search:
        notifications = notifications.filter(
            Q(title__icontains=search) |
            Q(message__icontains=search) |
            Q(user__username__icontains=search)
        )

    # 分页
    paginator = Paginator(notifications, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # 统计
    total_count = notifications.count()
    sent_count = notifications.filter(delivery_status='sent').count()
    read_count = notifications.filter(is_read=True).count()
    failed_count = notifications.filter(delivery_status='failed').count()

    # 获取用户列表（用于过滤）
    users = User.objects.filter(is_active=True).order_by('username')

    context = {
        'notifications': page_obj,
        'page_obj': page_obj,
        'users': users,
        'total_count': total_count,
        'sent_count': sent_count,
        'read_count': read_count,
        'failed_count': failed_count,
        'notification_types': Notification.NOTIFICATION_TYPES,
        'priority_choices': Notification.PRIORITY_CHOICES,
        'delivery_statuses': Notification._meta.get_field('delivery_status').choices,
        'current_type': notification_type,
        'current_user_id': user_id,
        'current_priority': priority,
        'current_status': delivery_status,
        'search': search,
    }

    return render(request, 'notification/admin_log.html', context)