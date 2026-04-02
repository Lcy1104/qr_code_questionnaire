# questionnaire/views_survey.py
import logging
import time
import json
import uuid
from django.views.decorators.cache import never_cache
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .forms import SelectTargetForm
from .models import Questionnaire, Response, Answer, QuestionnaireQRCode,Question
from .notification_manager  import NotificationManager
from django.contrib import messages
from django.core.cache import cache  # ===== 新增（移到顶部统一导入）=====

logger = logging.getLogger(__name__)

def survey_landing(request, survey_uuid):
    """
    问卷引导页 - 扫码后直接访问
    任何用户都能访问，用于展示问卷信息和引导登录
    """
    questionnaire = get_object_or_404(Questionnaire, id=survey_uuid, status='published')

    stop_condition_closed = False
    stop_reason = None
    if questionnaire.status == 'closed':
        stop_condition_closed = True
        if questionnaire.closed_reason:
            stop_reason = questionnaire.closed_reason
        else:
            # 兼容旧数据（如果还有字典格式）
            if isinstance(questionnaire.stop_condition, dict) and questionnaire.stop_condition.get('keyword'):
                keyword = questionnaire.stop_condition.get('keyword')
                threshold = questionnaire.stop_condition.get('threshold', 0)
                stop_reason = f"由于“{keyword}”数量已达到{threshold}，问卷已关闭。"
            else:
                stop_reason = "问卷已关闭。"

    if questionnaire.status != 'published':
        return render(request, 'questionnaire/not_available.html', {
            'questionnaire': questionnaire,
            'reason': '问卷未发布' if questionnaire.status == 'draft' else '问卷已结束'
        })

    context = {
        'questionnaire': questionnaire,
        'user_is_authenticated': request.user.is_authenticated,
        'stop_condition_closed': stop_condition_closed,  # 新增
        'stop_reason': stop_reason,  # 新增
    }

    if questionnaire.is_multi_target:
        start_url_name = 'multi_target_dashboard'
    elif questionnaire.targets:
        start_url_name = 'select_target'
    else:
        start_url_name = 'survey_form'

    if questionnaire.is_multi_target:
        context['anonymous_url'] = reverse('multi_target_dashboard', args=[survey_uuid]) + '?anonymous=1'
    elif questionnaire.targets:
        context['anonymous_url'] = reverse('select_target', args=[survey_uuid]) + '?anonymous=1'
    else:
        context['anonymous_url'] = reverse('survey_form', args=[survey_uuid]) + '?anonymous=1'

    if request.user.is_authenticated:
        context['start_url'] = reverse(start_url_name, args=[survey_uuid])
    else:
        context['login_url'] = reverse('login') + f'?next={reverse(start_url_name, args=[survey_uuid])}'
        context['register_url'] = reverse('register') + f'?next={reverse(start_url_name, args=[survey_uuid])}'

    return render(request, 'questionnaire/landing.html', context)

