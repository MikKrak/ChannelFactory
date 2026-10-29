"""publication.py — план публикации и безопасная последовательность отправки.

Не возобновляет попытки после сбоя. Репозиторий и транспорт подставляются
в тестах; все гарантии конкуренции дополнительно обеспечиваются SQL RPC.
"""
from uuid import uuid4


class PublicationError(Exception):
    """Безопасное сообщение пользователю, без токенов и HTTP-адресов API."""


class DeliveryUncertain(PublicationError):
    pass


class DeliveryRejected(PublicationError):
    pass


def chunks(text, limit):
    """Резать по UTF-16 units, не разрывая Unicode-кодовую точку."""
    result, part, size = [], [], 0
    for char in text:
        width = 2 if ord(char) > 0xffff else 1
        if size + width > limit:
            result.append(''.join(part)); part, size = [], 0
        part.append(char); size += width
    if part:
        result.append(''.join(part))
    return result


def image_url(blocks):
    """Сохранить прежнее правило: последнее изображение в посте."""
    value = None
    for block in blocks:
        if block.get('type') == 'image':
            value = block.get('url') or None
    return value


def build_plan(blocks, media=None):
    """Канонический plain-text план; SQL независимо проверяет его по снимку."""
    if not isinstance(blocks, list) or not all(isinstance(b, dict) for b in blocks):
        raise PublicationError('Неверная структура блоков поста.')
    text_parts, has_text = [], False
    for block in blocks:
        kind = block.get('type')
        if kind == 'text':
            value = block.get('content') or ''
            if not isinstance(value, str):
                raise PublicationError('Текстовый блок должен содержать строку.')
            has_text |= bool(value.strip(' \t\r\n'))
            if value: text_parts.append(value)
        elif kind == 'source':
            value = block.get('url') or ''
            if not isinstance(value, str): raise PublicationError('Неверный адрес источника.')
            if value: text_parts.append('Источник: ' + value)
    if not has_text: raise PublicationError('У поста нет текста.')
    text = '\n\n'.join(text_parts)
    photo = image_url(blocks)
    result = []
    if photo:
        if not media or media.get('url') != photo:
            raise PublicationError('Изображение не подготовлено.')
        if len(chunks(text, 1024)) == 1:
            return [{'method': 'sendPhoto', 'payload': {**media, 'caption': text}}]
        result.append({'method': 'sendPhoto', 'payload': dict(media)})
    elif media is not None:
        raise PublicationError('Пост не содержит подготовленного изображения.')
    result += [{'method': 'sendMessage', 'payload': {'text': part}} for part in chunks(text, 4096)]
    if len(result) > 100: raise PublicationError('Слишком большой пост.')
    return result


def publish(repo, transport, post_id, revision):
    """Один новый запуск. Никаких сетевых retries или подхвата старой попытки."""
    transport.ensure_enabled(post_id)
    post = repo.post(post_id)
    if not post or post.get('status') != 'ready' or post.get('revision') != revision:
        raise PublicationError('Пост не готов или изменился. Открой подтверждение заново.')
    # Выборка и подготовка не дают права отправлять: далее обязательна атомарная RPC.
    previous = repo.latest(post_id)
    if previous and (previous['state'] in ('sending', 'needs_review', 'succeeded')
                     or previous['post_revision'] == revision):
        raise PublicationError('Попытка уже существует. Открой результат и проверь канал.')
    media, photo_bytes = transport.prepare(image_url(post.get('blocks') or []))
    plan = build_plan(post.get('blocks') or [], media)
    bot_id, chat_id = transport.target()
    attempt_id, worker = str(uuid4()), str(uuid4())
    current = None
    try:
        # Неоднозначный ответ begin не разрешает ни одного отправления.
        repo.begin(attempt_id, worker, post_id, revision, bot_id, chat_id, plan, media)
        for ordinal, part in enumerate(plan, 1):
            current = ordinal
            claimed = repo.claim(attempt_id, worker, ordinal)
            if claimed != part:
                raise DeliveryUncertain('План базы не совпал с подготовленным постом.')
            receipt = transport.send(part, photo_bytes, chat_id)
            repo.record(attempt_id, worker, ordinal, receipt)
        repo.finish(attempt_id)
        return attempt_id
    except Exception as error:
        reason = 'telegram_rejected' if isinstance(error, DeliveryRejected) else 'transport' if isinstance(error, DeliveryUncertain) else 'database'
        try:
            repo.review(attempt_id, reason, current, isinstance(error, DeliveryRejected))
        except Exception:
            pass  # БД может быть недоступна; sending остаётся блокировкой, не разрешением повтора.
        raise PublicationError('Не удалось подтвердить завершение. Проверь журнал и канал; повторная отправка запрещена.') from None


class SupabasePublicationRepository:
    """Серверный адаптер RPC. Конструктор не читает .env и не создаёт соединений."""
    def __init__(self, database):
        self.database = database

    def rpc(self, name, **params):
        return self.database.db.rpc(name, {'p_' + key: value for key, value in params.items()}).execute().data

    def post(self, post_id):
        return self.database.get_post(str(post_id))

    def latest(self, post_id):
        # worker_token никогда не передаётся представлению/браузеру.
        rows = (self.database.db.table('cf_publication_attempts')
                .select('id,post_id,post_revision,chat_id,bot_id,state,started_at,review_after,finished_at,reason_code,review_note,reviewed_by,reviewed_at,review_log')
                .eq('post_id', str(post_id)).order('started_at', desc=True).limit(1).execute()).data
        return rows[0] if rows else None

    def parts(self, attempt_id):
        return (self.database.db.table('cf_publication_parts')
                .select('ordinal,method,state,message_id,telegram_date,reason_code,confirmation_source')
                .eq('attempt_id', str(attempt_id)).order('ordinal').execute()).data or []

    def begin(self, attempt_id, worker, post_id, revision, bot_id, chat_id, parts, media):
        value = self.rpc('cf_begin_publication', attempt_id=attempt_id, worker_token=worker,
                         post_id=str(post_id), expected_revision=revision, bot_id=bot_id,
                         chat_id=chat_id, parts=parts, media=media)
        if value != attempt_id: raise DeliveryUncertain('Начало не подтверждено.')

    def claim(self, attempt_id, worker, ordinal):
        return self.rpc('cf_claim_publication_part', attempt_id=attempt_id, worker_token=worker, ordinal=ordinal)

    def record(self, attempt_id, worker, ordinal, receipt):
        self.rpc('cf_record_publication_part', attempt_id=attempt_id, worker_token=worker, ordinal=ordinal,
                 chat_id=receipt['chat_id'], message_id=receipt['message_id'], date=receipt['date'])

    def review(self, attempt_id, reason, ordinal=None, rejected=False):
        self.rpc('cf_review_publication', attempt_id=attempt_id, reason=reason, ordinal=ordinal, rejected=rejected)

    def finish(self, attempt_id):
        self.rpc('cf_finish_publication', attempt_id=attempt_id)

    def reconcile(self, attempt_id, action, reviewer, note, quiesced, ordinal=None, message_id=None, date=None):
        self.rpc('cf_reconcile_publication', attempt_id=attempt_id, action=action, reviewer=reviewer,
                 note=note, quiesced=quiesced, ordinal=ordinal, message_id=message_id, date=date)
