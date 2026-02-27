from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from .models import Questionnaire


@login_required
def verify_invite_code(request, questionnaire_id):
    """验证邀请码页面"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 检查问卷状态
    if questionnaire.status != 'published':
        messages.error(request, '问卷未发布或已关闭')
        return redirect('questionnaire_list')

    # 检查是否已有有效的邀请码
    if 'valid_invite_code' in request.session and request.session['valid_invite_code'] == questionnaire.invite_code:
        return redirect('survey_form', questionnaire_id=questionnaire.id)

    # 如果是GET请求，显示验证页面
    if request.method == 'GET':
        return render(request, 'questionnaire/verify_invite_code.html', {
            'questionnaire': questionnaire,
        })

    # POST请求：验证邀请码
    elif request.method == 'POST':
        invite_code = request.POST.get('invite_code', '').strip().upper()

        if invite_code == questionnaire.invite_code:
            # 验证成功，设置会话
            request.session['valid_invite_code'] = questionnaire.invite_code
            request.session['verified_questionnaire'] = str(questionnaire.id)

            # 设置邀请码有效期（例如24小时）
            request.session.set_expiry(86400)  # 24小时

            messages.success(request, '邀请码验证成功！')
            return redirect('survey_form', questionnaire_id=questionnaire.id)
        else:
            messages.error(request, '邀请码错误，请重新输入')
            return render(request, 'questionnaire/verify_invite_code.html', {
                'questionnaire': questionnaire,
                'invite_code': invite_code,
            })


@login_required
def clear_invite_session(request, questionnaire_id):
    """清除邀请码会话（用于重新验证）"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 清除相关会话
    if 'valid_invite_code' in request.session:
        del request.session['valid_invite_code']
    if 'verified_questionnaire' in request.session:
        del request.session['verified_questionnaire']

    messages.info(request, '请重新验证邀请码')
    return redirect('verify_invite_code', questionnaire_id=questionnaire.id)