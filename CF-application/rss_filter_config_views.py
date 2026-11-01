"""Редактор проектного фильтра: две рабочие панели и справка в общем инспекторе.

Только представление; настройка, выборка и результаты имеют отдельные состояния.
"""
import json
from pathlib import Path
import studio_views as v
from rss_filter import analyze, entry_data, LABELS
from rss_filter_views import field_reference
from rss_filter_config import category_included
from rss_filter_recommendations import recommend


def asset(name):
    stamp=(Path(__file__).parent/'static'/name).stat().st_mtime_ns
    return f'/static/{name}?v={stamp}'


def icon(action,label,symbol,extra=''):
    return f'<button type="button" class="config-icon" {action} aria-label="{label}" title="{label}" {extra}>{symbol}</button>'


def result_content(entries,preview,rules=None):
    """Только тестовые карточки; галочки меняют правила, а не судьбу материала."""
    if preview is None:return '<p>Нажми «Обновить», чтобы проверить текущие условия.</p>'
    body='<div class="filter-summary-counts">'+''.join(f'<span class="filter-state {key}">{name}: {sum(x["state"]==key for x in preview)}</span>' for key,name in LABELS.items())+'</div>'
    for key,name in LABELS.items():
        rows=[(entry,result) for entry,result in zip(entries,preview) if result['state']==key]
        body+=f'<details class="result-group" open><summary><span class="filter-state {key}">{name}: {len(rows)}</span></summary>'
        for entry,result in rows:
            data=entry_data(entry)
            body+=f'<article><details class="result-material"><summary>{v.e(data["title"] or "Без заголовка")}</summary><p>{v.e(data["description"][:1000] or "Описание отсутствует")}</p>'
            if data['categories']:
                body+='<fieldset class="config-result-categories"><legend>Рубрики — общие правила фильтра</legend><p class="hint">Выбор изменит правило и для других материалов. Текущий тест пересчитается только по «Обновить».</p>'
                for category in data['categories']:
                    checked=rules is not None and category_included(category,rules)
                    body+=f'<label><input type="checkbox" data-result-category="{v.e(category)}" {"checked" if checked else ""}> {v.e(category)}</label>'
                body+='</fieldset>'
            else:body+='<p class="hint">В материале нет рубрик. Используются текстовые условия.</p>'
            body+='</details><ul>'+''.join(f'<li>{v.e(reason)}</li>' for reason in result['reasons'])+'</ul></article>'
        body+='</details>'
    return body


