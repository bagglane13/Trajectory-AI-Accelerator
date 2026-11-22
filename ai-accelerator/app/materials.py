import io, re, zipfile
from pathlib import Path
from pypdf import PdfReader
from docx import Document as Docx
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from .db import Chunk, Document
from .config import MAX_TEXT

def extract(name, raw):
    ext=Path(name).suffix.lower()
    try:
        if ext=='.txt': parts=[('Текст',raw.decode('utf-8-sig'))]
        elif ext=='.pdf':
            if not raw.startswith(b'%PDF'): raise ValueError('Это не PDF-файл')
            pdf=PdfReader(io.BytesIO(raw))
            if pdf.is_encrypted: raise ValueError('Снимите пароль с PDF')
            if len(pdf.pages)>300: raise ValueError('Допускается не более 300 страниц')
            parts=[(f'Страница {i+1}',clean_pdf_text(p.extract_text() or '')) for i,p in enumerate(pdf.pages)]
        elif ext=='.docx':
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                if sum(x.file_size for x in z.infolist())>40*1024*1024:raise ValueError('Слишком большой распакованный DOCX')
            doc=Docx(io.BytesIO(raw))
            parts=[(f'Абзац {i+1}',p.text) for i,p in enumerate(doc.paragraphs) if p.text.strip()]
            for i,t in enumerate(doc.tables):
                parts.append((f'Таблица {i+1}','\n'.join(' | '.join(c.text for c in r.cells) for r in t.rows)))
        else: raise ValueError('Поддерживаются PDF с текстом, DOCX и UTF-8 TXT')
    except ValueError: raise
    except Exception as e: raise ValueError('Не удалось прочитать файл. Проверьте формат и отсутствие пароля.') from e
    text='\n\n'.join(t for _,t in parts)
    if len(text.strip())<30:raise ValueError('В файле слишком мало текста. Для скана сначала выполните OCR.')
    if len(text)>MAX_TEXT:raise ValueError('Слишком много текста: максимум 1 млн символов')
    chunks=[]
    for loc,t in parts:
        for start in range(0,len(t),2300):
            piece=t[start:start+2600].strip()
            if piece:chunks.append((loc,piece))
    # Small DOCX paragraphs are combined; retain their starting paragraph locator.
    merged=[]
    for loc,t in chunks:
        if merged and len(merged[-1][1])+len(t)<2600 and ext=='.docx':
            merged[-1]=(merged[-1][0],merged[-1][1]+'\n'+t)
        else:merged.append((loc,t))
    return text,merged

def clean_pdf_text(text):
    # Page numbers are metadata, never teaching content. Preserve code indentation.
    text=re.sub(r'\A[ \t]*\d{1,4}[ \t]*\r?\n', '', text)
    text=re.sub(r'([а-яёА-ЯЁ]{2,})-\s*\n\s*(?=[а-яё])', r'\1', text)
    return text.strip()

def is_heading(text):
    return bool(re.match(r'^(?:вопросы\s+(?:для|к|по)|контрольные вопросы|список вопросов|для самостоятельного изучения)',text,re.I)) or text.strip().lower().rstrip('.') in (
        'каскадные таблицы стилей','ecmascript (базовый javascript)','язык разметки гипертекста – html 4.01')

def parse_questions(text):
    lines=[x.strip() for x in text.splitlines() if x.strip() and not is_heading(x.strip())]
    numbered=any(re.match(r'^\d+[.)]\s+',x) for x in lines)
    found=[]
    for line in lines:
        m=re.match(r'^\d+[.)]\s+(.+)',line)
        if m:found.append(m.group(1))
        elif numbered and found:found[-1]+=' '+line
        elif not numbered:found.append(line)
    return list(dict.fromkeys(x for x in found if len(x)>3 and not x.isdigit()))[:100]

def extract_questions(name, raw, text):
    if Path(name).suffix.lower()=='.docx':
        doc=Docx(io.BytesIO(raw)); listed=[]
        for p in doc.paragraphs:
            pr=p._p.pPr
            numbered=pr is not None and pr.numPr is not None
            style=p.style
            visited=set()
            while style is not None and not numbered and style.style_id not in visited:
                visited.add(style.style_id); spr=style.element.pPr
                numbered=spr is not None and spr.numPr is not None
                style=style.base_style
            if numbered and p.text.strip() and not is_heading(p.text.strip()):
                listed.append(re.sub(r'^\d+[.)]\s+', '', p.text.strip()))
        if listed:return list(dict.fromkeys(listed))[:100]
    return parse_questions(text)

STOP={'что','как','для','при','или','его','это','все','они','над','под','без','про','тип','вид','вопрос','документ'}
def tokens(text):
    words=re.findall(r'[а-яёa-z0-9_]+',text.lower())
    return [w[:6] if re.fullmatch('[а-яё]+',w) and len(w)>6 else w for w in words if len(w)>2 and w not in STOP and not w.isdigit()]

def is_question_list(text):
    """Exam lists name the topics but do not provide evidence for their answers.

    A continuation page may have no heading. Detect a dense numbered list as
    well, while retaining lessons with code and ordinary step-by-step examples.
    """
    lines=[line.strip() for line in clean_pdf_text(text).splitlines() if line.strip()]
    numbered=[line for line in lines if re.match(r'^\d{1,3}[.)]\s+\S',line)]
    heading=any(re.match(r'^(?:вопросы\s+(?:к\s+(?:зач[её]ту|экзамену)|для\s+самоконтроля)|контрольные\s+вопросы)',line,re.I) for line in lines[:4])
    if heading and len(numbered)>=2:return True
    if len(numbered)<4 or len(numbered)/len(lines)<.45:return False
    # Numbered instructions with executable examples are teaching material.
    if re.search(r'<\s*/?\s*[a-z][\w-]*(?:\s|>)|\b(?:function|return|console\.|document\.)|[{}=;]',text,re.I):return False
    if re.search(r'\b(?:создайте|добавьте|откройте|выберите|используйте|проверьте|выполните|найдите|запишите)\b',text,re.I):return False
    if sum(bool(re.search(r'\s[—–]\s',line)) for line in numbered)>=2:return False
    return True

def retrieve(db, course_id, query, count=6):
    rows=db.scalars(select(Chunk).join(Document,Document.id==Chunk.document_id).where(Chunk.course_id==course_id,Document.role=='methodology')).all()
    if not rows:return []
    query=re.sub(r'структура\s+html', 'html head body структура',query,flags=re.I)
    corpus=[tokens(clean_pdf_text(x.text)) or ['_'] for x in rows]
    bm=BM25Okapi(corpus);scores=bm.get_scores(tokens(query))
    # Lexical overlap gives useful ordering even on very small corpora (BM25 IDF may be zero).
    q=set(tokens(query))
    def rank(i):
        text=clean_pdf_text(rows[i].text)
        admin=bool(re.search(r'всего часов|курс рассчитан|для студентов направ|вопросы к зачету|контрольная работа не выполнена',text,re.I))
        toc=text.count('....')>3
        overlap=len(q&set(corpus[i]))
        return (0 if admin or toc else 1, overlap, float(scores[i]))
    matching=[i for i in range(len(rows)) if q&set(corpus[i]) and not is_question_list(rows[i].text)]
    ordered=sorted(matching,key=rank,reverse=True)[:count]
    names={d.id:d.name for d in db.scalars(select(Document).where(Document.course_id==course_id))}
    return [{'id':rows[i].id,'text':clean_pdf_text(rows[i].text),'locator':rows[i].locator,'document':names[rows[i].document_id]} for i in ordered]
