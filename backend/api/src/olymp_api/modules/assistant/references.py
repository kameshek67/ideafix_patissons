"""Справочный поиск для помощника: фрагменты документов, карточек и правил из таблицы passages.

Полнотекстовый поиск PostgreSQL (russian, websearch_to_tsquery), ранг — доля слов запроса с весом
по редкости, без эмбеддингов.
Фрагменты — справка: что за олимпиада, как проходит этап, что говорит закон. Факты о льготах
берутся только из базы льгот и проверяются кодом.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import fetch_all

MAX_LIMIT = 5
PER_SOURCE = 2  # фрагментов одного источника в выдаче: соседние куски перекрываются
MAX_QUERY = 300
MIN_COVERAGE = 0.45  # ниже — в справочнике по сути ничего нет, фрагменты случайные
SOURCE_LABELS = {
    "university_document": "документ вуза",
    "olympiad_card": "карточка олимпиады",
    "admission_rule": "правила приёма и закон",
    "olympiad_material": "материалы олимпиады",
}

# Кандидаты — фрагменты с любым из слов запроса. ts_rank_cd не знает, какие слова редкие: вопрос
# ученика полон слов вроде «олимпиада», «поступление», и они заглушали редкое («БВИ», «Курчатов»).
# Поэтому ранг — доля найденных слов запроса, взвешенных редкостью: ln(1 + всего / фрагментов со словом).
# 1 — в фрагменте есть все слова, 0.5 — слова на половину веса запроса.
_SQL = """
    WITH q AS MATERIALIZED (
        SELECT replace(websearch_to_tsquery('russian', :q)::text, ' & ', ' | ')::tsquery AS query
    ), terms AS MATERIALIZED (
        SELECT ('''' || m[1] || '''')::tsquery AS term
        FROM q, regexp_matches(q.query::text, '''([^'']+)''', 'g') AS m
    ), weights AS MATERIALIZED (
        SELECT term, ln(1 + (SELECT count(*) FROM passages)::float
                        / greatest(1, (SELECT count(*) FROM passages p WHERE p.document @@ terms.term))
                   ) AS weight
        FROM terms
    ), found AS MATERIALIZED (
        SELECT p.* FROM passages p, q WHERE p.document @@ q.query
    )
    SELECT f.source_type, f.title, f.url, f.page, f.chunk, f.body,
           (SELECT coalesce(sum(weight), 0) FROM weights WHERE f.document @@ weights.term)
               / (SELECT sum(weight) FROM weights) AS rank
    FROM found f
    ORDER BY rank DESC, f.id
    LIMIT :limit
"""


@dataclass(frozen=True)
class Reference:
    source_type: str
    title: str
    url: str
    page: int | None
    text: str
    rank: float

    @property
    def label(self) -> str:
        return SOURCE_LABELS.get(self.source_type, self.source_type)


async def search_passages(
    session: AsyncSession, query: str, limit: int = MAX_LIMIT
) -> list[Reference]:
    """Лучшие фрагменты по запросу; пусто — в справочнике этого нет (совпала малая часть слов)."""
    query = " ".join(query.split())[:MAX_QUERY]
    limit = max(1, min(limit, MAX_LIMIT))
    if not query:
        return []
    rows = await fetch_all(session, _SQL, {"q": query, "limit": limit * 4})
    rows = [row for row in rows if row["rank"] >= MIN_COVERAGE]
    taken: dict[tuple[str, str], int] = {}
    found: list[Reference] = []
    for row in rows:
        key = (row["title"], row["url"])
        if taken.get(key, 0) >= PER_SOURCE:
            continue
        taken[key] = taken.get(key, 0) + 1
        found.append(
            Reference(
                row["source_type"],
                row["title"],
                row["url"],
                row["page"],
                row["body"],
                float(row["rank"]),
            )
        )
        if len(found) == limit:
            break
    return found
