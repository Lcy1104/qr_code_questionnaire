# qr_code_questionnaire/middleware.py
"""
安全中间件
"""
import re
import json
from django.http import HttpResponseForbidden, JsonResponse
from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings
import logging
from .models import SecurityEvent
from questionnaire.utils.encryption import get_sm4_encryptor

logger = logging.getLogger("django.security")


class SecurityMiddleware(MiddlewareMixin):
    """安全中间件"""

    # SQL注入关键词
    SQL_INJECTION_PATTERNS = [
        r"(\s*)(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|EXEC|ALTER|CREATE|TRUNCATE)\b)",
        r"(\b(OR|AND)\b\s+\d+\s*=\s*\d+)",
        r"(\b(OR|AND)\b\s+'\w+'\s*=\s*'\w+')",
        r"(--|#|\/\*)",
        r"(\b(WAITFOR|DELAY)\b)",
    ]

    # XSS攻击关键词
    XSS_PATTERNS = [
        r"<script.*?>.*?</script>",
        r"javascript:",
        r"on\w+\s*=",
        r"eval\s*\(",
        r"alert\s*\(",
    ]

    def __init__(self, get_response):
        self.get_response = get_response
        self.sql_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.SQL_INJECTION_PATTERNS
        ]
        self.xss_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.XSS_PATTERNS
        ]

    def process_request(self, request):
        """处理请求前的安全检查"""

        # 跳过管理后台和静态文件
        if request.path.startswith(("/admin/", "/static/", "/media/")):
            return None

        # IP黑名单检查
        ip = self.get_client_ip(request)
        if self.is_ip_blacklisted(ip):
            return self.block_request(request, ip, "blacklist_ip")

        # 速率限制检查
        if not self.check_rate_limit(request, ip):
            return self.block_request(request, ip, "rate_limit")

        # SQL注入检查
        if self.check_sql_injection(request):
            return self.block_request(request, ip, "sqlinjection")

        # XSS检查
        if self.check_xss(request):
            return self.block_request(request, ip, "xss")

        # 文件上传检查
        if request.method == "POST" and request.FILES:
            if self.check_malicious_file(request):
                return self.block_request(request, ip, "file_upload")

        return None

    def process_response(self, request, response):
        """处理响应"""
        # 添加安全头
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response["X-XSS-Protection"] = "1; mode=block"

        # 如果使用HTTPS
        if getattr(settings, "SECURE_SSL_REDIRECT", False):
            response["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # 内容安全策略
        response["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        )

        return response

    def get_client_ip(self, request):
        """获取客户端真实IP"""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0]
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip

    def is_ip_blacklisted(self, ip):
        """检查IP是否在黑名单中"""
        cache_key = f"blacklist_ip_{ip}"
        return cache.get(cache_key) is not None

    def check_rate_limit(self, request, ip):
        """检查速率限制"""
        path = request.path

        # 不同路径有不同的限制
        if path in ["/login/", "/api/login/", "/register/", "/api/register/"]:
            limit_key = f"rate_limit_login_{ip}"
            limit = 5  # 5次/分钟
            window = 60  # 1分钟
        elif path.startswith("/api/"):
            limit_key = f"rate_limit_api_{ip}"
            limit = 100  # 100次/分钟
            window = 60
        else:
            limit_key = f"rate_limit_general_{ip}"
            limit = 200  # 200次/分钟
            window = 60

        # 获取当前计数
        current = cache.get(limit_key, 0)

        if current >= limit:
            return False

        # 增加计数
        cache.set(limit_key, current + 1, window)
        return True

    def check_sql_injection(self, request):
        """检查SQL注入攻击"""
        # 检查GET参数
        for key, value in request.GET.items():
            if self._contains_sql_injection(value):
                return True

        # 检查POST参数
        if request.method == "POST":
            # 检查form数据
            for key, value in request.POST.items():
                if self._contains_sql_injection(value):
                    return True

            # 检查JSON数据
            if request.content_type == "application/json":
                try:
                    data = json.loads(request.body.decode("utf-8"))
                    if self._check_dict_for_sql_injection(data):
                        return True
                except:
                    pass

        return False

    def _contains_sql_injection(self, value):
        """检查字符串是否包含SQL注入"""
        if not isinstance(value, str):
            return False

        for pattern in self.sql_patterns:
            if pattern.search(value):
                return True

        return False

    def _check_dict_for_sql_injection(self, data):
        """递归检查字典中的SQL注入"""
        if isinstance(data, dict):
            for value in data.values():
                if self._check_dict_for_sql_injection(value):
                    return True
        elif isinstance(data, list):
            for item in data:
                if self._check_dict_for_sql_injection(item):
                    return True
        elif isinstance(data, str):
            if self._contains_sql_injection(data):
                return True

        return False

    def check_xss(self, request):
        """检查XSS攻击"""
        # 检查GET参数
        for key, value in request.GET.items():
            if self._contains_xss(value):
                return True

        # 检查POST参数
        if request.method == "POST":
            for key, value in request.POST.items():
                if self._contains_xss(value):
                    return True

            # 检查JSON数据
            if request.content_type == "application/json":
                try:
                    data = json.loads(request.body.decode("utf-8"))
                    if self._check_dict_for_xss(data):
                        return True
                except:
                    pass

        return False

    def _contains_xss(self, value):
        """检查字符串是否包含XSS"""
        if not isinstance(value, str):
            return False

        for pattern in self.xss_patterns:
            if pattern.search(value):
                return True

        return False

    def _check_dict_for_xss(self, data):
        """递归检查字典中的XSS"""
        if isinstance(data, dict):
            for value in data.values():
                if self._check_dict_for_xss(value):
                    return True
        elif isinstance(data, list):
            for item in data:
                if self._check_dict_for_xss(item):
                    return True
        elif isinstance(data, str):
            if self._contains_xss(data):
                return True

        return False

    def check_malicious_file(self, request):
        """检查恶意文件上传"""
        for file in request.FILES.values():
            # 检查文件扩展名
            filename = file.name.lower()
            dangerous_extensions = [
                ".php",
                ".asp",
                ".aspx",
                ".jsp",
                ".exe",
                ".bat",
                ".sh",
            ]

            if any(filename.endswith(ext) for ext in dangerous_extensions):
                return True

            # 检查文件内容（简单检查）
            try:
                content = file.read(1024)  # 读取前1KB
                # 检查是否包含可执行代码
                suspicious_strings = [
                    b"<?php",
                    b"<script",
                    b"eval(",
                    b"exec(",
                    b"system(",
                ]
                for suspicious in suspicious_strings:
                    if suspicious in content:
                        return True
                file.seek(0)  # 重置文件指针
            except:
                pass

        return False

    def block_request(self, request, ip, event_type):
        """拦截请求并记录安全事件"""
        # 记录安全事件
        try:
            encryptor = get_sm4_encryptor()

            # 收集请求数据（加密存储）
            request_data = {
                "method": request.method,
                "path": request.path,
                "get_params": dict(request.GET),
                "post_params": dict(request.POST) if request.method == "POST" else {},
            }

            request_headers = dict(request.headers)

            security_event = SecurityEvent(
                event_type=event_type,
                severity="high" if event_type in ["sqlinjection", "xss"] else "medium",
                description=f"安全中间件拦截 - {event_type}",
                ip_address=ip,
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                request_path=request.path,
                request_method=request.method,
                request_data=encryptor.encrypt(
                    json.dumps(request_data, ensure_ascii=False)
                ),
                request_headers=encryptor.encrypt(
                    json.dumps(request_headers, ensure_ascii=False)
                ),
                blocked=True,
                action_taken="请求被拦截",
            )

            # 尝试关联用户
            if request.user.is_authenticated:
                security_event.user = request.user

            security_event.save()

            # 将IP加入临时黑名单（5分钟）
            if event_type in ["sqlinjection", "xss", "brute_force"]:
                cache.set(f"blacklist_ip_{ip}", True, 300)  # 5分钟

        except Exception as e:
            logger.error(f"记录安全事件失败: {str(e)}")

        # 返回403错误
        if request.path.startswith("/api/"):
            return JsonResponse(
                {
                    "success": False,
                    "message": "请求被安全策略拦截",
                    "code": "SECURITY_BLOCKED",
                },
                status=403,
            )
        else:
            return HttpResponseForbidden(
                "<h1>403 Forbidden</h1><p>请求被安全策略拦截。</p>"
            )


class AuditMiddleware(MiddlewareMixin):
    """审计中间件"""

    def process_view(self, request, view_func, view_args, view_kwargs):
        """记录重要操作"""
        # 只记录特定的视图
        audit_paths = [
            "/login/",
            "/logout/",
            "/register/",
            "/questionnaire/create/",
            "/questionnaire/publish/",
            "/survey/submit/",
            "/api/user/generate-codes/",
        ]

        if request.path in audit_paths or request.path.startswith("/api/"):
            request._audit_start_time = timezone.now()
            request._audit_view = view_func.__name__

    def process_response(self, request, response):
        """处理响应后记录审计日志"""
        if hasattr(request, "_audit_start_time"):
            duration = (timezone.now() - request._audit_start_time).total_seconds()

            # 记录审计日志
            audit_logger = logging.getLogger("survey.audit")

            user_info = "匿名用户"
            if request.user.is_authenticated:
                user_info = f"{request.user.username} ({request.user.id})"

            ip = self.get_client_ip(request)

            audit_data = {
                "user": user_info,
                "ip": ip,
                "action": request._audit_view,
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration": f"{duration:.3f}s",
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200],
            }

            audit_logger.info("", extra=audit_data)

        return response

    def get_client_ip(self, request):
        """获取客户端IP"""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0]
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip
