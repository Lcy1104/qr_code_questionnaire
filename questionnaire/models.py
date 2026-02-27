# questionnaire/models.py
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.db import transaction, models
import uuid
from .encrypted_fields import EncryptedTextField, EncryptedCharField, EncryptedJSONField
from django.conf import settings


class User(AbstractUser):
    """自定义用户模型"""
    USER_TYPE_CHOICES = [
        ('admin', '管理员'),
        ('user', '普通用户'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default='user', verbose_name='用户类型')
    phone = EncryptedCharField(max_length=20, blank=True, verbose_name='手机号')
    real_name = EncryptedCharField(max_length=150, blank=True, verbose_name='真实姓名')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_original_admin = models.BooleanField(
        default=False,
        verbose_name='原始管理员',
        help_text='只有原始管理员可以设置/移除其他管理员'
    )

    class Meta:
        db_table = 'users'
        verbose_name = '用户'
        verbose_name_plural = '用户'

    def save(self, *args, **kwargs):
        # 如果是更新操作，确保字段被保存
        if self.pk:
            # 调用父类的 save 方法
            super().save(*args, **kwargs)
        else:
            # 新建用户
            super().save(*args, **kwargs)

    def __str__(self):
        if self.is_original_admin:
            return f"{self.username} ⭐"
        return self.username

    @property
    def is_admin(self):
        return self.user_type == 'admin' or self.is_superuser or self.is_staff

    @is_admin.setter
    def is_admin(self, value):
        """
        设置用户是否为管理员
        直接设置 is_superuser 字段
        """
        self.is_superuser = value
        # 如果是管理员，也设置为 staff（以便访问管理后台）
        if value:
            self.is_staff = True

    @classmethod
    def create_user(cls, username, password, **extra_fields):
        """创建用户并确保加密字段正确保存"""
        # 确保 user_type 有默认值
        if 'user_type' not in extra_fields:
            extra_fields['user_type'] = 'user'

        # 使用父类的 create_user 方法
        user = super().create_user(username=username, password=password, **extra_fields)
        return user


class Questionnaire(models.Model):
    """问卷模型"""
    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('published', '已发布'),
        ('closed', '已关闭'),
        ('modified', '已修改'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = EncryptedCharField(max_length=200, verbose_name='问卷标题')
    description = EncryptedTextField(blank=True, verbose_name='问卷描述')
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_questionnaires',
                                verbose_name='创建者')

    # 发布设置
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft', verbose_name='状态')
    version = models.IntegerField(default=1, verbose_name='版本号')
    access_type = models.CharField(max_length=20,
                                   choices=[('public', '公开'), ('private', '私有'), ('invite', '仅邀请')],
                                   default='public', verbose_name='访问权限')
    invite_code = models.CharField(max_length=20, unique=True, null=True, blank=True, verbose_name='邀请码')
    limit_responses = models.BooleanField(
        default=False,
        verbose_name='限制提交份数'
    )
    max_responses = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='最大提交份数',
        help_text='当限制提交份数时，设置最大可提交数量'
    )

    # 二维码
    enable_multi_qrcodes = models.BooleanField(
        default=False,
        verbose_name='启用多个一次性二维码'
    )
    qr_code = models.ImageField(upload_to='qrcodes/', blank=True, null=True, verbose_name='二维码')
    qr_code_id = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
        verbose_name='二维码标识'
    )

    # 时间
    start_time = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    end_time = models.DateTimeField(null=True, blank=True, verbose_name='结束时间')

    # 统计
    view_count = models.IntegerField(default=0, verbose_name='浏览次数')
    submit_count = models.IntegerField(default=0, verbose_name='提交次数')

    notified_users = EncryptedJSONField(default=list, blank=True, verbose_name='已通知用户')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 保存旧状态用于比较
        self._original_status = self.status

    def save(self, *args, **kwargs):
        # 使用事务确保数据一致性
        with transaction.atomic():
            # 保存前获取旧版本
            old_version = None
            old_title = None
            old_description = None

            current_user = None

            try:
                # 方法1：通过Django的request上下文获取
                from django.core.handlers.wsgi import WSGIHandler

                # 尝试获取当前请求
                import inspect
                for frame_info in inspect.stack():
                    frame = frame_info.frame
                    # 在调用栈中查找request对象
                    if 'request' in frame.f_locals:
                        request = frame.f_locals['request']
                        if hasattr(request, 'user') and request.user.is_authenticated:
                            current_user = request.user
                            # 保存当前用户到实例属性，供通知方法使用
                            self._current_modifier = current_user
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.info(f"[SAVE] 从调用栈获取到用户: {current_user.username}")
                            break

            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"[SAVE] 获取当前用户失败: {e}")

            # 如果是已发布的问卷进行修改，则状态改为"已修改"
            if self.pk:  # 如果已存在（不是新建）
                try:
                    old = Questionnaire.objects.select_for_update().get(pk=self.pk)
                    old_version = old.version
                    old_title = old.title
                    old_description = old.description

                    # 状态从published改为其他状态（除closed外）
                    if old.status == 'published' and self.status != 'published' and self.status != 'closed':
                        self.status = 'modified'
                        self.version += 1

                    # 如果是发布操作
                    if old.status != 'published' and self.status == 'published':
                        if not self.published_at:
                            self.published_at = timezone.now()

                        # 生成邀请码（如果需要）
                        if self.access_type == 'invite' and not self.invite_code:
                            import secrets
                            import string
                            alphabet = string.ascii_uppercase + string.digits
                            self.invite_code = ''.join(secrets.choice(alphabet) for i in range(8))
                except Questionnaire.DoesNotExist:
                    pass

            super().save(*args, **kwargs)
            if old_version and self.version > old_version:
                # 问卷版本更新，发送通知
                updated_fields = []

                if old_title != self.title:
                    updated_fields.append('标题')
                if old_description != self.description:
                    updated_fields.append('描述')

                # 异步发送问卷更新通知 - 修复：使用正确的导入和调用
                try:
                    # 如果有获取到的当前用户，使用它
                    if hasattr(self, '_current_modifier'):
                        modifier = self._current_modifier
                        self._send_questionnaire_update_notification(updated_fields, modifier)
                    else:
                        self._send_questionnaire_update_notification(updated_fields)
                except Exception as e:
                    # 记录错误但不中断保存流程
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"发送问卷更新通知失败: {e}")

            # 保存后更新原始状态
            self._original_status = self.status

            # 如果问卷状态从published变为modified，异步发送通知
            if hasattr(self, '_original_status') and self._original_status == 'published' and self.status == 'modified':
                self._send_update_notifications_async()

    def _send_questionnaire_update_notification(self, updated_fields, modifier=None):
        """发送问卷更新通知给所有之前填写过问卷的用户

        最小修改：添加modifier参数，保持原函数签名兼容
        """
        try:
            # 关键修改：如果有传入的modifier就使用，否则使用问卷创建者
            if modifier is None:
                modifier = self.creator

            # 构建通知内容
            notification_type = 'questionnaire_update'
            title = f"问卷更新通知：{self.title}"

            # 构建详细的变更描述
            change_details = []
            if '标题' in updated_fields:
                change_details.append("修改了问卷标题")
            if '描述' in updated_fields:
                change_details.append("修改了问卷描述")
            if not change_details and updated_fields:
                change_details.append(f"修改了{len(updated_fields)}个字段")

            # 完整的消息内容 - 使用正确的修改者
            message = f"""
            问卷《{self.title}》已经更新。

            修改详情：
            {chr(10).join(f"- {detail}" for detail in change_details)}

            修改者：{modifier.username if modifier else '系统'}
            修改时间：{timezone.now().strftime('%Y年%m月%d日 %H:%M:%S')}
            问卷版本：{self.version}

            您可以重新访问问卷查看最新内容。
            """

            # 获取所有填写过问卷的用户
            from .models import Response

            responses = Response.objects.filter(
                questionnaire=self,
                is_submitted=True
            ).select_related('user')

            users = set()
            for response in responses:
                if response.user and response.user.is_active:
                    users.add(response.user)

            # 发送通知给每个用户
            notifications = []
            from .notification_manager import NotificationManager

            for user in users:
                try:
                    notification = NotificationManager.create_notification(
                        user=user,
                        title=title,
                        message=message.strip(),
                        notification_type=notification_type,
                        related_questionnaire=self,
                        priority='normal'
                    )
                    if notification:
                        notifications.append(notification)

                        # 记录发送日志
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.info(f"问卷更新通知发送给用户 {user.username}: {notification.id}")

                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"给用户 {user.username} 发送问卷更新通知失败: {e}")

            # 记录发送结果
            import logging
            logger = logging.getLogger(__name__)
            if notifications:
                logger.info(f"问卷 {self.id} 更新通知发送完成，成功发送给 {len(notifications)} 个用户")
            else:
                logger.warning(f"问卷 {self.id} 更新通知发送完成，但未找到可通知的用户")

            return notifications

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"发送问卷更新通知失败: {e}")
            return []

    def _send_update_notifications_async(self):
        """异步发送更新通知"""
        try:
            import threading
            from .simple_notification import send_update_notifications

            def send_notifications_async():
                try:
                    result = send_update_notifications(self.id)
                    if result.get('sent', 0) > 0:
                        print(f"已发送 {result['sent']} 个更新通知")
                except Exception as e:
                    print(f"发送通知失败: {e}")

            thread = threading.Thread(target=send_notifications_async)
            thread.daemon = True
            thread.start()
        except Exception as e:
            print(f"启动通知线程失败: {e}")

    def can_be_accessed_by(self, user=None, invite_code=None):
        """检查用户是否有权限访问问卷"""
        if self.status not in ['published', 'modified']:
            return False, '问卷未发布'

        # 检查时间限制
        now = timezone.now()
        if self.start_time and now < self.start_time:
            return False, '问卷尚未开始'
        if self.end_time and now > self.end_time:
            return False, '问卷已结束'

        # 检查访问权限
        if self.access_type == 'public':
            return True, '允许访问'
        elif self.access_type == 'private':
            if user and user.is_authenticated:
                return True, '允许访问'
            return False, '需要登录'
        elif self.access_type == 'invite':
            if invite_code == self.invite_code:
                return True, '允许访问'
            return False, '需要邀请码'

        return False, '无访问权限'

    @property
    def is_active(self):
        """问卷是否活跃（可填写）"""
        now = timezone.now()
        if self.status not in ['published', 'modified']:
            return False
        if self.start_time and now < self.start_time:
            return False
        if self.end_time and now > self.end_time:
            return False
        return True

    class Meta:
        ordering = ['-created_at']
        verbose_name = '问卷'
        verbose_name_plural = '问卷'

    def __str__(self):
        return str(self.title)  # 加密字段直接转为字符串


