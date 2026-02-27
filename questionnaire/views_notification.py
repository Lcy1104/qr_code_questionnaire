from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from .models import Notification, NotificationSettings
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from .models import Questionnaire, Response, Notification
from .notification_manager import NotificationManager
from django.contrib import messages

@login_required
def notification_list(request):
    # 清除 Django 消息框架中的所有消息
    # 通知列表页面不应该显示系统消息，只应该显示通知本身
    storage = messages.get_messages(request)
    storage.used = True  # 将消息标记为已使用，清除它们
    """显示用户的所有通知"""
    # 获取过滤参数
    notification_type = request.GET.get('type', '')
    read_status = request.GET.get('read', '')
    priority = request.GET.get('priority', '')

    # 获取通知
    notifications = NotificationManager.get_user_notifications(request.user)

    # 应用过滤器
    if notification_type:
        notifications = notifications.filter(notification_type=notification_type)
    if read_status == 'unread':
        notifications = notifications.filter(is_read=False)
    elif read_status == 'read':
        notifications = notifications.filter(is_read=True)
    if priority:
        notifications = notifications.filter(priority=priority)

    # 分页
    paginator = Paginator(notifications, 20)  # 每页20条
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # 统计
    unread_count = NotificationManager.get_user_unread_count(request.user)
    total_count = notifications.count()
    read_count = notifications.filter(is_read=True).count()

    context = {
        'notifications': page_obj,
        'page_obj': page_obj,
        'unread_count': unread_count,
        'total_count': total_count,
        'read_count': read_count,
        'notification_types': Notification.NOTIFICATION_TYPES,
        'priority_choices': Notification.PRIORITY_CHOICES,
        'current_type': notification_type,
        'current_read': read_status,
        'current_priority': priority,
    }
    return render(request, 'notification/list.html', context)


@login_required
def notification_detail(request, notification_id):
    """查看通知详情"""
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        user=request.user
    )

    # 标记为已读
    notification.mark_as_read()

    context = {
        'notification': notification,
    }
    return render(request, 'notification/detail.html', context)


@login_required
def mark_all_as_read(request):
    """标记所有通知为已读"""
    if request.method == 'POST':
        notifications = Notification.objects.filter(
            user=request.user,
            is_read=False,
            delivery_status='sent'
        )

        updated_count = 0
        for notification in notifications:
            notification.mark_as_read()
            updated_count += 1

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f'已标记 {updated_count} 条通知为已读'
            })

        return redirect('notification_list')

    return redirect('notification_list')


@login_required
def delete_notification(request, notification_id):
    """删除通知"""
    if request.method == 'POST':
        notification = get_object_or_404(
            Notification,
            id=notification_id,
            user=request.user
        )
        notification.delete()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': '通知已删除'})

        return redirect('notification_list')

    return redirect('notification_list')


@login_required
def delete_all_read(request):
    """删除所有已读通知"""
    if request.method == 'POST':
        notifications = Notification.objects.filter(
            user=request.user,
            is_read=True,
            delivery_status='sent'
        )

        deleted_count = notifications.count()
        notifications.delete()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f'已删除 {deleted_count} 条已读通知'
            })

        return redirect('notification_list')

    return redirect('notification_list')


@login_required
def notification_settings(request):
    """通知设置"""
    settings_obj, created = NotificationSettings.objects.get_or_create(
        user=request.user,
        defaults={
            'receive_questionnaire_updates': True,
            'receive_system_notifications': True,
            'receive_admin_notifications': True,
            'receive_urgent_notifications': True,
            'email_notifications': False,
            'push_notifications': True,
        }
    )

    if request.method == 'POST':
        settings_obj.receive_questionnaire_updates = request.POST.get(
            'receive_questionnaire_updates') == 'on'
        settings_obj.receive_system_notifications = request.POST.get(
            'receive_system_notifications') == 'on'
        settings_obj.receive_admin_notifications = request.POST.get(
            'receive_admin_notifications') == 'on'
        settings_obj.receive_urgent_notifications = request.POST.get(
            'receive_urgent_notifications') == 'on'
        settings_obj.email_notifications = request.POST.get(
            'email_notifications') == 'on'
        settings_obj.push_notifications = request.POST.get(
            'push_notifications') == 'on'
        settings_obj.save()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': '设置已保存'})

        return redirect('notification_settings')

    context = {
        'settings': settings_obj,
    }
    return render(request, 'notification/settings.html', context)


@login_required
def get_unread_count(request):
    """获取未读通知数量（用于AJAX轮询）"""
    unread_count = NotificationManager.get_user_unread_count(request.user)
    return JsonResponse({'unread_count': unread_count})

