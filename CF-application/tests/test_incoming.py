"""Синтетические проверки приёмника: без .env, сети и рабочей базы."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from incoming import (IncomingError, Journal, TelegramReader, capture_once,
                      normalize, private_directory)

BOT, CHANNEL, CHAT = 123, -100123, -200123


def event(uid=10):
    return {'update_id': uid, 'message': {
        'message_id': 7, 'date': 1700000000, 'text': 'Тестовое обращение',
        'chat': {'id': CHAT, 'type': 'supergroup', 'is_direct_messages': True},
        'from': {'id': 456, 'is_bot': False},
        'message_thread_id': 999,
        'direct_messages_topic': {'topic_id': 2**40,
                                  'user': {'id': 456, 'is_bot': False}},
    }}


class IncomingTests(unittest.TestCase):
    def test_dm_route_uses_topic_not_forum(self):
        result = normalize(event(), BOT, CHANNEL, CHAT)
        self.assertEqual(result['kind'], 'channel_dm_text')
        self.assertEqual(result['reply_route'], {'chat_id': CHAT, 'direct_messages_topic_id': 2**40})
        self.assertNotIn('message_thread_id', result['reply_route'])

    def test_private_bot_and_public_comment_are_not_dm(self):
        e = event(); e['message']['chat'] = {'id': 456, 'type': 'private'}
        self.assertEqual(normalize(e, BOT, CHANNEL, CHAT)['kind'], 'bot_private')
        e['message']['chat'] = {'id': -100456, 'type': 'supergroup'}
        self.assertEqual(normalize(e, BOT, CHANNEL, CHAT)['kind'], 'unsupported')

    def test_unknown_and_edited_events(self):
        for e in [{'update_id': 1, 'new_type': {}}, {'update_id': 2, 'edited_message': event()['message']}]:
            self.assertEqual(normalize(e, BOT, CHANNEL, CHAT)['kind'], 'unsupported')

    def test_missing_topic_and_bot_sender_fail_closed(self):
        for key in ['direct_messages_topic', 'text', 'message_id']:
            e = event(); del e['message'][key]
            self.assertEqual(normalize(e, BOT, CHANNEL, CHAT)['kind'], 'unsupported')
        e = event(); e['message']['from']['is_bot'] = True
        self.assertEqual(normalize(e, BOT, CHANNEL, CHAT)['kind'], 'unsupported')

    def test_transaction_duplicates_restart_and_conflict(self):
        with tempfile.TemporaryDirectory() as root:
            with private_directory(Path(root) / 'private') as path:
                journal = Journal(path, BOT)
                journal.save([event(), event()], CHANNEL, CHAT)
                journal.close()
                journal = Journal(path, BOT)
                journal.save([event()], CHANNEL, CHAT)
                self.assertEqual(journal.db.execute('SELECT count(*) FROM events').fetchone()[0], 1)
                changed = event(); changed['message']['text'] = 'Изменено'
                with self.assertRaises(IncomingError):
                    journal.save([event(11), changed], CHANNEL, CHAT)
                self.assertEqual(journal.db.execute('SELECT count(*) FROM events').fetchone()[0], 1)
                journal.close()
                self.assertEqual((path / 'events.sqlite3').stat().st_mode & 0o777, 0o600)

    def test_unknown_preserved_raw(self):
        with tempfile.TemporaryDirectory() as root:
            journal = Journal(root, BOT)
            e = {'update_id': 1, 'future_kind': {'x': 1}}
            journal.save([e], CHANNEL, CHAT)
            self.assertEqual(json.loads(journal.db.execute('SELECT raw FROM events').fetchone()[0]), e)
            journal.close()

    def test_second_local_consumer_rejected_and_released(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'private'
            with private_directory(path):
                with self.assertRaises(IncomingError):
                    with private_directory(path):
                        pass
            with private_directory(path):
                pass

    def test_insecure_directory_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as root:
            os.chmod(root, 0o755)
            reader = Mock()
            with self.assertRaises(IncomingError):
                capture_once(reader, root, BOT, CHANNEL, CHAT)
            reader.read_once.assert_not_called()

    @patch('incoming.requests.get')
    def test_read_does_not_ack_or_change_filter(self, get):
        response = get.return_value
        response.status_code = 200; response.ok = True
        response.json.return_value = {'ok': True, 'result': [event()]}
        self.assertEqual(TelegramReader('synthetic').read_once(), [event()])
        self.assertEqual(get.call_args.kwargs['params'], {'limit': 100, 'timeout': 0})
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertEqual(get.call_count, 1)

    @patch('incoming.requests.get')
    def test_telegram_conflict_and_error_hide_token(self, get):
        response = get.return_value; response.status_code = 409
        response.json.return_value = {'ok': False}
        with self.assertRaises(IncomingError):
            TelegramReader('synthetic').read_once()
        get.side_effect = RuntimeError('secret URL')
        with self.assertRaises(IncomingError) as error:
            TelegramReader('synthetic').read_once()
        self.assertNotIn('secret', str(error.exception))

    def test_webhook_prevents_read(self):
        reader = TelegramReader('synthetic')
        reader._get = Mock(side_effect=[{'id': BOT, 'is_bot': True}, {'url': 'https://example.invalid'}])
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(IncomingError):
                capture_once(reader, root, BOT, CHANNEL, CHAT)
        self.assertEqual(reader._get.call_count, 2)

    def test_disk_failure_no_further_request_or_ack(self):
        reader = Mock(); reader.read_once.return_value = [event()]
        with tempfile.TemporaryDirectory() as root:
            with patch.object(Journal, 'save', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    capture_once(reader, root, BOT, CHANNEL, CHAT)
        reader.read_once.assert_called_once_with()
        self.assertEqual(reader.method_calls, [unittest.mock.call.preflight(BOT, CHAT), unittest.mock.call.read_once()])


if __name__ == '__main__':
    unittest.main()
