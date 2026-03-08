from django.urls import path, include
from . import views, views_auth, user_views, dashboard_views, views_notification, views_ajax, views_survey,views_qrcode
from .core_captcha import generate_and_store_captcha, refresh_captcha_ajax
from .views_invite_first import verify_invite_only, api_verify_invite
from .views_notification import (
    notification_list, notification_detail, mark_all_as_read,
    delete_notification, notification_settings, get_unread_count, delete_all_read
)
from .views_admin_notification import admin_send_notification, admin_notification_log
from django.views.generic import RedirectView


urlpatterns = [
    # 首页和认证
    path('', views.home, name='home'),
    path('login/', views_auth.login_view, name='login'),
    path('logout/', views_auth.logout_view, name='logout'),
    path('register/', views_auth.register, name='register'),
    path('password_reset/', views_auth.password_reset_user, name='password_reset'),
    path('password_reset/confirm/', views_auth.password_reset_confirm, name='password_reset_confirm'),

    # 验证码
    path('captcha/image/', generate_and_store_captcha, name='captcha_image'),
    path('captcha/refresh/', refresh_captcha_ajax, name='captcha_refresh'),

    # 仪表盘和问卷管理
    path('dashboard/', dashboard_views.dashboard, name='dashboard'),
    path('questionnaires/', dashboard_views.questionnaire_list, name='questionnaire_list'),
    path('questionnaires/create/', dashboard_views.create_questionnaire, name='create_questionnaire'),
    path('questionnaires/<uuid:questionnaire_id>/edit/', views.edit_questionnaire, name='edit_questionnaire'),
    path('questionnaires/<uuid:questionnaire_id>/publish/', dashboard_views.publish_questionnaire,
         name='publish_questionnaire'),
    path('questionnaires/<uuid:questionnaire_id>/delete/', dashboard_views.delete_questionnaire,
         name='delete_questionnaire'),
    path('question/<int:question_id>/versions/', views.question_version_history, name='question_version_history'),
    # dashboard 的问卷详情（管理用）
    path('questionnaires/<uuid:questionnaire_id>/detail/', dashboard_views.questionnaire_detail,
         name='dashboard_questionnaire_detail'),
    path('qrcode/<str:qr_code_id>/', views.qrcode_access, name='qrcode_access'),
    path('qrcode/<str:qr_code_id>/image/', views_qrcode.get_qrcode_image, name='get_qrcode_image'),
    path('api/qrcode/<str:qr_code_id>/share/', views_qrcode.mark_qrcode_shared, name='mark_qrcode_shared'),
    path('response/<uuid:response_id>/', views.response_detail, name='response_detail'),
    # 公共问卷详情和分析（用户访问用）
    path('questionnaires/<uuid:questionnaire_id>/',
         views.questionnaire_detail,
         name='questionnaire_detail'),

    path('questionnaires/<uuid:questionnaire_id>/analytics/',views.questionnaire_analytics,name='questionnaire_analytics'),

    # 导出分析报告
    path('questionnaires/<uuid:questionnaire_id>/export-pdf/',views.export_analytics_pdf,name='export_analytics_pdf'),

    path('my-responses/', dashboard_views.my_responses, name='my_responses'),
    path('my-questionnaires/', dashboard_views.questionnaire_list, name='my_questionnaires'),

    # 问卷填写相关
    path('survey/<uuid:survey_uuid>/', views_survey.survey_landing, name='survey_landing'),
    path('survey-access/<uuid:questionnaire_id>/', user_views.survey_access, name='survey_access'),
    path('survey/<uuid:questionnaire_id>/form/', user_views.survey_form, name='survey_form'),
    path('survey/<uuid:questionnaire_id>/submit/', views_survey.handle_survey_submission, name='submit_response'),
    #path('survey/<uuid:survey_uuid>/submit/', views_survey.handle_survey_submission, name='submit_response'),
    path('survey/<uuid:survey_uuid>/thank-you/', views_survey.survey_thank_you, name='survey_thank_you'),
    path('questionnaires/<uuid:questionnaire_id>/update-time/', dashboard_views.update_questionnaire_time, name='update_questionnaire_time'),
    path('questionnaires/<uuid:questionnaire_id>/update-limit/', dashboard_views.update_questionnaire_limit, name='update_questionnaire_limit'),
    # 问卷状态检查
    path('survey/<uuid:questionnaire_id>/status/', views.check_questionnaire_status, name='check_status'),
    path('survey/<uuid:questionnaire_id>/check/', user_views.check_submitted, name='check_submitted'),
    # 邀请码相关
    path('invite/<str:invite_code>/', user_views.survey_access, name='survey_access_invite'),
    path('survey/<uuid:questionnaire_id>/invite-verify/', verify_invite_only, name='verify_invite_only'),
    path('api/survey/<uuid:questionnaire_id>/verify-invite/', api_verify_invite, name='api_verify_invite'),
    path('api/questionnaires/<uuid:questionnaire_id>/detail/', dashboard_views.api_questionnaire_detail, name='api_questionnaire_detail'),
    # 管理员功能
    path('system/users/', dashboard_views.manage_users, name='manage_users'),
    path('system/users/<uuid:user_id>/', dashboard_views.user_detail, name='user_detail'),
    path('system/users/<uuid:user_id>/toggle-active/', dashboard_views.toggle_user_active,
         name='toggle_user_active'),
    path('system/users/<uuid:user_id>/make-admin/', dashboard_views.make_user_admin,
         name='make_user_admin'),
    path('system/users/<uuid:user_id>/remove-admin/', dashboard_views.remove_user_admin,
         name='remove_user_admin'),
    #path('admin/statistics/', dashboard_views.admin_statistics, name='admin_statistics'),
    path('manage/statistics/', dashboard_views.admin_statistics, name='admin_statistics'),
    path('admin/dashboard/', dashboard_views.dashboard, name='admin_dashboard'),

    # 用户管理相关
    path('system/users/<uuid:user_id>/make-admin/', dashboard_views.make_user_admin, name='make_user_admin'),
    path('system/users/<uuid:user_id>/remove-admin/', dashboard_views.remove_user_admin, name='remove_user_admin'),

    # 问卷更新检查
    path('questionnaires/<uuid:questionnaire_id>/check-update/',
         views_notification.check_questionnaire_update,
         name='check_questionnaire_update'),

    path('questionnaires/<uuid:questionnaire_id>/acknowledge-update/',
         views_notification.acknowledge_update,
         name='acknowledge_update'),

    # AJAX发布问卷
    path('ajax/questionnaires/<uuid:questionnaire_id>/publish/',
         views_ajax.ajax_publish_questionnaire,
         name='ajax_publish_questionnaire'),
    path('questionnaires/<uuid:questionnaire_id>/redirect-wait/', dashboard_views.questionnaire_redirect_wait, name='questionnaire_redirect_wait'),
    path('ajax/batch-operate/', views_ajax.ajax_batch_operate, name='ajax_batch_operate'),
    path('ajax/task-result/', views_ajax.ajax_task_result, name='ajax_task_result'),

    # 通知相关 - 用户端
    path('notifications/', notification_list, name='notification_list'),
    path('notifications/<uuid:notification_id>/', notification_detail, name='notification_detail'),
    path('notifications/mark-all-read/', mark_all_as_read, name='mark_all_read'),
    path('notifications/<uuid:notification_id>/delete/', delete_notification, name='delete_notification'),
    path('notifications/delete-all-read/', delete_all_read, name='delete_all_read'),
    path('notifications/settings/', notification_settings, name='notification_settings'),
    path('notifications/unread-count/', get_unread_count, name='unread_count'),
    path('notifications/updates/', views.get_notification_updates, name='get_notification_updates'),

    # 通知相关 - 管理端
    path('admin/notifications/send/', admin_send_notification, name='admin_send_notification'),
    path('admin/notifications/log/', admin_notification_log, name='admin_notification_log'),

    path('users/', RedirectView.as_view(pattern_name='manage_users'), name='user_list'),

    # 用户资料
    path('profile/', dashboard_views.user_profile, name='user_profile'),

    # 检查用户名可用性
    path('profile/check-username/', dashboard_views.check_username_availability, name='check_username'),

    # 新增：创建方式选择
    path('create/choice/', views.create_choice, name='create_choice'),

    # 新增：模板列表
    path('templates/', views.TemplateListView.as_view(), name='template_list'),
    path('templates/<uuid:template_id>/use/', views.create_from_template, name='create_from_template'),

    # 新增：两步填写
    path('questionnaire/<uuid:questionnaire_id>/select-target/', views.select_target, name='select_target'),
    path('questionnaire/<uuid:questionnaire_id>/answer/', views.answer_questions, name='answer_questions'),
]
