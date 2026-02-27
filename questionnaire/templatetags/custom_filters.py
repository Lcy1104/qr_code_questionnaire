from django import template

register = template.Library()

@register.filter
def split_lines(value):
    """将文本按行分割为列表"""
    if not value:
        return []
    return [line.strip() for line in str(value).split('\n') if line.strip()]

@register.filter
def letter(number):
    """将数字转换为字母 (1->A, 2->B, ...)"""
    return chr(64 + int(number)) if 1 <= number <= 26 else str(number)