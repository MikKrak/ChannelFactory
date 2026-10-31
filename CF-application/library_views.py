"""library_views.py — серверные HTML-компоненты общей библиотеки и источников.

Получает готовые данные; не вызывает сеть и не меняет хранилище.
"""
from uuid import uuid4
import studio_views as v
from library import KINDS


def base(project):
    return v.BASE if project else '/studio/library'


def shell(title, body, project=False, message='', context=None):
    active = {'Общая библиотека':'materials','Просмотр очистки':'cleanup'}.get(title,'sources')
    return v.layout(title,body,active,message,global_scope=not project,context=context)


def tabs(project):
    root=base(project)
    return f'<nav class="tabs"><a href="{root}/sources">Источники</a><a href="/studio/library/materials">Общая библиотека материалов</a><a href="{v.BASE}/materials">Отобрано в СССР</a></nav>'


def source_list(items, project=False, message=''):
    root=base(project)
    body=v.heading('ПРОЕКТ' if project else 'ФАБРИКА','Источники проекта' if project else 'Общие источники',
        'Настройки действуют только для этого проекта. Подключай источники из общего каталога ниже.' if project else 'Общие сведения и использующие проекты. Подключение выполняется внутри проекта.',
        '<a class="button secondary" href="/studio/library/sources/new">＋ Создать общий источник ↗</a>' if project else '<a class="button" href="/studio/library/sources/new">＋ Новый источник</a>')
    groups=[('Подключены к проекту',[x for x in items if x.get('connection')]),('Доступны для подключения',[x for x in items if not x.get('connection')])] if project else [('Общий каталог',items)]
    for title,rows in groups:
        body+=f'<section class="panel source-panel"><h2>{title}</h2>'
        if not rows:body+='<p class="muted">Пока нет источников.</p>'
        for item in rows:
            sid=v.ident(item['id']);conn=item.get('connection')
            uses=', '.join(x.get('cf_projects',{}).get('name',x['project_code']) for x in item['projects']) or 'Пока не используется'
            body+=f'<div class="record"><div><a href="{root}/sources/{sid}"><b>{v.e(item["name"])}</b></a><small>{v.e(KINDS[item["kind"]])} · {v.e(uses)}</small><small>Последняя загрузка: {v.e(item.get("last_import_at") or "не было")} · новых: {v.e(item.get("last_import_count") or 0)}</small></div>'
            if project and conn:
                body+=f'<a class="button secondary" href="{root}/sources/{sid}/filter">Настроить</a>' if item['kind']=='rss' else f'<a class="button secondary" href="{root}/sources/{sid}">Настроить</a>'
                body+=f'<form method="post" action="{root}/sources/{sid}/disconnect"><button class="button secondary">Отключить</button></form>'
            elif project:
                body+=f'<form method="post" action="{root}/sources/{sid}/connect"><button class="button secondary">Подключить</button></form>'
            body+='</div>'
        body+='</section>'
    return shell('Источники',body,project,message)


