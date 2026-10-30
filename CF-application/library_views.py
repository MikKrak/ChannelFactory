"""library_views.py — серверные HTML-компоненты общей библиотеки и источников.

Получает готовые данные; не вызывает сеть и не меняет хранилище.
"""
from uuid import uuid4
import studio_views as v
from library import KINDS


def base(project):
    return v.BASE if project else '/studio/library'


def shell(title, body, project=False, message=''):
    return v.layout(title,body,'sources',message,global_scope=not project)


def tabs(project):
    root=base(project)
    return f'<nav class="tabs"><a href="{root}/sources">Источники</a><a href="/studio/library/materials">Общая библиотека материалов</a><a href="{v.BASE}/materials">Отобрано в СССР</a></nav>'


def source_list(items, project=False, message=''):
    root=base(project)
    body=v.heading('ПРОЕКТ СССР' if project else 'ОБЩАЯ БИБЛИОТЕКА','Источники',
        'Подключения и настройки действуют только в этом проекте.' if project else 'Один источник — несколько проектов. Загрузка пока доступна только для RSS.',
        f'<a class="button" href="{root}/sources/new">＋ Новый источник</a>')+tabs(project)
    body+='<section class="panel">'
    for item in items:
        conn=item.get('connection')
        uses=', '.join(x.get('cf_projects',{}).get('name',x['project_code']) for x in item['projects']) or 'Пока не используется'
        body+=f'<div class="record"><div><a href="{root}/sources/{v.ident(item["id"])}"><b>{v.e(item["name"])}</b></a><small>{v.e(KINDS[item["kind"]])} · {"Загрузка доступна" if item["kind"]=="rss" else "Адаптер ещё не реализован"}</small><small>{v.e(uses)}</small></div>'
        if project:
            action='disconnect' if conn else 'connect'
            label='Отключить' if conn else 'Подключить'
            body+=f'<form method="post" action="{root}/sources/{v.ident(item["id"])}/{action}"><button class="button secondary">{label}</button></form>'
        body+='</div>'
    return shell('Источники',body+('</section>' if items else '<p>Источников пока нет.</p></section>'),project,message)


def source_page(item=None, project=False, message=''):
    item=item or {'id':str(uuid4()),'kind':'rss','projects':[]}
    root=base(project);sid=v.ident(item['id']);conn=item.get('connection')
    body=f'<a class="back" href="{root}/sources">← Источники</a>'+v.heading('ОБЩИЙ КАТАЛОГ',item.get('name') or 'Новый источник','Название, адрес и описание общие для всех проектов.')
    body+=f'<section class="panel"><form method="post" action="{root}/sources/{sid}/save"><div class="library-form"><label>Название<input name="name" required maxlength="200" value="{v.e(item.get("name"))}"></label><label>Тип<select name="kind">'
    body+=''.join(f'<option value="{k}" {"selected" if item["kind"]==k else ""}>{label}</option>' for k,label in KINDS.items())
    body+=f'</select></label><label>Адрес ленты / расположение<input name="location" maxlength="2000" value="{v.e(item.get("location"))}"></label><label>Описание<textarea name="description" maxlength="4000" rows="4">{v.e(item.get("description"))}</textarea></label></div><p class="hint">Указывай только несекретное описание. Подключения к БД, API и файлам пока не выполняются. Пароли и токены сюда не вставляй.</p><button class="button">Сохранить {"и подключить к СССР" if project and not conn else "источник"}</button></form></section>'
    if item.get('name'):
        uses=', '.join(x.get('cf_projects',{}).get('name',x['project_code']) for x in item.get('projects',[])) or 'Ни одного'
        body+=f'<section class="panel"><h2>Использующие проекты</h2><p>{v.e(uses)}</p><p class="hint">Изменения общей карточки видны всем использующим её проектам. Отключение сохраняет материалы и посты.</p></section>'
        if item['kind']=='rss':
            body+=f'<section class="panel"><h2>Получить материалы в общую библиотеку</h2><p>Получение не добавляет материалы в проекты. Уже известные URL повторно не создаются и не перезаписываются.</p><p class="muted">Последняя загрузка: {v.e(item.get("last_import_at") or "ещё не было")} · добавлено: {v.e(item.get("last_import_count") or 0)}</p><form method="post" action="{root}/sources/{sid}/import"><label>Страница RSS <input type="number" name="page" min="1" max="100" value="1" required></label> <button class="button secondary">Получить RSS</button></form></section>'
        else:
            body+=v.notice('Источник зарегистрирован. Загрузка для этого типа ещё не реализована.')
        if project and conn:
            body+=f'<section class="panel"><h2>Настройки только для СССР</h2><form method="post" action="{root}/sources/{sid}/settings"><div class="library-form"><label><input type="checkbox" name="enabled" value="yes" {"checked" if conn["enabled"] else ""}> Допускать отбор материалов</label><label>Фраза в заголовке<input name="keyword" maxlength="200" value="{v.e(conn["keyword"])}"></label><p class="hint">Пустое поле — любые заголовки. Поиск буквальной фразы без учёта регистра; применяется при нажатии «Отобрать».</p><label>Заметки проекта<textarea name="notes" maxlength="2000">{v.e(conn["notes"])}</textarea></label></div><button class="button secondary">Сохранить настройки проекта</button></form><hr><form method="post" action="{root}/sources/{sid}/select"><p>Отобрать уже полученные материалы по сохранённым настройкам. Содержание не копируется.</p><button class="button">Отобрать в СССР</button></form></section>'
    return shell('Карточка источника',body,project,message)


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
