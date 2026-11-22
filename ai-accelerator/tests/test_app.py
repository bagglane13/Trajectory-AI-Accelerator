import io, json, uuid
from datetime import date
from docx import Document as Docx
from pypdf import PdfWriter
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.db import Session, Base, Job, Lesson, Attempt, Run, Document
from app import jobs, agents, config
from app.materials import extract, parse_questions
from app.planner import budget, allocate, InsufficientTime

def demo(client):
    r=client.post('/api/demo');assert r.status_code==201,r.text
    c=r.json();jobs.local_execute(c['job']['id'])
    detail=client.get('/api/courses/'+c['id']).json()
    assert detail['status']=='ready',client.get('/api/jobs/'+c['job']['id']).json()
    return detail

def prepared_lesson(client,c):
    lid=c['lessons'][0]['id'];r=client.post(f'/api/lessons/{lid}/generate');assert r.status_code==202,r.text
    jobs.local_execute(r.json()['id']);l=client.get('/api/lessons/'+lid).json()
    assert l['content'],client.get('/api/jobs/'+r.json()['id']).json()
    return l

def test_full_learning_flow_persists_and_does_not_leak_keys(client):
    c=demo(client);l=prepared_lesson(client,c)
    assert l['content']['mode']=='demo'
    t=l['content']['tasks'][0]
    assert 'correct_index' not in t and 'expected' not in t and 'rubric' not in t
    with Session() as db:choice=db.get(Lesson,l['id']).content['tasks'][0]['correct_index']
    r=client.post(f'/api/lessons/{l["id"]}/tasks/{t["id"]}/attempts',json={'answer':str(choice)})
    assert r.json()['result']['score']==100
    assert not r.json()['completed']
    assert client.put(f'/api/lessons/{l["id"]}/read').json()['completed']
    assert client.get('/api/courses/'+c['id']).json()['completed']==1
    before=client.get('/api/courses/'+c['id']+'/runs').json()
    assert len(before)>=6
    client.get('/api/lessons/'+l['id'])
    assert len(client.get('/api/courses/'+c['id']+'/runs').json())==len(before)
    q=client.get('/api/courses/'+c['id']+'/answers').json()
    assert q['questions'][0]['answers']
    token=client.cookies.get('session')
    with TestClient(app) as other:
        other.cookies.set('session',token)
        assert other.get('/api/courses/'+c['id']).json()['completed']==1

def test_other_user_cannot_read_course_lesson_or_source(client):
    c=demo(client);l=prepared_lesson(client,c)
    with TestClient(app) as stranger:
        r=stranger.post('/api/auth/register',json={'email':str(uuid.uuid4())+'@example.com','password':'test-password-123','name':'Другой'})
        stranger.headers['X-CSRF-Token']=r.json()['csrf']
        assert stranger.get('/api/courses/'+c['id']).status_code==404
        assert stranger.get('/api/lessons/'+l['id']).status_code==404
        assert stranger.get('/api/sources/'+l['content']['source_ids'][0]).status_code==404

