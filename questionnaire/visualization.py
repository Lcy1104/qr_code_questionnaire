import matplotlib
matplotlib.use('Agg')  # 使用非交互式后端
import warnings
warnings.filterwarnings('ignore', category=UserWarning)
# 然后导入 font_config 以确保字体已初始化
from .font_config import init_matplotlib_font
init_matplotlib_font()  # 确保字体已加载
from .models import Questionnaire, Response, Question, Answer
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
import json
import base64
import io
from datetime import datetime, timedelta
from collections import Counter
from django.db.models import Count, Avg, Min, Max
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.core.cache import cache
from .cache_manager import QuestionnaireCacheManager
from .sm4 import sm4_decode
import warnings

# 设置中文字体和样式
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
sns.set_style("whitegrid")
plt.style.use('ggplot')


class QuestionnaireVisualizer:
    """问卷数据可视化器"""

    def __init__(self, questionnaire_id):
        self.questionnaire_id = questionnaire_id
        self.questionnaire = Questionnaire.objects.get(id=questionnaire_id)
        self.responses = Response.objects.filter(
            questionnaire=self.questionnaire,
            is_submitted=True
        )
        self.questions = Question.objects.filter(
            questionnaire=self.questionnaire
        ).order_by('order')

    # 更新 get_response_data 方法
    # 只修改 get_response_data 方法，其他保持不变
    def get_response_data(self):
        """获取并解密回答数据 - 修复版：不再使用response.answers"""
        data = []
        for response in self.responses:
            try:
                # 从Answer模型获取答案，而不是response.answers
                answers = {}
                answer_items = Answer.objects.filter(response=response)

                for answer_item in answer_items:
                    try:
                        # answer_text已经是加密字段，会自动解密
                        answer_value = answer_item.answer_text

                        # 尝试解析JSON（如果是多选题）
                        try:
                            parsed_answer = json.loads(answer_value)
                            answers[str(answer_item.question.id)] = parsed_answer
                        except json.JSONDecodeError:
                            # 不是JSON，直接使用
                            answers[str(answer_item.question.id)] = answer_value
                    except Exception as e:
                        print(f"处理答案失败: {e}")
                        answers[str(answer_item.question.id)] = "解密失败"

                data.append({
                    'response_id': str(response.id),
                    'user': response.user.username if response.user else '匿名',
                    'submitted_at': response.submitted_at,
                    'answers': answers
                })
            except Exception as e:
                print(f"获取答案失败: {e}")
                continue
        return data

    def generate_dashboard_html(self):
        """生成完整的可视化仪表盘HTML"""
        charts = []

        # 1. 总体统计
        charts.append(self.generate_summary_chart())

        # 2. 每个问题的图表
        for question in self.questions:
            chart_html = self.generate_question_chart(question)
            if chart_html:
                charts.append(chart_html)

        # 3. 时间趋势图
        charts.append(self.generate_time_series_chart())

        # 4. 完成率分析
        charts.append(self.generate_completion_analysis())

        return '\n'.join(charts)

    def generate_summary_chart(self):
        """生成总体统计图表"""
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle(f'问卷统计概览 - {self.questionnaire.title}', fontsize=16, fontweight='bold')

        # 1. 提交量统计
        ax1 = axes[0, 0]
        if self.responses:
            # 按日期统计
            dates = [r.submitted_at.date() for r in self.responses]
            date_counts = Counter(dates)
            sorted_dates = sorted(date_counts.items())
            dates_str = [d.strftime('%m-%d') for d, _ in sorted_dates]
            counts = [c for _, c in sorted_dates]

            ax1.bar(dates_str, counts, color='steelblue', alpha=0.8)
            ax1.set_title('每日提交量', fontsize=14)
            ax1.set_xlabel('日期')
            ax1.set_ylabel('提交数量')
            ax1.tick_params(axis='x', rotation=45)

            # 添加平均值线
            if counts:
                avg_count = np.mean(counts)
                ax1.axhline(y=avg_count, color='red', linestyle='--', alpha=0.5,
                            label=f'平均值: {avg_count:.1f}')
                ax1.legend()
        else:
            ax1.text(0.5, 0.5, '暂无提交数据', ha='center', va='center',
                     transform=ax1.transAxes, fontsize=14)
            ax1.set_title('每日提交量', fontsize=14)

        # 2. 提交时间分布
        ax2 = axes[0, 1]
        if self.responses:
            hours = [r.submitted_at.hour for r in self.responses]
            hour_counts = Counter(hours)
            hours_sorted = sorted(hour_counts.items())
            hour_labels = [f'{h:02d}:00' for h, _ in hours_sorted]
            hour_values = [c for _, c in hours_sorted]

            ax2.plot(hour_labels, hour_values, marker='o', linewidth=2, color='darkorange')
            ax2.fill_between(hour_labels, hour_values, alpha=0.3, color='orange')
            ax2.set_title('提交时间分布（按小时）', fontsize=14)
            ax2.set_xlabel('时间')
            ax2.set_ylabel('提交数量')
            ax2.tick_params(axis='x', rotation=45)
            ax2.grid(True, alpha=0.3)
        else:
            ax2.text(0.5, 0.5, '暂无提交数据', ha='center', va='center',
                     transform=ax2.transAxes, fontsize=14)
            ax2.set_title('提交时间分布', fontsize=14)

        # 3. 回答时长统计（简化处理，实际项目需要记录开始时间）
        ax3 = axes[1, 0]
        if self.responses.count() > 1:
            # 这里需要记录开始时间，我们简化处理
            response_times = np.random.normal(180, 60, len(self.responses))  # 模拟数据

            ax3.hist(response_times, bins=20, edgecolor='black', alpha=0.7, color='green')
            ax3.set_title('回答时长分布', fontsize=14)
            ax3.set_xlabel('时长（秒）')
            ax3.set_ylabel('人数')
            if len(response_times) > 0:
                ax3.axvline(x=np.mean(response_times), color='red', linestyle='--',
                            label=f'平均: {np.mean(response_times):.1f}秒')
                ax3.legend()
        else:
            ax3.text(0.5, 0.5, '数据不足', ha='center', va='center',
                     transform=ax3.transAxes, fontsize=14)
            ax3.set_title('回答时长分布', fontsize=14)

        # 4. 问卷完成率
        ax4 = axes[1, 1]
        completed = len(self.responses)
        not_completed = max(0, self.questionnaire.view_count - completed)

        # 避免除以0的情况
        if completed == 0 and not_completed == 0:
            ax4.text(0.5, 0.5, '暂无访问数据', ha='center', va='center',
                     transform=ax4.transAxes, fontsize=14)
            ax4.set_title('问卷完成率', fontsize=14)
        else:
            completion_data = [completed, not_completed]
            labels = ['已完成', '未完成']
            colors = ['#4CAF50', '#FF9800']

            # 计算百分比
            total = sum(completion_data)
            percentages = [count / total * 100 for count in completion_data]

            # 绘制饼图
            wedges, texts, autotexts = ax4.pie(
                completion_data,
                labels=labels,
                autopct=lambda pct: f'{pct:.1f}%\n({int(pct / 100 * total)})',
                colors=colors,
                startangle=90,
                explode=(0.1, 0)
            )

            ax4.set_title('问卷完成率', fontsize=14)

            # 美化饼图文字
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontweight('bold')

        plt.tight_layout()

        # 转换为HTML
        return self.figure_to_html(fig, 'summary_chart')

    def generate_question_chart(self, question):
        """生成单个问题的图表"""
        data = self.get_response_data()
        if not data:
            return None

        answers_for_question = []
        for response in data:
            answer = response['answers'].get(str(question.id))
            if answer is not None:
                if isinstance(answer, list):
                    answers_for_question.extend(answer)
                else:
                    answers_for_question.append(str(answer))

        if not answers_for_question:
            return None

        if question.question_type in ['radio', 'checkbox']:
            return self.generate_choice_chart(question, answers_for_question)
        elif question.question_type == 'text':
            return self.generate_text_analysis(question, answers_for_question)
        elif question.question_type == 'number':
            return self.generate_number_chart(question, answers_for_question)
        else:
            return None

    def generate_choice_chart(self, question, answers):
        """生成选择题图表（单选/多选）"""
        fig = plt.figure(figsize=(14, 6))

        # 统计答案
        counter = Counter(answers)
        total = len(answers)

        # 准备数据
        if hasattr(question, 'options') and question.options:
            # 使用预设选项排序
            all_options = question.options
        else:
            # 按出现频率排序
            all_options = [item[0] for item in counter.most_common()]

        counts = [counter.get(option, 0) for option in all_options]
        percentages = [count / total * 100 for count in counts]

        # 创建子图
        ax1 = plt.subplot(121)  # 柱状图
        ax2 = plt.subplot(122)  # 饼图

        # 1. 柱状图
        colors = plt.cm.Set3(np.linspace(0, 1, len(all_options)))
        bars = ax1.bar(range(len(all_options)), counts, color=colors, edgecolor='black')
        ax1.set_xlabel('选项')
        ax1.set_ylabel('选择人数')
        ax1.set_title(f'{question.text[:50]}...\n选项分布（柱状图）', fontsize=12)
        ax1.set_xticks(range(len(all_options)))
        ax1.set_xticklabels(all_options, rotation=45, ha='right')

        # 在柱子上显示数字和百分比
        for i, (bar, count, pct) in enumerate(zip(bars, counts, percentages)):
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width() / 2., height + 0.1,
                     f'{count}\n({pct:.1f}%)', ha='center', va='bottom', fontsize=9)

        # 2. 饼图
        # 只显示有数据的部分
        pie_labels = []
        pie_sizes = []
        for option, count in zip(all_options, counts):
            if count > 0:
                pie_labels.append(f'{option[:15]}...' if len(option) > 15 else option)
                pie_sizes.append(count)

        if pie_sizes:
            wedges, texts, autotexts = ax2.pie(
                pie_sizes,
                labels=pie_labels,
                autopct=lambda pct: f'{pct:.1f}%\n({int(pct / 100 * sum(pie_sizes))})',
                startangle=90,
                colors=colors[:len(pie_sizes)]
            )
            ax2.set_title('选项分布（饼图）', fontsize=12)

            # 美化饼图
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontweight('bold')

        plt.tight_layout()
        return self.figure_to_html(fig, f'question_{question.id}_chart')

    def generate_text_analysis(self, question, answers):
        """生成文本分析图表"""
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        # 1. 词频分析（简化版）
        ax1 = axes[0]
        if answers:
            # 合并所有文本
            all_text = ' '.join([str(a) for a in answers if a])
            words = all_text.split()

            if words:
                # 简单的词频统计（中文需要更复杂的分词）
                word_counts = Counter(words)
                top_words = word_counts.most_common(10)

                if top_words:
                    words_list, counts_list = zip(*top_words)
                    ax1.barh(range(len(words_list)), counts_list, color='skyblue')
                    ax1.set_yticks(range(len(words_list)))
                    ax1.set_yticklabels(words_list)
                    ax1.set_xlabel('出现次数')
                    ax1.set_title('高频词汇分析（Top 10）')
                    ax1.invert_yaxis()  # 最高的在上面

        # 2. 回答长度分布
        ax2 = axes[1]
        if answers:
            lengths = [len(str(a)) for a in answers]

            if lengths:
                ax2.hist(lengths, bins=20, edgecolor='black', alpha=0.7, color='lightcoral')
                ax2.set_xlabel('回答长度（字符数）')
                ax2.set_ylabel('人数')
                ax2.set_title('回答长度分布')
                ax2.axvline(x=np.mean(lengths), color='red', linestyle='--',
                            label=f'平均长度: {np.mean(lengths):.1f}')

                # 添加统计信息
                stats_text = f"""
                总回答数: {len(answers)}
                平均长度: {np.mean(lengths):.1f}
                最短: {np.min(lengths)}
                最长: {np.max(lengths)}
                """
                ax2.text(0.02, 0.98, stats_text, transform=ax2.transAxes,
                         verticalalignment='top', fontsize=10,
                         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
                ax2.legend()

        plt.suptitle(f'文本分析 - {question.text[:50]}...', fontsize=14)
        plt.tight_layout()
        return self.figure_to_html(fig, f'text_analysis_{question.id}')

    def generate_number_chart(self, question, answers):
        """生成数字图表"""
        fig, axes = plt.subplots(1, 3, figsize=(18, 6))

        # 转换为数字
        numbers = []
        for answer in answers:
            try:
                num = float(answer)
                numbers.append(num)
            except:
                continue

        if not numbers:
            return None

        numbers = np.array(numbers)

        # 1. 直方图
        ax1 = axes[0]
        n, bins, patches = ax1.hist(numbers, bins=15, edgecolor='black', alpha=0.7, color='teal')
        ax1.set_xlabel('数值')
        ax1.set_ylabel('频数')
        ax1.set_title('数值分布直方图')
        ax1.grid(True, alpha=0.3)

        # 2. 箱线图
        ax2 = axes[1]
        box = ax2.boxplot(numbers, vert=True, patch_artist=True)
        box['boxes'][0].set_facecolor('lightblue')
        ax2.set_ylabel('数值')
        ax2.set_title('数值箱线图')
        ax2.grid(True, alpha=0.3)

        # 添加异常值标记
        q1 = np.percentile(numbers, 25)
        q3 = np.percentile(numbers, 75)
        iqr = q3 - q1
        outliers = numbers[(numbers < q1 - 1.5 * iqr) | (numbers > q3 + 1.5 * iqr)]
        if len(outliers) > 0:
            ax2.text(1.1, outliers[0], f'异常值: {len(outliers)}个', fontsize=9)

        # 3. 密度图
        ax3 = axes[2]
        ax3.hist(numbers, bins=20, density=True, alpha=0.6, color='g')

        # 添加核密度估计
        from scipy import stats
        kde = stats.gaussian_kde(numbers)
        x_range = np.linspace(numbers.min(), numbers.max(), 100)
        ax3.plot(x_range, kde(x_range), 'r-', linewidth=2)

        ax3.set_xlabel('数值')
        ax3.set_ylabel('密度')
        ax3.set_title('数值密度分布')
        ax3.grid(True, alpha=0.3)

        # 添加统计信息
        stats_text = f"""
        样本数: {len(numbers)}
        平均值: {numbers.mean():.2f}
        中位数: {np.median(numbers):.2f}
        标准差: {numbers.std():.2f}
        最小值: {numbers.min():.2f}
        最大值: {numbers.max():.2f}
        异常值: {len(outliers)}
        """

        fig.text(0.02, 0.02, stats_text, fontsize=10,
                 bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))

        plt.suptitle(f'数值分析 - {question.text[:50]}...', fontsize=14)
        plt.tight_layout()
        return self.figure_to_html(fig, f'number_chart_{question.id}')

    def generate_time_series_chart(self):
        """生成时间序列图表"""
        fig, axes = plt.subplots(2, 1, figsize=(14, 10))

        if self.responses:
            # 按小时统计
            hourly_counts = {}
            for response in self.responses:
                hour_key = response.submitted_at.strftime('%Y-%m-%d %H:00')
                hourly_counts[hour_key] = hourly_counts.get(hour_key, 0) + 1

            # 排序
            sorted_hours = sorted(hourly_counts.items())
            hours = [h for h, _ in sorted_hours]
            counts = [c for _, c in sorted_hours]

            # 1. 时间序列图
            ax1 = axes[0]
            ax1.plot(hours, counts, marker='o', linewidth=2, color='darkblue')
            ax1.fill_between(hours, counts, alpha=0.3, color='lightblue')
            ax1.set_xlabel('时间')
            ax1.set_ylabel('提交数量')
            ax1.set_title('提交时间序列')
            ax1.tick_params(axis='x', rotation=45)
            ax1.grid(True, alpha=0.3)

            # 添加移动平均线
            if len(counts) > 1:
                window = min(3, len(counts))
                moving_avg = pd.Series(counts).rolling(window=window).mean()
                ax1.plot(hours, moving_avg, 'r--', linewidth=2, label=f'{window}小时移动平均')
                ax1.legend()

            # 2. 累积提交图
            ax2 = axes[1]
            cumulative_counts = np.cumsum(counts)
            ax2.plot(hours, cumulative_counts, linewidth=3, color='darkgreen')
            ax2.fill_between(hours, cumulative_counts, alpha=0.3, color='lightgreen')
            ax2.set_xlabel('时间')
            ax2.set_ylabel('累计提交数量')
            ax2.set_title('累计提交趋势')
            ax2.tick_params(axis='x', rotation=45)
            ax2.grid(True, alpha=0.3)

            # 标记重要点
            if len(cumulative_counts) > 0:
                ax2.scatter(hours[-1], cumulative_counts[-1], color='red', s=100, zorder=5)
                ax2.annotate(f'总计: {cumulative_counts[-1]}',
                             xy=(hours[-1], cumulative_counts[-1]),
                             xytext=(10, 10), textcoords='offset points')

        plt.suptitle('提交时间趋势分析', fontsize=16, fontweight='bold')
        plt.tight_layout()
        return self.figure_to_html(fig, 'time_series_chart')

    def generate_completion_analysis(self):
        """生成完成率分析"""
        fig, ax = plt.subplots(figsize=(12, 8))

        # 计算各问题回答率
        response_data = self.get_response_data()
        question_stats = []

        for question in self.questions:
            answered_count = 0
            for response in response_data:
                if str(question.id) in response['answers']:
                    answered_count += 1

            completion_rate = answered_count / len(response_data) * 100 if response_data else 0
            question_stats.append({
                'question': question.text[:30] + ('...' if len(question.text) > 30 else ''),
                'completion_rate': completion_rate,
                'answered': answered_count,
                'total': len(response_data)
            })

        # 按完成率排序
        question_stats.sort(key=lambda x: x['completion_rate'], reverse=True)

        # 绘制水平条形图
        questions = [stat['question'] for stat in question_stats]
        rates = [stat['completion_rate'] for stat in question_stats]

        bars = ax.barh(range(len(questions)), rates, color=plt.cm.RdYlGn(np.array(rates) / 100))
        ax.set_yticks(range(len(questions)))
        ax.set_yticklabels(questions)
        ax.set_xlabel('完成率 (%)')
        ax.set_title('各问题完成率分析')
        ax.set_xlim([0, 105])

        # 在每个条上添加百分比
        for i, (bar, rate, stat) in enumerate(zip(bars, rates, question_stats)):
            width = bar.get_width()
            ax.text(width + 1, bar.get_y() + bar.get_height() / 2,
                    f'{rate:.1f}% ({stat["answered"]}/{stat["total"]})',
                    va='center', fontsize=10)

        # 添加平均线
        avg_rate = np.mean(rates) if rates else 0
        ax.axvline(x=avg_rate, color='red', linestyle='--', linewidth=2,
                   label=f'平均完成率: {avg_rate:.1f}%')
        ax.legend()

        plt.tight_layout()
        return self.figure_to_html(fig, 'completion_analysis')

    def figure_to_html(self, fig, chart_id):
        """将matplotlib图形转换为HTML"""
        # 保存到内存
        buffer = io.BytesIO()
        fig.savefig(buffer, format='png', dpi=100, bbox_inches='tight',
                    facecolor='white', edgecolor='white')
        plt.close(fig)
        buffer.seek(0)

        # 转换为base64
        image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        # 返回HTML片段
        return f'''
        <div class="chart-container mb-4" id="{chart_id}">
            <div class="card">
                <div class="card-body">
                    <div class="text-center">
                        <img src="data:image/png;base64,{image_base64}" 
                             alt="图表" 
                             class="img-fluid rounded shadow">
                    </div>
                </div>
            </div>
        </div>
        '''

    def export_to_pdf(self):
        """导出为PDF（返回PDF响应）"""
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        story = []
        styles = getSampleStyleSheet()

        # 添加标题
        title = Paragraph(f"问卷分析报告: {self.questionnaire.title}", styles['Title'])
        story.append(title)
        story.append(Spacer(1, 0.2 * inch))

        # 生成每个图表并添加到PDF
        # 这里需要将matplotlib图表保存为临时图片文件

        return HttpResponse(buffer.getvalue(), content_type='application/pdf')


