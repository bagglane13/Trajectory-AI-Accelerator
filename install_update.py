"""Install the supplied source update into Artem's existing project; keep data and secrets."""
from datetime import datetime
from pathlib import Path
import os
import runpy
import shutil
import socket

ROOT=Path(__file__).resolve().parent


def find_project(path):
    for p in (path,path/'ai-accelerator'):
        if (p/'app'/'main.py').is_file() and (p/'start.bat').is_file():return p
    raise ValueError('Папка проекта не найдена: '+str(path)+'\nРаспакуйте файлы ai-accelerator поверх своей папки проекта вручную. См. FREE_AI_RU.md.')


def allowed(path):
    return not any(x in ('data','.venv','__pycache__','.pytest_cache','.git') or x.startswith('.venv.backup-') or x.startswith('.env') and x!='.env.example' for x in path.parts) and path.suffix not in ('.pyc','.zip')


def install(source,target):
    if source.resolve()==target.resolve():return None
    backup=target/('backup-code-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    changed=[]
    try:
        for f in sorted(source.rglob('*')):
            rel=f.relative_to(source)
            if not f.is_file() or not allowed(rel):continue
            dest=target/rel
            if dest.is_file() and dest.read_bytes()==f.read_bytes():continue
            old=backup/rel if dest.exists() else None
            if old is not None:old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,old)
            changed.append((dest,old))
            dest.parent.mkdir(parents=True,exist_ok=True)
            temp=dest.with_name(dest.name+'.trajectory-update')
            shutil.copy2(f,temp);os.replace(temp,dest)
    except Exception:
        for dest,old in reversed(changed):
            dest.with_name(dest.name+'.trajectory-update').unlink(missing_ok=True)
            if old is not None and old.exists():shutil.copy2(old,dest)
            elif old is None:dest.unlink(missing_ok=True)
        raise
    return backup if backup.exists() else None


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Optional source update into an explicitly selected project. START.bat does not use this utility.')
    parser.add_argument('target',type=Path)
    args=parser.parse_args()
    target=find_project(args.target)
    backup=install(ROOT/'ai-accelerator',target)
    print('Updated:',target)
    if backup:print('Source backup:',backup)


if __name__=='__main__':main()
