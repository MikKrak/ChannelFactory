"""Новая схема — только синтетические данные в прежнем одноразовом кластере."""
import concurrent.futures
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4
from test_publication_sql import sql, literal
from test_incoming import event, BOT, CHANNEL, CHAT


@unittest.skipUnless(os.environ.get('CF_TEST_POSTGRES') == '1', 'Изолированная PostgreSQL явно не включена')
class InboxSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sql('SHOW data_directory', False).stdout.strip() != '/private/tmp/cf-publication-pg-20261029':
            raise RuntimeError('Refusing non-test cluster')
        root = Path(__file__).resolve().parents[1]
        sql((root/'tests/fixtures/publication_base.sql').read_text(), False)
        sql((root/'sql/inbox.sql').read_text(), False)

    def call(self, name, *args, check=True):
        return sql('SELECT cf_inbox_' + name + '(' + ','.join(literal(v) for v in args) + ')', check=check)

    def setUp(self):
        sql('TRUNCATE cf_inbox_consumers CASCADE', False)
        self.call('configure', BOT, CHANNEL, CHAT)
        self.token = str(uuid4())
        self.call('acquire', BOT, self.token)

    def scalar(self, query):
        return sql(query).stdout.strip()

    def store(self, updates):
        return self.call('store', BOT, self.token, updates)

    def prepare(self):
        self.store([event()])
        dialog = self.scalar('SELECT id FROM cf_inbox_dialogs')
        rid = str(uuid4())
        self.call('prepare_reply', rid, dialog, 'Ответ читателю')
        return dialog, rid

    def test_batch_dedup_restart_and_cursor(self):
        self.assertEqual(self.store([event()]).stdout.strip(), '11')
        self.store([event()])
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_inbox_messages'), '1')
        self.call('release', BOT, self.token)
        token = str(uuid4())
        config = json.loads(self.call('acquire', BOT, token).stdout)
        self.assertEqual(config['next_offset'], 11)

    def test_failure_rolls_back_whole_batch_and_cursor(self):
        self.assertNotEqual(self.call('store', BOT, self.token, [event(), {'update_id': 'invalid'}], check=False).returncode, 0)
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_inbox_events'), '0')
        self.assertEqual(self.scalar('SELECT next_offset IS NULL FROM cf_inbox_consumers'), 't')

    def test_unsupported_stored_before_cursor(self):
        e = {'update_id': 12, 'future_type': {'x': 'synthetic'}}
        self.store([event(), e])
        self.assertEqual(self.scalar("SELECT state FROM cf_inbox_events WHERE update_id=12"), 'unsupported')
        self.assertEqual(self.scalar('SELECT next_offset FROM cf_inbox_consumers'), '13')

    def test_conflicting_event_and_duplicate_message(self):
        self.store([event()])
        self.store([event(11)])
        self.assertEqual(self.scalar('SELECT count(*) FROM cf_inbox_messages'), '1')
        e = event(); e['message']['text'] = 'Другой текст'
        self.assertNotEqual(self.call('store', BOT, self.token, [e], check=False).returncode, 0)

    def test_acquire_competes_and_wrong_token_rejected(self):
        self.call('release', BOT, self.token)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda t: self.call('acquire', BOT, t, check=False), [str(uuid4()), str(uuid4())]))
        self.assertEqual(sum(r.returncode == 0 for r in results), 1)
        self.assertNotEqual(self.call('store', BOT, self.token, [event()], check=False).returncode, 0)
        self.assertNotEqual(self.call('release', BOT, self.token, check=False).returncode, 0)

    def test_direct_writes_and_client_access_rejected(self):
        self.assertNotEqual(sql("UPDATE cf_inbox_consumers SET next_offset=100", check=False).returncode, 0)
        self.assertEqual(self.scalar("SELECT has_table_privilege('anon','cf_inbox_events','SELECT')"), 'f')
        self.assertEqual(self.scalar("SELECT has_function_privilege('authenticated','cf_inbox_store(bigint,uuid,jsonb)','EXECUTE')"), 'f')

    def test_reply_claim_receipt_and_double_send(self):
        dialog, rid = self.prepare(); worker = str(uuid4())
        plan = json.loads(self.call('claim_reply', rid, worker).stdout)
        self.assertEqual(plan['direct_messages_topic_id'], 2**40)
        self.assertEqual(plan['chat_id'], CHAT)
        self.assertNotIn('message_thread_id', plan)
        self.assertNotEqual(self.call('claim_reply', rid, worker, check=False).returncode, 0)
        self.assertNotEqual(self.call('record_reply', rid, worker, CHAT-1, 2**40, 20, '2026-10-30T02:00:00Z', check=False).returncode, 0)
        self.call('record_reply', rid, worker, CHAT, 2**40, 20, '2026-10-30T02:00:00Z')
        self.call('record_reply', rid, worker, CHAT, 2**40, 20, '2026-10-30T02:00:00Z')
        self.assertEqual(self.scalar('SELECT state FROM cf_inbox_replies'), 'sent')
        self.assertEqual(self.scalar('SELECT state FROM cf_inbox_dialogs'), 'new')

    def test_uncertainty_no_retry_and_manual_review(self):
        dialog, rid = self.prepare(); worker = str(uuid4())
        self.call('claim_reply', rid, worker); self.call('review_reply', rid)
        self.assertNotEqual(self.call('prepare_reply', str(uuid4()), dialog, 'Повтор', check=False).returncode, 0)
        self.assertNotEqual(self.call('reconcile_reply', rid, 'confirm', 'Проверено', False, 20, '2026-10-30T02:00:00Z', check=False).returncode, 0)
        self.call('reconcile_reply', rid, 'confirm', 'Владелец сверил диалог', True, 20, '2026-10-30T02:00:00Z')
        self.assertEqual(self.scalar('SELECT state FROM cf_inbox_replies'), 'sent')
        self.assertEqual(self.scalar('SELECT jsonb_array_length(review_log) FROM cf_inbox_replies'), '1')

    def test_prepare_idempotent_and_unicode_limit(self):
        dialog, rid = self.prepare()
        self.call('prepare_reply', rid, dialog, 'Ответ читателю')
        self.assertNotEqual(self.call('prepare_reply', rid, dialog, 'Изменено', check=False).returncode, 0)
        self.call('claim_reply', rid, str(uuid4())); self.call('review_reply', rid)
        self.call('reconcile_reply', rid, 'no_delivery', 'Отправитель остановлен, диалог пуст', True)
        self.assertNotEqual(self.call('prepare_reply', str(uuid4()), dialog, '😀'*2049, check=False).returncode, 0)
        self.call('prepare_reply', str(uuid4()), dialog, '😀'*2048)

    def test_mark_handled_cannot_hide_unseen_message(self):
        dialog, _ = self.prepare()
        mid = self.scalar('SELECT id FROM cf_inbox_messages')
        self.call('mark', dialog, 'handled', mid)
        e = event(11); e['message']['message_id'] = 8; e['message']['date'] += 1
        self.store([e])
        self.assertEqual(self.scalar('SELECT state FROM cf_inbox_dialogs'), 'new')
        self.assertNotEqual(self.call('mark', dialog, 'handled', mid, check=False).returncode, 0)

    def test_recover_requires_stopped_consumer_and_preserves_cursor(self):
        self.store([event()])
        self.assertNotEqual(self.call('recover_consumer', BOT, False, 'Проверено', check=False).returncode, 0)
        self.call('recover_consumer', BOT, True, 'Старый процесс остановлен владельцем')
        self.assertEqual(self.scalar('SELECT next_offset FROM cf_inbox_consumers'), '11')
        self.assertEqual(self.scalar('SELECT jsonb_array_length(recovery_log) FROM cf_inbox_consumers'), '1')
        self.assertNotEqual(self.call('store', BOT, self.token, [event(11)], check=False).returncode, 0)

    def test_cancel_prepared_cannot_cancel_started_send(self):
        dialog,rid=self.prepare()
        self.call('cancel_prepared',rid)
        newer=str(uuid4()); self.call('prepare_reply',newer,dialog,'Исправленный ответ')
        self.call('claim_reply',newer,str(uuid4()))
        self.assertNotEqual(self.call('cancel_prepared',newer,check=False).returncode,0)

    def test_python_services_to_real_sql_complete_cycle(self):
        from inbox import InboxRepository, receive_batch, send_reply
        from types import SimpleNamespace
        from unittest.mock import patch
        # Освобождаем захват setUp: сервис должен получить собственный token.
        self.call('release', BOT, self.token)
        class Query:
            def __init__(self, table): self.table=table;self.where=[];self.sort=[];self.limit_value=''
            def select(self, fields): self.fields=fields;return self
            def eq(self, field, value): self.where.append(field+'='+literal(value));return self
            def order(self, field, desc=False): self.sort.append(field+(' DESC' if desc else ''));return self
            def range(self, start, end): self.limit_value=' LIMIT '+str(end-start+1)+' OFFSET '+str(start);return self
            def limit(self, count): self.limit_value=' LIMIT '+str(count);return self
            def execute(self):
                q='SELECT coalesce(jsonb_agg(to_jsonb(x)),\'[]\') FROM (SELECT '+self.fields+' FROM '+self.table
                if self.where: q+=' WHERE '+' AND '.join(self.where)
                if self.sort: q+=' ORDER BY '+','.join(self.sort)
                return SimpleNamespace(data=json.loads(sql(q+self.limit_value+') x').stdout))
        class Client:
            def table(self, name): return Query(name)
            def rpc(self, name, params):
                q='SELECT to_jsonb('+name+'('+','.join(k+'=>'+literal(v) for k,v in params.items())+'))'
                return SimpleNamespace(execute=lambda:SimpleNamespace(data=json.loads(sql(q).stdout)))
        repo=InboxRepository(Client())
        class Reader:
            def preflight(self, bot, chat): assert (bot,chat)==(BOT,CHAT)
            def read_batch(self, offset): assert offset is None;return [event()]
        with patch.dict(os.environ, {'CF_INBOX_RECEIVE_ENABLED':'1'}):
            self.assertEqual(receive_batch(repo,Reader(),BOT)['next_offset'],11)
        dialog=repo.dialogs()[0]['id']; rid=str(uuid4())
        repo.rpc('prepare_reply',id=rid,dialog_id=dialog,text='Проверочный ответ')
        class Transport:
            def send(self, plan):
                assert plan['direct_messages_topic_id']==2**40
                return {'chat_id':CHAT,'topic_id':2**40,'message_id':20,'date':'2026-10-30T02:00:00Z'}
        with patch.dict(os.environ, {'CF_INBOX_REPLY_ENABLED':'1','CF_INBOX_ALLOWED_REPLY_IDS':rid}):
            send_reply(repo,Transport(),rid)
            self.assertRaises(Exception,send_reply,repo,Transport(),rid)
        self.assertEqual(repo.reply(rid)['state'],'sent')
        self.assertEqual(len(repo.messages(dialog)),1)
