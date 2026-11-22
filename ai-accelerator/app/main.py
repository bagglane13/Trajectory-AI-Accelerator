import hashlib, re, secrets, threading, time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Depends, Request, Response, HTTPException, UploadFile, File, Form, Header
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from . import config, jobs, providers, exams
from .db import Base, engine, Session, User, LoginSession, Course, Document, Chunk, Lesson, Attempt, Exam, ExamAttempt, Job, Run, uid, now
from .schemas import Credentials, CourseInput, Schedule, QuestionsInput, AttemptInput, ReplanInput, ExamAnswers
from .planner import budget, allocate, InsufficientTime
from .materials import extract, parse_questions, extract_questions, is_heading

passwords=PasswordHasher();mutation_lock=threading.RLock();auth_hits=defaultdict(deque)

@asynccontextmanager
async def lifespan(app):
    if config.AI_MODE not in providers.LABELS:raise RuntimeError('AI_MODE must be demo, yandex, gemini or ollama')
    Base.metadata.create_all(engine)
    worker=jobs.start_worker() if config.WORKER_ENABLED else None
    yield
    if worker:worker[0].set();worker[1].join(timeout=2)

app=FastAPI(title='Траектория — AI-акселератор',version='1.3.6',lifespan=lifespan)

@app.middleware('http')
async def security_headers(request,call_next):
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and urlparse(origin).netloc!=request.headers.get('host'):
        return JSONResponse({'detail':'Недопустимый источник запроса'},403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/api'):response.headers['Cache-Control']='no-store'
    return response

def db_session():
    with Session() as db:yield db

def user_session(request:Request,db=Depends(db_session)):
    token=request.cookies.get('session','')
    sess=db.get(LoginSession,hashlib.sha256(token.encode()).hexdigest()) if token else None
    if not sess or sess.expires<now():raise HTTPException(401,'Войдите в учетную запись')
    if request.method not in ('GET','HEAD') and not secrets.compare_digest(request.headers.get('X-CSRF-Token',''),sess.csrf):
        raise HTTPException(403,'Обновите страницу: неверный CSRF-токен')
    return db.get(User,sess.user_id),sess

def own_course(db,cid,user):
    c=db.get(Course,cid)
    if not c or c.user_id!=user.id:raise HTTPException(404,'Курс не найден')
    return c

def own_lesson(db,lid,user):
    l=db.get(Lesson,lid)
    if not l:raise HTTPException(404,'Урок не найден')
    return l,own_course(db,l.course_id,user)

def auth_limit(request):
    key=request.client.host if request.client else 'local'
    with mutation_lock:
        t=now();q=auth_hits[key]
        while q and q[0]<t-60:q.popleft()
        if len(q)>=15:raise HTTPException(429,'Слишком много попыток. Подождите минуту.')
        q.append(t)
        if len(auth_hits)>10000:auth_hits.clear()

def set_session(db,u,response):
    token=secrets.token_hex(32);csrf=secrets.token_hex(32)
    db.add(LoginSession(token=hashlib.sha256(token.encode()).hexdigest(),user_id=u.id,csrf=csrf,expires=now()+7*86400));db.commit()
    response.set_cookie('session',token,max_age=7*86400,httponly=True,samesite='lax',secure=config.SECURE_COOKIE,path='/')
    return {'id':u.id,'email':u.email,'name':u.name,'csrf':csrf}

@app.get('/api/config')
def public_config():
    return {'ai_mode':config.AI_MODE,
            'provider_configured':providers.configured(),'provider_label':providers.LABELS.get(config.AI_MODE,config.AI_MODE),'model':providers.model_name(),
            'database':'sqlite','version':'1.3.6'}

@app.get('/health')
def health():return {'status':'ok'}

@app.post('/api/auth/register',status_code=201)
def register(data:Credentials,request:Request,response:Response,db=Depends(db_session)):
    auth_limit(request)
    email=data.email.strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise HTTPException(422,'Введите корректный email')
    u=User(email=email,name=data.name.strip() or 'Студент',password=passwords.hash(data.password));db.add(u)
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Этот email уже зарегистрирован')
    return set_session(db,u,response)

@app.post('/api/auth/login')
def login(data:Credentials,request:Request,response:Response,db=Depends(db_session)):
    auth_limit(request);u=db.scalar(select(User).where(User.email==data.email.strip().lower()))
    try:valid=bool(u and passwords.verify(u.password,data.password))
    except (VerifyMismatchError,InvalidHashError):valid=False
    if not valid:raise HTTPException(401,'Неверный email или пароль')
    return set_session(db,u,response)

@app.post('/api/auth/logout')
def logout(response:Response,auth=Depends(user_session),db=Depends(db_session)):
    db.execute(delete(LoginSession).where(LoginSession.token==auth[1].token));db.commit();response.delete_cookie('session');return {'ok':True}

@app.get('/api/me')
def me(auth=Depends(user_session)):
    u,s=auth;return {'id':u.id,'name':u.name,'email':u.email,'csrf':s.csrf}

def course_summary(db,c):
    lessons=db.scalars(select(Lesson).where(Lesson.course_id==c.id).order_by(Lesson.position)).all()
    done=sum(l.completed for l in lessons)
    active=db.scalars(select(Job).where(Job.course_id==c.id,Job.state.in_(jobs.ACTIVE))).all()
    return {'id':c.id,'title':c.title,'level':c.level,'schedule':c.schedule,'status':c.status,'version':c.version,
            'created':c.created,'question_count':len(c.questions),'total':len(lessons),'completed':done,
            'progress':round(100*done/len(lessons)) if lessons else 0,'budget':budget(c.schedule),
            'next_lesson':next((l.id for l in lessons if not l.completed),None),
            'active_jobs':[jobs.describe(j) for j in active]}

@app.get('/api/courses')
def courses(auth=Depends(user_session),db=Depends(db_session)):
    return [course_summary(db,c) for c in db.scalars(select(Course).where(Course.user_id==auth[0].id).order_by(Course.created.desc()))]

@app.post('/api/courses',status_code=201)
def create_course(data:CourseInput,auth=Depends(user_session),db=Depends(db_session)):
    c=Course(user_id=auth[0].id,title=data.title.strip(),level=data.level,schedule=data.schedule.model_dump(mode='json'));db.add(c);db.commit()
    return course_summary(db,c)

@app.get('/api/courses/{cid}')
def course_detail(cid:str,auth=Depends(user_session),db=Depends(db_session)):
    c=own_course(db,cid,auth[0]);result=course_summary(db,c)
    result.update(questions=c.questions,plan=c.plan,history=c.history,
        documents=[{'id':d.id,'name':d.name,'role':d.role,'characters':len(d.text)} for d in db.scalars(select(Document).where(Document.course_id==cid))],
        lessons=[{'id':l.id,'topic':l.topic,'ready':bool(l.content),'completed':l.completed,'theory_read':l.theory_read,'mode':l.content.get('mode')} for l in db.scalars(select(Lesson).where(Lesson.course_id==cid).order_by(Lesson.position))],
        recent_jobs=[jobs.describe(j) for j in db.scalars(select(Job).where(Job.course_id==cid).order_by(Job.created.desc()).limit(12))])
    return result

def require_editable(db,c):
    if c.status=='ready':raise HTTPException(409,'Материалы готового курса неизменяемы. Создайте новый курс для другой версии методички.')
    if db.scalar(select(Job.id).where(Job.course_id==c.id,Job.state.in_(jobs.ACTIVE)).limit(1)):
        raise HTTPException(409,'Дождитесь окончания текущей обработки')

@app.post('/api/courses/{cid}/documents',status_code=201)
def upload(cid:str,file:UploadFile=File(...),role:str=Form('methodology'),auth=Depends(user_session),db=Depends(db_session)):
    if role not in ('methodology','questions'):raise HTTPException(422,'Неизвестная роль файла')
    raw=file.file.read(config.MAX_FILE+1)
    if len(raw)>config.MAX_FILE:raise HTTPException(413,'Файл больше 20 МБ')
    name=Path(file.filename or 'file.txt').name[:255]
    with mutation_lock:
        c=own_course(db,cid,auth[0]);require_editable(db,c)
        sha=hashlib.sha256(raw).hexdigest()
        existing=db.scalar(select(Document).where(Document.course_id==cid,Document.sha==sha,Document.role==role))
        if existing:return {'id':existing.id,'duplicate':True,'questions':[q['text'] for q in c.questions]}
        total=db.scalar(select(func.count()).select_from(Document).where(Document.course_id==cid))
        if total>=config.MAX_DOCUMENTS:raise HTTPException(422,f'Максимум {config.MAX_DOCUMENTS} документов на курс')
        try:text,chunks=extract(name,raw)
        except ValueError as e:raise HTTPException(422,str(e))
        existing_text=sum(len(d.text) for d in db.scalars(select(Document).where(Document.course_id==cid)))
        if existing_text+len(text)>config.MAX_TEXT:raise HTTPException(422,'Превышен общий лимит текста курса')
        did=uid();path=config.UPLOADS/(did+Path(name).suffix.lower());path.write_bytes(raw)
        doc=Document(id=did,course_id=cid,name=name,role=role,sha=sha,path=path.name,text=text);db.add(doc);db.flush()
        for loc,piece in chunks:db.add(Chunk(document_id=did,course_id=cid,locator=loc,text=piece))
        questions=extract_questions(name,raw,text) if role=='questions' else []
        if questions:c.questions=[{'id':uid(),'text':q,'number':i+1} for i,q in enumerate(questions)]
        c.version+=1
        try:db.commit()
        except Exception:path.unlink(missing_ok=True);raise
        return {'id':did,'characters':len(text),'chunks':len(chunks),'questions':questions}

@app.get('/api/documents/{did}/preview')
def preview(did:str,auth=Depends(user_session),db=Depends(db_session)):
    d=db.get(Document,did)
    if not d:raise HTTPException(404,'Документ не найден')
    own_course(db,d.course_id,auth[0]);return {'name':d.name,'text':d.text[:30000],'truncated':len(d.text)>30000}

@app.get('/api/sources/{sid}')
def source(sid:str,auth=Depends(user_session),db=Depends(db_session)):
    s=db.get(Chunk,sid)
    if not s:raise HTTPException(404,'Источник не найден')
    own_course(db,s.course_id,auth[0]);d=db.get(Document,s.document_id)
    return {'text':s.text,'locator':s.locator,'document':d.name}

@app.put('/api/courses/{cid}/questions')
def questions(cid:str,data:QuestionsInput,auth=Depends(user_session),db=Depends(db_session)):
    with mutation_lock:
        c=own_course(db,cid,auth[0]);require_editable(db,c)
        c.questions=[{'id':uid(),'number':i+1,'text':q} for i,q in enumerate(data.questions)]
        c.version+=1;db.commit();return c.questions

def enqueue(db,c,kind,target='',key=None):
    with mutation_lock:
        # The local server serializes enqueue operations with mutation_lock.
        key=key or uid()
        if len(key)>100:raise HTTPException(422,'Слишком длинный Idempotency-Key')
        previous=db.scalar(select(Job).where(Job.course_id==c.id,Job.key==key))
        if previous:
            if previous.kind!=kind or previous.target!=target:raise HTTPException(409,'Ключ уже использован для другой операции')
            return jobs.describe(previous)
        existing=db.scalar(select(Job).where(Job.course_id==c.id,Job.state.in_(jobs.ACTIVE)))
        if existing:
            if existing.kind==kind and existing.target==target:return jobs.describe(existing)
            raise HTTPException(409,'У курса уже выполняется другая AI-операция. Дождитесь завершения.')
        j=Job(course_id=c.id,key=key,kind=kind,target=target,course_version=c.version);db.add(j);db.commit()
        return jobs.describe(j)

@app.post('/api/courses/{cid}/generate',status_code=202)
def generate_plan(cid:str,idempotency_key:str|None=Header(default=None),auth=Depends(user_session),db=Depends(db_session)):
    c=own_course(db,cid,auth[0])
    if idempotency_key:
        previous=db.scalar(select(Job).where(Job.course_id==cid,Job.key==idempotency_key))
        if previous:
            if previous.kind!='plan':raise HTTPException(409,'Ключ использован для другой операции')
            return jobs.describe(previous)
    if c.status=='ready':raise HTTPException(409,'План уже создан')
    if not c.questions:raise HTTPException(422,'Добавьте и сохраните контрольные вопросы')
    if not db.scalar(select(Document.id).where(Document.course_id==cid,Document.role=='methodology')):raise HTTPException(422,'Загрузите методичку')
    return enqueue(db,c,'plan',key=idempotency_key)

@app.get('/api/jobs/{jid}')
def job_status(jid:str,auth=Depends(user_session),db=Depends(db_session)):
    j=db.get(Job,jid)
    if not j:raise HTTPException(404,'Задание не найдено')
    own_course(db,j.course_id,auth[0]);return jobs.describe(j)

@app.post('/api/jobs/{jid}/retry',status_code=202)
def retry_job(jid:str,auth=Depends(user_session),db=Depends(db_session)):
    with mutation_lock:
        j=db.get(Job,jid)
        if not j:raise HTTPException(404,'Задание не найдено')
        c=own_course(db,j.course_id,auth[0])
        if j.state in jobs.ACTIVE:raise HTTPException(409,'Задание еще выполняется')
        if j.state=='completed':raise HTTPException(409,'Задание уже завершено')
        return enqueue(db,c,j.kind,j.target)

@app.post('/api/jobs/{jid}/cancel')
def cancel_job(jid:str,auth=Depends(user_session),db=Depends(db_session)):
    j=db.get(Job,jid)
    if not j:raise HTTPException(404,'Задание не найдено')
    own_course(db,j.course_id,auth[0])
    if j.state in jobs.ACTIVE:
        j.state='interrupted';j.error='Остановлено пользователем. Поздний результат не будет сохранен.';j.stage='Остановлено';j.token='';db.commit()
    return jobs.describe(j)

@app.post('/api/lessons/{lid}/generate',status_code=202)
def generate_lesson(lid:str,idempotency_key:str|None=Header(default=None),auth=Depends(user_session),db=Depends(db_session)):
    l,c=own_lesson(db,lid,auth[0])
    if idempotency_key:
        previous=db.scalar(select(Job).where(Job.course_id==c.id,Job.key==idempotency_key))
        if previous:
            if previous.kind!='lesson' or previous.target!=lid:raise HTTPException(409,'Ключ использован для другой операции')
            return jobs.describe(previous)
    if l.content:raise HTTPException(409,'Материал уже готов')
    return enqueue(db,c,'lesson',lid,idempotency_key)

@app.get('/api/lessons/{lid}')
def get_lesson(lid:str,auth=Depends(user_session),db=Depends(db_session)):
    l,c=own_lesson(db,lid,auth[0]);content=dict(l.content)
    if content:content['tasks']=[{k:v for k,v in t.items() if k not in ('correct_index','expected','rubric')} for t in content['tasks']]
    attempts=[{'id':a.id,'task_id':a.task_id,'answer':a.answer,'result':a.result,'created':a.created} for a in db.scalars(select(Attempt).where(Attempt.lesson_id==lid).order_by(Attempt.created.desc()))]
    siblings=db.scalars(select(Lesson).where(Lesson.course_id==c.id).order_by(Lesson.position)).all()
    return {'id':l.id,'course_id':c.id,'course_title':c.title,'topic':l.topic,'content':content,
            'theory_read':l.theory_read,'completed':l.completed,'attempts':attempts,
            'siblings':[{'id':x.id,'title':x.topic['title'],'completed':x.completed} for x in siblings],
            'jobs':[jobs.describe(j) for j in db.scalars(select(Job).where(Job.course_id==c.id).order_by(Job.created.desc()).limit(8))]}

@app.put('/api/lessons/{lid}/read')
def mark_read(lid:str,auth=Depends(user_session),db=Depends(db_session)):
    l,c=own_lesson(db,lid,auth[0])
    if not l.content:raise HTTPException(409,'Сначала создайте материал урока')
    l.theory_read=True;jobs.update_progress(db,l);db.commit();return {'completed':l.completed,'theory_read':True}

@app.post('/api/lessons/{lid}/tasks/{tid}/attempts')
def submit(lid:str,tid:str,data:AttemptInput,auth=Depends(user_session),db=Depends(db_session)):
    with mutation_lock:
        l,c=own_lesson(db,lid,auth[0]);task=next((x for x in l.content.get('tasks',[]) if x['id']==tid),None)
        if not task:raise HTTPException(404,'Задание не найдено')
        answer=data.answer.strip()
        if not answer:raise HTTPException(422,'Введите ответ')
        if task['type']=='quiz':
            try:choice=int(answer)
            except ValueError:raise HTTPException(422,'Выберите вариант ответа')
            if not 0<=choice<len(task['options']):raise HTTPException(422,'Неизвестный вариант')
            correct=choice==task['correct_index']
            result={'status':'graded','score':100 if correct else 0,'feedback':('Верно. ' if correct else 'Пока неверно. ')+task['expected'],
                    'correct_index':task['correct_index'],'mode':'deterministic'}
        elif config.AI_MODE=='demo':
            result={'status':'self_check','feedback':'Ответ сохранен. Подключите AI-провайдер для независимой проверки. Сравните свой ответ с опорным материалом.',
                    'reference':task['expected'],'rubric':task['rubric'],'analysis_only':True}
        else:
            if db.scalar(select(Job.id).where(Job.course_id==c.id,Job.state.in_(jobs.ACTIVE))):raise HTTPException(409,'Дождитесь текущей AI-операции')
            result={'status':'pending','feedback':'Ответ сохранен, ожидается проверка.'}
        a=Attempt(lesson_id=lid,task_id=tid,answer=answer,result=result);db.add(a);db.flush()
        jobs.update_progress(db,l)
        if result['status']=='pending':
            j=Job(course_id=c.id,key=uid(),kind='assessment',target=a.id,course_version=c.version);db.add(j);db.flush()
            job_result=jobs.describe(j)
        else:job_result=None
        db.commit();return {'id':a.id,'result':result,'job':job_result,'completed':l.completed}

@app.get('/api/courses/{cid}/exam')
def get_exam(cid:str,auth=Depends(user_session),db=Depends(db_session)):
    c=own_course(db,cid,auth[0]);summary=course_summary(db,c)
    exam=db.scalar(select(Exam).where(Exam.course_id==cid).order_by(Exam.created.desc()))
    if not exam:return {'course_id':cid,'eligible':summary['total']>0 and summary['completed']==summary['total'],'weaknesses':exams.weaknesses(db,cid),'exam':None}
    content=dict(exam.content)
    if content:content['items']=[{k:v for k,v in t.items() if k not in ('correct_index','expected','rubric')} for t in content['items']]
    return {'course_id':cid,'eligible':summary['total']>0 and summary['completed']==summary['total'],
        'weaknesses':exams.weaknesses(db,cid),
        'exam':{'id':exam.id,'blueprint':exam.blueprint,'content':content,
                'attempts':[{'id':a.id,'result':a.result,'created':a.created} for a in db.scalars(select(ExamAttempt).where(ExamAttempt.exam_id==exam.id).order_by(ExamAttempt.created.desc()))]},
        'jobs':[jobs.describe(j) for j in db.scalars(select(Job).where(Job.course_id==cid,Job.kind=='exam',Job.target==exam.id).order_by(Job.created.desc()))]}

@app.post('/api/courses/{cid}/exam',status_code=202)
def create_exam(cid:str,auth=Depends(user_session),db=Depends(db_session)):
    with mutation_lock:
        c=own_course(db,cid,auth[0]);summary=course_summary(db,c)
        if config.AI_MODE=='demo':raise HTTPException(409,'Для итогового теста запустите START.bat с локальной моделью')
        if not summary['total'] or summary['completed']!=summary['total']:raise HTTPException(409,'Сначала завершите все темы курса')
        if summary['active_jobs']:raise HTTPException(409,'Дождитесь текущей обработки')
        latest=db.scalar(select(Exam).where(Exam.course_id==cid).order_by(Exam.created.desc()))
        if latest and not db.scalar(select(ExamAttempt.id).where(ExamAttempt.exam_id==latest.id)):
            if latest.content:return {'exam_id':latest.id,'ready':True}
            return enqueue(db,c,'exam',latest.id)
        e=Exam(course_id=cid);db.add(e);db.flush();e.blueprint=exams.blueprint(db,cid,e.id)
        db.commit();return enqueue(db,c,'exam',e.id)

@app.post('/api/exams/{eid}/attempts')
def submit_exam(eid:str,data:ExamAnswers,auth=Depends(user_session),db=Depends(db_session)):
    with mutation_lock:
        e=db.get(Exam,eid)
        if not e:raise HTTPException(404,'Тест не найден')
        c=own_course(db,e.course_id,auth[0])
        if not e.content:raise HTTPException(409,'Дождитесь подготовки теста')
        try:result=exams.grade(e,data.answers)
        except ValueError as error:raise HTTPException(422,str(error))
        a=ExamAttempt(exam_id=eid,answers=data.answers,result=result);db.add(a);db.commit()
        return {'id':a.id,'result':result}

@app.get('/api/courses/{cid}/answers')
def answers(cid:str,auth=Depends(user_session),db=Depends(db_session)):
    c=own_course(db,cid,auth[0]);out=[]
    lessons=db.scalars(select(Lesson).where(Lesson.course_id==cid).order_by(Lesson.position)).all()
    for q in c.questions:
        related=[l for l in lessons if q['id'] in l.topic['question_ids']]
        prepared=[{**a,'lesson_id':l.id,'mode':l.content.get('mode')} for l in related for a in l.content.get('answers',[]) if a['question_id']==q['id']]
        out.append({**q,'answers':prepared,'lessons':[{'id':l.id,'title':l.topic['title'],'completed':l.completed} for l in related]})
    return {'title':c.title,'questions':out}

@app.get('/api/courses/{cid}/runs')
def runs(cid:str,auth=Depends(user_session),db=Depends(db_session)):
    own_course(db,cid,auth[0]);rows=db.execute(select(Run,Job.kind).join(Job,Run.job_id==Job.id).where(Job.course_id==cid).order_by(Run.created.desc()).limit(150)).all()
    return [{'id':r.id,'job_id':r.job_id,'kind':kind,'role':r.role,'revision':r.revision,'payload':r.payload,'created':r.created} for r,kind in rows]

LEVEL_MINUTES={'beginner':45,'basic':30,'revision':20}

def remaining_topics(db,c,level):
    lessons=db.scalars(select(Lesson).where(Lesson.course_id==c.id).order_by(Lesson.position)).all()
    if c.status!='ready':
        return [],[{'id':q['id'],'title':q['text'],'minutes':LEVEL_MINUTES[level],'prerequisites':[]} for q in c.questions]
    topics=[]
    for l in lessons:
        if l.completed:continue
        t=dict(l.topic)
        base=t.get('base_minutes',t['minutes']);base_level=t.get('base_level',c.level)
        t.update(base_minutes=base,base_level=base_level,minutes=max(15,round(base*LEVEL_MINUTES[level]/LEVEL_MINUTES[base_level])))
        topics.append(t)
    ids={t['id'] for t in topics}
    return lessons,[{**t,'prerequisites':[x for x in t['prerequisites'] if x in ids]} for t in topics]

@app.post('/api/courses/{cid}/replan-preview')
def replan_preview(cid:str,data:ReplanInput,auth=Depends(user_session),db=Depends(db_session)):
    c=own_course(db,cid,auth[0]);level=data.level or c.level
    _,topics=remaining_topics(db,c,level)
    learning=sum(t['minutes'] for t in topics);required=learning+(learning+3)//4
    available=budget(data.model_dump(mode='json',exclude={'level'}))['total_minutes']
    return {'level':level,'required_minutes':required,'available_minutes':available,'fits':required<=available,
            'estimated':True,'remaining_topics':len(topics),
            'note':'Предварительная оценка с резервом 25% на повторение. Смена уровня меняет оценку времени; она не подтверждает знания. Готовые уроки сохраняются, новые учитывают выбранный уровень.'}

@app.post('/api/courses/{cid}/replan')
def replan(cid:str,data:ReplanInput,auth=Depends(user_session),db=Depends(db_session)):
    with mutation_lock:
        c=own_course(db,cid,auth[0])
        if db.scalar(select(Job.id).where(Job.course_id==cid,Job.state.in_(jobs.ACTIVE))):raise HTTPException(409,'Дождитесь текущей обработки')
        schedule=data.model_dump(mode='json',exclude={'level'});level=data.level or c.level
        lessons,remaining=remaining_topics(db,c,level)
        plan=None
        if c.status=='ready':
            try:plan=allocate(remaining,schedule)
            except InsufficientTime as e:raise HTTPException(422,str(e))
        c.history=(c.history+[{'version':c.version,'level':c.level,'schedule':c.schedule,'plan':c.plan,'saved_at':now()}])[-20:]
        if plan is not None:
            by_id={t['id']:t for t in remaining}
            for l in lessons:
                if not l.completed:l.topic=by_id[l.topic['id']]
            c.plan={**plan,'mode':c.plan.get('mode',config.AI_MODE)}
        c.schedule=schedule;c.level=level;c.version+=1;db.commit()
        return course_summary(db,c)

@app.post('/api/attempts/{aid}/self-check')
def confirm_self_check(aid:str,auth=Depends(user_session),db=Depends(db_session)):
    a=db.get(Attempt,aid)
    if not a:raise HTTPException(404,'Ответ не найден')
    l,c=own_lesson(db,a.lesson_id,auth[0])
    if a.result.get('status') not in ('self_check','self_checked'):raise HTTPException(409,'Для этого ответа самопроверка недоступна')
    a.result={**a.result,'status':'self_checked','feedback':'Вы подтвердили сверку ответа с критериями. Это самостоятельное прохождение, без AI-оценки.'}
    db.flush();jobs.update_progress(db,l);db.commit()
    return {'completed':l.completed,'result':a.result}

@app.post('/api/courses/{cid}/repair-copy',status_code=201)
def repair_copy(cid:str,auth=Depends(user_session),db=Depends(db_session)):
    with mutation_lock:
        original=own_course(db,cid,auth[0])
        if db.scalar(select(Job.id).where(Job.course_id==cid,Job.state.in_(jobs.ACTIVE))):raise HTTPException(409,'Дождитесь текущей обработки')
        c=Course(user_id=auth[0].id,title=original.title[:140]+' · исправленная копия',level=original.level,schedule=original.schedule)
        paths=[];questions=[]
        try:
            db.add(c);db.flush()
            for d in db.scalars(select(Document).where(Document.course_id==cid)):
                raw=(config.UPLOADS/d.path).read_bytes();text,chunks=extract(d.name,raw)
                did=uid();path=config.UPLOADS/(did+Path(d.name).suffix.lower());path.write_bytes(raw);paths.append(path)
                db.add(Document(id=did,course_id=c.id,name=d.name,role=d.role,sha=d.sha,path=path.name,text=text));db.flush()
                for loc,piece in chunks:db.add(Chunk(document_id=did,course_id=c.id,locator=loc,text=piece))
                if d.role=='questions':questions.extend(extract_questions(d.name,raw,text))
            if not questions:questions=[q['text'] for q in original.questions if not is_heading(q['text'])]
            c.questions=[{'id':uid(),'text':q,'number':i+1} for i,q in enumerate(dict.fromkeys(questions))][:100]
            db.commit()
        except Exception as e:
            db.rollback()
            for path in paths:path.unlink(missing_ok=True)
            raise HTTPException(422,'Не удалось перечитать исходные файлы. Загрузите их в новый курс.') from e
        return course_summary(db,c)

@app.post('/api/courses/{cid}/upgrade-ai',status_code=202)
def upgrade_ai(cid:str,auth=Depends(user_session),db=Depends(db_session)):
    with mutation_lock:
        original=own_course(db,cid,auth[0])
        if config.AI_MODE=='demo':raise HTTPException(409,'Запустите приложение с локальной моделью')
        prior=next((x.get('ai_copy_id') for x in reversed(original.history) if x.get('ai_copy_id')),None)
        if prior and db.get(Course,prior):return {'id':prior,'existing':True}
        result=repair_copy(cid,auth,db);copy=db.get(Course,result['id'])
        if not copy.questions:raise HTTPException(422,'В исходных файлах не найдены контрольные вопросы')
        original.history=(original.history+[{'ai_copy_id':copy.id,'saved_at':now()}])[-20:];db.commit()
        job=enqueue(db,copy,'plan');return {'id':copy.id,'job':job}

@app.delete('/api/courses/{cid}')
def delete_course(cid:str,auth=Depends(user_session),db=Depends(db_session)):
    with mutation_lock:
        c=own_course(db,cid,auth[0])
        if db.scalar(select(Job.id).where(Job.course_id==cid,Job.state.in_(jobs.ACTIVE))):raise HTTPException(409,'Сначала остановите текущие задания')
        paths=[config.UPLOADS/d.path for d in db.scalars(select(Document).where(Document.course_id==cid))]
        db.delete(c);db.commit()
        for p in paths:p.unlink(missing_ok=True)
        return {'ok':True}

@app.post('/api/demo',status_code=201)
def demo_course(auth=Depends(user_session),db=Depends(db_session)):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    with mutation_lock:
        c=Course(user_id=auth[0].id,title='Основы Python',level='beginner',
            schedule={'start':datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat(),'duration':'1m','days':{'1':45,'3':45,'5':60}},
            questions=[{'id':uid(),'number':i+1,'text':q} for i,q in enumerate([
                'Переменные и типы данных в Python','Условия и логические выражения','Циклы for и while','Функции: параметры и возвращаемое значение'])])
        db.add(c);db.flush()
        raw=(config.ROOT/'examples'/'python-methodology.txt').read_bytes();text,chunks=extract('python-methodology.txt',raw)
        did=uid();path=config.UPLOADS/(did+'.txt');path.write_bytes(raw)
        db.add(Document(id=did,course_id=c.id,name='Краткая методичка Python.txt',role='methodology',sha=hashlib.sha256(raw).hexdigest(),path=path.name,text=text));db.flush()
        for loc,piece in chunks:db.add(Chunk(document_id=did,course_id=c.id,locator=loc,text=piece))
        db.commit();job=enqueue(db,c,'plan');return {'id':c.id,'job':job}

app.mount('/assets',StaticFiles(directory=config.ROOT/'frontend'),name='assets')
@app.get('/',include_in_schema=False)
def index():return FileResponse(config.ROOT/'frontend'/'index.html')
