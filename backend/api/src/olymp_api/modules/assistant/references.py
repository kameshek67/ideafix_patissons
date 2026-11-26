"""Справочный поиск для помощника: фрагменты документов, карточек и правил из таблицы passages.

Полнотекстовый поиск PostgreSQL (russian, websearch_to_tsquery, ts_rank_cd), без эмбеддингов.
Фрагменты — справка: что за олимпиада, как проходит этап, что говорит закон. Факты о льготах
берутся только из базы льгот и проверяются кодом.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import Row, fetch_all

MAX_LIMIT = 5
PER_SOURCE = 2  # фрагментов одного источника в выдаче: соседние куски перекрываются
MAX_QUERY = 300
SOURCE_LABELS = {
    "university_document": "документ вуза",
    "olympiad_card": "карточка олимпиады",
    "admission_rule": "правила приёма и закон",
    "olympiad_material": "материалы олимпиады",
}

# строгий запрос: все слова; мягкий — любое из слов (вопрос ученика длиннее, чем фраза в тексте)
_SQL = """
    SELECT source_type, title, url, page, chunk, body,
           ts_rank_cd(document, q.query, 32) AS rank
    FROM passages, (SELECT {query} AS query) q
    WHERE document @@ q.query
    ORDER BY rank DESC, id
    LIMIT :limit
"""
_STRICT = "websearch_to_tsquery('russian', :q)"
_LOOSE = "replace(websearch_to_tsquery('russian', :q)::text, ' & ', ' | ')::tsquery"


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
    """Лучшие фрагменты по запросу; пусто — в справочнике этого нет. Сначала запрос со всеми
    словами, если ничего — с любым из них."""
    query = " ".join(query.split())[:MAX_QUERY]
    limit = max(1, min(limit, MAX_LIMIT))
    if not query:
        return []
    rows: list[Row] = []
    for form in (_STRICT, _LOOSE):
        rows = await fetch_all(session, _SQL.format(query=form), {"q": query, "limit": limit * 4})
        if rows:
            break
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
