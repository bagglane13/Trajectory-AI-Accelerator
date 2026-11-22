"""Adaptive blueprint from real graded attempts, with 70% of slots on past mistakes."""
from collections import Counter
import random
from sqlalchemy import select
from .db import Lesson, Attempt, Exam, ExamAttempt, Chunk, Document
from .materials import retrieve


def weaknesses(db,cid):
    rows=db.execute(select(Attempt,Lesson.id).join(Lesson,Lesson.id==Attempt.lesson_id).where(Lesson.course_id==cid)).all()
    wrong=Counter();total=Counter()
    for a,lid in rows:
        if a.result.get('status')=='graded':
            total[lid]+=1
            if a.result.get('score',100)<70:wrong[lid]+=1
    past=db.scalars(select(ExamAttempt).join(Exam,Exam.id==ExamAttempt.exam_id).where(Exam.course_id==cid)).all()
    for a in past:
        for item in a.result.get('items',[]):
            total[item['lesson_id']]+=1
            if not item['correct']:wrong[item['lesson_id']]+=1
    lessons=db.scalars(select(Lesson).where(Lesson.course_id==cid).order_by(Lesson.position)).all()
    return [{'lesson_id':l.id,'title':l.topic['title'],'wrong':wrong[l.id],'attempts':total[l.id]} for l in lessons]


def blueprint(db,cid,seed,count=10):
    stats=weaknesses(db,cid)
    weak=sorted([x for x in stats if x['wrong']],key=lambda x:(-x['wrong'],-x['wrong']/max(x['attempts'],1),x['lesson_id']))
    strong=[x for x in stats if not x['wrong']]
    if not stats:raise ValueError('Сначала создайте темы курса')
    rng=random.Random(seed);rng.shuffle(strong)
    # Cover each weak topic before repeating. If every topic is weak, every slot is weak.
    selected=[weak[i%len(weak)] for i in range((count*7+9)//10)] if weak else []
    rest=strong or weak or stats
    selected += [rest[i%len(rest)] for i in range(count-len(selected))]
    rng.shuffle(selected)
    return [{'id':f'q{i+1}','lesson_id':x['lesson_id'],'title':x['title'],'weak':bool(x['wrong']),
             'past_mistakes':x['wrong'],'focus':'Применение понятия на новом примере; вопрос должен отличаться от других заданий теста.'} for i,x in enumerate(selected)]


def context(db,c,exam):
    sources=[];seen=set();items=[]
    for item in exam.blueprint:
        l=db.get(Lesson,item['lesson_id'])
        ss=retrieve(db,c.id,l.topic['title'],1)
        if not ss:
            rows=db.scalars(select(Chunk).join(Document).where(Chunk.id.in_(l.topic['source_ids']),Document.role=='methodology')).all()
            ss=[{'id':x.id,'text':x.text,'locator':x.locator} for x in rows[:1]]
        for s in ss:
            if s['id'] not in seen:sources.append({**s,'text':s['text'][:1400]});seen.add(s['id'])
        items.append({**item,'source_ids':[s['id'] for s in ss]})
    return {'kind':'exam','subject':c.title,'level':c.level,'items':items,'questions':c.questions,'sources':sources,
            'instruction':'Составь итоговый тест строго по items: сохрани id и lesson_id каждой позиции. По одному содержательному quiz с 3 вариантами на позицию. Правильность объясни в expected. Используй только source_ids этой позиции. Без повторяющихся формулировок. Сравни понимание конструкций на конкретных примерах, не узнавание цитат. Не используй заголовки и номера страниц как ответы.'}


def grade(exam,answers):
    tasks=exam.content['items'];expected={t['id'] for t in tasks}
    if set(answers)!=expected:raise ValueError('Ответьте на все вопросы теста без лишних полей')
    items=[]
    for t in tasks:
        choice=answers[t['id']]
        if isinstance(choice,bool) or not 0<=choice<len(t['options']):raise ValueError('Некорректный вариант ответа')
        items.append({'id':t['id'],'lesson_id':t['lesson_id'],'correct':choice==t['correct_index'],
            'answer':choice,'correct_index':t['correct_index'],'explanation':t['expected']})
    score=round(100*sum(x['correct'] for x in items)/len(items))
    return {'score':score,'passed':score>=70,'items':items,'review_lesson_ids':list(dict.fromkeys(x['lesson_id'] for x in items if not x['correct']))}
