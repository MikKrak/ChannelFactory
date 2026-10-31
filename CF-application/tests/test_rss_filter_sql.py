"""Правила и импорт — только синтетическая PostgreSQL, без сетевого RSS."""
import concurrent.futures
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from test_library_sql import fixture
from test_publication_sql import sql,literal
from rss_filter import normalize_rules,classify

ROOT=Path(__file__).resolve().parents[1]
SID='e3c9eb83-5a5f-4351-836b-c2f93b4fa567'
ENTRIES=[{'title':'Новый сад','url':'https://example.com/new-garden','description':'Уход за садом','categories':['Сад']},{'title':'Рецепт супа','url':'https://example.com/new-food','description':'Как сварить суп','categories':['Рецепты']},{'title':'Без рубрики','url':'https://example.com/new-unclear','description':'Текст без рубрик'}]


@unittest.skipUnless(os.environ.get('CF_TEST_POSTGRES')=='1','Требуется изолированная PostgreSQL')
class RSSFilterSQLTests(unittest.TestCase):
    def setUp(self):
        if sql('SHOW data_directory',False).stdout.strip()!='/private/tmp/cf-publication-pg-20261029':raise RuntimeError('Refusing non-test cluster')
        fixture();sql((ROOT/'sql/library.sql').read_text(),False)
        mid=sql("INSERT INTO cf_materials(source_id,url,title) VALUES("+literal(SID)+",'https://example.com/extra-old','Ручной выбор') RETURNING id").stdout.strip()
        sql("SELECT cf_library_select('cccp',"+literal(mid)+",NULL)")
        self.before=self.fingerprint()
        sql((ROOT/'sql/rss_filter.sql').read_text(),False)
        self.rules=normalize_rules({'include_categories':['Сад']})
    def scalar(self,q):return sql(q).stdout.strip()
    def call(self,name,*args,check=True):return sql('SELECT cf_filter_'+name+'('+','.join(map(literal,args))+')',check=check)
    def fingerprint(self):
        return self.scalar("SELECT md5(string_agg(x::text,'' ORDER BY x::text)) FROM (SELECT to_jsonb(m) x FROM cf_materials m UNION ALL SELECT to_jsonb(p) FROM cf_posts p UNION ALL SELECT to_jsonb(pm) FROM cf_project_materials pm) t")
    def save(self,project='cccp',rules=None,revision=0):return self.call('save',SID,project,revision,rules or self.rules)
    def materials(self):
        from source import prepare_materials
        return prepare_materials(ENTRIES,SID)
    def plan(self,project='cccp',rules=None,revision=1):
        return {'project':project,'revision':revision,'decisions':[{'url':e['url'],**classify(e,rules or self.rules)} for e in ENTRIES]}
    def load(self,plans=None,check=True):return self.call('import',SID,'https://www.botanichka.ru/feed/',self.materials(),[self.plan()] if plans is None else plans,check=check)

    def test_migration_and_saving_do_not_change_old_materials_or_99_links(self):
        self.assertEqual(self.before,self.fingerprint())
        self.assertEqual(self.save().stdout.strip(),'1')
        self.assertEqual(self.before,self.fingerprint())
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_project_materials'),'99')
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_material_filter_results'),'0')
        self.assertNotEqual(self.call('save',SID,'cccp',0,self.rules,check=False).returncode,0)

    def test_accepted_only_new_uncertain_retained_and_cleanup_protected(self):
        self.save();result=json.loads(self.load().stdout)
        self.assertEqual(result,{'saved':3,'selected':1})
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_materials'),'102')
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_project_materials'),'100')
        self.assertEqual(self.scalar("SELECT string_agg(decision,',' ORDER BY decision) FROM cf_material_filter_results"),'accepted,rejected,uncertain')
        self.assertEqual(self.scalar("SELECT count(*) FROM cf_library_cleanup_preview(now()+interval '1 day')"),'1')
        self.assertEqual(json.loads(self.load().stdout),{'saved':0,'selected':0})

    def test_independent_projects_and_concurrent_import(self):
        sql("INSERT INTO cf_projects VALUES('other','Синтетический проект'); INSERT INTO cf_project_sources(project_code,source_id) VALUES('other',"+literal(SID)+')')
        other=normalize_rules({'include_categories':['Рецепты']})
        self.save();self.save('other',other)
        query='SELECT cf_filter_import('+','.join(map(literal,[SID,'https://www.botanichka.ru/feed/',self.materials(),[self.plan(),self.plan('other',other)]]))+')'
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:json.loads(sql(query).stdout),range(2)))
        self.assertEqual(sorted(x['saved'] for x in results),[0,3])
        self.assertEqual(self.scalar("SELECT count(*) FROM cf_project_materials WHERE project_code='other'"),'1')
        self.assertEqual(self.scalar("SELECT m.title FROM cf_project_materials p JOIN cf_materials m ON m.id=p.material_id WHERE p.project_code='other'"),'Рецепт супа')
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_material_filter_results'),'6')

    def test_changed_revision_or_incomplete_decisions_roll_back_entire_batch(self):
        self.save();before=self.fingerprint()
        self.assertNotEqual(self.load([self.plan(revision=0)],False).returncode,0)
        plan=self.plan();plan['decisions'].pop()
        self.assertNotEqual(self.load([plan],False).returncode,0)
        self.assertEqual(before,self.fingerprint())
        sql("UPDATE cf_project_sources SET enabled=false WHERE project_code='cccp'")
        self.assertNotEqual(self.load(check=False).returncode,0)
        self.assertEqual(json.loads(self.load([],True).stdout),{'saved':3,'selected':0})

    def test_legacy_bulk_selection_cannot_bypass_rules_manual_single_still_works(self):
        self.save()
        old_import='SELECT cf_library_import('+','.join(map(literal,[SID,'https://www.botanichka.ru/feed/',self.materials()]))+')'
        self.assertNotEqual(sql(old_import,check=False).returncode,0)
        self.assertNotEqual(sql('SELECT cf_library_select(\'cccp\',NULL,'+literal(SID)+')',check=False).returncode,0)
        mid=self.scalar('SELECT id FROM cf_materials LIMIT 1')
        self.assertEqual(sql("SELECT cf_library_select('cccp',"+literal(mid)+',NULL)').returncode,0)

    def test_clients_and_malformed_configuration_rejected(self):
        self.assertNotEqual(self.call('save',SID,'cccp',0,{'version':1},check=False).returncode,0)
        for role in ('anon','authenticated'):
            for q in ('SELECT * FROM cf_material_filter_results','SELECT cf_filter_save('+','.join(map(literal,[SID,'cccp',0,self.rules]))+')'):
                self.assertNotEqual(sql('SET ROLE '+role+';'+q,False,False).returncode,0)

    def test_python_normal_import_path_uses_current_config_and_atomic_rpc(self):
        from library import LibraryRepository
        self.save()
        class Query:
            def __init__(self,table):self.table=table;self.filters=[]
            def select(self,*args,**kwargs):return self
            def eq(self,key,value):self.filters.append(key+'='+literal(value));return self
            def execute(self):
                q="SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (SELECT * FROM "+self.table+(' WHERE '+' AND '.join(self.filters) if self.filters else '')+') x'
                return SimpleNamespace(data=json.loads(sql(q).stdout))
        class Client:
            def table(self,name):return Query(name)
            def rpc(self,name,params):
                q='SELECT to_jsonb('+name+'('+','.join(k+'=>'+literal(v) for k,v in params.items())+'))'
                return SimpleNamespace(execute=lambda:SimpleNamespace(data=json.loads(sql(q).stdout)))
        repo=LibraryRepository(Client());repo.source=lambda _: {'kind':'rss','location':'https://www.botanichka.ru/feed/'}
        with patch.dict(os.environ,{'CF_RSS_FILTER_ENABLED':'1'}):result=repo.import_rss(SID,fetch=lambda **kwargs:ENTRIES)
        self.assertEqual(result,{'received':3,'saved':3,'selected':1})
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_project_materials'),'100')
