/**
 * 问卷更新检查工具
 * 用于实时检查问卷是否有更新，并显示通知
 */

class QuestionnaireUpdateChecker {
    constructor(options = {}) {
        this.options = {
            checkInterval: 60000, // 检查间隔，默认60秒
            notificationDuration: 5000, // 通知显示时长
            showUrgentNotifications: true, // 是否显示紧急通知
            ...options
        };

        this.currentQuestionnaireId = null;
        this.updateCallbacks = [];
        this.isChecking = false;
        this.checkTimer = null;
        this.notificationContainer = null;

        this.init();
    }

    init() {
        // 创建通知容器
        this.createNotificationContainer();

        // 监听页面可见性变化
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.stopChecking();
            } else {
                this.startChecking();
            }
        });
    }

    createNotificationContainer() {
        // 如果容器已存在，直接返回
        if (document.getElementById('update-notifications')) {
            this.notificationContainer = document.getElementById('update-notifications');
            return;
        }

        // 创建通知容器
        const container = document.createElement('div');
        container.id = 'update-notifications';
        container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 9999;
            max-width: 400px;
        `;

        document.body.appendChild(container);
        this.notificationContainer = container;
    }

    /**
     * 开始检查特定问卷的更新
     */
    startCheckingQuestionnaire(questionnaireId) {
        this.currentQuestionnaireId = questionnaireId;

        // 立即检查一次
        this.checkQuestionnaireUpdate();

        // 设置定时检查
        this.checkTimer = setInterval(() => {
            this.checkQuestionnaireUpdate();
        }, this.options.checkInterval);
    }

    /**
     * 停止检查问卷更新
     */
    stopCheckingQuestionnaire() {
        if (this.checkTimer) {
            clearInterval(this.checkTimer);
            this.checkTimer = null;
        }
        this.currentQuestionnaireId = null;
    }

    /**
     * 开始检查通知更新
     */
    startChecking() {
        if (this.isChecking) return;

        this.isChecking = true;

        // 立即检查一次
        this.checkNotifications();

        // 设置定时检查
        setInterval(() => {
            this.checkNotifications();
        }, 30000); // 每30秒检查一次通知
    }

    /**
     * 停止检查通知
     */
    stopChecking() {
        this.isChecking = false;
    }

    /**
     * 检查特定问卷是否有更新
     */
    async checkQuestionnaireUpdate() {
        if (!this.currentQuestionnaireId) return;

        try {
            const response = await fetch(`/questionnaires/${this.currentQuestionnaireId}/check-update/`, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();

            if (data.has_update) {
                // 显示更新通知
                this.showQuestionnaireUpdateNotification(data);

                // 触发回调
                this.triggerCallbacks('update', data);
            }

            return data;

        } catch (error) {
            console.error('检查问卷更新失败:', error);
            return { has_update: false, error: error.message };
        }
    }

    /**
     * 检查通知更新
     */
    async checkNotifications() {
        if (!this.isChecking) return;

        try {
            const response = await fetch('/notifications/updates/', {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();

            // 如果有未读通知，更新页面上的通知徽章
            this.updateNotificationBadge(data.unread_count);

            // 显示新通知
            if (data.notifications && data.notifications.length > 0) {
                this.showNewNotifications(data.notifications);
            }

            // 显示紧急通知
            if (this.options.showUrgentNotifications && data.urgent_notifications && data.urgent_notifications.length > 0) {
                this.showUrgentNotifications(data.urgent_notifications);
            }

            return data;

        } catch (error) {
            console.error('检查通知更新失败:', error);
            return { unread_count: 0, notifications: [], urgent_notifications: [] };
        }
    }

    /**
     * 显示问卷更新通知
     */
    showQuestionnaireUpdateNotification(data) {
        const notificationId = `questionnaire-update-${data.questionnaire_id}`;

        // 如果通知已存在，不重复显示
        if (document.getElementById(notificationId)) {
            return;
        }

        const notification = document.createElement('div');
        notification.id = notificationId;
        notification.className = 'alert alert-warning alert-dismissible fade show';
        notification.style.cssText = `
            animation: slideInRight 0.3s ease-out;
            margin-bottom: 10px;
        `;

        notification.innerHTML = `
            <div class="d-flex align-items-center">
                <i class="fas fa-exclamation-triangle fa-lg me-3"></i>
                <div class="flex-grow-1">
                    <h6 class="mb-1">问卷已更新</h6>
                    <p class="mb-1 small">《${data.questionnaire_title}》已更新到版本 ${data.update_info.current_version}</p>
                    <div class="mt-2">
                        <a href="/questionnaires/${data.questionnaire_id}/" class="btn btn-sm btn-outline-primary me-2">
                            查看更新
                        </a>
                        <button type="button" class="btn btn-sm btn-outline-secondary acknowledge-btn" 
                                data-questionnaire-id="${data.questionnaire_id}">
                            稍后再说
                        </button>
                    </div>
                </div>
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="关闭"></button>
            </div>
        `;

        this.notificationContainer.appendChild(notification);

        // 添加确认更新按钮事件
        const acknowledgeBtn = notification.querySelector('.acknowledge-btn');
        acknowledgeBtn.addEventListener('click', () => {
            this.acknowledgeUpdate(data.questionnaire_id);
            notification.remove();
        });

        // 自动消失
        setTimeout(() => {
            if (notification.parentNode) {
                notification.classList.remove('show');
                setTimeout(() => {
                    if (notification.parentNode) {
                        notification.remove();
                    }
                }, 300);
            }
        }, this.options.notificationDuration);
    }

    /**
     * 显示新通知
     */
    showNewNotifications(notifications) {
        notifications.forEach(notification => {
            const notificationId = `notification-${notification.id}`;

            // 如果通知已存在，不重复显示
            if (document.getElementById(notificationId)) {
                return;
            }

            const notificationElement = document.createElement('div');
            notificationElement.id = notificationId;

            // 根据通知类型和优先级设置样式
            let alertClass = 'alert-info';
            let icon = 'fa-info-circle';

            if (notification.priority === 'urgent') {
                alertClass = 'alert-danger';
                icon = 'fa-exclamation-triangle';
            } else if (notification.priority === 'high') {
                alertClass = 'alert-warning';
                icon = 'fa-exclamation-circle';
            } else if (notification.type === 'questionnaire_update') {
                alertClass = 'alert-primary';
                icon = 'fa-file-alt';
            } else if (notification.type === 'admin') {
                alertClass = 'alert-dark';
                icon = 'fa-user-shield';
            }

            notificationElement.className = `alert ${alertClass} alert-dismissible fade show`;
            notificationElement.style.cssText = `
                animation: slideInRight 0.3s ease-out;
                margin-bottom: 10px;
                cursor: pointer;
            `;

            let actionButtons = '';
            if (notification.related_questionnaire) {
                actionButtons = `
                    <div class="mt-2">
                        <a href="/questionnaires/${notification.related_questionnaire}/" 
                           class="btn btn-sm btn-outline-light">
                            查看问卷
                        </a>
                    </div>
                `;
            }

            notificationElement.innerHTML = `
                <div class="d-flex align-items-start">
                    <i class="fas ${icon} fa-lg me-3 mt-1"></i>
                    <div class="flex-grow-1">
                        <h6 class="mb-1">${notification.title}</h6>
                        <p class="mb-1 small">${notification.message}</p>
                        <small class="text-muted">${notification.time_since}</small>
                        ${actionButtons}
                    </div>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="alert" aria-label="关闭"></button>
                </div>
            `;

            // 点击通知跳转到详情页
            notificationElement.addEventListener('click', (e) => {
                if (!e.target.closest('.btn-close') && !e.target.closest('.btn')) {
                    window.location.href = `/notifications/${notification.id}/`;
                }
            });

            this.notificationContainer.appendChild(notificationElement);

            // 自动消失
            setTimeout(() => {
                if (notificationElement.parentNode) {
                    notificationElement.classList.remove('show');
                    setTimeout(() => {
                        if (notificationElement.parentNode) {
                            notificationElement.remove();
                        }
                    }, 300);
                }
            }, this.options.notificationDuration);
        });
    }

    /**
     * 显示紧急通知
     */
    showUrgentNotifications(notifications) {
        notifications.forEach(notification => {
            const notificationId = `urgent-notification-${notification.id}`;

            // 如果通知已存在，不重复显示
            if (document.getElementById(notificationId)) {
                return;
            }

            const modalHtml = `
                <div class="modal fade" id="urgentModal-${notification.id}" tabindex="-1" aria-hidden="true">
                    <div class="modal-dialog modal-dialog-centered">
                        <div class="modal-content border-danger">
                            <div class="modal-header bg-danger text-white">
                                <h5 class="modal-title">
                                    <i class="fas fa-exclamation-triangle me-2"></i>紧急通知
                                </h5>
                                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="关闭"></button>
                            </div>
                            <div class="modal-body">
                                <h5 class="mb-3">${notification.title}</h5>
                                <p>${notification.message}</p>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">稍后查看</button>
                                <a href="/notifications/${notification.id}/" class="btn btn-danger">查看详情</a>
                            </div>
                        </div>
                    </div>
                </div>
            `;

            // 添加到页面
            const modalContainer = document.createElement('div');
            modalContainer.innerHTML = modalHtml;
            document.body.appendChild(modalContainer);

            // 显示模态框
            const modalElement = document.getElementById(`urgentModal-${notification.id}`);
            const modal = new bootstrap.Modal(modalElement);
            modal.show();

            // 模态框关闭后移除元素
            modalElement.addEventListener('hidden.bs.modal', () => {
                modalElement.remove();
            });
        });
    }

    /**
     * 确认更新
     */
    async acknowledgeUpdate(questionnaireId) {
        try {
            const response = await fetch(`/questionnaires/${questionnaireId}/acknowledge-update/`, {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': this.getCookie('csrftoken')
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            console.log('更新已确认:', data.message);

            return data;

        } catch (error) {
            console.error('确认更新失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 更新通知徽章
     */
    updateNotificationBadge(count) {
        // 更新页面上的所有通知徽章
        const badges = document.querySelectorAll('.notification-badge, .unread-count-badge');
        badges.forEach(badge => {
            if (count > 0) {
                badge.textContent = count;
                badge.style.display = 'inline';
            } else {
                badge.style.display = 'none';
            }
        });
    }

    /**
     * 添加回调函数
     */
    on(event, callback) {
        this.updateCallbacks.push({ event, callback });
    }

    /**
     * 触发回调
     */
    triggerCallbacks(event, data) {
        this.updateCallbacks.forEach(item => {
            if (item.event === event) {
                item.callback(data);
            }
        });
    }

    /**
     * 获取Cookie
     */
    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
}

// 创建全局实例
window.questionnaireUpdateChecker = new QuestionnaireUpdateChecker();

// 添加CSS动画
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOutRight {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// 页面加载完成后启动检查器
document.addEventListener('DOMContentLoaded', function() {
    // 启动通知检查
    window.questionnaireUpdateChecker.startChecking();

    // 如果当前页面是问卷详情页，开始检查问卷更新
    const questionnaireIdMatch = window.location.pathname.match(/\/questionnaires\/([a-f0-9-]+)\/?$/);
    if (questionnaireIdMatch) {
        window.questionnaireUpdateChecker.startCheckingQuestionnaire(questionnaireIdMatch[1]);
    }
});