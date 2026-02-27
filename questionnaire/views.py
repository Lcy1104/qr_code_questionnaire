from .models import Questionnaire, Response,QuestionnaireQRCode
from .visualization import get_questionnaire_stats, build_stats
from .forms import QuestionnaireForm, QuestionForm, QuestionFormSet
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django import forms
from .models import Questionnaire, Question,Answer,Notification, NotificationSettings,Response
from .version_manager import VersionManager
from .notification_manager import NotificationManager
from django.http import JsonResponse
from django.db.models import Avg, Count
from django.utils import timezone
from datetime import timedelta
import json
import logging
logger = logging.getLogger(__name__)

# 在文件最顶部，import 之后
THIS_IS_A_TEST_FOR_RELOAD = "如果看到这条消息，说明 Django 重新加载了"
print(f"===== DJANGO RELOADED: {THIS_IS_A_TEST_FOR_RELOAD} =====")

@login_required
def check_questionnaire_status(request, questionnaire_id):
    """检查问卷状态（供创建者使用）"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    if request.user != questionnaire.creator and not request.user.is_admin:
        messages.error(request, '您没有权限查看此页面')
        return redirect('home')

    return render(request, 'registration/not_published.html', {
        'questionnaire': questionnaire,
        'can_edit': True,
    })

@login_required
def survey_form(request, questionnaire_id):
    """问卷填写页面 - 方案B兼容"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 检查问卷状态
    if questionnaire.status != 'published':
        messages.error(request, '问卷未发布或已关闭')
        return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)

    # 检查是否已经提交过
    if Response.objects.filter(questionnaire=questionnaire, user=request.user).exists():
        messages.warning(request, '您已经提交过此问卷')
        return render(request, 'questionnaire/already_submitted.html', {'questionnaire': questionnaire})

    # 根据访问权限类型检查权限
    if questionnaire.access_type == 'public':
        # 公开问卷：只需登录即可
        pass  # 已经登录，继续

    elif questionnaire.access_type == 'invite':
        # 邀请码问卷：检查邀请码验证状态
        from .views_invite_first import check_invite_session
        is_valid, error_msg = check_invite_session(request, questionnaire.id)

        if not is_valid:
            messages.warning(request, error_msg or '请先验证邀请码')
            return redirect('survey_access', questionnaire_id=questionnaire.id)

    elif questionnaire.access_type == 'private':
        # 私有问卷：检查权限
        if request.user != questionnaire.creator and not request.user.is_admin:
            messages.error(request, '您没有权限访问此问卷')
            return redirect('questionnaire_list')

    # 获取问题并显示表单
    questions = questionnaire.questions.all().order_by('order')

    # 增加访问计数（只在首次进入时增加）
    if 'questionnaire_viewed' not in request.session or request.session['questionnaire_viewed'] != str(
            questionnaire.id):
        questionnaire.view_count += 1
        questionnaire.save()
        request.session['questionnaire_viewed'] = str(questionnaire.id)

    return render(request, 'questionnaire/form.html', {
        'questionnaire': questionnaire,
        'questions': questions,
        'now': timezone.now(),
    })


