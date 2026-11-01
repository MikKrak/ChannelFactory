"""Редактор проектного фильтра: две рабочие панели и справка в общем инспекторе.

Только представление; настройка, выборка и результаты имеют отдельные состояния.
"""
import json
from pathlib import Path
import studio_views as v
from rss_filter import analyze
from rss_filter_views import field_reference, results


def asset(name):
    stamp=(Path(__file__).parent/'static'/name).stat().st_mtime_ns
    return f'/static/{name}?v={stamp}'


def icon(action,label,symbol,extra=''):
    return f'<button type="button" class="config-icon" {action} aria-label="{label}" title="{label}" {extra}>{symbol}</button>'


def result_content(entries,preview):
    # Содержимое прежнего проверенного представления, без второй шапки панели.
    from bs4 import BeautifulSoup
    doc=BeautifulSoup(results(entries,preview),'html.parser')
    counts=doc.select_one('.filter-summary-counts')
    scroll=doc.select_one('.filter-scroll')
    return (str(counts) if counts else '')+''.join(str(x) for x in scroll.contents).replace('Задай правила и нажми «Проверить отбор».','Нажми «Обновить», чтобы проверить текущие условия.')


def page(source,projects,project,state,token,entries,demo=False):
    path=f'/studio/{v.ident(project)}/sources/{v.ident(source["id"])}/filter'
    name=next(x['name'] for x in projects if x['code']==project)
    profile=analyze(entries)
    body=f'<div class="filter-workspace config-workspace"><div class="filter-top"><a class="back" href="/studio/{v.ident(project)}/sources" aria-label="Вернуться в источники проекта">←</a><h1>{v.e(source["name"])}</h1></div>'
    if demo:body+=v.notice('Демонстрация: настройки только в памяти. Рабочая база не подключена.')
    body+='<noscript><p>Для редактора и автосохранения нужен JavaScript.</p></noscript>'
    body+='<nav class="config-panel-bar" aria-label="Рабочие панели">'
    for key,label,symbol in [('editor','Настройка фильтра','☷'),('results','Результаты','▤')]:
        body+=icon(f'data-panel-show="{key}"',f'Показать: {label}',symbol,f'aria-controls="config-{key}-pane" aria-pressed="{str(key=="editor").lower()}"')+f'<span>{label}</span>'
    body+='</nav>'
    body+=f'<form class="filter-workform" id="config-form" method="post" data-autosave="true" data-endpoint="{path}"><div id="config-panels" class="config-panels" data-editor="true" data-results="false">'
    body+='<section class="panel filter-pane config-editor" id="config-editor-pane" aria-label="Настройка фильтра"><header><div class="config-pane-heading"><h2>Настройка фильтра</h2>'
    body+=icon('data-panel-max="editor"','Развернуть: Настройка фильтра','⛶')+icon('data-panel-hide="editor"','Скрыть: Настройка фильтра','×')+'</div><p id="config-save-status" role="status" aria-live="polite">Настройка ещё не сохранена</p><p id="config-error" role="alert" hidden></p><button type="button" class="button secondary" id="config-retry" hidden>Повторить сохранение</button></header><div class="filter-scroll" tabindex="0" aria-label="Условия фильтра">'
    if state['conversion_required']:body+='<p id="config-conversion">Есть прежние правила. Новая модель меняет смысл рубрик; прежние правила остаются до твоего выбора. <button type="button" class="button secondary" id="config-convert">Создать новый вариант</button></p>'
    # Внутренние массивы нужны очереди автосохранения, но не дублируют галочки.
    body+='<textarea name="include_categories" hidden></textarea><textarea name="exclude_categories" hidden></textarea>'
    body+='<details class="config-section" open><summary>Рубрики</summary><div class="config-reference-actions"><button type="button" class="config-icon" data-sample="fresh" aria-label="Обновить рубрики и поля" title="Обновить рубрики и поля">↻</button><span class="hint" id="config-reference-status" role="status" aria-live="polite">Загружаются рубрики и поля источника…</span></div><label class="config-category-all"><input type="checkbox" id="config-all"> Включить все</label><div id="config-categories" class="config-category-list"></div><details class="config-add-category"><summary>Добавить рубрику по названию</summary><label>Название рубрики<input id="config-category-name" maxlength="100" autocomplete="off"></label><button type="button" class="button secondary" id="config-category-add">Добавить</button><p class="hint">Для рубрики, которой пока нет в выборке.</p></details><label>Ранее неизвестные рубрики<select name="category_default"><option value="include">Включать</option><option value="exclude">Не включать</option></select></label><p class="hint">Достаточно одной включённой рубрики материала. Снятая галочка не запрещает другие основания.</p><div id="config-suggestion" hidden><p></p><button type="button" class="button secondary">Использовать предложение</button></div></details>'
    body+='<details class="config-section" open><summary>Слова и фразы</summary><div class="filter-rule-grid">'
    for field,label in [('include_words','Включающие слова и фразы'),('exclude_words','Исключающие слова и фразы')]:
        body+=f'<label>{label}<textarea name="{field}" id="{field}" rows="3" maxlength="6000" placeholder="Одно условие на строку"></textarea></label>'
    body+='</div><label>Рубрики и включающие фразы<select name="combine"><option value="all">Обе группы (И)</option><option value="any">Любая группа (ИЛИ)</option></select></label><label><input type="checkbox" name="match_forms"> Учитывать близкие словоформы</label><p class="hint">Проверяются заголовок и описание. Исключающая фраза запрещает материал. Словоформы определяются приблизительно по русским окончаниям.</p></details><details class="config-section"><summary>Поля и свойства материалов</summary><p>Рубрики, заголовок и описание участвуют в текущих условиях. Без рубрик проверяем текст; при нехватке данных результат — «сомнительно».</p><p class="hint">Ниже — доступные данные источника. Условия по датам, авторам и адресам пока не реализованы.</p><div id="config-editor-fields">'+field_reference(profile['fields'])+'</div></details></div></section>'
    body+='<div class="config-divider" id="config-divider" role="separator" aria-label="Ширина настройки фильтра" aria-orientation="vertical" aria-valuemin="25" aria-valuemax="75" aria-valuenow="55" tabindex="0" hidden></div>'
    body+='<section class="panel filter-pane config-result-pane" id="config-results-pane" aria-label="Результаты" hidden><header><div class="config-pane-heading"><h2>Результаты</h2>'+icon('id="config-test"','Обновить','↻')+icon('data-panel-max="results"','Развернуть: Результаты','⛶')+icon('data-panel-hide="results"','Скрыть: Результаты','×')+'</div><label>Выборка<select id="config-sample-kind"><option value="library">Материалы библиотеки</option><option value="fresh">Свежая выборка источника</option></select></label><p class="filter-sample-label" id="config-sample-label">Материалы библиотеки · '+str(len(entries))+' записей</p><p class="hint" id="config-test-note" role="status">Временная проверка правил, без импорта.</p></header><div class="filter-scroll" id="config-results" tabindex="0" aria-label="Результаты проверки">'+result_content(entries,None)+'</div></section></div></form>'
    body+='<dialog id="config-leave"><p id="config-leave-message"></p><div class="filter-actions"><button type="button" class="button secondary" id="config-stay">Остаться</button><button type="button" class="button" id="config-leave-confirm">Перейти с сохранённым черновиком</button></div></dialog>'
    initial={'state':state,'token':token,'profile':profile}
    encoded=json.dumps(initial,ensure_ascii=False).replace('<','\\u003c')
    for script in ['filter-config-model.js','filter-config-panels.js','filter-config-editor.js']:
        body+=f'<script defer src="{asset(script)}"></script>'
    body+=f'<script type="application/json" id="config-initial">{encoded}</script><link rel="stylesheet" href="{asset("rss-filter.css")}"><link rel="stylesheet" href="{asset("filter-config.css")}"></div>'
    context={'kind':'Источник проекта','title':source['name'],'fields':[('Проект',name),('Тип','RSS'),('Описание',source.get('description') or 'Не задано'),('Допуск источника','Допущен' if state.get('source_enabled',True) else 'Выключен в подключении'),('Рабочий фильтр','Включён' if state['configured'] and state['rules']['filter_enabled'] else 'Выключен'),('Адрес',source.get('location','')),('Последний импорт',source.get('last_import_at') or 'Не было')],'links':[('Общие сведения','/studio/library/sources/'+str(source['id']))]}
    inspector='<section class="config-source-reference"><h3>Временная выборка</h3><div class="filter-actions"><button type="button" class="button secondary" data-sample="fresh">Получить свежую выборку</button><button type="button" class="button secondary" data-sample="library">Материалы библиотеки</button></div><p class="hint">Только чтение, без импорта. Выборка ограничена; это не весь архив.</p><div id="config-source-profile">'+source_reference(profile)+'</div><div id="config-fields">'+field_reference(profile['fields'])+'</div></section>'
    html=v.layout('Настройка фильтра',body,'sources',context=context).replace('class="workbench"','class="workbench source-settings"',1).replace('/static/workspace.js"',asset('workspace.js')+'"',1)
    return html.replace('</aside></div>\n<footer',inspector+'</aside></div>\n<footer',1)


def source_reference(profile):
    cats=''.join(f'<li>{v.e(c)} · {n}</li>' for c,n in profile['categories'])
    return f'<p>Записей: {profile["total"]}. Рубрик: {len(profile["categories"])}. Без рубрик: {profile["missing_categories"]}; без описания: {profile["missing_description"]}.</p><details><summary>Рубрики выборки</summary><ul>{cats}</ul></details>'
