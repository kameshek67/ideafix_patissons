"""
Сборщик официальных материалов олимпиад для справочного поиска.

    olymp-materials  # обойти сайты из data/olympiad_sites.json и обновить data/olympiad_materials.json

На главной странице ищем ссылки того же сайта на положения, задания и расписания,
оставляем не больше трёх каждого вида и проверяем адреса запросом HEAD (при неудаче GET).
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
from html import unescape
from pathlib import Path
from typing import cast

from olymp_domain.textutils import clean_text

from .tls import is_tls_error, is_web_url, web_context

DATA_DIR = Path(os.environ.get("OLYMP_DATA_DIR", Path(__file__).resolve().parents[4] / "data"))
SITES_FILE = "olympiad_sites.json"
MATERIALS_FILE = "olympiad_materials.json"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122 Safari/537.36"
)
TIMEOUT = 15
MAX_WORKERS = 8
PER_KIND = 3
RE_LINK = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
RE_TAG = re.compile(r"<[^>]+>")
KIND_WORDS = {
    "regulations": ("положен", "регламент", "порядок"),
    "tasks": ("задани", "задач", "архив", "прошлых лет", "разбор", "решени"),
    "schedule": ("расписани", "график", "календар", "дат"),
}

SSL_CTX = web_context()


def _host(url: str) -> str:
    host = (up.urlsplit(url).hostname or "").lower().removeprefix("www.")
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def same_site(url: str, site_url: str) -> bool:
    """Ссылка ведёт на тот же сайт или его поддомен."""
    host, base = _host(url), _host(site_url)
    return bool(base) and (host == base or host.endswith("." + base))


def parse_links(html: str, site_url: str) -> list[tuple[str, str, str]]:
    """Ссылки с главной: [(kind, title, url)], не больше PER_KIND каждого вида."""
    found: list[tuple[str, str, str]] = []
    seen: dict[str, set[str]] = {kind: set() for kind in KIND_WORDS}
    counts: dict[str, int] = {kind: 0 for kind in KIND_WORDS}
    base = up.urldefrag(site_url)[0]
    for href, inner in RE_LINK.findall(html):
        url = up.urldefrag(up.urljoin(site_url, href.strip()))[0]
        if not is_web_url(url) or url == base or not same_site(url, base):
            continue
        title = clean_text(RE_TAG.sub(" ", unescape(inner)))
        haystack = f"{title} {up.unquote(url)}".lower().replace("ё", "е")
        kind = next((k for k, words in KIND_WORDS.items() if any(w in haystack for w in words)), "")
        if not kind or url in seen[kind] or counts[kind] >= PER_KIND:
            continue
        seen[kind].add(url)
        counts[kind] += 1
        found.append((kind, title or "Материал", url))
    return found


def _request_url(url: str) -> str:
    parts = up.urlsplit(url)
    host = parts.hostname or ""
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return url
    if ascii_host == host:
        return url
    return up.urlunsplit(
        (parts.scheme, parts.netloc.replace(host, ascii_host, 1), parts.path, parts.query, "")
    )


def fetch(url: str, timeout: int = TIMEOUT) -> tuple[object, str, str, str]:
    """-> (status, content-type, html, конечный url), как в refresh_sources."""
    last: object = "?"
    for _ in range(2):
        try:
            req = request.Request(
                _request_url(url), headers={"User-Agent": UA, "Accept": "text/html,*/*"}
            )
            with request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                ctype = resp.headers.get("Content-Type", "")
                body = resp.read(1_500_000).decode("utf-8", "ignore") if "html" in ctype else ""
                return resp.status, ctype, body, resp.geturl()
        except Exception as exc:
            if is_tls_error(exc):
                return "TLS", "", "", url
            last = getattr(exc, "code", None) or type(exc).__name__
            if last == 403:
                return last, "", "", url
    return last, "", "", url


def check_link(url: str) -> bool:
    """Материал оставляем только если отвечает 200 на HEAD или GET."""
    for method in ("HEAD", "GET"):
        try:
            req = request.Request(_request_url(url), headers={"User-Agent": UA}, method=method)
            with request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as resp:
                if resp.status == 200:
                    return True
        except Exception as exc:
            if is_tls_error(exc):
                return False
    return False


def load_sites(path: Path | None = None) -> dict[str, str]:
    path = path or DATA_DIR / SITES_FILE
    data = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    return cast(dict[str, str], data["sites"])


def collect(data_dir: Path | None = None) -> int:
    data_dir = data_dir or DATA_DIR
    sites = load_sites(data_dir / SITES_FILE)
    print(f"Сайтов: {len(sites)}")

    def work(item: tuple[str, str]) -> tuple[str, list[dict[str, str]]]:
        olympiad, site = item
        status, _, page, final = fetch(site)
        if status != 200 or not page:
            print(f"!! {olympiad[:44]:44s} {site[:70]} {status}")
            return olympiad, []
        rows = [
            {"olympiad": olympiad, "kind": kind, "title": title, "url": url}
            for kind, title, url in parse_links(page, final)
            if check_link(url)
        ]
        print(f"OK {olympiad[:44]:44s} материалов: {len(rows)}")
        return olympiad, rows

    materials: list[dict[str, str]] = []
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for _, rows in pool.map(work, sites.items()):
            materials.extend(rows)
    result = {"checked": time.strftime("%Y-%m-%d"), "materials": materials}
    path = data_dir / MATERIALS_FILE
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Записано: {path} · материалов: {len(materials)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Собрать официальные материалы олимпиад")
    parser.add_argument("--insecure", action="store_true", help="не проверять TLS-сертификаты")
    args = parser.parse_args(argv)
    if args.insecure:
        global SSL_CTX
        SSL_CTX = web_context(insecure=True)
    return collect()


if __name__ == "__main__":
    sys.exit(main())
