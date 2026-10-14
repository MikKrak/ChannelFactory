"""
editor.py — подготовка черновика поста из материала.

Получает словарь статьи и собирает пост из блоков:
изображение, текст и ссылка на источник.

Возвращает словарь с полями title и blocks.
Не сохраняет пост в базу и не отправляет его в Telegram.
"""


# --- Подготовка поста ---

def prepare_post(article):
    """Собрать заголовок и доступные блоки поста из данных статьи."""

    # --- Исходные данные ---
    # Отсутствующие поля заменяем пустыми значениями.
    content = article.get("content") or {}

    title = article.get("title") or ""
    text = content.get("text") or ""
    image_url = content.get("image_url") or ""
    source_url = article.get("url") or ""

    # --- Краткий текст поста ---
    # Берём первые 500 символов и удаляем часть после последнего пробела.
    # Текущее правило применяется и к тексту короче 500 символов.
    excerpt = text[:500].rsplit(" ", 1)[0] if text else ""

    # При наличии выдержки добавляем многоточие; иначе оставляем заголовок.
    post_text = f"{title}\n\n{excerpt}..." if excerpt else title

    # --- Блоки поста ---
    # Сохраняем порядок: изображение → текст → источник.
    # Блок добавляем только при наличии соответствующих данных.
    blocks = []

    if image_url:
        blocks.append(
            {
                "type": "image",
                "url": image_url,
            }
        )

    if post_text:
        blocks.append(
            {
                "type": "text",
                "content": post_text,
            }
        )

    if source_url:
        blocks.append(
            {
                "type": "source",
                "url": source_url,
            }
        )

    # --- Результат для последующего сохранения ---
    return {
        "title": title,
        "blocks": blocks,
    }
