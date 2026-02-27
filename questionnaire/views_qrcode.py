# questionnaire/views_qrcode.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest
import qrcode
from io import BytesIO
import base64
from django.core.files.base import ContentFile
from django.conf import settings
import socket

from django.utils import timezone

from .models import Questionnaire
import secrets
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from .models import QuestionnaireQRCode
from django.urls import reverse

def get_server_base_url(request: HttpRequest) -> str:
    """获取服务器基础URL"""
    # 优先使用配置的SERVER_URL - 这是最佳实践
    if hasattr(settings, 'SERVER_URL') and settings.SERVER_URL:
        return settings.SERVER_URL.rstrip('/')

    # 开发环境：获取本机IP - 自动适应开发环境
    if settings.DEBUG:
        try:
            # 获取本机IP
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)

            # 构建URL
            if request.get_port() == '80':
                return f"http://{local_ip}"
            else:
                return f"http://{local_ip}:{request.get_port()}"
        except:
            # 回退到请求的host - 优雅的降级
            return request.build_absolute_uri('/').rstrip('/')

    # 生产环境：使用请求的host - 安全可靠
    return request.build_absolute_uri('/').rstrip('/')


def generate_qrcode_for_questionnaire(request, questionnaire):
    """为问卷生成二维码并保存（可复用的函数）"""
    # 构建问卷访问URL
    if questionnaire.access_type == 'invite' and questionnaire.invite_code:
        survey_url = request.build_absolute_uri(f'/invite/{questionnaire.invite_code}/')
    else:
        from django.urls import reverse
        survey_url = request.build_absolute_uri(reverse('survey_landing', args=[questionnaire.id]))

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

    # 保存到问卷模型
    if questionnaire.qr_code:
        # 删除旧的二维码文件
        questionnaire.qr_code.delete(save=False)

    # 保存新的二维码
    questionnaire.qr_code.save(
        f'qrcode_{questionnaire.id}.png',
        ContentFile(buffer.getvalue())
    )
    questionnaire.save()

    # 返回二维码的URL
    if questionnaire.qr_code and hasattr(questionnaire.qr_code, 'url'):
        return request.build_absolute_uri(questionnaire.qr_code.url)
    return ''


@login_required
def generate_qrcode(request, questionnaire_id):
    """生成问卷二维码页面"""
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id, creator=request.user)

    # 使用上面的函数生成二维码
    qr_code_url = generate_qrcode_for_questionnaire(request, questionnaire)

    # 获取问卷访问URL
    if questionnaire.access_type == 'invite' and questionnaire.invite_code:
        survey_url = request.build_absolute_uri(f'/invite/{questionnaire.invite_code}/')
    else:
        from django.urls import reverse
        survey_url = request.build_absolute_uri(reverse('survey_landing', args=[questionnaire.id]))

    # 为显示页面生成Base64格式的二维码
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(survey_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    img_base64 = base64.b64encode(buffer.getvalue()).decode()

    return render(request, 'questionnaire/qrcode_display.html', {
        'questionnaire': questionnaire,
        'survey_url': survey_url,
        'qr_code_base64': f"data:image/png;base64,{img_base64}"
    })

def generate_multi_qrcodes_for_questionnaire(request, questionnaire):
    """为问卷生成多个一次性二维码"""
    count = questionnaire.max_responses
    if not count or count <= 0:
        return

    # 清除旧的二维码（如果重新生成）
    questionnaire.qrcodes.all().delete()

    qrcodes = []
    #base_url = request.build_absolute_uri('/').rstrip('/')
    '''
    for i in range(count):
        # 生成唯一标识（16位安全随机字符串）
        qr_code_id = secrets.token_urlsafe(16)[:16]
        # 构建访问链接
        survey_url = f"{base_url}/qrcode/{qr_code_id}/"

        # 生成二维码图片
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

        # 创建模型实例
        qrcode_obj = QuestionnaireQRCode(
            questionnaire=questionnaire,
            qr_code_id=qr_code_id,
        )
        # 保存图片文件
        filename = f'multi_qrcode_{questionnaire.id}_{i}.png'
        qrcode_obj.qr_code_image.save(
            filename,
            ContentFile(buffer.getvalue()),
            save=False
        )
        qrcodes.append(qrcode_obj)
    '''
    for i in range(count):
        qr_code_id = secrets.token_urlsafe(16)[:16]
        qrcodes.append(QuestionnaireQRCode(
            questionnaire=questionnaire,
            qr_code_id=qr_code_id,
        ))
    # 批量保存
    QuestionnaireQRCode.objects.bulk_create(qrcodes)

@require_POST
def mark_qrcode_shared(request, qr_code_id):
    """标记二维码为已分享（当用户复制链接时调用）"""
    try:
        qrcode = QuestionnaireQRCode.objects.get(qr_code_id=qr_code_id)
        qrcode.is_shared = True
        qrcode.save(update_fields=['is_shared'])
        return JsonResponse({'success': True})
    except QuestionnaireQRCode.DoesNotExist:
        return JsonResponse({'success': False, 'error': '二维码不存在'}, status=404)

def qrcode_access(request, qr_code_id):
    """通过一次性二维码访问问卷"""
    qrcode = get_object_or_404(QuestionnaireQRCode, qr_code_id=qr_code_id)
    if qrcode.is_used:
        return render(request, 'error.html', {'message': '该二维码已被使用'})
    # 标记为已分享（如果尚未），确保普通提交不会抢走
    if not qrcode.is_shared:
        qrcode.is_shared = True
        qrcode.save(update_fields=['is_shared'])
    # 将二维码ID存入 session，供提交时使用
    request.session['active_qrcode_id'] = qr_code_id
    return redirect('survey_landing', survey_uuid=qrcode.questionnaire.id)

def get_qrcode_image(request, qr_code_id):
    qrcode_obj = get_object_or_404(QuestionnaireQRCode, qr_code_id=qr_code_id)
    survey_url = request.build_absolute_uri(reverse('qrcode_access', args=[qr_code_id]))

    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(survey_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    response = HttpResponse(buffer.getvalue(), content_type='image/png')

    # 缓存策略
    if qrcode_obj.is_shared and not qrcode_obj.is_used:
        # 已共享：允许缓存1小时，减少重复生成
        response['Cache-Control'] = 'public, max-age=3600'
    elif qrcode_obj.questionnaire.end_time and qrcode_obj.questionnaire.end_time < timezone.now() and not qrcode_obj.is_used:
        # 已过期且未使用：禁止缓存
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
    else:
        # 可用或未共享：禁止缓存，确保每次请求都是最新的
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'

    return response