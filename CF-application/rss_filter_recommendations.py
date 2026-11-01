"""rss_filter_recommendations.py — заменяемый источник подсказок по рубрикам.

Возвращает только названия вариантов. Ни правила, ни выбор пользователя не меняет.
Текущая реализация использует прежнее совпадение слов, без ИИ.
"""
from rss_filter_config import suggestion


def recommend(project, categories):
    proposal = suggestion(project, categories)
    return proposal['categories'] if proposal else []
