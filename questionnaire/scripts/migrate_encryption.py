#!/usr/bin/env python
import os
import sys
import django
import json
from pathlib import Path

# 添加项目路径
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'qr_code_questionaire.settings')
django.setup()

from questionnaire.models import User, Questionnaire, Question, Answer, Response
from questionnaire.sm4 import sm4_encode
from questionnaire.encrypted_fields import EncryptedTextField, EncryptedCharField
import logging

logger = logging.getLogger(__name__)


def encrypt_user_data():
    """加密现有用户数据"""
    print("开始加密用户数据...")

    users = User.objects.all()
    total = users.count()
    print(f"发现 {total} 个用户需要加密")

    for i, user in enumerate(users, 1):
        try:
            # 检查并加密用户名
            if not user.username.startswith('enc_'):
                try:
                    # 尝试解密，如果已经是加密的则跳过
                    user.username = sm4_encode(user.username)
                except Exception as e:
                    logger.error(f"用户 {user.id} 用户名加密失败: {e}")

            # 检查并加密邮箱
            if user.email:
                try:
                    user.email = sm4_encode(user.email)
                except Exception as e:
                    logger.error(f"用户 {user.id} 邮箱加密失败: {e}")

            # 检查并加密手机号
            if user.phone:
                try:
                    user.phone = sm4_encode(user.phone)
                except Exception as e:
                    logger.error(f"用户 {user.id} 手机号加密失败: {e}")

            # 检查并加密真实姓名
            if user.real_name:
                try:
                    user.real_name = sm4_encode(user.real_name)
                except Exception as e:
                    logger.error(f"用户 {user.id} 真实姓名加密失败: {e}")

            user.save(update_fields=['username', 'email', 'phone', 'real_name'])

            if i % 100 == 0:
                print(f"进度: {i}/{total}")

        except Exception as e:
            print(f"用户 {user.id} 数据加密失败: {e}")
            continue

    print("用户数据加密完成！")


def encrypt_questionnaire_data():
    """加密现有问卷数据"""
    print("\n开始加密问卷数据...")

    questionnaires = Questionnaire.objects.all()
    total = questionnaires.count()
    print(f"发现 {total} 份问卷需要加密")

    for i, questionnaire in enumerate(questionnaires, 1):
        try:
            # 问卷会使用加密字段自动处理，这里确保保存一次
            questionnaire.save()

            if i % 50 == 0:
                print(f"进度: {i}/{total}")

        except Exception as e:
            print(f"问卷 {questionnaire.id} 数据加密失败: {e}")
            continue

    print("问卷数据加密完成！")


def encrypt_question_data():
    """加密现有问题数据"""
    print("\n开始加密问题数据...")

    questions = Question.objects.all()
    total = questions.count()
    print(f"发现 {total} 个问题需要加密")

    for i, question in enumerate(questions, 1):
        try:
            # 问题会使用加密字段自动处理
            question.save()

            if i % 100 == 0:
                print(f"进度: {i}/{total}")

        except Exception as e:
            print(f"问题 {question.id} 数据加密失败: {e}")
            continue

    print("问题数据加密完成！")


def encrypt_answer_data():
    """加密现有答案数据"""
    print("\n开始加密答案数据...")

    answers = Answer.objects.all()
    total = answers.count()
    print(f"发现 {total} 个答案需要加密")

    for i, answer in enumerate(answers, 1):
        try:
            # 答案会使用加密字段自动处理
            answer.save()

            if i % 100 == 0:
                print(f"进度: {i}/{total}")

        except Exception as e:
            print(f"答案 {answer.id} 数据加密失败: {e}")
            continue

    print("答案数据加密完成！")


def update_response_structure():
    """更新Response结构，移除answers字段"""
    print("\n检查Response结构...")

    # 检查是否有Response还有answers字段
    responses_with_answers = Response.objects.exclude(answers=None)
    count = responses_with_answers.count()

    if count > 0:
        print(f"发现 {count} 个Response需要迁移answers数据")

        for response in responses_with_answers:
            try:
                # 将旧的answers数据迁移到Answer模型
                answers_data = response.answers
                if isinstance(answers_data, dict):
                    for question_id, answer_value in answers_data.items():
                        try:
                            question = Question.objects.get(id=question_id)

                            # 处理答案格式
                            if isinstance(answer_value, list):
                                answer_text = json.dumps(answer_value, ensure_ascii=False)
                            else:
                                answer_text = str(answer_value)

                            # 创建Answer记录
                            Answer.objects.create(
                                response=response,
                                question=question,
                                answer_text=answer_text
                            )
                        except Question.DoesNotExist:
                            continue

                # 清空旧的answers字段
                response.answers = None
                response.save()
                print(f"Response {response.id} 数据迁移完成")

            except Exception as e:
                print(f"Response {response.id} 数据迁移失败: {e}")
                continue

    print("Response结构更新完成！")


def main():
    """主函数"""
    print("=" * 50)
    print("开始数据加密迁移")
    print("=" * 50)

    try:
        # 1. 更新Response结构
        update_response_structure()

        # 2. 加密用户数据
        encrypt_user_data()

        # 3. 加密问卷数据
        encrypt_questionnaire_data()

        # 4. 加密问题数据
        encrypt_question_data()

        # 5. 加密答案数据
        encrypt_answer_data()

        print("\n" + "=" * 50)
        print("数据加密迁移完成！")
        print("=" * 50)

    except Exception as e:
        print(f"\n迁移过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()