class Question(models.Model):
    """问题模型"""
    TYPE_CHOICES = [
        ('radio', '单选题'),
        ('checkbox', '多选题'),
        ('text', '简答题'),
    ]

    questionnaire = models.ForeignKey(Questionnaire, on_delete=models.CASCADE, related_name='questions')
    text = EncryptedTextField(verbose_name='问题内容')
    question_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='radio', verbose_name='题型')
    order = models.IntegerField(default=0, verbose_name='排序')
    required = models.BooleanField(default=True, verbose_name='必填')
    options = EncryptedJSONField(default=list, blank=True, verbose_name='选项（JSON格式）')
    max_length = models.PositiveIntegerField(
        default=0,
        blank=True,  # ① 表单允许不填
        null=True,  # ② 数据库允许为空
        verbose_name='字数限制（0为不限制）'
    )

    def clean(self):
        """验证数据"""
        from django.core.exceptions import ValidationError

        # 如果是选择题，确保有选项
        if self.question_type in ['radio', 'checkbox']:
            if not self.options or len(self.options) == 0:
                raise ValidationError('选择题必须至少有一个选项')

            # 检查选项是否为空
            for i, option in enumerate(self.options):
                if not option.strip():
                    raise ValidationError(f'第{i + 1}个选项不能为空')

        # 如果是简答题，确保max_length合理
        if self.question_type == 'text' and self.max_length < 0:
            raise ValidationError('字数限制不能为负数')

    def get_options_display(self):
        """获取显示的选项列表"""
        if self.question_type in ['radio', 'checkbox']:
            return [(chr(65 + i), option) for i, option in enumerate(self.options)]
        return []

    class Meta:
        ordering = ['order']
        unique_together = ['questionnaire', 'order']

    def __str__(self):
        return f"Q{self.order}: {self.text[:50]}"


