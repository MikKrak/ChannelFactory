"""Проверки отправителя на заменяемом транспорте, без сети и рабочей базы."""
import copy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publication import build_plan, chunks, publish, PublicationError, DeliveryUncertain, DeliveryRejected
from telegram import TelegramTransport, publication_enabled


class MemoryRepo:
    def __init__(self, blocks=None):
        self.item = {'id': 'post', 'status': 'ready', 'revision': 2, 'blocks': blocks or [{'type': 'text', 'content': 'Hello'}]}
        self.attempt = None; self.events = []; self.fail = None
    def post(self, id): return copy.deepcopy(self.item)
    def latest(self, id): return self.attempt
    def begin(self, aid, worker, *args):
        self.attempt = {'id': aid, 'state': 'sending', 'post_revision': 2}
        self.plan = args[-2]; self.events.append('begin')
        if self.fail == 'begin': raise RuntimeError()
    def claim(self, aid, worker, n):
        self.events.append('claim'+str(n))
        if self.fail == 'claim': raise RuntimeError()
        return self.plan[n-1]
    def record(self, aid, worker, n, receipt):
        self.events.append('record'+str(n))
        if self.fail == 'record': raise RuntimeError()
    def review(self, *args): self.attempt['state'] = 'needs_review'; self.events.append('review')
    def finish(self, aid):
        if self.fail == 'finish': raise RuntimeError()
        self.attempt['state'] = 'succeeded';self.item['status'] = 'published'
        self.events.append('finish')


class FakeTransport:
    def __init__(self, repo): self.repo = repo; self.sent = 0; self.fail_at = None
    def ensure_enabled(self, id): pass
    def prepare(self, image): return None, None
    def target(self): return 123, -100
    def send(self, part, raw, chat):
        self.sent += 1;self.repo.events.append('send'+str(self.sent))
        if self.sent == self.fail_at: raise DeliveryUncertain()
        return {'chat_id': chat, 'message_id': self.sent, 'date': '2026-10-29T00:00:00+00:00'}


class PublicationTests(unittest.TestCase):
    def test_unicode_splitting_and_caption(self):
        txt = '😀'*3000
        result = chunks(txt,4096)
        self.assertEqual(''.join(result), txt)
        self.assertTrue(all(len(s.encode('utf-16-le'))//2 <= 4096 for s in result))
        media={'url':'https://example.com/a.png','sha256':'a'*64,'mime':'image/png'}
        plan=build_plan([{'type':'image','url':media['url']},{'type':'text','content':'a'*1025}],media)
        self.assertEqual([p['method'] for p in plan],['sendPhoto','sendMessage'])
        self.assertRaises(PublicationError,build_plan,[{'type':'source','url':'https://example.com'}])

    def test_success_order_and_repeat(self):
        repo=MemoryRepo(); transport=FakeTransport(repo)
        publish(repo,transport,'post',2)
        self.assertEqual(repo.events,['begin','claim1','send1','record1','finish'])
        self.assertRaises(PublicationError,publish,repo,transport,'post',2)
        self.assertEqual(transport.sent,1)

    def test_begin_and_claim_unknown_do_not_send(self):
        for failure in ['begin','claim']:
            with self.subTest(failure=failure):
                repo=MemoryRepo();repo.fail=failure;transport=FakeTransport(repo)
                self.assertRaises(PublicationError,publish,repo,transport,'post',2)
                self.assertEqual(transport.sent,0)
                self.assertEqual(repo.attempt['state'],'needs_review')

    def test_partial_delivery_stops_and_restart_does_not_resume(self):
        repo=MemoryRepo([{'type':'text','content':'x'*9000}]);transport=FakeTransport(repo);transport.fail_at=2
        self.assertRaises(PublicationError,publish,repo,transport,'post',2)
        self.assertEqual(transport.sent,2)
        self.assertIn('record1',repo.events)
        self.assertNotIn('claim3',repo.events)
        self.assertRaises(PublicationError,publish,repo,FakeTransport(repo),'post',2)

    def test_database_failure_after_delivery_does_not_repeat(self):
        for failure in ['record','finish']:
            repo=MemoryRepo();repo.fail=failure;transport=FakeTransport(repo)
            self.assertRaises(PublicationError,publish,repo,transport,'post',2)
            self.assertEqual(transport.sent,1)
            self.assertEqual(repo.attempt['state'],'needs_review')

    def test_draft_and_stale_version(self):
        repo=MemoryRepo();transport=FakeTransport(repo)
        self.assertRaises(PublicationError,publish,repo,transport,'post',1)
        repo.item['status']='draft'
        self.assertRaises(PublicationError,publish,repo,transport,'post',2)
        self.assertEqual(transport.sent,0)

    def test_disabled_by_default_and_allowlist(self):
        with patch.dict('os.environ',{},clear=True):
            self.assertFalse(publication_enabled('post'))
        with patch.dict('os.environ',{'CF_PUBLICATION_ENABLED':'1','CF_PUBLICATION_ALLOWED_POST_IDS':'other'}):
            self.assertFalse(publication_enabled('post'))
        with patch.dict('os.environ',{'CF_PUBLICATION_ENABLED':'1','CF_PUBLICATION_ALLOWED_POST_IDS':'post'}):
            self.assertTrue(publication_enabled('post'))

    def test_transport_normalizes_receipt_and_redacts_error(self):
        tr=TelegramTransport();tr.token='TEST_SECRET'
        response=types.SimpleNamespace(json=lambda:{'ok':True,'result':{'chat':{'id':-100},'message_id':23,'date':100000}})
        part={'method':'sendMessage','payload':{'text':'abc'}}
        with patch('requests.post',return_value=response) as request:
            self.assertEqual(tr.send(part,None,-100)['message_id'],23)
            self.assertFalse(request.call_args.kwargs['allow_redirects'])
            self.assertEqual(request.call_count,1)
        with patch('requests.post',side_effect=RuntimeError('https://secret/TEST_SECRET')):
            with self.assertRaises(DeliveryUncertain) as ctx:tr.send(part,None,-100)
            self.assertNotIn('TEST_SECRET',str(ctx.exception))



class LegacyRouteTests(unittest.TestCase):
    def setUp(self):
        # test_editorial загружает реальный database с фиктивным соединением.
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import publication_routes
        self.routes = publication_routes
        app=FastAPI();app.include_router(publication_routes.router)
        self.client=TestClient(app)
        self.id='11111111-1111-4111-8111-111111111111'

    def test_both_routes_call_same_service(self):
        for path in ['/post/'+self.id+'/publish-now', '/studio/cccp/posts/'+self.id+'/publish-now']:
            with patch.object(self.routes,'publish',return_value='attempt') as service:
                r=self.client.post(path,data={'revision':'2','confirmed':'true'},follow_redirects=False)
                self.assertEqual(r.status_code,303)
                service.assert_called_once()
                self.assertEqual(service.call_args.args[2:],(self.id,2))

    def test_old_form_without_revision_cannot_send(self):
        with patch.object(self.routes,'publish') as service:
            self.assertEqual(self.client.post('/post/'+self.id+'/publish-now',data={}).status_code,422)
            service.assert_not_called()

    def test_disabled_route_cannot_access_database_or_send(self):
        with patch.dict('os.environ',{},clear=True), patch.object(self.routes,'repository') as repo, patch('requests.post') as network:
            r=self.client.post('/post/'+self.id+'/publish-now',data={'revision':'2','confirmed':'true'})
            self.assertEqual(r.status_code,409)
            repo.return_value.post.assert_not_called()
            network.assert_not_called()

if __name__=='__main__': unittest.main()
