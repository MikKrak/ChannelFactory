"""rss_filter_config_views.py — новая настройка в уже проверенном компактном каркасе."""
import json
from pathlib import Path
import studio_views as v
from rss_filter import analyze
from rss_filter_views import pane_heading,field_reference,results,FIELD_LABELS


def asset(name):
    # После локальной синхронизации браузер должен получить обновлённый код,
    # а не прежнюю копию с тем же адресом и округлённой датой изменения.
    stamp=(Path(__file__).parent/'static'/name).stat().st_mtime_ns
    return f'/static/{name}?v={stamp}'


def page(source,projects,project,state,token,entries,demo=False):
    path=f'/studio/{v.ident(project)}/sources/{v.ident(source["id"])}/filter'
    name=next(x['name'] for x in projects if x['code']==project)
    profile=analyze(entries)
    body=f'<div class="filter-workspace"><div class="filter-top"><a class="back" href="/studio/{v.ident(project)}/sources" aria-label="Вернуться в источники проекта">←</a><h1>{v.e(source["name"])}</h1><a class="filter-shared-link" href="/studio/library/sources/{v.ident(source["id"])}">Общие сведения ↗</a></div>'
    if demo:body+=v.notice('Демонстрация: настройки сохраняются только в памяти процесса. Рабочая база не подключена.')
    body+='<noscript><p>Для автосохранения нужен JavaScript. Рабочие операции здесь не выполняются.</p></noscript>'
    body+=f'<form class="filter-workform" id="config-form" method="post" data-autosave="true" data-endpoint="{path}"><div class="filter-columns">'
    body+='<section class="panel filter-pane"><header>'+pane_heading('Данные источника','Получение выборки и проверка используют только чтение. Ни материалы, ни связи не меняются.')+'<p class="filter-sample-label" id="config-sample-label">Материалы библиотеки · '+str(len(entries))+' записей</p><div class="filter-actions"><button type="button" class="button secondary" data-sample="fresh">Получить свежую выборку</button><button type="button" class="button secondary" data-sample="library">Проверить на материалах библиотеки</button></div></header><div class="filter-scroll" tabindex="0" aria-label="Рубрики источника"><div id="config-fields">'+field_reference(profile['fields'])+'</div><div class="filter-actions"><button type="button" class="button secondary" data-all="include">Включить все</button><button type="button" class="button secondary" data-all="exclude">Исключить все</button></div><div id="config-categories" class="filter-categories"></div></div></section>'
    body+='<section class="panel filter-pane"><header>'+pane_heading('Настройка отбора','Достаточно одной включённой рубрики; исключённая рубрика не запрещает материал. Исключающие фразы запрещают. Без рубрик проверяем текст, иначе отмечаем неопределённость. Автосохранение — завершённое изменение, не каждый символ. Проверка отдельно испытывает правила даже при выключенном фильтре.')+'<label class="filter-mode"><input type="checkbox" name="filter_enabled"> <span id="config-mode">Фильтр выключен</span></label><p id="config-save-status" role="status" aria-live="polite">Настройка ещё не сохранена</p><p id="config-error" role="alert" hidden></p><button type="button" class="button secondary" id="config-retry" hidden>Повторить сохранение</button></header><div class="filter-scroll" tabindex="0" aria-label="Настройки отбора">'
    if state['conversion_required']:body+='<p id="config-conversion">Есть прежние правила. Новая модель меняет смысл рубрик; действующие правила остаются до твоего выбора. <button type="button" class="button secondary" id="config-convert">Создать новый вариант</button></p>'
    body+='<div id="config-suggestion" hidden><p></p><button type="button" class="button secondary">Использовать предложение</button></div><div class="filter-rule-grid">'
    for field,label in FIELD_LABELS.items():body+=f'<label>{label}<textarea name="{field}" id="{field}" rows="3" maxlength="6000" placeholder="Одно условие на строку"></textarea></label>'
    body+='</div><label>Новые рубрики<select name="category_default"><option value="include">Включать</option><option value="exclude">Исключать</option></select></label><label>Рубрики и включающие фразы<select name="combine"><option value="all">Обе группы (И)</option><option value="any">Любая группа (ИЛИ)</option></select></label><p class="hint">Без рубрик достаточно совпадения включающей фразы. Без подтверждения темы материал остаётся сомнительным.</p><label><input type="checkbox" name="match_forms"> Учитывать близкие словоформы</label><p class="hint">Приближение по русским окончаниям, без понимания смысла.</p></div><footer><button type="button" class="button" id="config-test">Проверить отбор</button><p class="hint" id="config-test-note">Временная проверка правил, без импорта.</p></footer></section><div class="config-results-slot" id="config-results">'+results(entries,None)+'</div></div></form>'
    body+='<dialog id="config-leave"><p id="config-leave-message"></p><div class="filter-actions"><button type="button" class="button secondary" id="config-stay">Остаться</button><button type="button" class="button" id="config-leave-confirm">Перейти с сохранённым черновиком</button></div></dialog>'
    initial={'state':state,'token':token,'profile':profile}
    encoded=json.dumps(initial,ensure_ascii=False).replace('<','\\u003c')
    body+=f'<script type="application/json" id="config-initial">{encoded}</script><script defer src="{asset("filter-config-model.js")}"></script><script defer src="{asset("filter-config.js")}"></script><link rel="stylesheet" href="{asset("rss-filter.css")}"></div>'
    context={'kind':'Подключение источника','title':source['name'],'fields':[('Проект',name),('Тип','RSS'),('Отбор источника','Допущен' if state.get('source_enabled',True) else 'Выключен в подключении'),('Расположение',source.get('location','')),('Выборка','Первые 200 записей библиотеки или текущая страница источника')],'links':[('Общие сведения','/studio/library/sources/'+str(source['id']))]}
    return v.layout('Настройка источника',body,'sources',context=context).replace('class="workbench"','class="workbench source-settings"',1).replace('/static/workspace.js"',asset('workspace.js')+'"',1)
