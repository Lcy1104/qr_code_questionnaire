# questionnaire/views_auth.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, get_user_model, logout
from django.contrib.auth.hashers import make_password
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .forms import RegForm, LoginForm, PwdResetForm
from .core_captcha import verify_captcha
from .models import Questionnaire

# Axes 相关导入
from django.http import JsonResponse, HttpResponse
from axes.helpers import get_lockout_message
from django.utils import timezone
from datetime import timedelta
from django.conf import settings  # 导入 Django settings

User = get_user_model()


# ============== Axes 锁定响应函数 ==============
def lockout_response(request, credentials):
    """
    Axes账户锁定响应函数 - 当用户多次登录失败时调用
    注意：credentials中的用户名是明文，不需要解密
    """
    try:
        # 获取Axes的锁定消息
        message = get_lockout_message()

        # 获取冷却时间 - 从 Django settings 直接获取
        # 使用 getattr 确保安全访问
        cooloff = getattr(settings, 'AXES_COOLOFF_TIME', 1)  # 默认1小时

        # 处理冷却时间
        if isinstance(cooloff, int):
            cooloff = timedelta(hours=cooloff)
        elif isinstance(cooloff, timedelta):
            pass
        else:
            # 如果配置有问题，使用默认1小时
            cooloff = timedelta(hours=1)

        # 计算解锁时间
        unlock_time = timezone.now() + cooloff
        cooloff_minutes = int(cooloff.total_seconds() // 60)

        # 获取用户名（如果有）- credentials中的用户名是明文
        username = credentials.get('username', '') if credentials else ''

        # 特别注意：这里使用的是明文用户名，因为登录表单提交的是明文
        # 不需要对用户名进行解密操作

        # 获取客户端IP
        ip_address = request.META.get('REMOTE_ADDR', '未知IP')

        # 记录锁定日志（用于调试）
        import logging
        logger = logging.getLogger('axes')
        logger.warning(
            f"账户锁定 - 用户名: {username}, IP: {ip_address}, "
            f"时间: {timezone.now()}, 锁定时长: {cooloff_minutes}分钟"
        )

        # 判断请求类型
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        is_api = 'api' in request.path or request.content_type == 'application/json'

        if is_ajax or is_api:
            # 返回JSON响应
            return JsonResponse({
                'status': 'error',
                'code': 'ACCOUNT_LOCKED',
                'message': '账户已被锁定，请稍后再试',
                'detail': str(message),
                'unlock_time': unlock_time.isoformat(),
                'cooloff_minutes': cooloff_minutes,
            }, status=403)

        # 常规HTTP请求 - 渲染锁定页面
        context = {
            'title': '账户暂时锁定',
            'message': message,
            'username': username if username else '您的账户',
            'ip_address': ip_address,
            'unlock_time': unlock_time,
            'cooloff_minutes': cooloff_minutes,
            'current_time': timezone.now(),
        }

        # 使用已有的 locked.html 模板
        return render(request, 'registration/locked.html', context, status=403)

    except Exception as e:
        # 如果出错，返回简单的锁定信息
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"锁定响应出错: {e}")

        return HttpResponse(f"""
        <!DOCTYPE html>
        <html>
        <head><title>账户锁定</title></head>
        <body style="text-align: center; padding: 50px;">
            <h2 style="color: #dc3545;">🔒 账户已被锁定</h2>
            <p>由于多次登录失败，您的账户已被暂时锁定。</p>
            <p>请1小时后再试。</p>
            <a href="/">返回首页</a>
        </body>
        </html>
        """, status=403)


