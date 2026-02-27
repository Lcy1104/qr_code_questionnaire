# questionnaire/dashboard_views.py
from django.contrib import messages
from django.views.decorators.cache import never_cache
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db import connection
from django.views.decorators.http import require_POST
from .decorators import original_admin_required
from .forms import QuestionnaireForm, QuestionFormSet
from .models import User, Questionnaire, Response
from django.http import HttpResponse
from django.urls import reverse
from django.http import JsonResponse
import json
from .models import Question
import logging
from django.db.models import Count
from .notification_manager import NotificationManager
from .cache import get_detail_cache_key, clear_questionnaire_cache
from django.core.cache import cache
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .views_qrcode import generate_qrcode_for_questionnaire, generate_multi_qrcodes_for_questionnaire
from django.views.decorators.http import require_GET
import time
from django.db import connection

logger = logging.getLogger('questionnaire')
def admin_required(view_func):
    """管理员权限装饰器"""
    from functools import wraps

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_admin:
            return view_func(request, *args, **kwargs)
        messages.error(request, '需要管理员权限')
        return redirect('dashboard')

    return wrapper


@login_required
def dashboard(request):
    """统一仪表盘"""
    user = request.user

    # 获取当前时间
    today = timezone.now()

    if user.is_superuser:
        # 管理员统计
        total_users = User.objects.count()
        total_questionnaires = Questionnaire.objects.count()
        total_responses = Response.objects.count()
        published_questionnaires = Questionnaire.objects.filter(status='published').count()

        # 最近问卷
        recent_questionnaires = Questionnaire.objects.all().order_by('-created_at')[:5]
        recent_responses = Response.objects.all().select_related('questionnaire', 'user').order_by('-submitted_at')[:5]

        context = {
            'total_users': total_users,
            'total_questionnaires': total_questionnaires,
            'published_questionnaires': published_questionnaires,
            'total_responses': total_responses,
            'today': today,
            'recent_questionnaires': recent_questionnaires,
            'recent_responses': recent_responses,
            'recent_questionnaires': recent_questionnaires,
            'recent_responses': recent_responses,
            'is_admin': True
        }
    else:
        # 普通用户统计
        my_questionnaires = Questionnaire.objects.filter(creator=user).count()
        published_questionnaires = Questionnaire.objects.filter(creator=user, status='published').count()
        my_responses_count = Response.objects.filter(user=user).count()

        # 最近问卷
        recent_questionnaires = Questionnaire.objects.filter(creator=user).order_by('-created_at')[:5]
        recent_responses = Response.objects.filter(user=user).select_related('questionnaire').order_by('-submitted_at')[
                           :5]

        context = {
            'total_questionnaires': my_questionnaires,
            'published_questionnaires': published_questionnaires,
            'total_responses': my_responses_count,
            'today': today,
            'recent_questionnaires': recent_questionnaires,
            'recent_responses': recent_responses,
            'recent_questionnaires': recent_questionnaires,
            'recent_responses': recent_responses,
            'is_admin': False
        }

    return render(request, 'dashboard/index.html', context)

def get_derived_statuses(questionnaire, now):
    """计算问卷的派生状态列表，每个元素为 (bootstrap颜色类, 显示文本)"""
    statuses = []

    # 1. 手动状态优先级最高（已关闭、草稿、已修改）
    if questionnaire.status == 'closed':
        statuses.append(('danger', '已关闭'))
    elif questionnaire.status == 'draft':
        statuses.append(('secondary', '草稿'))
    elif questionnaire.status == 'modified':
        statuses.append(('warning', '已修改'))
    elif questionnaire.status == 'published':
        # 已发布问卷，检查自动条件
        # 待开始
        if questionnaire.start_time and questionnaire.start_time > now:
            statuses.append(('info', '待开始'))
        # 已结束（截止时间已过）
        if questionnaire.end_time and questionnaire.end_time < now:
            statuses.append(('dark', '已结束'))
        # 已满（提交数达到上限）
        if questionnaire.limit_responses and questionnaire.resp_cnt >= questionnaire.max_responses:
            statuses.append(('danger', '已满'))
        # 如果没有任何自动状态，显示“已发布”
        if not statuses:
            statuses.append(('success', '已发布'))

    return statuses