@login_required
def create_questionnaire(request):
    """创建问卷 - 支持不同保存操作"""
    if request.method == 'POST':
        logger = logging.getLogger('questionnaire')
        logger.info(f"[EDIT POST] 接收到的POST数据: {dict(request.POST)}")
        logger.info(f"[EDIT POST] TOTAL_FORMS: {request.POST.get('questions-TOTAL_FORMS')}")
        logger.info(f"[EDIT POST] INITIAL_FORMS: {request.POST.get('questions-INITIAL_FORMS')}")

        # 打印所有questions相关的字段
        for key in sorted(request.POST.keys()):
            if 'questions' in key:
                logger.info(f"[EDIT POST] {key} = {request.POST.get(key)!r}")
        form = QuestionnaireForm(request.POST)
        question_formset = QuestionFormSet(request.POST)

        logger.info(f"[EDIT POST] 提交的数据: {request.POST.dict()}")
        # 特别检查 id 字段
        for key, value in request.POST.items():
            if '-id' in key:
                logger.info(f"[EDIT POST] ID字段: {key} = {value!r}")

        if form.is_valid() and question_formset.is_valid():
            for f in question_formset:
                if f.cleaned_data.get('DELETE'):
                    logger.info('[EDIT] 问题 pk=%s 被标为 DELETE，文本=%s',
                                f.instance.pk, f.instance.text)

            questionnaire = form.save(commit=False)
            questionnaire.creator = request.user

            # 根据不同的按钮确定保存方式（使用 save_action 字段）
            save_action = request.POST.get('save_action', 'save_draft')

            if save_action == 'save_and_publish':
                # 发布问卷
                questionnaire.status = 'published'
                questionnaire.published_at = timezone.now()

                # 保存问卷
                questionnaire.save()

                # 保存问题
                questions = question_formset.save(commit=False)
                for i, question in enumerate(questions):
                    question.questionnaire = questionnaire
                    raw = question_formset.forms[i].cleaned_data.get('max_length_field', 0)
                    logger.info('[CREATE] 第%d题 max_length_field 原始值 = %s', i + 1, raw)
                    question.max_length = int(raw) if str(raw).isdigit() else 0
                    logger.info('[CREATE] 第%d题 写入 max_length = %s', i + 1, question.max_length)
                    question.save(update_fields=['max_length'])

                # 处理删除的问题
                for deleted_form in question_formset.deleted_forms:
                    if deleted_form.instance.pk:
                        deleted_form.instance.delete()

                # 根据访问权限生成相应内容
                from .views_qrcode import get_server_base_url
                base_url = get_server_base_url(request)

                # 生成二维码（所有类型的问卷都需要）
                import qrcode
                from io import BytesIO
                from django.core.files.base import ContentFile

                # 构建访问URL
                if questionnaire.access_type == 'invite':
                    # 生成邀请码
                    import uuid
                    invite_code = str(uuid.uuid4())[:8].upper()
                    questionnaire.invite_code = invite_code
                    invite_url = f"{base_url}/invite/{invite_code}/"
                    qr_data = invite_url
                else:
                    # 公开或私有问卷
                    survey_url = f"{base_url}/survey/{questionnaire.id}/"
                    qr_data = survey_url

                # 生成二维码图片
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=10,
                    border=4,
                )
                qr.add_data(qr_data)
                qr.make(fit=True)

                img = qr.make_image(fill_color="black", back_color="white")
                buffer = BytesIO()
                img.save(buffer, format="PNG")

                # 保存二维码到问卷模型
                questionnaire.qr_code.save(
                    f'qrcode_{questionnaire.id}.png',
                    ContentFile(buffer.getvalue())
                )
                questionnaire.save()

                # 根据访问权限显示不同的成功消息
                if questionnaire.access_type == 'invite':
                    messages.success(request, f'问卷已发布！二维码和邀请码已生成。邀请码：{invite_code}')
                else:
                    messages.success(request, '问卷已发布！二维码已生成。')

                # 发布后重定向到问卷管理页面
                return redirect('questionnaire_list')

            elif save_action == 'save_draft':
                # 保存草稿
                questionnaire.status = 'draft'
                questionnaire.save()

                # 保存问题
                questions = question_formset.save(commit=False)
                for question in questions:
                    question.questionnaire = questionnaire
                    question.save()

                # 处理删除的问题
                for deleted_form in question_formset.deleted_forms:
                    if deleted_form.instance.pk:
                        deleted_form.instance.delete()

                messages.success(request, '问卷已保存为草稿！')

                # 草稿保存后重定向到问卷管理页面
                return redirect('questionnaire_list')

        else:
            for idx, qform in enumerate(question_formset):
                if qform.errors:
                    logger.error('第%d题错误: %s', idx + 1, qform.errors)
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
            for form in question_formset:
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f'问题 {form.prefix}: {field}: {error}')

    else:
        form = QuestionnaireForm()
        question_formset = QuestionFormSet()

    return render(request, 'questionnaire/create.html', {
        'form': form,
        'question_formset': question_formset,
    })


