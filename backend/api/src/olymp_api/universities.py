"""Карточка вуза в ответах API — общая для модулей поиска и «Моих дипломов»."""

from typing import Any

# откуда цифры набора олимпиадников (подпись под ними в интерфейсе)
INTAKE_SOURCE = "Мониторинг эффективности вузов"

# последний год, за который у вуза есть данные панели; нет строк — NULL
INTAKE_FIELD = """(SELECT jsonb_build_object(
                          'year', i.year, 'olympiad_students', i.olympiad_students,
                          'olympiad_share', i.olympiad_share,
                          'avg_score_budget', i.avg_score_budget)
                   FROM university_intake i WHERE i.university_id = u.id
                   ORDER BY i.year DESC LIMIT 1) AS intake"""

UNIVERSITY_FIELDS = f"""u.id AS university_id, u.name AS university,
                       u.short_name AS university_short, u.region, u.city,
                       u.note AS university_note, u.site_url, u.docs_url, u.docs_title,
                       u.region_group, {INTAKE_FIELD}"""


def intake_of(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Набор олимпиадников вуза за последний год панели вместе с источником."""
    return {**value, "source": INTAKE_SOURCE} if value else None


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
        "intake": intake_of(row.get("intake")),
    }
