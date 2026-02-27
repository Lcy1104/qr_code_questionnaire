# questionnaire/views_survey.py
import logging
import time
from django.views.decorators.cache import never_cache
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Questionnaire, Response, Answer, QuestionnaireQRCode
from .notification_manager import NotificationManager

logger = logging.getLogger(__name__)

def survey_landing(request, survey_uuid):
    """
    问卷引导页 - 扫码后直接访问
    任何用户都能访问，用于展示问卷信息和引导登录
    """
    questionnaire = get_object_or_404(Questionnaire, id=survey_uuid, status='published')

    if questionnaire.status != 'published':
        return render(request, 'questionnaire/not_available.html', {
            'questionnaire': questionnaire,
            'reason': '问卷未发布' if questionnaire.status == 'draft' else '问卷已结束'
        })


    context = {
        'questionnaire': questionnaire,
        'user_is_authenticated': request.user.is_authenticated,
    }

    context['anonymous_url'] = reverse('survey_form', args=[survey_uuid]) + '?anonymous=1'

    if request.user.is_authenticated:
        # 已登录用户：显示“开始填写”按钮
        context['start_url'] = reverse('survey_form', args=[survey_uuid])
    else:
        # 未登录用户：显示登录、注册、匿名填写按钮
        context['login_url'] = reverse('login') + f'?next={reverse("survey_form", args=[survey_uuid])}'
        context['register_url'] = reverse('register') + f'?next={reverse("survey_form", args=[survey_uuid])}'

    return render(request, 'questionnaire/landing.html', context)

