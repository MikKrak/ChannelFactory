"""
main.py — веб-интерфейс редактора ChannelFactory.

Принимает запросы браузера: импорт материалов, подготовка и редактирование
постов, подтверждение и отправка в Telegram. Работу с данными, источником
и публикацией передаёт отдельным модулям.

HTML страниц формируется здесь; главная страница читается из шаблона.
Статические ресурсы разрешаются относительно расположения этого модуля.
Новый редакционный кабинет находится в studio.py и studio_views.py.
"""

from html import escape
from pathlib import Path

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from publication_routes import router as publication_router
from inbox_routes import router as inbox_router
from library_routes import router as library_router

from database import (
    count_materials,
    create_post,
    get_material,
    get_materials,
    get_post,
    get_posts,
    save_article_content,
    save_materials,
    update_post,
)
from editor import prepare_post, replace_text
from studio import router as studio_router
from extractor import extract_article
from source import get_articles, prepare_materials


# --- Приложение и статические ресурсы ---

app = FastAPI(title="Channel Factory")

APP_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
app.include_router(studio_router)
app.include_router(publication_router)
app.include_router(inbox_router)
app.include_router(library_router)


# --- Главная страница ---
@app.get("/", response_class=HTMLResponse)
def home():
    """Открыть список проектов нового кабинета."""

    return RedirectResponse(url="/studio", status_code=303)


# --- Импорт материалов ---
@app.post("/import")
def import_articles():
    """Получить вторую страницу RSS, сохранить материалы и вернуть счётчики."""

    from library import enabled, LibraryRepository
    if enabled():
        from database import db
        from source import SOURCE_ID
        return LibraryRepository(db).import_rss(SOURCE_ID, page=2)
    articles = get_articles(page=2)
    materials = prepare_materials(articles)

    saved = save_materials(materials)

    return {
        "status": "ok",
        "received": len(articles),
        "saved": saved,
        "database_count": count_materials(),
    }


# --- Список материалов ---
@app.get("/materials", response_class=HTMLResponse)
def show_materials():
    """Показать последние 20 материалов со ссылками на их карточки."""

    articles = get_materials(20)

    # Данные из базы экранируем перед включением в HTML.
    rows = ""

    for article in articles:
        title = escape(article.get("title") or "Без названия")
        url = escape(article.get("url") or "", quote=True)
        article_id = escape(str(article["id"]), quote=True)

        rows += f"""
        <tr>
            <td>{title}</td>
            <td>
                <a href="{url}" target="_blank" rel="noopener noreferrer">
                    Открыть
                </a>
            </td>
            <td>
                <a href="/material/{article_id}">Выбрать</a>
            </td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Материалы — Channel Factory</title>
        <link rel="stylesheet" href="/static/style.css">
    </head>
    <body>
        <main>
            <h1>Материалы</h1>
            <p><a href="/">← На главную</a></p>

            <section class="panel">
                <p>Последние {len(articles)} статей из Supabase</p>

                <table cellpadding="12">
                    <tr>
                        <th>Название</th>
                        <th>Источник</th>
                        <th>Действие</th>
                    </tr>
                    {rows}
                </table>
            </section>
        </main>
    </body>
    </html>
    """


