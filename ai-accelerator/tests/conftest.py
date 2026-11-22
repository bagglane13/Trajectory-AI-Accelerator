import os, tempfile, uuid
from pathlib import Path
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='trajectory-tests-')
os.environ['DATABASE_URL']='sqlite:///'+str(Path(os.environ['DATA_DIR'])/'test.db')
os.environ['WORKER_ENABLED']='false'
os.environ['AI_MODE']='demo'
import pytest
from fastapi.testclient import TestClient
from app.main import app, auth_hits

@pytest.fixture
def client():
    auth_hits.clear()
    with TestClient(app) as client:
        r=client.post('/api/auth/register',json={'name':'Тест','email':f'{uuid.uuid4().hex}@example.com','password':'test-password-123'})
        assert r.status_code==201,r.text
        client.headers['X-CSRF-Token']=r.json()['csrf']
        yield client
