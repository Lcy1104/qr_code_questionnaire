# questionnaire/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Questionnaire
print("DEBUG: 加载 WebSocket Consumer")


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        """WebSocket 连接建立"""
        print(f"DEBUG: WebSocket 连接尝试")
        print(f"DEBUG: scope keys: {self.scope.keys()}")
        print(f"DEBUG: scope path: {self.scope.get('path')}")
        print(f"DEBUG: scope user: {self.scope.get('user')}")
        print(f"DEBUG: scope headers: {self.scope.get('headers')}")

        self.user = self.scope["user"]

        # 检查用户是否认证
        if not self.user.is_authenticated:
            print("DEBUG: 用户未认证，关闭连接")
            await self.close(code=4001)
            return

        print(f"DEBUG: 用户认证成功: {self.user.username}")

        # 创建用户特定的组名
        self.group_name = f"user_{self.user.id}_notifications"
        print(f"DEBUG: 组名: {self.group_name}")

        # 将连接加入组
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()
        print("DEBUG: WebSocket 连接已接受")

        # 发送当前未读通知数量
        unread_count = await self.get_unread_count()
        await self.send(text_data=json.dumps({
            'type': 'unread_count',
            'unread_count': unread_count
        }))
        print(f"DEBUG: 发送未读数量: {unread_count}")

    async def disconnect(self, close_code):
        """WebSocket 连接断开"""
        print(f"DEBUG: WebSocket 断开连接，代码: {close_code}")
        group_name = getattr(self, 'group_name', None)
        if group_name:
            try:
                await self.channel_layer.group_discard(
                    group_name,
                    self.channel_name
                )
            except Exception as e:
                # 捕获并记录组移除过程中的任何异常
                print(f"DEBUG: 从组 {group_name} 移除时发生异常（可忽略）: {e}")

    async def receive(self, text_data):
        """接收客户端消息"""
        print(f"DEBUG: 收到消息: {text_data}")
        try:
            data = json.loads(text_data)

            if data.get('type') == 'mark_all_read':
                # 客户端请求标记所有为已读
                count = await self.mark_all_as_read()
                try:
                    await self.send(text_data=json.dumps({
                        'type': 'marked_all_read',
                        'count': count
                    }))
                except (ConnectionResetError, ConnectionRefusedError, OSError) as e:
                    print(f"DEBUG: 发送‘已标记’回执失败，连接可能已断开: {e}")
                    # 同样，静默处理，不再抛出

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'JSON 解析错误'
            }))

    async def send_notification(self, event):
        """发送通知给客户端"""
        print(f"DEBUG: 发送通知: {event}")
        try:
            await self.send(text_data=json.dumps({
                'type': 'new_notification',
                'notification': event['notification']
            }))
        except (ConnectionResetError, ConnectionRefusedError, OSError) as e:
            # 当连接已断开时，捕获异常并记录，避免错误上抛
            print(f"DEBUG: 向 {self.channel_name} 发送通知失败，连接可能已断开: {e}")
            # 可以在这里选择静默处理，不再进行其他操作

    @database_sync_to_async
    def get_unread_count(self):
        """获取用户未读通知数量"""
        if not self.user.is_authenticated:
            return 0

        from .models import Notification
        return Notification.objects.filter(
            user=self.user,
            is_read=False,
            delivery_status='sent'
        ).count()

    @database_sync_to_async
    def mark_all_as_read(self):
        """标记所有通知为已读"""
        if not self.user.is_authenticated:
            return 0

        from .models import Notification
        notifications = Notification.objects.filter(
            user=self.user,
            is_read=False,
            delivery_status='sent'
        )
        count = notifications.count()

        for notification in notifications:
            notification.is_read = True
            notification.save()

        return count

class QuestionnaireQRCodeConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.questionnaire_id = self.scope['url_route']['kwargs']['questionnaire_id']
        self.room_group_name = f'questionnaire_{self.questionnaire_id}'

        user = self.scope['user']
        print(f"WebSocket连接尝试: questionnaire_id={self.questionnaire_id}, user={user}")

        if user.is_authenticated:
            can_access = await self.check_permission()
            if can_access:
                await self.channel_layer.group_add(
                    self.room_group_name,
                    self.channel_name
                )
                await self.accept()
                print("WebSocket连接成功")
            else:
                print("权限检查失败，关闭连接")
                await self.close(code=4003)
        else:
            print("用户未认证，关闭连接")
            await self.close(code=4001)

    @database_sync_to_async
    def check_permission(self):
        try:
            q = Questionnaire.objects.get(id=self.questionnaire_id)
            user = self.scope['user']
            return user == q.creator or user.is_admin
        except Questionnaire.DoesNotExist:
            return False
        except Exception as e:
            print(f"权限检查异常: {e}")
            return False

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def qrcode_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'qrcode_update',
            'qr_code_id': event['qr_code_id'],
            'is_used': event['is_used'],
            'used_by': event['used_by'],
            'used_at': event['used_at'],
            'response_id': event['response_id'],
        }))

    async def questionnaire_updated(self, event):
        """当问卷被创建或更新时，通知前端"""
        await self.send(text_data=json.dumps({
            'type': 'questionnaire_updated',
            'questionnaire_id': event['questionnaire_id'],
            'has_available_qrcode': event.get('has_available_qrcode'),
            'questions': event.get('questions'),  # 新增，传递完整问题列表
            'submit_count': event.get('submit_count'),  # 新增
            'user_has_submitted': event.get('user_has_submitted'),  # 新增
        }))

    @database_sync_to_async
    def get_questionnaire_data(self, questionnaire_id):
        """获取问卷的完整数据（问题列表、二维码可用性等）"""
        try:
            from .models import Questionnaire, Question
            q = Questionnaire.objects.get(id=questionnaire_id)
            questions = list(q.questions.all().order_by('order').values(
                'id', 'text', 'question_type', 'options', 'required', 'max_length', 'order'
            ))
            has_available_qrcode = True
            if q.enable_multi_qrcodes:
                has_available_qrcode = q.qrcodes.filter(is_used=False).exists()
            return {
                'questionnaire_id': str(questionnaire_id),
                'has_available_qrcode': has_available_qrcode,
                'questions': questions,
                'submit_count': 0,  # 刚创建，提交数为0
                'user_has_submitted': False,
            }
        except Exception:
            return None

    async def receive(self, text_data):
        """处理来自前端的消息"""
        data = json.loads(text_data)
        msg_type = data.get('type')

        if msg_type == 'check_ready':
            # 前端请求检查问卷数据是否就绪
            questionnaire_id = data.get('questionnaire_id')
            ready = await self.check_questionnaire_ready(questionnaire_id)
            if ready:
                # 获取完整数据
                full_data = await self.get_questionnaire_data(questionnaire_id)
                if full_data:
                    await self.send(text_data=json.dumps({
                        'type': 'questionnaire_updated',
                        **full_data
                    }))
                else:
                    # 如果获取数据失败，只发ready（后备）
                    await self.send(text_data=json.dumps({
                        'type': 'questionnaire_updated',
                        'questionnaire_id': questionnaire_id,
                        'ready': True
                    }))
            else:
                # 未就绪不发送（让前端重试）
                pass


    @database_sync_to_async
    def check_questionnaire_ready(self, questionnaire_id):
        """检查问卷是否有问题（表示数据已就绪）"""
        from .models import Question
        return Question.objects.filter(questionnaire_id=questionnaire_id).exists()