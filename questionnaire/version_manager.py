"""
版本管理工具类 - 不修改原始模型
"""
from django.utils import timezone
import json
import logging
from .models_version import QuestionSnapshot, QuestionnaireSnapshot

logger = logging.getLogger(__name__)


class VersionManager:
    """版本管理器"""

    @staticmethod
    def create_question_snapshot(question):
        """
        创建问题快照
        参数question是原始的Question对象
        """
        try:
            # 获取当前版本号
            last_snapshot = QuestionSnapshot.objects.filter(
                original_question_id=question.id
            ).order_by('-version_number').first()

            version_number = last_snapshot.version_number + 1 if last_snapshot else 1

            # 创建快照
            snapshot = QuestionSnapshot.objects.create(
                original_question_id=question.id,
                questionnaire_id=question.questionnaire.id,
                version_number=version_number,
                text=question.text,
                question_type=question.question_type,
                order=question.order,
                required=question.required,
                options=question.options,
                max_length=question.max_length,
                metadata={
                    'created_at': question.created_at.isoformat() if question.created_at else None,
                    'updated_at': question.updated_at.isoformat() if hasattr(question, 'updated_at') else None,
                    'answer_count': question.answer_items.count() if hasattr(question, 'answer_items') else 0,
                }
            )

            logger.info(f"[VERSION] 创建问题快照: {question.id} -> v{version_number}")
            return snapshot

        except Exception as e:
            logger.error(f"[VERSION] 创建问题快照失败: {e}")
            return None

    @staticmethod
    def create_questionnaire_snapshot(questionnaire):
        """创建问卷快照"""
        try:
            # 获取所有问题
            questions_data = []
            for question in questionnaire.questions.all().order_by('order'):
                questions_data.append({
                    'id': str(question.id),
                    'text': question.text,
                    'question_type': question.question_type,
                    'order': question.order,
                    'required': question.required,
                    'options': question.options,
                    'max_length': question.max_length,
                })

            snapshot_data = {
                'questionnaire_id': str(questionnaire.id),
                'title': questionnaire.title,
                'description': questionnaire.description,
                'version': questionnaire.version,
                'status': questionnaire.status,
                'created_at': timezone.now().isoformat(),
                'questions': questions_data,
            }

            # 获取当前版本号
            last_snapshot = QuestionnaireSnapshot.objects.filter(
                questionnaire_id=questionnaire.id
            ).order_by('-version_number').first()

            version_number = last_snapshot.version_number + 1 if last_snapshot else 1

            snapshot = QuestionnaireSnapshot.objects.create(
                questionnaire_id=questionnaire.id,
                version_number=version_number,
                snapshot_data=snapshot_data,
                published_at=questionnaire.published_at,
            )

            logger.info(f"[VERSION] 创建问卷快照: {questionnaire.id} -> v{version_number}")
            return snapshot

        except Exception as e:
            logger.error(f"[VERSION] 创建问卷快照失败: {e}")
            return None

    @staticmethod
    def get_question_history(question_id):
        """获取问题历史版本 - 支持整数ID"""
        from .models_version import QuestionSnapshot

        # 查找问题快照
        snapshots = QuestionSnapshot.objects.filter(
            original_question_id=str(question_id)
        ).order_by('-version_number')

        return snapshots

    @staticmethod
    def get_questionnaire_history(questionnaire_id):
        """获取问卷历史版本"""
        return QuestionnaireSnapshot.objects.filter(
            questionnaire_id=questionnaire_id
        ).order_by('-version_number')