@never_cache
def survey_fill(request, survey_uuid):
    questionnaire = get_object_or_404(Questionnaire, id=survey_uuid, status='published')

    # ===== 修改：原有跳转逻辑，仅对非多目标问卷执行 =====
    if questionnaire.targets and not questionnaire.is_multi_target:
        return redirect('select_target', questionnaire_id=questionnaire.id)

    # ===== 新增：多目标处理 =====
    target = request.GET.get('target')
    if questionnaire.is_multi_target:
        # 没有指定目标 -> 跳转仪表盘
        if not target:
            return redirect('multi_target_dashboard', questionnaire_id=questionnaire.id)
        # 验证目标有效性
        if target not in questionnaire.targets:
            messages.error(request, '无效的评价目标')
            return redirect('multi_target_dashboard', questionnaire_id=questionnaire.id)

        # 检查该目标是否已提交
        if request.user.is_authenticated:
            exists = Response.objects.filter(
                questionnaire=questionnaire,
                user=request.user,
                questionnaire_version=questionnaire.version,
                target_name=target,
                is_submitted=True
            ).exists()
        else:
            fingerprint = request.session.get('anon_fingerprint')
            if fingerprint:
                exists = Response.objects.filter(
                    questionnaire=questionnaire,
                    device_fingerprint=fingerprint,
                    questionnaire_version=questionnaire.version,
                    target_name=target,
                    is_submitted=True
                ).exists()
            else:
                exists = False

        if exists:
            messages.info(request, f'您已经评价过目标“{target}”')
            return redirect('multi_target_dashboard', questionnaire_id=questionnaire.id)

        # 将当前目标存入 session，供提交时使用
        request.session['selected_target'] = target
        current_target = target
    else:
        # 原有逻辑：两步填写（单目标）
        if questionnaire.targets and not request.session.get('selected_target'):
            return redirect('select_target', questionnaire_id=questionnaire.id)
        current_target = None
    # ===== 新增结束 =====

    # 公共检查（邀请码）
    if questionnaire.access_type == 'invite':
        if 'valid_invite_code' not in request.session or request.session.get('valid_invite_code') != questionnaire.invite_code:
            return redirect('survey_landing', survey_uuid=survey_uuid)

    # 判断是否为匿名模式（通过 URL 参数 ?anonymous=1 触发）
    is_anonymous_mode = request.GET.get('anonymous') == '1'

    # 未登录且非匿名模式，重定向到引导页（由引导页决定登录或匿名）
    if not request.user.is_authenticated and not is_anonymous_mode:
        return redirect('survey_landing', survey_uuid=survey_uuid)

    if request.user.is_authenticated and not is_anonymous_mode:
        # 已登录且非匿名模式：正常登录用户填写
        if not questionnaire.is_multi_target:
            if Response.objects.filter(questionnaire=questionnaire, user=request.user).exists():
                return render(request, 'questionnaire/already_submitted.html', {
                    'questionnaire': questionnaire
                })
        questions = questionnaire.questions.all().order_by('order').values(
            'id', 'text', 'question_type', 'options', 'required', 'max_length'
        )
        # ===== 新增：预填答案（登录用户）=====
        answers_dict = {}
        if questionnaire.is_multi_target and current_target:
            filter_kwargs = {'user': request.user}
            try:
                draft = Response.objects.get(
                    questionnaire=questionnaire,
                    questionnaire_version=questionnaire.version,
                    target_name=current_target,
                    is_submitted=False,
                    **filter_kwargs
                )
                for ans in draft.answer_items.select_related('question'):
                    qid = ans.question.id
                    if ans.question.question_type == 'checkbox':
                        letters = ans.answer_text.split(',')
                        indices = [ord(letter)-65 for letter in letters if letter]
                        answers_dict[qid] = indices
                    elif ans.question.question_type == 'radio':
                        letter = ans.answer_text
                        if letter:
                            answers_dict[qid] = ord(letter) - 65
                    else:
                        answers_dict[qid] = ans.answer_text
            except Response.DoesNotExist:
                pass
        # ===== 新增结束 =====
        return render(request, 'questionnaire/fill.html', {
            'questionnaire': questionnaire,
            'questions': questions,
            'is_anonymous_mode': False,
            'current_target': current_target,  # ===== 新增 =====
            'answers_dict': json.dumps(answers_dict),  # ===== 新增 =====
            'anonymous_fingerprint': None,  # ===== 新增 =====
        })
    else:
        # 匿名模式（包括未登录用户或已登录但选择匿名）
        questions = questionnaire.questions.all().order_by('order').values(
            'id', 'text', 'question_type', 'options', 'required', 'max_length'
        )
        # ===== 新增：预填答案（匿名用户）和指纹同步 =====
        answers_dict = {}
        if questionnaire.is_multi_target and current_target:
            fingerprint = request.session.get('anon_fingerprint')
            logger.debug(f"survey_fill (anon): target={current_target}, fingerprint from session={fingerprint}")
            if fingerprint:
                try:
                    draft = Response.objects.get(
                        questionnaire=questionnaire,
                        questionnaire_version=questionnaire.version,
                        target_name=current_target,
                        is_submitted=False,
                        device_fingerprint=fingerprint
                    )
                    logger.debug(f"survey_fill (anon): found draft for {current_target}")
                    for ans in draft.answer_items.select_related('question'):
                        qid = ans.question.id
                        if ans.question.question_type == 'checkbox':
                            letters = ans.answer_text.split(',')
                            indices = [ord(letter)-65 for letter in letters if letter]
                            answers_dict[qid] = indices
                        elif ans.question.question_type == 'radio':
                            letter = ans.answer_text
                            if letter:
                                answers_dict[qid] = ord(letter) - 65
                        else:
                            answers_dict[qid] = ans.answer_text
                except Response.DoesNotExist:
                    logger.debug(f"survey_fill (anon): no draft for {current_target}")
                    pass

        anonymous_fingerprint = request.session.get('anon_fingerprint')
        if not anonymous_fingerprint:
            anonymous_fingerprint = str(uuid.uuid4())
            request.session['anon_fingerprint'] = anonymous_fingerprint
        return render(request, 'questionnaire/fill.html', {
            'questionnaire': questionnaire,
            'questions': questions,
            'is_anonymous_mode': True,
            'current_target': current_target,  # ===== 新增 =====
            'answers_dict': json.dumps(answers_dict),  # ===== 新增 =====
            'anonymous_fingerprint': anonymous_fingerprint,  # ===== 新增 =====
        })

