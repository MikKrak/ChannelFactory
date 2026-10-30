"""Регулярный получатель: синтетический транспорт и состояния, без рабочей сети."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inbox import InboxError, receive_loop
from inbox_state import read_state, write_state
from incoming import private_directory
from test_incoming import event, BOT, CHAT


class MemoryRepo:
    def __init__(self):
        self.token = None; self.offset = None; self.events = {}; self.fail_store = False
        self.names = []

    def rpc(self, name, **p):
        self.names.append(name)
        if name == 'acquire':
            if self.token: raise InboxError('Consumer busy')
            self.token = p['token']
            return {'bot_id': BOT, 'chat_id': CHAT, 'next_offset': self.offset}
        if self.token != p['token']: raise InboxError('Wrong worker')
        if name == 'release': self.token = None; return
        if name == 'store':
            if self.fail_store: raise OSError('Synthetic failure')
            records = copy.deepcopy(self.events)
            for u in p['updates']:
                if u['update_id'] in records and records[u['update_id']] != u: raise ValueError()
                records[u['update_id']] = u
            self.events = records
            if p['updates']: self.offset = max(u['update_id'] for u in p['updates']) + 1
            return self.offset
        raise AssertionError(name)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        p = patch.dict(os.environ, {'CF_INBOX_RECEIVE_ENABLED': '1'})
        p.start(); self.addCleanup(p.stop)

    def test_loop_one_owner_and_save_before_each_new_offset(self):
        repo = MemoryRepo(); reader = Mock()
        reader.read_batch.side_effect = [[event()], [{'update_id': 11, 'new_kind': {}}], []]
        result = receive_loop(repo, reader, BOT, max_batches=3)
        self.assertEqual([x.args[0] for x in reader.read_batch.call_args_list], [None, 11, 12])
        self.assertEqual(repo.names, ['acquire', 'store', 'store', 'store', 'release'])
        self.assertEqual(result, {'received': 2, 'next_offset': 12})
        self.assertIsNone(repo.token)

    def test_restart_reuses_durable_offset_no_duplicate(self):
        repo = MemoryRepo(); reader = Mock(); reader.read_batch.return_value = [event()]
        receive_loop(repo, reader, BOT, max_batches=1)
        receive_loop(repo, reader, BOT, max_batches=1)
        self.assertEqual(reader.read_batch.call_args.args, (11,))
        self.assertEqual(len(repo.events), 1)

    def test_save_failure_keeps_old_offset_and_stops(self):
        repo = MemoryRepo(); repo.offset = 10; repo.fail_store = True
        reader = Mock(); reader.read_batch.return_value = [event()]
        with self.assertRaises(OSError): receive_loop(repo, reader, BOT, max_batches=3)
        reader.read_batch.assert_called_once_with(10)
        self.assertEqual(repo.offset, 10)
        self.assertIsNone(repo.token)
        repo.fail_store = False
        receive_loop(repo, reader, BOT, max_batches=1)
        self.assertEqual(len(repo.events), 1)

    def test_stop_during_poll_saves_returned_packet_before_release(self):
        repo = MemoryRepo(); reader = Mock(); stopped = [False]
        def read(offset): stopped[0] = True; return [event()]
        reader.read_batch.side_effect = read
        receive_loop(repo, reader, BOT, stopped=lambda: stopped[0])
        self.assertEqual(repo.offset, 11)
        self.assertIsNone(repo.token)

    def test_second_consumer_does_not_steal_or_poll(self):
        repo = MemoryRepo(); repo.token = 'old-owner'; reader = Mock()
        with self.assertRaises(InboxError): receive_loop(repo, reader, BOT)
        reader.read_batch.assert_not_called()
        self.assertEqual(repo.token, 'old-owner')

    def test_network_conflict_releases_without_store_or_retry(self):
        repo = MemoryRepo(); reader = Mock(); reader.read_batch.side_effect = InboxError('409')
        with self.assertRaises(InboxError): receive_loop(repo, reader, BOT)
        self.assertEqual(repo.names, ['acquire', 'release'])
        self.assertIsNone(repo.offset)
        reader.read_batch.assert_called_once()

    def test_unknown_store_result_prevents_next_request(self):
        repo = Mock(); reader = Mock()
        repo.rpc.side_effect = [{'bot_id': BOT, 'chat_id': CHAT, 'next_offset': 10}, None, None]
        reader.read_batch.return_value = [event()]
        with self.assertRaises(InboxError): receive_loop(repo, reader, BOT, max_batches=3)
        reader.read_batch.assert_called_once_with(10)

    def test_release_failure_is_not_reported_as_success(self):
        repo = Mock(); reader = Mock(); reader.read_batch.return_value = []
        repo.rpc.side_effect = [{'bot_id': BOT, 'chat_id': CHAT, 'next_offset': 10}, 10, OSError()]
        with self.assertRaises(OSError): receive_loop(repo, reader, BOT, max_batches=1)

    def test_state_has_no_content_and_detects_missing_process(self):
        with tempfile.TemporaryDirectory() as root:
            write_state(root, state='running', phase='waiting', received=2, text='PRIVATE', token='SECRET')
            p = Path(root) / 'state.json'
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('PRIVATE', p.read_text())
            self.assertNotIn('SECRET', p.read_text())
            self.assertEqual(read_state(BOT, root)['state'], 'running')
            with patch('inbox_state.os.kill', side_effect=ProcessLookupError()):
                self.assertEqual(read_state(BOT, root)['state'], 'error')
            write_state(root, state='stopped')
            self.assertEqual(read_state(BOT, root)['state'], 'stopped')

    def test_stale_or_public_state_never_shows_running(self):
        with tempfile.TemporaryDirectory() as root:
            with patch('inbox_state.time.time', return_value=time.time()-100):
                write_state(root, state='running')
            self.assertEqual(read_state(BOT, root)['state'], 'unknown')
            os.chmod(Path(root)/'state.json', 0o644)
            self.assertEqual(read_state(BOT, root)['state'], 'unknown')

    def test_second_local_lock_does_not_overwrite_running_state(self):
        with tempfile.TemporaryDirectory() as root:
            with private_directory(root):
                write_state(root, state='running')
                before = (Path(root)/'state.json').read_text()
                with self.assertRaises(Exception):
                    with private_directory(root): write_state(root, state='error')
                self.assertEqual((Path(root)/'state.json').read_text(), before)
