import json
from pathlib import Path

import httpx
from olymp_domain.extraction import ExtractionFile
from olymp_workers import eval_extract as ev
from olymp_workers.ai.documents import DocumentStore

SHA = "c" * 64
URL = "https://u.example/rules.pdf"
PAGE2 = "01.03.02 Высшая проба: победители и призёры, ЕГЭ информатика 75 баллов"
PAGE3 = "09.03.01 Ломоносов: призёры"


def rec(
    code: str,
    olympiad: str,
    page: int = 2,
    quote: str = PAGE2,
    source_row: int | None = None,
    **extra: object,
) -> dict:
    return {
        "university": "Вуз",
        "campaign": 2027,
        "program_code": code,
        "benefit_type": "bvi",
        "olympiad": olympiad,
        "source": {"url": URL, "sha256": SHA, "page": page, "quote": quote, "row": source_row},
        **extra,
    }


def file(records: list[dict], pages: list[int] | None = None, url: str = URL) -> ExtractionFile:
    return ExtractionFile.model_validate(
        {
            "document": {
                "university": "Вуз",
                "campaign": 2027,
                "url": url,
                "sha256": SHA,
                "pages": pages or [2],
            },
            "records": records,
        }
    )


GOLD = file(
    [
        rec(
            "01.03.02",
            "Высшая проба",
            winner_role="both",
            levels=[1],
            ege={"subjects": ["inf"], "min": 75},
        ),
        rec("01.03.02", "Ломоносов", winner_role="winner"),
        rec("01.03.02", "МОШ"),
    ]
)


def test_precision_recall_and_fields_on_matched_records() -> None:
    pred = file(
        [
            rec(
                "01.03.02",
                "ВСЕРОССИЙСКАЯ ОЛИМПИАДА ШКОЛЬНИКОВ «ВЫСШАЯ ПРОБА»",
                winner_role="both",
                levels=[1],
                ege={"subjects": ["inf"], "min": 70},
            ),
            rec("01.03.02", "Ломоносов", winner_role="prizewinner"),
            rec("01.03.02", "Лишняя олимпиада"),
        ]
    )
    results, total = ev.run({"d": GOLD}, {"d": pred})
    r = results[0]
    assert (r.gold, r.pred, r.matched) == (3, 3, 2)
    assert r.precision == 2 / 3 and r.recall == 2 / 3
    assert r.field_accuracy("winner_role") == 0.5  # Ломоносов: призёр вместо победителя
    assert r.field_accuracy("ege_min") == 0.5
    assert r.field_accuracy("ege_subjects") == 1.0
    assert r.role_wrong == 1 and not r.passes
    assert total.matched == 2


def test_hits_are_kept_per_record_and_sum_up() -> None:
    pred = file(
        [
            rec("01.03.02", "Высшая проба", winner_role="both", levels=[1]),
            rec("01.03.02", "Ломоносов", winner_role="prizewinner"),
            rec("01.03.02", "Лишняя олимпиада"),
        ]
    )
    results, total = ev.run({"d": GOLD}, {"d": pred})
    r = results[0]
    assert r.gold_hits == [True, True, False]
    assert r.pred_hits == [True, True, False]
    assert len(r.pair_fields) == r.matched == 2
    assert total.gold_hits == r.gold_hits and sum(total.pred_hits) == total.matched


def test_any_code_spread_is_not_in_pred_hits() -> None:
    gold = file([rec("*", "МОШ")])
    pred = file([rec("01.03.02", "МОШ"), rec("09.03.01", "МОШ"), rec("09.03.01", "Лишняя")])
    r = ev.run({"d": gold}, {"d": pred})[0][0]
    assert len(r.pred_hits) == r.pred == 2 and sum(r.pred_hits) == 1


def test_honest_empty_role_is_not_a_wrong_role() -> None:
    pred = file(
        [rec("01.03.02", "Ломоносов"), rec("01.03.02", "Высшая проба"), rec("01.03.02", "МОШ")]
    )
    r = ev.run({"d": GOLD}, {"d": pred})[0][0]
    assert r.role_wrong == 0
    assert r.matched == 3
    assert r.empty == 15  # все пять полей пусты у трёх записей


