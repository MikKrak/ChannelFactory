"""rss_filter_views.py — проектное рабочее место исследования и проверки RSS.

Три независимые области; данные приходят готовыми, операций с базой здесь нет.
Логика правил 011 пока сохранена. Новая рубричная модель — следующий этап 012.
"""
import studio_views as v
from rss_filter import analyze, entry_data, LABELS, FIELDS

FIELD_LABELS={'include_categories':'Включать рубрики','exclude_categories':'Исключать рубрики','include_words':'Включать слова и фразы','exclude_words':'Исключать слова и фразы'}
RSS_FIELDS={
    'title':('Название','Заголовок'), 'title_detail':('Название','Сведения о заголовке'),
    'summary':('Содержание','Описание из RSS'), 'summary_detail':('Содержание','Сведения об описании'),
    'description':('Содержание','Описание'), 'content':('Содержание','Содержимое записи'),
    'link':('Адреса','Ссылка на статью'), 'links':('Адреса','Ссылки записи'),
    'id':('Адреса','Идентификатор записи'), 'guidislink':('Адреса','Идентификатор является ссылкой'),
    'published':('Даты','Дата публикации'), 'published_parsed':('Даты','Разобранная дата публикации'),
    'updated':('Даты','Дата обновления'), 'updated_parsed':('Даты','Разобранная дата обновления'),
    'author':('Авторство','Автор'), 'authors':('Авторство','Авторы'), 'author_detail':('Авторство','Сведения об авторе'),
    'tags':('Тематика','Рубрики и метки'), 'categories':('Тематика','Рубрики'),
}


def root(source,project):
    return f'/studio/{v.ident(project)}/sources/{v.ident(source["id"])}/filter'


def field_reference(fields):
    groups={}
    for key,count in fields:
        group,label=RSS_FIELDS.get(key,('Другие поля','Неизвестное поле'))
        groups.setdefault(group,[]).append(f'<li>{v.e(label)} · {count}<small>Имя в RSS: <code>{v.e(key)}</code></small></li>')
    return '<details class="rss-fields"><summary>Доступные данные RSS</summary>'+''.join(f'<h3>{v.e(group)}</h3><ul>'+''.join(rows)+'</ul>' for group,rows in groups.items())+'</details>'


def research(profile,label):
    body=f'<section class="panel filter-pane" aria-label="Исследование источника"><header><h2>Исследование</h2><p class="hint">{v.e(label)} · {profile["total"]} записей. Выборка, не весь архив.</p><div class="filter-actions"><button class="button secondary" name="action" value="analyze">Анализировать RSS</button><button class="button secondary" name="action" value="stored">Взять загруженные</button></div></header><div class="filter-scroll" tabindex="0" aria-label="Поля и рубрики RSS">'
    body+=field_reference(profile['fields'])
    if profile['categories']:
        body+='<h3>Рубрики в выборке</h3><div class="filter-categories">'
        for category,count in profile['categories']:
            body+=f'<div><b>{v.e(category)}</b><span>{count}</span><button type="button" class="button secondary" data-category-target="include_categories" data-category="{v.e(category)}" aria-label="Включить рубрику {v.e(category)}">＋ Включать</button><button type="button" class="button secondary" data-category-target="exclude_categories" data-category="{v.e(category)}" aria-label="Исключить рубрику {v.e(category)}">− Исключать</button></div>'
        body+='</div>'
    else:body+=v.notice('В выборке нет рубрик. Можно проверять заголовок и описание; недостаток данных отмечается как «сомнительно».')
    return body+f'<p class="hint">Без рубрик: {profile["missing_categories"]}; без описания: {profile["missing_description"]}. Старые записи не переписываются.</p></div></section>'


def rule_editor(rules,connection,is_demo):
    body='<section class="panel filter-pane" aria-label="Правила проекта"><header><h2>Правила проекта</h2><p class="hint">В этом варианте найденная исключающая рубрика или фраза запрещает материал, даже если он совпал с включением.</p></header><div class="filter-scroll" tabindex="0" aria-label="Поля правил"><div class="filter-rule-grid">'
    for field in FIELDS:
        body+=f'<label>{FIELD_LABELS[field]}<textarea id="{field}" name="{field}" maxlength="6000" rows="3" placeholder="Одно условие на строку">{v.e(chr(10).join(rules[field]))}</textarea></label>'
    body+='</div><p class="hint">Внутри поля достаточно одного совпадения. Рубрики сравниваются по названию, фразы — соседние слова.</p>'
    body+=f'<label>Между рубриками и словами <select name="combine"><option value="all" {"selected" if rules["combine"]=="all" else ""}>Обе группы (И)</option><option value="any" {"selected" if rules["combine"]=="any" else ""}>Любая группа (ИЛИ)</option></select></label><p class="hint">Пустая группа не ограничивает отбор.</p><p><label><input type="checkbox" name="match_forms" value="yes" {"checked" if rules["match_forms"] else ""}> Учитывать близкие словоформы</label></p><p class="hint">Эвристика русских окончаний, без понимания смысла. Возможны ошибки; ё/е равнозначны.</p>'
    body+=f'<details><summary>Сохранение · версия {connection.get("filter_revision",0)}</summary><p><label><input type="checkbox" name="auto_select" value="yes" {"checked" if rules["auto_select"] else ""}> Применять автоматически при штатном RSS-импорте</label></p><p class="hint">Только новые принятые материалы. Сохранение не запускает импорт и не меняет прежние связи.</p><p><label><input type="checkbox" name="confirmed" value="yes"> Подтверждаю сохранение проверенных правил. Уже существующие связи не изменять.</label></p><button class="button secondary" name="action" value="save">Сохранить фильтр</button><p class="hint">Сначала проверь текущие правила. {"Демо хранит их только в памяти." if is_demo else "Рабочая конфигурация меняется только этой командой."}</p></details>'
    return body+'</div><footer><button class="button" name="action" value="test">Проверить фильтр</button></footer></section>'