def page(source,projects,project,state,token,entries,demo=False):
    path=f'/studio/{v.ident(project)}/sources/{v.ident(source["id"])}/filter'
    name=next(x['name'] for x in projects if x['code']==project)
    profile=analyze(entries)
    body=f'<div class="filter-workspace config-workspace"><div class="filter-top"><a class="back" href="/studio/{v.ident(project)}/sources" aria-label="Вернуться в источники проекта">←</a><h1>{v.e(source["name"])}</h1></div>'
    if demo:body+=v.notice('Демонстрация: настройки только в памяти. Рабочая база не подключена.')
    body+='<noscript><p>Для редактора и автосохранения нужен JavaScript.</p></noscript>'
    body+=f'<form class="filter-workform" id="config-form" method="post" data-autosave="true" data-endpoint="{path}"><nav class="config-panel-recovery" id="config-panel-recovery" aria-label="Вернуть рабочие панели" hidden>'+icon('data-panel-show="editor"','Показать: Настройка фильтра','☷')+icon('data-panel-show="results"','Показать: Результаты','▤')+f'</nav><div id="config-panels" class="config-panels" data-editor="true" data-results="false">'
    body+='<section class="panel filter-pane config-editor" id="config-editor-pane" aria-label="Настройка фильтра"><header><div class="config-pane-heading"><h2>Настройка фильтра</h2>'
    body+=icon('data-panel-show="results"','Показать: Результаты','▤')+icon('data-panel-max="editor"','Развернуть: Настройка фильтра','⛶')+icon('data-panel-hide="editor"','Скрыть: Настройка фильтра','×')+'</div><p id="config-save-status" role="status" aria-live="polite">Настройка ещё не сохранена</p><p id="config-error" role="alert" hidden></p><button type="button" class="button secondary" id="config-retry" hidden>Повторить сохранение</button></header><div class="filter-scroll" tabindex="0" aria-label="Условия фильтра">'
    if state['conversion_required']:body+='<p id="config-conversion">Есть прежние правила. Новая модель меняет смысл рубрик; прежние правила остаются до твоего выбора. <button type="button" class="button secondary" id="config-convert">Создать новый вариант</button></p>'
    # Внутренние массивы нужны очереди автосохранения, но не дублируют галочки.
    body+='<textarea name="include_categories" hidden></textarea><textarea name="exclude_categories" hidden></textarea>'
    body+='<details class="config-section" open><summary>Рубрики</summary><div class="config-reference-actions"><button type="button" class="config-icon" data-sample="fresh" aria-label="Обновить рубрики и поля" title="Обновить рубрики и поля">↻</button><span class="hint" id="config-reference-status" role="status" aria-live="polite">Загружаются рубрики и поля источника…</span></div><div class="config-category-workspace" id="config-category-workspace" data-selected-open="true"><section class="config-category-catalog" aria-label="Все рубрики"><div class="config-category-heading"><h3>Все рубрики</h3><button type="button" class="config-icon" id="config-selected-show" aria-label="Показать выбранные рубрики" title="Показать выбранные рубрики" aria-controls="config-selected-pane" hidden>☑</button></div><label class="config-category-all"><input type="checkbox" id="config-all"> Включить все</label><div id="config-categories" tabindex="-1" class="config-category-list"></div></section><section id="config-selected-pane" aria-label="Выбранные рубрики"><div class="config-category-heading"><h3>Выбранные рубрики</h3><button type="button" class="config-icon" id="config-selected-hide" aria-label="Скрыть выбранные рубрики" title="Скрыть выбранные рубрики" aria-controls="config-selected-pane">×</button></div><label><input type="checkbox" id="config-show-recommended"> Показать рекомендованные</label><div id="config-selected-categories" tabindex="-1" class="config-category-list"></div></section></div><details class="config-add-category"><summary>Добавить рубрику по названию</summary><label>Название рубрики<input id="config-category-name" maxlength="100" autocomplete="off"></label><button type="button" class="button secondary" id="config-category-add">Добавить</button><p class="hint">Для рубрики, которой пока нет в выборке.</p></details><label>Ранее неизвестные рубрики<select name="category_default"><option value="include">Включать</option><option value="exclude">Не включать</option></select></label><p class="hint">Достаточно одной включённой рубрики материала. Снятая галочка не запрещает другие основания.</p></details>'
    body+='<details class="config-section" open><summary>Слова и фразы</summary><div class="filter-rule-grid">'
    for field,label in [('include_words','Включающие слова и фразы'),('exclude_words','Исключающие слова и фразы')]:
        body+=f'<label>{label}<textarea name="{field}" id="{field}" rows="3" maxlength="6000" placeholder="Одно условие на строку"></textarea></label>'
    body+='</div><label>Рубрики и включающие фразы<select name="combine"><option value="all">Обе группы (И)</option><option value="any">Любая группа (ИЛИ)</option></select></label><label><input type="checkbox" name="match_forms"> Учитывать близкие словоформы</label><p class="hint">Проверяются заголовок и описание. Исключающая фраза запрещает материал. Словоформы определяются приблизительно по русским окончаниям.</p></details><details class="config-section"><summary>Поля и свойства материалов</summary><p>Рубрики, заголовок и описание участвуют в текущих условиях. Без рубрик проверяем текст; при нехватке данных результат — «сомнительно».</p><p class="hint">Ниже — доступные данные источника. Условия по датам, авторам и адресам пока не реализованы.</p><div id="config-editor-fields">'+field_reference(profile['fields'])+'</div></details></div></section>'
    body+='<div class="config-divider" id="config-divider" role="separator" aria-label="Ширина настройки фильтра" aria-orientation="vertical" aria-valuemin="25" aria-valuemax="75" aria-valuenow="55" tabindex="0" hidden></div>'
    body+='<section class="panel filter-pane config-result-pane" id="config-results-pane" aria-label="Результаты" hidden><header><div class="config-pane-heading"><h2>Результаты</h2>'+icon('id="config-test"','Обновить','↻')+icon('data-panel-show="editor"','Показать: Настройка фильтра','☷')+icon('data-panel-max="results"','Развернуть: Результаты','⛶')+icon('data-panel-hide="results"','Скрыть: Результаты','×')+'</div><label>Выборка<select id="config-sample-kind"><option value="library">Материалы библиотеки</option><option value="fresh">Свежая выборка источника</option></select></label><p class="filter-sample-label" id="config-sample-label">Материалы библиотеки · '+str(len(entries))+' записей</p><p class="hint" id="config-test-note" role="status">Временная проверка правил, без импорта.</p></header><div class="filter-scroll" id="config-results" tabindex="0" aria-label="Результаты проверки">'+result_content(entries,None)+'</div></section></div></form>'
    body+='<dialog id="config-leave"><p id="config-leave-message"></p><div class="filter-actions"><button type="button" class="button secondary" id="config-stay">Остаться</button><button type="button" class="button" id="config-leave-confirm">Перейти с сохранённым черновиком</button></div></dialog>'
    selected_project=next(x for x in projects if x['code']==project)
    categories=list(dict.fromkeys([c for c,n in profile['categories']]+state['rules']['include_categories']+state['rules']['exclude_categories']))
    initial={'state':state,'token':token,'profile':profile,'recommendations':recommend(selected_project,categories)}
    encoded=json.dumps(initial,ensure_ascii=False).replace('<','\\u003c')
    for script in ['filter-config-model.js','filter-category-model.js','filter-config-panels.js','filter-config-editor.js']:
        body+=f'<script defer src="{asset(script)}"></script>'
    body+=f'<script type="application/json" id="config-initial">{encoded}</script><link rel="stylesheet" href="{asset("rss-filter.css")}"><link rel="stylesheet" href="{asset("filter-config.css")}"></div>'
    context={'kind':'Источник проекта','title':source['name'],'fields':[('Проект',name),('Тип','RSS'),('Описание',source.get('description') or 'Не задано'),('Допуск источника','Допущен' if state.get('source_enabled',True) else 'Выключен в подключении'),('Рабочий фильтр','Включён' if state['configured'] and state['rules']['filter_enabled'] else 'Выключен'),('Адрес',source.get('location','')),('Последний импорт',source.get('last_import_at') or 'Не было')],'links':[('Общие сведения','/studio/library/sources/'+str(source['id']))]}
    inspector='<section class="config-source-reference"><h3>Временная выборка</h3><div class="filter-actions"><button type="button" class="button secondary" data-sample="fresh">Получить свежую выборку</button><button type="button" class="button secondary" data-sample="library">Материалы библиотеки</button></div><p class="hint">Только чтение, без импорта. Выборка ограничена; это не весь архив.</p><div id="config-source-profile">'+source_reference(profile)+'</div><div id="config-fields">'+field_reference(profile['fields'])+'</div></section>'
    html=v.layout('Настройка фильтра',body,'sources',context=context).replace('class="workbench"','class="workbench source-settings"',1).replace('/static/workspace.js"',asset('workspace.js')+'"',1)
    return html.replace('</aside></div>\n<footer',inspector+'</aside></div>\n<footer',1)


def source_reference(profile):
    cats=''.join(f'<li>{v.e(c)} · {n}</li>' for c,n in profile['categories'])
    return f'<p>Записей: {profile["total"]}. Рубрик: {len(profile["categories"])}. Без рубрик: {profile["missing_categories"]}; без описания: {profile["missing_description"]}.</p><details><summary>Рубрики выборки</summary><ul>{cats}</ul></details>'
