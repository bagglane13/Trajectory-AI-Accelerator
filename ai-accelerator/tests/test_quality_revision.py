import io
import os
from pathlib import Path
import pytest
from docx import Document as Docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from app.materials import extract, extract_questions, clean_pdf_text, retrieve
from app.demo_content import validate_practice, exercise
from app.db import Session, Course, Lesson, Attempt
from app import jobs
from test_app import demo, prepared_lesson


def test_word_automatic_numbering_ignores_document_title():
    doc=Docx();doc.add_paragraph('Вопросы для самоконтроля по дисциплине «WEB-программирование».')
    doc.add_paragraph('Язык разметки гипертекста – HTML 4.01.')
    for text in ['Структура HTML-документа. Дескрипторы и их параметры.', 'Переносы и пробелы в документе.']:
        p=doc.add_paragraph(text);num=OxmlElement('w:numPr');nid=OxmlElement('w:numId');nid.set(qn('w:val'),'1');num.append(nid);p._p.get_or_add_pPr().append(num)
    raw=io.BytesIO();doc.save(raw);text,_=extract('questions.docx',raw.getvalue())
    qs=extract_questions('questions.docx',raw.getvalue(),text)
    assert len(qs)==2 and qs[0].startswith('Структура HTML')


def test_pdf_removes_leading_page_number_but_keeps_numeric_example():
    assert clean_pdf_text(' 9 \nHTML документ\nПример вывода:\n5\nКонец')=='HTML документ\nПример вывода:\n5\nКонец'


def test_old_meaningless_quiz_rejected():
    with pytest.raises(ValueError):validate_practice({'tasks':[{'prompt':'Какое утверждение взято из материала этого урока?','type':'quiz','options':['5','Нет']} ]})
    with pytest.raises(ValueError):validate_practice({'tasks':[{'prompt':'Что означает этот тег?','type':'quiz','options':['5','Элемент']} ]})
    assert exercise('Переменные и типы данных','JavaScript') is None


def test_preview_level_change_and_ready_progress(client):
    c=demo(client);l=prepared_lesson(client,c)
    tid=l['content']['tasks'][0]['id']
    client.post(f'/api/lessons/{l["id"]}/tasks/{tid}/attempts',json={'answer':'0'})
    client.put('/api/lessons/'+l['id']+'/read')
    attempts_before=client.get('/api/lessons/'+l['id']).json()['attempts']
    body={**c['schedule'],'level':'revision'}
    r=client.post('/api/courses/'+c['id']+'/replan-preview',json=body)
    assert r.status_code==200 and r.json()['required_minutes']==75
    assert client.get('/api/courses/'+c['id']).json()['level']=='beginner'
    r=client.post('/api/courses/'+c['id']+'/replan',json=body);assert r.status_code==200,r.text
    after=client.get('/api/courses/'+c['id']).json()
    assert after['level']=='revision' and after['completed']==1
    assert after['lessons'][0]['topic']['minutes']==45
    assert after['lessons'][1]['topic']['minutes']==20
    assert client.get('/api/lessons/'+l['id']).json()['attempts']==attempts_before
    client.post('/api/courses/'+c['id']+'/replan',json={**body,'level':'beginner'})
    assert client.get('/api/courses/'+c['id']).json()['lessons'][1]['topic']['minutes']==45


def test_replan_insufficient_time_is_atomic(client):
    c=demo(client)
    r=client.post('/api/courses/'+c['id']+'/replan',json={'start':'2026-10-05','duration':'15d','days':{'2':15},'level':'basic'})
    assert r.status_code==422
    after=client.get('/api/courses/'+c['id']).json()
    assert after['level']==c['level'] and after['schedule']==c['schedule'] and after['plan']==c['plan']


