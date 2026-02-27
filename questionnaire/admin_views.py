# questionnaire/admin_views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
import qrcode
import random
import string
from io import BytesIO
from django.core.files.base import ContentFile
from .models import User, Questionnaire, Question, Response
from .forms import QuestionnaireForm, QuestionFormSet
from .utils import generate_qr_code
from functools import wraps


def admin_required(view_func):
    """管理员权限装饰器"""
    @wraps(view_func)
    def check_admin(request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_admin:
            return view_func(request, *args, **kwargs)
        messages.error(request, '需要管理员权限')
        return redirect('dashboard')
    return check_admin


@login_required
def dashboard(request):
    """用户仪表盘"""
    user = request.user

    if user.is_admin:
        # 管理员仪表盘
        total_users = User.objects.count()
        total_questionnaires = Questionnaire.objects.count()
        total_responses = Response.objects.count()

        recent_questionnaires = Questionnaire.objects.all().order_by('-created_at')[:5]
        recent_users = User.objects.all().order_by('-date_joined')[:5]

        return render(request, 'admin/dashboard.html', {
            'total_users': total_users,
            'total_questionnaires': total_questionnaires,
            'total_responses': total_responses,
            'recent_questionnaires': recent_questionnaires,
            'recent_users': recent_users,
        })
    else:
        # 普通用户仪表盘
        my_questionnaires = Questionnaire.objects.filter(creator=user).order_by('-created_at')
        my_responses = Response.objects.filter(user=user).select_related('questionnaire').order_by('-submitted_at')

        return render(request, 'user/dashboard.html', {
            'my_questionnaires': my_questionnaires,
            'my_responses': my_responses,
        })


@login_required
@admin_required
def user_list(request):
    """用户管理（仅管理员）"""
    users = User.objects.all().order_by('-date_joined')
    return render(request, 'admin/user_list.html', {'users': users})


@login_required
@admin_required
def user_detail(request, user_id):
    """用户详情"""
    user = get_object_or_404(User, id=user_id)
    questionnaires = Questionnaire.objects.filter(creator=user)
    responses = Response.objects.filter(user=user)

    return render(request, 'admin/user_detail.html', {
        'target_user': user,
        'questionnaires': questionnaires,
        'responses': responses,
    })


@login_required
def questionnaire_list(request):
    """问卷列表（根据权限显示）"""
    if request.user.is_admin:
        questionnaires = Questionnaire.objects.all().order_by('-created_at')
    else:
        questionnaires = Questionnaire.objects.filter(creator=request.user).order_by('-created_at')

    return render(request, 'questionnaire/list.html', {
        'questionnaires': questionnaires,
    })


@login_required
def create_questionnaire(request):
    """创建问卷（一体化页面）"""
    if request.method == 'POST':
        form = QuestionnaireForm(request.POST)
        question_formset = QuestionFormSet(request.POST)

        if form.is_valid() and question_formset.is_valid():
            # 保存问卷
            questionnaire = form.save(commit=False)
            questionnaire.creator = request.user

            # 生成邀请码
            if not questionnaire.is_public:
                questionnaire.invite_code = ''.join(
                    random.choices(string.ascii_uppercase + string.digits, k=8)
                )

            questionnaire.save()

            # 保存问题
            questions = question_formset.save(commit=False)
            for i, question in enumerate(questions):
                question.questionnaire = questionnaire
                question.order = i
                question.save()

            messages.success(request, '问卷创建成功！')
            return redirect('edit_questionnaire', questionnaire_id=questionnaire.id)

    else:
        form = QuestionnaireForm()
        question_formset = QuestionFormSet()

    return render(request, 'questionnaire/create.html', {
        'form': form,
        'question_formset': question_formset,
    })


@login_required
def edit_questionnaire(request, questionnaire_id):
    """编辑问卷"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id, creator=request.user)

    if request.method == 'POST':
        form = QuestionnaireForm(request.POST, instance=questionnaire)
        question_formset = QuestionFormSet(request.POST, instance=questionnaire)

        if form.is_valid() and question_formset.is_valid():
            form.save()
            question_formset.save()
            messages.success(request, '问卷已保存！')
            return redirect('edit_questionnaire', questionnaire_id=questionnaire.id)

    else:
        form = QuestionnaireForm(instance=questionnaire)
        question_formset = QuestionFormSet(instance=questionnaire)

    return render(request, 'questionnaire/edit.html', {
        'questionnaire': questionnaire,
        'form': form,
        'question_formset': question_formset,
    })


@login_required
def publish_questionnaire(request, questionnaire_id):
    """发布问卷"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id, creator=request.user)

    if request.method == 'POST':
        # 生成二维码
        survey_url = request.build_absolute_uri(f'/survey/{questionnaire.id}/')
        qr_img = generate_qr_code(survey_url)

        # 保存二维码
        buffer = BytesIO()
        qr_img.save(buffer, format='PNG')
        questionnaire.qr_code.save(
            f'qrcode_{questionnaire.id}.png',
            ContentFile(buffer.getvalue())
        )

        # 更新状态
        questionnaire.status = 'published'
        questionnaire.published_at = timezone.now()
        questionnaire.save()

        messages.success(request, '问卷已发布！二维码已生成。')
        return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)

    return render(request, 'questionnaire/publish.html', {
        'questionnaire': questionnaire,
        'survey_url': request.build_absolute_uri(f'/survey/{questionnaire.id}/'),
    })


@login_required
def questionnaire_detail(request, questionnaire_id):
    """问卷详情"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 检查权限（管理员或创建者）
    if not request.user.is_admin and questionnaire.creator != request.user:
        messages.error(request, '没有权限查看此问卷')
        return redirect('questionnaire_list')

    responses = questionnaire.responses.select_related('user')

    return render(request, 'questionnaire/detail.html', {
        'questionnaire': questionnaire,
        'responses': responses,
        'qr_code_url': questionnaire.qr_code.url if questionnaire.qr_code else None,
        'invite_code': questionnaire.invite_code,
    })