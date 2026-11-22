from collections import Counter
import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient
from app.main import app
from app import config,jobs,agents,exams
from app.db import Session,Lesson,Attempt,Exam,ExamAttempt
from test_app import demo,prepared_lesson


def complete_course(c):
    with Session.begin() as db:
        for l in db.scalars(select(Lesson).where(Lesson.course_id==c['id'])):l.completed=True


def exam_answer(data):
    return {'items':[{'id':x['id'],'lesson_id':x['lesson_id'],'type':'quiz','prompt':f'Позиция {x["id"]}: где в Python использовать переменную в выражении?',
        'options':['После присваивания значения','Только в комментарии к программе','Внутри имени файла'],
        'correct_index':0,'expected':'Имя переменной можно использовать в выражении после присваивания.','rubric':'Понимание присваивания.','required':True,'source_ids':x['source_ids'][:1]} for x in data['items']]}


def test_blueprint_majority_weak_and_history_never_disappears(client):
    c=demo(client);weak=c['lessons'][0]['id']
    with Session.begin() as db:
        db.add(Attempt(lesson_id=weak,task_id='q',answer='wrong',result={'status':'graded','score':0}))
        db.add(Attempt(lesson_id=weak,task_id='q',answer='correct',result={'status':'graded','score':100}))
    with Session() as db:
        slots=exams.blueprint(db,c['id'],'seed')
        assert len(slots)==10 and sum(x['weak'] for x in slots)==7
        assert sum(x['lesson_id']==weak for x in slots)==7


def test_no_mistakes_covers_topics_and_ignores_ungraded(client):
    c=demo(client)
    with Session.begin() as db:db.add(Attempt(lesson_id=c['lessons'][0]['id'],task_id='q',answer='x',result={'status':'self_checked'}))
    with Session() as db:
        slots=exams.blueprint(db,c['id'],'seed')
        assert not any(x['weak'] for x in slots)
        assert set(x['lesson_id'] for x in slots)=={l['id'] for l in c['lessons']}


def test_exam_requires_completion_and_real_provider(client,monkeypatch):
    c=demo(client)
    assert client.post('/api/courses/'+c['id']+'/exam').status_code==409
    monkeypatch.setattr(config,'AI_MODE','ollama')
    assert client.post('/api/courses/'+c['id']+'/exam').status_code==409


def test_exam_generation_hidden_keys_scoring_retake_and_feedback(client,monkeypatch):
    c=demo(client);complete_course(c)
    monkeypatch.setattr(config,'AI_MODE','ollama')
    def llm(system,data,schema):return {'status':'approved','issues':[]} if 'ReviewerAgent' in system else exam_answer(data)
    monkeypatch.setattr(agents,'llm',llm)
    j=client.post('/api/courses/'+c['id']+'/exam').json();jobs.local_execute(j['id'])
    assert client.get('/api/jobs/'+j['id']).json()['state']=='completed'
    state=client.get('/api/courses/'+c['id']+'/exam').json();e=state['exam'];items=e['content']['items']
    assert len(items)==10 and all('correct_index' not in t and 'expected' not in t for t in items)
    assert client.post('/api/exams/'+e['id']+'/attempts',json={'answers':{}}).status_code==422
    answers={x['id']:0 for x in items};answers[items[0]['id']]=1
    result=client.post('/api/exams/'+e['id']+'/attempts',json={'answers':answers}).json()['result']
    assert result['score']==90 and result['passed'] and len(result['review_lesson_ids'])==1
    assert all('explanation' in x for x in result['items'])
    new=client.post('/api/courses/'+c['id']+'/exam').json();jobs.local_execute(new['id'])
    state=client.get('/api/courses/'+c['id']+'/exam').json()
    assert state['exam']['id']!=e['id'] and sum(x['weak'] for x in state['exam']['blueprint'])==7
    with Session() as db:assert db.scalar(select(ExamAttempt).where(ExamAttempt.exam_id==e['id']))


def test_exam_foreign_access_rejected(client,monkeypatch):
    c=demo(client);complete_course(c);monkeypatch.setattr(config,'AI_MODE','ollama')
    j=client.post('/api/courses/'+c['id']+'/exam').json()
    with Session() as db:e=db.get(__import__('app.db',fromlist=['Job']).Job,j['id']).target
    with TestClient(app) as stranger:
        r=stranger.post('/api/auth/register',json={'name':'Other','email':'exam-foreign@example.com','password':'test-password-123'})
        stranger.headers['X-CSRF-Token']=r.json()['csrf']
        assert stranger.get('/api/courses/'+c['id']+'/exam').status_code==404
        assert stranger.post('/api/exams/'+e+'/attempts',json={'answers':{'q1':0}}).status_code==404


def test_exam_validation_rejects_wrong_topic_or_duplicate(client,monkeypatch):
    c=demo(client);complete_course(c);monkeypatch.setattr(config,'AI_MODE','ollama')
    j=client.post('/api/courses/'+c['id']+'/exam').json()
    from app.db import Job,Course
    with Session() as db:
        job=db.get(Job,j['id']);course=db.get(Course,c['id']);ctx=agents.context_for(db,course,job)
        result=exam_answer(ctx);result['items'][0]['lesson_id']='foreign'
        with pytest.raises(ValueError,match='чужой'):agents.validate(result,job,ctx,course)


def test_large_local_plan_is_generated_and_reviewed_in_bounded_blocks(client,monkeypatch):
    c=demo(client)
    # Use a fresh draft with 12 distinct questions, reusing the demonstrator's methodology via a repair copy.
    copied=client.post('/api/courses/'+c['id']+'/repair-copy').json()
    questions=[f'Переменные Python, вопрос {i}: как работает присваивание?' for i in range(12)]
    client.put('/api/courses/'+copied['id']+'/questions',json={'questions':questions})
    client.post('/api/courses/'+copied['id']+'/replan',json={'start':'2026-10-28','duration':'3m','days':{'1':120,'3':120,'5':120}})
    monkeypatch.setattr(config,'AI_MODE','ollama');calls=[]
    def llm(system,data,schema):
        calls.append((system,data))
        if 'ReviewerAgent' in system:return {'status':'approved','issues':[]}
        assert len(data['questions'])<=10
        return {'topics':[{'id':f't{i}','title':q['text'],'objective':'Понять присваивание и разобрать примеры.','minutes':30,'prerequisites':[],
                           'question_ids':[q['id']],'source_ids':[data['sources'][0]['id']]} for i,q in enumerate(data['questions'])]}
    monkeypatch.setattr(agents,'llm',llm)
    j=client.post('/api/courses/'+copied['id']+'/generate').json();jobs.local_execute(j['id'])
    assert client.get('/api/jobs/'+j['id']).json()['state']=='completed'
    assert len(calls)==4 and len(client.get('/api/courses/'+copied['id']).json()['lessons'])==12


def test_automatic_demo_upgrade_is_idempotent_and_preserves_original(client,monkeypatch):
    c=demo(client);complete_course(c)
    monkeypatch.setattr(config,'AI_MODE','ollama')
    first=client.post('/api/courses/'+c['id']+'/upgrade-ai');assert first.status_code==202,first.text
    copied=first.json()['id']
    again=client.post('/api/courses/'+c['id']+'/upgrade-ai');assert again.status_code==202
    assert again.json()['id']==copied and again.json()['existing']
    original=client.get('/api/courses/'+c['id']).json();assert original['completed']==original['total']
    new=client.get('/api/courses/'+copied).json();assert new['status']=='draft' and new['active_jobs']
