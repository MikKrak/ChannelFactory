"""studio_views.py — компоненты редакционного кабинета.

Формирует HTML из переданных данных. Не читает базу и не вызывает сервисы.
Только один существующий проект; многопроектное хранение не имитируется.
"""
from html import escape
from urllib.parse import urlsplit, quote

PROJECT = 'СССР — Свой сад своими руками'
BASE = '/studio/cccp'
STATUSES = {'draft': 'Черновик', 'ready': 'Готов к публикации', 'published': 'Опубликован'}


def e(value):
    """Экранировать значения перед выводом в HTML и атрибутах."""
    return escape(str(value or ''), quote=True)


def url(value):
    """Разрешить в изображениях и внешних ссылках только HTTP(S)."""
    value = str(value or '')
    try:
        parts = urlsplit(value)
        return e(value) if parts.scheme in ('http', 'https') and parts.netloc else ''
    except ValueError:
        return ''


def ident(value):
    return quote(str(value), safe='')


def badge(status):
    return f'<span class="badge {e(status)}">{e(STATUSES.get(status, status))}</span>'


def notice(text, kind='info'):
    return f'<div class="notice {e(kind)}" role="status">{e(text)}</div>' if text else ''


def layout(title, body, active='overview', message='', global_scope=False):
    """Общая оболочка всех экранов, с обычными серверными ссылками."""
    nav = ''.join(f'<a class="{"active" if active == key else ""}" href="{href}"><span>{symbol}</span>{label}</a>' for key, href, symbol, label in [
        ('overview', BASE, '◫', 'Обзор проекта'),
        ('materials', BASE + '/materials', '▤', 'Материалы'),
        ('sources', BASE + '/sources', '◉', 'Источники'),
        ('posts', BASE + '/posts', '▣', 'Редакционные посты'),
        ('inbox', BASE + '/inbox', '✉', 'Обращения')])
    if global_scope:
        nav = '<a href="/studio/library/sources">Источники</a><a href="/studio/library/materials">Общие материалы</a><a href="/studio/library/cleanup">Просмотр очистки</a>'
    scope_label = 'ОБЩАЯ БИБЛИОТЕКА' if global_scope else 'ТЕКУЩИЙ ПРОЕКТ'
    project_name = '<b>Библиотека фабрики</b>' if global_scope else '<span class="leaf">♧</span><b>СССР<small>Свой сад своими руками</small></b>'
    breadcrumb = 'Общая библиотека' if global_scope else 'СССР'
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} · ChannelFactory</title>
<link rel="stylesheet" href="/static/studio.css"><script defer src="/static/studio.js"></script></head><body>
<aside class="sidebar"><a class="brand" href="/studio"><span class="brandmark">↗</span>ChannelFactory</a>
<a class="all-projects" href="/studio">← Все проекты</a><div class="project-label">{scope_label}</div>
<div class="project-name">{project_name}</div>
<nav aria-label="Разделы">{nav}</nav><a class="all-projects" href="/studio/library/sources">Общая библиотека →</a><div class="sidebar-foot"><span class="online"></span> Локальное приложение<small>Рабочие данные · Supabase</small></div></aside>
<div class="workspace"><header><span>Моё пространство <i>/</i> {breadcrumb} <i>/</i> <b>{e(title)}</b></span><span class="user">МК</span></header>
<main>{notice(message)}{body}<footer>ChannelFactory · Редакционная мастерская <span>Подготовка постов без автоматической отправки</span></footer></main></div></body></html>'''


def heading(kicker, title, subtitle='', action=''):
    return f'<div class="heading"><div><div class="eyebrow">{e(kicker)}</div><h1>{e(title)}</h1><p class="muted">{e(subtitle)}</p></div>{action}</div>'


def projects():
    body = heading('ТВОЁ РАБОЧЕЕ ПРОСТРАНСТВО', 'Проекты', 'Открой проект, чтобы продолжить редакционную работу.')
    body += f'''<div class="project-grid"><a class="project-card" href="{BASE}"><div class="project-cover"><span>♧</span><small>САД И ОГОРОД</small></div><div class="project-card-body"><span class="badge ready">Подключён</span><h2>{PROJECT}</h2><p class="muted">Материалы, черновики и готовые посты в одном рабочем месте.</p><div class="project-bottom">Telegram · @cccp_service_bot <b>Открыть →</b></div></div></a>