class Response(models.Model):
    """答卷模型"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    questionnaire = models.ForeignKey(Questionnaire, on_delete=models.CASCADE, related_name='responses')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='responses', null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True)
    is_submitted = models.BooleanField(default=True, verbose_name='已提交')
    completion_time = models.IntegerField(null=True, blank=True, verbose_name='完成时间')
    questionnaire_version = models.IntegerField(default=1, verbose_name='问卷版本')
    device_fingerprint = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        verbose_name='设备指纹'
    )
    qrcode = models.ForeignKey(
        'QuestionnaireQRCode',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='responses',
        verbose_name='使用的二维码'
    )

    class Meta:
        ordering = ['-submitted_at']
        unique_together = ['questionnaire', 'user', 'questionnaire_version']

    def __str__(self):
        return f"{self.user.username if self.user else '匿名'} - {self.questionnaire.title}"

    def save(self, *args, **kwargs):
        """保存时自动记录问卷版本"""
        if not self.questionnaire_version:
            self.questionnaire_version = self.questionnaire.version
        super().save(*args, **kwargs)

    @property
    def needs_update(self):
        """检查是否需要更新（如果问卷版本更新了）"""
        return self.questionnaire_version < self.questionnaire.version

    @property
    def is_complete(self):
        """检查答卷是否完整"""
        if not self.is_submitted:
            return False

        # 检查所有必填问题是否已回答
        required_questions = self.questionnaire.questions.filter(required=True)
        answered_questions = Answer.objects.filter(response=self, question__in=required_questions)

        return answered_questions.count() == required_questions.count()


class Answer(models.Model):
    """单个问题答案模型"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    response = models.ForeignKey(Response, on_delete=models.CASCADE, related_name='answer_items')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    answer_text = EncryptedTextField(verbose_name='答案内容')
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        """验证答案"""
        from django.core.exceptions import ValidationError

        # 检查必填问题
        if self.question.required and not self.answer_text.strip():
            raise ValidationError('必填问题不能为空')

        # 检查答案长度
        if self.question.max_length > 0 and len(self.answer_text) > self.question.max_length:
            raise ValidationError(f'答案长度不能超过{self.question.max_length}个字符')

        # 检查选择题答案是否在选项范围内
        if self.question.question_type == 'radio':
            if self.answer_text not in [chr(65 + i) for i in range(len(self.question.options))]:
                raise ValidationError('单选题答案必须在选项范围内')

        elif self.question.question_type == 'checkbox':
            answers = self.answer_text.split(',')
            valid_options = [chr(65 + i) for i in range(len(self.question.options))]
            for ans in answers:
                if ans not in valid_options:
                    raise ValidationError(f'多选题答案包含无效选项: {ans}')

    class Meta:
        ordering = ['created_at']
        verbose_name = '答案'
        verbose_name_plural = '答案'
        unique_together = ['response', 'question']

    def __str__(self):
        return f"{self.question.text[:50]}: {self.answer_text[:50]}"


