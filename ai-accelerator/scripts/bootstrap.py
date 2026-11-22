"""Project launcher; standard library only. Never changes global Python packages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
PROBE = "import json,sys,struct;print(json.dumps({'version':list(sys.version_info[:3]),'bits':struct.calcsize('P')*8,'release':sys.version_info.releaselevel,'path':sys.executable}))"
IMPORT_CHECK = 'import fastapi,uvicorn,sqlalchemy,httpx,multipart,argon2,pypdf,docx,rank_bm25,dotenv'

class SetupError(Exception):
    pass

def supported(info):
    return tuple(info['version'][:2]) in ((3,12),(3,13),(3,14)) and info['bits']==64 and info.get('release','final')=='final'

def probe(executable):
    try:
        r=subprocess.run([str(executable),'-c',PROBE],capture_output=True,text=True,timeout=15)
        return json.loads(r.stdout.strip()) if r.returncode==0 else None
    except (OSError,subprocess.TimeoutExpired,json.JSONDecodeError):
        return None

def execute(command):
    r=subprocess.run([str(x) for x in command],cwd=ROOT)
    if r.returncode:
        raise SetupError('Команда завершилась с ошибкой. Причина указана выше; сервер не запущен.')

def env_python(root=ROOT):
    return root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')

def ensure_environment(root=ROOT):
    target=env_python(root)
    info=probe(target) if target.exists() else None
    if info and supported(info) and tuple(info['version'][:2])==tuple(sys.version_info[:2]):return target,info
    if (root/'.venv').exists():
        backup=root/('.venv.backup-'+time.strftime('%Y%m%d-%H%M%S')+'-'+str(time.time_ns()%100000))
        (root/'.venv').rename(backup)
        print('Поврежденное или неподходящее окружение сохранено как '+backup.name,flush=True)
    print('Создаем отдельное окружение .venv...',flush=True)
    execute([sys.executable,'-m','venv',root/'.venv'])
    info=probe(target)
    if not info or not supported(info):raise SetupError('Не удалось создать рабочее окружение. Проверьте установку полного 64-битного Python.')
    return target,info

def install_dependencies(py,info,root=ROOT):
    requirements=root/'requirements.txt'
    fingerprint=hashlib.sha256(requirements.read_bytes()+json.dumps(info['version']).encode()).hexdigest()
    marker=root/'.venv'/'.trajectory-dependencies'
    ready=marker.exists() and marker.read_text().strip()==fingerprint
    if ready:
        result=subprocess.run([str(py),'-c',IMPORT_CHECK],capture_output=True)
        if result.returncode==0:
            print('Зависимости уже установлены. Повторное скачивание не требуется.',flush=True)
            return
    if subprocess.run([str(py),'-m','pip','--version'],capture_output=True).returncode:
        execute([py,'-m','ensurepip','--upgrade'])
    print('Устанавливаем FastAPI и остальные зависимости из requirements.txt. Нужен интернет.',flush=True)
    try:
        execute([py,'-m','pip','install','--disable-pip-version-check','--only-binary=:all:',
                 '--retries','2','--timeout','30','-r',requirements])
    except SetupError:
        raise SetupError('Установка пакетов не завершена. При ошибке сети проверьте доступ к pypi.org. '
                         'Если для вашей версии нет подходящего пакета, установите Python 3.12: py install 3.12. '
                         'Не устанавливайте C++ Build Tools: используются готовые wheels.')
    execute([py,'-c',IMPORT_CHECK])
    marker.write_text(fingerprint)

def available_port(port):
    try:
        with socket.socket() as s:s.bind(('127.0.0.1',port))
        return True
    except OSError:return False

def main(argv=None):
    parser=argparse.ArgumentParser(description='Запуск Траектории')
    parser.add_argument('--dev',action='store_true',help='Перезапуск сервера после изменения Python-кода')
    parser.add_argument('--check',action='store_true',help='Проверить окружение без установки пакетов')
    parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args(argv)
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
    info=probe(sys.executable)
    if not info or not supported(info):
        print('Нужен стабильный 64-битный Python 3.12, 3.13 или 3.14. Рекомендуется 3.12.')
        return 1
    print('Python: '+'.'.join(map(str,info['version']))+' (64-bit)\nПуть: '+info['path'],flush=True)
    if args.check:
        vinfo=probe(env_python()) if env_python().exists() else None
        print('.venv: '+('готово' if vinfo and supported(vinfo) else 'будет создано при запуске'))
        print('Порт '+str(args.port)+': '+('свободен' if available_port(args.port) else 'занят'))
        print('Диагностика завершена. Установка и запуск не выполнялись.')
        return 0
    if not 1024<=args.port<=65535:raise SetupError('Порт должен быть в диапазоне 1024–65535')
    if not available_port(args.port):raise SetupError(f'Порт {args.port} занят. Закройте другой сервер или запустите: start.bat --port 8001')
    py,info=ensure_environment()
    install_dependencies(py,info)
    execute([py,ROOT/'scripts'/'setup_env.py'])
    print(f'\nОткройте http://localhost:{args.port}\nОстановка: Ctrl+C. Данные сохраняются в папке data.\n',flush=True)
    command=[py,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(args.port)]
    if args.dev:command+=['--reload','--reload-dir',str(ROOT/'app')]
    try:return subprocess.call([str(x) for x in command],cwd=ROOT)
    except KeyboardInterrupt:return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (SetupError,OSError) as e:
        print('\nОшибка: '+str(e),file=sys.stderr)
        print('Инструкция: START_HERE_RU.md. Диагностика: diagnose.bat.',file=sys.stderr)
        sys.exit(1)