# ===== 新增：答案保存辅助函数 =====
def _save_answers(response, request, check_required=False):
    """保存答案到 response，check_required 为 True 时检查必填"""
    questionnaire = response.questionnaire
    for q in questionnaire.questions.all():
        key = f'question_{q.id}'
        raw = request.POST.get(f'maxlen_{q.id}', '0').strip()
        if raw.isdigit():
            q.max_length = int(raw)
            q.save(update_fields=['max_length'])

        if q.question_type == 'text':
            val = request.POST.get(key, '').strip()
            if val:
                Answer.objects.create(response=response, question=q, answer_text=val)
            elif check_required and q.required:
                return f'问题“{q.text}”是必填项，请填写内容。'

        elif q.question_type == 'radio':
            val = request.POST.get(key, '').strip()
            if val:
                if not val.isdigit():
                    return '单选参数异常'
                opt_idx = int(val)
                if opt_idx < 0 or opt_idx >= len(q.options):
                    return '选项超出范围'
                selected_option = chr(65 + opt_idx)
                Answer.objects.create(response=response, question=q, answer_text=selected_option)
            elif check_required and q.required:
                return f'问题“{q.text}”是必选题，请选择一个选项。'

        elif q.question_type == 'checkbox':
            vals = request.POST.getlist(key)
            selected_options = []
            for v in vals:
                if not v.isdigit():
                    return '多选参数异常'
                opt_idx = int(v)
                if opt_idx < 0 or opt_idx >= len(q.options):
                    return '选项超出范围'
                selected_options.append(chr(65 + opt_idx))
            if selected_options:
                answer_text = ','.join(selected_options)
                Answer.objects.create(response=response, question=q, answer_text=answer_text)
            elif check_required and q.required:
                return f'问题“{q.text}”是必选题，请至少选择一个选项。'
    return None
# ===== 新增结束 =====

