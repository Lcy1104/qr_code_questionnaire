# questionnaire/apps.py
from django.apps import AppConfig


class QuestionnaireConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'questionnaire'
    verbose_name = '问卷调查系统'

    def ready(self):
        # 导入信号
        import questionnaire.signals