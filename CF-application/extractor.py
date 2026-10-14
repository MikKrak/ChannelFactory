import requests
from bs4 import BeautifulSoup


def load_page(url):
    response = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    return response.text


def extract_article(url):
    html = load_page(url)
    soup = BeautifulSoup(html, "html.parser")

    # Селектор рассчитан на текущую разметку источника; без блока текст пустой.
    content = soup.select_one("div.td-post-content")

    if content:
        text = content.get_text(separator="\n", strip=True)
    else:
        text = ""

    title = soup.title.get_text(strip=True) if soup.title else ""

    # Обложку берём из метаданных страницы, а не из текста статьи.
    image_tag = soup.select_one('meta[property="og:image"]')

    image_url = (
        image_tag.get("content", "")
        if image_tag else ""
    )

    return {
        "title": title,
        "url": url,
        "text": text,
        "image_url": image_url,
    }


# Ручная проверка извлечения статьи при запуске модуля отдельно.
if __name__ == "__main__":
    url = "https://www.botanichka.ru/article/10-shagov-kak-podgotovit-pochvu-k-sleduyushhemu-sezonu-prakticheskij-algoritm-osennego-uhoda/"
    article = extract_article(url)

    print("Заголовок:", article["title"])
    print("Адрес:", article["url"])
    print("Длина текста:", len(article["text"]))
    print("Начало статьи:")
    print(article["text"][:500])
    print("Фотография:", article["image_url"])