@transaction.atomic
def handle_survey_submission(request, questionnaire_id):
    # 先检查是否为 AJAX 请求（通过头部）
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    # 例外情况：如果请求中包含有效的 device_fingerprint，则视为匿名AJAX提交（因为只有前端匿名脚本会添加此字段）
    fingerprint = request.POST.get('device_fingerprint', '').strip()
    has_valid_fingerprint = fingerprint and len(fingerprint) >= 16

    # 如果不是 AJAX 且没有有效指纹，则拒绝
    if not is_ajax and not has_valid_fingerprint:
        return JsonResponse({'ok': False, 'msg': '请使用 AJAX 提交'}, status=400)

    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id, status='published')
    logger.debug(f"问卷 {questionnaire_id} is_multi_target = {questionnaire.is_multi_target}")
    # 如果希望看到更详细的信息，可以打印所有 POST 数据
    logger.debug(f"POST data: {dict(request.POST)}")
    is_anonymous_mode = request.POST.get('anonymous') == '1'
    # ===== 新增：获取 action 参数 =====
    action = request.POST.get('action', 'submit')  # 'draft' 或 'submit'
    # ===== 新增结束 =====

    if request.user.is_authenticated and not is_anonymous_mode:
        logger.debug(f'request.POST = {dict(request.POST)}')
        # ===== 修改：根据 action 决定是否执行检查（只对提交执行）=====
        if action == 'submit':
            logger.debug("进入提交处理，is_multi_target = %s", questionnaire.is_multi_target)
            now = timezone.now()
            if questionnaire.end_time and now > questionnaire.end_time:
                return JsonResponse({'ok': False, 'msg': '问卷已截止'}, status=400)
            if questionnaire.limit_responses and questionnaire.max_responses is not None:
                if questionnaire.submit_count >= questionnaire.max_responses:
                    return JsonResponse({'ok': False, 'msg': '问卷已达到收集上限'}, status=400)

            if not questionnaire.is_multi_target:
                if Response.objects.filter(
                        questionnaire=questionnaire,
                        user=request.user,
                        questionnaire_version=questionnaire.version,
                        is_submitted=True).exists():
                    return JsonResponse({'ok': False, 'msg': '您已提交过当前版本'}, status=400)
        # ===== 修改结束 =====

        # ===== 新增：获取目标名称（支持多目标）=====
        target_name = request.POST.get('target_name', '')
        if not target_name:
            target_name = request.session.pop('selected_target', '') if questionnaire.targets else ''
        # ===== 新增结束 =====

        # ===== 修改：查找或创建暂存记录（支持暂存）=====
        try:
            response = Response.objects.select_for_update().get(
                questionnaire=questionnaire,
                user=request.user,
                questionnaire_version=questionnaire.version,
                target_name=target_name,
                is_submitted=False
            )
            # 删除旧答案，准备重新保存
            response.answer_items.all().delete()
        except Response.DoesNotExist:
            response = Response(
                questionnaire=questionnaire,
                user=request.user,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:200],
                questionnaire_version=questionnaire.version,
                target_name=target_name,
                is_submitted=False
            )
        # ===== 关键修复：立即保存 response，确保有主键 =====
        response.save()
        # ===== 修改结束 =====

        # 计算完成时间（原有逻辑）
        submitted_at = timezone.now()
        start_str = request.POST.get('start_time')
        completion_time = None
        if start_str:
            try:
                start = parse_datetime(start_str)
                if start.tzinfo is None or start.tzinfo.utcoffset(start) is None:
                    start = timezone.make_aware(start, timezone.utc)
                start = start.astimezone(timezone.get_default_timezone())
                submitted_at = submitted_at.astimezone(timezone.get_default_timezone())
                completion_time = int((submitted_at - start).total_seconds())
                response.completion_time = completion_time  # ===== 新增：赋值 =====
            except Exception as e:
                logger.error(f'计算 completion_time 异常: {e}')
        else:
            logger.warning("start_time 为空，无法计算 completion_time")

        # ===== 新增：保存答案（调用辅助函数）=====
        error = _save_answers(response, request, check_required=(action == 'submit'))
        if error:
            return JsonResponse({'ok': False, 'msg': error}, status=400)
        # ===== 新增结束 =====

        # ===== 修改：二维码处理（先关联，不立即标记为已使用）=====
        qrcode_obj = None
        if questionnaire.enable_multi_qrcodes:
            # 1. 尝试从 session 获取已绑定的二维码 ID
            bound_qrcode_id = request.session.get('bound_qrcode_id')
            if bound_qrcode_id:
                try:
                    qrcode_obj = QuestionnaireQRCode.objects.select_for_update().get(
                        qr_code_id=bound_qrcode_id,
                        questionnaire=questionnaire,
                        is_used=False
                    )
                except QuestionnaireQRCode.DoesNotExist:
                    # 绑定失效，清除
                    request.session.pop('bound_qrcode_id', None)
                    qrcode_obj = None

            # 2. 如果没有绑定，则执行原分配逻辑
            if not qrcode_obj:
                specific_id = request.session.get('active_qrcode_id')
                if specific_id:
                    try:
                        qrcode_obj = QuestionnaireQRCode.objects.select_for_update().get(
                            qr_code_id=specific_id,
                            questionnaire=questionnaire,
                            is_used=False
                        )
                        if not qrcode_obj.is_shared:
                            qrcode_obj.is_shared = True
                            qrcode_obj.save(update_fields=['is_shared'])
                    except QuestionnaireQRCode.DoesNotExist:
                        return JsonResponse({'ok': False, 'msg': '指定的二维码无效或已被使用'}, status=400)
                else:
                    qrcode_obj = QuestionnaireQRCode.objects.select_for_update().filter(
                        questionnaire=questionnaire,
                        is_used=False,
                        is_shared=False
                    ).first()
                    if not qrcode_obj:
                        return JsonResponse({'ok': False, 'msg': '当前无可用的二维码，请稍后再试'}, status=400)

                # 分配后，将二维码 ID 存入 session 作为绑定
                request.session['bound_qrcode_id'] = qrcode_obj.qr_code_id

        if qrcode_obj:
            response.qrcode = qrcode_obj
            # 注意：不立即标记 is_used

        # ===== 修改：根据 action 执行不同操作 =====
        if action == 'submit':
            response.is_submitted = True
            response.save()

            # 更新问卷提交计数
            questionnaire.submit_count += 1
            questionnaire.save()
            # ========== 检查停止条件 ==========
            stop_conditions = questionnaire.stop_condition
            if stop_conditions and isinstance(stop_conditions, list):
                # 按目标维护计数：target_counts[target_name][(question_id, option_index)] = count
                target_counts = {}
                trigger_info = []  # 存储所有触发的 (target_name, cond, answer)

                # 获取所有已提交答案（包含当前提交的），按时间排序
                answers = Answer.objects.filter(
                    response__questionnaire=questionnaire,
                    response__is_submitted=True
                ).select_related('question', 'response').order_by('response__submitted_at', 'id')

                for ans in answers:
                    target_name = ans.response.target_name or ''
                    q_id = str(ans.question.id)
                    if ans.question.question_type in ['radio', 'checkbox'] and ans.answer_text:
                        for letter in ans.answer_text:
                            option_index = ord(letter) - 65
                            for cond in stop_conditions:
                                if cond['question_id'] == q_id and cond['option_index'] == option_index:
                                    if target_name not in target_counts:
                                        target_counts[target_name] = {}
                                    key = (q_id, option_index)
                                    target_counts[target_name][key] = target_counts[target_name].get(key, 0) + 1
                                    if target_counts[target_name][key] >= cond['threshold']:
                                        # 检查是否已经记录过这个条件（避免重复）
                                        already_triggered = any(
                                            t[0] == target_name and t[1]['question_id'] == q_id and t[1][
                                                'option_index'] == option_index
                                            for t in trigger_info
                                        )
                                        if not already_triggered:
                                            trigger_info.append((target_name, cond, ans))
                    # 简答题类似扩展，如需支持可自行添加

                if trigger_info:
                    # 生成关闭原因
                    reasons = []
                    for target_name, cond, ans in trigger_info:
                        q_text = ans.question.text
                        option_text = ans.question.options[cond['option_index']]
                        reasons.append(f"评价目标“{target_name}”在问题“{q_text}”中选择了“{option_text}”")
                    # 假设所有触发条件的阈值相同（全局条件相同关键词的阈值一致），取最后一个的阈值
                    last_threshold = trigger_info[-1][1]['threshold']
                    close_reason = "，".join(reasons) + f"，使得该选项被选择次数达到{last_threshold}次"

                    questionnaire.status = 'closed'
                    questionnaire.closed_reason = close_reason
                    questionnaire.save(update_fields=['status', 'closed_reason'])
                    try:
                        from .notification_manager import NotificationManager
                        NotificationManager.create_notification(
                            user=questionnaire.creator,
                            title=f"问卷已自动关闭：{questionnaire.title}",
                            message=close_reason,
                            notification_type='system',
                            related_questionnaire=questionnaire,
                            priority='high'
                        )
                    except Exception as e:
                        logger.error(f"发送关闭通知失败: {e}")
            # ========== 停止条件检查结束 ==========
            # 发送通知（原有代码）
            try:
                NotificationManager.create_notification(
                    user=questionnaire.creator,
                    title=f"新答卷：{questionnaire.title}",
                    message=f"用户 {request.user.username} 提交了一份新答卷。",
                    notification_type='system',
                    related_questionnaire=questionnaire,
                    priority='normal'
                )
            except Exception as e:
                logger.error(f"发送新答卷通知失败: {e}")

            # ===== 新增：检查是否所有目标已完成（多目标）=====
            if questionnaire.is_multi_target:
                submitted_targets = Response.objects.filter(
                    questionnaire=questionnaire,
                    user=request.user,
                    questionnaire_version=questionnaire.version,
                    is_submitted=True
                ).values_list('target_name', flat=True)
                all_completed = all(t in submitted_targets for t in questionnaire.targets)
                if all_completed and qrcode_obj:
                    # 标记二维码为已完成
                    qrcode_obj.is_used = True
                    qrcode_obj.used_by = request.user
                    qrcode_obj.used_at = timezone.now()
                    qrcode_obj.save(update_fields=['is_used', 'used_by', 'used_at'])
                    request.session.pop('bound_qrcode_id', None)
                    # 发送 WebSocket 广播
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        f'questionnaire_{questionnaire.id}',
                        {
                            'type': 'qrcode_update',
                            'qr_code_id': qrcode_obj.qr_code_id,
                            'is_used': True,
                            'used_by': request.user.username,
                            'used_at': timezone.now().isoformat(),
                            'response_id': str(response.id),
                        }
                    )

                if all_completed:
                    redirect_url = reverse('survey_thank_you', args=[questionnaire.id])
                else:
                    redirect_url = reverse('multi_target_dashboard', args=[questionnaire.id])
            else:
                # 原有单目标重定向
                if qrcode_obj:
                    qrcode_obj.is_used = True
                    qrcode_obj.used_by = request.user
                    qrcode_obj.used_at = timezone.now()
                    qrcode_obj.save(update_fields=['is_used', 'used_by', 'used_at'])
                    # 发送 WebSocket 广播
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        f'questionnaire_{questionnaire.id}',
                        {
                            'type': 'qrcode_update',
                            'qr_code_id': qrcode_obj.qr_code_id,
                            'is_used': True,
                            'used_by': request.user.username,
                            'used_at': timezone.now().isoformat(),
                            'response_id': str(response.id),
                        }
                    )
                redirect_url = reverse('questionnaire_detail', args=[questionnaire.id]) + f'?_={int(time.time())}'
            # ===== 新增结束 =====

            return JsonResponse({'ok': True, 'redirect': redirect_url})

        else:  # action == 'draft'
            response.is_submitted = False
            response.save()
            return JsonResponse({'ok': True, 'msg': '草稿已保存', 'redirect': None})
        # ===== 修改结束 =====

    # ========== 匿名用户分支：新增，完全独立 ==========
    else:
        from django.core.cache import cache
        from django.db import IntegrityError

        # 1. 设备指纹验证
        fingerprint = request.POST.get('device_fingerprint', '').strip()
        if not fingerprint or len(fingerprint) < 16:
            logger.warning(f'匿名提交失败：无效指纹，长度={len(fingerprint)}')
            return JsonResponse({'ok': False, 'msg': '无法识别设备，请刷新页面重试'}, status=400)

        # 如果是最终提交，进行严格检查
        if action == 'submit':
            cache_key = f'survey:anon:{questionnaire.id}:{fingerprint}:v{questionnaire.version}'
            if cache.get(cache_key):
                return JsonResponse({'ok': False, 'msg': '您已提交过当前版本'}, status=403)

            now = timezone.now()
            if questionnaire.end_time and now > questionnaire.end_time:
                return JsonResponse({'ok': False, 'msg': '问卷已截止'}, status=400)
            if questionnaire.limit_responses and questionnaire.max_responses is not None:
                if questionnaire.submit_count >= questionnaire.max_responses:
                    return JsonResponse({'ok': False, 'msg': '问卷已达到收集上限'}, status=400)

            if not questionnaire.is_multi_target:
                cache_key = f'survey:anon:{questionnaire.id}:{fingerprint}:v{questionnaire.version}'
                if cache.get(cache_key):
                    return JsonResponse({'ok': False, 'msg': '您已提交过当前版本'}, status=403)

                if Response.objects.filter(
                        questionnaire=questionnaire,
                        device_fingerprint=fingerprint,
                        questionnaire_version=questionnaire.version).exists():
                    return JsonResponse({'ok': False, 'msg': '您已提交过当前版本'}, status=403)

        # 目标处理
        target_name = request.POST.get('target_name', '').strip()
        if not target_name and questionnaire.targets:
            # 如果 POST 中没有，尝试从 session 获取（用于单目标两步填写）
            target_name = request.session.pop('selected_target', '')

        if target_name:
            if target_name not in questionnaire.targets:
                return JsonResponse({'ok': False, 'msg': '无效的目标'}, status=400)
            if action == 'submit':
                if Response.objects.filter(
                        questionnaire=questionnaire,
                        device_fingerprint=fingerprint,
                        questionnaire_version=questionnaire.version,
                        target_name=target_name,
                        is_submitted=True
                ).exists():
                    return JsonResponse({'ok': False, 'msg': f'您已评价过目标“{target_name}”'}, status=403)

        # 查找或创建暂存记录
        try:
            response = Response.objects.select_for_update().get(
                questionnaire=questionnaire,
                device_fingerprint=fingerprint,
                questionnaire_version=questionnaire.version,
                target_name=target_name,
                is_submitted=False
            )
            response.answer_items.all().delete()
        except Response.DoesNotExist:
            response = Response(
                questionnaire=questionnaire,
                user=None,
                device_fingerprint=fingerprint,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:200],
                questionnaire_version=questionnaire.version,
                target_name=target_name,
                is_submitted=False
            )
        response.save()  # 确保有主键

        # 计算完成时间
        submitted_at = timezone.now()
        start_str = request.POST.get('start_time')
        completion_time = None
        if start_str:
            try:
                start = parse_datetime(start_str)
                if start.tzinfo is None:
                    start = timezone.make_aware(start, timezone.utc)
                start = start.astimezone(timezone.get_default_timezone())
                submitted_at = submitted_at.astimezone(timezone.get_default_timezone())
                completion_time = int((submitted_at - start).total_seconds())
                response.completion_time = completion_time
            except Exception as e:
                logger.error(f'匿名计算 completion_time 异常: {e}')

        # 二维码处理
        qrcode_obj = None
        if questionnaire.enable_multi_qrcodes:
            bound_qrcode_id = request.session.get('bound_qrcode_id')
            if bound_qrcode_id:
                try:
                    qrcode_obj = QuestionnaireQRCode.objects.select_for_update().get(
                        qr_code_id=bound_qrcode_id,
                        questionnaire=questionnaire,
                        is_used=False
                    )
                except QuestionnaireQRCode.DoesNotExist:
                    request.session.pop('bound_qrcode_id', None)
                    qrcode_obj = None

            if not qrcode_obj:
                specific_id = request.session.get('active_qrcode_id')
                if specific_id:
                    try:
                        qrcode_obj = QuestionnaireQRCode.objects.select_for_update().get(
                            qr_code_id=specific_id,
                            questionnaire=questionnaire,
                            is_used=False
                        )
                        if not qrcode_obj.is_shared:
                            qrcode_obj.is_shared = True
                            qrcode_obj.save(update_fields=['is_shared'])
                    except QuestionnaireQRCode.DoesNotExist:
                        return JsonResponse({'ok': False, 'msg': '指定的二维码无效'}, status=400)
                else:
                    qrcode_obj = QuestionnaireQRCode.objects.select_for_update().filter(
                        questionnaire=questionnaire,
                        is_used=False,
                        is_shared=False
                    ).first()
                    if not qrcode_obj:
                        return JsonResponse({'ok': False, 'msg': '当前无可用的二维码，请稍后再试'}, status=400)

                request.session['bound_qrcode_id'] = qrcode_obj.qr_code_id

        if qrcode_obj:
            response.qrcode = qrcode_obj

        # 保存答案
        error = _save_answers(response, request, check_required=(action == 'submit'))
        if error:
            return JsonResponse({'ok': False, 'msg': error}, status=400)

        if action == 'submit':
            response.is_submitted = True
            response.save()

            questionnaire.submit_count += 1
            questionnaire.save()
            # ========== 检查停止条件 ==========
            stop_conditions = questionnaire.stop_condition
            if stop_conditions and isinstance(stop_conditions, list):
                # 按目标维护计数：target_counts[target_name][(question_id, option_index)] = count
                target_counts = {}
                trigger_info = []  # 存储所有触发的 (target_name, cond, answer)

                # 获取所有已提交答案（包含当前提交的），按时间排序
                answers = Answer.objects.filter(
                    response__questionnaire=questionnaire,
                    response__is_submitted=True
                ).select_related('question', 'response').order_by('response__submitted_at', 'id')

                for ans in answers:
                    target_name = ans.response.target_name or ''
                    q_id = str(ans.question.id)
                    if ans.question.question_type in ['radio', 'checkbox'] and ans.answer_text:
                        for letter in ans.answer_text:
                            option_index = ord(letter) - 65
                            for cond in stop_conditions:
                                if cond['question_id'] == q_id and cond['option_index'] == option_index:
                                    if target_name not in target_counts:
                                        target_counts[target_name] = {}
                                    key = (q_id, option_index)
                                    target_counts[target_name][key] = target_counts[target_name].get(key, 0) + 1
                                    if target_counts[target_name][key] >= cond['threshold']:
                                        # 检查是否已经记录过这个条件（避免重复）
                                        already_triggered = any(
                                            t[0] == target_name and t[1]['question_id'] == q_id and t[1][
                                                'option_index'] == option_index
                                            for t in trigger_info
                                        )
                                        if not already_triggered:
                                            trigger_info.append((target_name, cond, ans))
                    # 简答题类似扩展，如需支持可自行添加

                if trigger_info:
                    # 生成关闭原因
                    reasons = []
                    for target_name, cond, ans in trigger_info:
                        q_text = ans.question.text
                        option_text = ans.question.options[cond['option_index']]
                        reasons.append(f"评价目标“{target_name}”在问题“{q_text}”中选择了“{option_text}”")
                    # 假设所有触发条件的阈值相同（全局条件相同关键词的阈值一致），取最后一个的阈值
                    last_threshold = trigger_info[-1][1]['threshold']
                    close_reason = "，".join(reasons) + f"，使得该选项被选择次数达到{last_threshold}次"

                    questionnaire.status = 'closed'
                    questionnaire.closed_reason = close_reason
                    questionnaire.save(update_fields=['status', 'closed_reason'])
                    try:
                        from .notification_manager import NotificationManager
                        NotificationManager.create_notification(
                            user=questionnaire.creator,
                            title=f"问卷已自动关闭：{questionnaire.title}",
                            message=close_reason,
                            notification_type='system',
                            related_questionnaire=questionnaire,
                            priority='high'
                        )
                    except Exception as e:
                        logger.error(f"发送关闭通知失败: {e}")
            # ========== 停止条件检查结束 ==========
            try:
                from .notification_manager import NotificationManager
                NotificationManager.create_notification(
                    user=questionnaire.creator,
                    title=f"新答卷：{questionnaire.title}",
                    message="一位匿名用户提交了一份新答卷。",
                    notification_type='system',
                    related_questionnaire=questionnaire,
                    priority='normal'
                )
            except Exception as e:
                logger.error(f"发送新答卷通知失败: {e}")

            # Redis 缓存
            cache_key = f'survey:anon:{questionnaire.id}:{fingerprint}:v{questionnaire.version}'
            cache.set(cache_key, '1', timeout=60 * 60 * 24 * 30)

            # 检查是否全部完成
            if questionnaire.is_multi_target:
                submitted_targets = Response.objects.filter(
                    questionnaire=questionnaire,
                    device_fingerprint=fingerprint,
                    questionnaire_version=questionnaire.version,
                    is_submitted=True
                ).values_list('target_name', flat=True)
                all_completed = all(t in submitted_targets for t in questionnaire.targets)
                if all_completed and qrcode_obj:
                    qrcode_obj.is_used = True
                    qrcode_obj.used_by = None
                    qrcode_obj.used_at = timezone.now()
                    qrcode_obj.save(update_fields=['is_used', 'used_by', 'used_at'])
                    request.session.pop('bound_qrcode_id', None)

                redirect_url = reverse('survey_thank_you', args=[questionnaire.id]) if all_completed else reverse('multi_target_dashboard', args=[questionnaire.id])
            else:
                # 单目标/普通问卷：提交后立即标记二维码
                if qrcode_obj:
                    qrcode_obj.is_used = True
                    qrcode_obj.used_by = None
                    qrcode_obj.used_at = timezone.now()
                    qrcode_obj.save(update_fields=['is_used', 'used_by', 'used_at'])
                    # 发送 WebSocket 广播
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        f'questionnaire_{questionnaire.id}',
                        {
                            'type': 'qrcode_update',
                            'qr_code_id': qrcode_obj.qr_code_id,
                            'is_used': True,
                            'used_by': '匿名用户',
                            'used_at': timezone.now().isoformat(),
                            'response_id': str(response.id),
                        }
                    )
                redirect_url = reverse('questionnaire_detail', args=[questionnaire.id]) + f'?_={int(time.time())}'

            return JsonResponse({'ok': True, 'redirect': redirect_url})

        else:  # action == 'draft'
            response.is_submitted = False
            response.save()
            return JsonResponse({'ok': True, 'msg': '草稿已保存', 'redirect': None})

