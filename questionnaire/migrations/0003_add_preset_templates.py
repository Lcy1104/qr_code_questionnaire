from django.db import migrations

def add_preset_templates(apps, schema_editor):
    Questionnaire = apps.get_model('questionnaire', 'Questionnaire')
    Question = apps.get_model('questionnaire', 'Question')
    User = apps.get_model('questionnaire', 'User')

    creator = User.objects.filter(is_superuser=True).first() or User.objects.first()
    if not creator:
        return

    # 模板1：员工互评（5维度）
    t1 = Questionnaire.objects.create(
        title='员工互评模板（5维度）',
        description='从5个方面评价同事',
        creator=creator,
        is_template=True,
        status='draft',
        access_type='public',
        targets=[]
    )
    questions1 = [
        ('工作态度', 'radio', ['优秀', '良好', '一般', '较差'], 1),
        ('团队合作', 'radio', ['优秀', '良好', '一般', '较差'], 2),
        ('沟通能力', 'radio', ['优秀', '良好', '一般', '较差'], 3),
        ('责任心', 'radio', ['优秀', '良好', '一般', '较差'], 4),
        ('专业技能', 'radio', ['优秀', '良好', '一般', '较差'], 5),
    ]
    for text, qtype, opts, order in questions1:
        Question.objects.create(
            questionnaire=t1,
            text=text,
            question_type=qtype,
            order=order,
            required=True,
            options=opts
        )

    # 模板2：客户满意度（5维度）
    t2 = Questionnaire.objects.create(
        title='客户满意度模板（5维度）',
        description='评价客服人员的表现',
        creator=creator,
        is_template=True,
        status='draft',
        access_type='public',
        targets=[]
    )
    questions2 = [
        ('服务态度', 'radio', ['非常满意', '满意', '一般', '不满意'], 1),
        ('响应速度', 'radio', ['非常满意', '满意', '一般', '不满意'], 2),
        ('问题解决能力', 'radio', ['非常满意', '满意', '一般', '不满意'], 3),
        ('专业知识', 'radio', ['非常满意', '满意', '一般', '不满意'], 4),
        ('总体评价', 'radio', ['非常满意', '满意', '一般', '不满意'], 5),
    ]
    for text, qtype, opts, order in questions2:
        Question.objects.create(
            questionnaire=t2,
            text=text,
            question_type=qtype,
            order=order,
            required=True,
            options=opts
        )

def reverse_func(apps, schema_editor):
    Questionnaire = apps.get_model('questionnaire', 'Questionnaire')
    Questionnaire.objects.filter(is_template=True).delete()

class Migration(migrations.Migration):
    dependencies = [
        ('questionnaire', '0002_add_targets_fields'),  # 必须与上一步的迁移名称一致
    ]
    operations = [
        migrations.RunPython(add_preset_templates, reverse_func),
    ]