# --- Карточка исходного материала ---
@app.get("/material/{material_id}", response_class=HTMLResponse)
def show_material(material_id: str):
    """Показать материал и предложенный текст для формы создания черновика."""

    article = get_material(material_id)

    if not article:
        return HTMLResponse(
            content="<h1>Материал не найден</h1>",
            status_code=404,
        )

    title = escape(article.get("title") or "Без названия")
    url = escape(article.get("url") or "", quote=True)

    published = article.get("published_at") or ""
    description = escape(published[:10])

    content = article.get("content") or {}

    article_text = escape(content.get("text") or "")
    image_url = escape(content.get("image_url") or "", quote=True)

    image_html = (
        f'<img src="{image_url}" '
        f'style="max-width:100%; border-radius:8px;">'
        if image_url
        else ""
    )

    text_html = (
        f'<div style="white-space:pre-line;">{article_text}</div>'
        if article_text
        else "<p>Содержание ещё не загружено.</p>"
    )

    # Предложение для формы; сохранение черновика выполняется отдельным запросом.
    if article_text:
        post = prepare_post(article)

        post_text = next(
            (
                block.get("content") or ""
                for block in post["blocks"]
                if block.get("type") == "text"
            ),
            "",
        )

        post_text = escape(post_text)
    else:
        post_text = ""

    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>{title} — Channel Factory</title>
        <link rel="stylesheet" href="/static/style.css">
    </head>
    <body>
        <main>
            <p><a href="/materials">← К списку материалов</a></p>

            <section class="panel">
                <h2>{title}</h2>

                <p>Дата публикации: {description}</p>

                <p>
                    <a href="{url}" target="_blank" rel="noopener noreferrer">
                        Открыть оригинал
                    </a>
                </p>

                <form action="/material/{material_id}/load" method="post">
                    <button type="submit">
                        Загрузить содержание
                    </button>
                </form>

                <h3>Исходная статья</h3>

                {image_html}
                {text_html}

                <hr>

                <h3>Подготовка Telegram-поста</h3>

                <form
                    action="/material/{material_id}/save-post"
                    method="post"
                >
                    <textarea
                        name="post_text"
                        rows="12"
                        style="width:100%; box-sizing:border-box;
                               padding:12px; font-size:15px;"
                    >{post_text}</textarea>

                    <p>
                        <button type="submit">
                            Сохранить черновик
                        </button>
                    </p>
                </form>
            </section>
        </main>
    </body>
    </html>
    """


# --- Загрузка полного текста исходного материала ---
@app.post("/material/{material_id}/load")
def load_material_content(material_id: str):
    """Загрузить и сохранить содержание статьи, если текст ещё отсутствует."""

    article = get_material(material_id)

    if not article:
        return HTMLResponse(
            content="<h1>Материал не найден</h1>",
            status_code=404,
        )

    content = article.get("content") or {}

    if content.get("text"):
        return RedirectResponse(
            url=f"/material/{material_id}",
            status_code=303,
        )

    extracted = extract_article(article["url"])

    save_article_content(material_id, extracted)

    return RedirectResponse(
        url=f"/material/{material_id}",
        status_code=303,
    )


# --- Создание черновика публикации из материала ---
@app.post("/material/{material_id}/save-post")
def save_material_post(
    material_id: str,
    post_text: str = Form(...),
):
    """Сохранить черновик из материала с текстом, полученным из формы."""

    article = get_material(material_id)

    if not article:
        return HTMLResponse(
            content="<h1>Материал не найден</h1>",
            status_code=404,
        )

    post = prepare_post(article)

    if not post_text.strip():
        return HTMLResponse("Текст поста не может быть пустым", status_code=400)
    post["blocks"] = replace_text(post["blocks"], post_text)

    create_post(
        material_id=material_id,
        title=post["title"],
        blocks=post["blocks"],
    )

    return RedirectResponse(
        url=f"/material/{material_id}",
        status_code=303,
    )


# --- Список публикаций ---
@app.get("/posts", response_class=HTMLResponse)
def show_posts(status: str = "all"):
    """Показать список постов с выбранным фильтром статуса."""

    allowed = {
        "all": "Все",
        "draft": "Черновики",
        "ready": "Готовые",
        "published": "Опубликованные",
    }

    if status not in allowed:
        status = "all"

    posts = get_posts(
        status=None if status == "all" else status
    )

    filters = " | ".join(
        f'<a href="/posts?status={key}">'
        f'{"<strong>" + label + "</strong>" if key == status else label}'
        f'</a>'
        for key, label in allowed.items()
    )

    status_names = {
        "draft": "Черновик",
        "ready": "Готов",
        "published": "Опубликован",
    }

    # Данные из базы экранируем перед включением в HTML.
    rows = ""

    for post in posts:
        post_id = escape(str(post["id"]), quote=True)
        title = escape(post.get("title") or "Без названия")

        post_status = status_names.get(
            post.get("status"),
            "Неизвестен",
        )

        updated = escape(
            (post.get("updated_at") or "")[:16].replace("T", " ")
        )

        rows += f"""
        <tr>
            <td>
                <a href="/post/{post_id}">{title}</a>
            </td>
            <td>{post_status}</td>
            <td>{updated}</td>
            <td>
                <form action="/post/{post_id}/publish" method="get">
                    <button type="submit">Опубликовать</button>
                </form>
            </td>
        </tr>
        """

    if not rows:
        rows = """
        <tr>
            <td colspan="4">Редакционных постов пока нет</td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Публикации — Channel Factory</title>
        <link rel="stylesheet" href="/static/style.css">
    </head>
    <body>
        <main>
            <h1>Публикации</h1>

            <p><a href="/">← На главную</a></p>

            <section class="panel">
                <p>{filters}</p>

                <p>Найдено публикаций: {len(posts)}</p>

                <table cellpadding="12">
                    <tr>
                        <th>Название</th>
                        <th>Статус</th>
                        <th>Изменено (UTC)</th>
                        <th>Действие</th>
                    </tr>
                    {rows}
                </table>
            </section>
        </main>
    </body>
    </html>
    """


# --- Карточка публикации ---
@app.get("/post/{post_id}", response_class=HTMLResponse)
def show_post(post_id: str):
    """Показать блоки поста; для черновика вывести форму редактирования."""

    post = get_post(post_id)

    if not post:
        return HTMLResponse(
            content="<h1>Публикация не найдена</h1>",
            status_code=404,
        )

    title = escape(post.get("title") or "Без названия")

    status_names = {
        "draft": "Черновик",
        "ready": "Готов",
        "published": "Опубликован",
    }

    status = status_names.get(
        post.get("status"),
        "Неизвестен",
    )

    is_draft = post.get("status") == "draft"

    blocks_html = ""

    for block in post.get("blocks") or []:
        block_type = block.get("type")

        # Фотография

        if block_type == "image":
            url = escape(block.get("url") or "", quote=True)

            if url:
                blocks_html += (
                    f'<p><img src="{url}" '
                    f'style="max-width:100%; border-radius:8px;"></p>'
                )

        # Текст публикации

        elif block_type == "text":
            content = escape(block.get("content") or "")

            if is_draft:
                # Черновик можно редактировать.
                blocks_html += f"""
                <form
                    action="/post/{post_id}/save"
                    method="post"
                >
                    <textarea
                        name="post_text"
                        rows="12"
                        style="width:100%; box-sizing:border-box;
                               padding:12px; font-size:15px;"
                    >{content}</textarea>

                    <p>
                        <button
                            type="submit"
                            name="action"
                            value="save"
                        >
                            Сохранить
                        </button>

                        <button
                            type="submit"
                            name="action"
                            value="ready"
                        >
                            Готово
                        </button>
                    </p>
                </form>
                """

            else:
                # Готовые и опубликованные посты показываем без формы редактирования.
                blocks_html += (
                    f'<div style="white-space:pre-line;">'
                    f'{content}'
                    f'</div>'
                )

        # Ссылка на источник

        elif block_type == "source":
            url = escape(block.get("url") or "", quote=True)

            if url:
                blocks_html += f"""
                <p>
                    Источник:
                    <a
                        href="{url}"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        Открыть оригинал
                    </a>
                </p>
                """

    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>{title} — Channel Factory</title>
        <link rel="stylesheet" href="/static/style.css">
    </head>
    <body>
        <main>
            <p><a href="/posts">← К публикациям</a></p>

            <section class="panel">
                <h2>{title}</h2>

                <p>
                    <strong>Статус:</strong> {status}
                </p>

                <hr>

                {blocks_html}
            </section>
        </main>
    </body>
    </html>
    """


# --- Сохранение и утверждение черновика ---
@app.post("/post/{post_id}/save")
def save_post(
    post_id: str,
    post_text: str = Form(...),
    action: str = Form(...),
):
    """Сохранить текст черновика или перевести его в готовые публикации."""

    if action not in ("save", "ready"):
        return HTMLResponse(
            content="Недопустимое действие",
            status_code=400,
        )

    # Сохранить: остаётся черновиком.
    # Готово: становится готовым к публикации.
    status = "ready" if action == "ready" else "draft"

    try:
        update_post(
            post_id=post_id,
            post_text=post_text,
            status=status,
        )

    except ValueError as error:
        return HTMLResponse(
            content=f"<h1>{escape(str(error))}</h1>",
            status_code=400,
        )

    return RedirectResponse(
        url=f"/post/{post_id}",
        status_code=303,
    )


# Публикация и подтверждение вынесены в publication_routes.py.
# Старые URL используют тот же сервис и журнал, что и кабинет.
