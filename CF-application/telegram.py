"""telegram.py — подготовка фотографии и отправка одной части публикации.

Не повторяет сетевые запросы. Вызовы возможны только через publication.py
после подтверждённой записи начала и разрешения части в базе.
"""
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv
from publication import DeliveryRejected, DeliveryUncertain, PublicationError

load_dotenv(Path(__file__).resolve().parent / '.env')


def publication_enabled(post_id):
    """Включение и список разрешённых IDs задаются владельцем отдельно от кода."""
    allowed = {x.strip() for x in os.environ.get('CF_PUBLICATION_ALLOWED_POST_IDS', '').split(',') if x.strip()}
    return os.environ.get('CF_PUBLICATION_ENABLED') == '1' and str(post_id) in allowed


class TelegramTransport:
    def ensure_enabled(self, post_id):
        if not publication_enabled(post_id):
            raise PublicationError('Реальная отправка выключена или этот пост не разрешён для испытания.')

    def target(self):
        """Проверить бота чтением, не потребляя входящие события."""
        try:
            self.token = os.environ['TELEGRAM_BOT_TOKEN']
            chat = int(os.environ['TELEGRAM_CHAT_ID'])
            result = requests.get(f'https://api.telegram.org/bot{self.token}/getMe', timeout=(10, 20), allow_redirects=False).json()
            if not result.get('ok') or not result['result'].get('is_bot'):
                raise ValueError()
            return int(result['result']['id']), chat
        except Exception:
            raise PublicationError('Не удалось проверить бота и канал. Отправка не начата.') from None

    def prepare(self, image_url):
        """Скачать изображение до начала отправки; сохранить точные байты и MIME."""
        if not image_url: return None, None
        try:
            parsed = urlsplit(image_url)
            if parsed.scheme not in ('https', 'http') or not parsed.netloc: raise ValueError()
            with requests.get(image_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=(10, 30), stream=True) as response:
                response.raise_for_status()
                data = bytearray()
                for part in response.iter_content(65536):
                    data.extend(part)
                    if len(data) > 10 * 1024 * 1024: raise ValueError()
            raw = bytes(data)
            if raw.startswith(b'\xff\xd8\xff'): mime = 'image/jpeg'
            elif raw.startswith(b'\x89PNG\r\n\x1a\n'): mime = 'image/png'
            elif raw.startswith(b'RIFF') and raw[8:12] == b'WEBP': mime = 'image/webp'
            else: raise ValueError()
            return {'url': image_url, 'sha256': hashlib.sha256(raw).hexdigest(), 'mime': mime}, raw
        except Exception:
            raise PublicationError('Не удалось подготовить фотографию. Поддерживаются JPEG, PNG, WebP до 10 МБ.') from None

    def send(self, part, photo_bytes, chat_id):
        """Ровно один запрос; успех нормализуется в минимальный receipt."""
        method, payload = part['method'], part['payload']
        if method not in ('sendMessage', 'sendPhoto'):
            raise DeliveryRejected('Неизвестный метод отправки.')
        try:
            endpoint = f'https://api.telegram.org/bot{self.token}/{method}'
            if method == 'sendPhoto':
                if not photo_bytes or hashlib.sha256(photo_bytes).hexdigest() != payload['sha256']:
                    raise DeliveryRejected('Фотография не совпадает со снимком.')
                ext = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}[payload['mime']]
                response = requests.post(endpoint, data={'chat_id': chat_id, 'caption': payload.get('caption', '')},
                    files={'photo': ('photo.' + ext, photo_bytes, payload['mime'])}, timeout=(10, 60), allow_redirects=False)
            else:
                response = requests.post(endpoint, json={'chat_id': chat_id, 'text': payload['text']}, timeout=(10, 30), allow_redirects=False)
            data = response.json()
            if data.get('ok') is False:
                raise DeliveryRejected('Telegram отклонил запрос.')
            if data.get('ok') is not True:
                raise ValueError()
            message = data['result']
            if message['chat']['id'] != chat_id or not isinstance(message['message_id'], int) or message['message_id'] <= 0:
                raise ValueError()
            return {'chat_id': chat_id, 'message_id': message['message_id'],
                    'date': datetime.fromtimestamp(message['date'], timezone.utc).isoformat()}
        except (DeliveryRejected, DeliveryUncertain):
            raise
        except Exception:
            raise DeliveryUncertain('Результат запроса неизвестен. Нужна сверка канала.') from None


def publish_to_telegram(post):
    """Прежний прямой интерфейс заблокирован, чтобы не обходить журнал."""
    raise PublicationError('Прямая отправка отключена. Используй общий сервис публикации.')
