"""Interactive local setup. Standard library only; never logs or sends keys to the app UI."""
import argparse
from datetime import datetime
from getpass import getpass
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import webbrowser

ROOT=Path(__file__).resolve().parent.parent
GEMINI_MODEL='gemini-3.8-flash'
OLLAMA_MODEL='qwen3:8b'
OLLAMA_URL='http://127.0.0.1:11434'


def request_json(url,body=None,headers=None,timeout=30):
    req=Request(url,data=None if body is None else json.dumps(body).encode('utf-8'),
                headers={'Content-Type':'application/json',**(headers or {})})
    try:
        with urlopen(req,timeout=timeout) as response:
            return json.load(response)
    except HTTPError as e:
        # Don't print the raw response or exception: upstream messages may include credentials.
        if e.code in (401,403):raise ValueError('Доступ отклонён. Проверьте ключ, регион и разрешения.') from None
        if e.code==429:raise ValueError('Бесплатная квота или частота запросов исчерпана. Повторите позже.') from None
        if e.code==404:raise ValueError('Модель не найдена. Проверьте её имя или скачайте её в Ollama.') from None
        raise ValueError(f'Провайдер вернул HTTP {e.code}. Настройки пока не сохранены.') from None
    except (URLError,TimeoutError,OSError):raise ValueError('Нет ответа. Проверьте интернет или запуск Ollama.') from None


def save_settings(values,root=ROOT):
    path=root/'.env'
    text=path.read_text(encoding='utf-8-sig') if path.exists() else (root/'.env.example').read_text(encoding='utf-8-sig')
    for value in values.values():
        if '\n' in value or '\r' in value or '"' in value:raise ValueError('Недопустимое значение настройки')
    lines=[];written=set()
    for line in text.splitlines():
        match=re.match(r'^\s*([A-Z_]+)\s*=',line)
        key=match.group(1) if match else None
        if key in values:
            if key not in written:lines.append(f'{key}="{values[key]}"');written.add(key)
        else:lines.append(line)
    lines.extend(f'{k}="{v}"' for k,v in values.items() if k not in written)
    # Write completely before replacement. A failed connection never reaches this function.
    temporary=root/'.env.connecting'
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:f.write('\n'.join(lines)+'\n')
    if path.exists():
        backup=root/('.env.backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        shutil.copyfile(path,backup)
        try:backup.chmod(0o600)
        except OSError:pass
    os.replace(temporary,path)
    try:path.chmod(0o600)
    except OSError:pass


def server_running():
    try:
        with socket.create_connection(('127.0.0.1',8000),timeout=0.3):return True
    except OSError:return False


def configure_gemini():
    print('\nGemini: используйте свой проект с тарифом Free Tier. Не подключайте оплату ради этого мастера.')
    print('Для региона, где Gemini недоступен, выберите локальную Ollama.')
    print('На бесплатном тарифе Google может использовать переданные материалы для улучшения продуктов.')
    print('Ключ выдаётся только в вашем аккаунте: https://aistudio.google.com/apikey')
    webbrowser.open('https://aistudio.google.com/apikey')
    key=getpass('Создайте свой ключ и вставьте сюда (ввод скрыт), затем Enter: ').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,256}',key):raise ValueError('Ключ пуст или содержит недопустимые символы. Скопируйте секретное значение целиком.')
    model=input(f'Модель [{GEMINI_MODEL}]: ').strip() or GEMINI_MODEL
    if not re.fullmatch(r'[A-Za-z0-9._-]+',model):raise ValueError('Некорректное имя модели')
    print('Проверяем короткий запрос. Текст методички не отправляется...')
    result=request_json(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
        {'contents':[{'parts':[{'text':'Верни только JSON: {"ok":true}'}]}],
         'generationConfig':{'responseMimeType':'application/json','maxOutputTokens':1024}},
        {'x-goog-api-key':key},timeout=120)
    try:
        candidate=result['candidates'][0]
        if candidate.get('finishReason') not in (None,'STOP'):raise ValueError()
        raw=''.join(p.get('text','') for p in candidate['content']['parts'] if not p.get('thought'))
        if json.loads(raw).get('ok') is not True:raise ValueError()
    except (KeyError,IndexError,TypeError,ValueError):raise ValueError('Ключ принят, но модель не вернула проверочный JSON. Настройки не изменены.') from None
    save_settings({'AI_MODE':'gemini','GEMINI_API_KEY':key,'GEMINI_MODEL':model})
    print('Gemini ответил. Ключ сохранён только в локальном .env. Запустите start.bat.')


