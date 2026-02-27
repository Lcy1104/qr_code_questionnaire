# questionnaire/utils/validators.py
from django.core.exceptions import ValidationError

def validate_phone(value):
    if not value.isdigit() or len(value) != 11:
        raise ValidationError('请输入有效的手机号码')

def validate_id_card(value):
    if len(value) != 18 or not value.isdigit():
        raise ValidationError('请输入有效的身份证号码')