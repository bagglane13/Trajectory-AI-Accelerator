import importlib.util
from pathlib import Path
import hashlib
import zipfile
import pytest

@pytest.fixture
def launcher():
    path=Path(__file__).resolve().parents[2]/'run_local.py'
    if not path.exists():pytest.skip('Launcher outside app folder')
    spec=importlib.util.spec_from_file_location('run_local',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_zip_extraction_rejects_escape(tmp_path,launcher):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('../outside.txt','bad')
    with pytest.raises(RuntimeError):launcher.safe_extract(archive,tmp_path/'runtime')
    assert not (tmp_path/'outside.txt').exists()


def test_small_ram_has_clear_error_not_silent_demo(launcher):
    with pytest.raises(RuntimeError,match='ОЗУ'):launcher.select_model(4)
    with pytest.raises(RuntimeError,match='12 ГБ'):launcher.select_model(8)
    assert launcher.select_model(12)=='qwen3:8b'


def test_download_checks_hash_before_replacing(tmp_path,launcher,monkeypatch):
    import io
    class Response(io.BytesIO):headers={'Content-Length':'5'}
    monkeypatch.setattr(launcher,'urlopen',lambda *a,**k:Response(b'hello'))
    dest=tmp_path/'file.zip'
    with pytest.raises(RuntimeError):launcher.download('https://official.example',dest,'wrong')
    assert not dest.exists()
    launcher.download('https://official.example',dest,hashlib.sha256(b'hello').hexdigest())
    assert dest.read_bytes()==b'hello'


def test_launch_uses_only_sources_in_unpacked_unicode_folder(tmp_path,launcher):
    bundle=tmp_path/'!учеба'/'мой проект'
    app=bundle/'ai-accelerator'
    for name in ('app/main.py','frontend/index.html','scripts/bootstrap.py','requirements.txt'):
        path=app/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('local edited source')
    assert launcher.existing_project(bundle)==app
    assert (app/'app/main.py').read_text()=='local edited source'
    with pytest.raises(RuntimeError,match='целиком'):launcher.existing_project(tmp_path/'missing')


def test_private_model_server_does_not_reuse_other_folders_engine(tmp_path,launcher,monkeypatch):
    import json
    monkeypatch.setattr(launcher,'BUNDLE',tmp_path/'this project')
    monkeypatch.setattr(launcher,'STATE',tmp_path/'state')
    monkeypatch.setattr(launcher,'RUNTIME',tmp_path/'state/runtime')
    root=launcher.RUNTIME/('ollama-'+launcher.OLLAMA_RELEASE);root.mkdir(parents=True)
    (root/'ollama.exe').write_text('fake');(root/'.verified').write_text('fake')
    (launcher.STATE/'ollama.json').write_text(json.dumps({'url':'http://127.0.0.1:11435','bundle':'another project'}))
    monkeypatch.setattr(launcher,'free_port',lambda start,stop:11436)
    calls=[]
    class Process:
        pid=123
        def poll(self):return None
    def popen(command,**kwargs):calls.append(kwargs);return Process()
    monkeypatch.setattr(launcher.subprocess,'Popen',popen)
    urls=[]
    monkeypatch.setattr(launcher,'json_request',lambda url:urls.append(url) or {'models':[]})
    logs=tmp_path/'logs';logs.mkdir()
    launcher.prepare_ollama(logs)
    assert urls==['http://127.0.0.1:11436/api/tags']
    assert calls[0]['env']['OLLAMA_MODELS']==str(launcher.STATE/'models')
    assert calls[0]['env']['OLLAMA_HOST']=='127.0.0.1:11436'
    assert json.loads((launcher.STATE/'ollama.json').read_text())['bundle']==str(launcher.BUNDLE.resolve())


def test_release_excludes_private_files_and_keeps_complete_sources(tmp_path):
    path=Path(__file__).resolve().parents[2]/'scripts/build_release.py'
    spec=importlib.util.spec_from_file_location('build_release',path)
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    root=tmp_path/'root';root.mkdir()
    required=('START.bat','START.ps1','run_local.py','Trajectory_AI_Instruction_RU.docx','README.md',
              'ai-accelerator/app/main.py','ai-accelerator/frontend/index.html','ai-accelerator/.env.example')
    private=('.runtime/models/secret-model','ai-accelerator/data/accelerator.db','ai-accelerator/.env',
             'ai-accelerator/.env.backup-123','ai-accelerator/.venv/python','ai-accelerator/backup-code-123/private.txt')
    for name in required+private:
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(name)
    archive=builder.build(root,tmp_path/'project.zip')
    with zipfile.ZipFile(archive) as z:
        names=set(z.namelist())
        assert all('Trajectory_AI_Accelerator/'+n in names for n in required)
        assert all('Trajectory_AI_Accelerator/'+n not in names for n in private)


def test_model_probe_recovers_from_bad_json_and_records_response(tmp_path,launcher,monkeypatch):
    import json
    replies=iter([{'message':{'content':'{\n"ok": true\n "extra": false}'}},
                  {'message':{'content':'{"ok":true}'},'done':True,'done_reason':'stop'}])
    calls=[]
    def request(url,body,timeout):
        calls.append(body)
        assert url.endswith('/api/chat') and not body['stream'] and not body['think']
        assert body['format']['additionalProperties'] is False
        assert body['format']['properties']['ok']['enum']==[True]
        assert body['options']['temperature']==0 and body['options']['num_predict']>=128
        return next(replies)
    monkeypatch.setattr(launcher,'json_request',request)
    launcher.check_model('qwen3:8b',tmp_path)
    report=json.loads((tmp_path/'startup-ai.json').read_text())
    assert len(calls)==2 and report['status']=='passed'
    assert report['attempts'][0]['invalid_json'].startswith('{')
    assert 'error' in report['attempts'][0] and report['attempts'][1]['success']


@pytest.mark.parametrize('response',[
    {'message':{'content':'{"ok":'}},
    {'message':{'content':'{"ok":false}'}},
    {'message':{'content':'{"ok":1}'}},
    {'message':{'content':'{"ok":true,"other":1}'}},
    {'message':{'content':'{"ok":true}'},'done_reason':'length'},
    {'message':{'content':'{"ok":true}'},'done':False},
    {'message':{}},
])
def test_model_probe_never_accepts_bad_or_incomplete_response(tmp_path,launcher,monkeypatch,response):
    import json
    calls=[]
    def request(*args,**kwargs):calls.append(1);return response
    monkeypatch.setattr(launcher,'json_request',request)
    with pytest.raises(RuntimeError,match='startup-ai.json'):launcher.check_model('qwen3:8b',tmp_path)
    report=json.loads((tmp_path/'startup-ai.json').read_text())
    assert len(calls)==2 and report['status']=='failed'
    assert all('error' in attempt and not attempt.get('success') for attempt in report['attempts'])


def test_model_probe_logs_malformed_http_json_and_network_error(tmp_path,launcher,monkeypatch):
    import json
    failures=iter([json.JSONDecodeError('Expecting comma','bad API json',2),OSError('connection closed')])
    def request(*args,**kwargs):raise next(failures)
    monkeypatch.setattr(launcher,'json_request',request)
    with pytest.raises(RuntimeError,match='двух попыток'):launcher.check_model('qwen3:8b',tmp_path)
    report=json.loads((tmp_path/'startup-ai.json').read_text())
    assert report['attempts'][0]['phase']=='http_response'
    assert report['attempts'][0]['invalid_json']=='bad API json'
    assert report['attempts'][1]['error']=='connection closed'
