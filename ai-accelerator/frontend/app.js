const $ = (s, root=document) => root.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const enc=encodeURIComponent;
const icons={grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',book:'M4 3h6a3 3 0 0 1 3 3v15a3 3 0 0 0-3-3H4zM13 6a3 3 0 0 1 3-3h5v15h-5a3 3 0 0 0-3 3',arrow:'M5 12h14M13 6l6 6-6 6',plus:'M12 5v14M5 12h14',clock:'M12 8v4l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',calendar:'M4 5h16v16H4zM4 10h16M8 3v4M16 3v4',check:'M5 12l4 4L19 6',upload:'M12 16V3M7 8l5-5 5 5M4 15v6h16v-6',help:'M9 9a3 3 0 0 1 6 0c0 2-3 2-3 5M12 17h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',logout:'M9 4H4v16h5M9 12h12M17 8l4 4-4 4',spark:'m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z',file:'M5 3h9l5 5v13H5zM14 3v6h5M8 13h8M8 17h6',target:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M17 12a5 5 0 1 1-10 0 5 5 0 0 1 10 0M12 10v4M10 12h4',settings:'M4 7h16M4 17h16M8 4v6M16 14v6',code:'m8 6-6 6 6 6M16 6l6 6-6 6M14 3l-4 18',bulb:'M9 18h6M9 21h6M8 15c-4-4-2-11 4-11s8 7 4 11l-1 3H9z'};
const icon=(name,size=18)=>`<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${icons[name]||icons.book}"/></svg>`;
const brand=()=>'<span class="brand-symbol">↗</span>Траектория';
let user=null, config={}, authMode='login', courses=[], current=null, renderId=0, pollTimer=null;
let watchIds=new Set(), notified=new Set(), dashboardFilter='all';
const stages={plan:'План',lesson:'Урок',assessment:'Проверка ответа',exam:'Итоговый тест'};
const activeStates=['queued','running'];
const dateLabel=s=>new Date(s+'T12:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'short'});
const hours=n=>`${Math.round(n/6)/10} ч`;
const localDate=()=>new Date().toLocaleDateString('sv-SE');
const levelLabels={beginner:'С нуля',basic:'Знаком с основами',revision:'Повторение'};

async function api(path, options={}){
  const headers={'Accept':'application/json',...(options.headers||{})};
  if(user?.csrf)headers['X-CSRF-Token']=user.csrf;
  if(options.body && !(options.body instanceof FormData)){headers['Content-Type']='application/json';options.body=JSON.stringify(options.body);}
  const r=await fetch('/api'+path,{...options,headers,credentials:'same-origin'});
  const data=await r.json().catch(()=>({detail:'Сервер вернул неожиданный ответ'}));
  if(!r.ok){
    if(r.status===401 && user){user=null;render();}
    const message=Array.isArray(data.detail)?data.detail.map(x=>x.msg).join('; '):data.detail||'Ошибка запроса';
    throw new Error(message);
  }
  return data;
}
async function uploadMethodologies(courseId,files,onProgress=()=>{}){
  for(let i=0;i<files.length;i++){
    onProgress(i+1,files.length,files[i].name);
    const body=new FormData();body.append('file',files[i]);body.append('role','methodology');
    await api('/courses/'+courseId+'/documents',{method:'POST',body});
  }
}
function toast(message,error=false){const e=document.createElement('div');e.className='toast'+(error?' error':'');e.textContent=message;$('#toasts').append(e);setTimeout(()=>e.remove(),6000);}
function modal(title,body){$('#modal-content').innerHTML=`<h2>${esc(title)}</h2>${body}`;if(!$('#modal').open)$('#modal').showModal();}
function go(path){if(location.hash===`#${path}`)render();else location.hash=path;}
function loading(){return '<div class="skeleton"></div><div class="skeleton"></div>';}
function errorPage(e){return `<div class="card page-error"><h2>Не получилось загрузить страницу</h2><p class="muted wrap">${esc(e.message)}</p><div class="row" style="margin-top:20px"><button class="btn" data-action="refresh">Повторить</button><a class="btn secondary" href="#/">Мои курсы</a></div></div>`;}
function shell(body,section='Мои курсы'){
  const isNew=location.hash.startsWith('#/new');
  $('#app').innerHTML=`<aside class="sidebar"><a class="brand" href="#/">${brand()}</a><div class="nav-label">ВАШЕ ОБУЧЕНИЕ</div><nav><a class="nav-item ${!isNew?'active':''}" href="#/">${icon('grid')}Мои курсы</a><a class="nav-item ${isNew?'active':''}" href="#/new">${icon('plus')}Создать курс</a></nav><div class="nav-bottom"><div class="sidebar-note">${icon('spark',21)}<strong>Учитесь в своем ритме</strong>Ваши материалы. Ваше время.<br>Ваша траектория.<br><button data-action="help">Как это работает ↗</button></div><div class="profile"><div class="avatar">${esc(user.name.slice(0,1).toUpperCase())}</div><div class="profile-info"><strong>${esc(user.name)}</strong><span>Личное пространство</span></div><button class="icon-button" data-action="logout" title="Выйти" aria-label="Выйти">${icon('logout',17)}</button></div></div></aside><div class="workspace"><header class="topbar"><a class="brand mobile-brand" href="#/">${brand()}</a><div class="breadcrumb">Личное пространство <span>/</span> <strong>${esc(section)}</strong></div><div class="row"><span class="mode-pill ${config.ai_mode!=='demo'?'live':''}">${esc(config.provider_label||'Деморежим')}</span><button class="help-link" data-action="help">${icon('help',16)}Помощь</button><button class="icon-button mobile-brand" data-action="logout" aria-label="Выйти">${icon('logout',16)}</button></div></header><main id="main">${body}</main></div>`;
}

function authPage(){
  const reg=authMode==='register';
  $('#app').innerHTML=`<main id="main" class="auth-page" style="padding:0;max-width:none"><section class="auth-story"><a class="brand" href="#/">${brand()}</a><h1>От первой темы<br>до уверенного<br><em>«я готов».</em></h1><p>Превратите свою методичку в понятный путь к экзамену. Теория, практика и план, который учитывает вашу жизнь.</p><div class="auth-art"><div class="auth-feature">${icon('file',25)}<div><strong>Ваши материалы</strong><small>Несколько методичек — одна база курса</small></div></div><div class="auth-feature">${icon('calendar',25)}<div><strong>Ваше расписание</strong><small>Только те дни, когда удобно вам</small></div></div><div class="auth-feature">${icon('target',25)}<div><strong>Ваша цель</strong><small>Каждый урок приближает к экзамену</small></div></div></div><div class="auth-caption">Маленькие шаги. Настоящие знания.</div></section><section class="auth-form-wrap"><form class="auth-form" id="auth-form"><div class="eyebrow">НАЧНИТЕ СВОЮ ТРАЕКТОРИЮ</div><h2 style="margin-top:12px">${reg?'Давайте знакомиться':'С возвращением'}</h2><p>${reg?'Создайте учетную запись и соберите свой первый курс.':'Ваши курсы и прогресс ждут вас.'}</p>${reg?'<div class="field"><label for="name">Как вас зовут</label><input id="name" name="name" required maxlength="80" autocomplete="given-name" placeholder="Артём"></div>':''}<div class="field"><label for="email">Электронная почта</label><input id="email" name="email" type="email" required autocomplete="email" placeholder="you@example.com"></div><div class="field"><label for="password">Пароль</label><input id="password" name="password" type="password" required minlength="8" maxlength="128" autocomplete="${reg?'new-password':'current-password'}" placeholder="Не менее 8 символов"></div><div class="form-error" id="auth-error" role="alert"></div><button class="btn full" type="submit">${reg?'Создать учетную запись':'Войти'} ${icon('arrow',16)}</button><div class="auth-toggle">${reg?'Уже есть аккаунт?':'Здесь впервые?'} <button type="button" class="text-link" data-action="auth-toggle">${reg?'Войти':'Зарегистрироваться'}</button></div><div class="notice info">${config.ai_mode==='demo'?'Сейчас включен деморежим. Можно создать курс, изучить материалы и проверить тесты без API-ключа.':'Включена AI-генерация. При облачном провайдере фрагменты методички и ответы передаются ему для обработки.'}</div></form></section></main>`;
}
function heroArt(){return `<div class="hero-visual" aria-hidden="true"><svg class="path-art" viewBox="0 0 290 180" fill="none"><path d="M28 150C-25 73 174 165 119 73S253 7 257 81" stroke="#f2a06a" stroke-width="2" stroke-dasharray="5 6"/><circle cx="38" cy="146" r="8" fill="#d96932"/><circle cx="142" cy="105" r="6" fill="#d96932"/><path d="M218 72l38 11-12-37-7 16z" fill="#f06b24"/><path d="m235 62 21 21" stroke="#8f1739"/></svg><div class="float-note note-one"><div class="mini-check">✓</div><div><b>Еще один шаг</b><span>Тема пройдена</span></div></div><div class="float-note note-two">${icon('book',22)}<div><b>План под вас</b><span>В вашем ритме</span></div></div><span class="goal-star">✧</span></div>`;}
function courseCard(c,i){
  const color=['','orange','green'][i%3];const ready=c.status==='ready';
  return `<article class="card course-card"><div class="row between"><div class="subject-icon ${color}">${/python/i.test(c.title)?'Py':/c\+\+/i.test(c.title)?'C++':icon('code',24)}</div><span class="badge ${c.progress===100?'success':ready?'accent':''}">${c.progress===100?'Завершен':ready?'В процессе':'Черновик'}</span></div><div><h3>${esc(c.title)}</h3><div class="metadata"><span>${icon('book',13)}${c.total||c.question_count} ${ready?'тем':'вопросов'}</span><span>${icon('calendar',13)}До ${dateLabel(c.budget.end)}</span></div></div><div><div class="progress-label"><span>${c.completed} из ${c.total} тем пройдено</span><strong>${c.progress}%</strong></div><div class="progress"><span style="width:${c.progress}%"></span></div></div><footer><span>${levelLabels[c.level]}</span><a class="text-link" href="#/course/${c.id}">${ready?'Продолжить':'Настроить курс'} →</a></footer></article>`;
}
async function dashboard(id){
  courses=await api('/courses');if(id!==renderId)return;
  watchIds=new Set(courses.flatMap(c=>c.active_jobs.map(j=>j.id)));
  const selected=courses.filter(c=>dashboardFilter==='all'||(dashboardFilter==='done'?c.progress===100:c.status==='ready'&&c.progress<100));
  const name=user.name.split(' ')[0];const done=courses.reduce((s,c)=>s+c.completed,0);const active=courses.filter(c=>c.status==='ready'&&c.progress<100).length;
  const totalQuestions=courses.reduce((s,c)=>s+c.question_count,0);
  shell(`<div class="page-intro row between"><div><div class="eyebrow">ВАШЕ ПРОСТРАНСТВО ЗНАНИЙ</div><h1>Привет, ${esc(name)} <span style="font-weight:400">✦</span></h1><p>Хороший день, чтобы стать на шаг ближе к цели.</p></div><a class="btn" href="#/new">${icon('plus',16)}Создать курс</a></div><section class="hero"><div class="hero-copy"><div class="eyebrow">ОТ МЕТОДИЧКИ ДО ЭКЗАМЕНА</div><h2>Большие цели.<br>Маленькие шаги.</h2><p>Загрузите материалы, выберите свой ритм — и двигайтесь по персональному плану обучения.</p><a class="btn" href="#/new">Построить свою траекторию ${icon('arrow',15)}</a></div>${heroArt()}</section><div class="section-heading"><h2>Мои курсы <span class="count">${courses.length}</span></h2><div class="tabs">${[['all','Все курсы'],['active','В процессе'],['done','Завершены']].map(([v,t])=>`<button class="tab ${dashboardFilter===v?'active':''}" data-action="filter" data-value="${v}">${t}</button>`).join('')}</div></div><div class="course-grid">${selected.map(courseCard).join('')}<a class="card new-card" href="#/new"><span class="plus-circle">+</span><h3>Новый предмет — новый путь</h3><p>Добавьте методичку и начните готовиться к следующему экзамену</p></a></div>${!courses.length?'<div class="notice info" style="margin-top:20px">Хотите сначала посмотреть, как все устроено? <button class="text-link" data-action="demo">Создать пример курса по Python →</button></div>':''}<div class="dashboard-bottom"><div class="card tip-card"><div class="tip-icon">${icon('bulb',21)}</div><div><h3>Регулярность важнее марафона</h3><p>Небольшие занятия помогают сохранять ритм. Оставляйте в расписании время на практику и повторение.</p></div></div><div class="card stats-row"><div class="stat"><strong>${active}</strong><span>активных курсов</span></div><div class="stat"><strong>${done}</strong><span>тем пройдено</span></div><div class="stat"><strong>${totalQuestions}</strong><span>вопросов к экзамену</span></div></div></div>`);
}
function scheduleFields(s={start:localDate(),duration:'1m',days:{'1':60,'3':60,'5':60}}){
  return `<div class="field"><label for="start">Дата начала</label><input type="date" id="start" name="start" value="${esc(s.start)}" required></div><div class="field"><label for="duration">Сколько времени на подготовку</label><select id="duration" name="duration">${[['15d','15 дней'],['1m','1 месяц'],['2m','2 месяца'],['3m','3 месяца'],['6m','Полгода'],['12m','Год']].map(([v,t])=>`<option value="${v}" ${s.duration===v?'selected':''}>${t}</option>`).join('')}</select></div><div class="field"><span class="field-label">Дни занятий и минуты в день</span><div class="day-grid">${['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map((d,i)=>`<div class="day-box"><label><input type="checkbox" name="day${i+1}" ${s.days[String(i+1)]?'checked':''}>${d}</label><input type="number" min="15" max="240" step="5" name="min${i+1}" value="${s.days[String(i+1)]||60}" aria-label="Минут в ${d}"></div>`).join('')}</div><small>Выберите хотя бы один день. От 15 до 240 минут.</small></div><div id="budget-preview" class="budget-preview"></div>`;
}
function readSchedule(form){
  const f=new FormData(form),days={};for(let i=1;i<=7;i++)if(f.has('day'+i))days[String(i)]=Number(f.get('min'+i));
  if(!Object.keys(days).length)throw new Error('Выберите хотя бы один день занятий');
  if(Object.values(days).some(n=>n<15||n>240))throw new Error('Время занятия должно быть от 15 до 240 минут');
  return {start:f.get('start'),duration:f.get('duration'),days};
}
function updateBudget(){
  const box=$('#budget-preview');if(!box)return;
  try{
    const s=readSchedule(box.closest('form')),start=new Date(s.start+'T12:00:00'),end=new Date(start);
    if(isNaN(start))return;
    if(s.duration==='15d')end.setDate(end.getDate()+15);
    else{const day=end.getDate();end.setDate(1);end.setMonth(end.getMonth()+parseInt(s.duration));const last=new Date(end.getFullYear(),end.getMonth()+1,0).getDate();end.setDate(Math.min(day,last));}
    let minutes=0,count=0;for(let d=new Date(start);d<end;d.setDate(d.getDate()+1)){const m=s.days[String(d.getDay()||7)];if(m){minutes+=m;count++;}}
    box.innerHTML=`<div>Ваш запас времени<strong>${hours(minutes)}</strong></div><span>${count} занятий<br>в выбранном периоде</span>`;
  }catch(e){box.textContent=e.message;}
}
function newCourse(){
  shell(`<div class="page-intro"><div class="eyebrow">ВАША НОВАЯ ТРАЕКТОРИЯ</div><h1>Соберем курс под вас</h1><p>Нужны материалы, контрольные вопросы и немного времени в расписании.</p></div><div class="step-bar"><div class="step"><strong>01</strong>Предмет и материалы</div><div class="step"><strong>02</strong>Вопросы к экзамену</div><div class="step"><strong>03</strong>Ваш ритм</div></div><form id="new-course-form"><div class="form-grid"><div class="stack"><section class="card padded"><div class="form-title"><span class="number-box">01</span><h2>Что будем изучать?</h2></div><div class="field"><label for="title">Название предмета</label><input id="title" name="title" required minlength="2" maxlength="160" placeholder="Например, основы программирования на C++"></div><div class="field"><label for="level">Ваш уровень</label><select id="level" name="level"><option value="beginner">Начинаю с нуля</option><option value="basic">Знаком с основами</option><option value="revision">Хочу повторить перед экзаменом</option></select></div><div class="field"><label for="methodology">Методички и учебные материалы</label><div class="upload-field">${icon('upload',26)}<strong class="small">Все выбранные файлы станут общей основой курса</strong><br><small>До 40 PDF, DOCX или TXT · каждый до 20 МБ</small><input id="methodology" name="methodology" type="file" accept=".pdf,.docx,.txt" multiple required><div id="methodology-files" class="small muted" style="margin-top:10px">Файлы не выбраны</div></div></div></section><section class="card padded"><div class="form-title"><span class="number-box">02</span><h2>К чему готовимся?</h2></div><div class="field"><label for="questions">Контрольные вопросы</label><textarea id="questions" name="questions" placeholder="Один вопрос на строку.\n1. Что такое переменная?\n2. Как работают условные операторы?"></textarea><small>Или загрузите отдельный файл ниже. После загрузки список можно исправить.</small></div><div class="field"><label for="questions-file">Файл с вопросами (необязательно)</label><input id="questions-file" name="questions_file" type="file" accept=".pdf,.docx,.txt"></div></section></div><aside class="card padded sticky"><div class="form-title"><span class="number-box">03</span><h2>В вашем ритме</h2></div>${scheduleFields()}<div class="notice info" style="margin-top:18px">Время на повторение тоже входит в план. Если занятий недостаточно, приложение предложит изменить срок.</div></aside></div><div class="form-footer"><p>${config.ai_mode==='demo'?'Деморежим показывает фрагменты и примеры. Для AI запустите connect-ai.bat.':config.ai_mode==='ollama'?'Материалы обрабатываются настроенной моделью Ollama.':'Выбранные фрагменты материалов передаются облачному AI-провайдеру.'}</p><button type="submit" class="btn" id="create-button">Сохранить и проверить материалы ${icon('arrow',16)}</button></div><div id="form-error" class="form-error" role="alert"></div></form>`,'Создать курс');updateBudget();
}
function courseTabs(cid,active){return `<nav class="course-tabs"><a class="${active==='roadmap'?'active':''}" href="#/course/${cid}">Дорожная карта</a><a class="${active==='questions'?'active':''}" href="#/questions/${cid}">Вопросы к экзамену</a><a class="${active==='exam'?'active':''}" href="#/exam/${cid}">Итоговый тест</a><a class="${active==='log'?'active':''}" href="#/log/${cid}">Журнал AI</a><a class="${active==='settings'?'active':''}" href="#/settings/${cid}">Настройки</a></nav>`;}
function courseBanner(c){return `<div class="course-banner"><div class="subject-icon orange">${icon('code',29)}</div><div><div class="eyebrow">ПЕРСОНАЛЬНЫЙ КУРС</div><h1>${esc(c.title)}</h1><div class="metadata" style="margin-top:9px"><span>${icon('calendar',13)}До ${dateLabel(c.budget.end)}</span><span>${icon('clock',13)}${hours(c.budget.total_minutes)} на подготовку</span><span>${c.question_count} вопросов</span></div></div></div>`;}
function jobBox(j){
  if(j.state==='completed')return '';
  const active=activeStates.includes(j.state);if(active)watchIds.add(j.id);
  return `<div class="job-box ${active?'':'job-error'}" data-job="${j.id}"><div class="row between"><strong>${active?'<span class="spinner"></span>':''}<span data-stage>${esc(j.stage)}</span> <span class="muted small">· ${stages[j.kind]} · ${j.revision||1}/3</span></strong>${active?`<button class="text-link" data-action="cancel-job" data-id="${j.id}">Остановить</button>`:`<button class="text-link" data-action="retry-job" data-id="${j.id}">Повторить →</button>`}</div>${j.error?`<p class="job-detail">${esc(j.error)}</p>${j.kind==='plan'?`<a class="text-link" href="#/${/Недостаточно времени/.test(j.error)?'settings':'course'}/${current.course_id||current.id}">${/Недостаточно времени/.test(j.error)?'Проверить время и изменить уровень':'Проверить материалы курса'} →</a>`:''}`:''}${active?'<div class="progress"><span style="width:35%"></span></div>':''}</div>`;
}
function latestRelevantJobs(list){const seen=new Set();return list.filter(j=>{const key=j.kind+j.target;if(seen.has(key))return false;seen.add(key);return j.state!=='completed';});}
async function coursePage(cid,id){
  const c=await api('/courses/'+cid);if(id!==renderId)return;current=c;
  if(config.ai_mode!=='demo'&&!c.active_jobs.length&&(c.plan.mode==='demo'||c.lessons.some(l=>l.mode==='demo'))){
    const copy=await api('/courses/'+cid+'/upgrade-ai',{method:'POST'});toast('Подготавливаем AI-версию курса. Старый курс и прогресс сохранены.');go('/course/'+copy.id);return;
  }
  if(c.status!=='ready'){
    shell(`${courseBanner(c)}${courseTabs(cid,'roadmap')}${latestRelevantJobs(c.recent_jobs).map(jobBox).join('')}<div class="form-grid"><section class="card padded"><h2>Проверим исходные материалы</h2><p class="muted small" style="margin:10px 0 22px">Сохраните исправленный список вопросов перед построением плана.</p>${c.documents.map(d=>`<div class="document-row">${icon('file',20)}<div class="grow wrap"><strong>${esc(d.name)}</strong><small>${d.role==='methodology'?'Методичка':'Вопросы'} · ${d.characters.toLocaleString('ru-RU')} символов</small></div><button class="text-link" data-action="preview" data-id="${d.id}">Открыть</button></div>`).join('')||'<div class="notice">Материалы пока не загружены.</div>'}<form id="upload-extra-form" data-course="${cid}" class="row" style="margin:15px 0 25px"><div class="field grow" style="margin:0"><label for="extra-file">Добавить одну или несколько методичек</label><input id="extra-file" type="file" name="file" accept=".txt,.pdf,.docx" multiple required><small>Можно выбрать сразу несколько файлов.</small></div><button class="btn secondary small">Загрузить</button></form><form id="questions-form" data-course="${cid}"><div class="field"><label for="question-edit">Контрольные вопросы · один на строку</label><textarea id="question-edit" name="questions" rows="10" required>${esc(c.questions.map(q=>q.text).join('\n'))}</textarea></div><button class="btn secondary" type="submit">Сохранить вопросы</button></form></section><aside class="card padded"><h3>Все готово к старту?</h3><div class="definition"><span>Вопросов</span><strong>${c.questions.length}</strong></div><div class="definition"><span>Бюджет</span><strong>${hours(c.budget.total_minutes)}</strong></div><div class="definition"><span>Уровень</span><strong>${levelLabels[c.level]}</strong></div><hr><button class="btn full" data-action="generate-plan" data-id="${cid}" ${c.active_jobs.length?'disabled':''}>${icon('spark',16)}Построить план</button><p class="small muted" style="margin-top:16px">Агент создаст темы, проверяющий найдет недочеты, а планировщик распределит занятия по дням.</p><a class="text-link" style="display:block;margin-top:15px" href="#/settings/${cid}">Проверить время и изменить уровень →</a></aside></div>`,'Материалы курса');return;
  }
  const next=c.lessons.find(l=>!l.completed)?.id;
  const sessions=c.plan.sessions||[];const today=localDate();const future=sessions.filter(s=>s.date>=today).slice(0,4);
  const agenda=(future.length?future:sessions.slice(-4)).map(s=>`<div class="agenda-item"><div class="date-box"><strong>${Number(s.date.slice(-2))}</strong><span>${new Date(s.date+'T12:00:00').toLocaleDateString('ru-RU',{month:'short'})}</span></div><div><p>${esc(s.title)}</p><small>${s.minutes} мин.${s.part>1?' · часть '+s.part:''}</small></div></div>`).join('');
  shell(`${courseBanner(c)}${courseTabs(cid,'roadmap')}${latestRelevantJobs(c.recent_jobs).filter(j=>j.kind==='plan'||activeStates.includes(j.state)).map(jobBox).join('')}<div class="roadmap-layout"><section><div class="section-heading"><h2>Ваш путь к экзамену</h2><span class="muted small">${c.lessons.length} тем</span></div><div class="timeline">${c.lessons.map((l,i)=>{const slot=sessions.find(s=>s.topic_id===l.id);return `<article class="timeline-item"><span class="step-dot ${l.completed?'done':l.id===next?'current':''}">${l.completed?'✓':String(i+1).padStart(2,'0')}</span><div class="card topic-card"><div class="row between"><span class="eyebrow" style="font-size:9px">ТЕМА ${String(i+1).padStart(2,'0')}</span><span class="badge ${l.completed?'success':'accent'}">${l.completed?'Пройдено':l.ready?'Материал готов':'По плану'}</span></div><h3>${esc(l.topic.title)}</h3><p>${esc(l.topic.objective)}</p><footer><span>${icon('clock',12)} ${l.topic.minutes} мин. ${slot?' · '+dateLabel(slot.date):''}</span><a class="text-link" href="#/lesson/${l.id}">${l.completed?'Повторить':'Открыть тему'} →</a></footer></div></article>`;}).join('')}<article class="timeline-item"><span class="step-dot">✦</span><div class="card topic-card"><span class="eyebrow" style="font-size:9px">ФИНИШНАЯ ПРЯМАЯ</span><h3>Итоговый тест с учётом ошибок</h3><p>После всех тем AI подготовит 10 вопросов. При наличии ошибок 70% заданий будут по этим темам.</p><a class="text-link" href="#/exam/${cid}">${c.completed===c.total?'Перейти к итоговому тесту':'Посмотреть готовность'} →</a></div></article></div></section><aside class="roadmap-aside stack"><div class="card aside-card"><h3>Ваш прогресс</h3><div class="ring" style="--p:${c.progress}%"><div><strong>${c.progress}%</strong><span>пути пройдено</span></div></div><div class="definition"><span>Пройдено тем</span><strong>${c.completed} из ${c.total}</strong></div><div class="definition"><span>Изучение и практика</span><strong>${hours(c.plan.learning_minutes||0)}</strong></div><div class="definition"><span>Повторение</span><strong>${hours(c.plan.review_minutes||0)}</strong></div></div><div class="card aside-card"><h3>Ближайшие занятия</h3>${agenda||'<p class="small muted">Все темы завершены.</p>'}<button class="text-link" data-action="agenda" data-id="${cid}" style="margin-top:10px">Все занятия →</button></div>${c.plan.mode==='demo'?'<div class="notice info">Демо-план: темы построены по списку вопросов. Для AI-анализа методички запустите connect-ai.bat.</div>':''}</aside></div>`,'Дорожная карта');
}
function sources(ids){return `<div class="source-buttons">${[...new Set(ids||[])].map((x,i)=>`<button class="source-button" data-action="source" data-id="${esc(x)}">${icon('file',11)} Источник ${i+1}</button>`).join('')}</div>`;}
function attemptResult(a){
  if(!a)return '';
  const r=a.result;const graded=r.status==='graded';
  return `<div class="result ${graded?(r.score>=70?'pass':'fail'):''}"><strong>${graded?`${r.score>=70?'✓':'↻'} ${r.score} / 100`:r.status==='self_checked'?'✓ Самопроверка подтверждена (без AI-оценки)':r.status==='self_check'?'Самопроверка':r.status==='pending'?'Ответ проверяется…':'Проверка остановлена'}</strong><p>${esc(r.feedback)}</p>${r.improvements?.length?`<ul>${r.improvements.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}${r.reference?`<details><summary>Опорный материал и критерии</summary><p>${esc(r.rubric)}</p><p>${esc(r.reference)}</p></details>`:''}${r.analysis_only?'<small>Анализ без выполнения кода</small>':''}${r.status==='self_check'?`<p><button type="button" class="btn secondary small" data-action="self-confirm" data-id="${a.id}">Я сверил ответ с критериями</button></p>`:''}</div>`;
}
async function lessonPage(lid,id){
  const l=await api('/lessons/'+lid);if(id!==renderId)return;current=l;
  if(config.ai_mode!=='demo'&&l.content?.mode==='demo'){
    const copy=await api('/courses/'+l.course_id+'/upgrade-ai',{method:'POST'});go('/course/'+copy.id);return;
  }
  const jobsForLesson=l.jobs.filter(j=>j.target===lid||j.kind==='assessment'&&l.attempts.some(a=>a.id===j.target));
  const jobHtml=latestRelevantJobs(jobsForLesson).map(jobBox).join('');
  let body;
  if(!l.content?.blocks && !l.jobs.some(j=>j.kind==='lesson'&&j.target===lid)){
    if(!l.jobs.some(j=>activeStates.includes(j.state))){await api('/lessons/'+lid+'/generate',{method:'POST'});await render(true);return;}
    l.jobs.filter(j=>activeStates.includes(j.state)).forEach(j=>watchIds.add(j.id));
  }
  if(!l.content?.blocks){body=`${jobHtml}<section class="card empty"><div class="empty-symbol">✦</div><h2>Создадим ваш урок</h2><p>Найдем материалы по теме, подготовим теорию и практику, затем проверим результат.</p><button class="btn" data-action="generate-lesson" data-id="${lid}" ${jobsForLesson.some(j=>activeStates.includes(j.state))?'disabled':''}>${icon('spark',16)}Подготовить урок</button></section>`;}
  else{
    const content=l.content;
    body=`${jobHtml}${content.mode==='demo'?'<div class="notice info" style="margin-bottom:20px">Офлайн-материал: фрагменты методички, встроенные примеры для отдельных тем и самопроверка. Для AI-генерации и проверки запустите connect-ai.bat и выберите провайдер.</div>':''}<section class="card lesson-section"><div class="eyebrow">01 · РАЗБИРАЕМСЯ В ТЕМЕ</div><h2 style="margin-top:8px">Теория</h2><p class="prose">${esc(content.intro)}</p>${content.blocks.map(b=>`<h3>${esc(b.title)}</h3><div class="prose">${esc(b.text)}</div>${b.code?`<pre><code>${esc(b.code)}</code></pre>`:''}`).join('')}${sources(content.source_ids)}<div class="read-footer"><span class="small muted">${l.theory_read?'✓ Теория отмечена прочитанной':'Прочитайте материал и переходите к практике'}</span><button class="btn ${l.theory_read?'secondary':''} small" data-action="read" data-id="${lid}" ${l.theory_read?'disabled':''}>${icon('check',15)}Я изучил теорию</button></div></section><section class="card lesson-section"><div class="eyebrow">02 · ЗАКРЕПЛЯЕМ ЗНАНИЯ</div><h2 style="margin-top:8px">Теперь ваша очередь</h2>${content.tasks.map((t,i)=>{const a=l.attempts.find(x=>x.task_id===t.id);return `<form class="task" data-task="${esc(t.id)}" data-lesson="${lid}"><div class="row between task-head"><span class="badge">Задание ${i+1} · ${t.type==='quiz'?'Тест':t.type==='code'?'Код':'Открытый ответ'}</span><span class="muted small">${t.required?'Обязательное':'Дополнительное'}</span></div><h3>${esc(t.prompt)}</h3>${t.type==='quiz'?t.options.map((opt,j)=>`<label class="option"><input type="radio" name="answer" value="${j}" required ${a?.answer===String(j)?'checked':''}><span>${esc(opt)}</span></label>`).join(''):`<textarea name="answer" class="${t.type==='code'?'code':''}" required maxlength="12000" placeholder="${t.type==='code'?'Напишите фрагмент кода. Он не будет выполняться.':'Объясните своими словами…'}">${esc(a?.answer||'')}</textarea>`}<div class="task-footer"><span class="muted small">${t.type==='quiz'?'Порог прохождения: 70%':'Без запуска кода'}</span><button type="submit" class="btn small">${a?'Отправить снова':'Проверить ответ'} ${icon('arrow',14)}</button></div>${attemptResult(a)}</form>`;}).join('')}</section>`;
  }
  const next=l.siblings[l.siblings.findIndex(x=>x.id===lid)+1];
  shell(`<div class="row between" style="margin-bottom:22px"><a href="#/course/${l.course_id}" class="text-link">← ${esc(l.course_title)}</a><span class="badge ${l.completed?'success':''}">${l.completed?'✓ Тема пройдена':'Учимся шаг за шагом'}</span></div><div class="lesson-layout"><aside class="card lesson-nav"><h3>Темы курса</h3>${l.siblings.map((s,i)=>`<a class="${s.id===lid?'active':''}" href="#/lesson/${s.id}"><span>${s.completed?'✓':String(i+1).padStart(2,'0')}</span>${esc(s.title)}</a>`).join('')}</aside><div class="lesson-main"><header class="lesson-header"><div class="eyebrow">${l.topic.minutes} МИНУТ · ТЕОРИЯ И ПРАКТИКА</div><h1>${esc(l.topic.title)}</h1><p>${esc(l.topic.objective)}</p></header>${body}<div class="row between" style="margin-top:23px"><a class="text-link" href="#/course/${l.course_id}">← К дорожной карте</a>${next?`<a class="btn secondary" href="#/lesson/${next.id}">Следующая тема ${icon('arrow',15)}</a>`:`<a class="btn secondary" href="#/questions/${l.course_id}">К экзаменационным вопросам →</a>`}</div></div></div>`,'Урок');
}
async function questionsPage(cid,id){
  const [c,q]=await Promise.all([api('/courses/'+cid),api('/courses/'+cid+'/answers')]);if(id!==renderId)return;current=c;
  const ready=q.questions.filter(x=>x.answers.length).length;
  shell(`${courseBanner(c)}${courseTabs(cid,'questions')}<div class="section-heading"><h2>Вопросы к экзамену</h2><span class="muted small">${ready} из ${q.questions.length} вопросов с материалами</span></div><div class="notice info" style="margin-bottom:22px">Ответы появляются вместе с уроками. «Ответ подготовлен» означает наличие материала, а не подтвержденное освоение темы.</div>${q.questions.map(x=>`<details class="card question-card"><summary><span class="question-number">${String(x.number).padStart(2,'0')}</span><span class="grow">${esc(x.text)}</span><span class="badge ${x.answers.length?'success':''}">${x.answers.length?'Есть материал':'В плане'}</span></summary><div class="answer-body">${x.answers.length?x.answers.map(a=>`<h4>${a.mode==='demo'?'ДЕМО · ОПОРНЫЙ ФРАГМЕНТ':'КРАТКИЙ ОТВЕТ'}</h4><p>${esc(a.short)}</p><h4>РАЗВЕРНУТЫЙ МАТЕРИАЛ</h4><p>${esc(a.full)}</p>${sources(a.source_ids)}`).join(''):'<p>Откройте связанную тему и подготовьте материал урока.</p>'}<div class="row" style="margin-top:20px">${x.lessons.map(l=>`<a class="btn secondary small" href="#/lesson/${l.id}">${l.completed?'✓ ':''}К теме →</a>`).join('')}</div></div></details>`).join('')||'<div class="card empty"><h3>Список пока пуст</h3><p>Добавьте вопросы в настройках материалов курса.</p></div>'}`,'Экзаменационные вопросы');
}
async function examPage(cid,id){
  const [c,state]=await Promise.all([api('/courses/'+cid),api('/courses/'+cid+'/exam')]);if(id!==renderId)return;current=c;
  const e=state.exam, jobsList=state.jobs||[];jobsList.filter(j=>activeStates.includes(j.state)).forEach(j=>watchIds.add(j.id));
  if(state.eligible&&!e&&config.ai_mode!=='demo'&&!c.active_jobs.length){await api('/courses/'+cid+'/exam',{method:'POST'});await render(true);return;}
  if(c.active_jobs.length)c.active_jobs.forEach(j=>watchIds.add(j.id));
  const weak=state.weaknesses.filter(x=>x.wrong>0);
  const result=e?.attempts?.[0]?.result;
  let body;
  if(!state.eligible)body=`<div class="card padded"><h2>Сначала завершим обучение</h2><p>Пройдено ${c.completed} из ${c.total} тем. После всех тем итоговый тест подготовится автоматически.</p><a class="btn" href="#/course/${cid}">Продолжить обучение</a></div>`;
  else if(!e?.content?.items)body=`${latestRelevantJobs(jobsList).map(jobBox).join('')}<div class="card padded"><h2>Подготавливаем персональный тест</h2><p>AI составляет новые вопросы по методичке и проверяет их правильность.</p>${!c.active_jobs.length?`<button class="btn" data-action="prepare-exam" data-id="${cid}">Подготовить тест</button>`:'<p><span class="spinner"></span> Дождитесь завершения AI-обработки.</p>'}</div>`;
  else body=`${result?`<section class="card padded"><h2>${result.score} / 100 · ${result.passed?'Тест пройден':'Нужно повторить'}</h2><p>Порог прохождения — 70%. Можно открыть темы с ошибками и затем пройти новый вариант.</p>${result.items.map((r,i)=>`<div class="notice ${r.correct?'info':''}"><strong>${i+1}. ${r.correct?'Верно':'Ошибка'}</strong><p>${esc(e.content.items.find(t=>t.id===r.id)?.prompt)}</p><p>${esc(r.explanation)}</p>${!r.correct?`<a href="#/lesson/${r.lesson_id}">Повторить тему →</a>`:''}</div>`).join('')}<button class="btn" data-action="prepare-exam" data-id="${cid}">Новый вариант с учётом ошибок</button></section>`:`<form id="exam-form" data-exam="${e.id}" class="card padded"><h2>Итоговая проверка</h2>${e.content.items.map((t,i)=>`<fieldset class="task"><legend><strong>${i+1}. ${esc(t.prompt)}</strong></legend>${t.options.map((opt,j)=>`<label class="option"><input type="radio" name="exam-${t.id}" value="${j}" required><span>${esc(opt)}</span></label>`).join('')}</fieldset>`).join('')}<button class="btn" type="submit">Завершить тест и показать разбор</button></form>`}`;
  shell(`${courseBanner(c)}${courseTabs(cid,'exam')}<div class="notice info" style="margin-bottom:20px">10 вопросов. ${weak.length?'Около 70% заданий — по темам с прошлыми ошибками, остальные — обзор курса.':'Ошибок с оценкой пока не было: вопросы распределены по всем темам.'} Самопроверки без оценки не считаются доказательством ошибки.</div>${weak.length?`<details class="card padded" style="margin-bottom:20px"><summary>Темы, которым уделим больше внимания</summary>${weak.map(w=>`<p>${esc(w.title)} · ошибок: ${w.wrong}</p>`).join('')}</details>`:''}${body}`,'Итоговый тест');
}
async function logPage(cid,id){
  const [c,runs]=await Promise.all([api('/courses/'+cid),api('/courses/'+cid+'/runs')]);if(id!==renderId)return;current=c;
  watchIds=new Set(c.active_jobs.map(j=>j.id));
  shell(`${courseBanner(c)}${courseTabs(cid,'log')}<div class="section-heading"><h2>Как работает ваш AI-оркестратор</h2><button class="btn secondary small" data-action="refresh">Обновить</button></div><div class="notice info" style="margin-bottom:22px">Поиск → CourseAgent → проверка структуры → ReviewerAgent → исправление или сохранение. Максимум 3 версии. В деморежиме генератор шаблонный, проверка — программная.</div>${latestRelevantJobs(c.recent_jobs).map(jobBox).join('')}${runs.map(r=>`<details class="card run-card"><summary><div class="row between"><div class="row"><span class="badge accent">${esc(r.role)}</span>${r.payload.check_type?`<span class="badge">${({ai:"AI-проверка",programmatic:"Проверка программой",ai_error:"Ошибка AI-проверки"})[r.payload.check_type]||esc(r.payload.check_type)}</span>`:""}<strong>${stages[r.kind]} · версия ${r.revision}</strong></div><time>${new Date(r.created*1000).toLocaleString('ru-RU')}</time></div></summary><pre>${esc(JSON.stringify(r.payload,null,2))}</pre></details>`).join('')||'<div class="card empty"><h3>История появится после генерации</h3><p>Здесь сохраняются результаты, замечания проверяющего и версии исправлений.</p></div>'}`,'Журнал AI');
}
async function settingsPage(cid,id){
  const c=await api('/courses/'+cid);if(id!==renderId)return;current=c;
  shell(`${courseBanner(c)}${courseTabs(cid,'settings')}<div class="settings-grid"><form id="schedule-form" data-course="${cid}" class="card padded"><div class="form-title">${icon('calendar',20)}<h2>План под ваше расписание</h2></div><p class="small muted" style="margin-bottom:20px">${c.status==='ready'?'Завершенные темы и попытки сохранятся. Оставшиеся занятия распределятся заново, начиная с выбранной даты.':'Измените время подготовки перед генерацией плана.'}</p><div class="field"><label for="level">Ваш уровень знаний</label><select id="level" name="level">${Object.entries(levelLabels).map(([v,t])=>`<option value="${v}" ${v===c.level?'selected':''}>${t}</option>`).join('')}</select><small>Выберите уровень по своим знаниям. Смена уровня сама по себе не означает готовность к экзамену.</small></div>${scheduleFields(c.schedule)}<button type="button" class="btn secondary" data-action="check-time" data-id="${cid}">Проверить, хватит ли времени</button><div id="time-check" aria-live="polite"></div><p class="small muted">Готовые уроки сохранятся. Новые будут учитывать выбранный уровень; время оставшихся тем пересчитается.</p><button class="btn" style="margin-top:22px" type="submit">${c.status==='ready'?'Перепланировать занятия':'Сохранить уровень и расписание'}</button><div id="form-error" class="form-error" role="alert"></div></form><div class="card padded" style="margin-top:22px"><h3>Материалы курса</h3><div style="margin-top:17px">${c.documents.map(d=>`<div class="document-row">${icon('file')}<span class="grow wrap">${esc(d.name)}</span><button class="text-link" data-action="preview" data-id="${d.id}">Открыть</button></div>`).join('')}</div><p class="small muted">Если в старом курсе заголовки попали в темы или задания получились бессмысленными, создайте исправленную копию. Программа заново прочитает исходные файлы; старый курс останется доступен.</p><button type="button" class="btn secondary" data-action="repair-copy" data-id="${cid}">Создать исправленную копию курса</button></div><section class="danger-zone"><h3>Удаление курса</h3><p>Будут удалены материалы, занятия, ответы и весь прогресс этого курса.</p><button class="btn danger" data-action="confirm-delete" data-id="${cid}">Удалить курс</button></section></div>`,'Настройки курса');updateBudget();
}
async function render(preserveScroll=false){
  const scroll=window.scrollY;const id=++renderId;clearTimeout(pollTimer);watchIds=new Set();
  if(!user){authPage();return;}
  const parts=(location.hash.slice(1)||'/').split('/').filter(Boolean);
  shell(loading(), 'Загрузка');
  try{
    if(parts[0]==='new')newCourse();
    else if(parts[0]==='course'&&parts[1])await coursePage(parts[1],id);
    else if(parts[0]==='lesson'&&parts[1])await lessonPage(parts[1],id);
    else if(parts[0]==='questions'&&parts[1])await questionsPage(parts[1],id);
    else if(parts[0]==='exam'&&parts[1])await examPage(parts[1],id);
    else if(parts[0]==='log'&&parts[1])await logPage(parts[1],id);
    else if(parts[0]==='settings'&&parts[1])await settingsPage(parts[1],id);
    else await dashboard(id);
  }catch(e){if(id===renderId&&user)shell(errorPage(e));}
  if(id!==renderId)return;
  window.scrollTo(0,preserveScroll?scroll:0);if(watchIds.size)pollTimer=setTimeout(pollJobs,2000);
}
async function pollJobs(){
  if(!user||!watchIds.size)return;
  const hash=location.hash;let finished=false;
  for(const jid of [...watchIds]){
    try{
      const j=await api('/jobs/'+jid);const box=$(`[data-job="${jid}"]`);
      if(box){const stage=$('[data-stage]',box);if(stage)stage.textContent=j.stage;}
      if(!activeStates.includes(j.state)){
        watchIds.delete(jid);finished=true;
        if(!notified.has(jid)){toast(j.state==='completed'?`${stages[j.kind]}: готово`:(j.error||'Нужны изменения'),j.state!=='completed');notified.add(jid);}
      }
    }catch{watchIds.delete(jid);}
  }
  if(finished&&hash===location.hash)await render(true);
  else if(watchIds.size)pollTimer=setTimeout(pollJobs,2500);
}

document.addEventListener('input',e=>{if(e.target.closest('#new-course-form,#schedule-form')){updateBudget();const check=$('#time-check');if(check)check.textContent='';}});
document.addEventListener('change',e=>{
  if(e.target.id==='methodology'){
    const files=[...e.target.files],box=$('#methodology-files');
    e.target.setCustomValidity(files.length>40?'Выберите не больше 40 методичек':'');
    if(box)box.innerHTML=files.length?`Выбрано файлов: <b>${files.length}</b><br>${files.map(x=>esc(x.name)).join('<br>')}`:'Файлы не выбраны';
  }
  if(e.target.closest('#new-course-form,#schedule-form')){updateBudget();const check=$('#time-check');if(check)check.textContent='';}
});
document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-action]');if(!b||b.disabled)return;
  const action=b.dataset.action,jid=b.dataset.id;e.preventDefault();
  if(action==='close-modal'){$('#modal').close();return;}
  if(action==='auth-toggle'){authMode=authMode==='login'?'register':'login';authPage();return;}
  if(action==='filter'){dashboardFilter=b.dataset.value;render();return;}
  if(action==='help'){
    modal('Как устроена Траектория',`<div class="stack"><p><b>1. Добавьте предмет.</b> Выберите один или несколько PDF, DOCX или TXT и добавьте контрольные вопросы.</p><p><b>2. Выберите ритм.</b> Срок, дни недели и минуты занятий. Сначала проверьте извлеченные вопросы, затем создайте план.</p><p><b>3. Учитесь по темам.</b> Откройте урок, подготовьте материал, прочитайте теорию и выполните практику.</p><p><b>4. Отслеживайте прогресс.</b> Тема завершается после прочтения теории и обязательной практики. В офлайн-уроках без теста нужно самостоятельно сверить ответ с критериями и подтвердить это; AI-балл не выставляется. История хранится в вашей учетной записи.</p><div class="notice info">${config.ai_mode==='demo'?'Деморежим: шаблонный план, исходные фрагменты и тесты. Открытые ответы сохраняются для самопроверки. Для AI-режима запустите connect-ai.bat, выберите Ollama или Gemini и перезапустите приложение.':'AI-режим: генератор создаёт материалы, отдельный проверяющий проверяет их по источникам. Облачные провайдеры получают фрагменты; локальная Ollama обрабатывает их на настроенном сервере.'}</div><p class="small">Версия ${esc(config.version)} · ${esc(config.database)} · локальная очередь агентов. Компилятора нет: код анализируется без выполнения.</p></div>`);return;
  }
  if(action==='confirm-delete'){modal('Удалить курс?',`<p>Это действие удалит все материалы и прогресс курса. Восстановить их из приложения нельзя.</p><div class="modal-actions"><button class="btn secondary" data-action="close-modal">Отмена</button><button class="btn danger" data-action="delete" data-id="${jid}">Удалить полностью</button></div>`);return;}
  b.disabled=true;
  try{
    if(action==='logout'){await api('/auth/logout',{method:'POST'});user=null;authMode='login';render();}
    else if(action==='self-confirm'){await api('/attempts/'+jid+'/self-check',{method:'POST'});await render(true);}
    else if(action==='repair-copy'){const c=await api('/courses/'+jid+'/repair-copy',{method:'POST'});toast('Копия создана. Проверьте вопросы и постройте новый план.');go('/course/'+c.id);}
    else if(action==='check-time'){
      const f=$('#schedule-form');if(!f.reportValidity())return;
      const r=await api('/courses/'+jid+'/replan-preview',{method:'POST',body:{...readSchedule(f),level:new FormData(f).get('level')}});
      $('#time-check').innerHTML=`<div class="notice info"><strong>${r.fits?'По предварительной оценке времени хватает':'Времени недостаточно'}</strong><p>Нужно: ${r.required_minutes} мин. (${hours(r.required_minutes)}). Доступно: ${r.available_minutes} мин. (${hours(r.available_minutes)}). Осталось тем: ${r.remaining_topics}.</p><p>${esc(r.note)}</p><small>Это проверка без сохранения. После изменения уровня проверьте время ещё раз и сохраните настройки.</small></div>`;
    }
    else if(action==='refresh')await render(true);
    else if(action==='demo'){const c=await api('/demo',{method:'POST'});go('/course/'+c.id);}
    else if(action==='generate-plan'){
      const form=$('#questions-form');if(form){const values=new FormData(form).get('questions').split('\n').map(x=>x.replace(/^\d+[.)]\s*/, '').trim()).filter(Boolean);await api('/courses/'+jid+'/questions',{method:'PUT',body:{questions:values}});}
      await api('/courses/'+jid+'/generate',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()}});await render(true);
    }
    else if(action==='prepare-exam'){await api('/courses/'+jid+'/exam',{method:'POST'});await render(true);}
    else if(action==='generate-lesson'){await api('/lessons/'+jid+'/generate',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()}});await render(true);}
    else if(action==='retry-job'){await api('/jobs/'+jid+'/retry',{method:'POST'});await render(true);}
    else if(action==='cancel-job'){await api('/jobs/'+jid+'/cancel',{method:'POST'});await render(true);}
    else if(action==='read'){const r=await api('/lessons/'+jid+'/read',{method:'PUT'});toast(r.completed?'Тема пройдена!':'Теория прочитана. Переходите к практике.');await render(true);}
    else if(action==='preview'){const p=await api('/documents/'+jid+'/preview');modal(p.name,`${p.truncated?'<p>Показаны первые 30 000 символов.</p>':''}<pre>${esc(p.text)}</pre>`);}
    else if(action==='source'){const s=await api('/sources/'+jid);modal(s.document,`<p>${esc(s.locator)}</p><pre>${esc(s.text)}</pre>`);}
    else if(action==='delete'){await api('/courses/'+jid,{method:'DELETE'});$('#modal').close();toast('Курс удален');go('/');}
    else if(action==='agenda'){const c=await api('/courses/'+jid);modal('Расписание занятий',`<div class="stack">${(c.plan.sessions||[]).map(s=>`<div class="document-row"><strong>${dateLabel(s.date)}</strong><span class="grow">${esc(s.title)}${s.part>1?' · часть '+s.part:''}</span><span>${s.minutes} мин.</span></div>`).join('')}</div>`);}
  }catch(err){toast(err.message,true);}finally{b.disabled=false;}
});

document.addEventListener('submit',async e=>{
  const f=e.target;if(!(f instanceof HTMLFormElement))return;e.preventDefault();
  const submit=$('button[type="submit"],button:not([type])',f);if(submit?.disabled)return;
  if(submit)submit.disabled=true;const data=new FormData(f);
  try{
    if(f.id==='auth-form'){
      $('#auth-error').textContent='';user=await api('/auth/'+(authMode==='register'?'register':'login'),{method:'POST',body:{email:data.get('email'),password:data.get('password'),name:data.get('name')||'Студент'}});await render();
    }else if(f.id==='new-course-form'){
      $('#form-error').textContent='';const schedule=readSchedule(f);
      const qtext=data.get('questions').trim(),qfile=data.get('questions_file'),methodologies=data.getAll('methodology').filter(x=>x?.size);
      if(!qtext&&!qfile?.size)throw new Error('Введите контрольные вопросы или загрузите файл с ними');
      if(!methodologies.length)throw new Error('Выберите хотя бы одну методичку');
      if(methodologies.length>40)throw new Error('Можно загрузить не больше 40 методичек в один курс');
      for(const file of [...methodologies,qfile])if(file?.size>20*1024*1024)throw new Error(`Файл «${file.name}» больше 20 МБ`);
      submit.textContent='Сохраняем материалы…';
      const c=await api('/courses',{method:'POST',body:{title:data.get('title'),level:data.get('level'),schedule}});
      try{
        await uploadMethodologies(c.id,methodologies,(n,total,name)=>submit.textContent=`Загружаем ${n} из ${total}: ${name}`);
        if(qfile?.size){const qf=new FormData();qf.append('file',qfile);qf.append('role','questions');await api('/courses/'+c.id+'/documents',{method:'POST',body:qf});}
        if(qtext)await api('/courses/'+c.id+'/questions',{method:'PUT',body:{questions:qtext.split('\n').map(x=>x.replace(/^\d+[.)]\s*/, '').trim()).filter(Boolean)}});
        await api('/courses/'+c.id+'/generate',{method:'POST'});toast('Материалы загружены. AI анализирует их и готовит план.');
      }catch(err){toast(err.message+' Курс сохранен как черновик.',true);}
      go('/course/'+c.id);
    }else if(f.id==='questions-form'){
      await api('/courses/'+f.dataset.course+'/questions',{method:'PUT',body:{questions:data.get('questions').split('\n').map(x=>x.replace(/^\d+[.)]\s*/, '').trim()).filter(Boolean)}});toast('Вопросы сохранены');await render(true);
    }else if(f.id==='upload-extra-form'){
      const files=data.getAll('file').filter(x=>x?.size);
      if(!files.length)throw new Error('Выберите хотя бы один файл');
      if(files.some(x=>x.size>20*1024*1024))throw new Error('Каждый файл должен быть не больше 20 МБ');
      await uploadMethodologies(f.dataset.course,files,(n,total)=>submit.textContent=`Загружаем ${n} из ${total}…`);
      toast(`Загружено методичек: ${files.length}`);await render(true);
    }else if(f.id==='schedule-form'){
      await api('/courses/'+f.dataset.course+'/replan',{method:'POST',body:{...readSchedule(f),level:data.get('level')}});toast('Уровень и расписание сохранены');go('/course/'+f.dataset.course);
    }else if(f.id==='exam-form'){
      const answers={};for(const [key,value] of data)if(key.startsWith('exam-'))answers[key.slice(5)]=Number(value);
      await api('/exams/'+f.dataset.exam+'/attempts',{method:'POST',body:{answers}});await render(true);
    }else if(f.dataset.task){
      const a=await api('/lessons/'+f.dataset.lesson+'/tasks/'+enc(f.dataset.task)+'/attempts',{method:'POST',body:{answer:data.get('answer')}});
      toast(a.completed?'Тема пройдена!':a.job?'Ответ отправлен на проверку':'Ответ сохранен');if(a.completed){const c=await api('/courses/'+current.course_id);if(c.total&&c.completed===c.total){go('/exam/'+c.id);return;}}await render(true);
    }
  }catch(err){const box=$('#auth-error',f)||$('#form-error',f);if(box)box.textContent=err.message;else toast(err.message,true);}
  finally{if(submit){submit.disabled=false;if(f.id==='new-course-form')submit.textContent='Сохранить и проверить материалы →';if(f.id==='upload-extra-form')submit.textContent='Загрузить';}}
});

window.addEventListener('hashchange',()=>render());
$('#modal').addEventListener('click',e=>{if(e.target===$('#modal')){const r=$('#modal').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('#modal').close();}});
async function boot(){try{config=await api('/config');user=await api('/me').catch(()=>null);await render();}catch(e){$('#app').innerHTML=errorPage(e);}}
boot();