@login_required
def questionnaire_list(request):
    """问卷列表"""
    if request.user.is_superuser:
        questionnaires = Questionnaire.objects.all().order_by('-created_at')
    else:
        questionnaires = Questionnaire.objects.filter(creator=request.user).order_by('-created_at')

    status = request.GET.get('status')
    has_inv = request.GET.get('has_invite')
    has_resp = request.GET.get('has_response')

    if status:
        questionnaires = questionnaires.filter(status=status)
    if has_inv in ('0', '1'):
        questionnaires = questionnaires.filter(invite_code__isnull=(has_inv == '0'))
    questionnaires = questionnaires.annotate(resp_cnt=Count('responses', distinct=True))
    if has_resp in ('0', '1'):
        questionnaires = questionnaires.annotate(resp_cnt=Count('responses'))
        questionnaires = questionnaires.filter(resp_cnt__gt=0) if has_resp == '1' else questionnaires.filter(resp_cnt=0)
    questionnaires = questionnaires.order_by('-created_at')
    now = timezone.now()
    for q in questionnaires:
        q.derived_statuses = get_derived_statuses(q, now)
    return render(request, 'questionnaire/list.html', {
        'questionnaires': questionnaires,
        'is_admin': request.user.is_superuser,  # 关键：使用 is_superuser
        'now': now,
    })

def save_questions_from_post(request, questionnaire):
    """从POST数据保存问题"""
    question_count = 0

    # 动态查找所有问题
    for key in request.POST:
        if key.startswith('questions-') and key.endswith('-text'):
            try:
                # 提取索引，如 'questions-0-text' -> '0'
                prefix = key.replace('questions-', '').replace('-text', '')

                text = request.POST.get(key, '').strip()
                if not text:
                    continue

                # 获取其他字段
                question_type = request.POST.get(f'questions-{prefix}-question_type', 'radio')
                required = request.POST.get(f'questions-{prefix}-required') == 'on'

                # 创建问题对象
                question = Question(
                    questionnaire=questionnaire,
                    text=text,
                    question_type=question_type,
                    order=question_count + 1,
                    required=required
                )

                # 处理选择题选项
                if question_type in ['radio', 'checkbox']:
                    options_text = request.POST.get(f'questions-{prefix}-options_text', '').strip()

                    if options_text:
                        options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
                    else:
                        options = ['选项1', '选项2']

                    # 保存选项（根据字段类型）
                    question.options = json.dumps(options, ensure_ascii=False)

                # 处理简答题字数限制
                elif question_type == 'text':
                    max_length_field = request.POST.get(f'questions-{prefix}-max_length', '0').strip()
                    logger.info(f"[CREATE] 简答题 {question_count + 1}: max_length_field = {max_length_field}")
                    try:
                        max_length = int(max_length_field)
                    except:
                        max_length = 0
                    question.max_length = max_length
                    logger.info(f"[CREATE] 简答题 {question_count + 1}: 设置 max_length = {max_length}")

                # 保存问题
                question.save()
                question_count += 1

            except Exception as e:
                print(f"保存问题失败: {e}")
                continue

    return question_count
