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

    def test_editor_panels_inspector_and_no_activation_control(self):
        from bs4 import BeautifulSoup
        self.repo.rule={'version':2,'include_categories':['Сохранённая рубрика'],'exclude_categories':['Другая'],'filter_enabled':False}
        page=BeautifulSoup(self.client.get(self.path).text,'html.parser')
        self.assertFalse(page.select('[name=filter_enabled]'))
        self.assertEqual(len(page.select('#config-panels > section')),2)
        self.assertTrue(page.select_one('#config-results-pane').has_attr('hidden'))
        self.assertEqual(len(page.select('[data-panel-max]')),2)
        self.assertTrue(page.select_one('#workspace-inspector [data-sample=fresh]'))
        self.assertTrue(page.select_one('#config-form [data-sample=fresh]'))
        self.assertTrue(page.select_one('#config-editor-fields'))
        self.assertTrue(page.select_one('#config-reference-status[role=status]'))
        self.assertTrue(page.select_one('#config-divider[role=separator][tabindex]'))
        self.assertTrue(page.select_one('#config-all'))
        self.assertFalse(page.select_one('textarea[name=include_categories]').find_parent('label'))
        self.assertIn('Сохранённая рубрика',page.select_one('#config-initial').text)
        self.assertEqual(self.repo.revision,0)

    def test_activation_rejects_unprepared_stale_and_invalid_rules(self):
        response=self.client.post(self.path+'/activation',data={'revision':0,'active':'true'},follow_redirects=False)
        self.assertIn('filter_message=',response.headers['location']);self.assertIsNone(self.repo.rule)
        self.repo.rule={'version':2,'filter_enabled':False,'include_words':['x'*101]}
        self.client.post(self.path+'/activation',data={'revision':0,'active':'true'},follow_redirects=False)
        self.assertEqual(self.repo.revision,0)
        self.repo.rule={'version':2,'filter_enabled':False,'include_categories':['Сад']}
        self.client.post(self.path+'/activation',data={'revision':9,'active':'true'},follow_redirects=False)
        self.assertEqual(self.repo.revision,0)

    def test_activation_changes_only_flag_and_preserves_disabled_rules(self):
        from rss_filter_config import normalize
        self.repo.rule=normalize({'include_categories':['Сад'],'exclude_words':['яд']})
        original=self.repo.rule.copy()
        for active in ['true','false']:
            response=self.client.post(self.path+'/activation',data={'revision':self.repo.revision,'active':active},follow_redirects=False)
            self.assertEqual(response.status_code,303)
            self.assertEqual(self.repo.rule,{**original,'filter_enabled':active=='true'})
        self.assertEqual(self.repo.sample,ENTRIES)
        self.assertEqual(self.repo.revision,2)
        with patch.object(self.repo,'connection',return_value={'filter_rules':self.repo.rule,'filter_revision':2,'enabled':False}):
            response=self.client.post(self.path+'/activation',data={'revision':2,'active':'true'},follow_redirects=False)
            self.assertEqual(self.repo.revision,2)

    def test_legacy_cannot_enable_and_disable_preserves_conditions(self):
        from rss_filter import normalize_rules
        self.repo.rule=normalize_rules({'include_categories':['Сад'],'auto_select':True})
        original=self.repo.rule.copy()
        self.client.post(self.path+'/activation',data={'revision':0,'active':'true'},follow_redirects=False)
        self.assertEqual(self.repo.revision,0)
        self.client.post(self.path+'/activation',data={'revision':0,'active':'false'},follow_redirects=False)
        self.assertEqual(self.repo.rule,{**original,'auto_select':False})

    def test_source_list_activation_is_separate_from_connection(self):
        from bs4 import BeautifulSoup
        import library_views
        item={'id':SID,'name':'RSS','kind':'rss','projects':[],'connection':self.repo.connection(SID,'cccp')}
        page=BeautifulSoup(library_views.source_list([item],True),'html.parser')
        activation=page.select_one('form[action$="/activation"]')
        self.assertTrue(activation.select_one('button').has_attr('disabled'))
        self.assertIn('Не настроен',page.get_text())
        self.assertTrue(page.find('a',string='Настройка'))
        self.repo.rule={'version':2,'filter_enabled':True}
        item['connection']=self.repo.connection(SID,'cccp')
        page=BeautifulSoup(library_views.source_list([item],True),'html.parser')
        self.assertEqual(page.select_one('form[action$="/activation"] button').get_text(),'Выключить')
        factory=BeautifulSoup(library_views.source_list([item],False),'html.parser')
        self.assertFalse(factory.select('form[action$="/activation"]'))

    def test_test_cards_edit_only_shared_rules_and_keep_preview_temporary(self):
        from bs4 import BeautifulSoup
        sample=self.client.post(self.path+'/sample',json={'kind':'fresh'}).json()
        self.assertIn('recommendations',sample)
        self.assertIn('Сад и огород',sample['recommendations'])
        rules=self.client.get(self.path+'/config').json()['rules']
        rules.update(category_default='exclude',include_categories=['Сад и огород'])
        response=self.client.post(self.path+'/test',json={'token':sample['token'],'rules':rules})
        cards=BeautifulSoup(response.json()['content_html'],'html.parser')
        self.assertTrue(cards.select('.result-material [data-result-category]'))
        garden=cards.select_one('[data-result-category="Сад и огород"]')
        self.assertTrue(garden.has_attr('checked'))
        self.assertFalse(cards.select_one('[data-result-category="Рецепты"]').has_attr('checked'))
        self.assertFalse(cards.select('form,button,a[href*="/select"],a[href*="/import"],a[href*="/publish"]'))
        self.assertIn('других материалов',cards.get_text())
        self.assertEqual(self.repo.revision,0);self.assertIsNone(self.repo.rule)
        self.assertEqual(self.repo.sample,ENTRIES)

    def test_category_views_recommendations_and_panel_recovery_have_accessible_controls(self):
        from bs4 import BeautifulSoup
        page=BeautifulSoup(self.client.get(self.path).text,'html.parser')
        self.assertTrue(page.select_one('#config-category-workspace [aria-label="Все рубрики"]'))
        self.assertTrue(page.select_one('#config-selected-pane[aria-label="Выбранные рубрики"]'))
        self.assertTrue(page.select_one('#config-show-recommended'))
        self.assertTrue(page.select_one('#config-selected-hide[title][aria-label]'))
        self.assertTrue(page.select_one('#config-selected-show[title][aria-label]'))
        self.assertFalse(page.select('.config-panel-bar,#config-suggestion'))
        for key in ('editor','results'):
            self.assertTrue(page.select_one(f'#config-panel-recovery [data-panel-show="{key}"][title][aria-label]'))
            other='results' if key=='editor' else 'editor'
            self.assertTrue(page.select_one(f'#config-{key}-pane header [data-panel-show="{other}"]'))
        self.assertIsNone(self.repo.rule)
