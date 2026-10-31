"""workspace_routes.py — старые ссылки открывают соответствующий раздел Studio.

Только GET-переходы. Прежние POST-операции сохранения и отправки не затрагиваются.
"""
from urllib.parse import urlencode
from uuid import UUID
from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

router = APIRouter()
BASE = '/studio/cccp'


@router.get('/materials', include_in_schema=False)
def materials(q: str = Query('', max_length=150), offset: int = Query(0, ge=0)):
    params = {'q': q, 'offset': offset} if q or offset else {}
    return RedirectResponse(BASE + '/materials' + ('?' + urlencode(params) if params else ''), status_code=303)


@router.get('/material/{material_id}', include_in_schema=False)
def material(material_id: UUID):
    return RedirectResponse(BASE + '/materials/' + str(material_id), status_code=303)


@router.get('/posts', include_in_schema=False)
def posts(status: str = 'all'):
    status = status if status in ('all', 'draft', 'ready', 'published') else 'all'
    return RedirectResponse(BASE + '/posts?' + urlencode({'status': status}), status_code=303)


@router.get('/post/{post_id}', include_in_schema=False)
def post(post_id: UUID):
    return RedirectResponse(BASE + '/posts/' + str(post_id), status_code=303)