@login_required
def create_questionnaire(request):
    """创建问卷"""
    if request.method == 'POST':
        form = QuestionnaireForm(request.POST)

        # 不再使用 QuestionFormSet，而是直接处理 POST 数据
        if form.is_valid():
            # 保存问卷
            questionnaire = form.save(commit=False)
            questionnaire.creator = request.user

            # 获取保存动作
            save_action = request.POST.get('save_action', 'save_draft')

            if save_action == 'save_and_publish':
                # 发布问卷
                questionnaire.status = 'published'
                questionnaire.published_at = timezone.now()

                # 生成邀请码（如果需要）
                if questionnaire.access_type == 'invite' and not questionnaire.invite_code:
                    import secrets
                    import string
                    alphabet = string.ascii_uppercase + string.digits
                    questionnaire.invite_code = ''.join(secrets.choice(alphabet) for i in range(8))

                # 保存问卷
                questionnaire.save()

                # 保存问题
                question_count = save_questions_from_post(request, questionnaire)

                if question_count == 0:
                    messages.error(request, '发布问卷必须至少有一个问题')
                    questionnaire.delete()  # 删除空问卷
                    return render(request, 'questionnaire/create.html', {'form': form})

                from .views_qrcode import generate_qrcode_for_questionnaire, generate_multi_qrcodes_for_questionnaire
                if questionnaire.enable_multi_qrcodes:
                    generate_multi_qrcodes_for_questionnaire(request, questionnaire)
                else:
                    generate_qrcode_for_questionnaire(request, questionnaire)

                has_available_qrcode = True
                if questionnaire.enable_multi_qrcodes:
                    has_available_qrcode = questionnaire.qrcodes.filter(is_used=False).exists()

                clear_questionnaire_cache(questionnaire)
                request.session['just_created'] = str(questionnaire.id)
                request.session.modified = True

                questions_data = list(questionnaire.questions.all().order_by('order').values(
                    'id', 'text', 'question_type', 'options', 'required', 'max_length', 'order'
                ))
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'questionnaire_{questionnaire.id}',
                    {
                        'type': 'questionnaire_updated',
                        'questionnaire_id': str(questionnaire.id),
                        'has_available_qrcode': has_available_qrcode,
                        'questions': questions_data,  # 新增
                        'submit_count': 0,  # 新增，刚创建为0
                        'user_has_submitted': False,  # 新增，创建者未提交
                    }
                )
                messages.success(request, '问卷已发布！')
                # 重定向到二维码页面
                from .views_qrcode import generate_qrcode
                # 发布后跳转到问卷详情页
                #return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)
                response = redirect('questionnaire_redirect_wait', questionnaire_id=questionnaire.id)
                response.set_cookie('just_created', str(questionnaire.id), max_age=10)  # 10秒内有效
                return response
            else:
                # 保存为草稿
                questionnaire.status = 'draft'
                questionnaire.save()

                # 保存问题
                save_questions_from_post(request, questionnaire)

                messages.success(request, '问卷已保存为草稿！')
                return redirect('questionnaire_list')
        else:
            # 表单验证失败
            messages.error(request, '表单验证失败，请检查填写内容')
    else:
        form = QuestionnaireForm()

    return render(request, 'questionnaire/create.html', {
        'form': form,
        'is_admin': request.user.is_admin
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
            return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)
    else:
        form = QuestionnaireForm(instance=questionnaire)
        question_formset = QuestionFormSet(instance=questionnaire)

    return render(request, 'questionnaire/edit.html', {
        'questionnaire': questionnaire,
        'form': form,
        'question_formset': question_formset,
        'is_admin': request.user.is_admin
    })


@login_required
@never_cache
def questionnaire_detail(request, questionnaire_id):
    # 强制关闭当前连接，下次数据库操作将使用新连接
    from django.db import connection
    connection.close()

    # 获取问卷对象（此时已使用新连接）
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 检查权限
    if not request.user.is_admin and questionnaire.creator != request.user:
        messages.error(request, '没有权限查看此问卷')
        return redirect('questionnaire_list')

    # 尝试从缓存获取动态数据（保持不变）
    cache_key = get_detail_cache_key(questionnaire)
    detail_data = cache.get(cache_key)
    if detail_data is None:
        has_available_qrcode = True
        if questionnaire.enable_multi_qrcodes:
            has_available_qrcode = questionnaire.qrcodes.filter(is_used=False).exists()
        submit_count = questionnaire.submit_count
        detail_data = {
            'has_available_qrcode': has_available_qrcode,
            'submit_count': submit_count,
        }
        cache.set(cache_key, detail_data, 60)

    has_available_qrcode = detail_data['has_available_qrcode']
    submit_count = detail_data['submit_count']

    # ========== 使用原始 SQL 查询问题列表，彻底绕过 ORM 连接状态 ==========
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
                       SELECT id, text, question_type, options, required, max_length, `order`
                       FROM questionnaire_question
                       WHERE questionnaire_id = %s
                       ORDER BY "order"
                       """, [str(questionnaire_id)])
        rows = cursor.fetchall()

    # 将原始数据转换为 Question 对象列表（保持模板兼容）
    from .models import Question
    questions = []
    for row in rows:
        q = Question(
            id=row[0],
            text=row[1],
            question_type=row[2],
            options=row[3],
            required=row[4],
            max_length=row[5],
            order=row[6],
            questionnaire_id=questionnaire_id
        )
        q._state.adding = False  # 标记为已存在
        questions.append(q)
    # =================================================================

    user_has_submitted = False
    if request.user.is_authenticated:
        user_has_submitted = Response.objects.filter(
            questionnaire=questionnaire,
            user=request.user,
            is_submitted=True
        ).exists()

    responses = Response.objects.filter(questionnaire=questionnaire)
    now = timezone.now()

    # 调试输出（可选）
    print("=== 详情视图调试 ===")
    print(f"问卷ID: {questionnaire.id}")
    print(f"问题数量: {len(questions)}")
    print(f"has_available_qrcode: {has_available_qrcode}")

    # 返回模板，保留原有所有模板变量
    return render(request, 'questionnaire/detail.html', {
        'questionnaire': questionnaire,
        'responses': responses,
        'questions': questions,
        'response_count': responses.count(),
        'is_admin': request.user.is_superuser,
        'has_available_qrcode': has_available_qrcode,
        'submit_count': submit_count,
        'user_has_submitted': user_has_submitted,
        'now': now,
        # 保留原有 just_created 变量（用于模板自动刷新脚本，但可能已不再需要）
        'just_created': request.session.pop('just_created', None) == str(questionnaire_id),
    })

@login_required
def my_responses(request):
    """我的回答"""
    responses = Response.objects.filter(user=request.user).select_related('questionnaire').order_by('-submitted_at')

    return render(request, 'questionnaire/my_responses.html', {
        'responses': responses,
        'total_count': responses.count(),
        'is_admin': request.user.is_admin
    })


@login_required
def manage_users(request):
    """管理用户（管理员专用）"""
    if not request.user.is_original_admin:
        messages.error(request, '您没有权限访问此页面')
        return redirect('dashboard')

    # 获取所有用户统计
    users = User.objects.all().order_by('-date_joined')
    user_stats = []

    for user in users:
        user_stats.append({
            'user': user,
            'questionnaires_count': Questionnaire.objects.filter(creator=user).count(),
            'responses_count': Response.objects.filter(user=user).count()
        })

    return render(request, 'admin/manage_users.html', {
        'user_stats': user_stats,
        'is_admin': True
    })

@login_required
@admin_required
def user_detail(request, user_id):
    """用户详情（仅管理员）"""
    user = get_object_or_404(User, id=user_id)
    questionnaires = Questionnaire.objects.filter(creator=user)
    responses = Response.objects.filter(user=user)
    return render(request, 'admin/user_detail.html', {
        'target_user': user,
        'questionnaires': questionnaires,
        'responses': responses,
        'is_admin': True
    })


@login_required
@admin_required
def toggle_user_active(request, user_id):
    """管理员可以禁用/激活其他用户，但只有原始管理员可以操作其他管理员"""
    if not request.user.is_admin:
        messages.error(request, '您没有权限执行此操作')
        return redirect('manage_users')

    user = get_object_or_404(User, id=user_id)

    # 不能对自己操作
    if user == request.user:
        messages.error(request, '不能对自己执行此操作')
        return redirect('manage_users')

    # 如果要操作的是管理员，检查是否是原始管理员
    if user.is_admin and not request.user.is_original_admin:
        messages.error(request, '只有原始管理员可以禁用/激活其他管理员')
        return redirect('manage_users')

    user.is_active = not user.is_active
    user.save()

    action = '激活' if user.is_active else '禁用'
    messages.success(request, f'用户 {user.username} 已{action}')
    return redirect('manage_users')


@login_required
@original_admin_required
def make_user_admin(request, user_id):
    """只有原始管理员可以将其他用户设为管理员"""
    user = get_object_or_404(User, id=user_id)

    # 不能对自己操作
    if user == request.user:
        messages.error(request, '不能对自己执行此操作')
        return redirect('manage_users')

    # 如果用户已经是管理员，直接返回
    if user.is_superuser:
        messages.info(request, f'用户 {user.username} 已经是管理员')
        return redirect('manage_users')

    # 设置为管理员
    user.is_superuser = True
    user.is_staff = True
    user.save()

    try:
        # 1. 发送通知给被设为管理员的用户
        admin_notification_message = f"""
           恭喜！您已被系统管理员 {request.user.username} 设为管理员。

           您现在拥有以下权限：
           - 查看系统统计信息
           - 管理所有用户的问卷
           - 查看所有问卷的回答
           - 管理用户权限

           请注意，只有原始管理员可以授予或取消管理员权限。

           操作时间：{timezone.now().strftime('%Y年%m月%d日 %H:%M:%S')}
           """

        NotificationManager.send_admin_notification(
            users=[user],
            title="🎉 您已被设为管理员",
            message=admin_notification_message.strip(),
            priority='high'
        )

        # 2. 发送通知给所有其他管理员（除了操作者和被操作者）
        other_admins = User.objects.filter(
            is_superuser=True,
            is_active=True
        ).exclude(id__in=[request.user.id, user.id])

        if other_admins.exists():
            other_admins_message = f"""
               管理员权限变更通知：

               用户 {user.username} 已被 {request.user.username} 设为系统管理员。

               现在系统中共有 {other_admins.count() + 2} 位管理员。

               操作时间：{timezone.now().strftime('%Y年%m月%d日 %H:%M:%S')}
               """

            NotificationManager.send_admin_notification(
                users=list(other_admins),
                title="管理员权限变更",
                message=other_admins_message.strip(),
                priority='normal'
            )

        # 3. 发送系统通知给所有用户
        all_users_message = f"用户 {user.username} 已被设为系统管理员，欢迎新管理员的加入！"
        NotificationManager.send_system_notification_to_all(
            title="新管理员加入",
            message=all_users_message,
            priority='normal',
            exclude_users=[user, request.user]
        )

        messages.success(request, f'用户 {user.username} 已设为管理员，并已发送通知')

    except Exception as e:
        # 即使通知发送失败，也不影响权限设置
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"发送管理员权限变更通知失败: {e}")
        messages.success(request, f'用户 {user.username} 已设为管理员（通知发送失败: {e}）')

    return redirect('manage_users')

@login_required
@admin_required
def admin_statistics(request):
    """系统统计（仅管理员）"""
    total_users = User.objects.count()
    new_users_today = User.objects.filter(date_joined__date=timezone.now().date()).count()
    total_questionnaires = Questionnaire.objects.count()
    published_questionnaires = Questionnaire.objects.filter(status='published').count()
    total_responses = Response.objects.count()

    context = {
        'total_users': total_users,
        'new_users_today': new_users_today,
        'total_questionnaires': total_questionnaires,
        'published_questionnaires': published_questionnaires,
        'total_responses': total_responses,
        'is_admin': True,
    }
    return render(request, 'admin/statistics.html', context)


'''logger.debug('==== admin_statistics 被调用 ====')
    logger.debug(f'用户: {request.user}  |  is_admin: {request.user.is_admin}')
    return HttpResponse('admin_statistics reached', content_type='text/plain')'''


# 添加：发布问卷功能
@login_required
def publish_questionnaire(request, questionnaire_id):
    """发布问卷并生成二维码"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id, creator=request.user)

    try:
        # 检查是否可以发布
        if questionnaire.questions.count() == 0:
            messages.error(request, '问卷必须至少有一个问题才能发布')
            return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)

        # 检查是否所有必填问题都有内容
        for question in questionnaire.questions.all():
            if not question.text.strip():
                messages.error(request, f'问题{question.order}不能为空')
                return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)
            if question.question_type in ['radio', 'checkbox'] and not question.options:
                messages.error(request, f'问题{question.order}需要设置选项')
                return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)

        # 更新状态
        questionnaire.status = 'published'
        questionnaire.published_at = timezone.now()

        # 如果没有邀请码，生成一个
        if not questionnaire.invite_code:
            import secrets
            import string
            alphabet = string.ascii_uppercase + string.digits
            questionnaire.invite_code = ''.join(secrets.choice(alphabet) for i in range(8))

        questionnaire.save()
        clear_questionnaire_cache(questionnaire)
        from .views_qrcode import generate_qrcode_for_questionnaire, generate_multi_qrcodes_for_questionnaire
        if questionnaire.enable_multi_qrcodes:
            generate_multi_qrcodes_for_questionnaire(request, questionnaire)
        else:
            generate_qrcode_for_questionnaire(request, questionnaire)

        # 生成二维码
        from .views_qrcode import generate_qrcode
        return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)

    except Exception as e:
        messages.error(request, f'发布失败: {str(e)}')
        return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)