# ============== 原有的登录功能 ==============
def user_login(request):
    """用户登录 - 支持方案B流程"""
    if request.method == 'POST':
        form = LoginForm(request.POST)

        if form.is_valid():
            # 验证逻辑...
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            captcha = form.cleaned_data['captcha']

            # 验证码验证...

            user = authenticate(request, username=username, password=password)

            if user is not None:
                login(request, user)

                # 方案B：检查是否有通过邀请码验证的问卷
                questionnaire_id = request.session.get('questionnaire_id')
                valid_invite_code = request.session.get('valid_invite_code')

                if questionnaire_id and valid_invite_code:
                    try:
                        questionnaire = Questionnaire.objects.get(id=questionnaire_id)
                        # 验证邀请码是否匹配
                        if questionnaire.invite_code == valid_invite_code:
                            # 检查问卷状态
                            if questionnaire.status == 'published':
                                # 直接跳转到问卷填写页面
                                next_url = f'/survey/{questionnaire_id}/form/'
                                messages.success(request, '登录成功，开始填写问卷')
                                return redirect(next_url)
                    except Questionnaire.DoesNotExist:
                        pass

                # 常规重定向逻辑
                next_url = request.POST.get('next', '')
                if next_url:
                    return redirect(next_url)
                else:
                    return redirect('dashboard')
            else:
                messages.error(request, '用户名或密码错误')
        else:
            messages.error(request, '表单验证失败')

    # GET请求
    else:
        form = LoginForm()

        # 方案B：如果有待填写的问卷，显示提示信息
        questionnaire_id = request.GET.get('questionnaire_id') or request.session.get('questionnaire_id')
        invite_code = request.session.get('valid_invite_code')

        if questionnaire_id and invite_code:
            try:
                questionnaire = Questionnaire.objects.get(id=questionnaire_id)
                if questionnaire.invite_code == invite_code:
                    messages.info(request, f'邀请码已验证，请登录以填写问卷："{questionnaire.title}"')
            except Questionnaire.DoesNotExist:
                pass

    return render(request, 'registration/login.html', {
        'form': form,
        'next': request.GET.get('next', ''),
    })


def login_view(request):
    """原有的登录视图 - 保持完整功能"""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        captcha = request.POST.get('captcha', '').strip()

        # 验证验证码
        is_valid, message = verify_captcha(request, captcha)
        if not is_valid:
            # 直接返回，不添加消息
            return render(request, 'registration/login.html', {'error': message})

        # 验证用户
        try:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                if user.is_active:
                    login(request, user)
                    next_url = request.POST.get('next') or request.GET.get('next')
                    if next_url and next_url.startswith('/'):  # 简单安全验证
                        return redirect(next_url)
                    return redirect('dashboard')
                else:
                    # 显示用户错误
                    return render(request, 'registration/login.html', {'error': '该账户已被禁用'})
            else:
                next_url = request.GET.get('next', '')
                # 显示用户错误
                return render(request, 'registration/login.html', {
                    'error': '用户名或密码错误',
                    'next': next_url
                })
        except Exception as e:
            # 系统错误：记录到日志，但显示通用错误
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"登录错误: {e}")
            # 显示用户友好的错误
            return render(request, 'registration/login.html', {'error': '登录时发生错误，请稍后重试'})

    # GET请求：不显示任何消息
    return render(request, 'registration/login.html')


