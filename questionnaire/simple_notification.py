"""
问卷更新通知服务
"""
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from .models import Questionnaire, Response
import logging

logger = logging.getLogger(__name__)


def send_update_notifications(questionnaire_id):
    """发送问卷更新通知"""
    try:
        questionnaire = Questionnaire.objects.get(id=questionnaire_id)

        # 只处理已修改状态的问卷
        if questionnaire.status != 'modified':
            return {"sent": 0, "errors": []}

        # 获取所有已提交的用户
        responses = Response.objects.filter(
            questionnaire=questionnaire,
            is_submitted=True,
            user__isnull=False
        ).select_related('user')

        sent_count = 0
        errors = []
        notified_users = questionnaire.notified_users or []

        for response in responses:
            user = response.user
            user_id = str(user.id)

            # 跳过已通知的用户
            if user_id in notified_users:
                continue

            # 检查用户是否需要更新
            if not response.needs_update:
                continue

            try:
                # 记录已通知用户
                if user_id not in notified_users:
                    notified_users.append(user_id)

                sent_count += 1

            except Exception as e:
                errors.append(f"用户 {user.username}: {str(e)}")

        # 更新已通知用户列表
        if sent_count > 0:
            questionnaire.notified_users = notified_users
            questionnaire.save(update_fields=['notified_users'])

        return {"sent": sent_count, "errors": errors}

    except Exception as e:
        logger.error(f"发送通知失败: {e}")
        return {"sent": 0, "errors": [str(e)]}