@login_required
@require_POST
def delete_questionnaire(request, questionnaire_id):
    """删除问卷"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 检查权限
    if not (request.user == questionnaire.creator or request.user.is_admin):
        messages.error(request, '没有权限删除此问卷')
        return redirect('questionnaire_list')

    if request.method == 'POST':
        title = questionnaire.title
        questionnaire.delete()
        messages.success(request, f'问卷 "{title}" 已删除')
        return redirect('questionnaire_list')

    return redirect('questionnaire_detail', questionnaire_id=questionnaire_id)


@login_required
@original_admin_required
def remove_user_admin(request, user_id):
    """只有原始管理员可以取消其他用户的管理员权限"""
    user = get_object_or_404(User, id=user_id)

    # 不能对自己操作
    if user == request.user:
        messages.error(request, '不能对自己执行此操作')
        return redirect('manage_users')

    # 如果用户不是管理员，直接返回
    if not user.is_superuser:
        messages.info(request, f'用户 {user.username} 不是管理员')
        return redirect('manage_users')

    # 不能取消原始管理员的管理员权限
    if user.is_original_admin:
        messages.error(request, '不能取消原始管理员的管理员权限')
        return redirect('manage_users')

    # 取消管理员权限
    user.is_superuser = False
    user.is_staff = False
    user.save()
    # ============ 添加通知功能 ============
    try:
        # 1. 发送通知给被取消管理员权限的用户
        removed_notification_message = f"""
            通知：您的管理员权限已被取消

            系统管理员 {request.user.username} 已取消您的管理员权限。

            您将不再拥有以下权限：
            - 查看系统统计信息
            - 管理其他用户的问卷
            - 管理用户权限

            如果您对此有疑问，请联系系统管理员。

            操作时间：{timezone.now().strftime('%Y年%m月%d日 %H:%M:%S')}
            """

        NotificationManager.send_admin_notification(
            users=[user],
            title="管理员权限变更通知",
            message=removed_notification_message.strip(),
            priority='high'
        )

        # 2. 发送通知给所有其他管理员（除了操作者）
        other_admins = User.objects.filter(
            is_superuser=True,
            is_active=True
        ).exclude(id=request.user.id)

        if other_admins.exists():
            other_admins_message = f"""
                管理员权限变更通知：

                用户 {user.username} 的管理员权限已被 {request.user.username} 取消。

                现在系统中共有 {other_admins.count()} 位管理员。

                操作时间：{timezone.now().strftime('%Y年%m月%d日 %H:%M:%S')}
                """

            NotificationManager.send_admin_notification(
                users=list(other_admins),
                title="管理员权限变更",
                message=other_admins_message.strip(),
                priority='normal'
            )

        messages.success(request, f'用户 {user.username} 已取消管理员权限，并已发送通知')

    except Exception as e:
        # 即使通知发送失败，也不影响权限取消
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"发送管理员权限取消通知失败: {e}")
        messages.success(request, f'用户 {user.username} 已取消管理员权限（通知发送失败: {e}）')

    return redirect('manage_users')

@login_required
def user_profile(request):
    """用户个人资料页面"""
    user = request.user

    if request.method == 'POST':
        try:
            # 获取表单数据
            username = request.POST.get('username', '').strip()
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            phone = request.POST.get('phone', '').strip()

            # 检查用户名是否更改
            if username != user.username:
                # 检查用户名是否已存在
                if User.objects.filter(username=username).exists():
                    # 生成推荐用户名
                    import random
                    import string
                    recommendations = []

                    # 方法1: 在原用户名后加随机数字
                    for i in range(3):
                        suggested = f"{username}{random.randint(100, 999)}"
                        if not User.objects.filter(username=suggested).exists():
                            recommendations.append(suggested)

                    # 方法2: 在原用户名后加随机字母
                    if len(recommendations) < 3:
                        for i in range(3 - len(recommendations)):
                            suggested = f"{username}{random.choice(string.ascii_lowercase)}{random.choice(string.ascii_lowercase)}"
                            if not User.objects.filter(username=suggested).exists():
                                recommendations.append(suggested)

                    # 方法3: 如果还是不够，用更简单的
                    if len(recommendations) < 3:
                        for i in range(3 - len(recommendations)):
                            suggested = f"{username}_{i + 1}"
                            if not User.objects.filter(username=suggested).exists():
                                recommendations.append(suggested)

                    # 准备错误消息
                    error_msg = f'用户名 "{username}" 已被使用，请换一个用户名。'
                    if recommendations:
                        error_msg += f' 推荐：{", ".join(recommendations[:3])}'

                    messages.error(request, error_msg)
                    return render(request, 'dashboard/profile.html', {
                        'user': user,
                        'is_admin': user.is_admin,
                        'unread_notifications_count': user.notifications.filter(is_read=False).count()
                    })

                # 更新用户名
                user.username = username

            # 更新其他信息
            user.first_name = first_name
            user.last_name = last_name
            user.phone = phone
            user.save()

            messages.success(request, '个人资料已更新')
            return redirect('user_profile')

        except Exception as e:
            logger.error(f"更新用户资料失败: {e}")
            messages.error(request, '更新失败，请稍后重试')

    # 计算未读通知数量
    unread_notifications_count = user.notifications.filter(is_read=False).count()

    return render(request, 'dashboard/profile.html', {
        'user': user,
        'is_admin': user.is_admin,
        'unread_notifications_count': unread_notifications_count
    })


@login_required
def check_username_availability(request):
    """检查用户名是否可用"""
    username = request.GET.get('username', '').strip()
    current_username = request.user.username

    if not username:
        return JsonResponse({
            'available': False,
            'message': '用户名不能为空'
        })

    if username == current_username:
        return JsonResponse({
            'available': True,
            'message': '这是您当前使用的用户名'
        })

    if len(username) < 3:
        return JsonResponse({
            'available': False,
            'message': '用户名长度不能少于3个字符'
        })

    # 检查用户名是否已存在
    if User.objects.filter(username=username).exists():
        # 生成推荐用户名
        import random
        import string
        recommendations = []

        # 尝试生成3个推荐
        for i in range(3):
            # 方法1: 加数字
            suggested = f"{username}{random.randint(100, 999)}"
            if not User.objects.filter(username=suggested).exists():
                recommendations.append(suggested)

        if len(recommendations) < 3:
            for i in range(3 - len(recommendations)):
                # 方法2: 加字母
                suggested = f"{username}{random.choice(string.ascii_lowercase)}{random.choice(string.ascii_lowercase)}"
                if not User.objects.filter(username=suggested).exists():
                    recommendations.append(suggested)

        if len(recommendations) < 3:
            for i in range(3 - len(recommendations)):
                # 方法3: 加下划线
                suggested = f"{username}_{i + 1}"
                if not User.objects.filter(username=suggested).exists():
                    recommendations.append(suggested)

        return JsonResponse({
            'available': False,
            'message': '用户名已被使用',
            'recommendations': recommendations[:3]
        })

    return JsonResponse({
        'available': True,
        'message': '用户名可用'
    })

@login_required
@require_POST
def update_questionnaire_time(request, questionnaire_id):
    """更新问卷的开始和截止时间（AJAX 用）"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)
    # 权限检查
    if not (request.user == questionnaire.creator or request.user.is_admin):
        return JsonResponse({'success': False, 'message': '没有权限'}, status=403)

    start_time = request.POST.get('start_time')
    end_time = request.POST.get('end_time')
    # 空字符串转为 None
    start_time = start_time if start_time else None
    end_time = end_time if end_time else None

    if start_time and end_time and end_time <= start_time:
        return JsonResponse({'success': False, 'message': '截止时间必须晚于开始时间'})

    try:
        questionnaire.start_time = start_time
        questionnaire.end_time = end_time
        questionnaire.save()
        return JsonResponse({'success': True, 'message': '时间设置已更新'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'更新失败: {str(e)}'})


