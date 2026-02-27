# questionnaire/views_questionnaire.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.core.files.base import ContentFile
from django.utils import timezone
import qrcode
from io import BytesIO
import random
import string
from .models import Questionnaire, Question
from .forms import QuestionnaireForm, QuestionForm, QuestionFormSet


@login_required
def create_questionnaire(request):
    if request.method == 'POST':
        # 1. 官方表单验证
        form = QuestionnaireForm(request.POST)
        qformset = QuestionFormSet(request.POST)

        if not form.is_valid() or not qformset.is_valid():
            # 验证失败 → 把错误带回页面
            return render(request, 'questionnaire/create.html',
                          {'form': form, 'question_formset': qformset})

        # 2. 验证通过 → 保存
        with transaction.atomic():
            questionnaire = form.save(commit=False)
            questionnaire.creator = request.user
            questionnaire.status = 'published'
            questionnaire.published_at = timezone.now()
            if questionnaire.access_type == 'invite':
                questionnaire.invite_code = generate_invite_code()
            questionnaire.save()

            qformset.instance = questionnaire
            qformset.save()          # 简答题的 max_length_field 会自动写库

        messages.success(request, '问卷发布成功！')
        return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)

    # GET
    return render(request, 'questionnaire/create.html', {
        'form': QuestionnaireForm(),
        'question_formset': QuestionFormSet(),
})

