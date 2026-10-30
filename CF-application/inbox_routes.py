"""Кабинет обращений: чтение, подготовка ответа и отдельное подтверждение.

Не запускает получение событий. До подключения схемы показывает пояснение.
Реальная отправка дополнительно закрыта списком конкретных ответов.
"""
import os
from functools import wraps
from uuid import UUID, uuid4
from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
import database
import studio_views as view
from inbox import InboxError, InboxRepository, ReplyTransport, require_enabled, send_reply
from inbox_state import read_state

BASE = view.BASE + '/inbox'
router = APIRouter(default_response_class=HTMLResponse)
STATES = {'new': 'Новое', 'handled': 'Обработано', 'prepared': 'Подготовлен',
          'sending': 'Отправляется — повтор запрещён', 'needs_review': 'Требуется проверка',
          'sent': 'Доставлен', 'cancelled': 'Закрыт без доставки'}


def repository():
    return InboxRepository(database.db)


def page(body):
    return view.layout('Обращения', body, 'inbox')


def error(text, status=503):
    return HTMLResponse(page('<section class="panel"><h1>Обращения</h1>' + view.notice(text) + f'<a href="{BASE}">К обращениям</a></section>'), status_code=status)


def receiver_notice():
    state = read_state(8995624604)['state']
    label = {'running': 'Работает', 'stopped': 'Остановлен', 'error': 'Ошибка — требуется проверка', 'unknown': 'Состояние не подтверждено'}.get(state, 'Состояние не подтверждено')
    return view.notice('Получатель сообщений: ' + label + '. Обнови страницу, чтобы увидеть новые обращения.')