def survey_thank_you(request, survey_uuid):
    """感谢页面"""
    questionnaire = get_object_or_404(Questionnaire, id=survey_uuid)
    return render(request, 'questionnaire/already_submitted.html', {
        'questionnaire': questionnaire,
    })

# ===== 新增：多目标仪表盘视图 =====
def multi_target_dashboard(request, questionnaire_id):
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id, is_multi_target=True)

    can_access, reason = questionnaire.can_be_accessed_by(user=request.user)
    if not can_access:
        # 如果问卷已关闭且有具体关闭原因，使用 closed_reason 作为详细原因
        display_reason = questionnaire.closed_reason if (
                    questionnaire.status == 'closed' and questionnaire.closed_reason) else reason
        return render(request, 'questionnaire/not_available.html', {
            'questionnaire': questionnaire,
            'reason': display_reason
        })

    if not request.user.is_authenticated:
        if 'anon_fingerprint' not in request.session:
            import uuid
            request.session['anon_fingerprint'] = str(uuid.uuid4())

    # 确定用户标识
    if request.user.is_authenticated:
        user_filter = {'user': request.user}
        user_identifier = request.user.username
    else:
        fingerprint = request.session.get('anon_fingerprint')
        logger.debug(f"Dashboard: session fingerprint = {fingerprint}")
        if fingerprint:
            user_filter = {'device_fingerprint': fingerprint}
        else:
            user_filter = None
        user_identifier = '您'

    # 查询已提交和暂存的目标
    submitted_targets = []
    draft_targets = []
    if user_filter:
        submitted_targets = Response.objects.filter(
            questionnaire=questionnaire,
            questionnaire_version=questionnaire.version,
            is_submitted=True,
            **user_filter
        ).values_list('target_name', flat=True)

        draft_targets = Response.objects.filter(
            questionnaire=questionnaire,
            questionnaire_version=questionnaire.version,
            is_submitted=False,
            **user_filter
        ).values_list('target_name', flat=True)
        logger.debug(f"Dashboard: found draft targets = {list(draft_targets)}")

    # 构建状态列表
    targets_status = []
    for target in questionnaire.targets:
        status = 'not_started'
        if target in submitted_targets:
            status = 'submitted'
        elif target in draft_targets:
            status = 'draft'
        targets_status.append({
            'name': target,
            'status': status,
        })

    all_completed = all(t['status'] == 'submitted' for t in targets_status)
    has_any_draft = any(t['status'] == 'draft' for t in targets_status)

    context = {
        'questionnaire': questionnaire,
        'targets_status': targets_status,
        'all_completed': all_completed,
        'has_any_draft': has_any_draft,
        'is_authenticated': request.user.is_authenticated,
        'user_identifier': user_identifier,
    }
    return render(request, 'questionnaire/multi_target_dashboard.html', context)

