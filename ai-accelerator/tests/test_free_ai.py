import importlib.util
import json
from pathlib import Path
import pytest
import httpx
from app import config, providers, jobs, demo_content
from app.schemas import Review
from test_app import prepared_lesson

spec=importlib.util.spec_from_file_location('connect_ai',Path(__file__).resolve().parents[1]/'scripts'/'connect_ai.py')
wizard=importlib.util.module_from_spec(spec);spec.loader.exec_module(wizard)


class Response:
    def __init__(self,data=None,status=200):self.data=data;self.status_code=status;self.headers={}
    def json(self):return self.data


@pytest.mark.parametrize('mode',['gemini','ollama'])
def test_adapter_native_request_and_json(mode,monkeypatch):
    monkeypatch.setattr(config,'AI_MODE',mode);monkeypatch.setattr(config,'GEMINI_API_KEY','test-secret')
    def post(url,headers,json,timeout,**kwargs):
        if mode=='gemini':
            assert url.startswith('https://generativelanguage.googleapis.com/v1beta/models/')
            assert 'test-secret' not in url and headers=={'x-goog-api-key':'test-secret'}
            assert json['generationConfig']['responseMimeType']=='application/json'
            return Response({'candidates':[{'finishReason':'STOP','content':{'parts':[{'thought':True,'text':'ignore'},{'text':'{"status":"approved","issues":[]}'}]}}]})
        assert url=='http://127.0.0.1:11434/api/chat' and headers=={}
        assert json['format']==Review.model_json_schema() and not json['stream'] and not json['think']
        return Response({'message':{'content':'{"status":"approved","issues":[]}'}})
    monkeypatch.setattr(providers.httpx,'post',post)
    assert providers.call('system',{},Review)=={'status':'approved','issues':[]}


