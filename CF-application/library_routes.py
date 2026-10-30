"""library_routes.py — общие источники и проектные подключения.

Все изменения отдельными POST; каталог включается после согласованной миграции.
Удаления материалов, отправки в Telegram и фоновой загрузки здесь нет.
"""
from functools import wraps
from uuid import UUID
import logging
from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
import database
import library as lib
import library_views as view

router=APIRouter(default_response_class=HTMLResponse)
logger=logging.getLogger(__name__)


def repository():
    return lib.LibraryRepository(database.db)


def guarded(func):
    @wraps(func)
    def run(*args,**kwargs):
        if not lib.enabled():
            return HTMLResponse(view.shell('Библиотека',view.v.notice('Раздел ещё не подключён к базе. Требуется согласованная миграция.')),status_code=503)
        try:
            return func(*args,**kwargs)
        except ValueError:
            return HTMLResponse(view.shell('Проверь данные',view.v.notice('Не удалось принять данные. Проверь поля формы и адрес источника.','error')),status_code=422)
        except Exception as error:
            logger.warning('Library operation %s failed (%s)',func.__name__,type(error).__name__)
            return HTMLResponse(view.shell('Действие не подтверждено',view.v.notice('Не удалось подтвердить действие. Проверь список перед повтором: изменения могли сохраниться.','error')),status_code=503)
    return run


def redirect(path):
    return RedirectResponse(path,status_code=303)


def scope(project):
    return '/studio/cccp' if project else '/studio/library'


# Два явных пути оставляют общей карточке один и тот же id и хранилище.
def register_sources(project):
    root=scope(project)+'/sources'

    @router.get(root,name='project_sources' if project else 'library_sources')
    @guarded
    def sources():
        return view.source_list(repository().sources('cccp' if project else None),project)

    @router.get(root+'/new',name='new_project_source' if project else 'new_source')
    @guarded
    def new():
        return view.source_page(project=project)

    @router.get(root+'/{source_id}',name='project_source' if project else 'source')
    @guarded
    def source(source_id:UUID):
        item=repository().source(source_id)
        if not item:
            return HTMLResponse(view.shell('Не найдено','Источник не найден.'),status_code=404)
        if project:
            item['connection']=next((x for x in item['projects'] if x['project_code']=='cccp'),None)
        return view.source_page(item,project)

    @router.post(root+'/{source_id}/save',name='save_project_source' if project else 'save_source')
    @guarded
    def save(source_id:UUID,name:str=Form(...,max_length=200),kind:str=Form(...),location:str=Form('',max_length=2000),description:str=Form('',max_length=4000)):
        submitted={'id':str(source_id),'name':name,'kind':kind if kind in lib.KINDS else 'other','location':location,'description':description,'projects':[]}
        try:
            values=lib.source_values(name,kind,location,description)
        except ValueError:
            return HTMLResponse(view.source_page(submitted,project,'Проверь название, тип и адрес. Для RSS нужен HTTP(S)-адрес без пароля и фрагмента.'),status_code=422)
        try:
            repository().save(source_id,values,'cccp' if project else None)
        except Exception as error:
            # Код SQLSTATE безопасен; текст исключения может содержать секреты сервиса.
            duplicate=getattr(error,'code',None)=='23505'
            message='Такой источник уже есть. Открой список и подключи существующий источник.' if duplicate else 'Сохранение не подтверждено. Проверь список перед повтором; поля формы оставлены ниже.'
            logger.warning('Library source save failed (%s)',type(error).__name__)
            return HTMLResponse(view.source_page(submitted,project,message),status_code=409 if duplicate else 503)
        return redirect(root+'/'+str(source_id))

    @router.post(root+'/{source_id}/import',name='import_project_source' if project else 'import_source')
    @guarded
    def load(source_id:UUID,page:int=Form(1,ge=1,le=100)):
        repo=repository();result=repo.import_rss(source_id,page)
        item=repo.source(source_id)
        if project:
            item['connection']=next((x for x in item['projects'] if x['project_code']=='cccp'),None)
        return view.source_page(item,project,f'Получено: {result["received"]}; новых материалов: {result["saved"]}. Отбор в проект выполняется отдельно.')

register_sources(False)
register_sources(True)


@router.post('/studio/cccp/sources/{source_id}/connect')
@guarded
def connect(source_id:UUID):
    repository().connect(source_id)
    return redirect('/studio/cccp/sources/'+str(source_id))


@router.post('/studio/cccp/sources/{source_id}/disconnect')
@guarded
def disconnect(source_id:UUID):
    repository().disconnect(source_id)
    return redirect('/studio/cccp/sources')


@router.post('/studio/cccp/sources/{source_id}/settings')
@guarded
def settings(source_id:UUID,enabled:str=Form(''),keyword:str=Form('',max_length=200),notes:str=Form('',max_length=2000)):
    repository().settings(source_id,enabled=='yes',keyword,notes)
    return redirect('/studio/cccp/sources/'+str(source_id))


@router.post('/studio/cccp/sources/{source_id}/select')
@guarded
def select_source(source_id:UUID):
    count=repository().select(source=source_id)
    return view.source_list(repository().sources('cccp'),True,f'Добавлено в проект: {count}. Повторный отбор не создаёт копий.')


@router.get('/studio/library/materials')
@guarded
def materials(offset:int=Query(0,ge=0),q:str=Query('',max_length=150)):
    items,total=repository().materials(offset=offset,search=q)
    return view.material_list(items,total,offset,q)


@router.post('/studio/library/materials/{material_id}/select')
@guarded
def select_material(material_id:UUID):
    repository().select(material=material_id)
    return redirect('/studio/cccp/materials/'+str(material_id))


@router.get('/studio/library/cleanup')
@guarded
def cleanup(before:str=Query('',max_length=10)):
    return view.cleanup(repository().cleanup(before) if before else None,before)
