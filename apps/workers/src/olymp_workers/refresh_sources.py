"""
Обновление ссылок на документы вузов.

    olymp-refresh-sources            # обойти страницы и обновить таблицу документов
    olymp-refresh-sources --dry-run  # только показать, что нашлось
    olymp-refresh-sources --only кфу # один вуз
    python -m olymp_workers.tasks refresh-sources   # то же, но фоновой задачей (Dramatiq)

Зачем: прямая ссылка на PDF живёт один сезон, адрес раздела — годами. В
`university_pages.py` руками поддерживается только страница, а конкретные файлы
скрипт находит на ней сам и кладёт в таблицу `university_documents`. Раз в год
достаточно запустить этот скрипт — ссылки обновятся без ручной работы.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import time
import urllib.parse as up
import urllib.request as request
from pathlib import Path

import psycopg
from olymp_db.session import database_url, psycopg_dsn
from olymp_domain.textutils import clean_text, squash

from .tls import is_tls_error, is_web_url, web_context
from .university_pages import DOCUMENT_KEYWORDS, PAGES, Page

DATA_DIR = Path(os.environ.get("OLYMP_DATA_DIR", Path(__file__).resolve().parents[4] / "data"))
# кэш найденных файлов: olymp-ingest подхватывает его при пересборке базы,
# поэтому обход сайтов нужен не после каждой сборки, а раз в сезон
CACHE_PATH = os.environ.get("SOURCES_CACHE", str(DATA_DIR / "university_documents.json"))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122 Safari/537.36"
)
RE_LINK = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
RE_TAG = re.compile(r"<[^>]+>")
RE_DOC = re.compile(r"\.(pdf|docx?|xlsx?)($|[?#])", re.IGNORECASE)
# ВШЭ раздаёт приложения без расширения — по адресу вида /mirror/pubs/share/123
RE_DOC_EXTRA = re.compile(r"/pubs/share/\d+", re.IGNORECASE)

# проверка TLS с сертификатом Минцифры (T-078); --insecure заменяет контекст на непроверяющий
SSL_CTX = web_context()


def fetch(url: str, timeout: int = 30) -> tuple[object, str, str, str]:
    """-> (status, content-type, тело html, конечный url)"""
    last: object = "?"
    for _ in range(2):
        try:
            req = request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
            with request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                ctype = resp.headers.get("Content-Type", "")
                body = resp.read(1_500_000).decode("utf-8", "ignore") if "html" in ctype else ""
                return resp.status, ctype, body, resp.url
        except Exception as exc:
            if is_tls_error(exc):
                return "TLS", "", "", url  # повтор не поможет: сертификат не проходит проверку
            last = getattr(exc, "code", None) or type(exc).__name__
            if last == 403:
                return 403, "", "", url
    return last, "", "", url


def documents_on_page(html: str, base_url: str) -> list[tuple[str, str]]:
    """Ссылки на файлы, подписи которых похожи на документы об олимпиадах и приёме."""
    found: dict[str, str] = {}
    for href, inner in RE_LINK.findall(html):
        label = clean_text(RE_TAG.sub(" ", inner))
        url = up.urljoin(base_url, href.strip())
        # javascript:…/x.pdf и data:…pdf проходят регулярку по расширению — только http(s)
        if not is_web_url(url):
            continue
        if not (RE_DOC.search(url) or RE_DOC_EXTRA.search(url)):
            continue
        haystack = (label + " " + up.unquote(url)).lower().replace("ё", "е")
        if not any(word.replace("ё", "е") in haystack for word in DOCUMENT_KEYWORDS):
            continue
        found.setdefault(url, label or "Документ")
    # сначала то, что прямо про олимпиады
    items = [(title, url) for url, title in found.items()]
    items.sort(key=lambda item: 0 if "олимпиад" in (item[0] + item[1]).lower() else 1)
    return items[:12]


def match_universities(conn: psycopg.Connection) -> list[tuple[int, str, str, Page]]:
    """Сопоставляет вузы из базы со страницами справочника."""
    out = []
    for uid, name in conn.execute("SELECT id, name FROM universities ORDER BY name").fetchall():
        key = squash(name)
        page = next((p for part, p in PAGES.items() if part in key), None)
        if page:
            out.append((uid, name, key, page))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Обновить ссылки на документы вузов")
    parser.add_argument(
        "--database-url", default=database_url(), help="по умолчанию OLYMP_DATABASE_URL"
    )
    parser.add_argument("--dry-run", action="store_true", help="ничего не записывать")
    parser.add_argument("--only", default="", help="подстрока названия вуза")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="не проверять TLS-сертификаты (если сайт иначе недоступен; см. infra/certs)",
    )
    args = parser.parse_args()
    if args.insecure:
        global SSL_CTX
        SSL_CTX = web_context(insecure=True)
    return refresh(args.database_url, dry_run=args.dry_run, only=args.only)


def refresh(url: str | None = None, dry_run: bool = False, only: str = "") -> int:
    """Обходит страницы вузов; вызывается из CLI и из фоновой задачи."""
    with psycopg.connect(psycopg_dsn(url)) as conn:
        return _refresh(conn, dry_run, only)


def _refresh(conn: psycopg.Connection, dry_run: bool, only: str) -> int:
    targets = match_universities(conn)
    if only:
        needle = squash(only)
        targets = [t for t in targets if needle in t[2]]

    known = {uid for uid, _, _, _ in match_universities(conn)}
    missing = [
        name
        for uid, name in conn.execute("SELECT id, name FROM universities ORDER BY name").fetchall()
        if uid not in known
    ]

    print(f"Страниц в справочнике: {len(PAGES)} · вузов к обходу: {len(targets)}\n")

    def work(target):
        uid, name, _, page = target
        status, ctype, html, final = fetch(page.url)
        docs = documents_on_page(html, final) if html else []
        return uid, name, page, status, docs

    stamp = time.strftime("%Y-%m-%d")
    found_total = silent = 0
    cache: dict[str, dict[str, object]] = {}
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as fh:
                cache = json.load(fh)
        except Exception:
            cache = {}
    with cf.ThreadPoolExecutor(max_workers=5) as pool:
        for uid, name, page, status, docs in pool.map(work, targets):
            mark = "OK " if status == 200 else "!! "
            print(
                f"{mark}[{page.status:8s}] {name[:44]:44s} {str(status):>10}  файлов: {len(docs)}"
            )
            print(f"             {page.url[:96]}")
            for title, url in docs[:5]:
                print(f"               • {title[:58]:58s} {url[:70]}")
            if not dry_run:
                conn.execute(
                    "UPDATE universities SET docs_url=%s, docs_title=%s WHERE id=%s",
                    (page.url, page.title, uid),
                )
            if docs:
                found_total += 1
                if not dry_run:
                    with conn.cursor() as cur:
                        cur.executemany(
                            """INSERT INTO university_documents (university_id, title, url, checked_at)
                               VALUES (%s,%s,%s,%s)
                               ON CONFLICT (university_id, url) DO UPDATE
                               SET title = EXCLUDED.title, checked_at = EXCLUDED.checked_at""",
                            [(uid, title, url, stamp) for title, url in docs],
                        )
                cache[name] = {
                    "page_title": page.title,
                    "page_url": page.url,
                    "checked_at": stamp,
                    "documents": [{"title": t, "url": u} for t, u in docs],
                }
            else:
                silent += 1
    if not dry_run:
        conn.commit()
        os.makedirs(os.path.dirname(os.path.abspath(CACHE_PATH)), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"\nКэш обновлён: {os.path.abspath(CACHE_PATH)}")

    print(f"\nСтраниц с найденными файлами: {found_total}, без файлов: {silent}")
    todo = [p for p in PAGES.values() if p.status == "todo"]
    if todo:
        print(
            f"Требуют ручной проверки адреса ({len(todo)}): "
            + ", ".join(sorted({p.title.split(":")[0] for p in todo}))
        )
    if missing:
        print("\nНет страницы в справочнике (добавьте в university_pages.py):")
        for name in missing:
            print("   ", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
