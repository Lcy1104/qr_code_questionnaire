from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.http import JsonResponse
from .models import Questionnaire
from django.urls import reverse

def verify_invite_only(request, questionnaire_id):
    """仅验证邀请码（无需登录）- 方案B"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 检查问卷状态
    if questionnaire.status != 'published':
        messages.error(request, '问卷未发布或已关闭')
        return render(request, 'questionnaire/verify_invite_simple.html', {'questionnaire': questionnaire})

    # 检查访问权限类型
    if questionnaire.access_type != 'invite':
        messages.error(request, '此问卷无需邀请码')
        return redirect('survey_access', questionnaire_id=questionnaire.id)

    if request.method == 'POST':
        # 验证邀请码
        invite_code = request.POST.get('invite_code', '').strip().upper()

        if invite_code == questionnaire.invite_code:
            # 验证成功，设置session
            request.session['valid_invite_code'] = questionnaire.invite_code
            request.session['verified_questionnaire'] = str(questionnaire.id)
            request.session['verified_time'] = timezone.now().isoformat()

            # 设置验证有效期（24小时）
            request.session.set_expiry(86400)

            messages.success(request, '邀请码验证成功！')

            return redirect('survey_landing', survey_uuid=questionnaire.id)
        else:
            # 验证失败
            messages.error(request, '邀请码错误，请重新输入')
            return render(request, 'questionnaire/verify_invite_code.html', {
                'questionnaire': questionnaire,
                'invite_code': invite_code,
            })

    # GET请求重定向到主访问页面
    return redirect('survey_access', questionnaire_id=questionnaire.id)


def api_verify_invite(request, questionnaire_id):
    """API接口：验证邀请码（用于AJAX验证）"""
    if request.method == 'POST':
        questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)
        invite_code = request.POST.get('invite_code', '').strip().upper()

        if invite_code == questionnaire.invite_code:
            # 验证成功，设置session
            request.session['valid_invite_code'] = questionnaire.invite_code
            request.session['verified_questionnaire'] = str(questionnaire.id)
            request.session['verified_time'] = timezone.now().isoformat()

            return JsonResponse({
                'success': True,
                'message': '邀请码验证成功',
                'redirect_url': reverse('survey_landing', args=[questionnaire.id])
            })
        else:
            return JsonResponse({
                'success': False,
                'message': '邀请码错误'
            })

    return JsonResponse({'success': False, 'message': '无效请求'})


def check_invite_session(request, questionnaire_id):
    """检查邀请码验证session是否有效"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 检查session
    if ('valid_invite_code' in request.session and
            request.session['valid_invite_code'] == questionnaire.invite_code):
        return True, None
    else:
        return False, "邀请码验证已过期或无效"