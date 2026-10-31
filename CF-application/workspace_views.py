"""workspace_views.py — единая оболочка фабрики и выбранного проекта.

Только HTML: навигация, вкладки разделов, панели и сведения выбранного объекта.
Не читает базу, не запускает инструменты и не меняет разрешения операций.
"""
from html import escape
from urllib.parse import urlsplit

PROJECT_BASE = '/studio/cccp'
FACTORY_TOOLS = (
    ('overview', '/studio', '◫', 'Пульт фабрики'),
    ('sources', '/studio/library/sources', '◉', 'Общие источники'),
    ('materials', '/studio/library/materials', '▤', 'Общие материалы'),
    ('cleanup', '/studio/library/cleanup', '⌕', 'Просмотр очистки'),
)
PROJECT_TOOLS = (
    ('overview', PROJECT_BASE, '◫', 'Обзор проекта'),
    ('materials', PROJECT_BASE + '/materials', '▤', 'Материалы проекта'),
    ('sources', PROJECT_BASE + '/sources', '◉', 'Источники проекта'),
    ('posts', PROJECT_BASE + '/posts', '▣', 'Редакционные посты'),
    ('inbox', PROJECT_BASE + '/inbox', '✉', 'Обращения'),
)


def e(value):
    return escape(str(value if value is not None else ''), quote=True)


def safe_link(value):
    """Разрешить только обычный внутренний путь или HTTP(S)-ссылку."""
    value = str(value or '')
    if value.startswith('/') and not value.startswith('//') and '\\' not in value:
        return e(value)
    try:
        parts = urlsplit(value)
        if parts.scheme in ('https', 'http') and parts.hostname and not parts.username and not parts.password:
            return e(value)
    except ValueError:
        pass
    return ''


def inspector(context):
    """Показать переданные свойства, без дублирования форм изменения объекта."""
    if not context:
        return '<div class="inspector-empty"><span>⌕</span><h3>Объект не выбран</h3><p>Открой материал, источник, пост или диалог. Здесь появятся сведения о выбранном объекте.</p></div>'
    body = f'<div class="eyebrow">{e(context.get("kind", "Выбранный объект"))}</div><h3>{e(context.get("title", "Сведения"))}</h3><dl>'
    for label, value in context.get('fields', []):
        body += f'<dt>{e(label)}</dt><dd>{e(value)}</dd>'
    body += '</dl><div class="inspector-links">'
    for label, href in context.get('links', []):
        link = safe_link(href)
        if link:
            external = not str(href).startswith('/')
            body += f'<a href="{link}" {"target=\"_blank\" rel=\"noopener noreferrer\"" if external else ""}>{e(label)} ↗</a>'
    return body + '</div>'