@login_required
def save_questions(request, questionnaire):
    """从POST数据保存问题 - 专门处理 EncryptedJSONField"""
    question_count = 0
    errors = []

    try:
        print(f"=== 开始保存问卷 {questionnaire.id} 的问题 ===")

        # 收集所有问题索引
        question_indices = []
        for key in request.POST:
            if key.startswith('questions-') and key.endswith('-text'):
                parts = key.split('-')
                if len(parts) >= 2:
                    index = parts[1]
                    if index not in question_indices:
                        question_indices.append(index)

        print(f"找到的问题索引: {question_indices}")

        for index in question_indices:
            print(f"\n--- 处理问题 {index} ---")

            # 检查是否被删除
            delete_flag = request.POST.get(f'questions-{index}-DELETE', '0')
            if delete_flag == '1':
                print(f"问题 {index} 被标记为删除，跳过")
                continue

            text = request.POST.get(f'questions-{index}-text', '').strip()
            if not text:
                print(f"问题 {index} 内容为空，跳过")
                continue

            question_type = request.POST.get(f'questions-{index}-question_type', 'radio')
            print(f"问题类型: {question_type}, 内容: {text[:50]}...")

            # 处理选项 - 关键：根据问题类型处理 options
            options = []

            if question_type in ['radio', 'checkbox']:
                # 从文本域获取选项
                options_text = request.POST.get(f'questions-{index}-options_text', '').strip()
                print(f"选择题选项文本: {options_text[:100] if options_text else '空'}")

                if options_text:
                    # 按行分割并过滤空行
                    raw_options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
                    options = raw_options
                else:
                    # 尝试从动态添加的选项输入框获取
                    option_prefix = f'questions-{index}-option-'
                    option_keys = sorted([k for k in request.POST.keys() if k.startswith(option_prefix)])
                    if option_keys:
                        raw_options = []
                        for key in option_keys:
                            option_val = request.POST.get(key, '').strip()
                            if option_val:
                                raw_options.append(option_val)
                        options = raw_options

                print(f"选择题选项: {options}")

                # 选择题必须有选项
                if not options:
                    error_msg = f"选择题必须至少有一个选项"
                    print(f"✗ {error_msg}")
                    errors.append(f"问题 {int(index) + 1}: {error_msg}")
                    continue

            elif question_type == 'text':
                # 简答题：options 必须是空列表，不能是 None
                options = []
                print(f"简答题，设置 options 为空列表")

            # 处理字数限制
            max_length = 0
            if question_type == 'text':
                # 尝试不同字段名
                max_length_str = None
                for field in [f'questions-{index}-max_length',
                              f'questions-{index}-max_length_field']:
                    val = request.POST.get(field)
                    if val is not None:
                        max_length_str = val
                        break

                if max_length_str is None:
                    max_length_str = '0'

                try:
                    max_length = int(max_length_str)
                    if max_length < 0:
                        max_length = 0
                except (ValueError, TypeError):
                    max_length = 0

                print(f"简答题字数限制: {max_length}")

            # 其他字段
            required = request.POST.get(f'questions-{index}-required', 'off') == 'on'
            order = request.POST.get(f'questions-{index}-order', str(question_count + 1))

            try:
                order = int(order)
            except (ValueError, TypeError):
                order = question_count + 1

            question_id = request.POST.get(f'questions-{index}-id', '')

            try:
                # 准备问题数据
                question_data = {
                    'questionnaire': questionnaire,
                    'text': text,
                    'question_type': question_type,
                    'order': order,
                    'required': required,
                    'max_length': max_length,
                }

                # 关键修复：确保 options 是有效的 JSON 可序列化数据
                # EncryptedJSONField 会自动调用 json.dumps()，所以要确保 options 是 JSON 兼容的
                if options is None:
                    options = []

                # 确保所有选项都是字符串（避免 JSON 序列化问题）
                options = [str(opt) for opt in options] if options else []

                # 测试 JSON 序列化
                import json
                try:
                    test_json = json.dumps(options, ensure_ascii=False)
                    print(f"测试 JSON 序列化成功: {test_json}")
                except Exception as json_err:
                    print(f"JSON 序列化失败: {json_err}")
                    # 使用简单字符串作为备选
                    options = []

                question_data['options'] = options

                print(f"最终保存的数据: options={options}, type={type(options)}")

                if question_id and question_id not in ['None', '', 'undefined']:
                    # 更新现有问题
                    try:
                        question = Question.objects.get(id=question_id, questionnaire=questionnaire)
                        for key, value in question_data.items():
                            setattr(question, key, value)

                        # 调用 save() 会触发 EncryptedJSONField 的 get_prep_value
                        question.save()
                        print(f"✓ 更新问题成功: {text[:30]}...")

                    except Question.DoesNotExist:
                        print(f"问题 {question_id} 不存在，创建新问题")
                        question = Question.objects.create(**question_data)
                        print(f"✓ 创建新问题成功: {text[:30]}...")

                else:
                    # 创建新问题
                    question = Question.objects.create(**question_data)
                    print(f"✓ 创建新问题成功: {text[:30]}... (ID: {question.id})")

                question_count += 1

            except Exception as e:
                error_msg = f"保存问题失败: {str(e)}"
                print(f"✗ {error_msg}")
                import traceback
                traceback.print_exc()
                errors.append(f"问题 {int(index) + 1}: {error_msg}")

        print(f"\n=== 保存完成 ===")
        print(f"成功保存: {question_count} 个问题")
        print(f"错误数量: {len(errors)}")

        return True

    except Exception as e:
        print(f"保存问题异常: {e}")
        import traceback
        traceback.print_exc()
        return False


