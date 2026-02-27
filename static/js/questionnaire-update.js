/**
 * 问卷更新检查与通知功能
 */
class QuestionnaireUpdateChecker {
    constructor() {
        this.csrfToken = this.getCSRFToken();
        this.notificationTimeout = 5000; // 5秒后自动隐藏
        this.acknowledgedUpdates = this.getAcknowledgedUpdates();
    }

    /**
     * 获取CSRF令牌
     */
    getCSRFToken() {
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]');
        if (csrfToken) {
            return csrfToken.value;
        }

        const metaToken = document.querySelector('meta[name="csrf-token"]');
        if (metaToken) {
            return metaToken.getAttribute('content');
        }

        console.warn('CSRF token not found');
        return '';
    }

    /**
     * 从本地存储获取已确认的更新
     */
    getAcknowledgedUpdates() {
        try {
            return JSON.parse(localStorage.getItem('acknowledgedUpdates') || '{}');
        } catch (e) {
            console.warn('Failed to parse acknowledged updates from localStorage', e);
            return {};
        }
    }

    /**
     * 保存已确认的更新到本地存储
     */
    saveAcknowledgedUpdate(questionnaireId) {
        this.acknowledgedUpdates[questionnaireId] = true;
        try {
            localStorage.setItem('acknowledgedUpdates', JSON.stringify(this.acknowledgedUpdates));
        } catch (e) {
            console.warn('Failed to save acknowledged update to localStorage', e);
        }
    }

    /**
     * 检查问卷是否有更新
     */
    async checkForUpdate(questionnaireId) {
        try {
            // 如果用户已经确认过这个更新，就不再检查
            if (this.acknowledgedUpdates[questionnaireId]) {
                console.log(`问卷 ${questionnaireId} 的更新已被用户确认`);
                return null;
            }

            const response = await fetch(`/questionnaires/${questionnaireId}/check-update/`);

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            return data.needs_update ? data : null;

        } catch (error) {
            console.error('检查问卷更新失败:', error);
            return null;
        }
    }

    /**
     * 显示更新通知
     */
    showUpdateNotification(questionnaireId, updateData) {
        // 防止重复显示通知
        const existingNotification = document.querySelector('.questionnaire-update-notification');
        if (existingNotification) {
            existingNotification.remove();
        }

        // 创建通知元素
        const notification = document.createElement('div');
        notification.className = 'questionnaire-update-notification alert alert-warning alert-dismissible fade show position-fixed';
        notification.style.cssText = `
            top: 20px;
            right: 20px;
            z-index: 1050;
            max-width: 400px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        `;

        notification.innerHTML = `
            <div class="d-flex align-items-start">
                <div class="flex-grow-1">
                    <h6 class="alert-heading mb-1">
                        <i class="fas fa-sync-alt me-2"></i>问卷已更新
                    </h6>
                    <p class="mb-2 small">${updateData.update_message}</p>
                    <div class="d-flex justify-content-between align-items-center">
                        <small class="text-muted">
                            <i class="fas fa-info-circle me-1"></i>
                            版本 ${updateData.user_version} → ${updateData.current_version}
                        </small>
                        <div>
                            <button type="button" class="btn btn-sm btn-outline-secondary me-2" id="remind-later">
                                稍后提醒
                            </button>
                            <button type="button" class="btn btn-sm btn-primary" id="acknowledge-update">
                                我已了解
                            </button>
                        </div>
                    </div>
                </div>
                <button type="button" class="btn-close ms-3" data-bs-dismiss="alert" aria-label="关闭"></button>
            </div>
        `;

        document.body.appendChild(notification);

        // 添加事件监听器
        this.setupNotificationEvents(notification, questionnaireId);

        // 自动隐藏（可选）
        if (this.notificationTimeout > 0) {
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.classList.remove('show');
                    setTimeout(() => notification.remove(), 150);
                }
            }, this.notificationTimeout);
        }
    }

    /**
     * 设置通知事件
     */
    setupNotificationEvents(notification, questionnaireId) {
        // 关闭按钮
        const closeBtn = notification.querySelector('.btn-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                this.saveAcknowledgedUpdate(questionnaireId);
            });
        }

        // 稍后提醒按钮
        const remindLaterBtn = notification.querySelector('#remind-later');
        if (remindLaterBtn) {
            remindLaterBtn.addEventListener('click', () => {
                notification.classList.remove('show');
                setTimeout(() => notification.remove(), 150);
                // 设置10分钟后重新提醒
                setTimeout(() => {
                    delete this.acknowledgedUpdates[questionnaireId];
                    this.saveAcknowledgedUpdate(questionnaireId);
                }, 10 * 60 * 1000);
            });
        }

        // 确认按钮
        const acknowledgeBtn = notification.querySelector('#acknowledge-update');
        if (acknowledgeBtn) {
            acknowledgeBtn.addEventListener('click', async () => {
                acknowledgeBtn.disabled = true;
                acknowledgeBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>处理中...';

                try {
                    await this.acknowledgeUpdate(questionnaireId);
                    notification.classList.remove('show');
                    setTimeout(() => notification.remove(), 150);
                } catch (error) {
                    console.error('确认更新失败:', error);
                    acknowledgeBtn.disabled = false;
                    acknowledgeBtn.textContent = '我已了解';
                }
            });
        }
    }

    /**
     * 向服务器确认更新
     */
    async acknowledgeUpdate(questionnaireId) {
        const response = await fetch(`/questionnaires/${questionnaireId}/acknowledge-update/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': this.csrfToken,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ acknowledged: true })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        if (data.status === 'success') {
            this.saveAcknowledgedUpdate(questionnaireId);
        }

        return data;
    }

    /**
     * 初始化问卷更新检查
     */
    async init(questionnaireId) {
        if (!questionnaireId) {
            console.warn('未提供问卷ID');
            return;
        }

        try {
            const updateData = await this.checkForUpdate(questionnaireId);
            if (updateData) {
                this.showUpdateNotification(questionnaireId, updateData);
            }
        } catch (error) {
            console.error('初始化问卷更新检查失败:', error);
        }
    }
}

// 导出为全局变量
window.QuestionnaireUpdateChecker = QuestionnaireUpdateChecker;