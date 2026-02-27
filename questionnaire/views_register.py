# questionnaire/views_register.py
from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages


def register_view(request):
    """用户注册页面"""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()

            # 自动登录
            login(request, user)

            # 欢迎消息
            messages.success(request, f'注册成功！欢迎 {user.username}')

            next_url = request.GET.get('next', 'dashboard')
            return redirect(next_url)
    else:
        form = UserCreationForm()

    return render(request, 'registration/register.html', {'form': form})