@pytest.mark.parametrize('mode',['gemini','ollama'])
def test_full_agent_cycle_with_provider_contracts(client,mode,monkeypatch):
    monkeypatch.setattr(config,'AI_MODE',mode);monkeypatch.setattr(config,'GEMINI_API_KEY','only-a-test-secret')
    calls=[]
    def post(url,headers,json,timeout,**kwargs):
        system=json['systemInstruction']['parts'][0]['text'] if mode=='gemini' else json['messages'][0]['content']
        prompt=json['contents'][0]['parts'][0]['text'] if mode=='gemini' else json['messages'][1]['content']
        data=__import__('json').loads(prompt)['task'];calls.append(system)
        if 'ReviewerAgent' in system:result={'status':'approved','issues':[]}
        elif data['kind']=='plan':
            result={'topics':[{'id':f't{i}','title':q['text'],'objective':'Изучить понятия и разобрать примеры.','minutes':45,'prerequisites':[],
                'question_ids':[q['id']],'source_ids':[data['sources'][0]['id']]} for i,q in enumerate(data['questions'])]}
        elif data['kind']=='lesson':
            result=demo_content.lesson(data)
            if mode=='ollama':
                quiz,practice=result.pop('tasks');result.update(quiz=quiz,practice=practice)
        else:result={'score':85,'feedback':'Верно объяснено назначение переменной; уточните пример.','improvements':['Добавьте пример преобразования типа.']}
        raw=__import__('json').dumps(result,ensure_ascii=False)
        return Response({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':raw}]}}]} if mode=='gemini' else {'message':{'content':raw}})
    monkeypatch.setattr(providers.httpx,'post',post)
    created=client.post('/api/demo').json();jobs.local_execute(created['job']['id'])
    c=client.get('/api/courses/'+created['id']).json();assert c['status']=='ready'
    l=prepared_lesson(client,c);assert l['content']['mode']==mode
    a=client.post('/api/lessons/'+l['id']+'/tasks/text-1/attempts',json={'answer':'Имя переменной связано с объектом Python.'}).json()
    jobs.local_execute(a['job']['id'])
    attempt=client.get('/api/lessons/'+l['id']).json()['attempts'][0]
    assert attempt['result']['score']==85 and attempt['result']['mode']==mode
    assert len(calls)==6 and sum('ReviewerAgent' in c for c in calls)==3
    public=client.get('/api/config').json()
    assert public['provider_configured'] and public['ai_mode']==mode
    assert 'only-a-test-secret' not in __import__('json').dumps(public)
    runs=client.get('/api/courses/'+c['id']+'/runs').json()
    assert all(r['payload']['model']==providers.model_name() for r in runs)


@pytest.mark.parametrize('status',[401,403,404,429,400])
def test_provider_errors_safe_and_bounded(status,monkeypatch):
    monkeypatch.setattr(config,'AI_MODE','gemini');monkeypatch.setattr(config,'GEMINI_API_KEY','private-secret')
    calls=[]
    def post(*args,**kwargs):calls.append(1);return Response({'error':'private-secret'},status)
    monkeypatch.setattr(providers.httpx,'post',post)
    with pytest.raises(ValueError) as error:providers.call('system',{},Review)
    assert 'private-secret' not in str(error.value) and len(calls)==1


def test_ollama_no_cloud_and_no_infinite_retry(monkeypatch):
    monkeypatch.setattr(config,'AI_MODE','ollama');monkeypatch.setattr(config,'OLLAMA_MODEL','qwen3:cloud')
    with pytest.raises(ValueError,match='локальную'):providers.call('system',{},Review)
    monkeypatch.setattr(config,'OLLAMA_MODEL','qwen3:8b');calls=[]
    def post(*args,**kwargs):calls.append(1);raise httpx.ReadTimeout('timeout')
    monkeypatch.setattr(providers.httpx,'post',post)
    with pytest.raises(ValueError,match='Нет ответа'):providers.call('system',{},Review)
    assert len(calls)==1


def test_provider_rejects_truncated_and_invalid_outputs(monkeypatch):
    monkeypatch.setattr(config,'AI_MODE','gemini');monkeypatch.setattr(config,'GEMINI_API_KEY','test-key')
    monkeypatch.setattr(providers.httpx,'post',lambda *a,**k:Response({'candidates':[{'finishReason':'MAX_TOKENS'}]}))
    with pytest.raises(ValueError,match='прервана'):providers.call('system',{},Review)
    with pytest.raises(ValueError):providers.parse_object('not json')
    with pytest.raises(ValueError):providers.parse_object('[]')


def test_wizard_preserves_settings_and_backs_up(tmp_path):
    env=tmp_path/'.env';original='AI_MODE=demo\nAI_MODE=yandex\nDATABASE_URL=sqlite:///my-data.db\nSECURE_COOKIE=false\nGEMINI_API_KEY=old-secret\n'
    env.write_text(original)
    wizard.save_settings({'AI_MODE':'gemini','GEMINI_API_KEY':'new-secret'},root=tmp_path)
    written=env.read_text()
    assert written.count('AI_MODE=')==1 and 'AI_MODE="gemini"' in written
    assert 'SECURE_COOKIE=false' in written and 'DATABASE_URL=sqlite:///my-data.db' in written
    assert list(tmp_path.glob('.env.backup-*'))[0].read_text()==original
    assert not (tmp_path/'.env.connecting').exists()


def test_wizard_failed_connection_never_changes_env(tmp_path,monkeypatch):
    monkeypatch.setattr(wizard,'ROOT',tmp_path)
    env=tmp_path/'.env';env.write_text('AI_MODE=demo\n')
    monkeypatch.setattr(wizard.webbrowser,'open',lambda _:True)
    monkeypatch.setattr(wizard,'getpass',lambda _: 'a'*30)
    monkeypatch.setattr('builtins.input',lambda _: '')
    def fail(*a,**k):raise ValueError('No connection')
    monkeypatch.setattr(wizard,'request_json',fail)
    with pytest.raises(ValueError):wizard.configure_gemini()
    assert env.read_text()=='AI_MODE=demo\n'


@pytest.fixture
def updater():
    path=Path(__file__).resolve().parents[2]/'install_update.py'
    if not path.is_file():pytest.skip('Archive installer is outside the application directory')
    spec=importlib.util.spec_from_file_location('install_update',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_update_finds_nested_project_preserves_secrets_and_data(tmp_path,updater):
    source=tmp_path/'new';target=tmp_path/'!учеба'/'АОКГ ПРОЕКТ'/'ai-accelerator'
    for root in (source,target):
        (root/'app').mkdir(parents=True);(root/'app'/'main.py').write_text('old')
        (root/'start.bat').write_text('start')
    (source/'app'/'main.py').write_text('new')
    (source/'.env').write_text('must not copy')
    (target/'.env').write_text('my key')
    (source/'data').mkdir();(source/'data'/'db').write_text('foreign data')
    (target/'data').mkdir();(target/'data'/'db').write_text('my progress')
    assert updater.find_project(target.parent)==target
    backup=updater.install(source,target)
    assert (target/'app'/'main.py').read_text()=='new'
    assert (backup/'app'/'main.py').read_text()=='old'
    assert (target/'.env').read_text()=='my key' and (target/'data'/'db').read_text()=='my progress'


def test_update_rolls_back_failed_copy(tmp_path,updater,monkeypatch):
    source=tmp_path/'new';target=tmp_path/'target';source.mkdir();target.mkdir()
    for name in ('a.txt','b.txt'):
        (source/name).write_text('new');(target/name).write_text('old')
    copy=updater.shutil.copy2
    def fail(src,dest):
        if Path(src)==source/'b.txt':raise OSError('simulated write failure')
        return copy(src,dest)
    monkeypatch.setattr(updater.shutil,'copy2',fail)
    with pytest.raises(OSError):updater.install(source,target)
    assert all((target/name).read_text()=='old' for name in ('a.txt','b.txt'))


def test_local_reference_aliases_round_trip_without_changing_theory():
    original={'sources':[{'id':'a'*32,'text':'Структура HTML и назначение body.'}], 'question_ids':['b'*32]}
    short,reverse=providers.short_ids(original)
    assert short['sources'][0]['id']=='ref_1'
    assert short['sources'][0]['text']==original['sources'][0]['text']
    assert providers.restore_ids(short,reverse)==original


def test_reviewer_checks_assessment_not_student_failure(monkeypatch):
    from types import SimpleNamespace
    from app import agents
    monkeypatch.setattr(config,'AI_MODE','ollama')
    def llm(system,data,schema):
        assert 'НЕ правильность ответа ученика' in system
        assert data['assessment']['score']==0
        assert data['student_answer']=='Не знаю'
        assert 'context' not in data
        return {'status':'approved','issues':[]}
    monkeypatch.setattr(agents,'llm',llm)
    result=agents.review({'score':0,'feedback':'Ответ не дан.','improvements':[]},SimpleNamespace(kind='assessment'),
                        {'task':{'prompt':'Напишите HTML'},'student_answer':'Не знаю','sources':[]})
    assert result['status']=='approved'
