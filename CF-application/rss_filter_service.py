"""rss_filter_service.py — выборки мастера, сохранение правил и планы импорта.

Предпросмотр не записывает данные. Демо-хранилище отделено от Supabase;
новый путь импорта включается только явным флагом после миграции.
"""
import copy
import json
import os
import time
from pathlib import Path
from uuid import uuid4
from source import get_articles, SOURCE_ID
from rss_filter import classify, normalize_rules, rule_hash


def enabled():return os.environ.get('CF_RSS_FILTER_ENABLED')=='1'
def demo():return os.environ.get('CF_RSS_FILTER_DEMO')=='1'
def available():return enabled() or demo()


class Samples:
    """Короткоживущие выборки в памяти, не в cookie/URL и не в рабочей базе."""
    def __init__(self):self.items={}
    def put(self,source,project,entries,label):
        now=time.monotonic()
        self.items={k:v for k,v in self.items.items() if now-v['at']<1800}
        while len(self.items)>=20:self.items.pop(next(iter(self.items)))
        token=str(uuid4());self.items[token]={'at':now,'source':str(source),'project':project,'entries':copy.deepcopy(entries[:200]),'label':label,'tested':set()}
        return token
    def get(self,token,source,project):
        row=self.items.get(token)
        if not row or time.monotonic()-row['at']>=1800 or row['source']!=str(source) or row['project']!=project:
            raise ValueError('Выборка устарела. Нажми «Анализировать» ещё раз.')
        return row

samples=Samples()


class FilterRepository:
    def __init__(self,client):self.db=client
    def projects(self):return self.db.table('cf_projects').select('code,name').order('name').execute().data or []
    def source(self,sid):
        rows=self.db.table('cf_sources').select('*').eq('id',str(sid)).limit(1).execute().data
        return rows[0] if rows else None
    def connection(self,sid,project):
        rows=self.db.table('cf_project_sources').select('*').eq('source_id',str(sid)).eq('project_code',project).limit(1).execute().data
        return rows[0] if rows else None
    def entries(self,sid):
        return self.db.table('cf_materials').select('id,title,url,raw_data').eq('source_id',str(sid)).order('imported_at',desc=True).limit(200).execute().data or []
    def analyze_feed(self,source):return get_articles(page=1,feed_url=source['location'])
    def save(self,sid,project,revision,rules):
        return self.db.rpc('cf_filter_save',{'p_source':str(sid),'p_project':project,'p_revision':revision,'p_rules':normalize_rules(rules)}).execute().data
    def results(self,sid,project,state):
        return self.db.table('cf_material_filter_results').select('decision,reasons,filter_revision,cf_materials(title,url)').eq('source_id',str(sid)).eq('project_code',project).eq('decision',state).order('checked_at',desc=True).limit(200).execute().data or []
    def import_plans(self,sid,materials):
        rows=self.db.table('cf_project_sources').select('*').eq('source_id',str(sid)).execute().data or []
        plans=[]
        for row in rows:
            rules=row.get('filter_rules')
            if row['enabled'] and rules and rules.get('auto_select'):
                plans.append({'project':row['project_code'],'revision':row['filter_revision'],'decisions':[{'url':m['url'],**classify(m,rules)} for m in materials]})
        return plans


class DemoRepository:
    """Снимок публичного RSS и правила в памяти; ни одного рабочего запроса/изменения."""
    def __init__(self,entries,stored=None):self.sample=copy.deepcopy(entries);self.stored=copy.deepcopy(entries if stored is None else stored);self.rule=None;self.revision=0
    def projects(self):return [{'code':'cccp','name':'СССР — тестовая копия настроек'}]
    def source(self,sid):return {'id':str(sid),'name':'Ботаничка · публичный RSS-снимок','kind':'rss','location':'https://www.botanichka.ru/feed/'} if str(sid)==SOURCE_ID else None
    def connection(self,sid,project):
        if project!='cccp':return None
        return {'filter_rules':copy.deepcopy(self.rule),'filter_revision':self.revision,'enabled':True}
    def entries(self,sid):return copy.deepcopy(self.stored)
    def analyze_feed(self,source):return copy.deepcopy(self.sample)
    def save(self,sid,project,revision,rules):
        if project!='cccp' or revision!=self.revision:raise ValueError('Правила изменились. Открой мастер заново.')
        self.rule=normalize_rules(rules);self.revision+=1;return self.revision
    def results(self,sid,project,state):return []

_demo_repository=None

def repository(client):
    global _demo_repository
    if demo():
        if _demo_repository is None:
            path=Path(os.environ.get('CF_RSS_FILTER_SAMPLE','/private/tmp/cf-rss-filter-011-sample.json'))
            stored_path=Path(os.environ.get('CF_RSS_FILTER_STORED','/private/tmp/cf-rss-filter-011-stored.json'))
            _demo_repository=DemoRepository(json.loads(path.read_text()),json.loads(stored_path.read_text()) if stored_path.exists() else None)
        return _demo_repository
    return FilterRepository(client)