def test_csrf_and_origin(client):
    r=client.post('/api/demo',headers={'X-CSRF-Token':''});assert r.status_code==403
    assert client.post('/api/demo',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/me').status_code==200

def test_calendar_actual_dates_and_end_of_month():
    s={'start':'2026-01-31','duration':'1m','days':{'1':60,'3':45}}
    b=budget(s);assert b['end']=='2026-02-27'
    assert all(date.fromisoformat(x['date']).isoweekday() in (1,3) for x in b['slots'])
    assert b['total_minutes']==420
    assert budget({'start':'2026-10-05','duration':'15d','days':{'1':60}})['end']=='2026-10-19'
    for duration in ('1m','2m','3m','6m','12m'):
        assert budget({**s,'duration':duration})['total_minutes']>0

def test_schedule_splits_and_rejects_overflow():
    t={'id':'a','title':'A','minutes':130,'prerequisites':[]}
    s={'start':'2026-10-05','duration':'15d','days':{'1':60,'3':60}}
    p=allocate([t],s)
    assert sum(x['minutes'] for x in p['sessions'])==163
    for day in {x['date'] for x in p['sessions']}:
        assert sum(x['minutes'] for x in p['sessions'] if x['date']==day)<=60
    try:allocate([{**t,'minutes':5000}],s);assert False
    except InsufficientTime:pass

def test_upload_questions_and_document_preview(client):
    c=client.post('/api/courses',json={'title':'C++','level':'beginner','schedule':{'start':'2026-10-05','duration':'1m','days':{'1':60}}}).json()
    cid=c['id'];text='Переменная — именованная область данных.\nУказатель хранит адрес объекта.\n'*15
    r=client.post(f'/api/courses/{cid}/documents',data={'role':'methodology'},files={'file':('notes.txt',text.encode(),'text/plain')})
    assert r.status_code==201,r.text
    assert client.get('/api/documents/'+r.json()['id']+'/preview').json()['text']==text
    r2=client.post(f'/api/courses/{cid}/documents',data={'role':'methodology'},files={'file':('notes.txt',text.encode(),'text/plain')})
    assert r2.json()['duplicate']
    q='1. Что такое переменная?\n2. Что такое указатель?'
    r=client.post(f'/api/courses/{cid}/documents',data={'role':'questions'},files={'file':('questions.txt',q.encode(),'text/plain')})
    assert r.status_code==201,r.text
    assert len(r.json()['questions'])==2

def test_course_accepts_more_than_eight_methodologies(client):
    c=client.post('/api/courses',json={'title':'Лабораторные работы','level':'basic','schedule':{'start':'2026-10-05','duration':'1m','days':{'1':60}}}).json()
    for number in range(1,13):
        text=(f'Лабораторная работа {number}. Теория и порядок выполнения задания {number}. '
              f'Контрольный термин laboratory_{number}. ')*12
        r=client.post(f'/api/courses/{c["id"]}/documents',data={'role':'methodology'},
            files={'file':(f'lab-{number}.txt',text.encode(),'text/plain')})
        assert r.status_code==201,r.text
    detail=client.get('/api/courses/'+c['id']).json()
    methodologies=[d for d in detail['documents'] if d['role']=='methodology']
    assert len(methodologies)==12
    assert {d['name'] for d in methodologies}=={f'lab-{n}.txt' for n in range(1,13)}
    with Session() as db:
        assert len(db.scalars(select(Document).where(Document.course_id==c['id'],Document.role=='methodology')).all())==12

def test_invalid_scan_and_docx():
    pdf=PdfWriter();pdf.add_blank_page(width=100,height=100);b=io.BytesIO();pdf.write(b)
    try:extract('scan.pdf',b.getvalue());assert False
    except ValueError as e:assert 'OCR' in str(e)
    d=Docx();d.add_paragraph('Это достаточно длинный текст для проверки извлечения документа DOCX.');out=io.BytesIO();d.save(out)
    text,chunks=extract('notes.docx',out.getvalue());assert 'DOCX' in text;assert chunks[0][0]=='Абзац 1'

def test_idempotency_and_claim_once(client):
    r=client.post('/api/demo').json();jid=r['job']['id'];cid=r['id']
    again=client.post(f'/api/courses/{cid}/generate',headers={'Idempotency-Key':'another-key'})
    assert again.json()['id']==jid
    claim=jobs.claim(jid);assert claim['claimed']
    assert not jobs.claim(jid)['claimed']
    client.post('/api/jobs/'+jid+'/cancel')
    assert jobs.generate_step(jid,claim['token'])['stop']
    assert client.get('/api/jobs/'+jid).json()['state']=='interrupted'

def test_loop_corrects_and_logs(client,monkeypatch):
    r=client.post('/api/demo').json();calls=[]
    def reviewer(candidate,job,context):
        calls.append(job.revision)
        return {'status':'revise','issues':['Уточните структуру']} if job.revision==1 else {'status':'approved','issues':[]}
    monkeypatch.setattr(agents,'review',reviewer)
    jobs.local_execute(r['job']['id'])
    j=client.get('/api/jobs/'+r['job']['id']).json()
    assert j['state']=='completed' and j['revision']==2
    assert calls==[1,2]

def test_loop_limit_and_no_publication(client,monkeypatch):
    r=client.post('/api/demo').json()
    monkeypatch.setattr(agents,'review',lambda *args:{'status':'revise','issues':['Требуется исправление']})
    jobs.local_execute(r['job']['id']);j=client.get('/api/jobs/'+r['job']['id']).json()
    assert j['state']=='needs_review' and j['revision']==3
    assert not client.get('/api/courses/'+r['id']).json()['lessons']

def test_insufficient_budget_is_not_fake_success(client):
    r=client.post('/api/demo').json();cid=r['id']
    client.post('/api/jobs/'+r['job']['id']+'/cancel')
    assert client.post(f'/api/courses/{cid}/replan',json={'start':'2026-10-05','duration':'15d','days':{'7':15}}).status_code==200
    j=client.post('/api/courses/'+cid+'/generate').json();jobs.local_execute(j['id'])
    status=client.get('/api/jobs/'+j['id']).json()
    assert status['state']=='needs_input' and 'Недостаточно' in status['error']

def test_replan_preserves_completed_lessons(client):
    c=demo(client);l=prepared_lesson(client,c)
    client.post(f'/api/lessons/{l["id"]}/tasks/quiz-1/attempts',json={'answer':'0'})
    client.put('/api/lessons/'+l['id']+'/read')
    r=client.post('/api/courses/'+c['id']+'/replan',json={'start':'2026-11-01','duration':'2m','days':{'2':60,'4':60}})
    assert r.status_code==200,r.text
    c2=client.get('/api/courses/'+c['id']).json()
    assert c2['completed']==1 and len(c2['history'])==1
    assert all(s['topic_id']!=l['id'] for s in c2['plan']['sessions'])
    assert client.get('/api/lessons/'+l['id']).json()['attempts']

def test_open_answer_demo_does_not_fake_ai_score(client):
    c=demo(client);l=prepared_lesson(client,c)
    r=client.post(f'/api/lessons/{l["id"]}/tasks/text-1/attempts',json={'answer':'Мой самостоятельный ответ'})
    assert r.json()['result']['status']=='self_check' and 'score' not in r.json()['result']

def test_local_execution_token_and_publish_contract(client):
    r=client.post('/api/demo').json();jid=r['job']['id']
    claim=jobs.claim(jid);assert claim['claimed']
    with Session() as db:
        import pytest
        with pytest.raises(ValueError):jobs.owned_job(db,jid,'bad')
        assert db.get(Job,jid).state=='running'
    assert not jobs.generate_step(jid,claim['token'])['stop']
    assert jobs.review_step(jid,claim['token'])['approved']
    assert jobs.finish_step(jid,claim['token'])['state']=='completed'
    with Session() as db:
        import pytest
        with pytest.raises(ValueError):jobs.owned_job(db,jid,claim['token'])

def test_delete_cascades_and_static_files(client):
    c=demo(client);prepared_lesson(client,c)
    r=client.delete('/api/courses/'+c['id']);assert r.status_code==200,r.text
    assert client.get('/api/courses/'+c['id']).status_code==404
    assert client.get('/').status_code==200
    assert client.get('/assets/app.js').status_code==200
    assert client.get('/assets/styles.css').status_code==200

def test_provider_adapter_native_yandex_contract(monkeypatch):
    monkeypatch.setattr(config,'YANDEX_API_KEY','fake-test-key');monkeypatch.setattr(config,'YANDEX_MODEL','gpt://test/model')
    def post(url,headers,json,timeout):
        assert headers['Authorization']=='Api-Key fake-test-key'
        assert json['modelUri']=='gpt://test/model'
        assert json['messages'][0]['role']=='system'
        class Response:
            status_code=200
            def json(self):return {'result':{'alternatives':[{'message':{'text':'{"status":"approved","issues":[]}'}}]}}
        return Response()
    monkeypatch.setattr(agents.httpx,'post',post)
    assert agents.llm('test',{},agents.Review)['status']=='approved'
