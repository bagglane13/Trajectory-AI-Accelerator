import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
DATA = Path(os.getenv('DATA_DIR', str(ROOT / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
UPLOADS = DATA / 'uploads'
UPLOADS.mkdir(exist_ok=True)
DATABASE_URL = os.getenv('DATABASE_URL', f'sqlite:///{DATA / "accelerator.db"}')
if not DATABASE_URL.startswith('sqlite:///'):
    raise RuntimeError('DATABASE_URL must point to a local SQLite database')
AI_MODE = os.getenv('AI_MODE', 'demo').lower()
YANDEX_API_KEY = os.getenv('YANDEX_API_KEY', '')
YANDEX_MODEL = os.getenv('YANDEX_MODEL', '')
YANDEX_URL = os.getenv('YANDEX_URL', 'https://ai.api.cloud.yandex.net/foundationModels/v1/completion')
SECURE_COOKIE = os.getenv('SECURE_COOKIE', 'false').lower() == 'true'
WORKER_ENABLED = os.getenv('WORKER_ENABLED', 'true').lower() == 'true'
MAX_FILE = 20 * 1024 * 1024
MAX_DOCUMENTS = 50
MAX_TEXT = 4_000_000


GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.8-flash')
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen3:8b')
