"""Источники: изолированные проверки интерфейса, RSS и разделения операций."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
# Клиент не соединяется с рабочей базой; в каждом тесте хранилище подменено.
with patch.dict(os.environ,{'SUPABASE_URL':'https://example.supabase.co','SUPABASE_KEY':'test-not-a-real-key'}), patch('supabase.create_client',return_value=SimpleNamespace()):
    import library_routes as routes
import library
import source
from fastapi import FastAPI
from fastapi.testclient import TestClient


class LibraryTests(unittest.TestCase):
    def test_source_validation_and_canonical_host(self):
        value=library.source_values(' RSS ','rss','HTTPS://Example.COM/feed',' описание ')
        self.assertEqual(value['location'],'https://example.com/feed')
        for address in ('javascript:alert(1)','https://name:secret@example.com/feed','file:///tmp/feed','https://example.com/#secret'):
            with self.assertRaises(ValueError):library.source_values('Имя','rss',address,'')
        self.assertEqual(library.source_values('БД','database','локальный каталог','')['kind'],'database')

    def test_rss_uses_registered_source_and_import_does_not_select(self):
        sid=str(uuid4());calls=[]
        class Client:
            def rpc(self,name,params):
                calls.append((name,params));return SimpleNamespace(execute=lambda:SimpleNamespace(data=1))
        repo=library.LibraryRepository(Client())
        repo.source=lambda _: {'kind':'rss','location':'https://example.com/feed'}
        def fetch(**kwargs):
            self.assertEqual(kwargs,{'page':3,'feed_url':'https://example.com/feed'})
            return [{'title':'Статья','url':'https://example.com/1','published':''}]
        self.assertEqual(repo.import_rss(sid,3,fetch),{'received':1,'saved':1})
        self.assertEqual([x[0] for x in calls],['cf_library_import'])
        self.assertEqual(calls[0][1]['p_materials'][0]['source_id'],sid)
        repo.source=lambda _: {'kind':'file','location':'test'}
        with self.assertRaises(ValueError):repo.import_rss(sid,fetch=fetch)
        self.assertEqual(len(calls),1)

    def test_real_rss_parser_with_synthetic_feed(self):
        xml=b'<rss version="2.0"><channel><title>Test</title><item><title>Article</title><link>https://example.com/a</link><pubDate>Fri, 30 Oct 2026 08:00:00 GMT</pubDate></item></channel></rss>'
        with patch.object(source.requests,'get',return_value=SimpleNamespace(content=xml,raise_for_status=lambda:None)) as get:
            rows=source.get_articles(page=1,feed_url='https://example.com/feed')
        self.assertEqual(rows[0]['title'],'Article')
        self.assertEqual(get.call_args.args,('https://example.com/feed',))
        self.assertEqual(source.prepare_materials(rows)[0]['published_at'],'2026-10-30T08:00:00+00:00')

    def test_rss_existing_defaults_preserved(self):
        result=source.prepare_materials([{'title':'Тест','url':'https://example.com/a','published':''}])
        self.assertEqual(result[0]['source_id'],source.SOURCE_ID)

    def test_interface_and_disabled_gate(self):
        app=FastAPI();app.include_router(routes.router)
        client=TestClient(app)
        with patch.dict(os.environ,{'CF_LIBRARY_ENABLED':'0'}),patch.object(routes,'repository') as repo:
            self.assertEqual(client.get('/studio/library/sources').status_code,503)
            repo.assert_not_called()
        sid=str(uuid4());repo=SimpleNamespace(
            sources=lambda *args:[],source=lambda _: {'id':sid,'name':'<script>secret</script>','kind':'api','location':'https://example.com/','projects':[]},
            cleanup=lambda _:[],select=lambda **kwargs:1)
        with patch.dict(os.environ,{'CF_LIBRARY_ENABLED':'1'}),patch.object(routes,'repository',return_value=repo):
            self.assertEqual(client.get('/studio/library/sources').status_code,200)
            page=client.get('/studio/cccp/sources/'+sid)
            self.assertIn('&lt;script&gt;',page.text)
            self.assertNotIn('<script>secret',page.text)
            self.assertIn('ещё не реализована',page.text)
            self.assertNotIn('Получить RSS',page.text)
            preview=client.get('/studio/library/cleanup?before=2026-10-01')
            self.assertIn('Удаление в этой версии отключено',preview.text)
            self.assertEqual(client.post('/studio/library/cleanup').status_code,405)
            self.assertEqual(client.post('/studio/library/materials/'+str(uuid4())+'/select',follow_redirects=False).status_code,303)

    def test_failed_source_save_retains_form(self):
        app=FastAPI();app.include_router(routes.router);client=TestClient(app)
        repo=SimpleNamespace(save=lambda *args: (_ for _ in ()).throw(RuntimeError('SECRET')))
        with patch.dict(os.environ,{'CF_LIBRARY_ENABLED':'1'}),patch.object(routes,'repository',return_value=repo):
            r=client.post('/studio/library/sources/'+str(uuid4())+'/save',data={'name':'Мой источник','kind':'rss','location':'https://example.com/feed','description':'Мои заметки'})
            self.assertEqual(r.status_code,503)
            self.assertIn('Мои заметки',r.text)
            self.assertNotIn('SECRET',r.text)

    def test_save_create_from_project_and_error_privacy(self):
        app=FastAPI();app.include_router(routes.router);client=TestClient(app)
        sid=str(uuid4());saved=[]
        repo=SimpleNamespace(save=lambda *args:saved.append(args))
        with patch.dict(os.environ,{'CF_LIBRARY_ENABLED':'1'}),patch.object(routes,'repository',return_value=repo):
            r=client.post('/studio/cccp/sources/'+sid+'/save',data={'name':'API','kind':'api','location':'https://example.com'},follow_redirects=False)
            self.assertEqual(r.status_code,303)
            self.assertEqual(saved[0][2],'cccp')
        with patch.dict(os.environ,{'CF_LIBRARY_ENABLED':'1'}),patch.object(routes,'repository',side_effect=RuntimeError('SECRET')):
            r=client.get('/studio/library/sources')
            self.assertEqual(r.status_code,503)
            self.assertNotIn('SECRET',r.text)