def test_pages_outside_gold_are_not_penalised() -> None:
    pred = file(
        [rec("01.03.02", "МОШ"), rec("09.03.01", "Ломоносов", page=3, quote=PAGE3)],
        pages=[2, 3],
    )
    r = ev.run({"d": GOLD}, {"d": pred})[0][0]
    assert r.pred == 1 and r.matched == 1


def test_rows_outside_gold_range_are_not_penalised() -> None:
    gold = file([rec("01.03.02", "МОШ")])
    gold.document.rows = (2, 56)
    pred = file(
        [
            rec("01.03.02", "МОШ", source_row=3),
            rec("01.03.02", "Ломоносов", source_row=700),
            rec("01.03.02", "Высшая проба"),  # строка неизвестна — считается
        ]
    )
    r = ev.run({"d": gold}, {"d": pred})[0][0]
    assert r.pred == 2 and r.matched == 1


def test_any_code_gold_matches_every_program_without_extra_penalty() -> None:
    gold = file([rec("*", "МОШ", winner_role="both"), rec("*", "Ломоносов")])
    pred = file(
        [
            rec("01.03.02", "МОШ", winner_role="both"),
            rec("09.03.01", "МОШ", winner_role="both"),
            rec("09.03.01", "Ломоносов"),
            rec("09.03.01", "Высшая проба"),
        ]
    )
    r = ev.run({"d": gold}, {"d": pred})[0][0]
    assert r.matched == 2 and r.pred == 3  # лишней считается только «Высшая проба»
    assert r.recall == 1 and r.field_ok["winner_role"] == 2


def test_loose_profile_matches_old_base_rows_without_profile() -> None:
    gold = file([rec("01.03.02", "МОШ", profile="Математика")])
    pred = file([rec("01.03.02", "МОШ")])
    g, p = [ev.row_of(r) for r in gold.records], [ev.row_of(r) for r in pred.records]
    assert ev.match_rows(g, p) == []
    assert len(ev.match_rows(g, p, loose_profile=True)) == 1


def test_missing_pred_file_gives_zero_recall() -> None:
    r = ev.run({"d": GOLD}, {})[0][0]
    assert r.recall == 0 and r.precision is None and r.note == "нет файла"


def test_pred_file_found_by_url_not_only_by_name() -> None:
    pred = file([rec("01.03.02", "МОШ")])
    r = ev.run({"gold-name": GOLD}, {"other-name": pred})[0][0]
    assert r.matched == 1


def test_duplicate_keys_are_paired_one_to_one() -> None:
    gold = file([rec("01.03.02", "МОШ", levels=[1]), rec("01.03.02", "МОШ", levels=[2])])
    pred = file([rec("01.03.02", "МОШ", levels=[2])])
    r = ev.run({"d": gold}, {"d": pred})[0][0]
    assert r.matched == 1 and r.field_accuracy("levels") == 1.0


def test_quotes_are_checked_on_the_stated_page(tmp_path: Path) -> None:
    pages = ["титул", PAGE2, PAGE3]
    document = {"pages": pages}

    class Store(DocumentStore):
        def get(self, url):  # type: ignore[no-untyped-def]
            from olymp_workers.ai.documents import Document

            return Document(url, url, "pdf", SHA, tuple(document["pages"]))

    pred = file(
        [
            rec("01.03.02", "МОШ", quote="01.03.02 высшая  проба: победители и призёры"),
            rec("01.03.02", "Ломоносов", quote="этого нет на странице"),
            rec("01.03.02", "Высшая проба", quote=PAGE3),  # цитата с другой страницы
        ]
    )
    checker = ev.QuoteChecker(Store(tmp_path))
    r = ev.run({"d": GOLD}, {"d": pred}, checker=checker)[0][0]
    assert r.quotes == (1, 2, 0)
    assert r.gold_quotes == (3, 0, 0)


