"""Версия 2: только изолированная БД. Сохранение не импортирует и не меняет ссылки."""
import os
from pathlib import Path
import unittest
from test_library_sql import fixture
from test_publication_sql import sql,literal
from rss_filter_config import normalize
ROOT=Path(__file__).resolve().parents[1]
SID='e3c9eb83-5a5f-4351-836b-c2f93b4fa567'

@unittest.skipUnless(os.environ.get('CF_TEST_POSTGRES')=='1','Нужна изолированная PostgreSQL')
class ConfigSQLTests(unittest.TestCase):
    def setUp(self):
        if sql('SHOW data_directory',False).stdout.strip()!='/private/tmp/cf-publication-pg-20261029':raise RuntimeError('Refusing non-test cluster')
        fixture();sql((ROOT/'sql/library.sql').read_text(),False);sql((ROOT/'sql/rss_filter.sql').read_text(),False)
        self.before=self.fingerprint();sql((ROOT/'sql/rss_filter_config.sql').read_text(),False)
    def fingerprint(self):return sql("SELECT md5(string_agg(x::text,'' ORDER BY x::text)) FROM (SELECT to_jsonb(m) x FROM cf_materials m UNION ALL SELECT to_jsonb(p) FROM cf_posts p UNION ALL SELECT to_jsonb(pm) FROM cf_project_materials pm) t").stdout.strip()
    def save(self,rev,rules,check=True):return sql('SELECT cf_filter_save('+','.join(map(literal,[SID,'cccp',rev,rules]))+')',check=check)
    def test_migration_autosave_disabled_and_toggle_preserve_contents(self):
        self.assertEqual(self.before,self.fingerprint())
        rules=normalize({'exclude_categories':['Рецепты']})
        self.assertEqual(self.save(0,rules).stdout.strip(),'1')
        rules['filter_enabled']=True;self.assertEqual(self.save(1,rules).stdout.strip(),'2')
        rules['filter_enabled']=False;self.assertEqual(self.save(2,rules).stdout.strip(),'3')
        self.assertEqual(self.before,self.fingerprint())
        self.assertEqual(sql('SELECT count(*) FROM cf_material_filter_results').stdout.strip(),'0')
        self.assertEqual(sql("SELECT filter_rules->'exclude_categories' FROM cf_project_sources").stdout.strip(),'["Рецепты"]')
    def test_invalid_or_conflicting_save_rolls_back_and_client_cannot_call(self):
        r=normalize({});self.save(0,r);before=self.fingerprint()
        self.assertNotEqual(self.save(0,{**r,'filter_enabled':True},False).returncode,0)
        for bad in ({**r,'include_categories':['Сад'],'exclude_categories':['сад']},{**r,'filter_enabled':'yes'},{**r,'category_default':'maybe'}):
            self.assertNotEqual(self.save(1,bad,False).returncode,0)
        self.assertEqual(sql('SELECT filter_revision FROM cf_project_sources').stdout.strip(),'1')
        self.assertEqual(before,self.fingerprint())
        self.assertEqual(sql("SELECT has_function_privilege('anon','cf_filter_save(uuid,text,bigint,jsonb)','EXECUTE')",False).stdout.strip(),'f')
    def test_new_rules_and_previous_version_both_validated(self):
        from rss_filter import classify
        r=normalize({'category_default':'exclude','include_categories':['Сад'],'exclude_categories':['Рецепты'],'filter_enabled':True})
        self.save(0,r)
        self.assertEqual(classify({'title':'Сад','categories':['Рецепты','Сад']},r)['state'],'accepted')
        self.assertEqual(sql("SELECT cf_filter_rules_valid('{\"version\":1,\"combine\":\"all\",\"match_forms\":true,\"auto_select\":true,\"include_categories\":[],\"exclude_categories\":[],\"include_words\":[],\"exclude_words\":[]}'::jsonb)").stdout.strip(),'t')

    def test_new_import_uses_v2_classifier_and_disabled_filter_does_not_rebind_old_materials(self):
        from rss_filter import classify
        from source import prepare_materials
        import json
        rules=normalize({'filter_enabled':True,'category_default':'exclude','include_categories':['Сад'],'exclude_categories':['Рецепты']})
        self.save(0,rules)
        entries=[{'title':'Сад','url':'https://example.test/mixed','description':'Полное описание','categories':['Рецепты','Сад']},{'title':'Рецепт','url':'https://example.test/food','description':'Полное описание','categories':['Рецепты']},{'title':'Без рубрик','url':'https://example.test/unknown','description':'Полное описание'}]
        materials=prepare_materials(entries,SID)
        def load(revision,items):
            plans=[{'project':'cccp','revision':revision,'rules_version':2,'decisions':[{'url':m['url'],**classify(m,rules)} for m in items]}]
            return json.loads(sql('SELECT cf_filter_import('+','.join(map(literal,[SID,'https://www.botanichka.ru/feed/',items,plans]))+')').stdout)
        self.assertEqual(load(1,materials),{'saved':3,'selected':1})
        rules['filter_enabled']=False;self.save(1,rules)
        self.assertEqual(load(2,materials),{'saved':0,'selected':0})
        fresh=prepare_materials([{'title':'Рецепт','url':'https://example.test/new-food','categories':['Рецепты']}],SID)
        self.assertEqual(load(2,fresh),{'saved':1,'selected':1})
        self.assertEqual(sql('SELECT count(*) FROM cf_project_materials').stdout.strip(),'100')

    def test_old_process_cannot_downgrade_or_import_without_v2_acknowledgement(self):
        from rss_filter import normalize_rules
        from source import prepare_materials
        r=normalize({'filter_enabled':True});self.save(0,r);before=self.fingerprint()
        self.assertNotEqual(self.save(1,normalize_rules({}),False).returncode,0)
        items=prepare_materials([{'title':'Новый','url':'https://example.test/legacy','categories':['Сад']}],SID)
        old=[{'project':'cccp','revision':1,'decisions':[{'url':items[0]['url'],'state':'accepted','reasons':['Old importer']}]}]
        result=sql('SELECT cf_filter_import('+','.join(map(literal,[SID,'https://www.botanichka.ru/feed/',items,old]))+')',check=False)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(before,self.fingerprint())
        self.assertEqual(sql('SELECT filter_revision FROM cf_project_sources').stdout.strip(),'1')
