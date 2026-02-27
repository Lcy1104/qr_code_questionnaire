# questionnaire/views_ajax.py
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Questionnaire, Question
import secrets
import string
import django_rq
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Count, Q
import json

# 导入二维码生成函数
from .views_qrcode import generate_qrcode_for_questionnaire


@login_required
def ajax_publish_questionnaire(request, questionnaire_id):
    """AJAX发布问卷"""
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'message': '非法请求'})

    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 检查权限
    if questionnaire.creator != request.user and not request.user.is_admin:
        return JsonResponse({'success': False, 'message': '没有权限'})

    # 检查问卷状态
    if questionnaire.status != 'draft':
        return JsonResponse({'success': False, 'message': '问卷已发布或已关闭'})

    # 验证问卷内容
    errors = validate_questionnaire_for_publishing(questionnaire)
    if errors:
        return JsonResponse({
            'success': False,
            'message': '问卷内容验证失败',
            'errors': errors
        })

    # 获取表单数据
    access_type = request.POST.get('access_type', 'public')
    invite_code = request.POST.get('invite_code', '').strip()

    # 更新问卷信息
    questionnaire.access_type = access_type
    questionnaire.status = 'published'
    questionnaire.published_at = timezone.now()
    questionnaire.version += 1

    # 如果是邀请码问卷，处理邀请码
    if access_type == 'invite':
        if invite_code:
            # 检查邀请码是否唯一
            if Questionnaire.objects.filter(invite_code=invite_code).exclude(id=questionnaire.id).exists():
                return JsonResponse({'success': False, 'message': '邀请码已存在'})
            questionnaire.invite_code = invite_code
        else:
            # 生成邀请码
            alphabet = string.ascii_uppercase + string.digits
            questionnaire.invite_code = ''.join(secrets.choice(alphabet) for _ in range(8))

    # 保存问卷
    questionnaire.save()

    # 生成并保存二维码
    qr_code_url = generate_qrcode_for_questionnaire(request, questionnaire)

    # 返回成功响应
    response_data = {
        'success': True,
        'message': '问卷已成功发布',
        'questionnaire_id': str(questionnaire.id),
        'status': questionnaire.status,
        'version': questionnaire.version,
        'access_type': questionnaire.access_type,
        'invite_code': questionnaire.invite_code,
        'published_at': questionnaire.published_at.isoformat() if questionnaire.published_at else None,
        'survey_url': request.build_absolute_uri(f'/survey/{questionnaire.id}/'),
        'qr_code_url': qr_code_url
    }

    return JsonResponse(response_data)


def validate_questionnaire_for_publishing(questionnaire):
    """验证问卷内容是否完整"""
    errors = []

    # 检查问卷标题
    if not questionnaire.title or questionnaire.title.strip() == '':
        errors.append('问卷标题不能为空')

    # 检查问题
    questions = questionnaire.questions.all()
    if not questions.exists():
        errors.append('问卷至少需要一个问题')
        return errors

    for i, question in enumerate(questions):
        # 检查问题内容
        if not question.text or question.text.strip() == '':
            errors.append(f'问题 {i + 1}: 问题内容不能为空')

        # 检查选择题的选项
        if question.question_type in ['radio', 'checkbox']:
            if not question.options or len(question.options) == 0:
                errors.append(f'问题 {i + 1}: 选择题必须至少有一个选项')
            else:
                # 检查选项是否为空
                for j, option in enumerate(question.options):
                    if not option or option.strip() == '':
                        errors.append(f'问题 {i + 1} 的选项 {j + 1}: 选项内容不能为空')

    return errors

@login_required
def ajax_batch_operate(request):
    """接收批量操作请求，扔进 Redis 队列"""
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'message': '非法请求'})
    action = request.POST.get('action')          # publish / delete
    ids = json.loads(request.POST.get('ids', '[]'))
    if action not in ('publish', 'delete') or not ids:
        return JsonResponse({'success': False, 'message': '参数错误'})

    # 权限：只能操作自己的问卷
    qs = Questionnaire.objects.filter(id__in=ids, creator=request.user)
    if qs.count() != len(ids):
        return JsonResponse({'success': False, 'message': '存在无权限问卷'})
    if action == 'delete':
        cnt = qs.count()
        qs.delete()
        return JsonResponse({'success': True, 'message': f'已删除 {cnt} 份问卷'})
    # 扔进队列
    queue = django_rq.get_queue('default')
    job = queue.enqueue(_do_batch, action, ids)
    return JsonResponse({'success': True, 'task_id': job.id, 'message': '任务已提交'})

def _do_batch(action, ids):
    """真正耗时的任务，在 worker 里执行"""
    qs = Questionnaire.objects.filter(id__in=ids)
    if action == 'publish':
        # 只能发布草稿
        qs = qs.filter(status='draft')
        for q in qs:
            q.status = 'published'
            q.published_at = timezone.now()
            if q.access_type == 'invite' and not q.invite_code:
                q.invite_code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        Questionnaire.objects.bulk_update(qs, ['status', 'published_at', 'invite_code'])

@login_required
def ajax_task_result(request):
    """轮询任务结果"""
    from rq.job import Job
    from django_rq import get_connection
    job = Job.fetch(request.GET.get('task_id'), connection=get_connection())
    if job.is_finished:
        return JsonResponse({'status': 'SUCCESS'})
    if job.is_failed:
        return JsonResponse({'status': 'FAILURE', 'error': str(job.exc_info)})
    return JsonResponse({'status': 'PENDING'})