@never_cache
def survey_fill(request, survey_uuid):
    questionnaire = get_object_or_404(Questionnaire, id=survey_uuid, status='published')

    # 公共检查（邀请码）
    if questionnaire.access_type == 'invite':
        if 'valid_invite_code' not in request.session or ...:
            return redirect('survey_landing', survey_uuid=survey_uuid)

    # 判断是否为匿名模式（通过 URL 参数 ?anonymous=1 触发）
    is_anonymous_mode = request.GET.get('anonymous') == '1'

    # 未登录且非匿名模式，重定向到引导页（由引导页决定登录或匿名）
    if not request.user.is_authenticated and not is_anonymous_mode:
        return redirect('survey_landing', survey_uuid=survey_uuid)

    if request.user.is_authenticated and not is_anonymous_mode:
        # 已登录且非匿名模式：正常登录用户填写
        if Response.objects.filter(questionnaire=questionnaire, user=request.user).exists():
            return render(request, 'questionnaire/already_submitted.html', {
                'questionnaire': questionnaire
            })
        questions = questionnaire.questions.all().order_by('order').values(
            'id', 'text', 'question_type', 'options', 'required', 'max_length'
        )
        return render(request, 'questionnaire/fill.html', {
            'questionnaire': questionnaire,
            'questions': questions,
            'is_anonymous_mode': False,
        })
    else:
        # 匿名模式（包括未登录用户或已登录但选择匿名）
        questions = questionnaire.questions.all().order_by('order').values(
            'id', 'text', 'question_type', 'options', 'required', 'max_length'
        )
        return render(request, 'questionnaire/fill.html', {
            'questionnaire': questionnaire,
            'questions': questions,
            'is_anonymous_mode': True,  # 传递标志给模板，以便在表单中添加隐藏字段
        })

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

    is_anonymous_mode = request.POST.get('anonymous') == '1'

    if request.user.is_authenticated and not is_anonymous_mode:
        logger.debug(f'request.POST = {dict(request.POST)}')
        now = timezone.now()
        if questionnaire.end_time and now > questionnaire.end_time:
            return JsonResponse({'ok': False, 'msg': '问卷已截止'}, status=400)
        if questionnaire.limit_responses and questionnaire.max_responses is not None:
            if questionnaire.submit_count >= questionnaire.max_responses:
                return JsonResponse({'ok': False, 'msg': '问卷已达到收集上限'}, status=400)

        if Response.objects.filter(
                questionnaire=questionnaire,
                user=request.user,
                questionnaire_version=questionnaire.version).exists():
            return JsonResponse({'ok': False, 'msg': '您已提交过当前版本'})

        submitted_at = timezone.now()
        logger.debug(f'Submitted at: {submitted_at}')

        start_str = request.POST.get('start_time')
        logger.debug(f'start_time 从 POST 获取 = {start_str}')

        completion_time = None
        if start_str:
            try:
                start = parse_datetime(start_str)
                if start.tzinfo is None or start.tzinfo.utcoffset(start) is None:
                    start = timezone.make_aware(start, timezone.utc)
                start = start.astimezone(timezone.get_default_timezone())
                submitted_at = submitted_at.astimezone(timezone.get_default_timezone())
                completion_time = int((submitted_at - start).total_seconds())
            except Exception as e:
                logger.error(f'计算 completion_time 异常: {e}')
        else:
            logger.warning("start_time 为空，无法计算 completion_time")

        logger.debug(f'completion_time 秒数 = {completion_time}')

        response = Response.objects.create(
            questionnaire=questionnaire,
            user=request.user,
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:200],
            is_submitted=True,
            questionnaire_version=questionnaire.version,
            completion_time=completion_time
        )
        logger.debug(f'已保存 Response id={response.id} completion_time 值={response.completion_time}')
        qrcode_obj = None
        if questionnaire.enable_multi_qrcodes:
            specific_id = request.session.pop('active_qrcode_id', None)
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

        if qrcode_obj:
            qrcode_obj.mark_as_used(user=request.user)
            response.qrcode = qrcode_obj
            response.save(update_fields=['qrcode'])

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
        for q in questionnaire.questions.all():
            key = f'question_{q.id}'
            raw = request.POST.get(f'maxlen_{q.id}', '0').strip()
            q.max_length = int(raw) if raw.isdigit() else 0
            q.save(update_fields=['max_length'])
            if q.question_type == 'text':
                val = request.POST.get(key, '').strip()
                if val:
                    ans = Answer(response=response, question=q, answer_text=val)
                    ans.full_clean()
                    ans.save()
                    logger.debug(f'Answer 创建 id={ans.id} text={val}')
            elif q.question_type == 'radio':
                val = request.POST.get(key, '').strip()
                if val:
                    if not val.isdigit():
                        return JsonResponse({'ok': False, 'msg': '单选参数异常'}, status=400)
                    opt_idx = int(val)
                    if opt_idx < 0 or opt_idx >= len(q.options):
                        return JsonResponse({'ok': False, 'msg': '选项超出范围'}, status=400)
                    selected_option = chr(65 + opt_idx)
                    ans = Answer.objects.create(
                        response=response,
                        question=q,
                        answer_text=selected_option
                    )
                    logger.debug(f'Answer 创建 id={ans.id} single={selected_option}')
                elif q.required:
                    return JsonResponse({'ok': False, 'msg': f'问题"{q.text}"是必选题，请选择一个选项'}, status=400)
                #logger.debug(f'Answer 创建 id={ans.id} single={selected_option}')
            elif q.question_type == 'checkbox':
                vals = request.POST.getlist(key)
                selected_options = []
                for v in vals:
                    if not v.isdigit():
                        return JsonResponse({'ok': False, 'msg': '多选参数异常'}, status=400)
                    opt_idx = int(v)
                    if opt_idx < 0 or opt_idx >= len(q.options):
                        return JsonResponse({'ok': False, 'msg': '选项超出范围'}, status=400)
                    selected_option = chr(65 + opt_idx)
                    selected_options.append(selected_option)
                if selected_options:
                    answer_text = ','.join(selected_options)
                    ans = Answer.objects.create(
                        response=response,
                        question=q,
                        answer_text=answer_text
                    )
                    logger.debug(f'Answer 创建 id={ans.id} multi={answer_text}')
                elif q.required:
                    return JsonResponse({'ok': False, 'msg': f'问题"{q.text}"是必选题，请至少选择一个选项'}, status=400)
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
        redirect_url = reverse('questionnaire_detail', args=[questionnaire.id]) + f'?_={int(time.time())}'
        return JsonResponse({'ok': True, 'redirect': redirect_url})

    # ========== 匿名用户分支：新增，完全独立 ==========
    else:
        from django.core.cache import cache
        from django.db import IntegrityError

        # 1. 设备指纹验证（FingerprintJS 生成32位十六进制，要求≥16即可）
        fingerprint = request.POST.get('device_fingerprint', '').strip()
        if not fingerprint or len(fingerprint) < 16:
            logger.warning(f'匿名提交失败：无效指纹，长度={len(fingerprint)}')
            return JsonResponse({'ok': False, 'msg': '无法识别设备，请刷新页面重试'}, status=400)

        # 2. Redis 快速拦截
        cache_key = f'survey:anon:{questionnaire.id}:{fingerprint}:v{questionnaire.version}'
        if cache.get(cache_key):
            return JsonResponse({'ok': False, 'msg': '您已提交过当前版本'}, status=403)

        now = timezone.now()
        if questionnaire.end_time and now > questionnaire.end_time:
            return JsonResponse({'ok': False, 'msg': '问卷已截止'}, status=400)
        if questionnaire.limit_responses and questionnaire.max_responses is not None:
            if questionnaire.submit_count >= questionnaire.max_responses:
                return JsonResponse({'ok': False, 'msg': '问卷已达到收集上限'}, status=400)

        # 3. 数据库检查
        if Response.objects.filter(
            questionnaire=questionnaire,
            device_fingerprint=fingerprint,
            questionnaire_version=questionnaire.version
        ).exists():
            return JsonResponse({'ok': False, 'msg': '您已提交过当前版本'}, status=403)

        # 4. 计算完成时间
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
            except Exception as e:
                logger.error(f'匿名计算 completion_time 异常: {e}')

        try:
            with transaction.atomic():
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

                qrcode_obj = None
                if questionnaire.enable_multi_qrcodes:
                    specific_id = request.session.pop('active_qrcode_id', None)
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

                if qrcode_obj:
                    qrcode_obj.mark_as_used(user=None)
                    response.qrcode = qrcode_obj
                    response.save(update_fields=['qrcode'])

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
                # 5. 保存答案（严格缩进，与登录逻辑一致）
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
                    elif q.question_type == 'radio':
                        val = request.POST.get(key, '').strip()
                        if val:
                            if not val.isdigit():
                                return JsonResponse({'ok': False, 'msg': '单选参数异常'}, status=400)
                            opt_idx = int(val)
                            if opt_idx < 0 or opt_idx >= len(q.options):
                                return JsonResponse({'ok': False, 'msg': '选项超出范围'}, status=400)
                            selected_option = chr(65 + opt_idx)
                            Answer.objects.create(response=response, question=q, answer_text=selected_option)
                        elif q.required:
                            return JsonResponse({'ok': False, 'msg': f'问题"{q.text}"是必选题，请选择一个选项'},
                                                status=400)
                    elif q.question_type == 'checkbox':
                        vals = request.POST.getlist(key)
                        selected_options = []
                        for v in vals:
                            if not v.isdigit():
                                return JsonResponse({'ok': False, 'msg': '多选参数异常'}, status=400)
                            opt_idx = int(v)
                            if opt_idx < 0 or opt_idx >= len(q.options):
                                return JsonResponse({'ok': False, 'msg': '选项超出范围'}, status=400)
                            selected_option = chr(65 + opt_idx)
                            selected_options.append(selected_option)
                        if selected_options:
                            answer_text = ','.join(selected_options)
                            Answer.objects.create(response=response, question=q, answer_text=answer_text)
                        elif q.required:
                            return JsonResponse({'ok': False, 'msg': f'问题"{q.text}"是必选题，请至少选择一个选项'}, status=400)

                questionnaire.submit_count += 1
                questionnaire.save()
            try:
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
            # 6. Redis 缓存（30天）
            cache.set(cache_key, '1', timeout=60*60*24*30)
            redirect_url = reverse('questionnaire_detail', args=[questionnaire.id]) + f'?_={int(time.time())}'
            return JsonResponse({'ok': True, 'redirect': redirect_url})

        except IntegrityError:
            return JsonResponse({'ok': False, 'msg': '您已提交过当前版本'}, status=403)
        except Exception as e:
            logger.exception("匿名问卷提交异常")
            return JsonResponse({'ok': False, 'msg': f'提交失败: {str(e)}'}, status=500)


def survey_thank_you(request, survey_uuid):
    """感谢页面"""
    questionnaire = get_object_or_404(Questionnaire, id=survey_uuid)
    return render(request, 'questionnaire/already_submitted.html', {
        'questionnaire': questionnaire
    })