class UserResponse(models.Model):
    """用户答卷：按（问卷+用户+版本）唯一，版本更新后可重新填"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    questionnaire = models.ForeignKey(
        'Questionnaire', on_delete=models.CASCADE,
        related_name='user_responses')  # 避免冲突
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='user_responses')  # 避免冲突
    submitted_at = models.DateTimeField(auto_now_add=True)
    questionnaire_version = models.PositiveIntegerField(
        default=1, help_text='提交时问卷版本号')

    class Meta:
        unique_together = ('questionnaire', 'user', 'questionnaire_version')

    def __str__(self):
        return f'{self.user} - {self.questionnaire.title} v{self.questionnaire_version}'

class Notification(models.Model):
    """消息通知模型"""
    NOTIFICATION_TYPES = [
        ('questionnaire_update', '问卷更新'),
        ('system', '系统通知'),
        ('admin', '管理员通知'),
        ('other', '其他'),
    ]

    PRIORITY_CHOICES = [
        ('low', '低'),
        ('normal', '正常'),
        ('high', '高'),
        ('urgent', '紧急'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='接收用户'
    )
    notification_type = models.CharField(
        max_length=50,
        choices=NOTIFICATION_TYPES,
        default='system',
        verbose_name='通知类型'
    )
    title = models.CharField(max_length=200, verbose_name='通知标题')
    message = models.TextField(verbose_name='通知内容')
    related_questionnaire = models.ForeignKey(
        'Questionnaire',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications',
        verbose_name='相关问卷'
    )
    is_read = models.BooleanField(default=False, verbose_name='已读')
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default='normal',
        verbose_name='优先级'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    # 发送状态字段
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name='发送时间')
    delivery_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', '待发送'),
            ('sent', '已发送'),
            ('failed', '发送失败'),
            ('read', '已读')
        ],
        default='pending',
        verbose_name='发送状态'
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = '通知'
        verbose_name_plural = '通知'

    def __str__(self):
        return f"{self.title} - {self.user.username}"

    def mark_as_read(self):
        """标记为已读"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.delivery_status = 'read'
            self.save()

    def mark_as_sent(self):
        """标记为已发送"""
        if not self.sent_at:
            self.sent_at = timezone.now()
            self.delivery_status = 'sent'
            self.save()

    @property
    def time_since(self):
        """返回创建时间的相对描述"""
        from django.utils.timesince import timesince
        return timesince(self.created_at) + '前'

    @property
    def is_active(self):
        """通知是否有效（未删除）"""
        return self.delivery_status != 'failed'


