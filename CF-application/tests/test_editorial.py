"""Изолированные проверки редакционного цикла. Сеть и рабочая база не нужны.

Запуск из CF-application: .venv/bin/python -m unittest discover -s tests -v
"""
import copy
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Подменяем только соединение Supabase при импорте, затем проверяем настоящий код.
class ImportClient:
    pass

with patch.dict('os.environ', {'SUPABASE_URL': 'https://example.supabase.co', 'SUPABASE_KEY': 'test-not-a-real-key'}):
    with patch('supabase.create_client', return_value=ImportClient()):
        import database

from editor import prepare_post, replace_text
import studio
from fastapi import FastAPI
from fastapi.testclient import TestClient

MATERIAL = str(uuid4())
POST = str(uuid4())


class EditorTests(unittest.TestCase):
    def test_short_text_is_not_truncated(self):
        post = prepare_post({'title': 'Заголовок', 'content': {'text': 'Короткий полный текст'}})
        self.assertEqual(post['blocks'][0]['content'], 'Заголовок\n\nКороткий полный текст')

    def test_only_long_text_has_ellipsis(self):
        post = prepare_post({'content': {'text': 'слово ' * 120}})
        text = post['blocks'][0]['content']
        self.assertTrue(text.endswith('…'))
        self.assertLessEqual(len(text), 501)
        self.assertFalse(text.endswith('сло…'))

    def test_new_text_block_is_inserted_and_original_untouched(self):
        blocks = [{'type': 'image', 'url': 'https://example.com/a.jpg'}, {'type': 'source', 'url': 'https://example.com'}]
        before = copy.deepcopy(blocks)
        result = replace_text(blocks, 'Мой текст')
        self.assertEqual([b['type'] for b in result], ['image', 'text', 'source'])
        self.assertEqual(blocks, before)

    def test_multiple_text_blocks_are_not_duplicated(self):
        result = replace_text([{'type': 'text', 'content': 'A'}, {'type': 'text', 'content': 'B'}], 'C')
        self.assertEqual(result, [{'type': 'text', 'content': 'C'}])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.article = {'id': MATERIAL, 'title': '<script>alert(1)</script>', 'url': 'https://example.com/article', 'content': {'text': 'Полная статья', 'image_url': ''}}
        self.item = None
        self.saved = []
        self.patches = []
        def replace(name, value):
            p = patch.object(database, name, value)
            p.start(); self.patches.append(p)
        replace('get_material', lambda id: self.article if id == MATERIAL else None)
        replace('find_material_draft', lambda id: self.item if self.item and self.item['status'] == 'draft' else None)
        replace('get_post', lambda id: copy.deepcopy(self.item) if self.item and id == POST else None)
        replace('create_post', self.create)
        replace('update_post', self.update)
        replace('return_post_to_draft', self.reopen)
        replace('list_materials', lambda **kw: ([self.article], 1))
        replace('list_posts', lambda **kw: [self.item] if self.item else [])
        replace('count_materials', lambda: 1)
        replace('count_posts', lambda status: int(bool(self.item and self.item['status'] == status)))
        replace('get_posts', lambda **kw: [self.item] if self.item else [])
        app = FastAPI(); app.include_router(studio.router)
        self.client = TestClient(app, raise_server_exceptions=True)

    def tearDown(self):
        for p in reversed(self.patches): p.stop()

    def create(self, material_id, title, blocks):
        self.item = {'id': POST, 'material_id': MATERIAL, 'title': title, 'blocks': blocks, 'status': 'draft'}
        self.saved.append('create')
        return POST

    def update(self, id, text, status):
        self.item['blocks'] = replace_text(self.item['blocks'], text)
        self.item['status'] = status
        self.saved.append(status)

    def reopen(self, id):
        self.item['status'] = 'draft'
        self.saved.append('reopen')

    def test_full_cycle(self):
        self.assertEqual(self.client.get('/studio').status_code, 200)
        self.assertEqual(self.client.get(studio.view.BASE).status_code, 200)
        self.assertEqual(self.client.get(studio.view.BASE + '/materials').status_code, 200)
        path = studio.view.BASE + '/materials/' + MATERIAL
        page = self.client.get(path)
        self.assertNotIn('<script>alert(1)</script>', page.text)
        self.assertIn('&lt;script&gt;', page.text)
        saved = self.client.post(path + '/draft', data={'post_text': 'Первый черновик'}, follow_redirects=False)
        self.assertEqual(saved.status_code, 303)
        self.assertEqual(saved.headers['location'], studio.view.BASE + '/posts/' + POST)
        post_path = saved.headers['location']
        self.assertEqual(self.client.get(post_path).status_code, 200)
        self.client.post(post_path + '/save', data={'post_text': 'Готовый текст', 'action': 'ready'})
        self.assertEqual(self.item['status'], 'ready')
        self.assertIn('Редакционный текст готов', self.client.get(post_path).text)
        self.client.post(post_path + '/draft')
        self.assertEqual(self.item['status'], 'draft')

    def test_duplicate_material_submission_does_not_overwrite_draft(self):
        path = studio.view.BASE + '/materials/' + MATERIAL + '/draft'
        self.client.post(path, data={'post_text': 'Первая версия'})
        self.client.post(path, data={'post_text': 'Повторная версия'})
        self.assertEqual(self.item['blocks'][0]['content'], 'Первая версия')
        self.assertEqual(self.saved, ['create'])

    def test_empty_text_and_invalid_id(self):
        path = studio.view.BASE + '/materials/' + MATERIAL + '/draft'
        self.assertEqual(self.client.post(path, data={'post_text': '   '}).status_code, 422)
        self.assertEqual(self.saved, [])
        self.assertEqual(self.client.get(studio.view.BASE + '/posts/not-a-uuid').status_code, 422)
        self.assertEqual(self.client.get(studio.view.BASE + '/materials/' + str(uuid4())).status_code, 404)

    def test_database_error_retains_user_text_and_hides_details(self):
        path = studio.view.BASE + '/materials/' + MATERIAL + '/draft'
        with patch.object(database, 'create_post', side_effect=RuntimeError('SECRET-TOKEN')):
            r = self.client.post(path, data={'post_text': 'Сохранить мой текст'})
        self.assertEqual(r.status_code, 503)
        self.assertIn('Сохранить мой текст', r.text)
        self.assertNotIn('SECRET-TOKEN', r.text)

    def test_ready_post_cannot_be_saved_directly(self):
        self.create(MATERIAL, 'Пост', [{'type': 'text', 'content': 'A'}])
        self.item['status'] = 'ready'
        r = self.client.post(studio.view.BASE + '/posts/' + POST + '/save', data={'post_text': 'B', 'action': 'save'})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.item['blocks'][0]['content'], 'A')

    def test_service_error_page(self):
        with patch.object(database, 'list_materials', side_effect=RuntimeError('SECRET')):
            r = self.client.get(studio.view.BASE + '/materials')
        self.assertEqual(r.status_code, 503)
        self.assertNotIn('SECRET', r.text)


class DatabaseSaveTests(unittest.TestCase):
    def test_existing_update_inserts_missing_text_and_guards_status(self):
        class Query:
            def __init__(self): self.filters = []; self.payload = None
            def update(self, data): self.payload = data; return self
            def eq(self, *args): self.filters.append(args); return self
            def execute(self): return types.SimpleNamespace(data=[self.payload])
        query = Query()
        with patch.object(database, 'get_post', return_value={'status': 'draft', 'blocks': [{'type': 'source', 'url': 'https://example.com'}]}), patch.object(database, 'db', types.SimpleNamespace(table=lambda _: query)):
            result = database.update_post(POST, 'Текст', 'ready')
        self.assertEqual(result['blocks'][0]['type'], 'text')
        self.assertIn(('status', 'draft'), query.filters)


if __name__ == '__main__':
    unittest.main()