@login_required
@require_POST
def update_questionnaire_limit(request, questionnaire_id):
    """更新问卷的提交份数限制（AJAX 用）"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)
    if not (request.user == questionnaire.creator or request.user.is_admin):
        return JsonResponse({'success': False, 'message': '没有权限'}, status=403)

    limit_responses = request.POST.get('limit_responses') == 'on'
    max_responses = request.POST.get('max_responses')

    if limit_responses and not max_responses:
        return JsonResponse({'success': False, 'message': '开启份数限制时必须填写最大份数'})

    if max_responses:
        try:
            max_responses = int(max_responses)
            if max_responses <= 0:
                raise ValueError
        except ValueError:
            return JsonResponse({'success': False, 'message': '最大份数必须为正整数'})
    else:
        max_responses = None

    try:
        questionnaire.limit_responses = limit_responses
        questionnaire.max_responses = max_responses
        questionnaire.save()
        return JsonResponse({'success': True, 'message': '份数限制已更新'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'更新失败: {str(e)}'})


@require_GET
def api_questionnaire_detail(request, questionnaire_id):
    """返回问卷的最新动态数据（用于 AJAX 更新）"""
    # 强制关闭当前连接，确保后续查询使用新连接
    connection.close()

    # 直接使用原始 SQL 获取问卷基本信息（避免 ORM 缓存）
    with connection.cursor() as cursor:
        cursor.execute("""
                       SELECT id,
                              title,
                              description,
                              status,
                              version,
                              access_type,
                              invite_code,
                              limit_responses,
                              max_responses,
                              enable_multi_qrcodes,
                              submit_count,
                              creator_id
                       FROM questionnaire_questionnaire
                       WHERE id = %s
                       """, [str(questionnaire_id)])
        row = cursor.fetchone()
        if not row:
            return JsonResponse({'error': '问卷不存在'}, status=404)

        # 构造 questionnaire 对象（仅用于后续非关键查询，或者也可以不用）
        # 但我们仍然需要 creator_id 用于权限检查
        creator_id = row[11]

    # 权限检查（需要用户对象，这里用 ORM 查询用户，但这是独立查询，不受影响）
    questionnaire = Questionnaire.objects.get(pk=questionnaire_id)
    if not request.user.is_admin and questionnaire.creator != request.user:
        return JsonResponse({'error': '无权限'}, status=403)

    # ========== 使用原始 SQL 查询问题列表，彻底绕过任何连接状态 ==========
    with connection.cursor() as cursor:
        cursor.execute("""
                       SELECT id, text, question_type, options, required, max_length, `order`
                       FROM questionnaire_question
                       WHERE questionnaire_id = %s
                       ORDER BY "order"
                       """, [str(questionnaire_id)])
        rows = cursor.fetchall()

    questions = []
    for row in rows:
        # 解析 options 字段（假设存储为 JSON 字符串）
        options = row[3]
        if isinstance(options, str):
            try:
                options = json.loads(options)
            except:
                options = []
        questions.append({
            'id': row[0],
            'text': row[1],
            'question_type': row[2],
            'options': options,
            'required': row[4],
            'max_length': row[5],
            'order': row[6],
        })
    # =================================================================

    # 以下使用 ORM 查询无妨（它们是独立查询，不依赖主查询连接）
    has_available_qrcode = True
    if questionnaire.enable_multi_qrcodes:
        has_available_qrcode = questionnaire.qrcodes.filter(is_used=False).exists()

    submit_count = questionnaire.submit_count

    user_has_submitted = False
    if request.user.is_authenticated:
        user_has_submitted = Response.objects.filter(
            questionnaire=questionnaire,
            user=request.user,
            is_submitted=True
        ).exists()

    return JsonResponse({
        'success': True,
        'questions': questions,
        'has_available_qrcode': has_available_qrcode,
        'submit_count': submit_count,
        'user_has_submitted': user_has_submitted,
        'questionnaire_version': questionnaire.version,
        'status': questionnaire.status,
    })

@login_required
def questionnaire_redirect_wait(request, questionnaire_id):
    redirect_url = reverse('questionnaire_detail', args=[questionnaire_id]) + f'?_={int(timezone.now().timestamp())}'
    return render(request, 'questionnaire/redirect_wait.html', {
        'redirect_url': redirect_url,
        'questionnaire_id': str(questionnaire_id)   # 新增传递问卷ID
    })