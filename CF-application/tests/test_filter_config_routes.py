"""Новый API: только конфигурация/чтение, конкуренция и отсутствие тайных записей."""
import os
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_rss_filter import SID,ENTRIES
import rss_filter_routes as old
import rss_filter_service as service
import rss_filter_config_routes as routes
import unittest

class ConfigRouteTests(unittest.TestCase):
    def setUp(self):
        self.repo=service.DemoRepository(ENTRIES)
        self.env=patch.dict(os.environ,{'CF_RSS_FILTER_DEMO':'1','CF_RSS_FILTER_CONFIG_ENABLED':'1'});self.env.start()
        self.mock=patch.object(old,'repository',return_value=self.repo);self.mock.start()
        app=FastAPI();app.include_router(old.router);app.include_router(routes.router);self.client=TestClient(app)
        self.path=f'/studio/cccp/sources/{SID}/filter'
    def tearDown(self):self.mock.stop();self.env.stop()
    def test_open_does_not_save_defaults_sample_or_proposal(self):
        r=self.client.get(self.path);self.assertEqual(r.status_code,200)
        self.assertNotIn('name="confirmed"',r.text);self.assertNotIn('Сохранить фильтр',r.text)
        self.assertIsNone(self.repo.rule)
        r=self.client.post(self.path+'/sample',json={'kind':'fresh'})
        self.assertEqual(r.status_code,200);self.assertIn('fields_html',r.json())
        self.assertIsNotNone(r.json()['suggestion'])
        self.assertIsNone(self.repo.rule)
    def test_autosave_disabled_preview_and_conflict_do_not_touch_entries(self):
        state=self.client.get(self.path+'/config').json();r=state['rules'];r['exclude_categories']=['Рецепты']
        saved=self.client.post(self.path+'/config',json={'revision':0,'rules':r});self.assertEqual(saved.status_code,200)
        self.assertFalse(saved.json()['rules']['filter_enabled']);self.assertEqual(self.repo.sample,ENTRIES)
        sample=self.client.post(self.path+'/sample',json={'kind':'fresh'}).json()
        result=self.client.post(self.path+'/test',json={'token':sample['token'],'rules':r})
        self.assertEqual(result.status_code,200);self.assertIn('Подходит: 1',result.json()['html'])
        self.assertEqual(self.repo.revision,1)
        self.assertEqual(self.client.post(self.path+'/config',json={'revision':0,'rules':r}).status_code,409)
        invalid={**r,'include_categories':['Рецепты']}
        self.assertEqual(self.client.post(self.path+'/config',json={'revision':1,'rules':invalid}).status_code,422)
        self.assertEqual(self.repo.revision,1)
    def test_two_concurrent_demo_saves_have_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        rules=self.client.get(self.path+'/config').json()['rules']
        def save(_):
            try:return self.repo.save(SID,'cccp',0,rules)
            except ValueError:return 'conflict'
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(save,range(2)))
        self.assertCountEqual(results,[1,'conflict'])
        self.assertEqual(self.repo.revision,1)

    def test_unknown_save_failure_is_not_reported_as_success(self):
        state=self.client.get(self.path+'/config').json()
        self.assertFalse(state['configured'])
        with patch.object(self.repo,'save',side_effect=RuntimeError('SECRET')):
            response=self.client.post(self.path+'/config',json={'revision':0,'rules':state['rules']})
        self.assertEqual(response.status_code,503)
        self.assertNotIn('SECRET',response.text)
        self.assertIsNone(self.repo.rule)

    def test_legacy_requires_explicit_conversion_and_disabled_gate(self):
        self.repo.rule={'version':1,'include_categories':['Сад'],'auto_select':True}
        state=self.client.get(self.path+'/config').json();self.assertTrue(state['conversion_required'])
        data={'revision':0,'rules':state['rules']}
        self.assertEqual(self.client.post(self.path+'/config',json=data).status_code,422)
        self.assertEqual(self.repo.rule['version'],1)
        self.assertEqual(self.client.post(self.path+'/config',json={**data,'accept_conversion':True}).status_code,200)
        with patch.dict(os.environ,{'CF_RSS_FILTER_CONFIG_ENABLED':'0'}):
            self.assertEqual(self.client.get(self.path+'/config').status_code,422)
