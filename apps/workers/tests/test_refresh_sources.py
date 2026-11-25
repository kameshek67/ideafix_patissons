import json
from pathlib import Path

import pytest
from olymp_workers.refresh_sources import documents_on_page, is_personal_list

DATA = Path(__file__).resolve().parents[3] / "data" / "university_documents.json"


@pytest.mark.parametrize(
    ("title", "url"),
    [
        ("Списки победителей и призеров олимпиад школьников, использующих право БВИ", "/a.pdf"),
        ("Список поступающих на бакалавриат", "/a.pdf"),
        ("Конкурсные списки 2026", "/a.pdf"),
        ("Рейтинговый список абитуриентов", "/a.pdf"),
        ("Приказ о зачислении (Бакалавриат, БВИ, 2026 г.)", "/a.pdf"),
        ("Приказ ректора от 01.08.2026 о зачислении на 1 курс", "/a.pdf"),
        ("Олимпиады БВИ", "/bac/Список_подавших_документы_БВИ_2026-07-25.pdf"),
        ("Олимпиады БВИ", "/bac/spisok_postupayushchikh.pdf"),
        ("Олимпиады", "/bac/reiting_2026.pdf"),
        ("Олимпиады", "/bac/rating-2026.pdf"),
    ],
)
def test_personal_lists_are_recognized(title: str, url: str) -> None:
    assert is_personal_list(title, url)


@pytest.mark.parametrize(
    ("title", "url"),
    [
        ("Перечень олимпиад школьников", "https://abiturient.spbu.ru/olymp.pdf"),
        ("Особенности приема поступающих из ДНР и ЛНР", "/priem/dnr.pdf"),
        ("Приказ Минобрнауки об утверждении перечня олимпиад", "/perechen.pdf"),
        ("Приказ о мерах поддержки принятых на обучение победителей олимпиад", "/a.pdf"),
        ("Особые права победителей и призеров олимпиад", "/a.pdf"),
        ("Список олимпиад, дающих право на БВИ", "/a.pdf"),
        (
            "Приоритетность вступительных испытаний при ранжировании списков поступающих",
            "/rules.pdf",
        ),
        ("Правила приема", "/operating-rules.pdf"),
    ],
)
def test_regular_documents_are_kept(title: str, url: str) -> None:
    assert not is_personal_list(title, url)


def test_crawler_skips_personal_lists() -> None:
    page = """
<a href="/bac/Список_подавших_документы_Олимпиады_БВИ.pdf">Олимпиады БВИ: списки победителей</a>
<a href="/bac/prikaz-zachislenie.pdf">Приказ о зачислении, БВИ, олимпиады</a>
<a href="/bac/olimpiady-2026.pdf">Перечень олимпиад 2026</a>
"""
    urls = [url for _, url in documents_on_page(page, "https://uni.example/priem/")]
    assert urls == ["https://uni.example/bac/olimpiady-2026.pdf"]


def test_cache_has_no_personal_lists() -> None:
    cache = json.loads(DATA.read_text(encoding="utf-8"))
    bad = [
        (name, doc["title"])
        for name, entry in cache.items()
        for doc in entry["documents"]
        if is_personal_list(doc["title"], doc["url"])
    ]
    assert not bad
