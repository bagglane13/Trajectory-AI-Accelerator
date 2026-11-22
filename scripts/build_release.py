"""Build a source release, excluding local data, secrets and downloaded runtimes."""
import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def include(path):
    parts = path.parts
    excluded = {'.git', '.runtime', '.venv', 'data', '__pycache__', '.pytest_cache', 'dist'}
    if any(part in excluded or part.startswith(('.venv.backup-', 'backup-code-')) for part in parts):
        return False
    if any(part.startswith('.env') and part != '.env.example' for part in parts):
        return False
    return path.suffix.lower() not in ('.zip', '.pyc', '.pyo', '.log') and not path.name.startswith('~$')


def build(root=ROOT, output=None):
    root = Path(root).resolve()
    output = Path(output) if output is not None else root / 'dist' / 'Trajectory_AI_Project.zip'
    required = ('START.bat', 'START.ps1', 'run_local.py', 'Trajectory_AI_Instruction_RU.docx',
                'README.md', 'ai-accelerator/app/main.py', 'ai-accelerator/frontend/index.html')
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise ValueError('Missing release files: ' + ', '.join(missing))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(root.rglob('*')):
            if path.is_file() and include(path.relative_to(root)) and path.resolve() != output.resolve():
                archive.write(path, Path('Trajectory_AI_Accelerator') / path.relative_to(root))
    with zipfile.ZipFile(output) as archive:
        damaged = archive.testzip()
        if damaged:
            raise ValueError('Archive verification failed: ' + damaged)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print(build(output=args.output))
