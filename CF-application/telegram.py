import os
import requests
from dotenv import load_dotenv

load_dotenv()


def publish_to_telegram(post):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    image_url = None
    text_parts = []

    for block in post.get("blocks") or []:
        if block.get("type") == "image":
            image_url = block.get("url")

        elif block.get("type") == "text":
            text_parts.append(block.get("content") or "")

        elif block.get("type") == "source":
            url = block.get("url")
            if url:
                text_parts.append(f"Источник: {url}")

    text = "\n\n".join(part for part in text_parts if part)

    if not text:
        raise ValueError("У поста нет текста")

    api_url = f"https://api.telegram.org/bot{token}"

    def send(method, payload):
        url = f"{api_url}/{method}"

        if method == "sendPhoto":
            image_url = payload["photo"]

            # Скачиваем фотографию с сайта-источника
            image_response = requests.get(
                image_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            image_response.raise_for_status()

            # Передаём фотографию Telegram как файл
            response = requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "caption": payload.get("caption", ""),
                },
                files={
                    "photo": (
                        "photo.jpg",
                        image_response.content,
                        "image/jpeg",
                    )
                },
                timeout=60,
            )

        else:
            # Обычное текстовое сообщение
            response = requests.post(
                url,
                json={"chat_id": chat_id, **payload},
                timeout=30,
            )

        result = response.json()

        if not result.get("ok"):
            raise RuntimeError(
                f"Telegram: {response.status_code} — "
                f"{result.get('description', 'Неизвестная ошибка')}"
            )

        return result["result"]

    messages = []

    # Короткий текст — одно сообщение с фотографией.
    if image_url and len(text) <= 1024:
        messages.append(send("sendPhoto", {
            "photo": image_url,
            "caption": text,
        }))

    else:
        # Длинный текст — сначала фотография.
        if image_url:
            messages.append(send("sendPhoto", {
                "photo": image_url,
            }))

        # Затем текст, частями не более 4096 символов.
        for start in range(0, len(text), 4096):
            messages.append(send("sendMessage", {
                "text": text[start:start + 4096],
            }))

    return messages