"""Единые маршруты публикации для старого интерфейса и нового кабинета.

Отправка по умолчанию закрыта конфигурацией; просмотр журнала и ручная
сверка не вызывают Telegram. Реальная БД требует отдельно применённого SQL.
"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import database
import studio_views as view
from publication import PublicationError, SupabasePublicationRepository, publish
from telegram import TelegramTransport, publication_enabled

router = APIRouter(default_response_class=HTMLResponse)


def repository():
    return SupabasePublicationRepository(database)


def message(text, code=409):
    return HTMLResponse(view.layout('Публикация', '<section class="panel"><h1>Публикация</h1><p>' + view.e(text) + '</p><a href="' + view.BASE + '/posts">К постам →</a></section>', 'posts'), status_code=code)


def status_panel(post):
    """Читать состояние без изменений БД и без запроса Telegram."""
    if 'revision' not in post:
        return view.notice('Журнал публикаций ещё не подключён к базе. Отправка через новый код закрыта до отдельного применения и проверки SQL.')
    repo = repository()
    try:
        attempt = repo.latest(post['id'])
        parts = repo.parts(attempt['id']) if attempt else []
    except Exception:
        return view.notice('Журнал публикаций недоступен. Не отправляй пост повторно до проверки соединения.', 'error')
    if not attempt:
        if post.get('status') == 'published':
            return view.notice('Для этой прежней публикации сведения об отправке не зафиксированы.')
        if post.get('status') == 'ready':
            if publication_enabled(post['id']):
                return f'<p><a class="button" href="{view.BASE}/posts/{view.ident(post["id"])}/publish">Проверить и опубликовать →</a></p>'
            return view.notice('Отправка выключена или этот пост не включён владельцем в список разрешённых для испытания.')
        return ''
    states = {'sending': 'Отправляется', 'needs_review': 'Требуется проверка', 'succeeded': 'Опубликовано', 'cancelled_no_delivery': 'Отменено: подтверждено отсутствие доставки'}
    confirmed = sum(p['state'] == 'confirmed' for p in parts)
    rows = ''.join(f'<tr><td>{p["ordinal"]}</td><td>{view.e(p["method"])}</td><td>{view.e(p["state"])}</td><td>{view.e(p.get("message_id"))}</td><td>{view.e(p.get("telegram_date"))}</td></tr>' for p in parts)
    body = f'<section class="panel source-panel"><h2>{states[attempt["state"]]}</h2><p>Подтверждено {confirmed} из {len(parts)} частей · редакция {attempt["post_revision"]}</p><p class="hint">Канал {attempt["chat_id"]} · попытка {view.e(attempt["id"])}</p><div style="overflow:auto"><table cellpadding="10"><thead><tr><th>Часть</th><th>Метод</th><th>Состояние</th><th>Message ID</th><th>Время UTC</th></tr></thead><tbody>{rows}</tbody></table></div>'
    if attempt['state'] == 'sending':
        body += f'<p class="hint">Истечение времени не разрешает повтор. После сбоя/перезапуска проверь состояние.</p><form method="post" action="{view.BASE}/posts/{post["id"]}/publication-check"><button class="button secondary">Проверить зависшую попытку</button></form>'
    if attempt['state'] == 'needs_review':
        body += f'''<p class="notice">Не отправляй пост заново. Сначала останови прежний отправитель и сверь сообщения с каналом. Эта форма не отправляет сообщений.</p>
<form method="post" action="{view.BASE}/posts/{post['id']}/publication-review">
<input type="hidden" name="attempt_id" value="{attempt['id']}">
<label>Кто проверил <input name="reviewer" required maxlength="100" value="Владелец"></label>
<label>Основание решения <textarea name="note" required rows="3" maxlength="2000"></textarea></label>
<label><input type="checkbox" name="quiesced" value="true" required> Прежний отправитель остановлен; незавершённых запросов нет</label>
<details><summary>Дозаписать подтверждённое сообщение</summary><label>Номер части <input type="number" name="ordinal" min="1"></label><label>Message ID из канала <input type="number" name="message_id" min="1"></label><label>Дата сообщения (UTC) <input type="datetime-local" name="date" step="1"></label><button class="button secondary" name="action" value="confirm">Подтвердить найденную часть</button></details>
<p><button class="button secondary" name="action" value="finish">Завершить по всем подтверждениям</button></p>
<label><input type="checkbox" name="no_delivery" value="true"> Я проверил, что ни одна часть не доставлена</label><p><button class="button secondary" name="action" value="cancel_no_delivery">Закрыть без доставки</button></p></form>'''
    if attempt['state'] == 'cancelled_no_delivery':
        body += '<p class="hint">Для новой попытки верни пост в черновик и утверди заново. Старую редакцию повторять нельзя.</p>'
    for decision in attempt.get('review_log') or []:
        body += '<p class="hint">Решение: ' + view.e(decision.get('action')) + ' · ' + view.e(decision.get('reviewer')) + ' · ' + view.e(decision.get('reviewed_at')) + '<br>' + view.e(decision.get('note')) + '</p>'
    body += '</section>'
    return body


@router.get('/post/{post_id}/publish')
@router.get(view.BASE + '/posts/{post_id}/publish')
def confirm(post_id: UUID):
    try:
        post = database.get_post(str(post_id))
        if not post: return message('Пост не найден.', 404)
        if post.get('status') != 'ready': return message('Публиковать можно только готовый пост.')
        if not publication_enabled(post_id): return message('Реальная отправка выключена или этот пост не разрешён владельцем.', 403)
        if 'revision' not in post: return message('Сначала подключи журнал публикаций к базе.', 503)
        attempt = repository().latest(post_id)
        if attempt and (attempt['state'] != 'cancelled_no_delivery' or attempt['post_revision'] == post['revision']):
            return message('Попытка уже существует. Открой журнал перед дальнейшими действиями.')
        body = f'''<section class="panel"><h1>Опубликовать готовый пост?</h1><h2>{view.e(post['title'])}</h2><p>СССР · редакция {post['revision']}</p><p>Перед отправкой проверь канал: старый статус ready не доказывает, что пост никогда не отправлялся.</p><form method="post" action="{view.BASE}/posts/{post_id}/publish-now"><input type="hidden" name="revision" value="{post['revision']}"><label><input type="checkbox" required name="confirmed" value="true"> Текст, канал и отсутствие прежней отправки проверены</label><p><button class="button">Опубликовать в Telegram</button></p></form><a href="{view.BASE}/posts/{post_id}">Вернуться в пост</a></section>'''
        return view.layout('Подтверждение публикации', body, 'posts')
    except Exception:
        return message('Не удалось проверить данные. Отправка не начата.', 503)


@router.post('/post/{post_id}/publish-now')
@router.post(view.BASE + '/posts/{post_id}/publish-now')
def send(post_id: UUID, revision: int = Form(..., ge=1), confirmed: bool = Form(False)):
    if not confirmed: return message('Необходимо подтвердить проверку поста.', 422)
    try:
        publish(repository(), TelegramTransport(), str(post_id), revision)
    except PublicationError as error:
        return message(str(error))
    except Exception:
        return message('Не удалось проверить/завершить отправку. Сверь журнал и канал перед повтором.', 503)
    return RedirectResponse(f'{view.BASE}/posts/{post_id}', status_code=303)


@router.post(view.BASE + '/posts/{post_id}/publication-check')
def check(post_id: UUID):
    try:
        repo = repository(); attempt = repo.latest(post_id)
        if attempt and attempt['state'] == 'sending':
            deadline = datetime.fromisoformat(attempt['review_after'].replace('Z', '+00:00'))
            if datetime.now(timezone.utc) < deadline:
                return message('Время попытки ещё не истекло. Не запускай отправку повторно.')
            repo.review(attempt['id'], 'expired')
        return RedirectResponse(f'{view.BASE}/posts/{post_id}', status_code=303)
    except Exception:
        return message('Не удалось проверить журнал. Повторная отправка не разрешена.', 503)


@router.post(view.BASE + '/posts/{post_id}/publication-review')
def review(post_id: UUID, attempt_id: UUID = Form(...), action: str = Form(...),
           reviewer: str = Form(..., max_length=100), note: str = Form(..., max_length=2000),
           quiesced: bool = Form(False), no_delivery: bool = Form(False),
           ordinal: str = Form(''), message_id: str = Form(''), date: str = Form('')):
    try:
        repo = repository(); attempt = repo.latest(post_id)
        if not attempt or attempt['id'] != str(attempt_id) or not quiesced or not reviewer.strip() or not note.strip():
            return message('Сначала останови отправитель и укажи основание проверки.', 422)
        if action == 'finish': repo.finish(str(attempt_id))
        elif action == 'confirm':
            stamp = datetime.fromisoformat(date)
            if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
            repo.reconcile(str(attempt_id), action, reviewer, note, True, int(ordinal), int(message_id), stamp.isoformat())
        elif action == 'cancel_no_delivery' and no_delivery:
            repo.reconcile(str(attempt_id), action, reviewer, note, True)
        else: return message('Выбери действие и подтверди результат сверки.', 422)
        return RedirectResponse(f'{view.BASE}/posts/{post_id}', status_code=303)
    except Exception:
        return message('Решение не применено или не подтверждено. Проверь журнал; отправка не выполнялась.')