def guarded(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        try:
            require_enabled('CF_INBOX_UI_ENABLED')
            return fn(*args, **kwargs)
        except InboxError as exc:
            return error(str(exc), 409)
        except Exception:
            return error('Не удалось подтвердить действие. Проверь историю перед повтором. Отправка заново не выполняется.')
    return call


@router.get(BASE)
@guarded
def dialogs(offset: int = Query(0, ge=0)):
    items = repository().dialogs(offset)
    body = view.heading('ПЕРЕПИСКА С ЧИТАТЕЛЯМИ', 'Обращения', 'Личные сообщения каналу. Ответ отправляется только после отдельного подтверждения.')
    body += receiver_notice()
    body += '<section class="panel">'
    for item in items:
        body += f'<a class="record" href="{BASE}/{item["id"]}"><div><b>Диалог {view.e(str(item["id"])[:8])}</b><small>{view.e(STATES[item["state"]])} · {view.e(item["updated_at"])}</small></div><span>Открыть →</span></a>'
    body += ('' if items else '<p>Обращений пока нет.</p>') + '</section>'
    if offset:
        body += f'<a href="{BASE}?offset={max(0,offset-20)}">← Новее</a> '
    if len(items) == 20:
        body += f'<a href="{BASE}?offset={offset+20}">Старее →</a>'
    return page(body)


@router.get(BASE + '/{dialog_id}')
@guarded
def dialog(dialog_id: UUID, offset: int = Query(0, ge=0)):
    repo = repository(); item = repo.dialog(dialog_id)
    if not item:
        return error('Диалог не найден.', 404)
    messages = repo.messages(dialog_id, offset)
    replies = repo.replies(dialog_id)
    body = f'<a href="{BASE}">← Обращения</a><h1>Переписка с читателем · {str(dialog_id)[:8]}</h1><p>{view.e(STATES[item["state"]])}</p>'
    body += receiver_notice()
    for msg in reversed(messages):
        body += '<section class="panel"><h2>Сообщение читателя</h2><small>' + view.e(msg['sent_at']) + '</small><p style="white-space:pre-wrap">' + view.e(msg['text']) + '</p></section>'
    if offset:
        body += f'<a href="{BASE}/{dialog_id}?offset={max(0,offset-20)}">← Новее</a> '
    if len(messages) == 20:
        body += f'<a href="{BASE}/{dialog_id}?offset={offset+20}">Ранее →</a>'
    unresolved = False
    for reply in reversed(replies):
        state = reply['state']; unresolved |= state in ('prepared', 'sending', 'needs_review')
        body += f'<section class="panel"><h2>Ответ · {view.e(STATES[state])}</h2><p style="white-space:pre-wrap">{view.e(reply["text"])}</p>'
        if state == 'sent':
            body += f'<p>Сообщение №{reply["message_id"]} · {view.e(reply["sent_at"])}</p>'
        elif state == 'prepared':
            body += f'<a class="button" href="{BASE}/replies/{reply["id"]}/confirm">Проверить ответ</a>'
        elif state == 'sending':
            body += f'<p>После сбоя сначала останови отправитель, затем сверь переписку.</p><form method="post" action="{BASE}/replies/{reply["id"]}/review"><button class="button secondary">Перевести на ручную проверку</button></form>'
        elif state == 'needs_review':
            body += f'''<form method="post" action="{BASE}/replies/{reply['id']}/reconcile">
<label>Основание и кто проверил<textarea name="note" required maxlength="2000"></textarea></label>
<label><input type="checkbox" name="quiesced" value="true" required> Отправитель остановлен, запросов в работе нет</label>
<label>Номер найденного сообщения<input name="message_id" type="number" min="1"></label>
<label>Время сообщения UTC<input name="date" type="datetime-local" step="1"></label>
<button class="button" name="action" value="confirm">Подтвердить доставку</button>
<label><input type="checkbox" name="no_delivery" value="true"> Проверено: ответ не доставлен</label>
<button class="button secondary" name="action" value="no_delivery">Закрыть без доставки</button></form>'''
        for decision in reply.get('review_log') or []:
            body += '<p>Решение: ' + view.e(decision.get('action')) + ' · ' + view.e(decision.get('note')) + '</p>'
        body += '</section>'
    if not unresolved:
        body += f'''<section class="panel"><h2>Ручной ответ</h2><form method="post" action="{BASE}/{dialog_id}/prepare">
<input type="hidden" name="request_id" value="{uuid4()}"><label>Текст ответа<textarea name="text" required maxlength="4096" rows="5"></textarea></label>
<button class="button">Сохранить и проверить ответ</button><p>Этот шаг ничего не отправляет.</p></form></section>'''
    if offset == 0 and messages:
        body += f'<form method="post" action="{BASE}/{dialog_id}/state"><input type="hidden" name="seen_message" value="{messages[0]["id"]}"><button class="button secondary" name="state" value="handled">Отметить обработанным</button> <button class="button secondary" name="state" value="new">Вернуть в новые</button></form>'
    return page(body)


@router.post(BASE + '/{dialog_id}/prepare')
@guarded
def prepare(dialog_id: UUID, request_id: UUID = Form(...), text: str = Form(..., max_length=4096)):
    if not text.strip() or len(text.encode('utf-16-le')) // 2 > 4096:
        return error('Ответ должен содержать от 1 до 4096 символов Telegram.', 422)
    repository().rpc('prepare_reply', id=str(request_id), dialog_id=str(dialog_id), text=text)
    return RedirectResponse(f'{BASE}/replies/{request_id}/confirm', 303)


@router.get(BASE + '/replies/{reply_id}/confirm')
@guarded
def confirm(reply_id: UUID):
    reply = repository().reply(reply_id)
    if not reply:
        return error('Ответ не найден.', 404)
    if reply['state'] != 'prepared':
        return error('Ответ уже обрабатывался. Проверь историю.', 409)
    allowed = os.environ.get('CF_INBOX_REPLY_ENABLED') == '1' and str(reply_id) in os.environ.get('CF_INBOX_ALLOWED_REPLY_IDS', '').split(',')
    messages = repository().messages(reply['dialog_id'])
    body = '<section class="panel"><h1>Проверка ответа читателю</h1><p>Диалог ' + view.e(str(reply['dialog_id'])[:8]) + '</p>'
    if messages:
        body += '<h2>Последнее обращение</h2><p style="white-space:pre-wrap">' + view.e(messages[0]['text']) + '</p>'
    body += '<h2>Твой ответ</h2><p style="white-space:pre-wrap">' + view.e(reply['text']) + '</p>'
    body += f'<a href="{BASE}/{reply["dialog_id"]}">Вернуться к переписке и проверить адресата</a>'
    if allowed:
        body += f'<form method="post" action="{BASE}/replies/{reply_id}/send"><label><input type="checkbox" required name="confirmed" value="true"> Текст и диалог проверены</label><button class="button">Отправить читателю</button></form>'
    else:
        body += view.notice('Реальная отправка этого ответа ещё не разрешена владельцем.')
    body += f'<form method="post" action="{BASE}/replies/{reply_id}/cancel"><button class="button secondary">Отменить подготовленный ответ</button><p>После отмены можно написать новый текст. Отправки не будет.</p></form>'
    return page(body + '</section>')


@router.post(BASE + '/replies/{reply_id}/cancel')
@guarded
def cancel(reply_id: UUID):
    repo = repository(); reply = repo.reply(reply_id)
    if not reply:
        return error('Ответ не найден.', 404)
    repo.rpc('cancel_prepared', id=str(reply_id))
    return RedirectResponse(f'{BASE}/{reply["dialog_id"]}', 303)


@router.post(BASE + '/replies/{reply_id}/send')
@guarded
def send(reply_id: UUID, confirmed: bool = Form(False)):
    if not confirmed:
        return error('Подтверди текст и диалог.', 422)
    repo = repository()
    send_reply(repo, ReplyTransport(os.environ.get('TELEGRAM_BOT_TOKEN', '')), reply_id)
    reply = repo.reply(reply_id)
    return RedirectResponse(f'{BASE}/{reply["dialog_id"]}', 303)


@router.post(BASE + '/{dialog_id}/state')
@guarded
def mark(dialog_id: UUID, state: str = Form(...), seen_message: UUID = Form(...)):
    repository().rpc('mark', dialog_id=str(dialog_id), state=state, seen_message=str(seen_message))
    return RedirectResponse(f'{BASE}/{dialog_id}', 303)


@router.post(BASE + '/replies/{reply_id}/review')
@guarded
def review(reply_id: UUID):
    repo = repository(); reply = repo.reply(reply_id)
    if not reply:
        return error('Ответ не найден.', 404)
    repo.rpc('review_reply', id=str(reply_id))
    return RedirectResponse(f'{BASE}/{reply["dialog_id"]}', 303)


@router.post(BASE + '/replies/{reply_id}/reconcile')
@guarded
def reconcile(reply_id: UUID, action: str = Form(...), note: str = Form(..., max_length=2000),
              quiesced: bool = Form(False), no_delivery: bool = Form(False),
              message_id: str = Form(''), date: str = Form('')):
    from datetime import datetime, timezone
    if action not in ('confirm', 'no_delivery') or not quiesced or not note.strip() or (action == 'no_delivery' and not no_delivery):
        return error('Нужны основание решения и подтверждение остановки отправителя.', 422)
    repo = repository(); reply = repo.reply(reply_id)
    if not reply:
        return error('Ответ не найден.', 404)
    stamp = datetime.fromisoformat(date).replace(tzinfo=timezone.utc).isoformat() if action == 'confirm' else None
    repo.rpc('reconcile_reply', id=str(reply_id), action=action, note=note, quiesced=True,
             message_id=int(message_id) if action == 'confirm' else None, date=stamp)
    return RedirectResponse(f'{BASE}/{reply["dialog_id"]}', 303)
