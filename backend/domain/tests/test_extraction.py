import json
from pathlib import Path

import pytest
from olymp_domain import extraction
from olymp_domain.extraction import (
    ExtractionError,
    ExtractionFile,
    load_dir,
    olympiad_key,
    quote_found,
    record_key,
)

SHA = "a" * 64
ROOT = Path(__file__).resolve().parents[3]


def payload(**record: object) -> dict:
    base = {
        "university": "НИУ ВШЭ",
        "campaign": 2027,
        "program_code": "01.03.02",
        "benefit_type": "bvi",
        "olympiad": "Высшая проба",
        "source": {"url": "https://u.example/d.pdf", "sha256": SHA, "page": 2, "quote": "строка"},
    }
    return {
        "document": {
            "university": "НИУ ВШЭ",
            "campaign": 2027,
            "url": "https://u.example/d.pdf",
            "sha256": SHA,
            "pages": [2, 3],
        },
        "records": [{**base, **record}],
    }


def test_minimal_file_is_valid_and_defaults_are_empty() -> None:
    rec = ExtractionFile.model_validate(payload()).records[0]
    assert rec.winner_role is None
    assert rec.levels == [] and rec.grades == [] and rec.ege is None and rec.profile == ""


def test_olympiad_names_match_across_spellings() -> None:
    a = olympiad_key("Высшая проба")
    assert a == olympiad_key("ВСЕРОССИЙСКАЯ ОЛИМПИАДА ШКОЛЬНИКОВ «ВЫСШАЯ ПРОБА»")
    assert olympiad_key("ВсОШ") == olympiad_key("Всероссийская олимпиада школьников")
    assert olympiad_key("Неизвестная  олимпиада!") == "неизвестнаяолимпиада"


def test_record_key_ignores_case_and_quotes() -> None:
    first = ExtractionFile.model_validate(payload(profile="Математика")).records[0]
    second = ExtractionFile.model_validate(
        payload(olympiad="«ВЫСШАЯ ПРОБА»", profile="математика")
    ).records[0]
    other = ExtractionFile.model_validate(payload(benefit_type="100")).records[0]
    assert record_key(first) == record_key(second)
    assert record_key(first) != record_key(other)


@pytest.mark.parametrize(
    "change",
    [
        {"benefit_type": "bvi2"},
        {"winner_role": "всем"},
        {"levels": [4]},
        {"ege": {"subjects": ["math2"], "min": 75}},
        {"ege": {"subjects": ["math"], "min": 175}},
        {"typo_field": 1},
        {"source": {"url": "https://u.example/d.pdf", "sha256": SHA, "page": 9, "quote": "x"}},
        {"source": {"url": "https://u.example/d.pdf", "sha256": "b" * 64, "page": 2, "quote": "x"}},
        {"source": {"url": "https://u.example/d.pdf", "sha256": "zz", "page": 2, "quote": "x"}},
    ],
)
def test_invalid_records_are_rejected(change: dict) -> None:
    with pytest.raises(ValueError):
        ExtractionFile.model_validate(payload(**change))


def test_quote_matching_ignores_whitespace_hyphenation_and_quotes() -> None:
    page = "Олимпиада школь-\nников  «Высшая\nпроба» —\n  победители"
    assert quote_found('школьников "Высшая проба" - победители', page)
    assert not quote_found("призёры", page)
    assert not quote_found("   ", page)


def test_load_dir_reports_every_broken_file(tmp_path: Path) -> None:
    (tmp_path / "ok.json").write_text(json.dumps(payload()), encoding="utf-8")
    (tmp_path / "bad.json").write_text("{}", encoding="utf-8")
    (tmp_path / "schema.json").write_text("{}", encoding="utf-8")
    (tmp_path / "baseline-xlsx.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ExtractionError, match="bad.json"):
        load_dir(tmp_path)
    (tmp_path / "bad.json").unlink()
    assert list(load_dir(tmp_path)) == ["ok"]


def test_document_rows_are_checked() -> None:
    data = payload()
    data["document"]["rows"] = [2, 56]
    data["records"][0]["source"]["row"] = 10
    assert ExtractionFile.model_validate(data).document.rows == (2, 56)
    data["records"][0]["source"]["row"] = 57
    with pytest.raises(ValueError, match="document.rows"):
        ExtractionFile.model_validate(data)
    data["document"]["rows"] = [9, 3]
    with pytest.raises(ValueError, match="первая строка"):
        ExtractionFile.model_validate(data)


def test_committed_schema_is_current() -> None:
    committed = (ROOT / "data/eval/extraction/schema.json").read_text(encoding="utf-8")
    assert committed == extraction.schema_text()
