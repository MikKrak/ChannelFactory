"""Объяснимый RSS-отбор: алгоритм, неполные поля и безопасный мастер."""
import copy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import os
from unittest.mock import patch
import unittest
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rss_filter import classify,normalize_rules,analyze,contains
import rss_filter_service as service
import rss_filter_routes as routes

SID='e3c9eb83-5a5f-4351-836b-c2f93b4fa567'
ENTRIES=[{'title':'Защита садовых растений','url':'https://example.com/garden','description':'Уход за садом и земляникой.','categories':['Сад и огород'],'available_fields':['title','summary','tags']},{'title':'Суп на ужин','url':'https://example.com/food','description':'Простой рецепт','categories':['Рецепты']},{'title':'Без рубрик','url':'https://example.com/unknown','description':'Описание без рубрик'}]


class AlgorithmTests(unittest.TestCase):
    def test_inclusions_exclusions_and_reasons(self):
        rules=normalize_rules({'include_categories':['Сад и огород'],'exclude_categories':['Рецепты']})
        self.assertEqual([classify(e,rules)['state'] for e in ENTRIES],['accepted','rejected','uncertain'])
        self.assertIn('Рецепты',classify(ENTRIES[1],rules)['reasons'][0])
        rules['exclude_words']=['земляника']
        result=classify(ENTRIES[0],rules)
        self.assertEqual(result['state'],'rejected');self.assertIn('описание',result['reasons'][0])

    def test_and_or_and_empty_groups(self):
        rules={'include_categories':['Рецепты'],'include_words':['растения']}
        self.assertEqual(classify(ENTRIES[0],rules)['state'],'rejected')
        self.assertEqual(classify(ENTRIES[0],{**rules,'combine':'any'})['state'],'accepted')
        self.assertEqual(classify(ENTRIES[0],{})['state'],'accepted')
        self.assertEqual(classify({}, {})['state'],'uncertain')

    def test_word_boundaries_forms_phrases_and_case(self):
        self.assertTrue(contains('Уход за САДОВЫМИ растениями','садовые растения',True))
        self.assertTrue(contains('Чёрная смородина','черная смородина',False))
        self.assertTrue(contains('Сажаем томаты и землянику','томат',True))
        self.assertFalse(contains('Посадка рассады','сад',True))
        self.assertFalse(contains('Растения для дома','растение',False))
        self.assertFalse(contains('Уход и защита для сада','уход сада',True))

    def test_missing_fields_conservative_no_semantics(self):
        self.assertEqual(classify({'title':'Сад'}, {'include_words':['томат']})['state'],'uncertain')
        self.assertEqual(classify({'title':'Сад','description':'Полное описание'}, {'include_words':['томат']})['state'],'rejected')
        self.assertEqual(classify({'title':'Сад'}, {'include_words':['сад'],'exclude_words':['реклама']})['state'],'uncertain')
        self.assertEqual(classify({'title':'Сад','categories':['Сад']},{'include_categories':['Сад']})['state'],'accepted')

    def test_profile_and_invalid_rules(self):
        profile=analyze(ENTRIES)
        self.assertEqual(profile['total'],3);self.assertEqual(profile['missing_categories'],1)
        self.assertIn(('tags',1),profile['fields'])
        for config in ({'combine':'code'},{'include_words':['x'*101]},{'include_categories':['a']*51},{'match_forms':'yes'}):
            with self.assertRaises(ValueError):normalize_rules(config)
        self.assertEqual(normalize_rules({'include_words':'Сад\nсад\n\nТоматы'})['include_words'],['Сад','Томаты'])


    def test_rss_metadata_kept_and_invalid_date_does_not_drop_article(self):
        from source import get_articles,prepare_materials
        from types import SimpleNamespace
        xml=b'<rss version="2.0"><channel><title>Other feed</title><item><title>Garden</title><link>https://other.example/a</link><description>&lt;b&gt;Plants&lt;/b&gt;</description><category>Topic</category><pubDate>unknown</pubDate></item></channel></rss>'
        with patch('source.requests.get',return_value=SimpleNamespace(content=xml,raise_for_status=lambda:None)):
            entries=get_articles(feed_url='https://other.example/feed')
        self.assertEqual(entries[0]['categories'],['Topic'])
        self.assertEqual(entries[0]['description'],'Plants')
        self.assertIsNone(prepare_materials(entries)[0]['published_at'])
        self.assertEqual(prepare_materials(entries)[0]['raw_data']['categories'],['Topic'])


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.repo=service.DemoRepository(ENTRIES)
        self.env=patch.dict(os.environ,{'CF_RSS_FILTER_DEMO':'1','CF_RSS_FILTER_ENABLED':'0'});self.env.start()
        self.mock=patch.object(routes,'repository',return_value=self.repo);self.mock.start()
        app=FastAPI();app.include_router(routes.router);self.client=TestClient(app)
        self.path='/studio/library/sources/'+SID+'/filter'
        page=self.client.get(self.path+'?project=cccp')
        self.token=BeautifulSoup(page.text,'html.parser').select_one('input[name=token]')['value']
        self.data={'project':'cccp','token':self.token,'revision':0,'include_categories':'Сад и огород','exclude_categories':'Рецепты','combine':'all','match_forms':'yes','auto_select':'yes'}
    def tearDown(self):self.mock.stop();self.env.stop()

    def test_preview_does_not_save_confirmed_save_changes_only_demo_rules(self):
        r=self.client.post(self.path,data={**self.data,'action':'test'})
        self.assertEqual(r.status_code,200)
        for text in ('Подходит: 1','Не подходит: 1','Сомнительно: 1','Защита садовых растений'):self.assertIn(text,r.text)
        self.assertIsNone(self.repo.rule)
        self.assertEqual(self.client.post(self.path,data={**self.data,'action':'save'}).status_code,422)
        r=self.client.post(self.path,data={**self.data,'action':'save','confirmed':'yes'})
        self.assertEqual(r.status_code,200);self.assertEqual(self.repo.revision,1)
        self.assertEqual(self.repo.rule['include_categories'],['Сад и огород'])
        self.assertEqual(self.repo.sample,ENTRIES)

    def test_untested_changed_rules_and_expired_token_cannot_save(self):
        r=self.client.post(self.path,data={**self.data,'action':'save','confirmed':'yes'})
        self.assertEqual(r.status_code,422);self.assertIsNone(self.repo.rule)
        self.client.post(self.path,data={**self.data,'action':'test'})
        r=self.client.post(self.path,data={**self.data,'include_words':'томат','action':'save','confirmed':'yes'})
        self.assertEqual(r.status_code,422);self.assertIsNone(self.repo.rule)
        service.samples.items[self.token]['at']-=1801
        self.assertEqual(self.client.post(self.path,data={**self.data,'action':'test'}).status_code,422)

    def test_invalid_input_retained_and_html_escaped(self):
        r=self.client.post(self.path,data={**self.data,'include_words':'<script>alert(1)</script>','action':'test'})
        self.assertNotIn('<script>alert(1)</script>',r.text)
        r=self.client.post(self.path,data={**self.data,'include_words':'я'*101,'action':'test'})
        self.assertEqual(r.status_code,422);self.assertIn('я'*101,r.text)

    def test_disabled_gate_no_database_access(self):
        with patch.dict(os.environ,{'CF_RSS_FILTER_DEMO':'0','CF_RSS_FILTER_ENABLED':'0'}),patch.object(routes,'repository') as repo:
            self.assertEqual(self.client.get(self.path).status_code,422);repo.assert_not_called()
