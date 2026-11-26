"""olymp-extract: льготы из документа вуза в единый JSON (без ИИ).

    olymp-extract --url https://pk.mpei.ru/docs/app2_26.pdf --university "НИУ «МЭИ»"
    olymp-extract --from-gold            # все документы эталона data/eval/extraction

Результат — data/extracted/<имя>.json; проверка: olymp-eval-extract --gold data/eval/extraction --pred data/extracted
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import unquote, urlsplit

from olymp_domain.extraction import ExtractionError, load_dir

from olymp_workers.ai.documents import DEFAULT_CACHE, DocumentError, DocumentStore

from .adapters import pick
from .build import extract
from .layout import load


def slug(url: str) -> str:
    path = unquote(urlsplit(url).path).rsplit("/", 1)[-1] or urlsplit(url).netloc
    name = re.sub(r"\.(pdf|xlsx)$", "", path, flags=re.IGNORECASE)
    return re.sub(r"[^\w-]+", "-", name, flags=re.UNICODE).strip("-").lower()[:80] or "document"


def run_one(
    store: DocumentStore,
    url: str,
    university: str,
    out: Path,
    name: str,
    *,
    campaign: int | None = None,
    title: str = "",
) -> str:
    loaded = load(url, store.raw(url))
    adapter = pick(loaded, lambda link: store.get(link).pages)
    result = extract(loaded, university=university, campaign=campaign, title=title, adapter=adapter)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(result.file.model_dump_json(), encoding="utf-8")
    return f"{name}: записей {len(result.file.records)}, страниц {len(result.file.document.pages)}"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="olymp-extract", description=__doc__.split("\n")[0])
    ap.add_argument("--url", help="адрес документа (PDF или xlsx)")
    ap.add_argument("--university", help="название вуза, как в эталоне")
    ap.add_argument("--campaign", type=int, help="год приёма; по умолчанию из текста документа")
    ap.add_argument("--title", default="", help="название документа")
    ap.add_argument("--from-gold", action="store_true", help="прогнать все документы эталона")
    ap.add_argument("--gold", type=Path, default=Path("data/eval/extraction"))
    ap.add_argument("--out", type=Path, default=Path("data/extracted"))
    ap.add_argument("--name", help="имя файла результата без расширения")
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--insecure", action="store_true", help="не проверять TLS при скачивании")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if bool(args.url) == args.from_gold:
        print("Нужно одно из: --url с --university, либо --from-gold.", file=sys.stderr)
        return 2
    if args.url and not args.university:
        print("С --url нужно --university.", file=sys.stderr)
        return 2
    jobs: list[tuple[str, str, str, int | None, str]] = []
    if args.from_gold:
        try:
            gold = load_dir(args.gold)
        except ExtractionError as exc:
            print(exc, file=sys.stderr)
            return 2
        jobs = [
            (name, f.document.url, f.document.university, args.campaign, f.document.title)
            for name, f in gold.items()
        ]
    else:
        jobs = [(args.name or slug(args.url), args.url, args.university, args.campaign, args.title)]
    store = DocumentStore(args.cache_dir, insecure=args.insecure)
    failed = 0
    try:
        for name, url, university, campaign, title in jobs:
            try:
                print(
                    run_one(store, url, university, args.out, name, campaign=campaign, title=title)
                )
            except DocumentError as exc:
                failed += 1
                print(f"{name}: {exc}", file=sys.stderr)
    finally:
        store.close()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