<div class="project-placeholder"><span>＋</span><h3>Другие проекты</h3><p>Добавление проектов появится после согласования их хранения и разделения данных.</p></div></div>'''
    return layout('Проекты', body, active='')


def overview(material_count, posts, counts):
    body = heading('ПРОЕКТ · САД И ОГОРОД', PROJECT, 'От интересного материала к готовой публикации.', f'<a class="button" href="{BASE}/materials">Выбрать материал →</a>')
    body += '<div class="stats">' + ''.join(f'<a class="stat" href="{href}"><span>{label}</span><strong>{number}</strong><small>{hint}</small></a>' for label, number, hint, href in [
        ('Материалы', material_count, 'В общей библиотеке установки', BASE + '/materials'),
        ('Черновики', counts['draft'], 'Можно продолжить редактирование', BASE + '/posts?status=draft'),
        ('Готовые посты', counts['ready'], 'Готовность текста · результат в журнале', BASE + '/posts?status=ready')]) + '</div>'
    body += '<div class="two-panels"><section class="panel"><div class="section-heading"><h2>Продолжить работу</h2><a href="'+BASE+'/posts">Все посты →</a></div>'
    drafts = [p for p in posts if p.get('status') == 'draft'][:4]
    body += ''.join(f'<a class="record" href="{BASE}/posts/{ident(p["id"])}"><div><b>{e(p.get("title") or "Без названия")}</b><small>Редакционный черновик</small></div><span>→</span></a>' for p in drafts) or '<p class="empty">Пока нет черновиков. Начни с выбора материала.</p>'
    body += '''</section><section class="panel guide"><div class="eyebrow">РЕДАКЦИОННЫЙ ПУТЬ</div><h2>Три шага до готового поста</h2><ol><li><b>Выбери материал</b><p>Открой источник и загрузи содержание.</p></li><li><b>Подготовь черновик</b><p>Сравни текст с оригиналом и проверь предпросмотр.</p></li><li><b>Отметь готовым</b><p>Сохрани проверенный пост для будущей публикации.</p></li></ol></section></div>'''
    body += notice('Сейчас работает один проект. Общие источники и материалы доступны через библиотеку; управление другими проектами пока не подключено.')
    return layout('Обзор', body)


def material_list(items, total, offset, limit, query):
    body = heading('ПРОЕКТ СССР', 'Материалы', f'Доступно материалов: {total}. Выбери статью для подготовки поста.', '<a class="button secondary" href="/studio/library/materials">Общая библиотека →</a>')
    body += f'<form class="searchbar" method="get"><label for="search">Поиск по заголовку</label><input id="search" name="q" value="{e(query)}" placeholder="Например, земляника"><button class="button secondary">Найти</button></form>'
    body += '<section class="panel list-panel">'
    for item in items:
        body += f'<a class="record" href="{BASE}/materials/{ident(item["id"])}"><span class="record-icon">▤</span><div><b>{e(item.get("title") or "Без названия")}</b><small>{e((item.get("published_at") or "")[:10])} · {e(urlsplit(item.get("url") or "").hostname or "Источник")}</small></div><span class="record-action">Открыть →</span></a>'
    body += '' if items else '<div class="empty">Материалы не найдены. Измени запрос или вернись к полному списку.</div>'
    body += '</section><div class="pagination">'
    if offset:
        body += f'<a class="button secondary" href="?offset={max(0,offset-limit)}&q={quote(query)}">← Назад</a>'
    if offset + len(items) < total:
        body += f'<a class="button secondary" href="?offset={offset+limit}&q={quote(query)}">Следующие →</a>'
    return layout('Материалы', body+'</div>', 'materials')


def editor_form(action, text, image_url, source_url, ready=False, error='', saved=False):
    """Единая форма текста и предпросмотра для материала и черновика."""
    photo = f'<img src="{url(image_url)}" alt="Изображение публикации" referrerpolicy="no-referrer">' if url(image_url) else '<div class="no-image">Без изображения</div>'
    return f'''<div class="editor-grid"><section class="panel"><div class="section-heading"><h2>Текст поста</h2><span class="muted">Редактор</span></div>{notice(error, 'error')}
