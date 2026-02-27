# qr_code_questionnaire/models.py
"""
数据模型，使用SM4加密敏感信息
"""
from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.utils import timezone
from django.core.validators import validate_email, RegexValidator
import uuid
import json
from questionnaire.utils.encryption import SM4EncryptedField
from questionnaire.utils.validators import validate_phone, validate_id_card


class CustomUserManager(BaseUserManager):
    """自定义用户管理器"""

    def create_user(self, username, email, password=None, **extra_fields):
        """创建普通用户"""
        if not email:
            raise ValueError("用户必须提供邮箱")

        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        """创建超级用户"""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("超级用户必须有 is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("超级用户必须有 is_superuser=True")

        return self.create_user(username, email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """自定义用户模型（SM4加密敏感信息）"""

    # 基础信息
    username = models.CharField(
        "用户名",
        max_length=50,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^[a-zA-Z0-9_]{3,50}$",
                message="用户名只能包含字母、数字和下划线，长度3-50位",
            )
        ],
    )
    email = models.EmailField("邮箱", unique=True, validators=[validate_email])

    # 加密存储的敏感信息
    real_name = SM4EncryptedField("真实姓名", max_length=50, blank=True)
    phone = SM4EncryptedField(
        "手机号", max_length=20, blank=True, validators=[validate_phone]
    )
    id_card = SM4EncryptedField(
        "身份证号", max_length=50, blank=True, validators=[validate_id_card]
    )

    # 用户状态和权限
    is_active = models.BooleanField("激活状态", default=True)
    is_staff = models.BooleanField("员工状态", default=False)
    is_verified = models.BooleanField("邮箱验证", default=False)

    # 安全字段
    login_attempts = models.IntegerField("登录尝试次数", default=0)
    locked_until = models.DateTimeField("锁定至", null=True, blank=True)
    last_login_ip = models.GenericIPAddressField("最后登录IP", null=True, blank=True)
    last_login_time = models.DateTimeField("最后登录时间", null=True, blank=True)

    # 时间戳
    date_joined = models.DateTimeField("注册时间", default=timezone.now)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = "用户"
        indexes = [
            models.Index(fields=["username"]),
            models.Index(fields=["email"]),
            models.Index(fields=["date_joined"]),
        ]

    def __str__(self):
        return self.username

    def get_full_name(self):
        """获取用户全名"""
        try:
            from questionnaire.utils.encryption import get_sm4_encryptor

            encryptor = get_sm4_encryptor()
            return (
                encryptor.decrypt(self.real_name) if self.real_name else self.username
            )
        except:
            return self.username

    def lock_account(self, minutes=30):
        """锁定账号"""
        self.locked_until = timezone.now() + timezone.timedelta(minutes=minutes)
        self.save(update_fields=["locked_until"])

    def unlock_account(self):
        """解锁账号"""
        self.locked_until = None
        self.login_attempts = 0
        self.save(update_fields=["locked_until", "login_attempts"])

    def is_locked(self):
        """检查账号是否被锁定"""
        if self.locked_until:
            return timezone.now() < self.locked_until
        return False


