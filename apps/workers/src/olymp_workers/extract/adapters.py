"""Адаптеры по видам таблиц; выбираются по содержимому документа, а не по названию вуза."""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

from olymp_domain.textutils import squash

from .build import Adapter
from .cells import Program
from .layout import Loaded

# «для использования особого права на прием без вступительных испытаний — по предмету,
# соответствующему профилю олимпиады … приведены в таблице 1»
RE_BVI_TABLE_ONE = re.compile(
    r"прием\s+без\s+вступительных\s+испытаний.{0,900}?приведены\s+в\s+таблице\s+1\b",
    re.IGNORECASE | re.DOTALL,
)


# «профилям республиканских олимпиад школьников Донецкой Народной Республики, Луганской Народной Республики»
RE_REPUBLIC = re.compile(
    r"республиканск\w+\s+олимпиад\w*\s+школьников\s+"
    r"((?:[А-ЯЁ]\w+\s+)+Республик\w+(?:\s*,\s*(?:[А-ЯЁ]\w+\s+)+Республик\w+)*)"
)


def republic_olympiad(text: str) -> str:
    """Название из заголовка: «Республиканские олимпиады школьников Донецкой … Республики, …»."""
    match = RE_REPUBLIC.search(" ".join(text.split()))
    return f"Республиканские олимпиады школьников {match.group(1)}" if match else ""


# МГУ называет направления без кодов; коды — в перечне КЦП того же года рядом с документом
MSU_HOST = "cpk.msu.ru"
MSU_KCP = "kcp_bak.pdf"
RE_KCP_PROGRAM = re.compile(
    r'^(\d{2}\.\d{2}\.\d{2}) \| (?:Специальность|Направление подготовки) "([^"]+)"', re.MULTILINE
)


def kcp_codes(pages: tuple[str, ...]) -> dict[str, str]:
    """Название направления (squash) -> код по перечню КЦП."""
    codes: dict[str, str] = {}
    for page in pages:
        for code, name in RE_KCP_PROGRAM.findall(page):
            codes.setdefault(squash(name), code)
    return codes


def programs_by_name(codes: dict[str, str], source: str) -> Callable[[str], list[Program]]:
    def lookup(text: str) -> list[Program]:
        name = " ".join(text.split())
        code = codes.get(squash(name))
        if code is None:
            return []
        return [
            Program(
                code, name, f"в документе указано название направления; код по перечню КЦП {source}"
            )
        ]

    return lookup


def head_text(loaded: Loaded, pages: int = 3) -> str:
    return "\n".join(page.plain for page in loaded.pages[:pages])


def msu_adapter(loaded: Loaded, kcp_pages: Callable[[str], tuple[str, ...]] | None) -> Adapter:
    kcp_url = urljoin(loaded.url, MSU_KCP)
    codes = kcp_codes(kcp_pages(kcp_url)) if kcp_pages else {}
    programs = programs_by_name(codes, urlsplit(kcp_url).netloc + urlsplit(kcp_url).path)
    first = " ".join(head_text(loaded, 1).split()).lower()
    if "соотнесение профилей" in first:
        # перечень олимпиад по направлениям: предмет — профиль, льгота не названа; ВсОШ и международные дают БВИ
        return Adapter(
            "МГУ: соответствие олимпиад направлениям",
            programs=programs,
            benefit="bvi",
            benefit_note="тип льготы в документе не указан",
            roles={"ege_subject": "profile"},
        )
    return Adapter("МГУ: особые права по факультетам", programs=programs, olympiad_lists=True)


def pick(loaded: Loaded, kcp_pages: Callable[[str], tuple[str, ...]] | None = None) -> Adapter:
    """kcp_pages(url) — текст страниц соседнего документа (перечень КЦП МГУ); без него МГУ не разбирается."""
    if urlsplit(loaded.url).netloc == MSU_HOST:
        return msu_adapter(loaded, kcp_pages)
    head = " ".join(head_text(loaded).split())
    if RE_BVI_TABLE_ONE.search(head):
        return Adapter(
            "таблица профилей для БВИ по учебным годам", benefit="bvi", latest_period_only=True
        )
    if RE_REPUBLIC.search(head):
        return Adapter("республиканские олимпиады", olympiad=republic_olympiad)
    return Adapter()
