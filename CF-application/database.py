import os

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

db = create_client(SUPABASE_URL, SUPABASE_KEY)


def count_materials():
    result = (
        db.table("cf_materials")
        .select("id", count="exact")
        .limit(1)
        .execute()
    )
    return result.count

def save_materials(articles):
    result = (
        db.table("cf_materials")
        .upsert(
            articles,
            on_conflict="source_id,url"
        )
        .execute()
    )
    return len(result.data or [])

def get_materials(limit=10):
    result = (
        db.table("cf_materials")
        .select("id,title,url,published_at")
        .order("published_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data

def get_material(material_id):
    result = (
        db.table("cf_materials")
        .select("*")
        .eq("id", material_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None

def save_article_content(material_id, article):
    content = {
        "text": article["text"],
        "image_url": article["image_url"]
    }

    result = (
        db.table("cf_materials")
        .update({"content": content})
        .eq("id", material_id)
        .execute()
    )

    return result.data

def create_post(material_id, title, blocks):
    result = db.rpc(
        "cf_save_material_draft",
        {
            "p_material_id": material_id,
            "p_title": title,
            "p_blocks": blocks
        }
    ).execute()

    return result.data

def get_posts(status=None, limit=100):
    query = (
        db.table("cf_posts")
        .select("id,title,status,updated_at")
        .order("updated_at", desc=True)
        .limit(limit)
    )

    if status in ("draft", "ready", "published"):
        query = query.eq("status", status)

    result = query.execute()
    return result.data or []

def get_post(post_id):
    result = (
        db.table("cf_posts")
        .select("*")
        .eq("id", post_id)
        .limit(1)
        .execute()
    )

    return result.data[0] if result.data else None

def update_post(post_id, post_text, status="draft"):
    if status not in ("draft", "ready"):
        raise ValueError("Недопустимый статус")

    post = get_post(post_id)

    if not post or post["status"] != "draft":
        raise ValueError("Редактировать можно только черновик")

    blocks = post.get("blocks") or []

    for block in blocks:
        if block.get("type") == "text":
            block["content"] = post_text

    result = (
        db.table("cf_posts")
        .update({
            "blocks": blocks,
            "status": status
        })
        .eq("id", post_id)
        .eq("status", "draft")
        .execute()
    )

    if not result.data:
        raise ValueError("Не удалось сохранить черновик")

    return result.data[0]

def return_post_to_draft(post_id):
    result = (
        db.table("cf_posts")
        .update({"status": "draft"})
        .eq("id", post_id)
        .eq("status", "ready")
        .execute()
    )

    if not result.data:
        raise ValueError("Вернуть в черновики можно только готовую публикацию")

    return result.data[0]

if __name__ == "__main__":
    print("Подключаемся к Supabase...")
    print(f"Материалов в базе: {count_materials()}")
   