<form method="post" action="{e(action)}" data-editor><label class="sr-only" for="post-text">Текст поста</label><textarea id="post-text" name="post_text" rows="17" required placeholder="Напиши текст публикации…">{e(text)}</textarea>
<div class="editor-meta"><span id="char-count"></span><span id="dirty-status" role="status">{'Сохранено' if saved else 'Изменения ещё не сохранены'}</span></div>
<div class="form-actions"><button class="button secondary" name="action" value="save">Сохранить черновик</button>{'<button class="button" name="action" value="ready">Готов к публикации ✓</button>' if ready else '<span class="muted">Сначала сохрани черновик</span>'}</div><p class="hint">Кнопка «Готов» только меняет статус. В Telegram ничего не отправляется.</p></form></section>
<section class="preview-column"><div class="preview-caption">ПРЕДПРОСМОТР ПОСТА</div><div class="telegram-preview">{photo}<div class="preview-body"><b class="channel-name">СССР · Свой сад своими руками</b><div id="post-preview" class="prose">{e(text)}</div>{f'<a class="source-link" href="{url(source_url)}" target="_blank" rel="noopener noreferrer">Источник ↗</a>' if url(source_url) else ''}<small class="preview-stamp">Предпросмотр · не опубликовано</small></div></div><p class="hint">Пример отображения. Окончательный вид зависит от Telegram.</p></section></div>'''


def material_page(article, draft=None, text=None, error='', message=''):
    from editor import prepare_post
    content = article.get('content') or {}
    if text is None:
        text = next((b.get('content', '') for b in prepare_post(article)['blocks'] if b.get('type') == 'text'), '')
    body = f'<a class="back" href="{BASE}/materials">← Материалы</a>' + heading('ПОДГОТОВКА ПУБЛИКАЦИИ', article.get('title') or 'Без названия', 'Исходная статья, редакционный текст и предпросмотр.')
    body += '<div class="workflow"><span class="done">1 · Материал</span><span>→</span><span class="current">2 · Черновик</span><span>→</span><span>3 · Готовый пост</span></div>'
    if draft:
        body += notice('У этого материала уже есть черновик. Продолжи редактировать его, чтобы не перезаписать сохранённый текст.')
        body += f'<p><a class="button" href="{BASE}/posts/{ident(draft["id"])}">Открыть существующий черновик →</a></p>'
    else:
        body += editor_form(f'{BASE}/materials/{ident(article["id"])}/draft', text, content.get('image_url'), article.get('url'), error=error)
    source = url(article.get('url'))
    body += f'<section class="panel source-panel"><div class="section-heading"><h2>Исходный материал</h2>{f"<a href=\"{source}\" target=\"_blank\" rel=\"noopener noreferrer\">Открыть оригинал ↗</a>" if source else ""}</div>'
    if content.get('text'):
        body += f'<details><summary>Прочитать исходную статью</summary><div class="prose original">{e(content["text"])}</div></details>'
    else:
        body += f'<p class="muted">Полный текст ещё не загружен. Можно загрузить его с сайта или написать пост вручную.</p><form method="post" action="{BASE}/materials/{ident(article["id"])}/load"><button class="button secondary">Загрузить содержание статьи</button></form>'
    return layout('Подготовка поста', body+'</section>', 'materials', message)


def post_list(items, status, offset, limit):
    body = heading('РЕДАКЦИЯ', 'Посты', 'Продолжай черновики и проверяй готовые публикации.')
    body += '<nav class="tabs" aria-label="Статусы">' + ''.join(f'<a class="{"active" if status == s else ""}" href="?status={s}">{label}</a>' for s, label in [('all','Все'),('draft','Черновики'),('ready','Готовые'),('published','Опубликованные')]) + '</nav><section class="panel list-panel">'
    body += ''.join(f'<a class="record" href="{BASE}/posts/{ident(p["id"])}"><span class="record-icon">▣</span><div><b>{e(p.get("title") or "Без названия")}</b><small>Изменено: {e((p.get("updated_at") or "")[:16].replace("T"," "))} UTC</small></div>{badge(p.get("status"))}<span>→</span></a>' for p in items)
    if not items:
        body += f'<div class="empty">Постов пока нет.<p><a href="{BASE}/materials">Выбрать исходный материал →</a></p></div>'
    body += '</section><div class="pagination">'
    if offset:
        body += f'<a class="button secondary" href="?status={status}&offset={max(0,offset-limit)}">← Назад</a>'
    if len(items) == limit:
        body += f'<a class="button secondary" href="?status={status}&offset={offset+limit}">Следующие →</a>'
    return layout('Посты', body+'</div>', 'posts')


def post_page(post, text=None, error='', message='', article=None, publication=''):
    submitted_text = text
    blocks = post.get('blocks') or []
    if text is None:
        text = '\n\n'.join(b.get('content') or '' for b in blocks if b.get('type') == 'text')
    image = next((b.get('url') for b in reversed(blocks) if b.get('type') == 'image'), '')
    source = next((b.get('url') for b in blocks if b.get('type') == 'source'), '')
    body = f'<a class="back" href="{BASE}/posts">← Редакционные посты</a>' + heading('РЕДАКЦИОННЫЙ ПОСТ', post.get('title') or 'Без названия', '', badge(post.get('status')))
    if post.get('status') == 'draft':
        body += editor_form(f'{BASE}/posts/{ident(post["id"])}/save', text, image, source, ready=True, error=error, saved=not error)
    else:
        body += notice('Редакционный текст готов. Фактический результат отправки проверь в журнале публикаций.' if post.get('status') == 'ready' else 'Пост отмечен опубликованным. Здесь показана сохранённая версия.')
        body += f'<section class="panel read-post">{f"<img src=\"{url(image)}\" alt=\"Изображение поста\">" if url(image) else ""}<div class="prose">{e(text)}</div>{f"<p><a href=\"{url(source)}\" target=\"_blank\" rel=\"noopener noreferrer\">Источник ↗</a></p>" if url(source) else ""}</section>'
        if post.get('status') == 'ready':
            body += f'<form method="post" action="{BASE}/posts/{ident(post["id"])}/draft"><button class="button secondary">Вернуть на редактирование</button></form>'
    if submitted_text is not None and post.get('status') != 'draft':
        body += '<section class="panel source-panel"><h2>Твой несохранённый текст</h2><p class="muted">Скопируй его перед повторным открытием редактора.</p><textarea readonly rows="10" style="width:100%">' + e(submitted_text) + '</textarea></section>'
    if article:
        body += '<section class="panel source-panel"><h2>Исходная статья</h2><details><summary>Сравнить с оригиналом</summary><div class="prose original">' + e((article.get('content') or {}).get('text') or 'Текст статьи ещё не загружен.') + '</div></details></section>'
    return layout('Редактор поста', body + publication, 'posts', message)
