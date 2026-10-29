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
    # Короткие статьи сохраняем полностью, многоточие — только при сокращении.
    text = text.strip()
    excerpt = text
    if len(text) > 500:
        excerpt = text[:500]
        if not text[500].isspace() and not excerpt[-1].isspace():
            excerpt = excerpt.rsplit(" ", 1)[0] if " " in excerpt else excerpt
        excerpt = excerpt.rstrip() + "…"
    post_text = "\n\n".join(part for part in (title, excerpt) if part)

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


def replace_text(blocks, text):
    """Заменить текстовые блоки одним, сохранив изображение и источник.

    Если текстового блока ещё нет, добавить его перед ссылкой на источник.
    Входные блоки не изменяются: их копии пригодны для сохранения в базе.
    """
    result = []
    inserted = False
    for block in blocks or []:
        if block.get("type") == "text":
            if not inserted:
                result.append({"type": "text", "content": text})
                inserted = True
        else:
            if block.get("type") == "source" and not inserted:
                result.append({"type": "text", "content": text})
                inserted = True
            result.append(dict(block))
    if not inserted:
        result.append({"type": "text", "content": text})
    return result