@login_required
def create_questionnaire(request):
    if request.method == 'POST':
        import logging, traceback
        logger = logging.getLogger(__name__)
        logger.info('=== POST 开始 ===')
        try:
            save_action = request.POST.get('save_action')
            logger.info(f'save_action={save_action}')

            # 1. 先整体验证问卷主表单
            form = QuestionnaireForm(request.POST)
            if not form.is_valid():
                logger.error('主表单验证失败')
                for field, errs in form.errors.items():
                    logger.error(f'{field}: {errs}')
                return render(request, 'questionnaire/create.html', {
                    'form': form,
                    'question_formset': QuestionFormSet(request.POST),  # 继续回填
                })

            # 2. 验证问题表单集
            qformset = QuestionFormSet(request.POST)
            if not qformset.is_valid():
                logger.error('问题表单集验证失败')
                for i, qf in enumerate(qformset):
                    if qf.errors:
                        logger.error(f'问题{i}: {qf.errors}')
                return render(request, 'questionnaire/create.html', {
                    'form': form,
                    'question_formset': qformset,
                })

            logger.info('两级表单均通过，开始事务保存')
            # === 简答题专项日志 ===
            has_text = any(qf.cleaned_data.get('question_type') == 'text' for qf in qformset if qf.cleaned_data)
            logger.info(f'检测到简答题：{has_text}')
            if has_text:
                logger.info(f'问卷级max_length={form.cleaned_data.get("max_length")}')
                for i, qf in enumerate(qformset):
                    if qf.cleaned_data.get('question_type') == 'text':
                        logger.info(f'问题{i} max_length_field={qf.cleaned_data.get("max_length_field")}')
            # === 日志结束 ===
            # 3. 事务保存
            with transaction.atomic():
                questionnaire = form.save(commit=False)
                questionnaire.creator = request.user
                questionnaire.status = 'published'
                questionnaire.published_at = timezone.now()
                if questionnaire.access_type == 'invite':
                    questionnaire.invite_code = generate_invite_code()
                questionnaire.save()

                # 保存问题
                saved_questions = qformset.save()
                logger.info(f'published_at={questionnaire.published_at}')
                logger.info(f'updated_at={questionnaire.updated_at}')
                logger.info(f'问卷 {questionnaire.id} 已创建，问题数：{len(saved_questions)}')

            messages.success(request, '问卷发布成功！')
            return redirect('questionnaire_detail', questionnaire_id=questionnaire.id)

        except Exception as e:
            logger.error(f'发布异常: {e}', exc_info=True)
            messages.error(request, f'发布失败：{e}')
            return render(request, 'questionnaire/create.html', {
                'form': QuestionnaireForm(request.POST),
                'question_formset': QuestionFormSet(request.POST),
            })

    # GET 请求
    return render(request, 'questionnaire/create.html', {
        'form': QuestionnaireForm(),
        'question_formset': QuestionFormSet(),
    })

def validate_questions(request):
    """验证问题数据是否有效"""
    has_valid_question = False

    for key in request.POST:
        if key.startswith('questions-') and key.endswith('-text'):
            text = request.POST.get(key, '').strip()
            if text:
                has_valid_question = True
                break

    if not has_valid_question:
        return False, '请至少添加一个问题'

    return True, ''


def generate_invite_code(length=8):
    """生成唯一邀请码"""
    characters = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(characters, k=length))
        if not Questionnaire.objects.filter(invite_code=code).exists():
            return code


def generate_qrcode(request, questionnaire):
    """生成二维码"""
    # 构建问卷URL
    base_url = request.build_absolute_uri('/').rstrip('/')

    if questionnaire.access_type == 'invite' and questionnaire.invite_code:
        survey_url = f"{base_url}/invite/{questionnaire.invite_code}/"
    else:
        survey_url = f"{base_url}/survey/{questionnaire.id}/"

    # 生成二维码
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(survey_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # 保存到内存
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return buffer


def download_qrcode_response(questionnaire):
    """返回二维码下载响应"""
    if questionnaire.qr_code:
        response = HttpResponse(questionnaire.qr_code.read(), content_type='image/png')
        response['Content-Disposition'] = f'attachment; filename="qrcode_{questionnaire.title}.png"'
        return response
    else:
        # 如果没有二维码，生成一个
        # 这里需要request对象，所以简化处理
        return HttpResponse('二维码生成失败')


# 原有的其他函数保持不变
@login_required
def manage_questionnaire(request, questionnaire_id):
    """管理问卷"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id, creator=request.user)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'publish' and questionnaire.status == 'draft':
            questionnaire.status = 'published'
            questionnaire.save()
            messages.success(request, '问卷已发布！')

        elif action == 'close' and questionnaire.status == 'published':
            questionnaire.status = 'closed'
            questionnaire.save()
            messages.success(request, '问卷已结束！')

    return render(request, 'questionnaire/manage.html', {
        'questionnaire': questionnaire,
        'survey_url': f'/survey/{questionnaire.uuid}/'
    })


@login_required
def my_questionnaires(request):
    """我的问卷列表"""
    questionnaires = Questionnaire.objects.filter(creator=request.user).order_by('-created_at')
    return render(request, 'questionnaire/list.html', {
        'questionnaires': questionnaires
    })