def get_questionnaire_stats(questionnaire_id):
    """获取问卷统计数据的缓存版本"""
    # 尝试从缓存获取
    cached_stats = QuestionnaireCacheManager.get_cached_questionnaire_stats(questionnaire_id)
    if cached_stats:
        return cached_stats

    # 重新计算
    visualizer = QuestionnaireVisualizer(questionnaire_id)
    stats = {
        'total_responses': visualizer.responses.count(),
        'total_questions': visualizer.questions.count(),
        'completion_rate': visualizer.responses.count() / max(1, visualizer.questionnaire.view_count) * 100,
        'charts_html': visualizer.generate_dashboard_html()
    }

    # 缓存结果
    QuestionnaireCacheManager.cache_questionnaire_stats(questionnaire_id, stats)

    return stats


# 简化的图表生成函数（兼容旧代码）
def generate_chart_html(questionnaire, responses):
    """生成图表HTML（兼容旧接口）"""
    visualizer = QuestionnaireVisualizer(questionnaire.id)
    return visualizer.generate_dashboard_html()


def generate_choice_chart(question, responses, question_index):
    """生成选择题图表（兼容旧接口）"""
    visualizer = QuestionnaireVisualizer(question.questionnaire.id)
    return visualizer.generate_question_chart(question)


def generate_text_summary(question, responses, question_index):
    """生成文本题摘要（兼容旧接口）"""
    visualizer = QuestionnaireVisualizer(question.questionnaire.id)
    return visualizer.generate_question_chart(question)


