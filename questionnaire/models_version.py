"""
版本控制相关模型 - 使用代理模式，不修改原有模型结构
"""
from django.db import models
import uuid
from .encrypted_fields import EncryptedTextField, EncryptedCharField, EncryptedJSONField


class QuestionSnapshot(models.Model):
    """
    问题快照模型
    用于记录问题的历史版本，但完全不修改Question模型
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # 不直接关联Question，只存储ID和版本信息
    original_question_id = models.UUIDField(verbose_name='原问题ID')
    questionnaire_id = models.UUIDField(verbose_name='问卷ID')

    # 版本信息
    version_number = models.IntegerField(default=1, verbose_name='版本号')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    # 问题内容（完整复制）
    text = EncryptedTextField(verbose_name='问题内容')
    question_type = models.CharField(
        max_length=20,
        choices=[
            ('radio', '单选题'),
            ('checkbox', '多选题'),
            ('text', '简答题'),
        ],
        default='radio',
        verbose_name='题型'
    )
    order = models.IntegerField(default=0, verbose_name='排序')
    required = models.BooleanField(default=True, verbose_name='必填')
    options = EncryptedJSONField(default=list, blank=True, verbose_name='选项（JSON格式）')
    max_length = models.PositiveIntegerField(default=0, blank=True, null=True, verbose_name='字数限制')

    # 元数据
    metadata = models.JSONField(default=dict, blank=True, verbose_name='元数据')

    class Meta:
        ordering = ['original_question_id', '-version_number']
        unique_together = ['original_question_id', 'version_number']
        verbose_name = '问题快照'
        verbose_name_plural = '问题快照'

    def __str__(self):
        return f"问题快照 v{self.version_number}"


class QuestionnaireSnapshot(models.Model):
    """
    问卷快照
    每次发布时保存完整的问卷状态
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    questionnaire_id = models.UUIDField(verbose_name='问卷ID')
    version_number = models.IntegerField(default=1, verbose_name='版本号')
    snapshot_data = models.JSONField(verbose_name='快照数据')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    published_at = models.DateTimeField(null=True, blank=True, verbose_name='发布时间')

    class Meta:
        ordering = ['questionnaire_id', '-version_number']
        verbose_name = '问卷快照'
        verbose_name_plural = '问卷快照'

    def __str__(self):
        return f"问卷快照 v{self.version_number}"