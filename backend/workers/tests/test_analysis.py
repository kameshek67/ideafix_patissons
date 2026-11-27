"""olymp_workers.analysis: разрезы данных на маленькой базе и готовых отчётах."""

import json
from pathlib import Path

import psycopg
from olymp_db.session import psycopg_dsn
from olymp_domain.extraction import olympiad_key
from olymp_workers import analysis as an

from .test_eval_extract import file, rec


def add_benefit(
    conn: psycopg.Connection,
    program_id: int,
    olympiad_id: int,
    role: str,
    benefit_type: str = "БВИ",
    layer: str = "detailed",
    profile: str = "математика",
    subjects: list[str] | None = None,
) -> None:
    benefit_id = conn.execute(
        "INSERT INTO benefits (program_id, benefit_type, raw_conditions_text, layer, "
        "winner_role, confirm_subjects, row_key) VALUES (%s, %s, 'условие', %s, %s, %s, %s) "
        "RETURNING id",
        (program_id, benefit_type, layer, role, subjects, f"k{program_id}-{olympiad_id}-{role}"),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO benefit_olympiads (benefit_id, olympiad_id, profile, winner_role) "
        "VALUES (%s, %s, %s, %s)",
        (benefit_id, olympiad_id, profile, role),
    )


def build(conn: psycopg.Connection) -> None:
    conn.execute("DELETE FROM universities")
    conn.execute("DELETE FROM olympiads")
    unis = [
        conn.execute(
            "INSERT INTO universities (name, short_name) VALUES (%s, %s) RETURNING id", (n, n)
        ).fetchone()[0]
        for n in ("Вуз А", "Вуз Б")
    ]
    programs = [
        conn.execute(
            "INSERT INTO programs (university_id, faculty_or_direction, code) "
            "VALUES (%s, %s, %s) RETURNING id",
            (unis[i], f"Направление {i}", f"01.03.0{i + 1}"),
        ).fetchone()[0]
        for i in (0, 1)
    ]

    def olympiad(name: str, kind: str, in_list: bool | None) -> int:
        return conn.execute(
            "INSERT INTO olympiads (canonical_name, short_name, squash_key, kind, "
            "in_rsosh_2026_27) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (name, name, name.lower(), kind, in_list),
        ).fetchone()[0]

    listed = olympiad("Первая", "rsosh", True)
    dropped = olympiad("Вторая", "rsosh", False)
    vsosh = olympiad("Всероссийская олимпиада школьников (заключительный этап)", "vsosh", None)
    squash_vsosh = an.VSOSH_KEY
    conn.execute("UPDATE olympiads SET squash_key = %s WHERE id = %s", (squash_vsosh, vsosh))
    a, b = programs
    add_benefit(conn, a, listed, "победители и призёры", subjects=["math"])
    add_benefit(conn, b, listed, "только победители")
    add_benefit(conn, a, dropped, "призёры", subjects=["math"])
    add_benefit(conn, b, vsosh, "победители и призёры")
    add_benefit(conn, a, listed, "победители", benefit_type="100 баллов")
    add_benefit(conn, a, listed, "победители и призёры", layer="raw")


def test_sections_on_small_database(empty_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        try:
            build(conn)
            links = an.load_links(conn)
        finally:
            conn.rollback()
    assert len(links) == 5  # слой raw в выдачу не попадает

    prize = an.prize_2027(links)
    # призёрам БВИ доступно в трёх строках; ВсОШ остаётся, две перечневые превращаются в 100 баллов
    assert prize["prize_bvi_rows"] == 3
    assert prize["to_hundred_rows"] == 2
    assert prize["to_hundred_programs"] == 1
    assert prize["prize_bvi_programs"] == 2
    assert prize["top_olympiads"][0]["programs"] == 1

    dropped = an.list_change(links)
    assert dropped["olympiads_out_of_list_with_rows"] == 1
    assert dropped["bvi_out_programs"] == 1
    assert dropped["top"][0]["name"] == "Вторая"

    spread = an.concentration(links)
    assert spread["bvi_links"] == 4
    # строка «призёры» открыта и победителям (roles_allowed), поэтому у победителей четыре связи
    assert [t["programs"] for t in spread["winners"]["top"]] == [2, 1, 1]
    assert spread["prizes"]["pairs"] == 3


def test_classify_document_by_types() -> None:
    gold = file(
        [
            rec(
                "01.03.02", "Высшая проба", winner_role="both", ege={"subjects": ["inf"], "min": 75}
            ),
            rec("01.03.02", "Ломоносов", winner_role="winner"),
            rec("01.03.02", "МОШ", winner_role="both"),
            rec("01.03.02", "Физтех"),
        ]
    )
    old = [
        an.Row(
            key=("вуз", "01.03.02", olympiad_key(name), "", "bvi"),
            winner_role=role,
            levels=frozenset(),
            grades=frozenset(),
            ege_min=ege,
            ege_subjects=frozenset({"inf"} if ege else ()),
        )
        for name, role, ege in (
            ("Высшая проба", "both", 70),  # порог ЕГЭ другой
            ("Ломоносов", "prizewinner", None),  # «кому» другое
            ("Турнир городов", "both", None),  # такой олимпиады в эталоне нет
        )
    ]
    # МОШ у вуза записана группой направлений, без кода
    raw = [
        {"benefit_type": "БВИ", "olympiad": "МОШ", "code": "", "direction": "Все направления"},
        {"benefit_type": "БВИ", "olympiad": "Высшая проба", "code": "01.03.02", "direction": ""},
    ]
    result = an.classify_document(gold, old, raw)
    assert result["counts"] == {
        "missing": 1,
        "extra": 0,  # «Турнир городов» нельзя проверить: его нет среди записей эталона
        "role": 1,
        "ege": 1,
        "grade_level": 0,
        "detail": 1,
    }
    assert result["extra_unverifiable"] == 1
    assert result["ok"] == 0


def test_ai_metrics_from_reports(tmp_path: Path) -> None:
    total = {
        "gold": 10,
        "pred": 8,
        "matched": 6,
        "precision": 0.75,
        "recall": 0.6,
        "role_wrong": 0,
        "fields": {"winner_role": 1.0},
    }
    for directory in ("extraction", "holdout"):
        (tmp_path / directory).mkdir()
        for name in ("baseline-extract.json", "baseline-xlsx.json"):
            (tmp_path / directory / name).write_text(json.dumps({"total": total}), encoding="utf-8")
    (tmp_path / "assistant").mkdir()
    model = {
        "model": "m",
        "cases": 69,
        "passed_share": 0.7,
        "error_share_raw": 0.15,
        "error_share_final": 0.0,
        "answer_p95": 12.34,
        "cost_per_answer": 0.004,
        "gate_passed": True,
    }
    (tmp_path / "assistant" / "summary.json").write_text(
        json.dumps({"models": [model], "selected": "m", "summary": model}), encoding="utf-8"
    )
    result = an.ai_metrics(tmp_path)
    assert result["extraction"]["holdout_extract"]["recall"] == 0.6
    assistant = result["assistant"]
    assert assistant["models"][0]["cost_per_student_year"] == {"3": 0.012, "10": 0.04, "30": 0.12}
    assert assistant["selected_cost_per_1000_students"] == 40.0
