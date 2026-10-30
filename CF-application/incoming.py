"""Приём одного пакета Telegram для CF-02C-007, без отправки и подтверждения.

Не подключён к FastAPI. Сохраняет пакет в приватную временную SQLite вне Git.
Никогда не задаёт offset/allowed_updates: не подтверждает и не меняет фильтр.
Постоянное хранение и продвижение курсора относятся к следующему этапу.
"""
import fcntl
import json
import os
from pathlib import Path
import sqlite3
from contextlib import contextmanager

import requests


class IncomingError(Exception):
    """Безопасное сообщение без токена, URL и персональных данных."""


def integer(value, positive=False):
    return type(value) is int and (not positive or value > 0)


def normalize(update, bot_id, channel_id, dm_chat_id):
    """Маршрут DM берём только из проверенного чата и direct_messages_topic."""
    if not isinstance(update, dict) or not integer(update.get('update_id')):
        raise IncomingError('Некорректный идентификатор события.')
    base = {'bot_id': bot_id, 'update_id': update['update_id'], 'kind': 'unsupported'}
    message = update.get('message')
    if not isinstance(message, dict):
        return base
    chat = message.get('chat') or {}
    if chat.get('type') == 'private':
        return base | {'kind': 'bot_private'}
    if chat.get('id') != dm_chat_id or chat.get('is_direct_messages') is not True:
        return base
    topic = message.get('direct_messages_topic') or {}
    sender = message.get('from') or {}
    user = topic.get('user') or {}
    if not (integer(topic.get('topic_id'), True)
            and integer(message.get('message_id'), True)
            and integer(message.get('date'))
            and isinstance(message.get('text'), str)
            and message['text'].strip()
            and integer(user.get('id'), True)
            and user.get('is_bot') is False
            and sender.get('id') == user['id']
            and sender.get('is_bot') is False):
        return base
    return base | {
        'kind': 'channel_dm_text', 'channel_id': channel_id,
        'chat_id': dm_chat_id, 'topic_id': topic['topic_id'],
        'message_id': message['message_id'], 'date': message['date'],
        'reader_id': user['id'], 'text': message['text'],
        'reply_route': {'chat_id': dm_chat_id,
                        'direct_messages_topic_id': topic['topic_id']},
    }


@contextmanager
def private_directory(path):
    """Один локальный потребитель; flock освобождается и после аварии процесса."""
    path = Path(path)
    if path.is_symlink():
        raise IncomingError('Каталог журнала не должен быть ссылкой.')
    path.mkdir(mode=0o700, parents=False, exist_ok=True)
    stat = path.stat()
    if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise IncomingError('Нужен приватный каталог владельца с правами 700.')
    fd = os.open(path / 'receiver.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise IncomingError('Другой локальный приёмник уже работает.') from None
        yield path
    finally:
        os.close(fd)


class Journal:
    """Сохраняет весь полученный пакет атомарно, включая неизвестные события."""
    def __init__(self, directory, bot_id):
        self.bot_id = bot_id
        path = Path(directory) / 'events.sqlite3'
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
            raise IncomingError('Небезопасные права файла журнала.')
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (bot_id INTEGER NOT NULL, update_id INTEGER NOT NULL, raw TEXT NOT NULL, normalized TEXT NOT NULL, PRIMARY KEY(bot_id,update_id))')

    def save(self, updates, channel_id, dm_chat_id):
        if not isinstance(updates, list):
            raise IncomingError('Ожидался пакет событий.')
        result = []
        with self.db:
            for update in updates:
                item = normalize(update, self.bot_id, channel_id, dm_chat_id)
                raw = json.dumps(update, ensure_ascii=False, sort_keys=True)
                old = self.db.execute('SELECT raw FROM events WHERE bot_id=? AND update_id=?', (self.bot_id, item['update_id'])).fetchone()
                if old and old[0] != raw:
                    raise IncomingError('Содержимое повторного события отличается.')
                self.db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?)',
                                (self.bot_id, item['update_id'], raw, json.dumps(item, ensure_ascii=False)))
                result.append(item)
        return result

    def close(self):
        self.db.close()


class TelegramReader:
    """Только getMe/getWebhookInfo/getChat и один getUpdates, без повторов."""
    def __init__(self, token):
        self.token = token

    def _get(self, method, params=None):
        try:
            response = requests.get('https://api.telegram.org/bot' + self.token + '/' + method,
                                    params=params, timeout=(10, 35), allow_redirects=False)
            data = response.json()
            if response.status_code == 409:
                raise IncomingError('Конфликт потребителей Telegram; опыт остановлен.')
            if not response.ok or data.get('ok') is not True:
                raise IncomingError('Telegram отклонил запрос; повтор не выполнен.')
            return data['result']
        except IncomingError:
            raise
        except Exception:
            raise IncomingError('Не удалось получить ответ Telegram; повтор не выполнен.') from None

    def preflight(self, expected_bot_id, dm_chat_id):
        bot = self._get('getMe')
        if bot.get('id') != expected_bot_id or bot.get('is_bot') is not True:
            raise IncomingError('Не тот бот.')
        if self._get('getWebhookInfo').get('url'):
            raise IncomingError('Webhook настроен; polling запрещён.')
        chat = self._get('getChat', {'chat_id': dm_chat_id})
        if chat.get('id') != dm_chat_id or chat.get('is_direct_messages') is not True:
            raise IncomingError('Служебный чат канала не подтверждён.')

    def read_once(self):
        return self._get('getUpdates', {'limit': 100, 'timeout': 0})


def capture_once(reader, directory, bot_id, channel_id, dm_chat_id):
    """Только после согласования владельцем; возвращает сводку без содержимого."""
    with private_directory(directory) as path:
        journal = Journal(path, bot_id)
        try:
            reader.preflight(bot_id, dm_chat_id)
            result = journal.save(reader.read_once(), channel_id, dm_chat_id)
            return {'received': len(result),
                    'channel_dm_text': sum(x['kind'] == 'channel_dm_text' for x in result),
                    'offset_sent': False, 'filter_changed': False}
        finally:
            journal.close()