class Questionnaire(models.Model):
    """问卷模型"""

    STATUS_CHOICES = [
        ("draft", "草稿"),
        ("published", "已发布"),
        ("paused", "暂停"),
        ("closed", "已关闭"),
    ]

    # 基本信息
    title = models.CharField("问卷标题", max_length=200)
    description = models.TextField("问卷描述", blank=True)
    creator = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="questionnaires",
        verbose_name="创建者",
    )

    # 问卷设置（JSON格式存储）
    settings = models.JSONField("问卷设置", default=dict, blank=True)

    # 问卷状态
    status = models.CharField(
        "状态", max_length=20, choices=STATUS_CHOICES, default="draft"
    )
    published_at = models.DateTimeField("发布时间", null=True, blank=True)
    closed_at = models.DateTimeField("关闭时间", null=True, blank=True)

    # 时间戳
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    # 加密存储的额外信息
    confidential_notes = SM4EncryptedField("保密备注", blank=True)

    class Meta:
        verbose_name = "问卷"
        verbose_name_plural = "问卷"
        indexes = [
            models.Index(fields=["creator", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["status"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_active(self):
        """问卷是否活跃"""
        if self.status != "published":
            return False

        if self.settings.get("deadline"):
            from django.utils.dateparse import parse_datetime

            deadline = parse_datetime(self.settings["deadline"])
            if timezone.now() > deadline:
                return False

        return True


class Question(models.Model):
    """问题模型"""

    TYPE_CHOICES = [
        ("single", "单选题"),
        ("multiple", "多选题"),
        ("text", "文本题"),
        ("rating", "评分题"),
        ("matrix", "矩阵题"),
    ]

    questionnaire = models.ForeignKey(
        Questionnaire,
        on_delete=models.CASCADE,
        related_name="questions",
        verbose_name="问卷",
    )
    type = models.CharField("问题类型", max_length=20, choices=TYPE_CHOICES)
    title = models.TextField("问题标题")
    description = models.TextField("问题描述", blank=True)

    # 选项（JSON格式）
    options = models.JSONField("选项配置", default=list, blank=True)

    # 验证规则
    is_required = models.BooleanField("是否必填", default=False)
    validation_rules = models.JSONField("验证规则", default=dict, blank=True)

    # 排序和分组
    sort_order = models.IntegerField("排序序号", default=0)
    group = models.CharField("问题分组", max_length=100, blank=True)

    # 逻辑跳转
    logic_rules = models.JSONField("逻辑规则", default=dict, blank=True)

    class Meta:
        verbose_name = "问题"
        verbose_name_plural = "问题"
        indexes = [
            models.Index(fields=["questionnaire", "sort_order"]),
        ]
        ordering = ["questionnaire", "sort_order"]

    def __str__(self):
        return f"{self.questionnaire.title} - {self.title[:50]}"


class UserResponse(models.Model):
    """用户答卷模型（一人一码的核心）"""

    # 问卷和用户关联
    questionnaire = models.ForeignKey(
        Questionnaire,
        on_delete=models.CASCADE,
        related_name="responses",
        verbose_name="问卷",
    )
    user_code = models.CharField(
        "用户码",
        max_length=64,
        unique=True,
        db_index=True,
        help_text="唯一用户码，用于一人一码",
    )

    # 二维码信息
    qr_code_url = models.URLField("二维码链接", max_length=500, blank=True)
    qr_code_image = models.TextField("二维码图片base64", blank=True)

    # 访问信息（SM4加密敏感部分）
    ip_address = models.GenericIPAddressField("IP地址", protocol="both")
    user_agent = models.TextField("用户代理", blank=True)
    device_type = models.CharField("设备类型", max_length=20, blank=True)
    location_info = SM4EncryptedField("位置信息", blank=True)  # 加密存储

    # 时间信息
    start_time = models.DateTimeField("开始时间", null=True, blank=True)
    submit_time = models.DateTimeField("提交时间", null=True, blank=True)
    time_spent = models.IntegerField("耗时(秒)", null=True, blank=True)

    # 状态
    is_submitted = models.BooleanField("已提交", default=False)
    is_valid = models.BooleanField("有效答卷", default=True)

    # 加密的备注信息
    admin_notes = SM4EncryptedField("管理员备注", blank=True)

    # 时间戳
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "用户答卷"
        verbose_name_plural = "用户答卷"
        indexes = [
            models.Index(fields=["questionnaire", "is_submitted"]),
            models.Index(fields=["user_code"]),
            models.Index(fields=["ip_address"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["submit_time"]),
        ]
        unique_together = [["questionnaire", "user_code"]]

    def __str__(self):
        return f"{self.questionnaire.title} - {self.user_code}"

    def save(self, *args, **kwargs):
        """保存前自动生成用户码"""
        if not self.user_code:
            self.user_code = self.generate_user_code()
        super().save(*args, **kwargs)

    def generate_user_code(self):
        """生成唯一用户码"""
        import hashlib
        import time
        import random

        timestamp = int(time.time() * 1000)
        random_str = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=8))
        base_str = f"{self.questionnaire_id}_{timestamp}_{random_str}"

        # 生成MD5哈希
        return hashlib.md5(base_str.encode()).hexdigest()[:12].upper()

    @property
    def completion_rate(self):
        """答卷完成率（如果有多个部分的话）"""
        # 这里可以根据实际答题情况计算
        return 100 if self.is_submitted else 0


class Answer(models.Model):
    """答案模型"""

    response = models.ForeignKey(
        UserResponse,
        on_delete=models.CASCADE,
        related_name="answers",
        verbose_name="答卷",
    )
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="answers", verbose_name="问题"
    )

    # 答案内容（根据问题类型存储）
    answer_text = SM4EncryptedField("文本答案", blank=True)  # 加密存储
    answer_options = models.JSONField("选项答案", default=list, blank=True)
    answer_rating = models.IntegerField("评分答案", null=True, blank=True)

    # 元数据
    page_number = models.IntegerField("页面编号", default=1)
    answer_time = models.DateTimeField("答题时间", auto_now_add=True)

    class Meta:
        verbose_name = "答案"
        verbose_name_plural = "答案"
        indexes = [
            models.Index(fields=["response", "question"]),
            models.Index(fields=["question", "answer_rating"]),
        ]
        unique_together = [["response", "question"]]

    def __str__(self):
        return f"{self.response.user_code} - {self.question.title[:30]}"


class LoginLog(models.Model):
    """登录日志（审计用）"""

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="login_logs",
        verbose_name="用户",
    )
    username = models.CharField("用户名", max_length=50, db_index=True)

    # 登录信息
    ip_address = models.GenericIPAddressField("IP地址", protocol="both")
    user_agent = models.TextField("用户代理", blank=True)
    location = models.CharField("地理位置", max_length=100, blank=True)

    # 登录结果
    success = models.BooleanField("登录成功", default=False)
    failure_reason = models.CharField("失败原因", max_length=200, blank=True)

    # 验证码信息
    captcha_used = models.BooleanField("使用验证码", default=False)

    # 时间戳
    created_at = models.DateTimeField("登录时间", auto_now_add=True)

    class Meta:
        verbose_name = "登录日志"
        verbose_name_plural = "登录日志"
        indexes = [
            models.Index(fields=["username", "created_at"]),
            models.Index(fields=["ip_address", "created_at"]),
            models.Index(fields=["success", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        status = "成功" if self.success else "失败"
        return f"{self.username} - {status} - {self.created_at}"


class SecurityEvent(models.Model):
    """安全事件日志"""

    EVENT_TYPES = [
        ("brute_force", "暴力破解"),
        ("sqlinjection", "SQL注入尝试"),
        ("xss", "XSS攻击尝试"),
        ("csrf", "CSRF攻击"),
        ("file_upload", "恶意文件上传"),
        ("data_breach", "数据泄露尝试"),
        ("rate_limit", "频率限制"),
        ("blacklist_ip", "黑名单IP"),
    ]

    SEVERITY_LEVELS = [
        ("low", "低"),
        ("medium", "中"),
        ("high", "高"),
        ("critical", "严重"),
    ]

    # 事件信息
    event_type = models.CharField("事件类型", max_length=50, choices=EVENT_TYPES)
    severity = models.CharField("严重程度", max_length=20, choices=SEVERITY_LEVELS)
    description = models.TextField("事件描述")

    # 攻击者信息
    ip_address = models.GenericIPAddressField("IP地址", protocol="both")
    user_agent = models.TextField("用户代理", blank=True)
    request_path = models.CharField("请求路径", max_length=500)
    request_method = models.CharField("请求方法", max_length=10)

    # 请求数据（加密存储）
    request_data = SM4EncryptedField("请求数据", blank=True)
    request_headers = SM4EncryptedField("请求头", blank=True)

    # 响应和处置
    blocked = models.BooleanField("是否拦截", default=False)
    action_taken = models.CharField("处置措施", max_length=200, blank=True)

    # 用户关联（如果有的话）
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="关联用户"
    )

    # 时间戳
    created_at = models.DateTimeField("发生时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "安全事件"
        verbose_name_plural = "安全事件"
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["ip_address", "created_at"]),
            models.Index(fields=["severity", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.get_event_type_display()} - {self.ip_address} - {self.created_at}"
        )