def results(entries,preview):
    body='<section class="panel filter-pane" aria-label="Результаты теста"><header><h2>Результаты теста</h2><p class="hint">Временный предпросмотр. Материалы и связи не меняются; результаты в базу не записываются.</p></header><div class="filter-scroll" tabindex="0" aria-label="Список результатов">'
    if preview is None:return body+'<p class="muted">Задай правила и нажми «Проверить фильтр».</p></div></section>'
    for state,name in LABELS.items():
        rows=[(entry,result) for entry,result in zip(entries,preview) if result['state']==state]
        body+=f'<details class="result-group" open><summary><span class="filter-state {state}">{name}: {len(rows)}</span></summary>'
        for entry,result in rows:
            data=entry_data(entry)
            body+=f'<article><details class="result-material"><summary>{v.e(data["title"] or "Без заголовка")}</summary><p class="hint">Рубрики: {v.e(", ".join(data["categories"]) or "нет")}</p><p>{v.e(data["description"][:1000] or "Описание отсутствует")}</p></details><ul>'+''.join(f'<li>{v.e(reason)}</li>' for reason in result['reasons'])+'</ul></article>'
        body+='</details>'
    return body+'</div></section>'


def page(source,projects,project,connection,rules,token,label,entries,preview=None,message='',is_demo=False,unsaved=False):
    path=root(source,project)
    selected=next((x for x in projects if x['code']==project),None)
    name=selected['name'] if selected else 'Проект не найден'
    body=f'<div class="filter-workspace"><div class="filter-top"><div><a class="back" href="/studio/{v.ident(project)}/sources">← Источники проекта</a><h1>{v.e(source["name"])}</h1><p class="hint">Настройка подключения · {v.e(name)} · только исследование и правила</p></div><a href="/studio/library/sources/{v.ident(source["id"])}">Общие сведения источника ↗</a></div>'
    if is_demo:body+=v.notice('ТЕСТОВЫЙ РЕЖИМ. Публичные снимки; сохранение только в памяти процесса, без рабочей базы.')
    if not selected or not connection:
        body+=v.notice('Подключи источник в разделе «Источники проекта». Настройка не создаёт связей автоматически.')
    else:
        profile=analyze(entries)
        body+=f'<form method="post" action="{path}" class="filter-workform" data-unsaved="{str(unsaved).lower()}"><input type="hidden" name="project" value="{v.e(project)}"><input type="hidden" name="token" value="{v.e(token)}"><input type="hidden" name="revision" value="{connection.get("filter_revision",0)}"><div class="filter-columns">'+research(profile,label)+rule_editor(rules,connection,is_demo)+results(entries,preview)+'</div></form>'
    body+='</div><script defer src="/static/rss-filter.js"></script><link rel="stylesheet" href="/static/rss-filter.css">'
    context={'kind':'Подключение источника','title':source['name'],'fields':[('Проект',name),('Расположение',source.get('location','')),('Сохранённая версия',str((connection or {}).get('filter_revision',0)))],'links':[('Общие сведения источника','/studio/library/sources/'+str(source['id'])),('Сохранённые сомнительные',path+'/review')]}
    return v.layout('Настройка источника',body,'sources',message,context=context)


def review(source,project,items,is_demo=False):
    body=v.heading('СОХРАНЁННЫЕ РЕШЕНИЯ','Сомнительные материалы','Это рабочие результаты на момент импорта, а не временный тест. Автоматически в проект не добавлены.')
    if is_demo:body+=v.notice('Демо: реального импорта и сохранённых результатов нет.')
    body+='<section class="panel">'
    for row in items:
        material=row.get('cf_materials') or {}
        body+=f'<article><h3>{v.e(material.get("title") or "Без заголовка")}</h3><p>Версия: {row["filter_revision"]}</p><ul>'+''.join(f'<li>{v.e(reason)}</li>' for reason in row['reasons'])+'</ul></article>'
    if not items:body+='<p>В этом списке пока нет материалов. Предпросмотр сюда не записывается.</p>'
    body+=f'</section><p><a href="{root(source,project)}">← К настройке источника</a></p>'
    return v.layout('Проверка фильтра',body,'sources')
