"""Каркас интерфейса: режимы/навигация и изолированная модель вкладок.

Без подключения к Supabase и без вызова операций приложения.
"""
from pathlib import Path
import shutil
import subprocess
import unittest
from bs4 import BeautifulSoup
import studio_views as view
import workspace_views as shell

ROOT=Path(__file__).resolve().parents[1]


class WorkspaceTests(unittest.TestCase):
    def parse(self, html):return BeautifulSoup(html,'html.parser')

    def test_factory_dashboard_scope_and_real_counts(self):
        doc=self.parse(view.projects({'materials':148,'selected':99,'draft':3,'ready':2}))
        self.assertEqual(doc.body['data-space'],'factory')
        self.assertEqual(doc.select_one('.command-bar .brand')['href'],'/studio')
        self.assertEqual(doc.h1.get_text(),'Рабочий пульт')
        self.assertNotIn('СССР',doc.select_one('.breadcrumbs').get_text())
        self.assertIn('148',doc.get_text())
        self.assertEqual(len(doc.select('.factory-project-row')),1)
        self.assertEqual(doc.select_one('.factory-project-row a')['href'],'/studio/cccp')
        self.assertNotIn('Другие проекты',doc.get_text())
        self.assertEqual(len(doc.select('.factory-resources a')),3)

    def test_project_scope_navigation_and_panels(self):
        doc=self.parse(view.layout('Материалы','<h1>Материалы</h1>','materials'))
        self.assertEqual(doc.body['data-space'],'cccp')
        self.assertEqual(doc.select_one('.factory-return')['href'],'/studio')
        self.assertEqual(len(doc.select('#project-picker option')),2)
        self.assertEqual(doc.select_one('#project-picker option[selected]')['value'],'/studio/cccp')
        self.assertEqual(len(doc.select('[data-toggle-panel]')),2)
        self.assertEqual(len(doc.select('[data-resize-panel]')),2)
        self.assertIn('СССР',doc.select_one('.breadcrumbs').get_text())
        for path in ('/studio/cccp/materials','/studio/cccp/sources','/studio/cccp/posts','/studio/cccp/inbox','/studio/library/materials'):
            self.assertIsNotNone(doc.select_one(f'.workspace-navigation a[href="{path}"]'))
        self.assertIn('Объект не выбран',doc.select_one('.workspace-inspector').get_text())

    def test_inspector_escapes_context_and_has_only_safe_links(self):
        doc=self.parse(shell.render('Title','',context={'kind':'<script>','title':'<img src=x onerror=alert(1)>','fields':[('Поле','<b>value</b>')],'links':[('bad','javascript:alert(1)'),('bad2','//evil.example'),('Good','https://example.com/source')]}))
        panel=doc.select_one('.workspace-inspector')
        self.assertIsNone(panel.find('script'))
        self.assertIsNone(panel.find('img'))
        self.assertIn('<b>value</b>',panel.get_text())
        self.assertEqual([x['href'] for x in panel.find_all('a')],['https://example.com/source'])
        self.assertIsNone(panel.find('form'))

    def test_source_and_material_global_views_keep_factory_mode(self):
        import library_views
        for page in (library_views.source_list([]),library_views.material_list([],0),library_views.cleanup()):
            doc=self.parse(page)
            self.assertEqual(doc.body['data-space'],'factory')
            self.assertNotIn('СССР',doc.select_one('.breadcrumbs').get_text())
        project=self.parse(library_views.source_list([],project=True))
        self.assertEqual(project.body['data-space'],'cccp')

    def test_no_fake_zero_when_factory_counters_unavailable(self):
        doc=self.parse(view.projects())
        self.assertIn('Счётчики сейчас недоступны',doc.get_text())
        self.assertEqual(len(doc.select('.project-metrics')),0)

    def test_legacy_get_links_redirect_without_data_access(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from workspace_routes import router
        app=FastAPI();app.include_router(router)
        client=TestClient(app)
        ident='7ef10475-0397-4539-8e54-72797a6dc394'
        for old,new in [('/materials','/studio/cccp/materials'),('/posts?status=ready','/studio/cccp/posts?status=ready'),('/material/'+ident,'/studio/cccp/materials/'+ident),('/post/'+ident,'/studio/cccp/posts/'+ident)]:
            result=client.get(old,follow_redirects=False)
            self.assertEqual(result.status_code,303)
            self.assertEqual(result.headers['location'],new)
        self.assertEqual(client.post('/post/'+ident).status_code,405)
        self.assertEqual(client.get('/post/not-an-id').status_code,422)

    @unittest.skipUnless(shutil.which('node'),'Node нужен только для изолированной проверки модели JS')
    def test_javascript_navigation_model(self):
        result=subprocess.run([shutil.which('node'),str(ROOT/'tests/test_workspace_model.cjs')],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
