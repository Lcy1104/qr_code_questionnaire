# questionnaire/decorators.py
from django.shortcuts import redirect
from django.contrib import messages


def original_admin_required(view_func):
    """装饰器：只有原始管理员可以访问"""

    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, '请先登录')
            return redirect('login')

        if not request.user.is_original_admin:
            messages.error(request, '只有原始管理员可以执行此操作')
            return redirect('manage_users')

        return view_func(request, *args, **kwargs)

    return wrapper