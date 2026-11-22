from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, model_validator

class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default='Студент', min_length=1, max_length=80)

class Schedule(BaseModel):
    start: date
    duration: Literal['15d','1m','2m','3m','6m','12m'] = '1m'
    days: dict[str, int]
    @model_validator(mode='after')
    def valid_days(self):
        if not self.days or any(k not in '1234567' or len(k)!=1 or not 15 <= v <= 240 for k,v in self.days.items()):
            raise ValueError('Выберите дни недели и от 15 до 240 минут на каждый день')
        if not 2020 <= self.start.year <= 2100:
            raise ValueError('Дата начала должна быть между 2020 и 2100 годом')
        return self

class CourseInput(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    level: Literal['beginner','basic','revision'] = 'beginner'
    schedule: Schedule

class QuestionsInput(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=100)
    @model_validator(mode='after')
    def clean(self):
        self.questions = list(dict.fromkeys(q.strip() for q in self.questions if q.strip()))
        if not self.questions or any(len(q)>2000 for q in self.questions):
            raise ValueError('Нужны вопросы длиной до 2000 символов')
        return self

class Topic(BaseModel):
    id: str = Field(min_length=1, max_length=50, pattern=r'^[A-Za-z0-9_-]+$')
    title: str = Field(min_length=2, max_length=200)
    objective: str = Field(min_length=5, max_length=2000)
    minutes: int = Field(ge=15, le=600)
    prerequisites: list[str] = Field(default_factory=list, max_length=50)
    question_ids: list[str] = Field(min_length=1, max_length=100)
    source_ids: list[str] = Field(min_length=1, max_length=12)

class PlanOutput(BaseModel):
    topics: list[Topic] = Field(min_length=1, max_length=100)

class TheoryBlock(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=10, max_length=12000)
    code: str = Field(default='', max_length=6000)

class Task(BaseModel):
    id: str = Field(min_length=1, max_length=50, pattern=r'^[A-Za-z0-9_-]+$')
    type: Literal['quiz','text','code']
    prompt: str = Field(min_length=5, max_length=4000)
    options: list[str] = Field(default_factory=list, max_length=6)
    correct_index: int = 0
    expected: str = Field(min_length=3, max_length=6000)
    rubric: str = Field(min_length=3, max_length=2000)
    required: bool = True
    @model_validator(mode='after')
    def quiz_valid(self):
        if self.type=='quiz' and (len(self.options)<2 or not 0<=self.correct_index<len(self.options)):
            raise ValueError('Некорректные варианты теста')
        return self

class Answer(BaseModel):
    question_id: str
    short: str = Field(min_length=5, max_length=3000)
    full: str = Field(min_length=10, max_length=10000)
    source_ids: list[str] = Field(min_length=1)

class QuizTask(Task):
    type: Literal['quiz'] = 'quiz'
    options: list[str] = Field(min_length=3, max_length=3)
    correct_index: int = Field(ge=0, le=2)

class OpenTask(Task):
    type: Literal['text','code']

class LessonOutput(BaseModel):
    intro: str = Field(min_length=10, max_length=3000)
    blocks: list[TheoryBlock] = Field(min_length=1, max_length=10)
    tasks: list[QuizTask | OpenTask] = Field(min_length=1, max_length=6)
    answers: list[Answer] = Field(min_length=1, max_length=100)
    source_ids: list[str] = Field(min_length=1, max_length=12)

class LocalLessonOutput(BaseModel):
    intro: str = Field(min_length=10, max_length=3000)
    blocks: list[TheoryBlock] = Field(min_length=1, max_length=5)
    quiz: QuizTask
    practice: OpenTask
    answers: list[Answer] = Field(min_length=1, max_length=100)
    source_ids: list[str] = Field(min_length=1, max_length=12)

class Assessment(BaseModel):
    score: int = Field(ge=0, le=100)
    feedback: str = Field(min_length=5, max_length=5000)
    improvements: list[str] = Field(default_factory=list, max_length=10)

class Review(BaseModel):
    status: Literal['approved','revise','insufficient_evidence']
    issues: list[str] = Field(default_factory=list, max_length=20)
    @model_validator(mode='after')
    def issues_valid(self):
        if self.status!='approved' and not self.issues:
            raise ValueError('Проверяющий должен описать замечания')
        if self.status=='approved' and self.issues:
            raise ValueError('Одобренный результат не должен содержать замечаний')
        return self

class AttemptInput(BaseModel):
    answer: str = Field(min_length=1, max_length=12000)

class ReplanInput(Schedule):
    level: Literal['beginner','basic','revision'] | None = None

class ExamQuestion(QuizTask):
    type: Literal['quiz'] = 'quiz'
    lesson_id: str
    source_ids: list[str] = Field(min_length=1, max_length=4)

class ExamOutput(BaseModel):
    items: list[ExamQuestion] = Field(min_length=1, max_length=10)

class ExamAnswers(BaseModel):
    answers: dict[str,int] = Field(min_length=1,max_length=10)
