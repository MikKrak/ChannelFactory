"""Прикладная логика обращений: БД, один пакет входящих и ручной ответ.

Импорт не запускает polling и ничего не отправляет. Рабочее включение отдельно
закрыто параметрами окружения. Не читает временный журнал опыта CF-02C-007.
"""
import os
from uuid import uuid4

from incoming import IncomingError, TelegramReader


class InboxError(Exception):
    """Безопасное сообщение для владельца, без секретов и личных данных."""


def require_enabled(name):
    if os.environ.get(name) != '1':
        raise InboxError('Эта возможность ещё не подключена владельцем.')


class InboxRepository:
    def __init__(self, client):
        self.db = client

    def rpc(self, name, **params):
        return self.db.rpc('cf_inbox_' + name, {'p_' + k: v for k, v in params.items()}).execute().data

    def dialogs(self, offset=0):
        return self.db.table('cf_inbox_dialogs').select('id,state,updated_at').order('updated_at', desc=True).order('id').range(offset, offset + 19).execute().data or []

    def dialog(self, id):
        rows = self.db.table('cf_inbox_dialogs').select('id,state,updated_at').eq('id', str(id)).limit(1).execute().data
        return rows[0] if rows else None

    def messages(self, id, offset=0):
        return self.db.table('cf_inbox_messages').select('id,text,sent_at,message_id').eq('dialog_id', str(id)).order('sent_at', desc=True).order('id').range(offset, offset + 19).execute().data or []

    def replies(self, id):
        return self.db.table('cf_inbox_replies').select('id,dialog_id,text,state,message_id,sent_at,created_at,review_log').eq('dialog_id', str(id)).order('created_at', desc=True).limit(20).execute().data or []

    def reply(self, id):
        rows = self.db.table('cf_inbox_replies').select('id,dialog_id,text,state').eq('id', str(id)).limit(1).execute().data
        return rows[0] if rows else None


class InboxReader(TelegramReader):
    def read_batch(self, offset):
        params = {'limit': 100, 'timeout': 20}
        if offset is not None:
            if type(offset) is not int or offset < 0:
                raise InboxError('Некорректный курсор. Получение остановлено.')
            params['offset'] = offset
        return self._get('getUpdates', params)


def receive_batch(repo, reader, bot_id):
    """Совместимость с прежним явным запуском одного пакета."""
    return receive_loop(repo, reader, bot_id, max_batches=1)


def receive_loop(repo, reader, bot_id, *, max_batches=None, stopped=lambda: False,
                 progress=lambda **values: None):
    """Один захват на весь цикл; каждый следующий offset только из ответа БД.

    SIGINT/SIGTERM вызывающий код превращает в флаг остановки. Уже полученный
    пакет сохраняется до освобождения захвата. Ошибка останавливает цикл без
    сетевых повторов; аварийный захват автоматически не перехватывается.
    """
    require_enabled('CF_INBOX_RECEIVE_ENABLED')
    if max_batches is not None and (type(max_batches) is not int or max_batches < 1):
        raise InboxError('Некорректное число пакетов.')
    token = str(uuid4())
    config = repo.rpc('acquire', bot_id=bot_id, token=token)
    try:
        if not isinstance(config, dict) or config.get('bot_id') != bot_id:
            raise InboxError('Не подтверждён захват получателя.')
        offset = config['next_offset']
        if offset is not None and (type(offset) is not int or offset < 0):
            raise InboxError('Некорректный сохранённый курсор.')
        reader.preflight(bot_id, config['chat_id'])
        batches = 0
        total = 0
        while not stopped() and (max_batches is None or batches < max_batches):
            progress(state='running', phase='waiting', received=total)
            updates = reader.read_batch(offset)
            progress(state='running', phase='saving', received=total)
            saved = repo.rpc('store', bot_id=bot_id, token=token, updates=updates)
            expected = max([u['update_id'] + 1 for u in updates] + [offset or 0])
            if ((saved is None and expected != 0)
                    or (saved is not None and (type(saved) is not int or saved < expected))):
                raise InboxError('Не подтверждён сохранённый курсор. Получение остановлено.')
            offset = saved
            total += len(updates)
            batches += 1
        return {'received': total, 'next_offset': offset}
    finally:
        repo.rpc('release', bot_id=bot_id, token=token)


def send_reply(repo, transport, reply_id):
    """Начало фиксируется до сети. Потерянный ответ/receipt — только сверка."""
    require_enabled('CF_INBOX_REPLY_ENABLED')
    allowed = {x.strip() for x in os.environ.get('CF_INBOX_ALLOWED_REPLY_IDS', '').split(',') if x.strip()}
    if str(reply_id) not in allowed:
        raise InboxError('Этот ответ ещё не разрешён для отправки.')
    token = str(uuid4())
    # Неизвестный результат claim не разрешает сетевую отправку.
    plan = repo.rpc('claim_reply', id=str(reply_id), token=token)
    if not isinstance(plan, dict) or str(plan.get('id')) != str(reply_id):
        raise InboxError('Не подтверждено начало отправки. Проверь историю ответа.')
    try:
        receipt = transport.send(plan)
        repo.rpc('record_reply', id=str(reply_id), token=token,
                 chat_id=receipt['chat_id'], topic_id=receipt['topic_id'],
                 message_id=receipt['message_id'], date=receipt['date'])
    except Exception:
        try:
            repo.rpc('review_reply', id=str(reply_id))
        except Exception:
            pass
        raise InboxError('Результат требует проверки. Не отправляй ответ заново; сверь переписку.') from None


class ReplyTransport:
    """Единственный sendMessage, адрес только из сохранённого диалога."""
    def __init__(self, token):
        self.token = token

    def send(self, plan):
        import requests
        from datetime import datetime, timezone
        try:
            # Проверка выбранного бота до POST также не использует getUpdates.
            bot = TelegramReader(self.token)._get('getMe')
            if bot.get('id') != plan['bot_id']:
                raise ValueError()
            response = requests.post('https://api.telegram.org/bot' + self.token + '/sendMessage',
                                     json={k: plan[k] for k in ('chat_id', 'direct_messages_topic_id', 'text')},
                                     timeout=(10, 30), allow_redirects=False)
            data = response.json()
            if not response.ok or data.get('ok') is not True:
                raise ValueError()
            msg = data['result']
            if (msg['chat']['id'] != plan['chat_id']
                    or msg.get('direct_messages_topic', {}).get('topic_id') != plan['direct_messages_topic_id']
                    or type(msg.get('message_id')) is not int or msg['message_id'] <= 0
                    or type(msg.get('date')) is not int):
                raise ValueError()
            return {'chat_id': msg['chat']['id'], 'topic_id': plan['direct_messages_topic_id'],
                    'message_id': msg['message_id'],
                    'date': datetime.fromtimestamp(msg['date'], timezone.utc).isoformat()}
        except Exception:
            raise InboxError('Подтверждение доставки не получено.') from None
