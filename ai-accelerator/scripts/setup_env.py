"""Create the local settings file once; preserve existing settings."""
from pathlib import Path

root=Path(__file__).resolve().parent.parent
path=root/'.env'
if not path.exists():
    path.write_text((root/'.env.example').read_text(encoding='utf-8'),encoding='utf-8')
    try:path.chmod(0o600)
    except OSError:pass
print('Конфигурация .env готова. Существующие настройки сохранены.')