def ollama_executable():
    found=shutil.which('ollama')
    if found:return found
    local_appdata=os.environ.get('LOCALAPPDATA','')
    if local_appdata:
        path=Path(local_appdata)/'Programs'/'Ollama'/'ollama.exe'
        if path.is_file():return str(path)
    return None


def ensure_ollama():
    try:return request_json(OLLAMA_URL+'/api/tags',timeout=2)
    except ValueError:pass
    exe=ollama_executable()
    if not exe:
        webbrowser.open('https://ollama.com/download/windows')
        raise ValueError('Открыта официальная страница Ollama. Установите Ollama, запустите её и повторите connect-ai.bat → 1. Настройки не изменены.')
    print('Запускаем локальный сервер Ollama...')
    # No shell: paths containing Cyrillic, spaces and ! are passed as one argument.
    kwargs={'creationflags':getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)} if os.name=='nt' else {'start_new_session':True}
    subprocess.Popen([exe,'serve'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**kwargs)
    for _ in range(20):
        try:return request_json(OLLAMA_URL+'/api/tags',timeout=1)
        except ValueError:time.sleep(1)
    raise ValueError('Ollama не запустилась. Откройте Ollama через меню Пуск и повторите мастер.')


def configure_ollama():
    print('\nЛокальная модель: без аккаунта, ключа и оплаты API. Скорость зависит от компьютера.')
    print('qwen3:8b: файл около 5.2 ГБ; память для работы нужна дополнительно. Для курса лучше иметь 16+ ГБ ОЗУ.')
    print('На слабом компьютере урок может генерироваться долго; начните с двух вопросов.')
    tags=ensure_ollama();model=input(f'Локальная модель [{OLLAMA_MODEL}]: ').strip() or OLLAMA_MODEL
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]*',model) or model.endswith((':cloud','-cloud')):
        raise ValueError('Укажите локальную модель без суффикса cloud, например qwen3:8b.')
    names={x.get('name') for x in tags.get('models',[])}
    if model not in names:
        exe=ollama_executable()
        if not exe:raise ValueError('Не найдена команда ollama. Откройте новое окно cmd после установки.')
        print('Скачиваем модель. В окне будет виден прогресс; первое скачивание может занять время...')
        subprocess.run([exe,'pull',model],check=True)
    print('Проверяем генерацию JSON на вашем компьютере. Это может занять несколько минут...')
    result=request_json(OLLAMA_URL+'/api/chat',
        {'model':model,'stream':False,'think':False,'format':'json',
         'messages':[{'role':'user','content':'Верни только JSON-объект {"ok":true}'}],
         'options':{'temperature':0,'num_predict':128}},timeout=240)
    try:
        if json.loads(result['message']['content']).get('ok') is not True:raise ValueError()
    except (KeyError,TypeError,ValueError):raise ValueError('Локальная модель не прошла проверку JSON. Настройки не изменены.') from None
    save_settings({'AI_MODE':'ollama','OLLAMA_URL':OLLAMA_URL,'OLLAMA_MODEL':model})
    print('Локальная модель ответила. Настройки сохранены. Запустите start.bat.')


def main():
    if server_running():raise ValueError('Сначала остановите приложение на порту 8000: Ctrl+C в окне сервера. Затем повторите мастер.')
    print('Траектория — подключение настоящей нейросети')
    print('1 — Локальная Ollama: API-ключ вообще не нужен')
    print('2 — Gemini Free Tier: собственный ключ Google, интернет и ограничения квоты')
    print('0 — Выйти без изменений')
    choice=input('Выберите 1 или 2: ').strip()
    if choice=='1':configure_ollama()
    elif choice=='2':configure_gemini()
    elif choice!='0':raise ValueError('Неизвестный пункт')


if __name__=='__main__':
    try:main()
    except (KeyboardInterrupt,EOFError):print('\nОтменено. Существующие настройки сохранены.');raise SystemExit(1)
    except (ValueError,OSError,subprocess.CalledProcessError) as e:
        # Only our own ValueErrors contain safe user-facing messages.
        print('\n'+(str(e) if isinstance(e,ValueError) else 'Ошибка чтения/записи или команды Ollama. Проверьте путь и повторите.'))
        raise SystemExit(1)