@login_required
def check_questionnaire_update(request, questionnaire_id):
    """
    检查问卷是否有更新
    用于AJAX轮询，检查用户填写的问卷是否有更新
    """
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': '非法请求'}, status=400)

    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 检查用户是否有权限访问这个问卷
    if not request.user.is_authenticated:
        return JsonResponse({'has_update': False, 'error': '请先登录'})

    # 获取用户对这个问卷的最新回答
    latest_response = Response.objects.filter(
        questionnaire=questionnaire,
        user=request.user,
        is_submitted=True
    ).order_by('-submitted_at').first()

    # 检查问卷是否有更新
    has_update = False
    update_info = {}

    if latest_response:
        # 如果问卷版本比用户回答的版本新，说明有更新
        if questionnaire.version > latest_response.questionnaire_version:
            has_update = True
            update_info = {
                'current_version': questionnaire.version,
                'user_version': latest_response.questionnaire_version,
                'questionnaire_id': str(questionnaire.id),
                'questionnaire_title': questionnaire.title,
                'update_message': f"问卷已更新到版本 {questionnaire.version}",
                'update_time': questionnaire.updated_at.isoformat() if questionnaire.updated_at else None
            }

    # 同时检查是否有关于这个问卷的未读通知
    questionnaire_notifications = Notification.objects.filter(
        user=request.user,
        related_questionnaire=questionnaire,
        is_read=False,
        notification_type='questionnaire_update'
    ).exists()

    # 如果有未读通知，也视为有更新
    if questionnaire_notifications:
        has_update = True
        if not update_info:
            update_info = {
                'questionnaire_id': str(questionnaire.id),
                'questionnaire_title': questionnaire.title,
                'update_message': "有新的问卷更新通知",
                'update_source': 'notification'
            }

    response_data = {
        'has_update': has_update,
        'questionnaire_id': str(questionnaire.id),
        'questionnaire_title': questionnaire.title,
        'current_version': questionnaire.version,
        'update_info': update_info if has_update else None
    }

    return JsonResponse(response_data)


@login_required
def acknowledge_update(request, questionnaire_id):
    """
    确认问卷更新
    用户确认已经查看过问卷更新
    """
    if request.method != 'POST':
        return JsonResponse({'error': '只支持POST请求'}, status=400)

    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 获取用户对这个问卷的最新回答
    latest_response = Response.objects.filter(
        questionnaire=questionnaire,
        user=request.user,
        is_submitted=True
    ).order_by('-submitted_at').first()

    if latest_response:
        # 更新用户的回答版本号（模拟用户已经看到最新版本）
        # 注意：这里不修改数据库中的实际版本，只是记录用户已确认
        latest_response.questionnaire_version = questionnaire.version
        latest_response.save()

    # 将关于这个问卷的所有未读通知标记为已读
    notifications = Notification.objects.filter(
        user=request.user,
        related_questionnaire=questionnaire,
        is_read=False,
        notification_type='questionnaire_update'
    )

    read_count = 0
    for notification in notifications:
        notification.mark_as_read()
        read_count += 1

    # 返回成功响应
    response_data = {
        'success': True,
        'message': f'已确认问卷更新，标记了 {read_count} 条通知为已读',
        'questionnaire_id': str(questionnaire.id),
        'questionnaire_title': questionnaire.title,
        'current_version': questionnaire.version
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse(response_data)

    # 如果不是AJAX请求，重定向到问卷详情页
    return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)


@login_required
def get_notification_updates(request):
    """
    获取用户的未读通知更新（用于实时通知）
    """
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': '非法请求'}, status=400)

    # 获取未读通知数量
    unread_count = NotificationManager.get_user_unread_count(request.user)

    # 获取最新的未读通知
    recent_notifications = NotificationManager.get_user_notifications(
        request.user,
        limit=5,
        unread_only=True
    )

    # 获取紧急通知
    urgent_notifications = Notification.objects.filter(
        user=request.user,
        priority='urgent',
        is_read=False
    ).order_by('-created_at')[:3]

    # 格式化通知数据
    notifications_data = []
    for notification in recent_notifications:
        notifications_data.append({
            'id': str(notification.id),
            'title': notification.title,
            'message': notification.message[:100] + ('...' if len(notification.message) > 100 else ''),
            'type': notification.notification_type,
            'priority': notification.priority,
            'time_since': notification.time_since,
            'created_at': notification.created_at.isoformat() if notification.created_at else None,
            'related_questionnaire': str(
                notification.related_questionnaire.id) if notification.related_questionnaire else None,
            'questionnaire_title': notification.related_questionnaire.title if notification.related_questionnaire else None
        })

    # 格式化紧急通知数据
    urgent_data = []
    for notification in urgent_notifications:
        urgent_data.append({
            'id': str(notification.id),
            'title': notification.title,
            'message': notification.message[:150] + ('...' if len(notification.message) > 150 else ''),
            'created_at': notification.created_at.isoformat() if notification.created_at else None
        })

    response_data = {
        'unread_count': unread_count,
        'notifications': notifications_data,
        'urgent_notifications': urgent_data,
        'timestamp': timezone.now().isoformat()
    }

    return JsonResponse(response_data)