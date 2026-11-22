import calendar
from datetime import date, timedelta
from .schemas import Schedule

def budget(schedule):
    s=Schedule.model_validate(schedule)
    start=s.start
    if s.duration=='15d': end=start+timedelta(days=15)
    else:
        months=int(s.duration[:-1]); n=start.year*12+start.month-1+months
        year,month=divmod(n,12); month+=1
        end=date(year,month,min(start.day,calendar.monthrange(year,month)[1]))
    slots=[]; d=start
    while d<end:
        if str(d.isoweekday()) in s.days:
            slots.append({'date':d.isoformat(),'minutes':s.days[str(d.isoweekday())]})
        d+=timedelta(days=1)
    return {'start':start.isoformat(),'end':(end-timedelta(days=1)).isoformat(),
            'total_minutes':sum(x['minutes'] for x in slots),'slots':slots}

def order_topics(topics):
    by_id={x['id']:x for x in topics}
    if len(by_id)!=len(topics): raise ValueError('Повторяются идентификаторы тем')
    ordered=[]; seen=set(); visiting=set()
    def visit(t):
        if t['id'] in seen:return
        if t['id'] in visiting: raise ValueError('Циклическая зависимость тем')
        visiting.add(t['id'])
        for p in t['prerequisites']:
            if p not in by_id: raise ValueError('Неизвестная предпосылка темы')
            visit(by_id[p])
        visiting.remove(t['id']);seen.add(t['id']);ordered.append(t)
    for t in topics: visit(t)
    return ordered

class InsufficientTime(ValueError):
    def __init__(self, required, available):
        self.required=required;self.available=available
        super().__init__(f'Недостаточно времени: нужно {required} мин., доступно {available} мин. Увеличьте срок или нагрузку; если ваш уровень знаний указан неверно, измените его в настройках.')

def allocate(topics, schedule):
    b=budget(schedule); ordered=order_topics(topics)
    learning=sum(t['minutes'] for t in ordered)
    review=(learning+3)//4 if learning else 0
    if learning+review>b['total_minutes']: raise InsufficientTime(learning+review,b['total_minutes'])
    tasks=[dict(topic_id=t['id'], title=t['title'], minutes=t['minutes'],kind='learn') for t in ordered]
    if review: tasks.append(dict(topic_id=None,title='Повторение и пробный экзамен',minutes=review,kind='review'))
    entries=[]; i=0; remaining=b['slots'][0]['minutes'] if b['slots'] else 0
    for task in tasks:
        left=task['minutes']; part=1
        while left:
            if not remaining:
                i+=1;remaining=b['slots'][i]['minutes']
            n=min(left,remaining)
            entries.append({**task,'date':b['slots'][i]['date'],'minutes':n,'part':part})
            left-=n;remaining-=n;part+=1
    return {'sessions':entries,'budget':b,'learning_minutes':learning,'review_minutes':review,'required_minutes':learning+review}

