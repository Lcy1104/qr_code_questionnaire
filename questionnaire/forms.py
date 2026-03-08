from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from .models import Questionnaire, Question, Response, QuestionnaireQRCode
from django.utils import timezone
import json

User = get_user_model()


class LoginForm(forms.Form):
    """登录表单"""
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '用户名'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '密码'})
    )
    captcha = forms.CharField(
        max_length=6,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '验证码'})
    )

class RegForm(UserCreationForm):
    """注册表单"""
    email = forms.EmailField(
        required=False,  # 改为非必填
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': '邮箱（可选）'})
    )
    captcha = forms.CharField(
        max_length=6,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '验证码'})
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '用户名'}),
            'password1': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '密码'}),
            'password2': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '确认密码'}),
        }

    def clean_username(self):
        """验证用户名"""
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('用户名已存在')
        return username

    def clean_password2(self):
        """验证密码一致性"""
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')

        if password1 and password2 and password1 != password2:
            raise forms.ValidationError('两次输入的密码不一致')

        if password1 and len(password1) < 8:
            raise forms.ValidationError('密码至少需要8个字符')

        if password1 and password1.isdigit():
            raise forms.ValidationError('密码不能全是数字')

        return password2


class PwdResetForm(forms.Form):
    """密码重置表单"""
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '新密码'})
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '确认密码'})
    )
    captcha = forms.CharField(
        max_length=6,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '验证码'})
    )

    def clean(self):
        cleaned_data = super().clean()
        pwd1 = cleaned_data.get('new_password1')
        pwd2 = cleaned_data.get('new_password2')

        if pwd1 and pwd2 and pwd1 != pwd2:
            raise ValidationError('两次输入的密码不一致')

        return cleaned_data


class QuestionnaireForm(forms.ModelForm):
    start_time = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        label='开始时间'
    )
    end_time = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        label='截止时间'
    )
    limit_responses = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='限制提交份数'
    )
    max_responses = forms.IntegerField(
        required=False, min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '例如 100'}),
        label='最大提交份数'
    )
    enable_multi_qrcodes = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='生成多个一次性二维码'
    )
    targets = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4, 'class': 'form-control', 'placeholder': '每行一个人名'}),
        required=False,
        label='评价目标列表',
        help_text='输入可被评价的人名，每行一个。留空表示无需选择目标。'
    )

    class Meta:
        model = Questionnaire
        fields = [
            'title', 'description', 'access_type',
            'start_time', 'end_time', 'limit_responses', 'max_responses',
            'enable_multi_qrcodes', 'targets', # 新增
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'access_type': forms.Select(attrs={'class': 'form-select'}),
            'max_length': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.targets:
            # 将列表转换为 JSON 字符串（供前端隐藏字段使用）
            self.initial['targets'] = json.dumps(self.instance.targets, ensure_ascii=False)
            print(f"DEBUG: initial targets set to {self.initial['targets']}")
        else:
            self.initial['targets'] = '[]'

    def clean_targets(self):
        data = self.cleaned_data.get('targets', '')
        if not data:
            return []
        try:
            # 尝试解析 JSON
            targets = json.loads(data)
            if isinstance(targets, list):
                return targets
        except json.JSONDecodeError:
            pass
        # 兼容旧数据（按换行分割），可选
        return [line.strip() for line in data.splitlines() if line.strip()]

    def clean_start_time(self):
        return self.cleaned_data.get('start_time')

    def clean_end_time(self):
        return self.cleaned_data.get('end_time')

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_time')
        end = cleaned_data.get('end_time')
        limit = cleaned_data.get('limit_responses')
        max_resp = cleaned_data.get('max_responses')
        enable_multi = cleaned_data.get('enable_multi_qrcodes')

        if start and end and end <= start:
            raise ValidationError('截止时间必须晚于开始时间')

        if limit:
            if not max_resp:
                self.add_error('max_responses', '开启份数限制时必须填写最大提交份数')
            elif max_resp <= 0:
                self.add_error('max_responses', '最大提交份数必须为正整数')
        else:
            cleaned_data['max_responses'] = None

        if enable_multi:
            if not limit or not max_resp:
                self.add_error('enable_multi_qrcodes', '启用一次性二维码必须先开启份数限制并填写有效份数')

        return cleaned_data


class QuestionForm(forms.ModelForm):
    options_text = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        required=False,
        label='选项（每行一个）'
    )

    max_length_field = forms.IntegerField(
        min_value=0,
        initial=0,
        required=False,  # ① 表单层不再必填
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        label='字数限制'
    )

    class Meta:
        model = Question
        # ② 把模型里 required=True 的 max_length 排除掉，由我们手动赋值
        exclude = ['max_length']
        widgets = {
            'text': forms.TextInput(attrs={'class': 'form-control'}),
            'question_type': forms.Select(attrs={'class': 'form-select'}),
            'order': forms.HiddenInput(),
        }

    def clean(self):
        cleaned = super().clean()
        # ③ 简答题必须给值，其它题型默认 0
        if cleaned.get('question_type') == 'text':
            if cleaned.get('max_length_field') is None:
                self.add_error('max_length_field', '简答题必须填写字数限制（0 表示不限制）')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)

        # ④ 把表单值写回模型字段
        instance.max_length = self.cleaned_data.get('max_length_field', 0)

        # ⑤ 处理选项
        options_text = self.cleaned_data.get('options_text', '')
        if instance.question_type in ['radio', 'checkbox']:
            instance.options = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
        else:
            instance.options = []

        if commit:
            instance.save()
        return instance


# forms.py 底部
QuestionFormSet = forms.inlineformset_factory(
    Questionnaire,
    Question,
    form=QuestionForm,
    exclude=('max_length',),  # ① 完全交给表单自己去处理
    extra=1,
    can_delete=True,
    max_num=20,
)

class SelectTargetForm(forms.Form):
    """选择评价目标（第一步）"""
    target = forms.ChoiceField(
        widget=forms.RadioSelect,
        label='请选择被评价人'
    )

    def __init__(self, *args, targets_list=None, **kwargs):
        super().__init__(*args, **kwargs)
        if targets_list:
            self.fields['target'].choices = [(name, name) for name in targets_list]
