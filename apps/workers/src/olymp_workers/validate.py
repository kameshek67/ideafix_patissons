"""
Проверка качества собранной базы.

    olymp-validate                 # быстрые проверки по БД
    olymp-validate --check-links   # плюс HTTP-проверка всех источников

Скрипт не правит данные, а показывает, где разбор мог пойти не так:
пустые ссылки, строки без олимпиады, дубликаты, подозрительные профили.
Код возврата 1, если есть ошибки уровня ERROR.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import ssl
import sys
import urllib.request as request

import psycopg
from olymp_db.session import database_url, psycopg_dsn

from .university_pages import PAGES

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122 Safari/537.36"
)


class Report:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []

    def add(self, level: str, title: str, detail: str = "") -> None:
        self.items.append((level, title, detail))

    def check(self, condition: bool, level: str, title: str, detail: str = "") -> None:
        self.add(level if condition else INFO, title, detail)

    @property
    def errors(self) -> int:
        return sum(1 for level, _, _ in self.items if level == ERROR)

    def print(self) -> None:
        icons = {ERROR: "✗", WARN: "!", INFO: "✓"}
        for level, title, detail in self.items:
            print(f" {icons[level]} [{level:5s}] {title}")
            if detail:
                for line in detail.splitlines():
                    print(f"            {line}")


def validate(conn: psycopg.Connection, check_links: bool) -> Report:
    r = Report()

    # без параметров psycopg не разбирает %, поэтому LIKE 'http%' пишется как есть
    def q(sql, *p):
        return conn.execute(sql, p or None).fetchall()

    def one(sql, *p):
        return conn.execute(sql, p or None).fetchone()[0]

    # --- источники ------------------------------------------------------
    no_url = one("SELECT COUNT(*) FROM programs WHERE source_url = ''")
    r.check(
        no_url > 0,
        ERROR,
        f"Направлений без ссылки на источник: {no_url}",
        "\n".join(
            f"{name} — {cnt}"
            for name, cnt in q(
                """SELECT u.name, COUNT(*) FROM programs p
                   JOIN universities u ON u.id = p.university_id
                   WHERE p.source_url = '' GROUP BY u.id ORDER BY 2 DESC LIMIT 5"""
            )
        ),
    )

    broken = q("""SELECT DISTINCT source_url FROM programs
                  WHERE source_url <> '' AND source_url NOT LIKE 'http%'""")
    r.check(
        bool(broken),
        ERROR,
        f"Ссылки не похожи на URL: {len(broken)}",
        "\n".join(row[0][:100] for row in broken[:5]),
    )

    spaced = q("SELECT DISTINCT source_url FROM programs WHERE source_url LIKE '% %'")
    r.check(
        bool(spaced),
        ERROR,
        f"URL с пробелами (сломаются в браузере): {len(spaced)}",
        "\n".join(row[0][:100] for row in spaced[:5]),
    )

    # --- связи «льгота ↔ олимпиада» -------------------------------------
    rows_total = one("SELECT COUNT(*) FROM benefits WHERE layer IN ('detailed','derived')")
    rows_unlinked = one(
        """SELECT COUNT(*) FROM benefits b WHERE b.layer IN ('detailed','derived')
           AND NOT EXISTS (SELECT 1 FROM benefit_olympiads bo WHERE bo.benefit_id=b.id)"""
    )
    share = rows_unlinked / rows_total * 100 if rows_total else 0
    r.check(
        share > 5,
        WARN,
        f"Строк таблиц без опознанной олимпиады: {rows_unlinked} из {rows_total} ({share:.1f}%)",
        "\n".join(
            f"{name}: {cnt}"
            for name, cnt in q(
                """SELECT u.name, COUNT(*) FROM benefits b
                   JOIN programs p ON p.id=b.program_id JOIN universities u ON u.id=p.university_id
                   WHERE b.layer IN ('detailed','derived')
                     AND NOT EXISTS (SELECT 1 FROM benefit_olympiads bo WHERE bo.benefit_id=b.id)
                   GROUP BY u.id ORDER BY 2 DESC LIMIT 5"""
            )
        ),
    )

    # --- дубликаты ------------------------------------------------------
    # дубль — это полностью совпадающая строка таблицы: та же олимпиада, профиль,
    # уровень, роль и класс. Разные классы или роли — это разные условия, не дубли.
    # дубль — строка, у которой совпадает всё, что видит пользователь в таблице
    DUP_KEY = """b.program_id, b.benefit_type, bo.olympiad_id, b.olympiad_profile,
                 b.olympiad_subject, b.level, b.winner_role, b.grade,
                 b.confirm_subject, b.min_ege"""
    dupes = one(f"""SELECT COALESCE(SUM(c - 1), 0) FROM (
                      SELECT COUNT(*) AS c FROM benefits b
                      JOIN benefit_olympiads bo ON bo.benefit_id = b.id
                      WHERE b.layer IN ('detailed','derived')
                      GROUP BY {DUP_KEY} HAVING COUNT(*) > 1) d""")
    r.check(
        dupes > 0,
        WARN,
        f"Лишних (полностью одинаковых) строк в таблицах: {dupes}",
        "\n".join(
            f"{u}: {c}"
            for u, c in q(
                f"""SELECT u.name, SUM(d.c - 1) FROM (
                      SELECT b.program_id AS pid, COUNT(*) AS c FROM benefits b
                      JOIN benefit_olympiads bo ON bo.benefit_id = b.id
                      WHERE b.layer IN ('detailed','derived')
                      GROUP BY {DUP_KEY} HAVING COUNT(*) > 1) d
                    JOIN programs p ON p.id = d.pid JOIN universities u ON u.id = p.university_id
                    GROUP BY u.id ORDER BY 2 DESC LIMIT 5"""
            )
        ),
    )

    # --- качество справочника олимпиад ----------------------------------
    # разовые вузовские мероприятия (ИД, фаст-трек) упоминаются один раз по своей природе —
    # подозрительны только редкие записи из перечневых листов
    rare = q("""SELECT o.short_name, o.mentions FROM olympiads o
                WHERE o.mentions <= 2 AND NOT EXISTS (
                    SELECT 1 FROM benefit_olympiads bo JOIN benefits b ON b.id = bo.benefit_id
                    WHERE bo.olympiad_id = o.id
                      AND b.benefit_type IN ('ИД (доп. баллы)', 'Фаст-трек'))
                ORDER BY o.mentions""")
    r.check(
        len(rare) > 15,
        WARN,
        f"Редких олимпиад из перечневых листов: {len(rare)}",
        "возможны обрывки строк из PDF; проверьте список:\n"
        + ", ".join(f"{n} ({m})" for n, m in rare[:12]),
    )

    long_names = q("SELECT short_name FROM olympiads WHERE length(short_name) > 46")
    r.check(
        bool(long_names),
        WARN,
        f"Слишком длинные короткие названия олимпиад: {len(long_names)}",
        "\n".join(row[0][:90] for row in long_names[:5]),
    )

    # --- профили --------------------------------------------------------
    weird = q("""SELECT o.short_name, pr.name, pr.mentions FROM olympiad_profiles pr
                 JOIN olympiads o ON o.id = pr.olympiad_id
                 WHERE length(pr.name) > 90 ORDER BY pr.mentions DESC LIMIT 5""")
    r.check(
        bool(weird),
        INFO,
        f"Очень длинные названия профилей: {len(weird)}",
        "\n".join(f"{o}: {p[:70]}… ({m})" for o, p, m in weird),
    )

    # --- покрытие -------------------------------------------------------
    empty_programs = q("""SELECT u.name, COUNT(*) FROM programs p
                          JOIN universities u ON u.id=p.university_id
                          WHERE NOT EXISTS (SELECT 1 FROM benefits b
                                            WHERE b.program_id=p.id AND b.layer IN ('detailed','derived'))
                          GROUP BY u.id ORDER BY 2 DESC""")
    total_empty = sum(cnt for _, cnt in empty_programs)
    r.check(
        total_empty > 0,
        INFO,
        f"Направлений без таблицы (только текстовые правила): {total_empty}",
        "\n".join(f"{name}: {cnt}" for name, cnt in empty_programs[:5]),
    )

    derived = one("SELECT COUNT(*) FROM benefits WHERE layer='derived'")
    r.add(
        INFO,
        f"Строк, выведенных из правил «по профилю»: {derived} "
        f"({derived / rows_total * 100:.0f}% таблиц)",
        "это не цитаты из документов, а вывод по справочнику профилей",
    )

    # --- ссылки сетью ---------------------------------------------------
    if check_links:
        urls = [
            row[0]
            for row in q("SELECT DISTINCT source_url FROM programs WHERE source_url LIKE 'http%'")
        ]
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        def probe(url: str):
            # сайты вузов часто отвечают медленно, поэтому две попытки
            last = "?"
            for _attempt in range(2):
                for method in ("HEAD", "GET"):
                    try:
                        req = request.Request(url, headers={"User-Agent": UA}, method=method)
                        with request.urlopen(req, timeout=30, context=ctx) as resp:
                            return url, resp.status, resp.headers.get("Content-Type", "")
                    except Exception as exc:
                        last = getattr(exc, "code", None) or type(exc).__name__
                        if last == 403:  # защита от ботов, ссылка рабочая
                            return url, 403, ""
            return url, last, ""

        with cf.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(probe, urls))
        dead = [(u, s) for u, s, _ in results if s not in (200, 403)]
        guarded = [u for u, s, _ in results if s == 403]
        r.check(
            bool(dead),
            ERROR,
            f"Источники не открылись: {len(dead)} из {len(urls)}",
            "\n".join(f"{status}: {url[:85]}" for url, status in dead),
        )
        if guarded:
            r.add(
                INFO,
                f"Отвечают 403 (антибот, в браузере открываются): {len(guarded)}",
                "\n".join(u[:85] for u in guarded),
            )

        # страницы разделов тоже проверяем: именно они показываются пользователю.
        # Часть вузовских сайтов отвечает только браузеру — для них в справочнике
        # стоит статус guarded, и молчание сайта не считается ошибкой.
        guarded = {p.url for p in PAGES.values() if p.status == "guarded"}
        pages = [
            row[0] for row in q("SELECT DISTINCT docs_url FROM universities WHERE docs_url <> ''")
        ]
        with cf.ThreadPoolExecutor(max_workers=4) as pool:
            page_results = list(pool.map(probe, pages))
        dead = [(u, s) for u, s, _ in page_results if s not in (200, 403) and u not in guarded]
        silent = [(u, s) for u, s, _ in page_results if s not in (200, 403) and u in guarded]
        r.check(
            bool(dead),
            ERROR,
            f"Страницы вузов не открылись: {len(dead)} из {len(pages)}",
            "\n".join(f"{status}: {url[:85]}" for url, status in dead),
        )
        if silent:
            r.add(
                INFO,
                f"Не отвечают скрипту, но помечены как guarded: {len(silent)}",
                "\n".join(f"{status}: {url[:85]}" for url, status in silent),
            )
    return r


def validate_sources(conn: psycopg.Connection, r: Report) -> None:
    """Проверки новой системы источников: страница раздела + файлы с неё."""

    def q(sql, *p):
        return conn.execute(sql, p or None).fetchall()

    def one(sql, *p):
        return conn.execute(sql, p or None).fetchone()[0]

    no_page = q("SELECT name FROM universities WHERE docs_url = '' ORDER BY name")
    r.check(
        bool(no_page),
        ERROR,
        f"Вузов без страницы приёмной комиссии: {len(no_page)}",
        "\n".join(n for (n,) in no_page[:10])
        + "\n(добавьте запись в apps/workers/src/olymp_workers/university_pages.py)",
    )

    todo = [p for p in PAGES.values() if p.status == "todo"]
    r.check(
        bool(todo),
        WARN,
        f"Страниц со статусом todo: {len(todo)} из {len(PAGES)}",
        "\n".join(f"{p.title[:48]:48s} {p.url[:60]}" for p in todo),
    )

    total_docs = one("SELECT COUNT(*) FROM university_documents")
    with_docs = one("""SELECT COUNT(DISTINCT university_id) FROM university_documents""")
    total_unis = one("SELECT COUNT(*) FROM universities")
    r.add(
        INFO,
        f"Файлов найдено автоматически: {total_docs} у {with_docs} из {total_unis} вузов",
        "остальным показывается только страница раздела — это нормально, "
        "если вуз публикует правила текстом на странице",
    )

    stale = q("""SELECT u.name, MIN(d.checked_at) FROM university_documents d
                 JOIN universities u ON u.id = d.university_id
                 GROUP BY u.id
                 HAVING MIN(d.checked_at) < to_char(CURRENT_DATE - 180, 'YYYY-MM-DD')""")
    r.check(
        bool(stale),
        WARN,
        f"Ссылки не обновлялись более полугода: {len(stale)}",
        "\n".join(f"{n}: {d}" for n, d in stale[:8]) + "\nзапустите: olymp-refresh-sources",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка качества базы")
    parser.add_argument(
        "--database-url", default=database_url(), help="по умолчанию OLYMP_DATABASE_URL"
    )
    parser.add_argument("--check-links", action="store_true", help="проверить источники по сети")
    args = parser.parse_args()

    with psycopg.connect(psycopg_dsn(args.database_url)) as conn:
        conn.read_only = True
        print(f"Проверяю {conn.info.dbname}@{conn.info.host}\n")
        report = validate(conn, args.check_links)
        validate_sources(conn, report)
    report.print()
    print(f"\nОшибок: {report.errors}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