class NotificationSettings(models.Model):
    """用户通知设置"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_settings',
        verbose_name='用户'
    )
    receive_questionnaire_updates = models.BooleanField(
        default=True,
        verbose_name='接收问卷更新通知'
    )
    receive_system_notifications = models.BooleanField(
        default=True,
        verbose_name='接收系统通知'
    )
    receive_admin_notifications = models.BooleanField(
        default=True,
        verbose_name='接收管理员通知'
    )
    receive_urgent_notifications = models.BooleanField(
        default=True,
        verbose_name='接收紧急通知'
    )
    email_notifications = models.BooleanField(
        default=False,
        verbose_name='邮件通知'
    )
    push_notifications = models.BooleanField(
        default=True,
        verbose_name='站内推送'
    )

    class Meta:
        verbose_name = '通知设置'
        verbose_name_plural = '通知设置'

    def __str__(self):
        return f"{self.user.username} 的通知设置"

class QuestionnaireQRCode(models.Model):
    """问卷的多个一次性二维码"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    questionnaire = models.ForeignKey(
        'Questionnaire',
        on_delete=models.CASCADE,
        related_name='qrcodes',
        verbose_name='所属问卷'
    )
    qr_code_id = models.CharField(
        max_length=50,
        unique=True,
        verbose_name='二维码唯一标识'
    )
    qr_code_image = models.ImageField(
        upload_to='qrcodes/multi/',
        blank=True,
        null=True,
        verbose_name='二维码图片'
    )
    is_shared = models.BooleanField(
        default=False,
        verbose_name='是否已分享'
    )
    is_used = models.BooleanField(default=False, verbose_name='是否已使用')
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name='使用用户'
    )
    used_at = models.DateTimeField(null=True, blank=True, verbose_name='使用时间')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = '问卷二维码'
        verbose_name_plural = '问卷二维码'

    def __str__(self):
        return f'{self.questionnaire.title} - {self.qr_code_id}'

    def mark_as_used(self, user=None):
        """标记二维码为已使用"""
        self.is_used = True
        self.used_by = user
        self.used_at = timezone.now()
        self.save(update_fields=['is_used', 'used_by', 'used_at'])
