from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache
from django.db import IntegrityError
from django.utils.dateparse import parse_datetime
import json
from .models import Questionnaire, Response, Question, Answer
from .sm4 import sm4_encode
from django.db.models import F

def survey_access(request, questionnaire_id=None, invite_code=None):
    """问卷访问入口"""
    questionnaire = None

    if questionnaire_id:
        questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)
    elif invite_code:
        questionnaire = get_object_or_404(Questionnaire, invite_code=invite_code)

    if not questionnaire:
        messages.error(request, '问卷不存在')
        return redirect('home')

    # 增加访问计数
    questionnaire.view_count += 1
    questionnaire.save()

    # 检查问卷状态
    if questionnaire.status != 'published':
        return render(request, 'questionnaire/verify_invite_simple.html', {'questionnaire': questionnaire})

    # ====== 新增：时间和份数检查 ======
    now = timezone.now()
    if questionnaire.start_time and now < questionnaire.start_time:
        return render(request, 'questionnaire/closed.html', {'reason': '问卷尚未开始'})
    if questionnaire.end_time and now > questionnaire.end_time:
        return render(request, 'questionnaire/closed.html', {'reason': '问卷已截止'})
    if questionnaire.limit_responses and questionnaire.max_responses is not None:
        if questionnaire.submit_count >= questionnaire.max_responses:
            return render(request, 'questionnaire/closed.html', {'reason': '问卷已达到收集上限'})
    # =================================

    # 检查访问权限（原样保留）
    if questionnaire.access_type == 'public':
        # 公开访问，需要登录
        return redirect('survey_form', questionnaire_id=questionnaire.id)
    elif questionnaire.access_type == 'invite':
        # 邀请码访问
        if 'valid_invite_code' not in request.session or request.session.get(
                'valid_invite_code') != questionnaire.invite_code:
            return render(request, 'questionnaire/verify_invite_code.html', {'questionnaire': questionnaire})
        return redirect('survey_form', questionnaire_id=questionnaire.id)

    messages.error(request, '无法访问此问卷')
    return redirect('home')


def survey_form(request, questionnaire_id):
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)
    now = timezone.now()
    if questionnaire.start_time and now < questionnaire.start_time:
        return render(request, 'questionnaire/closed.html', {'reason': '问卷尚未开始'})
    if questionnaire.end_time and now > questionnaire.end_time:
        return render(request, 'questionnaire/closed.html', {'reason': '问卷已截止'})
    if questionnaire.limit_responses and questionnaire.max_responses is not None:
        if questionnaire.submit_count >= questionnaire.max_responses:
            return render(request, 'questionnaire/closed.html', {'reason': '问卷已达到收集上限'})
    # ---------- 公共检查（问卷状态、邀请码）----------
    if questionnaire.access_type == 'invite':
        if 'valid_invite_code' not in request.session or request.session.get(
                'valid_invite_code') != questionnaire.invite_code:
            return redirect('survey_access', questionnaire_id=questionnaire.id)
    viewed_key = f'viewed_q_{questionnaire.id}'
    if not request.session.get(viewed_key):
        # 使用 F 表达式在数据库层原子更新，避免并发丢失
        Questionnaire.objects.filter(id=questionnaire.id).update(view_count=F('view_count') + 1)
        # 刷新当前 questionnaire 对象，使后续使用保持最新
        questionnaire.refresh_from_db()
        # 标记该会话已计数
        request.session[viewed_key] = True
    if request.user.is_authenticated:
        check_count = Response.objects.filter(questionnaire=questionnaire, user=request.user).count()
        debug_check = f'问卷ID={questionnaire.id} 用户ID={request.user.id} Response记录数={check_count}'

        current_version_submitted = Response.objects.filter(
            questionnaire=questionnaire,
            user=request.user,
            questionnaire_version=questionnaire.version
        ).exists()

        if current_version_submitted:
            return render(request, 'questionnaire/already_submitted.html', {
                'questionnaire': questionnaire,
                'current_version': questionnaire.version,
            })

        old_responses = Response.objects.filter(
            questionnaire=questionnaire,
            user=request.user
        ).exclude(questionnaire_version=questionnaire.version)

        has_old_version_submission = old_responses.exists()
        latest_old_version = None
        if has_old_version_submission:
            latest_old = old_responses.order_by('-questionnaire_version').first()
            latest_old_version = latest_old.questionnaire_version if latest_old else None

        submitted = Response.objects.filter(questionnaire=questionnaire, user=request.user).exists()
        record_count = Response.objects.filter(questionnaire=questionnaire, user=request.user).count()

        context = {
            'questionnaire': questionnaire,
            'questions': questionnaire.questions.all().order_by('order'),
            'submitted': submitted,
            'debug_check': debug_check,
            'record_count': record_count,
            'has_old_version_submission': has_old_version_submission,
            'questionnaire_version': questionnaire.version,
            'latest_old_version': latest_old_version,
        }
        return render(request, 'questionnaire/form.html', context)

    else:
        context = {
            'questionnaire': questionnaire,
            'questions': questionnaire.questions.all().order_by('order'),
            'questionnaire_version': questionnaire.version,
        }
        return render(request, 'questionnaire/form.html', context)


