# questionnaire/utils/qrcode.py
import qrcode
from io import BytesIO
from django.core.files.base import ContentFile
from django.conf import settings


def generate_qr_code_for_questionnaire(questionnaire, request):
    """为问卷生成二维码并保存"""
    # 生成访问URL
    survey_url = request.build_absolute_uri(f'/survey/{questionnaire.uuid}/')

    # 创建二维码
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(survey_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # 保存到ImageField
    buffer = BytesIO()
    img.save(buffer, format='PNG')

    filename = f'qr_{questionnaire.uuid}.png'
    questionnaire.qr_code_image.save(filename, ContentFile(buffer.getvalue()))
    questionnaire.save()

    return questionnaire.qr_code_image.url