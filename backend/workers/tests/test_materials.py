"""Разбор ссылок на официальные материалы без обращения к сети."""

from pathlib import Path

from olymp_workers.materials import parse_links, same_site

FIXTURE = Path(__file__).parent / "fixtures" / "olympiad_materials.html"
SITE = "https://www.example.ru/olymp/"


def test_parse_links_groups_by_kind_and_limits_each() -> None:
    items = parse_links(FIXTURE.read_text(encoding="utf-8"), SITE)
    assert [(kind, url) for kind, _, url in items] == [
        ("regulations", "https://www.example.ru/docs/polozhenie.pdf"),
        ("regulations", "https://olymp.example.ru/reglament"),
        ("regulations", "https://example.ru/order"),
        ("tasks", "https://www.example.ru/files/tasks"),
        ("tasks", "https://www.example.ru/files/arhiv"),
        ("tasks", "https://www.example.ru/files/решения"),
        ("schedule", "https://www.example.ru/schedule"),
        ("schedule", "https://www.example.ru/grafik"),
    ]
    assert items[1][1] == "Регламент проведения"


def test_only_same_site_links() -> None:
    assert same_site("https://example.ru/a", SITE)
    assert same_site("https://olymp.example.ru/a", SITE)
    assert not same_site("https://example.org/a", SITE)
    assert not same_site("https://other.example.ru.evil/a", SITE)