@login_required
def edit_questionnaire(request, questionnaire_id):
    """编辑问卷 - 修复extra表单问题"""
    #questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id, creator=request.user)
    #只允许问卷创建者访问，请启用上文
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    logger.info(f"[EDIT] 用户 {request.user.username} 尝试编辑问卷 {questionnaire_id}")
    logger.info(f"[EDIT] 问卷创建者: {questionnaire.creator.username}")
    logger.info(f"[EDIT] 当前用户是管理员吗? {request.user.is_admin}")

    # 检查权限：问卷创建者或管理员可以编辑
    if questionnaire.creator != request.user and not request.user.is_admin:
        logger.warning(f"[EDIT] 权限检查失败: 用户 {request.user.username} 无权编辑问卷 {questionnaire_id}")
        messages.error(request, '您没有权限编辑此问卷')
        return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)

    logger.info(f"[EDIT] 权限检查通过，继续编辑")
    # 关键修改：为编辑页面创建一个没有extra表单的formset
    EditableQuestionFormSet = forms.inlineformset_factory(
        Questionnaire,
        Question,
        form=QuestionForm,
        exclude=('max_length',),
        extra=0,  # 编辑页面不添加空白表单
        can_delete=True,
        max_num=20,
    )

    if request.method == 'POST':
        logger.info(f"[EDIT POST] ===== 开始处理编辑问卷 {questionnaire_id} =====")

        # 打印所有与问题相关的POST数据
        for key in sorted(request.POST.keys()):
            if key.startswith('questions-'):
                logger.info(f"[EDIT POST] {key} = {request.POST.get(key)}")

        form = QuestionnaireForm(request.POST, instance=questionnaire)

        # 关键修改：修复 POST 数据，确保管理表单字段正确
        mutable_post = request.POST.copy()

        # 修复管理表单字段
        if 'questions-TOTAL_FORMS' not in mutable_post:
            # 计算问题数量
            total_forms = 0
            for key in mutable_post.keys():
                if key.startswith('questions-') and key.endswith('-text'):
                    total_forms += 1
            mutable_post['questions-TOTAL_FORMS'] = str(total_forms)

        # 确保其他管理表单字段存在
        if 'questions-INITIAL_FORMS' not in mutable_post:
            mutable_post['questions-INITIAL_FORMS'] = '0'
        if 'questions-MIN_NUM_FORMS' not in mutable_post:
            mutable_post['questions-MIN_NUM_FORMS'] = '0'
        if 'questions-MAX_NUM_FORMS' not in mutable_post:
            mutable_post['questions-MAX_NUM_FORMS'] = '20'

        logger.info(f"[EDIT POST] 修复后管理表单: TOTAL_FORMS={mutable_post.get('questions-TOTAL_FORMS')}")

        # 关键修改：在验证前，手动将 options_text 转换为 options 并放入 POST 数据
        total_forms = int(mutable_post.get('questions-TOTAL_FORMS', 0))
        for i in range(total_forms):
            question_type = mutable_post.get(f'questions-{i}-question_type')
            options_text = mutable_post.get(f'questions-{i}-options_text', '')

            logger.info(f"[EDIT PREPROCESS] 问题 {i}: type={question_type}, options_text={options_text!r}")

            if question_type in ['radio', 'checkbox']:
                # 按行分割并去除空行
                options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
                if not options:
                    # 如果选项为空，设置为默认选项
                    options = ['选项1', '选项2']
                    logger.warning(f"[EDIT PREPROCESS] 问题 {i} 选项为空，设置为默认值")
                    mutable_post[f'questions-{i}-options_text'] = '选项1\n选项2'

                # 关键：将 options 转换为 JSON 字符串并放入 POST 数据
                import json
                options_json = json.dumps(options, ensure_ascii=False)
                mutable_post[f'questions-{i}-options'] = options_json
                logger.info(f"[EDIT PREPROCESS] 问题 {i} 设置 options JSON: {options_json}")
            else:
                # 非选择题，设置空数组
                mutable_post[f'questions-{i}-options'] = '[]'

        # 重新创建formset
        question_formset = EditableQuestionFormSet(mutable_post, instance=questionnaire)

        # 验证表单
        if form.is_valid() and question_formset.is_valid():
            logger.info("[EDIT POST] 表单验证通过")

            # 打印验证后的数据
            for i, qform in enumerate(question_formset.forms):
                if qform.is_valid():
                    logger.info(f"[EDIT POST] 问题 {i} 验证通过: text={qform.cleaned_data.get('text')!r}")
                    logger.info(f"[EDIT POST] 问题 {i} options_text={qform.cleaned_data.get('options_text')!r}")
                    logger.info(f"[EDIT POST] 问题 {i} options={qform.cleaned_data.get('options')!r}")
                    logger.info(f"[EDIT POST] 问题 {i} instance.pk={qform.instance.pk}")
                else:
                    logger.error(f"[EDIT POST] 问题 {i} 验证失败: {qform.errors}")

            # 检查是否有任何修改
            has_modifications = False

            # 1. 检查问卷基本信息是否修改
            for field in ['title', 'description', 'access_type']:
                if form.has_changed() and field in form.changed_data:
                    has_modifications = True
                    logger.info(f"[EDIT] 问卷基本信息已修改: {field}")
                    break

            # 2. 检查问题是否修改
            for i, qform in enumerate(question_formset.forms):
                if qform.is_valid():
                    # 检查是否需要删除
                    if qform.cleaned_data.get('DELETE'):
                        if qform.instance.pk:
                            has_modifications = True
                            qform.instance.delete()
                            logger.info(f"[EDIT] 删除问题: {qform.instance.id}")
                        continue

                    # 检查是否是新问题或修改的问题
                    if qform.instance.pk:
                        # 已有问题：检查是否被修改
                        if qform.has_changed():
                            has_modifications = True
                            logger.info(f"[EDIT] 修改问题: {qform.instance.id}")
                    else:
                        # 新添加的问题
                        if qform.cleaned_data.get('text'):  # 确保不是空表单
                            has_modifications = True
                            logger.info(f"[EDIT] 添加新问题")

            # 保存问卷基本信息
            questionnaire = form.save(commit=False)
            save_action = request.POST.get('save_action', 'save_draft')

            # 关键：只有有修改时才更新版本号
            if has_modifications:
                questionnaire.version += 1
                logger.info(f"[EDIT] 问卷有修改，版本号更新为: {questionnaire.version}")
            else:
                logger.info(f"[EDIT] 问卷无修改，版本号保持不变: {questionnaire.version}")

            if save_action == 'save_and_publish':
                questionnaire.status = 'published'
                if not questionnaire.published_at:
                    questionnaire.published_at = timezone.now()
                logger.info(f"[EDIT] 发布问卷，状态: {questionnaire.status}")
            else:
                questionnaire.status = 'draft'
                logger.info(f"[EDIT] 保存草稿，状态: {questionnaire.status}")

            questionnaire.save()

            # 关键修改：完全手动处理每个问题的保存，确保新问题被保存
            try:
                # 首先，处理删除的表单
                logger.info(f"[EDIT SAVE] 开始处理保存")

                # 获取POST数据中的问题总数
                total_forms = int(request.POST.get('questions-TOTAL_FORMS', 0))
                logger.info(f"[EDIT SAVE] 总共 {total_forms} 个问题需要处理")

                # 存储新问题的ID，用于后续验证
                new_question_ids = []

                # 遍历每个问题
                for i in range(total_forms):
                    logger.info(f"[EDIT SAVE] 处理问题 {i}")

                    # 获取问题数据
                    question_id = request.POST.get(f'questions-{i}-id', '').strip()
                    text = request.POST.get(f'questions-{i}-text', '').strip()
                    question_type = request.POST.get(f'questions-{i}-question_type', 'radio')
                    order = request.POST.get(f'questions-{i}-order', str(i))
                    required = request.POST.get(f'questions-{i}-required') == 'on'
                    options_text = request.POST.get(f'questions-{i}-options_text', '')
                    max_length_field = request.POST.get(f'questions-{i}-max_length_field', '0')
                    delete_flag = request.POST.get(f'questions-{i}-DELETE', '')

                    logger.info(
                        f"[EDIT SAVE] 问题 {i} 原始数据: id={question_id}, text={text!r}, type={question_type}, delete={delete_flag}")

                    # 检查是否标记为删除
                    if delete_flag == '1':
                        if question_id:
                            try:
                                question = Question.objects.get(id=question_id)
                                question.delete()
                                logger.info(f"[EDIT SAVE] 删除问题: ID={question_id}")
                            except Question.DoesNotExist:
                                logger.warning(f"[EDIT SAVE] 要删除的问题不存在: ID={question_id}")
                        continue

                    # 确保问题文本不为空
                    if not text:
                        logger.warning(f"[EDIT SAVE] 问题 {i} 文本为空，跳过")
                        continue

                    # 处理已有问题或新问题
                    if question_id:  # 已有问题
                        try:
                            question = Question.objects.get(id=question_id)
                            logger.info(f"[EDIT SAVE] 更新已有问题: ID={question_id}, text={text}")

                            # 更新字段
                            question.text = text
                            question.question_type = question_type
                            question.order = int(order) if order.isdigit() else i
                            question.required = required

                            # 处理选项
                            if question_type in ['radio', 'checkbox']:
                                options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
                                question.options = options if options else ['选项1', '选项2']
                                logger.info(f"[EDIT SAVE] 问题 {i} 选项: {question.options}")
                            else:
                                question.options = []

                            # 设置 max_length
                            question.max_length = int(max_length_field) if max_length_field.isdigit() else 0
                            logger.info(f"[EDIT SAVE] 问题 {i} max_length 设置为: {question.max_length}")
                            question.save()
                            logger.info(f"[EDIT SAVE] 已有问题保存成功: ID={question.id}")

                        except Question.DoesNotExist:
                            logger.error(f"[EDIT SAVE] 问题不存在: ID={question_id}，将作为新问题创建")
                            # 作为新问题创建
                            question_id = ''

                    if not question_id:  # 新问题
                        logger.info(f"[EDIT SAVE] 创建新问题 {i}: text={text!r}")

                        # 创建新问题
                        question = Question(
                            questionnaire=questionnaire,
                            text=text,
                            question_type=question_type,
                            order=int(order) if order.isdigit() else i,
                            required=required,
                        )

                        # 处理选项
                        if question_type in ['radio', 'checkbox']:
                            options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
                            question.options = options if options else ['选项1', '选项2']
                            logger.info(f"[EDIT SAVE] 新问题 {i} 选项: {question.options}")
                        else:
                            question.options = []

                        # 设置 max_length
                        question.max_length = int(max_length_field) if max_length_field.isdigit() else 0

                        # 保存新问题
                        question.save()
                        new_question_ids.append(question.id)
                        logger.info(f"[EDIT SAVE] 新问题保存成功: ID={question.id}")

                # 验证：立即从数据库加载问题，确认保存成功
                saved_questions = questionnaire.questions.all().order_by('order')
                logger.info(f"[EDIT SAVE] 问卷现有问题数量: {saved_questions.count()}")
                logger.info(f"[EDIT SAVE] 新创建的问题ID列表: {new_question_ids}")

                for q in saved_questions:
                    logger.info(f"[EDIT SAVE] 问卷问题: ID={q.id}, text={q.text}, order={q.order}, options={q.options}")

            except Exception as e:
                logger.error(f"[EDIT SAVE] 表单集保存失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
                messages.error(request, f'保存失败: {str(e)}')
                return redirect('edit_questionnaire', questionnaire.id)

            # 保存成功消息
            if has_modifications:
                messages.success(request, f'问卷已保存！版本号: {questionnaire.version}')
            else:
                messages.info(request, '问卷已保存，无修改内容')

            # 重定向
            if save_action == 'save_and_publish':
                return redirect('dashboard_questionnaire_detail', questionnaire.id)
            else:
                return redirect('edit_questionnaire', questionnaire.id)

        else:
            # 表单验证失败
            logger.error(f"[EDIT ERROR] 表单验证失败")
            logger.error(f"表单错误: {form.errors}")
            logger.error(f"表单集错误: {question_formset.errors}")

            # 显示更详细的错误信息
            for i, qform in enumerate(question_formset.forms):
                if qform.errors:
                    logger.error(f"[EDIT ERROR] 问题 {i} 详细错误: {qform.errors}")
                    logger.error(
                        f"[EDIT ERROR] 问题 {i} 原始数据: type={request.POST.get(f'questions-{i}-question_type')}, options_text={request.POST.get(f'questions-{i}-options_text', '')!r}")

            # 收集所有错误信息
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    error_messages.append(f'问卷信息 - {field}: {error}')

            for i, qform in enumerate(question_formset.forms):
                for field, errors in qform.errors.items():
                    for error in errors:
                        error_messages.append(f'问题{i + 1} - {field}: {error}')

            # 显示错误消息
            for error in error_messages[:5]:
                messages.error(request, error)

            if len(error_messages) > 5:
                messages.warning(request, f'还有{len(error_messages) - 5}个错误未显示')

    else:
        # GET 请求
        form = QuestionnaireForm(instance=questionnaire)
        question_formset = EditableQuestionFormSet(instance=questionnaire)

        logger.info(f"[EDIT GET] 加载编辑页面: {questionnaire_id}, 问题数量: {question_formset.total_form_count()}")

    return render(request, 'questionnaire/edit.html', {
        'questionnaire': questionnaire,
        'form': form,
        'question_formset': question_formset,
    })

def create_question_version(question):
    """创建问题历史版本 - 独立函数"""
    try:
        # 临时方案：先不创建新模型，只记录日志
        logger.info(f"[VERSIONING] 问题 {question.id} 有回答且被修改，应该创建新版本")
        logger.info(f"[VERSIONING] 问题内容: {question.text[:50]}...")
        logger.info(f"[VERSIONING] 答案数量: {Answer.objects.filter(question=question).count()}")

        # 创建一个新问题作为新版本
        new_question = Question.objects.create(
            questionnaire=question.questionnaire,
            text=question.text,
            question_type=question.question_type,
            order=question.order,
            required=question.required,
            options=question.options,
            max_length=question.max_length
        )

        logger.info(f"[VERSIONING] 已创建新问题作为版本: {new_question.id}")
        return new_question

    except Exception as e:
        logger.error(f"[VERSIONING] 创建问题版本失败: {e}")
        return None


def survey_access(request, questionnaire_id=None, invite_code=None):
    """问卷访问入口 - 方案B：先验证邀请码再登录"""
    questionnaire = None

    # 获取问卷对象
    if questionnaire_id:
        questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)
    elif invite_code:
        # 如果有邀请码参数，尝试通过邀请码查找
        try:
            questionnaire = Questionnaire.objects.get(invite_code=invite_code)
        except Questionnaire.DoesNotExist:
            questionnaire = None

    if not questionnaire:
        messages.error(request, '问卷不存在')
        return redirect('home')

    # 检查问卷状态
    if questionnaire.status != 'published':
        can_edit = request.user.is_authenticated and (
                request.user == questionnaire.creator or
                request.user.is_admin
        )

        return render(request, 'registration/not_published.html', {
            'questionnaire': questionnaire,
            'error_message': '问卷未发布或已关闭'
        })

    # 根据访问权限类型处理
    if questionnaire.access_type == 'public':
        # 公开问卷：如果已登录，直接跳转到填写页面
        if request.user.is_authenticated:
            return redirect('survey_form', questionnaire_id=questionnaire.id)
        else:
            # 未登录：保存问卷ID到session，跳转到登录页面
            request.session['next'] = f'/survey/{questionnaire.id}/form/'
            request.session['questionnaire_id'] = str(questionnaire.id)
            messages.info(request, '请登录以填写问卷')
            return redirect('login')

    elif questionnaire.access_type == 'invite':
        # 邀请码问卷：方案B - 先验证邀请码
        # 检查是否已经有有效的邀请码验证
        has_valid_invite = False
        verified_by_session = False

        # 检查session中是否有有效的邀请码
        if ('valid_invite_code' in request.session and
                request.session.get('valid_invite_code') == questionnaire.invite_code):
            has_valid_invite = True
            verified_by_session = True

        # 如果有邀请码参数，验证它
        if invite_code:
            if invite_code == questionnaire.invite_code:
                # 邀请码正确，设置session
                request.session['valid_invite_code'] = questionnaire.invite_code
                request.session['verified_questionnaire'] = str(questionnaire.id)
                request.session['verified_time'] = timezone.now().isoformat()
                has_valid_invite = True
            else:
                # 邀请码错误
                messages.error(request, '邀请码无效')
                # 继续显示邀请码验证页面
                return render(request, 'questionnaire/verify_invite_code.html', {
                    'questionnaire': questionnaire,

                })

        # 如果有有效的邀请码验证（无论是通过session还是url参数）
        if has_valid_invite:
            # 检查用户是否已登录
            if request.user.is_authenticated:
                # 已登录，直接跳转到填写页面
                return redirect('survey_form', questionnaire_id=questionnaire.id)
            else:
                # 未登录，保存信息并跳转到登录页面
                request.session['next'] = f'/survey/{questionnaire.id}/form/'
                request.session['questionnaire_id'] = str(questionnaire.id)
                messages.success(request, '邀请码验证成功，请登录以填写问卷')
                return redirect('login')

        # 如果既没有session验证，也没有url参数验证，显示邀请码验证页面
        return render(request, 'questionnaire/verify_invite_code.html', {
            'questionnaire': questionnaire,
        })

    else:
        messages.error(request, '无法访问此问卷')
        return redirect('home')

