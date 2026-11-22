"""A repeated exam question must not outrank the lesson explaining it."""
from app import agents, config
from app.db import Chunk, Course, Document, Job, Session, uid
from app.materials import is_question_list, retrieve


QUESTION_LIST='''28. Модель DOM. Уровни. Структура документа.
29. DOM. Навигация по дереву документа.
30. DOM. Редактирование дерева элементов.
31. DOM. Массивы элементов.
32. Библиотека jQuery.
33. Создание элементов DOM.
Для самостоятельного изучения
34. Системы управления контентом.
35. Классификация CMS.'''


def course_with_sources(client,parts):
    course=client.post('/api/courses',json={'title':'WEB-программирование','level':'basic',
        'schedule':{'start':'2026-11-02','duration':'1m','days':{'1':60,'3':60,'5':60}}}).json()
    cid=course['id']
    client.put('/api/courses/'+cid+'/questions',json={'questions':['Модель DOM. Уровни. Структура документа.']})
    with Session.begin() as db:
        document=Document(id=uid(),course_id=cid,name='Авторские учебные примеры.txt',role='methodology',
            sha=uid()*2,path='example.txt',text='\n\n'.join(text for _,text in parts))
        db.add(document);db.flush()
        for locator,text in parts:db.add(Chunk(id=uid(),course_id=cid,document_id=document.id,locator=locator,text=text))
    return cid


def test_dom_explanation_beats_repeated_question_list(client,monkeypatch):
    monkeypatch.setattr(config,'AI_MODE','ollama')
    cid=course_with_sources(client,[('Страница 7',QUESTION_LIST),('Страница 45',
        'Модель DOM — интерфейс для работы с документом. Структура DOM — дерево узлов. '
        'Уровни DOM описывают развитие стандарта. Документ содержит элементы, атрибуты и текст.'),
        ('Страница 46','Навигация DOM использует связи parentNode и childNodes. Пример: document.body;')])
    with Session() as db:
        result=retrieve(db,cid,'Модель DOM. Уровни. Структура документа.')
        assert result[0]['locator']=='Страница 45'
        assert 'Страница 7' not in {x['locator'] for x in result}
        context=agents.context_for(db,db.get(Course,cid),Job(kind='plan'))
        assert len(context['sources'])==1
        assert context['sources'][0]['locator']=='Страница 45'


def test_question_list_alone_is_not_evidence(client):
    cid=course_with_sources(client,[('Страница 7',QUESTION_LIST)])
    with Session() as db:assert retrieve(db,cid,'Модель DOM. Уровни. Структура документа.')==[]


def test_numbered_explanations_and_code_remain_usable():
    assert is_question_list(QUESTION_LIST)
    assert is_question_list('Вопросы к зачету\n1. Назначение HTML.\n2. Модель DOM.')
    assert not is_question_list('Модель DOM\nУровень 1 вводит понятие узла.\nУровень 2 расширяет интерфейс.')
    assert not is_question_list('''1. Найдите узел: const node = document.body;
2. Создайте элемент: const item = document.createElement("p");
3. Заполните элемент: item.textContent = "Пример";
4. Добавьте элемент: node.appendChild(item);''')
    assert not is_question_list('''1. Откройте страницу в браузере.
2. Найдите нужный заголовок на странице.
3. Выберите элемент мышью.
4. Проверьте текст элемента.''')
    assert not is_question_list('''1. DOM — представление документа в виде дерева.
2. Элемент — узел с именем тега и дочерними узлами.
3. Атрибут — свойство элемента.
4. Текстовый узел — содержимое текста документа.''')
