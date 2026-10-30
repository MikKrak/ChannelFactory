"""Сервис и HTTP-формы обращений без сети, секретов и рабочей базы."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inbox import InboxError, InboxReader, ReplyTransport, receive_batch, send_reply
from test_incoming import event, BOT, CHAT


class InboxServiceTests(unittest.TestCase):
    def test_disabled_receive_and_reply_do_not_touch_services(self):
        repo, transport = Mock(), Mock()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(InboxError): receive_batch(repo, transport, BOT)
            with self.assertRaises(InboxError): send_reply(repo, transport, 'reply')
        repo.rpc.assert_not_called(); transport.send.assert_not_called()

    def test_store_before_next_offset_and_release(self):
        repo, reader = Mock(), Mock(); reader.read_batch.return_value = [event()]
        calls = []
        def rpc(name, **params):
            calls.append((name, params))
            if name == 'acquire': return {'bot_id': BOT, 'chat_id': CHAT, 'next_offset': 10}
            if name == 'store': return 11
        repo.rpc.side_effect = rpc
        with patch.dict(os.environ, {'CF_INBOX_RECEIVE_ENABLED': '1'}):
            result = receive_batch(repo, reader, BOT)
        self.assertEqual(result, {'received': 1, 'next_offset': 11})
        self.assertEqual([x[0] for x in calls], ['acquire', 'store', 'release'])
        self.assertEqual(calls[0][1]['token'], calls[-1][1]['token'])
        reader.read_batch.assert_called_once_with(10)

    def test_store_failure_does_not_request_new_offset(self):
        repo, reader = Mock(), Mock(); reader.read_batch.return_value = [event()]
        repo.rpc.side_effect = [{'bot_id': BOT, 'chat_id': CHAT, 'next_offset': None}, RuntimeError(), None]
        with patch.dict(os.environ, {'CF_INBOX_RECEIVE_ENABLED': '1'}):
            with self.assertRaises(RuntimeError): receive_batch(repo, reader, BOT)
        reader.read_batch.assert_called_once_with(None)
        self.assertEqual(repo.rpc.call_args.args[0], 'release')

    def test_claim_failure_never_sends(self):
        for result in [None, {'id': 'wrong'}]:
            repo, transport = Mock(), Mock(); repo.rpc.return_value = result
            with patch.dict(os.environ, {'CF_INBOX_REPLY_ENABLED': '1', 'CF_INBOX_ALLOWED_REPLY_IDS': 'reply'}):
                with self.assertRaises(InboxError): send_reply(repo, transport, 'reply')
            transport.send.assert_not_called()

    def test_receipt_failure_marks_review_no_second_send(self):
        repo, transport = Mock(), Mock()
        repo.rpc.side_effect = [{'id': 'reply'}, RuntimeError('DB unavailable'), None]
        transport.send.return_value = {'chat_id': CHAT, 'topic_id': 123, 'message_id': 5, 'date': '2026-10-30T00:00:00Z'}
        with patch.dict(os.environ, {'CF_INBOX_REPLY_ENABLED': '1', 'CF_INBOX_ALLOWED_REPLY_IDS': 'reply'}):
            with self.assertRaises(InboxError): send_reply(repo, transport, 'reply')
        transport.send.assert_called_once()
        self.assertEqual([x.args[0] for x in repo.rpc.call_args_list], ['claim_reply', 'record_reply', 'review_reply'])

    @patch('incoming.requests.get')
    def test_read_uses_only_saved_offset_no_filter(self, get):
        get.return_value.status_code = 200; get.return_value.ok = True
        get.return_value.json.return_value = {'ok': True, 'result': []}
        reader = InboxReader('synthetic'); reader.read_batch(11)
        self.assertEqual(get.call_args.kwargs['params'], {'limit': 100, 'timeout': 20, 'offset': 11})
        with self.assertRaises(InboxError): reader.read_batch(-1)
        self.assertEqual(get.call_count, 1)

    @patch('incoming.TelegramReader._get', return_value={'id': BOT})
    @patch('requests.post')
    def test_transport_one_post_exact_topic_and_safe_failure(self, post, get):
        plan = {'id': 'r', 'bot_id': BOT, 'chat_id': CHAT, 'direct_messages_topic_id': 2**40, 'text': 'Ответ'}
        post.return_value.ok = True
        post.return_value.json.return_value = {'ok': True, 'result': {'message_id': 8, 'date': 1700000000, 'chat': {'id': CHAT}, 'direct_messages_topic': {'topic_id': 2**40}}}
        receipt = ReplyTransport('synthetic').send(plan)
        self.assertEqual(receipt['message_id'], 8)
        self.assertEqual(set(post.call_args.kwargs['json']), {'chat_id', 'direct_messages_topic_id', 'text'})
        self.assertEqual(post.call_count, 1)
        post.side_effect = RuntimeError('secret URL')
        with self.assertRaises(InboxError) as exc: ReplyTransport('synthetic').send(plan)
        self.assertNotIn('secret', str(exc.exception))


with patch.dict(os.environ, {'SUPABASE_URL': 'https://example.supabase.co', 'SUPABASE_KEY': 'synthetic'}):
    with patch('supabase.create_client', return_value=Mock()):
        import inbox_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


class InboxRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI(); self.app.include_router(inbox_routes.router)
        self.client = TestClient(self.app)
        self.dialog = str(uuid4()); self.reply = str(uuid4())
        self.repo = Mock()
        self.repo.dialog.return_value = {'id': self.dialog, 'state': 'new'}
        self.repo.messages.return_value = [{'id': str(uuid4()), 'text': '<script>bad()</script>', 'sent_at': '2026-10-30'}]
        self.repo.replies.return_value = []
        self.patches = [patch.object(inbox_routes, 'repository', return_value=self.repo),
                        patch.dict(os.environ, {'CF_INBOX_UI_ENABLED': '1', 'CF_INBOX_REPLY_ENABLED': '0'})]
        for p in self.patches: p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def test_disabled_page_has_no_database_read(self):
        with patch.dict(os.environ, {'CF_INBOX_UI_ENABLED': '0'}):
            response = self.client.get(inbox_routes.BASE)
        self.assertEqual(response.status_code, 409)
        self.repo.dialogs.assert_not_called()

    def test_dialog_escapes_text_and_separates_prepare_send(self):
        response = self.client.get(inbox_routes.BASE + '/' + self.dialog)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<script>bad()', response.text)
        self.assertIn('&lt;script&gt;', response.text)
        self.assertIn('Сохранить и проверить ответ', response.text)
        self.assertNotIn('Отправить читателю', response.text)

    def test_prepare_saves_exact_text_without_send(self):
        response = self.client.post(inbox_routes.BASE + '/' + self.dialog + '/prepare', data={'request_id': self.reply, 'text': 'Ответ'}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.repo.rpc.assert_called_once_with('prepare_reply', id=self.reply, dialog_id=self.dialog, text='Ответ')

    def test_disabled_send_and_confirmation_requirement(self):
        path = inbox_routes.BASE + '/replies/' + self.reply + '/send'
        self.assertEqual(self.client.post(path, data={}).status_code, 422)
        response = self.client.post(path, data={'confirmed': 'true'})
        self.assertEqual(response.status_code, 409)
        self.repo.rpc.assert_not_called()

    def test_manual_no_delivery_requires_explicit_check(self):
        path = inbox_routes.BASE + '/replies/' + self.reply + '/reconcile'
        response = self.client.post(path, data={'action': 'no_delivery', 'note': 'Сверено', 'quiesced': 'true'})
        self.assertEqual(response.status_code, 422)
        self.repo.rpc.assert_not_called()
