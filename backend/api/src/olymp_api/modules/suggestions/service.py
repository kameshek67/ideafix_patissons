import urllib.parse as up

from fastapi import HTTPException
from olymp_domain.urls import is_personal_list, normalize_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import fetch_all, fetch_one

# общие хранилища и соцсети: домен «известен», но вузу не принадлежит
SHARED_HOSTS = frozenset(
    {
        "google.com",
        "yandex.ru",
        "yadi.sk",
        "mail.ru",
        "vk.com",
        "t.me",
        "dropbox.com",
        "github.com",
        "wikipedia.org",
    }
)
RU_TLDS = (".ru", ".xn--p1ai")
FILE_SUFFIXES = (".pdf", ".xlsx", ".xls")


def site_of(host: str) -> str:
    """Сайт без поддомена: последние две метки адреса."""
    return ".".join(host.lower().rstrip(".").split(".")[-2:])


def host_of(url: str) -> str:
    return (up.urlsplit(url).hostname or "").lower()


async def known_sites(session: AsyncSession, university: str) -> set[str]:
    """Сайты, где у вуза уже есть документы: страницы справочника, источники и принятые файлы."""
    rows = await fetch_all(
        session,
        """SELECT d.url FROM university_documents d JOIN universities u ON u.id = d.university_id
           WHERE u.name = :u
           UNION ALL SELECT docs_url FROM universities WHERE name = :u
           UNION ALL SELECT site_url FROM universities WHERE name = :u
           UNION ALL SELECT url FROM sources WHERE university = :u
           UNION ALL SELECT document_url FROM document_records WHERE university = :u""",
        {"u": university},
    )
    sites = {site_of(host_of(row["url"])) for row in rows if row["url"]}
    return {site for site in sites if site and site not in SHARED_HOSTS}


async def suggest(
    session: AsyncSession, url: str, university: str, comment: str, max_user_id: int | None
) -> bool:
    """Ставит ссылку на разбор. True — принята, False — такая ссылка у нас уже есть."""
    try:
        url = normalize_url(url)
    except ValueError:
        raise HTTPException(422, "Ссылка должна начинаться с http:// или https://") from None
    parts = up.urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.username or parts.password or "." not in host:
        raise HTTPException(422, "Нужна обычная ссылка на сайт вуза")
    university = " ".join(university.split())
    if len(university) < 2:
        raise HTTPException(422, "Укажи вуз")
    if is_personal_list("", url):
        raise HTTPException(422, "Это похоже на список людей, такие ссылки мы не принимаем")

    known = await fetch_one(
        session,
        """SELECT 1 AS found FROM sources WHERE url = :url
           UNION ALL SELECT 1 FROM university_documents WHERE url = :url
           UNION ALL SELECT 1 FROM document_records WHERE document_url = :url LIMIT 1""",
        {"url": url},
    )
    if known:
        return False

    # регистр в базе не нормализован (колонки в collation C): сравниваем в Python
    wanted = university.casefold()
    for row in await fetch_all(session, "SELECT name, short_name FROM universities ORDER BY id"):
        if wanted in (row["name"].casefold(), row["short_name"].casefold()):
            university = row["name"]
            break
    site = site_of(host)
    if site in SHARED_HOSTS or not (
        host.endswith(RU_TLDS) or site in await known_sites(session, university)
    ):
        raise HTTPException(
            422, "Нужна ссылка с сайта вуза: страница приёма или документ про олимпиады"
        )

    kind = "document" if parts.path.lower().endswith(FILE_SUFFIXES) else "page"
    source = await fetch_one(
        session,
        """INSERT INTO sources (university, url, kind, added_by) VALUES (:u, :url, :kind, 'user')
           ON CONFLICT (url) DO NOTHING RETURNING id""",
        {"u": university, "url": url, "kind": kind},
    )
    if source is None:  # успели добавить в параллельном запросе
        await session.rollback()
        return False
    await session.execute(
        text(
            """INSERT INTO source_jobs (source_id, origin, comment, max_user_id)
               VALUES (:s, 'user', :comment, :user)"""
        ),
        {"s": source["id"], "comment": comment.strip(), "user": max_user_id},
    )
    await session.commit()
    return True