@require_POST
def submit_response(request, questionnaire_id):
    """提交问卷（登录用户和匿名用户）"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # ========== 登录用户分支 ==========
    if request.user.is_authenticated:
        with transaction.atomic():
            # 锁定问卷行，防止并发提交
            questionnaire = Questionnaire.objects.select_for_update().get(pk=questionnaire_id)

            # 时间和份数检查
            now = timezone.now()
            if questionnaire.end_time and now > questionnaire.end_time:
                return JsonResponse({'success': False, 'error': '问卷已截止'}, status=400)
            if questionnaire.limit_responses and questionnaire.max_responses is not None:
                if questionnaire.submit_count >= questionnaire.max_responses:
                    return JsonResponse({'success': False, 'error': '问卷已达到收集上限'}, status=400)

            # 检查是否已提交当前版本
            if Response.objects.filter(
                    questionnaire=questionnaire,
                    user=request.user,
                    questionnaire_version=questionnaire.version
            ).exists():
                return render(request, 'questionnaire/already_submitted.html', {
                    'questionnaire': questionnaire,
                })

            try:
                # 计算完成时间
                start_time = request.session.get('start_time')
                completion_time = None
                if start_time:
                    start = timezone.datetime.fromisoformat(start_time)
                    if start.tzinfo is None:
                        start = timezone.make_aware(start, timezone.get_current_timezone())
                    completion_time = int((timezone.now() - start).total_seconds())

                # ---------- 备份版本的答案收集逻辑（完整保留）----------
                data = request.POST.dict()
                answers_dict = {}
                for key, value in data.items():
                    if key.startswith('question_'):
                        question_id = key.replace('question_', '')
                        if key in request.POST.lists():
                            answers_dict[question_id] = request.POST.getlist(key)
                        else:
                            answers_dict[question_id] = value

                # 必填问题检查
                for question in questionnaire.questions.all():
                    if question.required:
                        answer = answers_dict.get(str(question.id))
                        if not answer or (isinstance(answer, str) and answer.strip() == ''):
                            return JsonResponse({
                                'success': False,
                                'error': f'问题"{question.text}"是必填项'
                            })

                # 加密答案（保留原有加密逻辑）
                encrypted_answers = sm4_encode(json.dumps(answers_dict))

                # 创建答卷（与备份版本字段完全一致）
                response = Response.objects.create(
                    questionnaire=questionnaire,
                    user=request.user,
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    is_submitted=True,
                    questionnaire_version=questionnaire.version,
                    user_id=request.user.id,
                    questionnaire_id=questionnaire.id,
                    completion_time=completion_time
                )

                # 保存每个问题的答案
                for question_id, answer_value in answers_dict.items():
                    try:
                        question = Question.objects.get(id=question_id, questionnaire=questionnaire)

                        if question.question_type == 'radio':
                            # 将索引转换为字母
                            if isinstance(answer_value, str) and answer_value.isdigit():
                                idx = int(answer_value)
                                if 0 <= idx < len(question.options):
                                    answer_text = chr(65 + idx)
                                else:
                                    answer_text = ''  # 选项超出范围，留空或忽略
                            else:
                                answer_text = answer_value  # 如果已经是字母，直接使用

                        elif question.question_type == 'checkbox':
                            # 处理多选：可能为列表或单个字符串
                            selected = []
                            if isinstance(answer_value, list):
                                for v in answer_value:
                                    if isinstance(v, str) and v.isdigit():
                                        idx = int(v)
                                        if 0 <= idx < len(question.options):
                                            selected.append(chr(65 + idx))
                            elif isinstance(answer_value, str) and answer_value.isdigit():
                                idx = int(answer_value)
                                if 0 <= idx < len(question.options):
                                    selected.append(chr(65 + idx))
                            answer_text = ','.join(selected) if selected else ''

                        else:  # text 简答题
                            answer_text = answer_value

                        Answer.objects.create(
                            response=response,
                            question=question,
                            answer_text=answer_text
                        )
                    except Question.DoesNotExist:
                        continue

                # 原子递增提交计数
                questionnaire.submit_count += 1
                questionnaire.save(update_fields=['submit_count'])

                messages.success(request, '问卷提交成功！')
                return JsonResponse({'success': True, 'response_id': str(response.id)})


            except Exception as e:
                import traceback
                traceback.print_exc()
                transaction.set_rollback(True)  # 新增：手动回滚事务
                messages.error(request, f'提交失败: {str(e)}')
                return redirect('survey_form', questionnaire_id=questionnaire.id)

    # ========== 匿名用户分支 ==========
    else:
        fingerprint = request.POST.get('device_fingerprint', '').strip()
        if not fingerprint or len(fingerprint) < 32:
            return JsonResponse({'success': False, 'error': '无法识别设备，请刷新页面重试'})

        cache_key = f'survey:anon:{questionnaire.id}:{fingerprint}:v{questionnaire.version}'
        if cache.get(cache_key):
            return JsonResponse({'success': False, 'error': '您已提交过当前版本'})

        # 快速数据库检查
        if Response.objects.filter(
            questionnaire=questionnaire,
            device_fingerprint=fingerprint,
            questionnaire_version=questionnaire.version
        ).exists():
            return JsonResponse({'success': False, 'error': '您已提交过当前版本'})

        start_str = request.POST.get('start_time')
        completion_time = None
        if start_str:
            try:
                start = parse_datetime(start_str)
                if start.tzinfo is None:
                    start = timezone.make_aware(start, timezone.utc)
                completion_time = int((timezone.now() - start).total_seconds())
            except:
                pass

        try:
            with transaction.atomic():
                # 锁定问卷行
                questionnaire = Questionnaire.objects.select_for_update().get(pk=questionnaire_id)

                # 新增：时间和份数检查
                now = timezone.now()
                if questionnaire.end_time and now > questionnaire.end_time:
                    return JsonResponse({'success': False, 'error': '问卷已截止'}, status=400)
                if questionnaire.limit_responses and questionnaire.max_responses is not None:
                    if questionnaire.submit_count >= questionnaire.max_responses:
                        return JsonResponse({'success': False, 'error': '问卷已达到收集上限'}, status=400)

                # 再次检查指纹（防止并发）
                if Response.objects.filter(
                    questionnaire=questionnaire,
                    device_fingerprint=fingerprint,
                    questionnaire_version=questionnaire.version
                ).exists():
                    return JsonResponse({'success': False, 'error': '您已提交过当前版本'})

                response = Response.objects.create(
                    questionnaire=questionnaire,
                    user=None,
                    device_fingerprint=fingerprint,
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:200],
                    is_submitted=True,
                    questionnaire_version=questionnaire.version,
                    completion_time=completion_time
                )

                # 保存答案（与登录分支逻辑一致）
                for q in questionnaire.questions.all():
                    key = f'question_{q.id}'
                    if q.question_type == 'text':
                        val = request.POST.get(key, '').strip()
                        if val:
                            Answer.objects.create(response=response, question=q, answer_text=val)
                    elif q.question_type == 'radio':
                        val = request.POST.get(key, '').strip()
                        if val.isdigit():
                            opt_idx = int(val)
                            if 0 <= opt_idx < len(q.options):
                                selected = chr(65 + opt_idx)
                                Answer.objects.create(response=response, question=q, answer_text=selected)
                    elif q.question_type == 'checkbox':
                        vals = request.POST.getlist(key)
                        selected = [chr(65 + int(v)) for v in vals if v.isdigit() and 0 <= int(v) < len(q.options)]
                        if selected:
                            Answer.objects.create(response=response, question=q, answer_text=','.join(selected))

                # 原子递增提交计数
                questionnaire.submit_count += 1
                questionnaire.save(update_fields=['submit_count'])

            cache.set(cache_key, '1', timeout=60*60*24*30)
            return JsonResponse({'success': True, 'response_id': str(response.id)})

        except IntegrityError:
            transaction.set_rollback(True)  # 新增
            return JsonResponse({'success': False, 'error': '您已提交过当前版本'})
        except Exception as e:
            transaction.set_rollback(True)  # 新增
            return JsonResponse({'success': False, 'error': f'提交失败: {str(e)}'})


@login_required
@require_GET
def check_submitted(request, questionnaire_id):
    """进入页面时检查是否已提交（原样保留）"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)
    submitted = Response.objects.filter(
        questionnaire=questionnaire,
        user=request.user,
        questionnaire_version=questionnaire.version
    ).exists()
    return JsonResponse({'submitted': submitted})