@login_required
def questionnaire_detail(request, questionnaire_id):
    """问卷详情 - 包含可视化图表"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 检查权限（管理员或创建者）
    if not request.user.is_admin and questionnaire.creator != request.user:
        messages.error(request, '没有权限查看此问卷')
        return redirect('questionnaire_list')

    # 获取回答数据
    responses = Response.objects.filter(
        questionnaire=questionnaire,
        is_submitted=True
    )

    # 获取可视化统计数据和图表
    stats = get_questionnaire_stats(questionnaire_id)

    # 或者使用 build_stats 获取更详细的数据
    detailed_stats = build_stats(questionnaire)

    # 获取图表HTML
    from .visualization import QuestionnaireVisualizer
    visualizer = QuestionnaireVisualizer(questionnaire_id)
    charts_html = visualizer.generate_dashboard_html()

    return render(request, 'questionnaire/detail.html', {
        'questionnaire': questionnaire,
        'responses': responses,
        'stats': stats,
        'charts_html': charts_html,
        'detailed_stats': detailed_stats,
        'response_count': responses.count(),
        'is_admin': request.user.is_admin
    })


@login_required
def questionnaire_analytics(request, questionnaire_id):
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)
    if not request.user.is_admin and questionnaire.creator != request.user:
        messages.error(request, '没有权限查看此问卷分析')
        return redirect('dashboard')

    from .visualization import QuestionnaireVisualizer
    visualizer = QuestionnaireVisualizer(questionnaire_id)

    # 1. 平均用时
    responses_with_time = visualizer.responses.filter(completion_time__isnull=False)
    avg_seconds = responses_with_time.aggregate(avg=Avg('completion_time'))['avg'] or 0
    avg_time_display = f"{int(avg_seconds//60)}分{int(avg_seconds%60)}秒" if avg_seconds else "暂无数据"

    # 2. 回答趋势（最近7天）
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=6)
    date_list = [start_date + timedelta(days=i) for i in range(7)]
    trend_labels = [d.strftime('%m-%d') for d in date_list]
    trend_data = []
    for day in date_list:
        count = Response.objects.filter(
            questionnaire=questionnaire,
            submitted_at__date=day,
            is_submitted=True
        ).count()
        trend_data.append(count)

    # 3. 提交时间分布（按4小时）
    time_buckets = [(0,4),(4,8),(8,12),(12,16),(16,20),(20,24)]
    bucket_labels = ['00:00-04:00','04:00-08:00','08:00-12:00','12:00-16:00','16:00-20:00','20:00-24:00']
    time_data = []
    for start_hour, end_hour in time_buckets:
        count = Response.objects.filter(
            questionnaire=questionnaire,
            submitted_at__hour__gte=start_hour,
            submitted_at__hour__lt=end_hour,
            is_submitted=True
        ).count()
        time_data.append(count)

    # ========== 新增：回答时长分布数据 ==========
    durations = [r.completion_time for r in visualizer.responses if r.completion_time]

    # ========== 新增：各问题完成率数据 ==========
    from django.db.models import Count
    completion_data = []
    for question in visualizer.questions:
        answered_count = Answer.objects.filter(
            question=question,
            response__is_submitted=True
        ).values('response').distinct().count()
        completion_data.append({
            'question': question.text[:30],
            'rate': answered_count / visualizer.responses.count() * 100 if visualizer.responses.count() else 0,
            'answered': answered_count,
            'total': visualizer.responses.count()
        })

    # ========== 新增：每个问题的详细数据 ==========
    question_stats = []
    for question in visualizer.questions:
        answers = Answer.objects.filter(question=question, response__is_submitted=True)
        if question.question_type in ['radio', 'checkbox']:
            # 选择题：统计每个选项的答案数量
            options = question.options or []
            counts = [0] * len(options)
            for answer in answers:
                ans_text = answer.answer_text
                if question.question_type == 'radio':
                    if ans_text and len(ans_text) == 1:
                        idx = ord(ans_text) - 65
                        if 0 <= idx < len(options):
                            counts[idx] += 1
                else:  # checkbox
                    parts = ans_text.split(',')
                    for part in parts:
                        part = part.strip()
                        if part and len(part) == 1:
                            idx = ord(part) - 65
                            if 0 <= idx < len(options):
                                counts[idx] += 1
            question_stats.append({
                'id': str(question.id),
                'text': question.text,
                'type': question.question_type,
                'options': options,
                'counts': counts,
            })
        elif question.question_type == 'text':
            # 文本题：收集所有回答文本
            answer_list = []
            for a in answers:
                username = a.response.user.username if a.response.user else '匿名用户'
                answer_list.append({
                    'user': username,
                    'answer': a.answer_text
                })
            question_stats.append({
                'id': str(question.id),
                'text': question.text,
                'type': 'text',
                'answers': answer_list,
                })
        else:
            # 其他类型
            question_stats.append({
                'id': str(question.id),
                'text': question.text,
                'type': question.question_type,
            })

    summary = {
        'total_responses': visualizer.responses.count(),
        'total_questions': visualizer.questions.count(),
        'completion_rate': (visualizer.responses.count() / max(1, questionnaire.view_count)) * 100 if questionnaire.view_count else 0,
        'average_time': avg_time_display,
    }

    context = {
        'questionnaire': questionnaire,
        'summary': summary,
        'responses': visualizer.responses,
        'trend_labels': json.dumps(trend_labels),
        'trend_data': json.dumps(trend_data),
        'time_labels': json.dumps(bucket_labels),
        'time_data': json.dumps(time_data),
        'duration_data': json.dumps(durations),
        'completion_data': json.dumps(completion_data),
        'question_stats': json.dumps(question_stats, ensure_ascii=False),
        'current_time': timezone.now(),
    }
    return render(request, 'questionnaire/analytics.html', context)

@login_required
def export_analytics_pdf(request, questionnaire_id):
    """导出分析报告为PDF"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 检查权限
    if not request.user.is_admin and questionnaire.creator != request.user:
        messages.error(request, '没有权限导出此问卷分析')
        return redirect('dashboard')

    from .visualization import QuestionnaireVisualizer
    visualizer = QuestionnaireVisualizer(questionnaire_id)

    # 导出PDF（需要实现PDF导出功能）
    # response = visualizer.export_to_pdf()
    # return response

    messages.info(request, 'PDF导出功能正在开发中')
    return redirect('questionnaire_analytics', questionnaire_id=questionnaire_id)

