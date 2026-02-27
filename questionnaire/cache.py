from django.core.cache import cache

def get_detail_cache_key(questionnaire):
    return f"q:detail:{questionnaire.id}:v{questionnaire.version}"

def get_stats_cache_key(questionnaire):
    return f"q:stats:{questionnaire.id}"

def clear_questionnaire_cache(questionnaire):
    cache.delete(get_detail_cache_key(questionnaire))
    cache.delete(get_stats_cache_key(questionnaire))