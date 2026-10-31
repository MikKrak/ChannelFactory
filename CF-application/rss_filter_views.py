"""rss_filter_views.py — мастер рубрик и фраз, в существующей оболочке Studio."""
import studio_views as v
from rss_filter import analyze, entry_data, LABELS, FIELDS, normalize_rules

FIELD_LABELS={'include_categories':'Включать рубрики','exclude_categories':'Исключать рубрики','include_words':'Включать слова и фразы','exclude_words':'Исключать слова и фразы'}


def page(source,projects,project,connection,rules,token,label,entries,preview=None,message='',is_demo=False,unsaved=False):
    root='/studio/library/sources/'+v.ident(source['id'])+'/filter'
    selected=next((x for x in projects if x['code']==project),None)
    name=selected['name'] if selected else 'Выбери проект'
    body=f'<a class="back" href="/studio/library/sources/{v.ident(source["id"])}">← Источник</a>'+v.heading('ТЕМАТИЧЕСКИЙ ОТБОР','Фильтр RSS для проекта',source['name'])
    if is_demo:body+=v.notice('ТЕСТОВЫЙ РЕЖИМ. Реальные заголовки из публичного RSS-снимка; правила сохраняются только в памяти этого процесса. Рабочая база и 99 связей СССР не меняются.')
    body+=f'<section class="panel"><form method="get"><label>Проект <select name="project" aria-label="Проект для фильтра">'
    body+=''.join(f'<option value="{v.e(x["code"])}" {"selected" if x["code"]==project else ""}>{v.e(x["name"])}</option>' for x in projects)
    body+='</select></label> <button class="button secondary">Открыть настройки проекта</button></form><p class="hint">Источник общий. Эти правила относятся только к выбранному проекту и не оценивают качество будущего поста.</p></section>'
    if not selected or not connection:
        body+=v.notice('Сначала подключи этот источник к выбранному проекту. Мастер не создаёт подключений автоматически.')
        return v.layout('Фильтр RSS',body,'sources',message,global_scope=True)
    profile=analyze(entries)
    body+=f'<section class="panel filter-section"><h2>1. Исследовать источник</h2><p class="muted">{v.e(label)}. В выборке: {profile["total"]}. Не весь архив сайта.</p>'
    if profile['fields']:body+='<details><summary>Какие поля доступны</summary><ul>'+''.join(f'<li>{v.e(key)} — {count} записей</li>' for key,count in profile['fields'])+'</ul></details>'
    if profile['categories']:
        body+='<details open><summary>Рубрики в выборке</summary><div class="filter-categories">'
        for category,count in profile['categories']:
            body+=f'<div><b>{v.e(category)}</b><span>{count}</span><button type="button" class="button secondary" data-category-target="include_categories" data-category="{v.e(category)}" aria-label="Включить рубрику {v.e(category)}">＋ Включать</button><button type="button" class="button secondary" data-category-target="exclude_categories" data-category="{v.e(category)}" aria-label="Исключить рубрику {v.e(category)}">− Исключать</button></div>'
        body+='</div></details>'
    else:body+=v.notice('Рубрики в этой выборке отсутствуют. Используй правила по заголовку и описанию; недостающие рубрики дадут «сомнительно».')
    body+=f'<p class="hint">Без рубрик: {profile["missing_categories"]}; без описания: {profile["missing_description"]}. Старые материалы могли сохраняться без этих полей; анализ RSS не переписывает их.</p></section>'
    body+=f'<form method="post" action="{root}" data-unsaved="{str(unsaved).lower()}"><input type="hidden" name="project" value="{v.e(project)}"><input type="hidden" name="token" value="{v.e(token)}"><input type="hidden" name="revision" value="{connection.get("filter_revision",0)}"><section class="panel filter-section"><button class="button secondary" name="action" value="analyze">Анализировать {"RSS-снимок" if is_demo else "текущий RSS"}</button> <button class="button secondary" name="action" value="stored">Взять уже загруженные материалы</button><p class="hint">Только чтение. Не импортирует материалы и не меняет проект.</p></section><section class="panel filter-section"><h2>2. Настроить правила для {v.e(name)}</h2><div class="filter-rule-grid">'
    for field in FIELDS:
        body+=f'<label>{FIELD_LABELS[field]}<textarea id="{field}" name="{field}" maxlength="6000" rows="4" placeholder="Одно условие на строку">{v.e(chr(10).join(rules[field]))}</textarea></label>'
    body+='</div><p class="hint">Внутри каждого поля достаточно одного совпадения. Рубрики — точные названия без учёта регистра; фразы — соседние слова. Исключения всегда имеют приоритет.</p>'
    body+=f'<label>Между включаемыми рубриками и словами <select name="combine"><option value="all" {"selected" if rules["combine"]=="all" else ""}>Нужны обе группы условий (И)</option><option value="any" {"selected" if rules["combine"]=="any" else ""}>Достаточно любой группы (ИЛИ)</option></select></label><p class="hint">Пустая группа не ограничивает отбор. Если обе группы пустые — допускается любая тема, кроме исключений.</p><p><label><input type="checkbox" name="match_forms" value="yes" {"checked" if rules["match_forms"] else ""}> Учитывать близкие словоформы</label></p><p class="hint">Простое отсечение распространённых русских окончаний; без словаря, понимания смысла и синонимов. Возможны неточные совпадения. «ё» и «е» равнозначны.</p><button class="button" name="action" value="test">Проверить фильтр</button></section>'
    if preview is not None:
        totals={key:sum(x['state']==key for x in preview) for key in LABELS}
        body+='<section class="panel filter-section"><h2>3. Результаты проверки</h2><p>Предпросмотр не изменяет материалы и проектные связи.</p><div class="filter-totals">'+''.join(f'<span class="filter-state {key}">{value}: {totals[key]}</span>' for key,value in LABELS.items())+'</div><div class="filter-results">'
        for entry,result in zip(entries,preview):
            data=entry_data(entry)
            body+=f'<article><span class="filter-state {result["state"]}">{LABELS[result["state"]]}</span><h3>{v.e(data["title"] or "Без заголовка")}</h3><small>Рубрики: {v.e(", ".join(data["categories"]) or "нет")}</small><p class="muted">{v.e(data["description"][:400] or "Описание отсутствует")}</p><ul>'+''.join(f'<li>{v.e(reason)}</li>' for reason in result['reasons'])+'</ul></article>'
        body+='</div></section>'
    body+=f'<section class="panel filter-section"><h2>Сохранение</h2><p><label><input type="checkbox" name="auto_select" value="yes" {"checked" if rules["auto_select"] else ""}> После сохранения отбирать новые материалы автоматически при штатном RSS-импорте</label></p><p class="hint">Только «подходит» попадает в проект. Остальные остаются в общей библиотеке; «сомнительно» — в отдельном списке. Допуск отбора источника в настройках проекта также должен быть включён.</p><p><label><input type="checkbox" name="confirmed" value="yes"> Подтверждаю сохранение проверенных правил. Уже существующие связи не изменять.</label></p><button class="button secondary" name="action" value="save">Сохранить фильтр</button><p class="hint">Сначала проверь текущие правила. Версия сохранённой конфигурации: {connection.get("filter_revision",0)}. {"После перезапуска демо-процесса правила сбросятся." if is_demo else "Сохранение не отбирает старые материалы заново."}</p><p><a href="{root}/review?project={v.ident(project)}">Открыть сомнительные материалы →</a></p></section></form><script defer src="/static/rss-filter.js"></script><link rel="stylesheet" href="/static/rss-filter.css">'
    return v.layout('Фильтр RSS',body,'sources',message,global_scope=True,context={'kind':'Фильтр проекта','title':name,'fields':[('Источник',source['name']),('Выборка',str(profile['total'])),('Сохранённая версия',str(connection.get('filter_revision',0)))],'links':[('Источник','/studio/library/sources/'+str(source['id']))]})


def review(source,project,items,is_demo=False):
    body=v.heading('РУЧНАЯ ПРОВЕРКА','Сомнительные материалы','Эти материалы не привязаны к проекту автоматически. Решения относятся к версии правил на момент получения.')
    if is_demo:body+=v.notice('Тестовый режим: реальный импорт не запускался, сохранённых результатов нет.')
    body+='<section class="panel">'
    for row in items:
        material=row.get('cf_materials') or {}
        body+=f'<article><h3>{v.e(material.get("title") or "Без заголовка")}</h3><p>Версия: {row["filter_revision"]}</p><ul>'+''.join(f'<li>{v.e(reason)}</li>' for reason in row['reasons'])+'</ul></article>'
    if not items:body+='<p>В этом списке пока нет материалов. Предпросмотр мастера сюда не записывается.</p>'
    body+=f'</section><p><a href="/studio/library/sources/{v.ident(source["id"])}/filter?project={v.ident(project)}">← К фильтру</a></p>'
    return v.layout('Проверка фильтра',body,'sources',global_scope=True)
