def prepare_post(article):
    content = article.get("content") or {}

    title = article.get("title") or ""
    text = content.get("text") or ""
    image_url = content.get("image_url") or ""
    source_url = article.get("url") or ""

    # Берём первые 500 символов и отбрасываем хвост после последнего пробела.
    excerpt = text[:500].rsplit(" ", 1)[0] if text else ""

    post_text = f"{title}\n\n{excerpt}..." if excerpt else title

    # Порядок блоков: изображение, текст, ссылка на источник.
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

    return {
        "title": title,
        "blocks": blocks,
    }