def home(request):
    """首页"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'home.html')


@login_required
def my_questionnaires(request):
    """显示用户的所有问卷（重定向到dashboard_views的实现）"""
    return redirect('questionnaire_list')


@login_required
def question_version_history(request, question_id):
    """查看问题的版本历史"""
    from .models import Question

    # 直接获取问题，question_id 现在是整数
    question = get_object_or_404(Question, id=question_id)

    # 检查权限
    if not (request.user.is_admin or question.questionnaire.creator == request.user):
        messages.error(request, '没有权限查看')
        return redirect('questionnaire_list')

    # 使用版本管理器获取历史
    try:
        versions = VersionManager.get_question_history(str(question.id))
    except:
        versions = []  # 如果没有版本数据，返回空列表

    return render(request, 'questionnaire/version_history.html', {
        'question': question,
        'versions': versions,
        'questionnaire': question.questionnaire,
        'answer_count': question.answer_set.count(),
    })

@login_required
def notification_list(request):
    """显示用户的所有通知"""
    # 获取过滤参数
    notification_type = request.GET.get('type', '')
    read_status = request.GET.get('read', '')
    priority = request.GET.get('priority', '')

    # 获取通知
    notifications = NotificationManager.get_user_notifications(request.user)

    # 应用过滤器
    if notification_type:
        notifications = notifications.filter(notification_type=notification_type)
    if read_status == 'unread':
        notifications = notifications.filter(is_read=False)
    elif read_status == 'read':
        notifications = notifications.filter(is_read=True)
    if priority:
        notifications = notifications.filter(priority=priority)

    # 分页
    from django.core.paginator import Paginator
    paginator = Paginator(notifications, 20)  # 每页20条
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # 统计
    unread_count = NotificationManager.get_user_unread_count(request.user)
    total_count = notifications.count()
    read_count = notifications.filter(is_read=True).count()

    context = {
        'notifications': page_obj,
        'page_obj': page_obj,
        'unread_count': unread_count,
        'total_count': total_count,
        'read_count': read_count,
        'notification_types': Notification.NOTIFICATION_TYPES,
        'priority_choices': Notification.PRIORITY_CHOICES,
        'current_type': notification_type,
        'current_read': read_status,
        'current_priority': priority,
    }
    return render(request, 'notification/list.html', context)


@login_required
def notification_detail(request, notification_id):
    """查看通知详情"""
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        user=request.user
    )

    # 标记为已读
    notification.mark_as_read()

    context = {
        'notification': notification,
    }
    return render(request, 'notification/detail.html', context)


@login_required
def mark_all_as_read(request):
    """标记所有通知为已读"""
    if request.method == 'POST':
        # 使用NotificationManager的方法
        updated_count = NotificationManager.mark_all_as_read_for_user(request.user)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f'已标记 {updated_count} 条通知为已读'
            })

        return redirect('notification_list')

    return redirect('notification_list')


@login_required
def delete_notification(request, notification_id):
    """删除通知"""
    if request.method == 'POST':
        notification = get_object_or_404(
            Notification,
            id=notification_id,
            user=request.user
        )
        notification.delete()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': '通知已删除'})

        return redirect('notification_list')

    return redirect('notification_list')


@login_required
def delete_all_read(request):
    """删除所有已读通知"""
    if request.method == 'POST':
        notifications = Notification.objects.filter(
            user=request.user,
            is_read=True,
            delivery_status='sent'
        )

        deleted_count = notifications.count()
        notifications.delete()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f'已删除 {deleted_count} 条已读通知'
            })

        return redirect('notification_list')

    return redirect('notification_list')


@login_required
def notification_settings(request):
    """通知设置"""
    settings_obj, created = NotificationSettings.objects.get_or_create(
        user=request.user,
        defaults={
            'receive_questionnaire_updates': True,
            'receive_system_notifications': True,
            'receive_admin_notifications': True,
            'receive_urgent_notifications': True,
            'email_notifications': False,
            'push_notifications': True,
        }
    )

    if request.method == 'POST':
        settings_obj.receive_questionnaire_updates = request.POST.get(
            'receive_questionnaire_updates') == 'on'
        settings_obj.receive_system_notifications = request.POST.get(
            'receive_system_notifications') == 'on'
        settings_obj.receive_admin_notifications = request.POST.get(
            'receive_admin_notifications') == 'on'
        settings_obj.receive_urgent_notifications = request.POST.get(
            'receive_urgent_notifications') == 'on'
        settings_obj.email_notifications = request.POST.get(
            'email_notifications') == 'on'
        settings_obj.push_notifications = request.POST.get(
            'push_notifications') == 'on'
        settings_obj.save()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': '设置已保存'})

        return redirect('notification_settings')

    context = {
        'settings': settings_obj,
    }
    return render(request, 'notification/settings.html', context)


@login_required
def get_unread_count(request):
    """获取未读通知数量（用于AJAX轮询）"""
    unread_count = NotificationManager.get_user_unread_count(request.user)
    return JsonResponse({'unread_count': unread_count})


@login_required
def check_questionnaire_update(request, questionnaire_id):
    """
    检查问卷是否有更新
    用于AJAX轮询，检查用户填写的问卷是否有更新
    """
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': '非法请求'}, status=400)

    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 检查用户是否有权限访问这个问卷
    if not request.user.is_authenticated:
        return JsonResponse({'has_update': False, 'error': '请先登录'})

    # 获取用户对这个问卷的最新回答
    latest_response = Response.objects.filter(
        questionnaire=questionnaire,
        user=request.user,
        is_submitted=True
    ).order_by('-submitted_at').first()

    # 检查问卷是否有更新
    has_update = False
    update_info = {}

    if latest_response:
        # 如果问卷版本比用户回答的版本新，说明有更新
        if questionnaire.version > latest_response.questionnaire_version:
            has_update = True
            update_info = {
                'current_version': questionnaire.version,
                'user_version': latest_response.questionnaire_version,
                'questionnaire_id': str(questionnaire.id),
                'questionnaire_title': questionnaire.title,
                'update_message': f"问卷已更新到版本 {questionnaire.version}",
                'update_time': questionnaire.updated_at.isoformat() if questionnaire.updated_at else None
            }

    # 同时检查是否有关于这个问卷的未读通知
    questionnaire_notifications = Notification.objects.filter(
        user=request.user,
        related_questionnaire=questionnaire,
        is_read=False,
        notification_type='questionnaire_update'
    ).exists()

    # 如果有未读通知，也视为有更新
    if questionnaire_notifications:
        has_update = True
        if not update_info:
            update_info = {
                'questionnaire_id': str(questionnaire.id),
                'questionnaire_title': questionnaire.title,
                'update_message': "有新的问卷更新通知",
                'update_source': 'notification'
            }

    response_data = {
        'has_update': has_update,
        'questionnaire_id': str(questionnaire.id),
        'questionnaire_title': questionnaire.title,
        'current_version': questionnaire.version,
        'update_info': update_info if has_update else None
    }

    return JsonResponse(response_data)


@login_required
def acknowledge_update(request, questionnaire_id):
    """
    确认问卷更新
    用户确认已经查看过问卷更新
    """
    if request.method != 'POST':
        return JsonResponse({'error': '只支持POST请求'}, status=400)

    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # 获取用户对这个问卷的最新回答
    latest_response = Response.objects.filter(
        questionnaire=questionnaire,
        user=request.user,
        is_submitted=True
    ).order_by('-submitted_at').first()

    if latest_response:
        # 更新用户的回答版本号（模拟用户已经看到最新版本）
        # 注意：这里不修改数据库中的实际版本，只是记录用户已确认
        latest_response.questionnaire_version = questionnaire.version
        latest_response.save()

    # 将关于这个问卷的所有未读通知标记为已读
    notifications = Notification.objects.filter(
        user=request.user,
        related_questionnaire=questionnaire,
        is_read=False,
        notification_type='questionnaire_update'
    )

    read_count = 0
    for notification in notifications:
        notification.mark_as_read()
        read_count += 1

    # 返回成功响应
    response_data = {
        'success': True,
        'message': f'已确认问卷更新，标记了 {read_count} 条通知为已读',
        'questionnaire_id': str(questionnaire.id),
        'questionnaire_title': questionnaire.title,
        'current_version': questionnaire.version
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse(response_data)

    # 如果不是AJAX请求，重定向到问卷详情页
    return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)


@login_required
def get_notification_updates(request):
    """
    获取用户的未读通知更新（用于实时通知）
    """
    if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': '非法请求'}, status=400)

    # 获取未读通知数量
    unread_count = NotificationManager.get_user_unread_count(request.user)

    # 获取最新的未读通知
    recent_notifications = NotificationManager.get_user_notifications(
        request.user,
        limit=5,
        unread_only=True
    )

    # 获取紧急通知
    urgent_notifications = Notification.objects.filter(
        user=request.user,
        priority='urgent',
        is_read=False
    ).order_by('-created_at')[:3]

    # 格式化通知数据
    notifications_data = []
    for notification in recent_notifications:
        notifications_data.append({
            'id': str(notification.id),
            'title': notification.title,
            'message': notification.message[:100] + ('...' if len(notification.message) > 100 else ''),
            'type': notification.notification_type,
            'priority': notification.priority,
            'time_since': notification.time_since,
            'created_at': notification.created_at.isoformat() if notification.created_at else None,
            'related_questionnaire': str(
                notification.related_questionnaire.id) if notification.related_questionnaire else None,
            'questionnaire_title': notification.related_questionnaire.title if notification.related_questionnaire else None
        })

    # 格式化紧急通知数据
    urgent_data = []
    for notification in urgent_notifications:
        urgent_data.append({
            'id': str(notification.id),
            'title': notification.title,
            'message': notification.message[:150] + ('...' if len(notification.message) > 150 else ''),
            'created_at': notification.created_at.isoformat() if notification.created_at else None
        })

    response_data = {
        'unread_count': unread_count,
        'notifications': notifications_data,
        'urgent_notifications': urgent_data,
        'timestamp': timezone.now().isoformat()
    }

    return JsonResponse(response_data)

def qrcode_access(request, qr_code_id):
    """通过一次性二维码访问问卷"""
    qrcode = get_object_or_404(QuestionnaireQRCode, qr_code_id=qr_code_id)
    if qrcode.is_used:
        return render(request, 'error.html', {'message': '该二维码已被使用'})

    questionnaire = qrcode.questionnaire
    # 将二维码ID存入 session，供提交时标记
    request.session['active_qrcode_id'] = qr_code_id
    # 重定向到问卷引导页（复用现有逻辑）
    return redirect('survey_landing', survey_uuid=questionnaire.id)

@login_required
def response_detail(request, response_id):
    response = get_object_or_404(
        Response.objects.select_related('questionnaire', 'user', 'qrcode'),
        id=response_id
    )
    # 权限：问卷创建者或管理员可看
    if not (request.user == response.questionnaire.creator or request.user.is_admin):
        messages.error(request, '没有权限查看此回答')
        return redirect('dashboard')

    answers = response.answer_items.all().select_related('question').order_by('question__order')
    return render(request, 'questionnaire/response_detail.html', {
        'response': response,
        'answers': answers,
    })
