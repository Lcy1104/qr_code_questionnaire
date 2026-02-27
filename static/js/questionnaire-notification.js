/**
 * 问卷通知系统
 */
(function() {
    'use strict';

    // 配置
    const CONFIG = {
        notificationDuration: 8000, // 8秒后自动隐藏
        storageKey: 'questionnaire_notifications'
    };

    // 工具函数
    const Utils = {
        getCSRFToken() {
            const token = document.querySelector('[name=csrfmiddlewaretoken]');
            return token ? token.value : '';
        },

        showNotification(message, type = 'info') {
            const container = document.createElement('div');
            container.className = `notification notification-${type}`;
            container.innerHTML = `
                <div class="notification-content">
                    <span>${message}</span>
                    <button class="notification-close">&times;</button>
                </div>
            `;

            document.body.appendChild(container);

            // 自动移除
            setTimeout(() => {
                container.classList.add('fade-out');
                setTimeout(() => container.remove(), 300);
            }, CONFIG.notificationDuration);

            // 关闭按钮
            container.querySelector('.notification-close').addEventListener('click', () => {
                container.classList.add('fade-out');
                setTimeout(() => container.remove(), 300);
            });
        }
    };

    // 更新检查类
    class UpdateChecker {
        constructor(questionnaireId) {
            this.questionnaireId = questionnaireId;
            this.notificationShown = false;
        }

        async check() {
            try {
                const response = await fetch(`/questionnaires/${this.questionnaireId}/check-update/`);
                const data = await response.json();

                if (data.needs_update) {
                    this.showUpdateAlert(data);
                    return true;
                }
                return false;
            } catch (error) {
                console.error('更新检查失败:', error);
                return false;
            }
        }

        showUpdateAlert(data) {
            if (this.notificationShown) return;

            const alert = document.createElement('div');
            alert.className = 'alert alert-warning questionnaire-update-alert';
            alert.innerHTML = `
                <div class="d-flex align-items-center">
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    <div class="flex-grow-1">
                        <strong>问卷已更新</strong>
                        <p class="mb-0 small">${data.update_message}</p>
                    </div>
                    <button class="btn btn-sm btn-outline-primary me-2" id="update-remind-later">稍后</button>
                    <button class="btn btn-sm btn-primary" id="update-acknowledge">知道了</button>
                </div>
            `;

            const container = document.querySelector('.container, .content-wrapper, main');
            if (container) {
                container.prepend(alert);
                this.setupAlertEvents(alert);
                this.notificationShown = true;
            }
        }

        setupAlertEvents(alert) {
            // 稍后提醒
            alert.querySelector('#update-remind-later').addEventListener('click', () => {
                alert.remove();
                this.notificationShown = false;
                // 5分钟后重新显示
                setTimeout(() => this.check(), 5 * 60 * 1000);
            });

            // 确认更新
            alert.querySelector('#update-acknowledge').addEventListener('click', async () => {
                const button = alert.querySelector('#update-acknowledge');
                button.disabled = true;
                button.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

                try {
                    await fetch(`/questionnaires/${this.questionnaireId}/acknowledge-update/`, {
                        method: 'POST',
                        headers: {
                            'X-CSRFToken': Utils.getCSRFToken(),
                        }
                    });

                    alert.remove();
                    this.notificationShown = false;
                    Utils.showNotification('更新已确认', 'success');
                } catch (error) {
                    console.error('确认更新失败:', error);
                    button.disabled = false;
                    button.textContent = '知道了';
                    Utils.showNotification('操作失败，请重试', 'error');
                }
            });
        }
    }

    // 自动初始化
    document.addEventListener('DOMContentLoaded', function() {
        // 检查是否有问卷ID
        const container = document.querySelector('[data-questionnaire-id]');
        if (!container) return;

        const questionnaireId = container.getAttribute('data-questionnaire-id');
        if (!questionnaireId) return;

        // 延迟检查，让页面先加载
        setTimeout(() => {
            const checker = new UpdateChecker(questionnaireId);
            checker.check();
        }, 1000);
    });

    // 全局导出
    window.QuestionnaireNotifications = {
        UpdateChecker,
        Utils
    };

})();