# ============== 原有的注册功能 ==============
def register(request):
    """用户注册 - 支持方案B流程"""
    error = None
    info = None

    if request.method == 'POST':
        form = RegForm(request.POST)

        # 获取表单数据
        username = request.POST.get('username', '').strip()
        password1 = request.POST.get('password1', '').strip()
        password2 = request.POST.get('password2', '').strip()
        captcha = request.POST.get('captcha', '').strip()

        # 1. 验证验证码
        is_valid, captcha_message = verify_captcha(request, captcha)
        if not is_valid:
            error = captcha_message
            # 保留表单数据
            return render(request, 'registration/register.html', {
                'form': form,
                'error': error,
                'username': username
            })

        # 2. 基础验证
        if not username:
            error = '用户名不能为空'
        elif not password1:
            error = '密码不能为空'
        elif password1 != password2:
            error = '两次输入的密码不一致'
        elif len(password1) < 8:
            error = '密码至少需要8个字符'
        elif password1.isdigit():
            error = '密码不能全是数字'

        if error:
            return render(request, 'registration/register.html', {
                'form': form,
                'error': error,
                'username': username
            })

        # 3. 检查用户名是否已存在
        try:
            user = User.objects.get(username=username)
            error = '用户名已存在'
            return render(request, 'registration/register.html', {
                'form': form,
                'error': error,
                'username': username
            })
        except User.DoesNotExist:
            # 用户名不存在，可以继续注册
            pass

        # 4. 创建用户
        try:
            user = User.objects.create_user(
                username=username,
                password=password1,
                user_type='user'  # 默认用户类型
            )

            # 5. 方案B：如果注册前有通过邀请码验证的问卷，自动处理
            questionnaire_id = request.session.get('questionnaire_id')
            valid_invite_code = request.session.get('valid_invite_code')

            if questionnaire_id and valid_invite_code:
                try:
                    questionnaire = Questionnaire.objects.get(id=questionnaire_id)
                    # 验证邀请码是否匹配
                    if questionnaire.invite_code == valid_invite_code and questionnaire.status == 'published':
                        # 保持验证状态
                        request.session['valid_invite_code'] = valid_invite_code
                        request.session['verified_questionnaire'] = questionnaire_id

                        # 自动登录
                        login(request, user, backend='django.contrib.auth.backends.ModelBackend')

                        # 跳转到问卷填写页面
                        return redirect('survey_form', questionnaire_id=questionnaire_id)
                except Questionnaire.DoesNotExist:
                    pass

            # 6. 常规注册流程：自动登录并跳转到仪表盘
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('dashboard')

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"用户注册失败: {e}")
            error = '注册失败，请稍后重试'
            return render(request, 'registration/register.html', {
                'form': form,
                'error': error,
                'username': username
            })

    # GET请求
    else:
        form = RegForm()

        # 方案B：如果有待填写的问卷，在注册页显示提示
        questionnaire_id = request.session.get('questionnaire_id')
        invite_code = request.session.get('valid_invite_code')

        if questionnaire_id and invite_code:
            try:
                questionnaire = Questionnaire.objects.get(id=questionnaire_id)
                if questionnaire.invite_code == invite_code:
                    info = f'邀请码已验证，注册后即可填写问卷："{questionnaire.title}"'
            except Questionnaire.DoesNotExist:
                pass

    return render(request, 'registration/register.html', {
        'form': form,
        'info': info
    })


def password_reset_user(request):
    """密码重置第一步：输入用户名"""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        if not username:
            return render(request, 'registration/password_reset_user.html', {
                'error': '用户名不能为空',
                'username': username
            })
        try:
            user = User.objects.get(username=username)
            request.session['reset_username'] = username
            return redirect('password_reset_confirm')
        except User.DoesNotExist:
            messages.error(request, '用户不存在')
            return render(request, 'registration/password_reset_user.html', {
                'error': '用户不存在',
                'username': username
            })

    return render(request, 'registration/password_reset_user.html')


def password_reset_confirm(request):
    """密码重置第二步：设置新密码"""
    username = request.session.get('reset_username')
    if not username:
        return redirect('password_reset')

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        messages.error(request, '用户不存在')
        return redirect('password_reset')

    if request.method == 'POST':
        form = PwdResetForm(request.POST)
        if form.is_valid():
            # 验证验证码
            captcha = request.POST.get('captcha', '').strip()
            is_valid, message = verify_captcha(request, captcha)
            if not is_valid:
                messages.error(request, message)
                return render(request, 'registration/password_reset_confirm.html', {
                    'form': form,
                    'username': username
                })

            # 更新密码
            new_password = form.cleaned_data['new_password1']
            user.set_password(new_password)
            user.save()

            # 清除session
            if 'reset_username' in request.session:
                del request.session['reset_username']

            messages.success(request, '密码重置成功，请使用新密码登录')
            return redirect('login')
    else:
        form = PwdResetForm()

    return render(request, 'registration/password_reset_confirm.html', {
        'form': form,
        'username': username
    })


def logout_view(request):
    """退出登录"""
    username = request.user.username if request.user.is_authenticated else '用户'
    logout(request)
    # messages.success(request, f'{username} 已成功退出登录')
    return redirect('home')