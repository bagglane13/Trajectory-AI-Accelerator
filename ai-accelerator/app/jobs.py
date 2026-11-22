import hashlib, secrets, threading, logging
from sqlalchemy import select, update
from .db import Session, Course, Job, Run, Lesson, Attempt, Exam, now, uid
from . import agents, config, providers
from .planner import allocate, order_topics, InsufficientTime

log=logging.getLogger('accelerator')
ACTIVE=('queued','running')
TERMINAL=('completed','needs_input','needs_review','failed','interrupted')

def describe(j):
    return {'id':j.id,'kind':j.kind,'target':j.target,'state':j.state,'stage':j.stage,
            'revision':j.revision,'error':j.error,'created':j.created,'review':j.review}

def claim(job_id):
    token=secrets.token_hex(32)
    with Session.begin() as db:
        result=db.execute(update(Job).where(Job.id==job_id,Job.state=='queued').values(
            state='running',stage='Подбор материалов',token=hashlib.sha256(token.encode()).hexdigest(),heartbeat=now()))
        if not result.rowcount:return {'job_id':job_id,'claimed':False}
    return {'job_id':job_id,'token':token,'claimed':True}

def owned_job(db,job_id,token):
    j=db.get(Job,job_id)
    if not j or j.state!='running' or not secrets.compare_digest(j.token,hashlib.sha256(token.encode()).hexdigest()):
        raise ValueError('Задание уже завершено или токен исполнения устарел')
    c=db.get(Course,j.course_id)
    if c.version!=j.course_version:raise ValueError('Версия курса изменилась. Создайте новое задание.')
    return j,c

def log_run(db,j,role,payload):
    db.add(Run(job_id=j.id,revision=j.revision,role=role,payload={
        'mode':config.AI_MODE,'model':providers.model_name(),
        'prompt_version':'1.1',**payload}))

def fail(job_id,message,state='failed'):
    with Session.begin() as db:
        j=db.get(Job,job_id)
        if j and j.state in ACTIVE:
            j.state=state;j.error=message;j.stage='Нужны изменения' if state=='needs_input' else 'Остановлено';j.heartbeat=now()
            if j.kind=='assessment':
                a=db.get(Attempt,j.target)
                if a:a.result={'status':state,'feedback':message}

def generate_step(job_id,token):
    try:
        with Session.begin() as db:
            j,c=owned_job(db,job_id,token)
            if j.stage not in ('Подбор материалов','Исправление'):raise ValueError('Генерация уже выполнялась на этом шаге')
            j.revision+=1
            if j.revision>3:raise ValueError('Исчерпан лимит исправлений')
            j.stage='Генерация';j.heartbeat=now();j.review={};j.candidate={}
            ctx=agents.context_for(db,c,j)
            if not ctx['sources']:raise ValueError('Нет методических материалов для поиска')
            j.sources=ctx['sources']
            log_run(db,j,'search_materials',{'sources':[{'id':x['id'],'locator':x['locator']} for x in ctx['sources']]})
        # Network I/O happens outside a write transaction.
        try:
            with Session() as db:
                j,c=owned_job(db,job_id,token)
                draft=agents.generate(db,c,j,ctx)
                candidate=agents.validate(draft,j,ctx,c)
            validation=[]
        except InsufficientTime as e:
            fail(job_id,str(e),'needs_input')
            return {'job_id':job_id,'token':token,'stop':True,'approved':False,'retry':False}
        except Exception as e:
            candidate=draft if isinstance(locals().get('draft'),dict) else {};validation=[str(e)[:1200]]
        with Session.begin() as db:
            j,c=owned_job(db,job_id,token)
            j.candidate=candidate;j.feedback=validation;j.stage='Проверка';j.heartbeat=now()
            log_run(db,j,'CourseAgent',{'candidate':candidate,'validation_errors':validation})
        return {'job_id':job_id,'token':token,'stop':False}
    except Exception as e:
        fail(job_id,str(e)[:1500]);return {'job_id':job_id,'token':token,'stop':True,'approved':False,'retry':False}

