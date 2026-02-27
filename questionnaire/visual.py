from .models import Answer
from .utils import pie_base64
import json

def build_stats(questionnaire):
    """
    返回 dict
      charts: [{title, img_base64}, ...]
      table:  [{q_text, type, answers:[{user, answer}]}, ...]
    """
    qs = questionnaire.qs.order_by('order')
    table = []
    charts = []
    for q in qs:
        ans = Answer.objects.filter(questionnaire=questionnaire, q_order=q.order)
        row = {'q_text': q.get_text(), 'type': q.q_type, 'answers': []}
        if q.q_type in ('radio', 'checkbox'):
            counter = {}
            a: Answer
            for a in ans:
                for v in a.get_answer_text().split('|'):
                    counter[v] = counter.get(v, 0) + 1
            if counter:
                charts.append({
                    'title': q.get_text()[:30],
                    'img_base64': pie_base64(list(counter.keys()), list(counter.values()))
                })
        for a in ans:
            row['answers'].append({'user': a.user.username, 'answer': a.get_answer_text()})
        table.append(row)
    return {'charts': charts, 'table': table}