// 改进的选项添加功能
class OptionsManager {
    constructor(questionIndex) {
        this.questionIndex = questionIndex;
        this.optionsList = document.getElementById(`options-list-${questionIndex}`);
        this.optionsContainer = document.getElementById(`options-container-${questionIndex}`);
        this.hiddenTextarea = document.querySelector(`[name="questions-${questionIndex}-options_text"]`);
        this.initOptions();
    }

    initOptions() {
        // 初始化选项列表
        if (!this.optionsList) return;

        // 如果已有选项，显示它们
        const existingOptions = this.getExistingOptions();
        if (existingOptions.length > 0) {
            existingOptions.forEach((option, index) => {
                this.addOptionElement(option, index);
            });
        } else {
            // 默认添加两个空选项
            this.addOption();
            this.addOption();
        }
    }

    getExistingOptions() {
        // 从隐藏文本域获取已有选项
        if (this.hiddenTextarea && this.hiddenTextarea.value) {
            return this.hiddenTextarea.value.split('\n').filter(opt => opt.trim());
        }
        return [];
    }

    addOption(initialValue = '') {
        const optionCount = this.optionsList.children.length;

        // 创建选项元素
        const optionDiv = document.createElement('div');
        optionDiv.className = 'option-item mb-2';
        optionDiv.innerHTML = `
            <div class="input-group">
                <span class="input-group-text option-letter">
                    ${String.fromCharCode(65 + optionCount)}
                </span>
                <input type="text" class="form-control option-input" 
                       placeholder="请输入选项内容" value="${initialValue}"
                       oninput="updateOptionsText(${this.questionIndex})">
                <button type="button" class="btn btn-outline-danger remove-option" 
                        onclick="removeOption(this, ${this.questionIndex})">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        `;

        this.optionsList.appendChild(optionDiv);
        this.updateOptionsText();
        this.updateLetterLabels();
    }

    removeOption(button) {
        const optionItem = button.closest('.option-item');
        if (optionItem) {
            optionItem.remove();
            this.updateOptionsText();
            this.updateLetterLabels();
        }
    }

    updateLetterLabels() {
        const optionItems = this.optionsList.querySelectorAll('.option-item');
        optionItems.forEach((item, index) => {
            const letterSpan = item.querySelector('.option-letter');
            if (letterSpan) {
                letterSpan.textContent = String.fromCharCode(65 + index);
            }
        });
    }

    updateOptionsText() {
        if (!this.hiddenTextarea) return;

        const optionInputs = this.optionsList.querySelectorAll('.option-input');
        const options = Array.from(optionInputs)
            .map(input => input.value.trim())
            .filter(value => value.length > 0);

        this.hiddenTextarea.value = options.join('\n');
    }

    addOptionButton(container) {
        const addButton = document.createElement('button');
        addButton.type = 'button';
        addButton.className = 'btn btn-sm btn-outline-primary mt-2';
        addButton.innerHTML = '<i class="fas fa-plus me-1"></i>添加选项';
        addButton.onclick = () => this.addOption();
        container.appendChild(addButton);
    }
}

// 初始化所有问题的选项管理器
document.addEventListener('DOMContentLoaded', function() {
    // 为每个问题初始化选项管理器
    const questionItems = document.querySelectorAll('.question-item');
    questionItems.forEach((item, index) => {
        const questionIndex = item.id.replace('question-', '');
        const typeSelect = item.querySelector('.question-type-select');

        if (typeSelect) {
            // 初始显示/隐藏选项区域
            toggleOptionsArea(questionIndex, typeSelect.value);

            // 监听类型变化
            typeSelect.addEventListener('change', function() {
                toggleOptionsArea(questionIndex, this.value);
            });
        }
    });
});

function toggleOptionsArea(questionIndex, questionType) {
    const optionsContainer = document.getElementById(`options-container-${questionIndex}`);
    const maxlengthContainer = document.getElementById(`maxlength-container-${questionIndex}`);

    if (!optionsContainer || !maxlengthContainer) return;

    const showOptions = questionType === 'radio' || questionType === 'checkbox';
    const showMaxLength = questionType === 'text';

    optionsContainer.style.display = showOptions ? 'block' : 'none';
    maxlengthContainer.style.display = showMaxLength ? 'block' : 'none';

    // 如果是选择题且选项容器已显示，初始化选项管理器
    if (showOptions) {
        new OptionsManager(questionIndex);
    }
}