def review_step(job_id,token):
    try:
        with Session() as db:
            j,c=owned_job(db,job_id,token)
            if j.stage!='Проверка':raise ValueError('Нет результата для проверки')
            ctx=agents.context_for(db,c,j);ctx['sources']=j.sources
            if j.feedback:result={'status':'revise','issues':j.feedback,'check_type':'programmatic'}
            else:
                try:
                    result=agents.review(j.candidate,j,ctx)
                    result['check_type']='programmatic' if config.AI_MODE=='demo' else 'ai'
                except Exception as e:result={'status':'revise','issues':['Ошибка проверяющего: '+str(e)[:1000]],'check_type':'ai_error'}
        with Session.begin() as db:
            j,c=owned_job(db,job_id,token)
            j.review=result;j.feedback=result['issues'];j.heartbeat=now()
            log_run(db,j,'ReviewerAgent',result)
            approved=result['status']=='approved'
            retry=result['status']=='revise' and j.revision<3
            j.stage='Сохранение' if approved else ('Исправление' if retry else 'Завершение проверки')
        return {'job_id':job_id,'token':token,'approved':approved,'retry':retry,'stop':False}
    except Exception as e:
        fail(job_id,str(e)[:1500]);return {'job_id':job_id,'token':token,'stop':True,'approved':False,'retry':False}

def update_progress(db,lesson):
    tasks=lesson.content.get('tasks',[])
    required={t['id'] for t in tasks if t['required']}
    passed={a.task_id for a in db.scalars(select(Attempt).where(Attempt.lesson_id==lesson.id))
        if (a.result.get('status')=='graded' and a.result.get('score',0)>=70) or a.result.get('status')=='self_checked'}
    lesson.completed=bool(lesson.content and lesson.theory_read and required.issubset(passed))

def finish_step(job_id,token):
    try:
        with Session.begin() as db:
            j,c=owned_job(db,job_id,token)
            if j.stage not in ('Сохранение','Завершение проверки'):raise ValueError('Проверка результата еще не завершена')
            if j.review.get('status')!='approved':
                j.state='needs_input' if j.review.get('status')=='insufficient_evidence' else 'needs_review'
                j.error='; '.join(j.feedback);j.stage='Не прошло проверку'
                if j.kind=='assessment':db.get(Attempt,j.target).result={'status':j.state,'feedback':j.error}
                return {'job_id':job_id,'state':j.state}
            ctx=agents.context_for(db,c,j);ctx['sources']=j.sources
            result=agents.validate(j.candidate,j,ctx,c)
            if j.kind=='plan':
                if db.scalar(select(Lesson.id).where(Lesson.course_id==c.id).limit(1)):
                    raise ValueError('План уже создан. Используйте перепланирование оставшихся занятий.')
                topics=order_topics(result['topics']);mapping={t['id']:uid() for t in topics}
                for i,t in enumerate(topics):
                    t={**t,'id':mapping[t['id']],'prerequisites':[mapping[x] for x in t['prerequisites']]}
                    db.add(Lesson(id=t['id'],course_id=c.id,position=i,topic=t))
                remapped=[{**t,'id':mapping[t['id']],'prerequisites':[mapping[x] for x in t['prerequisites']]} for t in topics]
                c.plan={**allocate(remapped,c.schedule),'mode':config.AI_MODE};c.status='ready';c.version+=1
            elif j.kind=='lesson':
                l=db.get(Lesson,j.target)
                l.content={**result,'mode':config.AI_MODE,'generated_at':now()}
            elif j.kind=='exam':
                db.get(Exam,j.target).content={**result,'mode':config.AI_MODE,'generated_at':now()}
            else:
                a=db.get(Attempt,j.target)
                a.result={'status':'graded',**result,'analysis_only':True,'mode':config.AI_MODE}
                db.flush();update_progress(db,db.get(Lesson,a.lesson_id))
            j.state='completed';j.stage='Готово';j.heartbeat=now()
        return {'job_id':job_id,'state':'completed'}
    except Exception as e:
        fail(job_id,str(e)[:1500]);return {'job_id':job_id,'state':'failed'}

def local_execute(job_id):
    claim_result=claim(job_id)
    if not claim_result['claimed']:return
    token=claim_result['token']
    for _ in range(3):
        g=generate_step(job_id,token)
        if g['stop']:return
        r=review_step(job_id,token)
        if r['stop']:return
        if not r['retry']:
            finish_step(job_id,token);return

def recover_stale():
    with Session() as db:
        ids=db.scalars(select(Job.id).where(Job.state=='running',Job.heartbeat<now()-900)).all()
    for jid in ids:fail(jid,'Исполнение прервано или превысило 15 минут без обновления. Нажмите «Повторить».','interrupted')

def worker(stop):
    while not stop.is_set():
        try:
            recover_stale()
            with Session() as db:
                # One active model job per local instance.
                running=db.scalar(select(Job.id).where(Job.state=='running').limit(1))
                jid=None if running else db.scalar(select(Job.id).where(Job.state=='queued').order_by(Job.created).limit(1))
            if jid:local_execute(jid)
        except Exception:
            log.exception('Worker error')
        stop.wait(1)

def start_worker():
    stop=threading.Event()
    thread=threading.Thread(target=worker,args=(stop,),daemon=True);thread.start()
    return stop,thread
