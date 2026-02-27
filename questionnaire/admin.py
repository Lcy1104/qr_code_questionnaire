from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Questionnaire, Question, Response


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'real_name', 'phone', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'real_name', 'phone')
    list_filter = ('is_active', 'is_staff', 'is_superuser')

    fieldsets = UserAdmin.fieldsets + (
        ('个人信息', {'fields': ('phone', 'real_name')}),
    )


@admin.register(Questionnaire)
class QuestionnaireAdmin(admin.ModelAdmin):
    list_display = ('title', 'creator', 'status', 'created_at', 'published_at')
    list_filter = ('status', 'created_at')
    search_fields = ('title', 'description')
    raw_id_fields = ('creator',)
    date_hierarchy = 'created_at'

    readonly_fields = ('created_at', 'updated_at', 'published_at')


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('text', 'questionnaire', 'question_type', 'required', 'order')
    list_filter = ('question_type', 'required')
    search_fields = ('text',)
    raw_id_fields = ('questionnaire',)
    list_editable = ('order', 'required')


@admin.register(Response)
class ResponseAdmin(admin.ModelAdmin):
    list_display = ('get_user', 'questionnaire', 'submitted_at', 'ip_address', 'is_submitted')
    list_filter = ('is_submitted', 'submitted_at')
    search_fields = ('user__username', 'questionnaire__title', 'ip_address')
    raw_id_fields = ('questionnaire', 'user')
    readonly_fields = ('submitted_at', 'ip_address', 'user_agent')
    date_hierarchy = 'submitted_at'

    def get_user(self, obj):
        return obj.user.username if obj.user else '匿名'
    get_user.short_description = '用户'