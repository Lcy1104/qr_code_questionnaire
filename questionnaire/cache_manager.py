# questionnaire/cache_manager.py
import json
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from .sm4 import sm4_encode, sm4_decode


class QuestionnaireCacheManager:
    """问卷系统Redis缓存管理器"""

    @staticmethod
    def _get_cache_key(model_name, obj_id):
        """生成缓存键"""
        return f"questionnaire:{model_name}:{obj_id}"

    @staticmethod
    def cache_object(model_name, obj_id, data, timeout=3600):
        """缓存对象"""
        cache_key = QuestionnaireCacheManager._get_cache_key(model_name, obj_id)
        # 对敏感数据加密
        if isinstance(data, dict) or isinstance(data, list):
            data_str = json.dumps(data, cls=DjangoJSONEncoder)
            encrypted_data = sm4_encode(data_str)
            cache.set(cache_key, encrypted_data, timeout)
        else:
            # 非字典/列表数据直接存储
            cache.set(cache_key, data, timeout)

    @staticmethod
    def get_cached_object(model_name, obj_id):
        """获取缓存的解密对象"""
        cache_key = QuestionnaireCacheManager._get_cache_key(model_name, obj_id)
        cached_data = cache.get(cache_key)

        if cached_data:
            try:
                # 尝试解密
                decrypted = sm4_decode(cached_data)
                return json.loads(decrypted)
            except:
                # 如果不是加密数据，直接返回
                try:
                    return json.loads(cached_data)
                except:
                    return cached_data
        return None

    @staticmethod
    def delete_cache(model_name, obj_id):
        """删除缓存"""
        cache_key = QuestionnaireCacheManager._get_cache_key(model_name, obj_id)
        cache.delete(cache_key)

    @staticmethod
    def cache_questionnaire_stats(questionnaire_id, stats, timeout=300):
        """缓存问卷统计信息"""
        cache_key = f"questionnaire:stats:{questionnaire_id}"
        encrypted_stats = sm4_encode(json.dumps(stats))
        cache.set(cache_key, encrypted_stats, timeout)

    @staticmethod
    def get_cached_questionnaire_stats(questionnaire_id):
        """获取缓存的问卷统计信息"""
        cache_key = f"questionnaire:stats:{questionnaire_id}"
        cached = cache.get(cache_key)
        if cached:
            try:
                return json.loads(sm4_decode(cached))
            except:
                return None
        return None

    @staticmethod
    def model_to_dict(instance):
        """将模型实例转换为字典"""
        from django.forms.models import model_to_dict as django_model_to_dict
        return django_model_to_dict(instance)

    @staticmethod
    def set_cache_data(model_name, key, data, timeout):
        """设置缓存数据（兼容旧代码）"""
        return QuestionnaireCacheManager.cache_object(model_name, key, data, timeout)

    @staticmethod
    def get_cache_data(model_name, key):
        """获取缓存数据（兼容旧代码）"""
        return QuestionnaireCacheManager.get_cached_object(model_name, key)
