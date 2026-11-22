"""One-click Windows launcher. Runs local AI only; never asks for a key or modifies cloud billing."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import Request,urlopen,build_opener,ProxyHandler
import webbrowser
import zipfile

BUNDLE=Path(__file__).resolve().parent
STATE=BUNDLE/'.runtime'
RUNTIME=STATE/'runtime'
OLLAMA_RELEASE='v0.40.12'
OLLAMA_SHA256='21814944f3e50d3f07b6bb3af75baddb96f59e91353c332ac9c5063b3bfd1041'
OLLAMA_URL='http://127.0.0.1:11435'
MODEL_CHECK_SCHEMA={'type':'object','properties':{'ok':{'type':'boolean','enum':[True]}},
                    'required':['ok'],'additionalProperties':False}


def load_script(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def download(url,path,sha=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        with path.open('rb') as f:
            digest=hashlib.file_digest(f,'sha256').hexdigest()
        if not sha or digest==sha:return
    temporary=path.with_suffix(path.suffix+'.part');last=0;count=0;digest=hashlib.sha256()
    req=Request(url,headers={'User-Agent':'TrajectoryAI/1.3.6'})
    with urlopen(req,timeout=60) as response,temporary.open('wb') as f:
        size=int(response.headers.get('Content-Length','0'))
        while block:=response.read(4*1024*1024):
            f.write(block);digest.update(block);count+=len(block)
            if time.monotonic()-last>5:
                print(f'  Скачано {count//1048576} МБ'+(f' из {size//1048576} МБ' if size else ''),flush=True);last=time.monotonic()
    if sha and digest.hexdigest()!=sha:
        temporary.unlink(missing_ok=True);raise RuntimeError('Контрольная сумма скачанного файла не совпала. Повторите запуск.')
    temporary.replace(path)


def safe_extract(path,destination):
    destination.mkdir(parents=True,exist_ok=True);root=destination.resolve()
    with zipfile.ZipFile(path) as z:
        for item in z.infolist():
            out=(root/item.filename).resolve()
            if not out.is_relative_to(root):raise RuntimeError('Некорректный путь в скачанном архиве')
        z.extractall(destination)


def json_request(url,body=None,timeout=5):
    req=Request(url,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    with build_opener(ProxyHandler({})).open(req,timeout=timeout) as response:return json.load(response)


def check_model(model,logs):
    """Run a bounded real inference probe; never bypass a failed model check."""
    path=Path(logs)/'startup-ai.json'
    report={'model':model,'url':OLLAMA_URL,'status':'checking','attempts':[]}
    body={'model':model,'stream':False,'think':False,'format':MODEL_CHECK_SCHEMA,
          'messages':[{'role':'system','content':'Return exactly the JSON object required by the schema. No explanation.'},
                      {'role':'user','content':'Return {"ok": true}.'}],
          'options':{'temperature':0,'num_predict':128,'num_ctx':4096}}
    for attempt in range(1,3):
        started=time.monotonic();record={'attempt':attempt,'phase':'http_response'}
        report['attempts'].append(record)
        try:
            response=json_request(OLLAMA_URL+'/api/chat',body,timeout=600)
            record['response']=response
            record['phase']='model_message'
            if not isinstance(response,dict):raise ValueError('API вернул ответ неправильного типа')
            if response.get('done_reason')=='length':raise ValueError('Пробный ответ обрезан лимитом длины')
            if response.get('done') is False:raise ValueError('Генерация пробного ответа не завершена')
            message=response.get('message')
            if not isinstance(message,dict) or not isinstance(message.get('content'),str):
                raise ValueError('API не вернул текст пробного ответа')
            answer=json.loads(message['content'])
            if not isinstance(answer,dict) or set(answer)!={'ok'} or answer['ok'] is not True:
                raise ValueError('Пробный ответ не соответствует схеме {"ok": true}')
            record['success']=True;report['status']='passed'
        except (ValueError,KeyError,TypeError,OSError) as error:
            record['error']=str(error)
            if isinstance(error,json.JSONDecodeError):record['invalid_json']=error.doc[:32000]
        record['seconds']=round(time.monotonic()-started,3)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if record.get('success'):return
        if attempt<2:print('  Пробный ответ не прошёл проверку. Повторяем короткий запрос (2/2)...',flush=True)
    report['status']='failed'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    raise RuntimeError('Не удалось подтвердить корректный ответ локальной модели после двух попыток. '
                       'Сайт пока не запущен. Подробности: '+str(path))


def existing_project(bundle=None):
    project=(BUNDLE if bundle is None else Path(bundle))/'ai-accelerator'
    required=('app/main.py','frontend/index.html','scripts/bootstrap.py','requirements.txt')
    if not all((project/name).is_file() for name in required):
        raise RuntimeError('Распакуйте архив целиком. Рядом с START.bat должна быть папка ai-accelerator с исходниками.')
    return project


def free_port(start=8000,stop=8020):
    for port in range(start,stop):
        with socket.socket() as s:
            try:s.bind(('127.0.0.1',port));return port
            except OSError:pass
    raise RuntimeError(f'Все локальные порты {start}–{stop-1} заняты')


def select_model(memory_gib):
    # Tiny models are not used as a silent substitute: they cannot reliably write and review a course.
    if memory_gib<11:raise RuntimeError('Для qwen3:8b нужно минимум 12 ГБ ОЗУ; на ноутбуке обнаружено меньше. Для стабильной работы рекомендуется 16 ГБ или больше.')
    return 'qwen3:8b'


def memory_gib():
    if os.name=='nt':
        import ctypes
        class Status(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total',ctypes.c_ulonglong),('avail',ctypes.c_ulonglong),('page',ctypes.c_ulonglong),('page_avail',ctypes.c_ulonglong),('virtual',ctypes.c_ulonglong),('virtual_avail',ctypes.c_ulonglong),('extended',ctypes.c_ulonglong)]
        stat=Status();stat.length=ctypes.sizeof(Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):return stat.total/2**30
    return 16


def prepare_ollama(logs):
    global OLLAMA_URL
    root=RUNTIME/('ollama-'+OLLAMA_RELEASE);exe=root/'ollama.exe';marker=root/'.verified'
    if not exe.is_file() or not marker.is_file():
        if shutil.disk_usage(RUNTIME).free<10*2**30:raise RuntimeError('Нужно около 15 ГБ свободного места на диске с проектом для движка, распаковки и модели.')
        print('[3/6] Скачиваем локальный AI-движок Ollama (первый запуск)...',flush=True)
        archive=RUNTIME/'ollama-windows-amd64.zip'
        download(f'https://github.com/ollama/ollama/releases/download/{OLLAMA_RELEASE}/ollama-windows-amd64.zip',archive,OLLAMA_SHA256)
        safe_extract(archive,root)
        if not exe.is_file():raise RuntimeError('В архиве не найден ollama.exe')
        marker.write_text(OLLAMA_SHA256)
        archive.unlink(missing_ok=True)
    marker=STATE/'ollama.json'
    try:
        saved=json.loads(marker.read_text(encoding='utf-8'))
        address=saved['url']
        from urllib.parse import urlparse
        parsed=urlparse(address)
        if (saved.get('bundle')==str(BUNDLE.resolve()) and parsed.scheme=='http' and parsed.hostname=='127.0.0.1'
            and 11435<=parsed.port<11455 and parsed.path in ('','/') and not parsed.query and not parsed.fragment):
            json_request(address+'/api/tags');OLLAMA_URL=address;return exe,None
    except (OSError,ValueError,KeyError,TypeError):pass
    OLLAMA_URL=f'http://127.0.0.1:{free_port(11435,11455)}'
    env=dict(os.environ,OLLAMA_HOST=OLLAMA_URL.removeprefix('http://'),OLLAMA_MODELS=str(STATE/'models'),OLLAMA_NO_CLOUD='1',OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_FLASH_ATTENTION='1',OLLAMA_KV_CACHE_TYPE='q8_0')
    output=(logs/'ollama.log').open('a',encoding='utf-8')
    daemon=subprocess.Popen([str(exe),'serve'],cwd=root,env=env,stdout=output,stderr=output,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    for _ in range(60):
        if daemon.poll() is not None:raise RuntimeError('AI-движок остановился. Подробности: '+str(logs/'ollama.log'))
        try:
            json_request(OLLAMA_URL+'/api/tags')
            marker.write_text(json.dumps({'url':OLLAMA_URL,'bundle':str(BUNDLE.resolve()),'pid':daemon.pid}),encoding='utf-8')
            return exe,daemon
        except Exception:time.sleep(1)
    daemon.terminate();raise RuntimeError('Ollama не успела запуститься. Подробности: '+str(logs/'ollama.log'))


def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
    if os.name!='nt':raise RuntimeError('Этот автоматический установщик предназначен для Windows 10/11 x64.')
    RUNTIME.mkdir(parents=True,exist_ok=True);logs=STATE/'logs';logs.mkdir(exist_ok=True)
    # A second click opens the existing instance; it never launches a second worker against the same data.
    marker=STATE/'server.json'
    if marker.is_file():
        try:
            address=json.loads(marker.read_text())['url'];c=json_request(address+'/api/config')
            if c.get('version')=='1.3.6' and c.get('ai_mode')=='ollama' and json.loads(marker.read_text()).get('project')==str(existing_project().resolve()):webbrowser.open(address);return
        except Exception:pass
    import msvcrt
    guard=(STATE/'launcher.lock').open('a+b')
    if guard.seek(0,2)==0:guard.write(b'0');guard.flush()
    guard.seek(0)
    try:msvcrt.locking(guard.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        print('Запуск уже выполняется в другом окне. Дождитесь окончания подготовки.',flush=True);return
    project=existing_project()
    print('[1/6] Запускаем исходники из этой папки: '+str(project),flush=True)
    bootstrap=load_script('trajectory_bootstrap',project/'scripts/bootstrap.py')
    print('[2/6] Готовим Python и зависимости (первый запуск требует интернет)...',flush=True)
    py,info=bootstrap.ensure_environment(project);bootstrap.install_dependencies(py,info,project)
    model=select_model(memory_gib());exe,daemon=prepare_ollama(logs)
    env=dict(os.environ,AI_MODE='ollama',WORKER_ENABLED='true',OLLAMA_URL=OLLAMA_URL,OLLAMA_MODEL=model,
             DATA_DIR=str(project/'data'),DATABASE_URL='sqlite:///'+str(project/'data/accelerator.db'),SECURE_COOKIE='false',PYTHONUTF8='1')
    env['OLLAMA_HOST']=OLLAMA_URL.removeprefix('http://')
    models=json_request(OLLAMA_URL+'/api/tags').get('models',[])
    if not any(m.get('name')==model for m in models):
        print('[4/6] Скачиваем модель '+model+' (~5.2 ГБ). Дождитесь окончания...',flush=True)
        subprocess.run([str(exe),'pull',model],env=env,check=True)
    else:print('[4/6] Модель уже скачана.',flush=True)
    print('[5/6] Проверяем реальный ответ локальной нейросети...',flush=True)
    check_model(model,logs)
    settings=load_script('trajectory_settings',project/'scripts/connect_ai.py')
    settings.save_settings({'AI_MODE':'ollama','OLLAMA_URL':OLLAMA_URL,'OLLAMA_MODEL':model},root=project)
    print('[6/6] Запускаем приложение и открываем браузер...',flush=True)
    port=free_port();address=f'http://127.0.0.1:{port}';output=(logs/'app.log').open('a',encoding='utf-8')
    process=subprocess.Popen([str(py),'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=project,env=env,stdout=output,stderr=output)
    try:
        for _ in range(60):
            if process.poll() is not None:raise RuntimeError('Сервер остановился. Откройте журнал: '+str(logs/'app.log'))
            try:
                if json_request(address+'/health').get('status')=='ok':break
            except Exception:pass
            time.sleep(1)
        else:raise RuntimeError('Сервер не успел запуститься. Журнал: '+str(logs/'app.log'))
        marker.write_text(json.dumps({'url':address,'pid':process.pid,'project':str(project.resolve())}))
        webbrowser.open(address)
        print('\nГОТОВО: '+address+'\nAI: '+model+' · '+OLLAMA_URL+'\nЛокальная нейросеть подключена. Окно можно свернуть. Для остановки нажмите Ctrl+C.\nЖурналы: '+str(logs),flush=True)
        process.wait()
    finally:
        if process.poll() is None:process.terminate()
        marker.unlink(missing_ok=True)


if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('\nПриложение остановлено.')
    except Exception as e:print('\nОшибка запуска: '+str(e),flush=True);raise SystemExit(1)
