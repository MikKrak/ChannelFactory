"""
source.py — получение списка статей из выбранной RSS-ленты.

Ботаничка остаётся источником по умолчанию для прежнего ручного импорта.

Загружает выбранную страницу ленты и преобразует записи в материалы
для последующего сохранения: источник, URL, заголовок, дата и исходные данные.
Полный текст статьи не загружает и в базу самостоятельно не записывает.
"""

import requests
import feedparser
from email.utils import parsedate_to_datetime

# --- Адрес источника ---

RSS_URL = "https://www.botanichka.ru/feed/"


# --- Получение записей RSS ---

def get_articles(page=2, feed_url=RSS_URL):
    """Загрузить страницу RSS и вернуть заголовки, ссылки и даты статей."""

    response = requests.get(
        feed_url,
        params={"paged": page},
        timeout=20,
    )
    response.raise_for_status()

    feed = feedparser.parse(response.content)

    if feed.bozo:
        raise ValueError(f"Ошибка разбора RSS: {feed.bozo_exception}")

    return [
        {
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "published": item.get("published", ""),
        }
        for item in feed.entries
    ]


# --- Связь с источником в базе ---

SOURCE_ID = "e3c9eb83-5a5f-4351-836b-c2f93b4fa567"


# --- Подготовка материалов к сохранению ---

def prepare_materials(articles, source_id=SOURCE_ID):
    """Преобразовать записи RSS в словари для таблицы материалов."""

    materials = []

    for article in articles:
        published = article.get("published", "")

        # Дату RSS переводим в ISO; отсутствие даты сохраняем как None.
        published_at = (
            parsedate_to_datetime(published).isoformat()
            if published else None
        )

        materials.append(
            {
                "source_id": source_id,
                "url": article["url"],
                "title": article["title"],
                "published_at": published_at,
                "raw_data": article,
            }
        )

    return materials


# Ручная проверка RSS при запуске модуля отдельно.
# --- Ручная проверка ---

if __name__ == "__main__":
    articles = get_articles(page=2)

    print(f"Получено статей: {len(articles)}")

    for number, article in enumerate(articles, 1):
        print(f"{number}. {article['title']}")
        print(f"   {article['url']}")
