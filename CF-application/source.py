import requests
import feedparser
from email.utils import parsedate_to_datetime

RSS_URL = "https://www.botanichka.ru/feed/"


def get_articles(page=2):
    response = requests.get(
        RSS_URL,
        params={"paged": page},
        timeout=20
    )
    response.raise_for_status()

    feed = feedparser.parse(response.content)

    if feed.bozo:
        raise ValueError(f"Ошибка разбора RSS: {feed.bozo_exception}")

    return [
        {
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "published": item.get("published", "")
        }
        for item in feed.entries
    ]


SOURCE_ID = "e3c9eb83-5a5f-4351-836b-c2f93b4fa567"


def prepare_materials(articles):
    materials = []

    for article in articles:
        published = article.get("published", "")

        published_at = (
            parsedate_to_datetime(published).isoformat()
            if published else None
        )

        materials.append({
            "source_id": SOURCE_ID,
            "url": article["url"],
            "title": article["title"],
            "published_at": published_at,
            "raw_data": article
        })

    return materials

if __name__ == "__main__":
    articles = get_articles(page=2)

    print(f"Получено статей: {len(articles)}")

    for number, article in enumerate(articles, 1):
        print(f"{number}. {article['title']}")
        print(f"   {article['url']}")