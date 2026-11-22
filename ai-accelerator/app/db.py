import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, event, String, Text, Integer, Float, Boolean, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import DATABASE_URL

def uid(): return uuid.uuid4().hex
def now(): return datetime.now(timezone.utc).timestamp()

engine = create_engine(DATABASE_URL, pool_pre_ping=True,
    connect_args={'check_same_thread': False, 'timeout': 30})

@event.listens_for(engine, 'connect')
def sqlite_config(dbapi_connection, _):
    dbapi_connection.execute('PRAGMA foreign_keys=ON')
    dbapi_connection.execute('PRAGMA journal_mode=WAL')

Session = sessionmaker(engine, expire_on_commit=False)
class Base(DeclarativeBase): pass
class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    password: Mapped[str] = mapped_column(String(255))
    created: Mapped[float] = mapped_column(Float, default=now)
class LoginSession(Base):
    __tablename__ = 'sessions'
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)
class Course(Base):
    __tablename__ = 'courses'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    title: Mapped[str] = mapped_column(String(160))
    level: Mapped[str] = mapped_column(String(30), default='beginner')
    schedule: Mapped[dict] = mapped_column(JSON)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    history: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default='draft')
    version: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[float] = mapped_column(Float, default=now)
class Document(Base):
    __tablename__ = 'documents'
    __table_args__ = (UniqueConstraint('course_id','sha','role'),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey('courses.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    sha: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
class Chunk(Base):
    __tablename__ = 'chunks'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id', ondelete='CASCADE'))
    course_id: Mapped[str] = mapped_column(ForeignKey('courses.id', ondelete='CASCADE'), index=True)
    locator: Mapped[str] = mapped_column(String(160))
    text: Mapped[str] = mapped_column(Text)
class Lesson(Base):
    __tablename__ = 'lessons'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey('courses.id', ondelete='CASCADE'), index=True)
    topic: Mapped[dict] = mapped_column(JSON)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    theory_read: Mapped[bool] = mapped_column(Boolean, default=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
class Attempt(Base):
    __tablename__ = 'attempts'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    lesson_id: Mapped[str] = mapped_column(ForeignKey('lessons.id', ondelete='CASCADE'), index=True)
    task_id: Mapped[str] = mapped_column(String(50))
    answer: Mapped[str] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created: Mapped[float] = mapped_column(Float, default=now)
class Job(Base):
    __tablename__ = 'jobs'
    __table_args__ = (UniqueConstraint('course_id','key'),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey('courses.id', ondelete='CASCADE'), index=True)
    key: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    target: Mapped[str] = mapped_column(String(32), default='')
    state: Mapped[str] = mapped_column(String(30), default='queued', index=True)
    stage: Mapped[str] = mapped_column(String(40), default='Ожидание')
    revision: Mapped[int] = mapped_column(Integer, default=0)
    course_version: Mapped[int] = mapped_column(Integer)
    token: Mapped[str] = mapped_column(String(64), default='')
    candidate: Mapped[dict] = mapped_column(JSON, default=dict)
    review: Mapped[dict] = mapped_column(JSON, default=dict)
    feedback: Mapped[list] = mapped_column(JSON, default=list)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default='')
    created: Mapped[float] = mapped_column(Float, default=now)
    heartbeat: Mapped[float] = mapped_column(Float, default=now)
class Run(Base):
    __tablename__ = 'agent_runs'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey('jobs.id', ondelete='CASCADE'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    created: Mapped[float] = mapped_column(Float, default=now)

class Exam(Base):
    __tablename__ = 'final_exams'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey('courses.id', ondelete='CASCADE'), index=True)
    blueprint: Mapped[list] = mapped_column(JSON, default=list)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    created: Mapped[float] = mapped_column(Float, default=now)

class ExamAttempt(Base):
    __tablename__ = 'final_exam_attempts'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    exam_id: Mapped[str] = mapped_column(ForeignKey('final_exams.id', ondelete='CASCADE'), index=True)
    answers: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created: Mapped[float] = mapped_column(Float, default=now)