def source_page(item=None, project=False, message=''):
    item=item or {'id':str(uuid4()),'kind':'rss','projects':[]}
    root=base(project);sid=v.ident(item['id']);conn=item.get('connection')
    if project and item.get('name'):
        body=f'<a class="back" href="{root}/sources">← Источники проекта</a>'+v.heading('ПОДКЛЮЧЕНИЕ ИСТОЧНИКА',item['name'],'Общие сведения редактируются отдельно в фабрике.')
        if conn and item['kind']=='rss':body+=f'<a class="button" href="{root}/sources/{sid}/filter">Настроить</a>'
        elif not conn:body+=v.notice('Источник ещё не подключён. Подключение доступно в списке источников проекта.')
        else:body+=v.notice('Настройка загрузки для этого типа ещё не реализована.')
        if item['kind']!='rss':body+=v.notice('Настройка загрузки для этого типа ещё не реализована.')
        body+=f'<p><a href="/studio/library/sources/{sid}">Открыть общие сведения в фабрике ↗</a></p>'
        return shell('Подключение источника',body,True,message)
    body=f'<a class="back" href="{root}/sources">← Источники</a>'+v.heading('ОБЩИЙ КАТАЛОГ',item.get('name') or 'Новый источник','Название, адрес и описание общие для всех проектов.')
    body+=f'<section class="panel"><form method="post" action="{root}/sources/{sid}/save"><div class="library-form"><label>Название<input name="name" required maxlength="200" value="{v.e(item.get("name"))}"></label><label>Тип<select name="kind">'
    body+=''.join(f'<option value="{k}" {"selected" if item["kind"]==k else ""}>{label}</option>' for k,label in KINDS.items())
    body+=f'</select></label><label>Адрес ленты / расположение<input name="location" maxlength="2000" value="{v.e(item.get("location"))}"></label><label>Описание<textarea name="description" maxlength="4000" rows="4">{v.e(item.get("description"))}</textarea></label></div><p class="hint">Указывай только несекретное описание. Подключения к БД, API и файлам пока не выполняются. Пароли и токены сюда не вставляй.</p><button class="button">Сохранить источник</button></form></section>'
    if item.get('name'):
        uses=', '.join(x.get('cf_projects',{}).get('name',x['project_code']) for x in item.get('projects',[])) or 'Ни одного'
        body+=f'<section class="panel"><h2>Использующие проекты</h2><p>{v.e(uses)}</p><p class="hint">Изменения общей карточки видны всем использующим её проектам. Отключение сохраняет материалы и посты.</p></section>'
        if item['kind']=='rss':

            body+=f'<section class="panel"><h2>Получить материалы в общую библиотеку</h2><p>Получение не добавляет материалы в проекты. Уже известные URL повторно не создаются и не перезаписываются.</p><p class="muted">Последняя загрузка: {v.e(item.get("last_import_at") or "ещё не было")} · добавлено: {v.e(item.get("last_import_count") or 0)}</p><form method="post" action="{root}/sources/{sid}/import"><label>Страница RSS <input type="number" name="page" min="1" max="100" value="1" required></label> <button class="button secondary">Получить RSS</button></form></section>'
        else:
            body+=v.notice('Источник зарегистрирован. Загрузка для этого типа ещё не реализована.')
    return shell('Карточка источника',body,project,message,context={'kind':'Общий источник','title':item.get('name') or 'Новый источник','fields':[('Тип',KINDS[item['kind']]),('Расположение',item.get('location') or 'Не задано'),('Используется',', '.join(x.get('cf_projects',{}).get('name',x['project_code']) for x in item.get('projects',[])) or 'Пока не подключён'),('Загрузка','Ручной RSS' if item['kind']=='rss' else 'Адаптер ещё не реализован')],'links':[('Общие источники','/studio/library/sources'),('Источники СССР',v.BASE+'/sources')]})


def material_list(items,total,offset=0,search='',message=''):
    root='/studio/library/materials'
    body=v.heading('ОБЩАЯ БИБЛИОТЕКА','Все материалы',f'Всего: {total}. Выбери материал для проекта; содержимое останется в одном экземпляре.', '<a class="button secondary" href="/studio/library/cleanup">Просмотр кандидатов очистки</a>')+tabs(False)
    body+=f'<form class="searchbar" method="get"><label>Поиск по заголовку <input name="q" maxlength="150" value="{v.e(search)}"></label><button class="button secondary">Найти</button></form><section class="panel">'
    for item in items:
        body+=f'<div class="record"><div><b>{v.e(item.get("title") or "Без названия")}</b><small>{v.e(item.get("published_at"))}</small></div><form method="post" action="/studio/library/materials/{v.ident(item["id"])}/select"><button class="button secondary">Выбрать для СССР →</button></form></div>'
    body+='</section><div class="pagination">'
    if offset:
        body+=f'<a href="{root}?offset={max(0,offset-20)}&q={v.ident(search)}">← Назад</a>'
    if offset+len(items)<total:
        body+=f'<a href="{root}?offset={offset+20}&q={v.ident(search)}">Следующие →</a>'
    return shell('Общая библиотека',body+'</div>',message=message)


def cleanup(items=None,before='',message=''):
    body=v.heading('БЕЗ УДАЛЕНИЯ','Кандидаты очистки','Только материалы без ссылок проектов и постов и без отметки защиты. Не более 50 записей за просмотр.')
    body+=f'<section class="panel"><form method="get"><label>Получены раньше (дата, UTC) <input type="date" name="before" required value="{v.e(before)}"></label><button class="button secondary">Посмотреть кандидатов</button></form><p>Это только предварительный список. Удаление в этой версии отключено.</p>'
    if items is not None:
        body+=f'<p>Найдено в этом просмотре: {len(items)}</p>'
        body+=''.join(f'<div class="record"><b>{v.e(x.get("title") or "Без названия")}</b><small>{v.e(x["imported_at"])}</small></div>' for x in items)
    return shell('Просмотр очистки',body+'</section>',message=message)
