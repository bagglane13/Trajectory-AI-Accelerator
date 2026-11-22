"""Small explicit teaching examples. Never manufacture quizzes from document lines."""
import re

def exercise(title, subject=""):
    t=title.lower()
    if 'структур' in t and 'html' in t:
        return {
            'explanation':'HTML-документ организован в элементы. Элемент html содержит head со служебными сведениями и body с содержимым страницы. Теги обозначают начало и конец элемента; атрибуты задают дополнительные параметры. Например, в <a href="lesson.html">Урок</a> атрибут href указывает адрес ссылки. Название вкладки задается элементом title внутри head.',
            'code':'<html>\n  <head>\n    <title>Моя первая страница</title>\n  </head>\n  <body>\n    <h1>Привет!</h1>\n    <a href="lesson.html">Перейти к уроку</a>\n  </body>\n</html>',
            'prompt':'В каком разделе HTML-документа нужно разместить заголовок <h1>, который пользователь увидит на странице?',
            'options':['В body — это содержимое страницы','В head — рядом с названием вкладки','В атрибуте href ссылки'],
            'expected':'Заголовок h1 размещают в body. Head содержит служебные сведения; href задает адрес ссылки.',
            'practice':'Напишите HTML-документ с названием вкладки «Моя страница», видимым заголовком «Обо мне» и ссылкой на about.html. Объясните назначение head, body и href.',
            'rubric':'Есть html, head с title и body; h1 находится в body; ссылка использует href="about.html"; объяснено различие заголовка вкладки и заголовка страницы.'}
    if 'переменн' in t and 'python' in (t+' '+subject.lower()):
        return {'explanation':'Переменная в Python — имя, связанное с объектом. Тип влияет на результат операции: числа складываются, а строки объединяются.',
            'code':'a = "2"\nb = "3"\nprint(a + b)',
            'prompt':'Что выведет Python: print("2" + "3")?', 'options':['23 — объединение строк','5 — сложение чисел','Возникнет ошибка при любом сложении строк'],
            'expected':'Получится строка 23: оба операнда являются строками.',
            'practice':'Напишите код, который читает возраст через input(), преобразует его в число и выводит возраст через год. Объясните необходимость преобразования.',
            'rubric':'Есть input(), преобразование int(), прибавление 1 и объяснение того, что input возвращает строку.'}
    return None

def lesson(context):
    ss=context['sources'];qs=context['questions'];title=context['topic']['title']
    ex=exercise(title, context.get("subject", ""))
    reference='\n\n'.join(s['text'] for s in ss[:2])[:5000]
    practice=(ex['practice'] if ex else f'По теме «{title}» объясните основные понятия своими словами. Приведите небольшой пример кода или разметки и разберите, как он работает. Если в предложенных фрагментах нет нужной информации, явно укажите, чего не хватает.')
    rubric=ex['rubric'] if ex else 'Раскрыты понятия темы; приведен связанный с темой пример; объяснены его части; отмечены пробелы источника. Это критерии самопроверки, а не автоматическая оценка.'
    tasks=[]
    if ex:
        tasks.append({'id':'quiz-1','type':'quiz','prompt':ex['prompt'],'options':ex['options'],'correct_index':0,'expected':ex['expected'],'rubric':'Понимание назначения конструкций в примере.','required':True})
    tasks.append({'id':'text-1','type':'text','prompt':practice,'options':[],'correct_index':0,
        'expected':(ex['rubric'] if ex else 'Сверьте ответ с критериями и материалами урока. Готового проверенного ответа в офлайн-режиме нет.'),
        'rubric':rubric,'required':not bool(ex)})
    blocks=[]
    if ex:blocks.append({'title':'Учебный пример из встроенного демонабора','text':ex['explanation'],'code':ex['code']})
    blocks += [{'title':'Исходный материал · '+s['locator'],'text':s['text'],'code':''} for s in ss[:2]]
    return {'intro':'Офлайн-режим: учебный пример (если есть в демонаборе), найденные фрагменты и содержательная самопроверка. Это не AI-проверка знаний. Для персональной теории и оценивания подключите AI-провайдер.',
        'blocks':blocks,'tasks':tasks,
        'answers':[{'question_id':q['id'],'short':'Материал для самостоятельной подготовки; готовность ответа нужно проверить.', 'full':reference,'source_ids':[s['id'] for s in ss[:2]]} for q in qs],
        'source_ids':[s['id'] for s in ss[:2]]}

def validate_practice(result):
    for task in result['tasks']:
        prompt=task['prompt'].strip()
        if re.search(r'какое утверждение взято|вопросы для самоконтроля по дисциплине',prompt,re.I):
            raise ValueError('Задание должно проверять понятие или применение, а не заголовок документа или случайную цитату')
        if task['type']=='quiz':
            options=[x.strip() for x in task['options']]
            if any(re.fullmatch(r'[\W\d_]+',x) for x in options):
                raise ValueError('Вариант ответа из одних цифр/символов недопустим: добавьте смысловое объяснение')
            if len(set(x.lower() for x in options))!=len(options):raise ValueError('Варианты теста повторяются')
