"""library.py — общий каталог источников, получение RSS и отбор для проектов.

Не публикует посты и не удаляет материалы. Сеть и хранилище передаются отдельно;
получение в общую библиотеку не означает автоматического отбора в проект.
"""
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID
from source import get_articles, prepare_materials

KINDS = {'rss': 'RSS', 'website': 'Сайт', 'database': 'База данных', 'api': 'API', 'file': 'Файл', 'other': 'Другое'}


def enabled():
    return os.environ.get('CF_LIBRARY_ENABLED') == '1'


def source_values(name, kind, location, description):
    name, location, description = name.strip(), location.strip(), description.strip()
    if not name or len(name)>200 or kind not in KINDS or len(location)>2000 or len(description)>4000:
        raise ValueError('Проверь название, тип и длину описания.')
    if kind in ('rss', 'website', 'api'):
        parts = urlsplit(location)
        if parts.scheme.lower() not in ('http','https') or not parts.hostname or parts.username or parts.password or parts.fragment:
            raise ValueError('Укажи HTTP(S)-адрес без пароля и фрагмента. Секреты здесь не сохраняем.')
        # Одинаковый адрес с разным регистром домена не создаёт второй источник.
        location = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or '/', parts.query, ''))
    return dict(name=name, kind=kind, location=location, description=description)


class LibraryRepository:
    """Тонкий серверный доступ к существующим таблицам и атомарным операциям."""
    def __init__(self, client):
        self.db = client

    def sources(self, project=None):
        rows = self.db.table('cf_sources').select('*').order('name').execute().data or []
        links = self.db.table('cf_project_sources').select('*,cf_projects(name)').execute().data or []
        for row in rows:
            row['projects'] = [x for x in links if x['source_id']==row['id']]
            row['connection'] = next((x for x in row['projects'] if x['project_code']==project), None)
        return rows

    def source(self, source_id):
        return next((x for x in self.sources() if x['id']==str(source_id)), None)

    def save(self, source_id, values, project=None):
        return self.db.rpc('cf_library_save_source', {'p_id':str(UUID(str(source_id))), **{'p_'+k:v for k,v in values.items()}, 'p_project':project}).execute().data

    def connect(self, source_id, project='cccp'):
        self.db.table('cf_project_sources').upsert({'project_code':project,'source_id':str(source_id)}, on_conflict='project_code,source_id', ignore_duplicates=True).execute()

    def disconnect(self, source_id, project='cccp'):
        # Отключение не удаляет ни источник, ни отобранные материалы.
        self.db.table('cf_project_sources').delete().eq('project_code',project).eq('source_id',str(source_id)).execute()

    def settings(self, source_id, enabled, keyword, notes, project='cccp'):
        if len(keyword)>200 or len(notes)>2000:
            raise ValueError('Слишком длинные настройки.')
        self.db.table('cf_project_sources').update({'enabled':enabled,'keyword':keyword.strip(),'notes':notes.strip()}).eq('project_code',project).eq('source_id',str(source_id)).execute()

    def import_rss(self, source_id, page=1, fetch=get_articles):
        source = self.source(source_id)
        if not source or source['kind']!='rss':
            raise ValueError('Для этого типа загрузка ещё не реализована.')
        if not 1<=page<=100:
            raise ValueError('Страница RSS должна быть от 1 до 100.')
        articles = fetch(page=page, feed_url=source['location'])
        materials = prepare_materials(articles, source_id=str(source_id))
        count = self.db.rpc('cf_library_import', {'p_source':str(source_id),'p_location':source['location'],'p_materials':materials}).execute().data
        return {'received':len(materials),'saved':count}

    def select(self, material=None, source=None, project='cccp'):
        return self.db.rpc('cf_library_select',{'p_project':project,'p_material':str(material) if material else None,'p_source':str(source) if source else None}).execute().data

    def materials(self, project=None, offset=0, search=''):
        fields = 'id,title,url,published_at,source_id,protected'
        if project:
            fields += ',cf_project_materials!inner(project_code)'
        q = self.db.table('cf_materials').select(fields,count='exact')
        if project:
            q=q.eq('cf_project_materials.project_code',project)
        if search.strip():
            pattern=search.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            q=q.ilike('title','%'+pattern+'%')
        # Сохраняем привычный порядок проекта по дате публикации;
        # общую библиотеку сначала группируем по времени получения.
        if not project:
            q=q.order('imported_at',desc=True)
        r=q.order('published_at',desc=True).order('id').range(offset,offset+19).execute()
        return r.data or [],r.count or 0

    def cleanup(self, before):
        dt=datetime.fromisoformat(before).replace(tzinfo=timezone.utc)
        return self.db.rpc('cf_library_cleanup_preview',{'p_before':dt.isoformat(),'p_limit':50}).execute().data or []
