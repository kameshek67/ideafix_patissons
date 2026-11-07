"""Карточка вуза в ответах API — общая для модулей поиска и «Моих дипломов»."""

from typing import Any

UNIVERSITY_FIELDS = """u.id AS university_id, u.name AS university,
                       u.short_name AS university_short, u.region, u.city,
                       u.note AS university_note, u.site_url, u.docs_url, u.docs_title,
                       u.region_group"""


def university_of(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["university_id"],
        "name": row["university"],
        "short_name": row["university_short"],
        "region": row["region"],
        "city": row["city"],
        "note": row["university_note"],
        "site_url": row["site_url"],
        "docs_url": row["docs_url"],
        "docs_title": row["docs_title"],
        "region_group": row["region_group"],
    }
