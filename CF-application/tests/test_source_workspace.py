"""012: границы фабрики/проекта и настройка без рабочих побочных операций."""
import copy
import os
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import UUID
import unittest
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import rss_filter_routes as routes
import rss_filter_service as service
import library_views
from test_rss_filter import ENTRIES,SID


class SourceWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.repo=service.DemoRepository(ENTRIES)
        self.env=patch.dict(os.environ,{'CF_RSS_FILTER_DEMO':'1','CF_RSS_FILTER_ENABLED':'0'});self.env.start()
        self.mock=patch.object(routes,'repository',return_value=self.repo);self.mock.start()
        app=FastAPI();app.include_router(routes.router);self.client=TestClient(app)
        self.path=f'/studio/cccp/sources/{SID}/filter'
    def tearDown(self):self.mock.stop();self.env.stop()

    def test_project_context_legacy_link_and_no_operational_forms(self):
        response=self.client.get(f'/studio/library/sources/{SID}/filter?project=cccp')
        self.assertEqual(response.url.path,self.path)
        page=BeautifulSoup(response.text,'html.parser')
        self.assertEqual(page.body['data-space'],'cccp')
        self.assertEqual(page.body['data-tool'],'sources')
        form=page.select_one('form.filter-workform')
        self.assertEqual(form['action'],self.path)
        self.assertEqual({b.get('value') for b in form.select('button[name=action]')},{'analyze','stored','test','save'})
        self.assertFalse(page.select('form[action$="/import"],form[action$="/select"],form[action$="/settings"],form[action$="/publish-now"]'))
        self.assertEqual(len(page.select('.filter-columns > .filter-pane')),3)
        self.assertIn('href="/studio/cccp/sources"',response.text)

    def test_url_project_wins_over_posted_context_and_preview_is_temporary(self):
        before=copy.deepcopy(self.repo.sample)
        response=self.client.get(self.path)
        token=BeautifulSoup(response.text,'html.parser').select_one('[name=token]')['value']
        response=self.client.post(self.path,data={'project':'other','token':token,'action':'test','include_categories':'Сад и огород','combine':'all'})
        self.assertEqual(response.status_code,200)
        self.assertIn('Подходит: 1',response.text)
        self.assertIsNone(self.repo.rule)
        self.assertEqual(before,self.repo.sample)
        self.assertEqual(self.repo.revision,0)
        page=BeautifulSoup(response.text,'html.parser')
        self.assertEqual(page.select_one('form.filter-workform')['data-unsaved'],'true')
        self.assertEqual(len(page.select('.result-group')),3)
        self.assertIn('временный предпросмотр',response.text)

    def test_project_route_retains_validation_and_version_guard(self):
        response=self.client.get(self.path)
        token=BeautifulSoup(response.text,'html.parser').select_one('[name=token]')['value']
        self.assertEqual(self.client.post(self.path,data={'action':'test','token':token,'include_words':'x'*6001}).status_code,422)
        data={'action':'test','token':token,'include_words':'сад','combine':'all'}
        self.assertEqual(self.client.post(self.path,data=data).status_code,200)
        self.repo.revision=1
        response=self.client.post(self.path,data={**data,'action':'save','confirmed':'yes','revision':0})
        self.assertEqual(response.status_code,422)
        self.assertIsNone(self.repo.rule)

    def test_factory_does_not_assign_projects_and_project_has_explicit_setup(self):
        item={'id':SID,'name':'Example RSS','kind':'rss','location':'https://example.org/feed','projects':[{'project_code':'cccp','cf_projects':{'name':'Проект'}}],'connection':{'enabled':True}}
        factory=BeautifulSoup(library_views.source_list([item]),'html.parser')
        self.assertFalse(factory.select('form[action$="/connect"]'))
        self.assertIn('Проект',factory.get_text())
        project=BeautifulSoup(library_views.source_list([item],True),'html.parser')
        setup=project.find('a',string='Настроить')
        self.assertEqual(setup['href'],self.path)
        detail=BeautifulSoup(library_views.source_page(item,True),'html.parser')
        self.assertFalse(detail.select('form[action$="/save"]'))
        self.assertIn('Общие сведения',detail.get_text())
        shared=BeautifulSoup(library_views.source_page(item),'html.parser')
        self.assertTrue(shared.select('form[action$="/save"]'))
        self.assertFalse(shared.select('form[action$="/settings"],form[action$="/connect"]'))

    def test_compact_heading_accessible_touch_help_and_visible_state(self):
        response=self.client.get(self.path)
        page=BeautifulSoup(response.text,'html.parser')
        self.assertIn('source-settings',page.body['class'])
        self.assertEqual(len(page.select('.filter-top h1')),1)
        self.assertFalse(page.select('.filter-top p'))
        self.assertEqual(len(page.select('details.filter-help > summary[aria-label][title]')),3)
        self.assertEqual(page.select_one('.filter-mode').get_text(),'Фильтр не настроен')
        buttons={x.get_text() for x in page.select('button[name=action]')}
        self.assertTrue({'Получить свежую выборку','Проверить на материалах библиотеки','Проверить отбор'} <= buttons)
        token=page.select_one('[name=token]')['value']
        response=self.client.post(self.path,data={'action':'test','token':token,'include_categories':'Сад и огород'})
        header=BeautifulSoup(response.text,'html.parser').select_one('.filter-summary-counts')
        self.assertIn('Подходит: 1',header.get_text())
        self.assertIn('Не подходит: 1',header.get_text())
        self.assertIn('Сомнительно: 1',header.get_text())
        self.assertIsNone(self.repo.rule)

    def test_field_labels_and_unknown_fields_are_not_guessed(self):
        from rss_filter_views import field_reference
        html=field_reference([('summary',4),('tags',3),('unknown_vendor_field',1)])
        self.assertIn('Описание из RSS',html)
        self.assertIn('Рубрики и метки',html)
        self.assertIn('Неизвестное поле',html)
        self.assertIn('unknown_vendor_field',html)
        self.assertIn('Имя в RSS',html)
