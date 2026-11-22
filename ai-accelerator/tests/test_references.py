"""Regression: local generation must cite only evidence sent in this request."""
import json
from sqlalchemy import select
import pytest
from app import agents, config, jobs, providers
from app.db import Chunk, Course, Document, Job, Session, uid
from app.schemas import LocalLessonOutput, PlanOutput


@pytest.mark.parametrize('mode',['ollama','gemini'])
def test_plan_context_does_not_advertise_unselected_chunk_ids(client,monkeypatch,mode):
    monkeypatch.setattr(config,'AI_MODE',mode)
    created=client.post('/api/demo').json()
    unrelated=uid()
    with Session.begin() as db:
        document=db.scalar(select(Document).where(Document.course_id==created['id'],Document.role=='methodology'))
        db.add(Chunk(id=unrelated,document_id=document.id,course_id=created['id'],
                     locator='Приложение',text='Тираж типографии, издательские сведения и выходные данные.'))
    with Session() as db:
        context=agents.context_for(db,db.get(Course,created['id']),db.get(Job,created['job']['id']))
    assert unrelated not in json.dumps(context)
    assert all('id' not in item for item in context['overview'])
    if mode=='ollama':assert not context['overview']


@pytest.mark.parametrize('schema',[PlanOutput,LocalLessonOutput])
def test_native_decoder_restricts_refs_and_restores_real_ids(monkeypatch,schema):
    monkeypatch.setattr(config,'AI_MODE','ollama')
    source,question,old_source='a'*32,'b'*32,'c'*32
    context={'kind':'plan' if schema is PlanOutput else 'lesson',
             'topic':{'source_ids':[old_source]},
             'questions':[{'id':question,'text':'Для чего нужен HTML?'}],
             'sources':[{'id':source,'text':'HTML задаёт структуру страницы.'}]}
    def post(url,headers,json:dict,timeout,**kwargs):
        task=__import__('json').loads(json['messages'][1]['content'])['task']
        allowed_source=task['sources'][0]['id'];allowed_question=task['questions'][0]['id']
        forbidden=task['topic']['source_ids'][0]
        properties=json['format']['$defs']['Topic' if schema is PlanOutput else 'Answer']['properties']
        assert properties['source_ids']['items']['enum']==[allowed_source]
        question_field=properties['question_ids']['items'] if schema is PlanOutput else properties['question_id']
        assert question_field['enum']==[allowed_question]
        assert forbidden not in properties['source_ids']['items']['enum']
        assert allowed_question!=allowed_source
        if schema is LocalLessonOutput:
            assert json['format']['properties']['source_ids']['items']['enum']==[allowed_source]
        class Response:
            status_code=200
            def json(self):return {'message':{'content':__import__('json').dumps(
                {'source_ids':[allowed_source],'answers':[{'question_id':allowed_question,'source_ids':[allowed_source]}]})}}
        return Response()
    monkeypatch.setattr(providers.httpx,'post',post)
    output=providers.call('system',context,schema)
    assert output['source_ids']==[source]
    assert output['answers'][0]['question_id']==question
    assert PlanOutput.model_json_schema()['$defs']['Topic']['properties']['source_ids']['items']=={'type':'string'}


def test_invalid_refs_fail_safely_then_retry_uses_ai_reviewer(client,monkeypatch):
    monkeypatch.setattr(config,'AI_MODE','ollama')
    invalid=True;review_calls=[]
    def post(url,headers,json:dict,timeout,**kwargs):
        task=__import__('json').loads(json['messages'][1]['content'])['task']
        if 'ReviewerAgent' in json['messages'][0]['content']:
            review_calls.append(1);result={'status':'approved','issues':[]}
        else:
            result={'topics':[{'id':f't{i}','title':q['text'],'objective':'Изучить определение и примеры применения.',
                'minutes':30,'prerequisites':[],'question_ids':[q['id']],
                'source_ids':['invented-fragment' if invalid else task['sources'][0]['id']]}
                for i,q in enumerate(task['questions'])]}
        class Response:
            status_code=200
            def json(self):return {'message':{'content':__import__('json').dumps(result)}}
        return Response()
    monkeypatch.setattr(providers.httpx,'post',post)
    created=client.post('/api/demo').json();jid=created['job']['id'];cid=created['id']
    before=client.get('/api/courses/'+cid).json()
    jobs.local_execute(jid)
    status=client.get('/api/jobs/'+jid).json()
    assert status['state']=='needs_review' and status['revision']==3
    assert 'вне переданного контекста' in status['error']
    assert not review_calls
    assert not client.get('/api/courses/'+cid).json()['lessons']
    runs=client.get('/api/courses/'+cid+'/runs').json()
    assert all(r['payload']['check_type']=='programmatic' for r in runs if r['role']=='ReviewerAgent')
    invalid=False
    retry=client.post('/api/jobs/'+jid+'/retry')
    assert retry.status_code==202
    jobs.local_execute(retry.json()['id'])
    course=client.get('/api/courses/'+cid).json()
    assert course['status']=='ready' and course['lessons']
    assert course['questions']==before['questions'] and course['schedule']==before['schedule']
    assert review_calls==[1]
    runs=client.get('/api/courses/'+cid+'/runs').json()
    assert any(r['role']=='ReviewerAgent' and r['payload']['check_type']=='ai' for r in runs)
