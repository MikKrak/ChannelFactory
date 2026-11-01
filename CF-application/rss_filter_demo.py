"""rss_filter_demo.py — отдельный безопасный сервер мастера до рабочей миграции.

Нет клиента рабочей базы, маршрутов импорта/публикации/ответа/изменения связей.
Единственное сохранение — тестовая конфигурация в памяти процесса.
"""
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import rss_filter_routes
from source import SOURCE_ID
import studio_views as view

if os.environ.get('CF_RSS_FILTER_DEMO')!='1':raise RuntimeError('Demo mode must be explicitly enabled')
app=FastAPI(title='ChannelFactory — безопасная демонстрация RSS-фильтра')
app.mount('/static',StaticFiles(directory=str(Path(__file__).parent/'static')),name='static')
app.include_router(rss_filter_routes.router)
from rss_filter_config_routes import router as config_router
app.include_router(config_router)
MASTER=f'/studio/library/sources/{SOURCE_ID}/filter?project=cccp'

@app.get('/')
@app.get('/studio')
def home():return RedirectResponse(MASTER,status_code=303)

@app.get('/studio/cccp/sources',response_class=HTMLResponse)
def demo_sources(filter_message:str=""):
    import library_views
    import rss_filter_service as service
    repo=service.repository(None);item=repo.source(SOURCE_ID)
    item.update(projects=[{'project_code':'cccp','cf_projects':{'name':repo.projects()[0]['name']}}],connection=repo.connection(SOURCE_ID,'cccp'))
    return library_views.source_list([item],True,filter_message[:300] or 'Демонстрация: рабочие подключения и операции здесь недоступны.')

@app.get('/{path:path}',response_class=HTMLResponse)
def demo_navigation(path:str):
    return view.layout('Демонстрация мастера',view.heading('ТЕСТОВЫЙ РЕЖИМ','Демонстрация RSS-фильтра','Здесь доступны только тестовые настройки; рабочие разделы не подключены.')+f'<a class="button" href="{MASTER}">Открыть мастер →</a>','sources',global_scope=True)
