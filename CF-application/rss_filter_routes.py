"""rss_filter_routes.py — мастер: чтение/анализ, безопасный тест и явное сохранение.

Проверка не импортирует материалы. Рабочий доступ требует отдельного флага;
демо использует только снимок публичного RSS и изолированное хранилище в памяти.
"""
import logging
from uuid import UUID
from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
import rss_filter_service as service
import rss_filter_views as view
from rss_filter import classify, normalize_rules, rule_hash

router=APIRouter(default_response_class=HTMLResponse)
log=logging.getLogger(__name__)
PATH='/studio/library/sources/{source_id}/filter'
PROJECT_PATH='/studio/{project}/sources/{source_id}/filter'


def repository():
    if service.demo():return service.repository(None)
    import database
    return service.repository(database.db)


def context(sid,project):
    if not service.available():raise ValueError('Мастер ещё не подключён. Требуется согласованная миграция.')
    repo=repository();source=repo.source(sid)
    if not source or source['kind']!='rss':raise ValueError('Выбери существующий RSS-источник.')
    projects=repo.projects();selected=project or (projects[0]['code'] if projects else '')
    if selected not in [x['code'] for x in projects]:raise ValueError('Проект не найден.')
    return repo,source,projects,selected,repo.connection(sid,selected)


def error_page(text,status=422):
    return HTMLResponse(view.v.layout('Фильтр RSS',view.v.notice(text,'error'),'sources',global_scope=True),status_code=status)


def wizard(source_id:UUID,project:str=Query('',max_length=40),saved:bool=False):
    try:
        repo,source,projects,project,conn=context(source_id,project)
        entries=repo.entries(source_id)
        label='Библиотека · тестовый снимок' if service.demo() else 'Материалы библиотеки'
        token=service.samples.put(source_id,project,entries,label)
        return view.page(source,projects,project,conn,normalize_rules((conn or {}).get('filter_rules') or {}),token,label,entries,message='Правила сохранены. Существующие материалы и связи не менялись.' if saved else '',is_demo=service.demo())
    except ValueError as exc:return error_page(str(exc))
    except Exception as exc:
        log.warning('RSS filter opening failed (%s)',type(exc).__name__)
        return error_page('Не удалось прочитать настройки. Рабочая миграция могла ещё не быть подключена.',503)


@router.get(PATH)
def legacy_wizard(source_id:UUID,project:str=Query('',max_length=40),saved:bool=False):
    if not project:
        return error_page('Открой настройку из источников нужного проекта.')
    return RedirectResponse(f'/studio/{view.v.ident(project)}/sources/{source_id}/filter'+('?saved=true' if saved else ''),status_code=303)


@router.get(PROJECT_PATH)
def project_wizard(source_id:UUID,project:str,saved:bool=False):
    return wizard(source_id,project,saved)


@router.post(PATH)
def action(source_id:UUID,project:str=Form(...,max_length=40),token:str=Form('',max_length=40),revision:int=Form(0,ge=0),action:str=Form(...),include_categories:str=Form('',max_length=6000),exclude_categories:str=Form('',max_length=6000),include_words:str=Form('',max_length=6000),exclude_words:str=Form('',max_length=6000),combine:str=Form('all'),match_forms:str=Form(''),auto_select:str=Form(''),confirmed:str=Form('')):
    values={'include_categories':include_categories,'exclude_categories':exclude_categories,'include_words':include_words,'exclude_words':exclude_words,'combine':combine,'match_forms':match_forms=='yes','auto_select':auto_select=='yes'}
    try:
        repo,source,projects,project,conn=context(source_id,project)
        if not conn:raise ValueError('Сначала подключи источник к проекту.')
        rules={**values,**{field:values[field].splitlines() for field in ('include_categories','exclude_categories','include_words','exclude_words')}}
        rules=normalize_rules(values)
        if action in ('analyze','stored'):
            entries=repo.analyze_feed(source) if action=='analyze' else repo.entries(source_id)
            label=('Свежая выборка · тестовый снимок' if service.demo() else 'Свежая выборка') if action=='analyze' else ('Материалы библиотеки · тестовый снимок' if service.demo() else 'Материалы библиотеки')
            token=service.samples.put(source_id,project,entries,label)
            sample=service.samples.get(token,source_id,project);preview=None
        else:
            sample=service.samples.get(token,source_id,project)
            preview=[classify(entry,rules) for entry in sample['entries']]
            if action=='test':sample['tested'].add(rule_hash(rules))
            elif action=='save':
                if confirmed!='yes':raise ValueError('Подтверди сохранение правил отдельной галочкой.')
                if rule_hash(rules) not in sample['tested']:raise ValueError('Сначала проверь текущую конфигурацию кнопкой «Проверить фильтр».')
                repo.save(source_id,project,revision,rules)
                return RedirectResponse(f'/studio/{view.v.ident(project)}/sources/{source_id}/filter?saved=true',status_code=303)
            else:raise ValueError('Неизвестная команда.')
        unsaved=rule_hash(rules)!=rule_hash(conn.get('filter_rules') or {})
        return view.page(source,projects,project,conn,rules,token,sample['label'],sample['entries'],preview,is_demo=service.demo(),unsaved=unsaved)
    except ValueError as exc:
        message=str(exc);status=422
    except Exception as exc:
        log.warning('RSS filter action failed (%s)',type(exc).__name__)
        message='Действие не подтверждено. Проверь сохранённые настройки перед повтором; версия правил могла измениться.';status=503
    # Сохраняем введённые поля при ошибке, не показываем ответ БД/адреса сервисов.
    if 'source' in locals() and 'rules' in locals():
        sample=service.samples.items.get(token)
        entries=sample['entries'] if sample else []
        label=sample['label'] if sample else 'Выборка устарела; нажми «Анализировать»'
        return HTMLResponse(view.page(source,projects,project,conn,rules,token,label,entries,message=message,is_demo=service.demo(),unsaved=True),status_code=status)
    return error_page(message,status)


@router.get(PATH+'/review')
def review(source_id:UUID,project:str=Query(...,max_length=40)):
    try:
        repo,source,_,project,conn=context(source_id,project)
        if not conn:raise ValueError('Источник не подключён к проекту.')
        return view.review(source,project,repo.results(source_id,project,'uncertain'),service.demo())
    except ValueError as exc:return error_page(str(exc))
    except Exception as exc:
        log.warning('RSS filter review failed (%s)',type(exc).__name__)
        return error_page('Не удалось прочитать результаты. Предпросмотр мастера не записывает их в базу.',503)


@router.post(PROJECT_PATH)
def project_action(source_id:UUID,project:str,token:str=Form('',max_length=40),revision:int=Form(0,ge=0),action_name:str=Form(...,alias='action'),include_categories:str=Form('',max_length=6000),exclude_categories:str=Form('',max_length=6000),include_words:str=Form('',max_length=6000),exclude_words:str=Form('',max_length=6000),combine:str=Form('all'),match_forms:str=Form(''),auto_select:str=Form(''),confirmed:str=Form('')):
    # Контекст задаёт адрес проекта; одноимённое поле POST не может его сменить.
    return action(source_id,project,token,revision,action_name,include_categories,exclude_categories,include_words,exclude_words,combine,match_forms,auto_select,confirmed)


@router.get(PROJECT_PATH+'/review')
def project_review(source_id:UUID,project:str):
    return review(source_id,project)
