"""rss_filter_config_routes.py — JSON для временного теста и версионного автосохранения.

Отдельный флаг после миграции; в демо только память. Ни импорта, ни ссылок.
"""
import os
import logging
from uuid import UUID
from fastapi import APIRouter
from fastapi.responses import HTMLResponse,JSONResponse
from pydantic import BaseModel,Field
from rss_filter_config import normalize,classify,suggestion
import rss_filter_service as service
import rss_filter_routes as old
from rss_filter import analyze

router=APIRouter();log=logging.getLogger(__name__)
PATH='/studio/{project}/sources/{source_id}/filter'


def enabled():return os.environ.get('CF_RSS_FILTER_CONFIG_ENABLED')=='1' and service.available()


def state(repo,sid,project):
    conn=repo.connection(sid,project)
    if not conn:raise ValueError('Источник не подключён к проекту.')
    raw=conn.get('filter_rules')
    return {'rules':normalize(raw) if raw and raw.get('version')==2 else normalize({}), 'revision':conn.get('filter_revision',0),'source_enabled':bool(conn.get('enabled')),'configured':bool(raw and raw.get('version')==2),'conversion_required':bool(raw and raw.get('version')!=2)}


def context(sid,project):
    if not enabled():raise ValueError('Новая настройка ещё не подключена.')
    return old.context(sid,project)


def open_page(sid,project):
    from rss_filter_config_views import page
    try:
        repo,source,projects,project,conn=context(sid,project)
        data=state(repo,sid,project)
        entries=repo.entries(sid)
        token=service.samples.put(sid,project,entries,'Материалы библиотеки')
        return page(source,projects,project,data,token,entries,service.demo())
    except ValueError as exc:return old.error_page(str(exc))
    except Exception as exc:
        log.warning('Config opening failed (%s)',type(exc).__name__)
        return old.error_page('Не удалось прочитать настройку.',503)


class Save(BaseModel):
    revision:int=Field(ge=0,le=9007199254740991)
    rules:dict
    accept_conversion:bool=False


class Sample(BaseModel):
    kind:str=Field(max_length=20)


class Test(BaseModel):
    token:str=Field(max_length=40)
    rules:dict


def failure(exc):
    if isinstance(exc,ValueError):return JSONResponse({'error':str(exc)},status_code=422)
    log.warning('Config request failed (%s)',type(exc).__name__)
    return JSONResponse({'error':'Не удалось подтвердить действие. Настройки не перезаписывай: проверь сохранённую версию.'},status_code=503)


@router.get(PATH+'/config')
def get_config(source_id:UUID,project:str):
    try:
        repo,*_=context(source_id,project)
        return state(repo,source_id,project)
    except Exception as exc:return failure(exc)


@router.post(PATH+'/config')
def save_config(source_id:UUID,project:str,payload:Save):
    try:
        rules=normalize(payload.rules)
        repo,*_=context(source_id,project);current=state(repo,source_id,project)
        if current['revision']!=payload.revision:return JSONResponse({'error':'Настройки изменены в другом окне. Твой черновик сохранён локально; открой актуальную версию.'},status_code=409)
        if current['conversion_required'] and not payload.accept_conversion:raise ValueError('Подтверди создание нового варианта вместо прежних правил.')
        repo.save(source_id,project,payload.revision,rules)
        # Чтение после записи также обнаруживает конкурентную правку/неизвестный исход.
        saved=state(repo,source_id,project)
        if saved['rules']!=rules:return JSONResponse({'error':'После сохранения настройки снова изменились. Черновик не потерян.'},status_code=409)
        return saved
    except Exception as exc:return failure(exc)


@router.post(PATH+'/sample')
def sample(source_id:UUID,project:str,payload:Sample):
    try:
        repo,source,projects,project,_=context(source_id,project)
        if payload.kind not in ('fresh','library'):raise ValueError('Неизвестная выборка.')
        entries=repo.analyze_feed(source) if payload.kind=='fresh' else repo.entries(source_id)
        token=service.samples.put(source_id,project,entries,'Свежая выборка' if payload.kind=='fresh' else 'Материалы библиотеки')
        profile=analyze(entries)
        selected=next(x for x in projects if x['code']==project)
        from rss_filter_views import field_reference
        return {'token':token,'fields_html':field_reference(profile['fields']),'profile':profile,'label':service.samples.get(token,source_id,project)['label'],'suggestion':suggestion(selected,[c for c,n in profile['categories']])}
    except Exception as exc:return failure(exc)


@router.post(PATH+'/test')
def test(source_id:UUID,project:str,payload:Test):
    from rss_filter_views import results
    try:
        context(source_id,project)
        rules=normalize(payload.rules)
        sample=service.samples.get(payload.token,source_id,project)
        preview=[classify(e,rules,preview=True) for e in sample['entries']]
        return {'html':results(sample['entries'],preview),'note':'Испытание правил, даже когда рабочий фильтр выключен. Результаты временные.'}
    except Exception as exc:return failure(exc)