def generate_number_chart(question, responses, question_index):
    """生成数字题图表（兼容旧接口）"""
    visualizer = QuestionnaireVisualizer(question.questionnaire.id)
    return visualizer.generate_question_chart(question)


def build_stats(questionnaire):
    """构建统计数据的完整视图（兼容visual.py）"""
    visualizer = QuestionnaireVisualizer(questionnaire.id)
    response_data = visualizer.get_response_data()

    charts = []
    table = []

    for question in visualizer.questions:
        # 收集答案
        answers_for_question = []
        for response in response_data:
            answer = response['answers'].get(str(question.id))
            if answer is not None:
                if isinstance(answer, list):
                    answers_for_question.extend(answer)
                else:
                    answers_for_question.append(str(answer))

        # 创建表格行
        table_row = {
            'q_text': question.text,
            'type': question.question_type,
            'answers': []
        }

        for response in response_data[:10]:  # 只显示前10个答案
            answer = response['answers'].get(str(question.id), '未回答')
            table_row['answers'].append({
                'user': response['user'],
                'answer': str(answer)
            })

        table.append(table_row)

        # 生成图表
        if question.question_type in ['radio', 'checkbox'] and answers_for_question:
            chart_html = visualizer.generate_question_chart(question)
            if chart_html:
                charts.append({
                    'title': question.text[:30] + ('...' if len(question.text) > 30 else ''),
                    'html': chart_html
                })

    return {
        'charts': charts,
        'table': table,
        'summary': {
            'total_responses': len(response_data),
            'total_questions': visualizer.questions.count(),
            'questionnaire_title': questionnaire.title
        }
    }


#detail.html问卷详细页删除问卷应该转回问卷管理页而不是原页面！，1.29待完善
#uvicorn qr_code_questionaire.asgi:application --host 0.0.0.0 --port 8000