def test_draft_level_can_change_after_time_failure(client):
    c=client.post('/api/courses',json={'title':'Python','schedule':{'start':'2026-10-05','duration':'15d','days':{'1':15}}}).json()
    client.put('/api/courses/'+c['id']+'/questions',json={'questions':['Переменные Python']})
    first=client.post('/api/courses/'+c['id']+'/replan-preview',json=c['schedule']).json()
    assert not first['fits']
    body={**c['schedule'],'level':'revision'}
    assert client.post('/api/courses/'+c['id']+'/replan-preview',json=body).json()['fits']
    assert client.post('/api/courses/'+c['id']+'/replan',json=body).json()['level']=='revision'
    assert client.post('/api/courses/'+c['id']+'/replan',json={**body,'level':'invalid'}).status_code==422


def test_generic_demo_self_check_completes_without_fake_score(client):
    c=demo(client);lid=c['lessons'][1]['id']
    j=client.post('/api/lessons/'+lid+'/generate').json();jobs.local_execute(j['id'])
    l=client.get('/api/lessons/'+lid).json();task=l['content']['tasks'][0]
    assert task['type']=='text' and task['required']
    a=client.post(f'/api/lessons/{lid}/tasks/{task["id"]}/attempts',json={'answer':'Условие if выполняет блок только при истинном выражении. Например, if age >= 18: print("Вход разрешен").'}).json()
    client.put('/api/lessons/'+lid+'/read')
    assert not client.get('/api/lessons/'+lid).json()['completed']
    result=client.post('/api/attempts/'+a['id']+'/self-check').json()
    assert result['completed'] and result['result']['status']=='self_checked' and 'score' not in result['result']


def test_repair_keeps_original_data_and_copies_files(client):
    c=demo(client);l=prepared_lesson(client,c)
    r=client.post('/api/courses/'+c['id']+'/repair-copy');assert r.status_code==201,r.text
    copied=client.get('/api/courses/'+r.json()['id']).json()
    assert copied['status']=='draft' and not copied['lessons']
    assert copied['documents'][0]['id']!=c['documents'][0]['id']
    assert copied['questions'][0]['text']==c['questions'][0]['text']
    assert client.get('/api/lessons/'+l['id']).json()['content']==l['content']
    client.delete('/api/courses/'+copied['id'])
    again=client.post('/api/courses/'+c['id']+'/repair-copy');assert again.status_code==201,again.text


@pytest.mark.skipif(not os.environ.get('TRAJECTORY_USER_FIXTURES'),reason='Private user attachments are not distributed')
def test_actual_web_documents(client):
    root=Path(os.environ['TRAJECTORY_USER_FIXTURES'])
    c=client.post('/api/courses',json={'title':'WEB-программирование','schedule':{'start':'2026-10-05','duration':'3m','days':{'1':120,'3':120,'5':120}}}).json();cid=c['id']
    for name,role in [('02-web.pdf','methodology'),('01-1-.docx','questions')]:
        r=client.post('/api/courses/'+cid+'/documents',data={'role':role},files={'file':(name,(root/name).read_bytes())});assert r.status_code==201,r.text
    c=client.get('/api/courses/'+cid).json()
    assert c['questions'][0]['text']=='Структура HTML-документа. Дескрипторы и их параметры.'
    assert not any(q['text'].startswith('Вопросы для') for q in c['questions'])
    with Session() as db:
        sources=retrieve(db,cid,c['questions'][0]['text'])
        assert sources[0]['locator']=='Страница 9',[(s['locator'],s['text'][:90]) for s in sources]
    j=client.post('/api/courses/'+cid+'/generate').json();jobs.local_execute(j['id'])
    c=client.get('/api/courses/'+cid).json();assert c['status']=='ready',client.get('/api/jobs/'+j['id']).json()
    l=prepared_lesson(client,c)
    assert '<h1>' in l['content']['tasks'][0]['prompt']
    assert all(o.strip()!='5' for o in l['content']['tasks'][0]['options'])
    assert 'head, body' in l['content']['tasks'][1]['prompt']
    print('REAL WEB: questions=',len(c['questions']),'first source=',sources[0]['locator'])