# ===== 新增：批量提交视图 =====
@transaction.atomic
def handle_batch_submit(request, questionnaire_id):
    """批量提交当前用户所有暂存的答卷"""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'msg': '仅支持POST'}, status=405)

    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id, status='published')

    # 确定用户标识
    is_anonymous = not request.user.is_authenticated or request.POST.get('anonymous') == '1'
    if is_anonymous:
        fingerprint = request.POST.get('device_fingerprint', '') or request.session.get('anon_fingerprint')
        if not fingerprint:
            return JsonResponse({'ok': False, 'msg': '无法识别设备'}, status=400)
        filter_kwargs = {'device_fingerprint': fingerprint}
    else:
        filter_kwargs = {'user': request.user}

    # 获取所有未提交的暂存答卷（当前版本）
    drafts = Response.objects.filter(
        questionnaire=questionnaire,
        questionnaire_version=questionnaire.version,
        is_submitted=False,
        **filter_kwargs
    ).select_for_update()

    if not drafts.exists():
        return JsonResponse({'ok': False, 'msg': '没有可提交的草稿'}, status=400)

    # 检查每个暂存答卷的必填问题是否都已答
    for resp in drafts:
        required_questions = questionnaire.questions.filter(required=True)
        answered_questions = Answer.objects.filter(response=resp, question__in=required_questions)
        if answered_questions.count() != required_questions.count():
            missing = required_questions.exclude(id__in=answered_questions.values('question_id')).first()
            return JsonResponse({
                'ok': False,
                'msg': f'目标“{resp.target_name}”还有必填问题未回答，请先完成。'
            }, status=400)

    # 批量标记为提交
    now = timezone.now()
    for resp in drafts:
        resp.is_submitted = True
        resp.save(update_fields=['is_submitted'])

    # 更新问卷提交计数
    questionnaire.submit_count += drafts.count()
    questionnaire.save(update_fields=['submit_count'])

    # 检查是否全部完成
    submitted_targets = Response.objects.filter(
        questionnaire=questionnaire,
        is_submitted=True,
        **filter_kwargs
    ).values_list('target_name', flat=True)
    all_completed = all(t in submitted_targets for t in questionnaire.targets)

    # 如果全部完成，标记对应的二维码
    if all_completed:
        first_response = drafts.first()
        if first_response and first_response.qrcode:
            qrcode = first_response.qrcode
            qrcode.is_used = True
            qrcode.used_by = request.user if request.user.is_authenticated else None
            qrcode.used_at = now
            qrcode.save(update_fields=['is_used', 'used_by', 'used_at'])

    redirect_url = reverse('survey_thank_you', args=[questionnaire.id]) if all_completed else reverse('multi_target_dashboard', args=[questionnaire.id])
    return JsonResponse({'ok': True, 'redirect': redirect_url})