def test_unavailable_document_is_unchecked_not_missing(tmp_path: Path) -> None:
    store = DocumentStore(tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    r = ev.run({"d": GOLD}, {"d": GOLD}, checker=ev.QuoteChecker(store))[0][0]
    assert r.quotes == (0, 0, 3) and r.quote_rate is None


def test_db_value_conversion() -> None:
    assert ev.db_role("только победители") == "winner"
    assert ev.db_role("победители и призёры (10–11 класс)") == "both"
    assert ev.db_role("члены сборных команд РФ") is None
    assert ev.db_levels("I, III") == {1, 3}
    assert ev.db_grades("класс 10-11") == {10, 11}
    assert ev.db_grades("9, 10, 11 класс") == {9, 10, 11}
    assert ev.db_grades("") == frozenset()


def test_db_row_is_limited_to_gold_codes_and_known_types() -> None:
    raw = {
        "code": "01.03.02, 09.03.01",
        "direction": "Прикладная математика",
        "benefit_type": "БВИ",
        "source_url": "",
        "winner_role": "победители",
        "level": "I",
        "profile": "Математика",
        "grade": "11 класс",
        "confirm_subjects": ["math"],
        "min_ege_score": 75,
        "olympiad": "Всероссийская олимпиада школьников «Высшая проба»",
    }
    rows = ev.db_rows_of(raw, {"01.03.02"}, "Вуз")
    assert [r.key[1] for r in rows] == ["01.03.02"]
    assert rows[0].winner_role == "winner" and rows[0].ege_min == 75
    assert ev.db_rows_of({**raw, "benefit_type": "Фаст-трек"}, {"01.03.02"}, "Вуз") == []
    assert ev.db_rows_of(raw, {"01.03.02"}, "Вуз", {"100"}) == []  # в документе только 100 баллов
    assert len(ev.db_rows_of(raw, None, "Вуз")) == 2  # эталон с «*»: все направления


def test_db_rows_without_codes_are_linked_by_division() -> None:
    raw = {
        "code": "",
        "direction": "Механико-математический факультет",
        "benefit_type": "БВИ",
        "source_url": "",
        "winner_role": "победители",
        "level": "I",
        "profile": "",
        "grade": "11 класс",
        "confirm_subjects": [],
        "min_ege_score": None,
        "olympiad": "Турнир городов",
    }
    units = {"механикоматематическийфакультет": {"01.05.01"}}
    rows = ev.db_rows_of(raw, {"01.05.01"}, "МГУ", None, units)
    assert [r.key[1] for r in rows] == ["01.05.01"]
    assert ev.db_rows_of(raw, {"01.05.01"}, "МГУ") == []


def test_cli_prints_table_and_writes_json(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    gold_dir, pred_dir = tmp_path / "gold", tmp_path / "pred"
    gold_dir.mkdir()
    pred_dir.mkdir()
    (gold_dir / "d.json").write_text(GOLD.model_dump_json(), encoding="utf-8")
    (pred_dir / "x.json").write_text(GOLD.model_dump_json(), encoding="utf-8")
    out = tmp_path / "m.json"
    code = ev.main(["--gold", str(gold_dir), "--pred", str(pred_dir), "--json", str(out)])
    assert code == 0
    assert "ИТОГО" in capsys.readouterr().out
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["total"]["precision"] == 1.0 and data["documents"][0]["passes"] is True


def test_cli_rejects_gold_without_pages(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    broken = json.loads(GOLD.model_dump_json())
    broken["document"]["pages"] = []
    (tmp_path / "d.json").write_text(json.dumps(broken), encoding="utf-8")
    assert ev.main(["--gold", str(tmp_path), "--pred", str(tmp_path)]) == 2
    assert "document.pages" in capsys.readouterr().err


def test_db_baseline_matches_gold_by_key(built_database_url: str) -> None:
    import psycopg
    from olymp_db.session import psycopg_dsn

    gold = file(
        [
            rec("01.03.01", "Ломоносов", profile="Физика", winner_role="winner"),
            rec("01.03.01", "Несуществующая олимпиада"),
        ],
        pages=[2],
    )
    gold.document.university = "НИУ ВШЭ"
    for r in gold.records:
        r.university = "НИУ ВШЭ"
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        rows, note = ev.db_rows(conn, gold)
    assert "ВШЭ" in note and rows
    assert all(r.key[1] == "01.03.01" for r in rows)
    pairs = ev.match_rows([ev.row_of(r) for r in gold.records], rows)
    assert len(pairs) == 1 and pairs[0][1].winner_role == "winner"