def render(title, body, active='overview', message='', global_scope=False, context=None):
    """Одна оболочка для всех серверных страниц; ссылки работают и без JS."""
    space = 'factory' if global_scope else 'cccp'
    mode = 'Фабрика' if global_scope else 'Проект · СССР'
    tools = FACTORY_TOOLS if global_scope else PROJECT_TOOLS
    selected = next((x for x in tools if x[0] == active), tools[0])
    nav = ''.join(f'<a class="{"active" if key == selected[0] else ""}" href="{href}" data-tool="{key}"><span aria-hidden="true">{symbol}</span>{label}</a>' for key, href, symbol, label in tools)
    if global_scope:
        nav += '<div class="nav-group-label">ПРОЕКТЫ</div><a href="/studio/cccp" data-resume-space="cccp"><span aria-hidden="true">♧</span>СССР · Сад</a>'
    else:
        nav += '<div class="nav-group-label">РЕСУРСЫ ФАБРИКИ</div><a href="/studio/library/sources">Общие источники ↗</a><a href="/studio/library/materials">Общая библиотека ↗</a>'
    crumbs = '<a href="/studio">Фабрика</a>'
    if not global_scope:
        crumbs += '<span aria-hidden="true">/</span><a href="/studio/cccp">СССР</a>'
    if selected[1] != '/studio':
        crumbs += f'<span aria-hidden="true">/</span><a href="{selected[1]}">{e(selected[3])}</a>'
    list_titles = {'overview': {'Обзор', 'Пульт фабрики'}, 'materials': {'Материалы', 'Общая библиотека'}, 'sources': {'Источники'}, 'posts': {'Посты'}, 'inbox': {'Обращения'}, 'cleanup': {'Просмотр очистки'}}
    if title != selected[3] and title not in list_titles.get(active, set()):
        crumbs += f'<span aria-hidden="true">/</span><span aria-current="page">{e(title)}</span>'
    back_to_factory = '<a class="factory-return" href="/studio">← Все проекты</a>' if not global_scope else ''
    note = f'<div class="notice" role="status">{e(message)}</div>' if message else ''
    fallback_tabs = ''.join(f'<a href="{href}" class="{"current" if key == selected[0] else ""}">{e(label)}</a>' for key, href, _, label in tools)
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} · ChannelFactory</title>
<link rel="stylesheet" href="/static/studio.css"><link rel="stylesheet" href="/static/workspace.css">
<script defer src="/static/studio.js"></script><script defer src="/static/workspace.js"></script></head>
<body class="workbench" data-space="{space}" data-tool="{selected[0]}">
<a class="skip-link" href="#workspace-content">К содержимому</a>
<header class="command-bar"><a class="brand" href="/studio" aria-label="ChannelFactory — пульт фабрики"><span class="brandmark" aria-hidden="true">↗</span>ChannelFactory</a>
<nav class="mode-switch" aria-label="Рабочее пространство"><a href="/studio" {"aria-current=\"page\"" if global_scope else ""}>Фабрика</a><a href="/studio/cccp" data-resume-space="cccp" {"aria-current=\"page\"" if not global_scope else ""}>Проект</a></nav>
<label class="project-picker"><span class="sr-only">Выбор проекта</span><select id="project-picker" aria-label="Выбор проекта"><option value="">Выбери проект</option><option value="/studio/cccp" {"selected" if not global_scope else ""}>СССР · Свой сад</option></select></label>
<div class="command-actions"><button type="button" class="icon-button" data-toggle-panel="left" aria-label="Навигация" aria-controls="workspace-navigation" aria-expanded="true" title="Показать или скрыть навигацию">☰ <span>Навигация</span></button><button type="button" class="icon-button" data-toggle-panel="right" aria-label="Сведения" aria-controls="workspace-inspector" aria-expanded="true" title="Показать или скрыть сведения">ⓘ <span>Сведения</span></button></div></header>
<div class="workbench-grid"><aside class="workspace-navigation" id="workspace-navigation" aria-label="Навигация пространства"><div class="panel-caption">{"ФАБРИКА" if global_scope else "ПРОЕКТ СССР"}</div>{back_to_factory}<nav aria-label="Разделы {e(mode)}">{nav}</nav><div class="nav-note">{"Общие ресурсы для всех проектов" if global_scope else "Свой сад своими руками"}</div></aside>
<div class="panel-resizer left-resizer" role="separator" aria-label="Ширина навигации" aria-orientation="vertical" tabindex="0" data-resize-panel="left"></div>
<div class="workspace-center"><div class="workspace-tabs" id="workspace-tabs" aria-label="Открытые инструменты"><noscript>{fallback_tabs}</noscript></div>
<nav class="breadcrumbs" aria-label="Навигационная цепочка">{crumbs}</nav>
<main id="workspace-content" tabindex="-1">{note}{body}</main></div>
<div class="panel-resizer right-resizer" role="separator" aria-label="Ширина сведений" aria-orientation="vertical" tabindex="0" data-resize-panel="right"></div>
<aside class="workspace-inspector" id="workspace-inspector" aria-label="Сведения об объекте"><div class="panel-caption">СВЕДЕНИЯ ОБ ОБЪЕКТЕ</div>{inspector(context)}</aside></div>
<footer class="workspace-status"><span><span class="online" aria-hidden="true"></span>{e(mode)}</span><span id="workspace-save-state" role="status">Изменения — через формы разделов</span><span>Локальное приложение</span></footer>
</body></html>'''
