from django.utils import timezone
from datetime import datetime, timedelta
from django.urls import reverse
from django.http import HttpResponseForbidden
from django.contrib import messages

class InviteSessionCleanupMiddleware:
    """清理过期的邀请码验证session"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 处理请求前检查session
        if 'verified_time' in request.session:
            try:
                verified_time = datetime.fromisoformat(request.session['verified_time'])
                # 如果超过24小时，清理session
                if timezone.now() - verified_time > timedelta(hours=24):
                    if 'valid_invite_code' in request.session:
                        del request.session['valid_invite_code']
                    if 'verified_questionnaire' in request.session:
                        del request.session['verified_questionnaire']
                    if 'verified_time' in request.session:
                        del request.session['verified_time']
                    # 设置标志表示session已过期
                    request.session['invite_session_expired'] = True
            except (ValueError, TypeError):
                # 时间格式错误，清理session
                if 'valid_invite_code' in request.session:
                    del request.session['valid_invite_code']
                if 'verified_questionnaire' in request.session:
                    del request.session['verified_questionnaire']
                if 'verified_time' in request.session:
                    del request.session['verified_time']

        response = self.get_response(request)
        return response


class AdminPermissionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 检查是否尝试访问管理员功能
        admin_paths = ['/system/users/', '/admin/']

        if any(request.path.startswith(path) for path in admin_paths):
            if not request.user.is_authenticated:
                # 重定向到登录页面
                from django.shortcuts import redirect
                return redirect(f'{reverse("login")}?next={request.path}')

            if not request.user.is_admin:
                from django.contrib import messages
                from django.shortcuts import redirect
                messages.error(request, '您没有权限访问管理员功能')
                return redirect('dashboard')

        response = self.get_response(request)
        return response


class NotificationPageMessagesMiddleware:
    """清除通知页面的系统消息，避免显示不相关的消息"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 检查是否是通知相关页面
        if request.path.startswith('/notifications/'):
            # 处理请求前清除消息
            storage = messages.get_messages(request)
            storage.used = True  # 将消息标记为已使用，从而清除它们

            # 如果需要，也可以记录日志
            # print(f"已清除通知页面的消息: {request.path}")

        response = self.get_response(request)
        return response