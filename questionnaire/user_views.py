from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone
from django.urls import reverse
from django.db import transaction
from django.core.cache import cache
from django.db import IntegrityError
from django.utils.dateparse import parse_datetime
import json
import uuid  # 新增导入
from .models import Questionnaire, Response, Question, Answer, QuestionnaireQRCode  # 新增导入 QuestionnaireQRCode
from .sm4 import sm4_encode
from django.db.models import F

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
    target = request.GET.get('target')
    if questionnaire.is_multi_target:
        # 没有指定目标 -> 跳转仪表盘
        if not target:
            return redirect('multi_target_dashboard', questionnaire_id=questionnaire.id)
        # 验证目标有效性
        if target not in questionnaire.targets:
            messages.error(request, '无效的评价目标')
            return redirect('multi_target_dashboard', questionnaire_id=questionnaire.id)

        # 检查该目标是否已提交（最终提交）
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
        current_target = None

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
                        indices = [ord(letter) - 65 for letter in letters if letter]
                        answers_dict[qid] = indices
                    elif ans.question.question_type == 'radio':
                        letter = ans.answer_text
                        if letter:
                            answers_dict[qid] = ord(letter) - 65
                    else:
                        answers_dict[qid] = ans.answer_text
            except Response.DoesNotExist:
                pass

        context = {
            'questionnaire': questionnaire,
            'questions': questionnaire.questions.all().order_by('order'),
            'submitted': submitted,
            'debug_check': debug_check,
            'record_count': record_count,
            'has_old_version_submission': has_old_version_submission,
            'questionnaire_version': questionnaire.version,
            'latest_old_version': latest_old_version,
            'current_target': current_target,  # 新增
            'answers_dict': json.dumps(answers_dict),  # 新增
            'anonymous_fingerprint': None,  # 新增
        }
        return render(request, 'questionnaire/form.html', context)

    else:
        answers_dict = {}
        if questionnaire.is_multi_target and current_target:
            fingerprint = request.session.get('anon_fingerprint')
            if fingerprint:
                try:
                    draft = Response.objects.get(
                        questionnaire=questionnaire,
                        questionnaire_version=questionnaire.version,
                        target_name=current_target,
                        is_submitted=False,
                        device_fingerprint=fingerprint
                    )
                    for ans in draft.answer_items.select_related('question'):
                        qid = ans.question.id
                        if ans.question.question_type == 'checkbox':
                            letters = ans.answer_text.split(',')
                            indices = [ord(letter) - 65 for letter in letters if letter]
                            answers_dict[qid] = indices
                        elif ans.question.question_type == 'radio':
                            letter = ans.answer_text
                            if letter:
                                answers_dict[qid] = ord(letter) - 65
                        else:
                            answers_dict[qid] = ans.answer_text
                except Response.DoesNotExist:
                    pass

        anonymous_fingerprint = request.session.get('anon_fingerprint')
        if not anonymous_fingerprint:
            anonymous_fingerprint = str(uuid.uuid4())
            request.session['anon_fingerprint'] = anonymous_fingerprint
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

    # ===== 新增：获取 action 参数 =====
    action = request.POST.get('action', 'submit')  # 'draft' 或 'submit'
    is_anonymous_mode = request.POST.get('anonymous') == '1'
    # ===== 新增结束 =====

    # ========== 登录用户分支 ==========
    if request.user.is_authenticated:
        with transaction.atomic():
            # 锁定问卷行，防止并发提交
            questionnaire = Questionnaire.objects.select_for_update().get(pk=questionnaire_id)

            # ===== 修改：仅当最终提交时执行时间和份数检查 =====
            if action == 'submit':
                now = timezone.now()
                if questionnaire.end_time and now > questionnaire.end_time:
                    return JsonResponse({'success': False, 'error': '问卷已截止'}, status=400)
                if questionnaire.limit_responses and questionnaire.max_responses is not None:
                    if questionnaire.submit_count >= questionnaire.max_responses:
                        return JsonResponse({'success': False, 'error': '问卷已达到收集上限'}, status=400)

                # 检查是否已提交当前版本（最终提交）
                if Response.objects.filter(
                        questionnaire=questionnaire,
                        user=request.user,
                        questionnaire_version=questionnaire.version,
                        is_submitted=True
                ).exists():
                    return JsonResponse({'success': False, 'error': '您已提交过当前版本'})
            # ===== 修改结束 =====

            # ===== 新增：获取目标名称 =====
            target_name = request.POST.get('target_name', '')
            if not target_name:
                target_name = request.session.pop('selected_target', '') if questionnaire.targets else ''
            # ===== 新增结束 =====

            # ===== 新增：查找或创建暂存记录 =====
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
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    questionnaire_version=questionnaire.version,
                    target_name=target_name,
                    is_submitted=False,
                    user_id=request.user.id,
                    questionnaire_id=questionnaire.id,
                )
            # 确保 response 有主键
            response.save()
            # ===== 新增结束 =====

            # 计算完成时间（原有逻辑）
            start_time = request.session.get('start_time')
            completion_time = None
            if start_time:
                start = timezone.datetime.fromisoformat(start_time)
                if start.tzinfo is None:
                    start = timezone.make_aware(start, timezone.get_current_timezone())
                completion_time = int((timezone.now() - start).total_seconds())
                response.completion_time = completion_time  # 新增：赋值

            # ===== 新增：使用 _save_answers 保存答案 =====
            error = _save_answers(response, request, check_required=(action == 'submit'))
            if error:
                return JsonResponse({'success': False, 'error': error})
            # ===== 新增结束 =====

            # ===== 新增：二维码处理 =====
            qrcode_obj = None
            if questionnaire.enable_multi_qrcodes:
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
                        return JsonResponse({'success': False, 'error': '指定的二维码无效或已被使用'}, status=400)
                else:
                    qrcode_obj = QuestionnaireQRCode.objects.select_for_update().filter(
                        questionnaire=questionnaire,
                        is_used=False,
                        is_shared=False
                    ).first()
                    if not qrcode_obj:
                        return JsonResponse({'success': False, 'error': '当前无可用的二维码，请稍后再试'}, status=400)

            if qrcode_obj:
                response.qrcode = qrcode_obj
                # 不立即标记 is_used，等待全部完成后标记
            # ===== 新增结束 =====

            # ===== 修改：根据 action 执行不同操作 =====
            if action == 'submit':
                response.is_submitted = True
                response.save()

                # 原子递增提交计数
                questionnaire.submit_count += 1
                questionnaire.save(update_fields=['submit_count'])

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
                        qrcode_obj.is_used = True
                        qrcode_obj.used_by = request.user
                        qrcode_obj.used_at = timezone.now()
                        qrcode_obj.save(update_fields=['is_used', 'used_by', 'used_at'])

                        # 发送 WebSocket 广播
                        from channels.layers import get_channel_layer
                        from asgiref.sync import async_to_sync
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
                    redirect_url = reverse('questionnaire_detail', args=[questionnaire.id])
                # ===== 新增结束 =====

                messages.success(request, '问卷提交成功！')
                return JsonResponse({'success': True, 'response_id': str(response.id), 'redirect': redirect_url})

            else:  # action == 'draft'
                response.is_submitted = False
                response.save()
                return JsonResponse({'success': True, 'msg': '草稿已保存'})
            # ===== 修改结束 =====

    # ========== 匿名用户分支 ==========
    else:
        fingerprint = request.POST.get('device_fingerprint', '').strip()
        if not fingerprint or len(fingerprint) < 32:
            return JsonResponse({'success': False, 'error': '无法识别设备，请刷新页面重试'})

        # ===== 修改：仅当最终提交时检查缓存和已提交记录 =====
        if action == 'submit':
            cache_key = f'survey:anon:{questionnaire.id}:{fingerprint}:v{questionnaire.version}'
            if cache.get(cache_key):
                return JsonResponse({'success': False, 'error': '您已提交过当前版本'})

            if Response.objects.filter(
                questionnaire=questionnaire,
                device_fingerprint=fingerprint,
                questionnaire_version=questionnaire.version
            ).exists():
                return JsonResponse({'success': False, 'error': '您已提交过当前版本'})
        # ===== 修改结束 =====

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

                # ===== 新增：仅当最终提交时执行时间和份数检查 =====
                if action == 'submit':
                    now = timezone.now()
                    if questionnaire.end_time and now > questionnaire.end_time:
                        return JsonResponse({'success': False, 'error': '问卷已截止'}, status=400)
                    if questionnaire.limit_responses and questionnaire.max_responses is not None:
                        if questionnaire.submit_count >= questionnaire.max_responses:
                            return JsonResponse({'success': False, 'error': '问卷已达到收集上限'}, status=400)
                # ===== 新增结束 =====

                # ===== 新增：目标处理 =====
                target_name = ''
                if questionnaire.is_multi_target:
                    target_name = request.POST.get('target_name', '').strip()
                    if target_name:
                        if target_name not in questionnaire.targets:
                            return JsonResponse({'success': False, 'error': '无效的目标'}, status=400)
                        if action == 'submit':
                            # 提交时检查该目标是否已提交
                            if Response.objects.filter(
                                    questionnaire=questionnaire,
                                    device_fingerprint=fingerprint,
                                    questionnaire_version=questionnaire.version,
                                    target_name=target_name,
                                    is_submitted=True
                            ).exists():
                                return JsonResponse({'success': False, 'error': f'您已评价过目标“{target_name}”'}, status=403)
                # ===== 新增结束 =====

                # ===== 新增：查找或创建暂存记录 =====
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
                response.save()
                # ===== 新增结束 =====

                # 计算完成时间（保留）
                response.completion_time = completion_time

                # ===== 新增：二维码处理 =====
                qrcode_obj = None
                if questionnaire.enable_multi_qrcodes:
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
                            return JsonResponse({'success': False, 'error': '指定的二维码无效'}, status=400)
                    else:
                        qrcode_obj = QuestionnaireQRCode.objects.select_for_update().filter(
                            questionnaire=questionnaire,
                            is_used=False,
                            is_shared=False
                        ).first()
                        if not qrcode_obj:
                            return JsonResponse({'success': False, 'error': '当前无可用的二维码，请稍后再试'}, status=400)

                if qrcode_obj:
                    response.qrcode = qrcode_obj
                # ===== 新增结束 =====

                # ===== 新增：使用 _save_answers 保存答案 =====
                error = _save_answers(response, request, check_required=(action == 'submit'))
                if error:
                    return JsonResponse({'success': False, 'error': error})
                # ===== 新增结束 =====

                if action == 'submit':
                    response.is_submitted = True
                    response.save()

                    # 原子递增提交计数
                    questionnaire.submit_count += 1
                    questionnaire.save(update_fields=['submit_count'])

                    # ===== 新增：检查是否全部完成（多目标）=====
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

                        redirect_url = reverse('survey_thank_you', args=[questionnaire.id]) if all_completed else reverse('multi_target_dashboard', args=[questionnaire.id])
                    else:
                        redirect_url = reverse('questionnaire_detail', args=[questionnaire.id])
                    # ===== 新增结束 =====

                    cache_key = f'survey:anon:{questionnaire.id}:{fingerprint}:v{questionnaire.version}'
                    cache.set(cache_key, '1', timeout=60*60*24*30)
                    return JsonResponse({'success': True, 'response_id': str(response.id), 'redirect': redirect_url})

                else:  # action == 'draft'
                    response.is_submitted = False
                    response.save()
                    return JsonResponse({'success': True, 'msg': '草稿已保存'})

        except IntegrityError:
            transaction.set_rollback(True)
            return JsonResponse({'success': False, 'error': '您已提交过当前版本'})
        except Exception as e:
            transaction.set_rollback(True)
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

def multi_target_dashboard(request, questionnaire_id):
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id, status='published', is_multi_target=True)

    can_access, reason = questionnaire.can_be_accessed_by(user=request.user)
    if not can_access:
        messages.error(request, reason)
        return redirect('home')

    # 确定用户标识
    if request.user.is_authenticated:
        user_filter = {'user': request.user}
        user_identifier = request.user.username
    else:
        fingerprint = request.session.get('anon_fingerprint')
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