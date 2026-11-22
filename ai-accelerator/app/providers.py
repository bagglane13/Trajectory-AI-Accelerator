"""Gemini's native API and a keyless local Ollama adapter. No extra SDKs required."""
import json
import re
import time
import httpx
from . import config

LABELS={'demo':'Деморежим','yandex':'Yandex AI','gemini':'Gemini AI','ollama':'Локальная AI · Ollama'}


def model_name():
    return {'demo':'demo-template','yandex':config.YANDEX_MODEL,
            'gemini':config.GEMINI_MODEL,'ollama':config.OLLAMA_MODEL}.get(config.AI_MODE,'')


def configured():
    return {'demo':False,'yandex':bool(config.YANDEX_API_KEY and config.YANDEX_MODEL),
            'gemini':bool(config.GEMINI_API_KEY and config.GEMINI_MODEL),
            'ollama':bool(config.OLLAMA_URL and config.OLLAMA_MODEL)}.get(config.AI_MODE,False)


def parse_object(raw):
    raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw.strip())
    try:result=json.loads(raw)
    except (TypeError,json.JSONDecodeError) as e:raise ValueError('Модель вернула некорректный JSON. Попробуйте более короткую тему или другую модель.') from e
    if not isinstance(result,dict):raise ValueError('Модель должна вернуть JSON-объект')
    return result


def short_ids(data):
    aliases={}
    def encode(value):
        if isinstance(value,str) and re.fullmatch(r'[0-9a-f]{32}',value):
            if value not in aliases:aliases[value]='ref_'+str(len(aliases)+1)
            return aliases[value]
        if isinstance(value,list):return [encode(x) for x in value]
        if isinstance(value,dict):return {k:encode(v) for k,v in value.items()}
        return value
    return encode(data),{v:k for k,v in aliases.items()}


def restore_ids(data,reverse):
    if isinstance(data,str):return reverse.get(data,data)
    if isinstance(data,list):return [restore_ids(x,reverse) for x in data]
    if isinstance(data,dict):return {k:restore_ids(v,reverse) for k,v in data.items()}
    return data


def response_schema(schema,data):
    """Constrain reference fields to evidence actually supplied to this request.

    These constraints guide Ollama's structured decoder. The application still
    validates the returned references before a result can be published.
    """
    result=schema.model_json_schema()
    context=data.get('context',data)
    sources=list(dict.fromkeys(x['id'] for x in context.get('sources',[]) if isinstance(x,dict) and isinstance(x.get('id'),str)))
    questions=list(dict.fromkeys(x['id'] for x in context.get('questions',[]) if isinstance(x,dict) and isinstance(x.get('id'),str)))
    lessons=list(dict.fromkeys(x['lesson_id'] for x in context.get('items',[]) if isinstance(x,dict) and isinstance(x.get('lesson_id'),str)))
    def constrain(node):
        if not isinstance(node,dict):return
        properties=node.get('properties',{})
        if 'source_ids' in properties and sources:
            properties['source_ids']['items']={'type':'string','enum':sources}
            properties['source_ids']['description']='Только идентификаторы из sources этого запроса. Не номера страниц и не question_ids.'
        if 'question_ids' in properties and questions:
            properties['question_ids']['items']={'type':'string','enum':questions}
        if 'question_id' in properties and questions:
            properties['question_id'].update(type='string',enum=questions)
        if 'lesson_id' in properties and lessons:
            properties['lesson_id'].update(type='string',enum=lessons)
        for value in node.values():
            if isinstance(value,dict):constrain(value)
            elif isinstance(value,list):
                for item in value:constrain(item)
    constrain(result)
    return result


def call(system,data,schema):
    mode=config.AI_MODE
    reverse={}
    if mode=='ollama':data,reverse=short_ids(data)
    output_schema=response_schema(schema,data) if mode=='ollama' else schema.model_json_schema()
    prompt=json.dumps({'task':data,'json_schema':output_schema},ensure_ascii=False)
    if mode=='gemini':
        if not config.GEMINI_API_KEY:raise ValueError('Запустите connect-ai.bat и укажите свой Gemini API-ключ.')
        if not re.fullmatch(r'[a-zA-Z0-9._-]+',config.GEMINI_MODEL):raise ValueError('Некорректное имя модели Gemini')
        url=f'https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent'
        headers={'x-goog-api-key':config.GEMINI_API_KEY}
        body={'systemInstruction':{'parts':[{'text':system}]},
              'contents':[{'role':'user','parts':[{'text':prompt}]}],
              'generationConfig':{'temperature':0.2,'maxOutputTokens':12000,'responseMimeType':'application/json'}}
        timeout=120
    elif mode=='ollama':
        if config.OLLAMA_MODEL.endswith((':cloud','-cloud')):raise ValueError('Выберите локальную модель, например qwen3:8b, без суффикса cloud.')
        url=config.OLLAMA_URL.rstrip('/')+'/api/chat';headers={}
        body={'model':config.OLLAMA_MODEL,'stream':False,'think':False,
              'messages':[{'role':'system','content':system},{'role':'user','content':prompt}],
              'format':output_schema,
              'options':{'temperature':0.2,'num_ctx':12288,'num_predict':{'plan':5000,'lesson':3000,'assessment':800,'exam':5000}.get(data.get('kind'),800)}}
        timeout=600
    else:raise ValueError('Неподдерживаемый AI-провайдер')
    for attempt in range(3):
        try:
            r=httpx.post(url,headers=headers,json=body,timeout=timeout,**({'trust_env':False} if mode=='ollama' else {}))
            if r.status_code in (500,502,503,504) and attempt<2:
                time.sleep(2*(attempt+1));continue
            if r.status_code==429:raise ValueError('Лимит запросов или бесплатная квота исчерпаны. Подождите и повторите позже; платный тариф автоматически не включается приложением.')
            if r.status_code in (401,403):raise ValueError('Провайдер отклонил доступ. Проверьте свой ключ, разрешения и доступность сервиса в регионе.')
            if r.status_code==404:raise ValueError('Модель не найдена. Для Ollama запустите connect-ai.bat и скачайте выбранную модель; для Gemini проверьте имя модели.')
            if r.status_code>=400:raise ValueError(f'AI вернул HTTP {r.status_code}. Проверьте модель, параметры запроса и квоту.')
            result=r.json()
            if mode=='gemini':
                candidate=result['candidates'][0]
                if candidate.get('finishReason') not in (None,'STOP'):raise ValueError('Генерация Gemini прервана (лимит длины или фильтр). Сократите тему или число вопросов.')
                raw=''.join(p.get('text','') for p in candidate['content']['parts'] if not p.get('thought'))
            else:
                if result.get('done_reason')=='length':raise ValueError('Ответ локальной модели обрезан. Сократите тему или используйте более мощную модель.')
                raw=result['message']['content']
            return restore_ids(parse_object(raw),reverse)
        except (httpx.TimeoutException,httpx.NetworkError):
            # A local model may need several minutes; do not repeat that expensive generation automatically.
            if mode=='ollama' or attempt==2:raise ValueError('Нет ответа от модели. Для Ollama проверьте запуск приложения, память и скорость компьютера; для облака — интернет.') from None
            time.sleep(2*(attempt+1))
        except (KeyError,IndexError,TypeError,json.JSONDecodeError):raise ValueError('AI не вернул ожидаемый текстовый ответ. Проверьте модель и журнал операции.') from None
