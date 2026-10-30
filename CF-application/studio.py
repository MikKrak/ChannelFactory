"""studio.py — маршруты редакционного кабинета одного существующего проекта.

Связывает представления, редактор и существующее хранилище. Публикация вынесена в отдельный маршрутизатор с серверным журналом. Все изменения — отдельные POST.
"""
from uuid import UUID
from functools import wraps
import logging
from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
import database as db
import studio_views as view
from editor import prepare_post, replace_text
from extractor import extract_article
from publication_routes import status_panel

router = APIRouter(default_response_class=HTMLResponse)
logger = logging.getLogger(__name__)


def guarded(func):
    """Не показывать браузеру адреса запросов, ключи и сырые ошибки сервисов."""
    @wraps(func)
    def run(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as error:
            # Только тип: исключение сервиса может включать адрес с секретом.
            logger.warning("Studio operation %s failed (%s)", func.__name__, type(error).__name__)
            recovery = ''
            if 'post_text' in kwargs:
                recovery = '<h2>Твой несохранённый текст</h2><textarea readonly rows="12" style="width:100%">' + view.e(kwargs['post_text']) + '</textarea>'
            return HTMLResponse(view.layout('Не удалось выполнить действие',
                '<section class="panel"><h1>Не удалось обратиться к данным</h1>'
                '<p>Проверь подключение к сети и повтори действие. Изменения могли сохраниться: '
                'перед повторным сохранением открой список постов.</p>'
                f'<a class="button secondary" href="{view.BASE}/posts">Проверить посты</a> '
                f'<a href="{view.BASE}/materials">Открыть материалы</a>{recovery}</section>'), status_code=503)
    return run


def missing():
    return HTMLResponse(view.layout('Не найдено', '<section class="panel"><h1>Запись не найдена</h1><p>Возможно, её удалили. Вернись к списку материалов или постов.</p></section>'), status_code=404)


@router.get('/studio')
def projects():
    return view.projects()


@router.get(view.BASE)
@guarded
def overview():
    counts = {status: db.count_posts(status) for status in ('draft', 'ready')}
    from library import enabled, LibraryRepository
    material_count = LibraryRepository(db.db).materials(project='cccp')[1] if enabled() else db.count_materials()
    return view.overview(material_count, db.get_posts(status='draft', limit=4), counts)


@router.get(view.BASE + '/materials')
@guarded
def materials(offset: int = Query(0, ge=0), q: str = Query('', max_length=150)):
    from library import enabled, LibraryRepository
    items, total = LibraryRepository(db.db).materials(project='cccp', offset=offset, search=q) if enabled() else db.list_materials(offset=offset, search=q)
    return view.material_list(items, total, offset, 20, q)


@router.get(view.BASE + '/materials/{material_id}')
@guarded
def material(material_id: UUID):
    article = db.get_material(str(material_id))
    if not article:
        return missing()
    return view.material_page(article, db.find_material_draft(str(material_id)))


@router.post(view.BASE + '/materials/{material_id}/load')
@guarded
def load(material_id: UUID):
    article = db.get_material(str(material_id))
    if not article:
        return missing()
    if not (article.get('content') or {}).get('text'):
        try:
            extracted = extract_article(article['url'])
            if not extracted.get('text'):
                return HTMLResponse(view.material_page(article, message='На странице не удалось найти текст статьи. Открой оригинал или напиши пост вручную.'), status_code=422)
            db.save_article_content(str(material_id), extracted)
        except Exception:
            return HTMLResponse(view.material_page(article, message='Не удалось загрузить статью. Проверь оригинал и попробуй позже.'), status_code=502)
    return RedirectResponse(f'{view.BASE}/materials/{material_id}', status_code=303)


@router.post(view.BASE + '/materials/{material_id}/draft')
@guarded
def draft(material_id: UUID, post_text: str = Form(..., max_length=50000)):
    article = db.get_material(str(material_id))
    if not article:
        return missing()
    existing = db.find_material_draft(str(material_id))
    if existing:
        # Повторная отправка формы не перезаписывает уже начатую редакционную работу.
        return RedirectResponse(f'{view.BASE}/posts/{existing["id"]}', status_code=303)
    if not post_text.strip():
        return HTMLResponse(view.material_page(article, text=post_text, error='Добавь текст перед сохранением.'), status_code=422)
    post = prepare_post(article)
    try:
        saved_id = db.create_post(str(material_id), post['title'], replace_text(post['blocks'], post_text))
    except Exception:
        return HTMLResponse(view.material_page(article, text=post_text, error='Не удалось подтвердить сохранение. Текст оставлен в форме. Проверь список постов перед повтором.'), status_code=503)
    if saved_id:
        return RedirectResponse(f'{view.BASE}/posts/{UUID(str(saved_id))}', status_code=303)
    return RedirectResponse(f'{view.BASE}/posts?status=draft', status_code=303)


@router.get(view.BASE + '/posts')
@guarded
def posts(status: str = 'all', offset: int = Query(0, ge=0)):
    if status not in ('all', 'draft', 'ready', 'published'):
        status = 'all'
    items = db.list_posts(offset=offset, status=status)
    return view.post_list(items, status, offset, 20)


@router.get(view.BASE + '/posts/{post_id}')
@guarded
def post(post_id: UUID, saved: bool = False):
    item = db.get_post(str(post_id))
    if not item:
        return missing()
    article = db.get_material(str(item['material_id'])) if item.get('material_id') else None
    return view.post_page(item, message='Изменения сохранены.' if saved else '', article=article, publication=status_panel(item))


@router.post(view.BASE + '/posts/{post_id}/save')
@guarded
def save(post_id: UUID, post_text: str = Form(..., max_length=50000), action: str = Form(...)):
    item = db.get_post(str(post_id))
    if not item:
        return missing()
    if action not in ('save', 'ready') or not post_text.strip():
        return HTMLResponse(view.post_page(item, text=post_text, error='Выбери действие и добавь непустой текст.'), status_code=422)
    if item.get('status') != 'draft':
        return HTMLResponse(view.post_page(item, message='Статус поста изменился. Сначала верни готовый пост на редактирование.'), status_code=409)
    try:
        db.update_post(str(post_id), post_text, 'ready' if action == 'ready' else 'draft')
    except Exception:
        return HTMLResponse(view.post_page(item, text=post_text, error='Не удалось подтвердить сохранение. Текст оставлен в форме. Проверь статус поста перед повтором.'), status_code=409)
    return RedirectResponse(f'{view.BASE}/posts/{post_id}?saved=true', status_code=303)


@router.post(view.BASE + '/posts/{post_id}/draft')
@guarded
def reopen(post_id: UUID):
    try:
        db.return_post_to_draft(str(post_id))
    except ValueError:
        item = db.get_post(str(post_id))
        return HTMLResponse(view.post_page(item, message='Вернуть в черновики можно только готовый пост.'), status_code=409) if item else missing()
    return RedirectResponse(f'{view.BASE}/posts/{post_id}?saved=true', status_code=303)
