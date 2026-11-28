"""olymp_workers.monitoring: расчёты по панели, связка с нашими вузами, загрузка в базу."""

import csv
import math
import shutil
from pathlib import Path
from typing import Any

import openpyxl
import psycopg
import pytest
from olymp_db.session import psycopg_dsn
from olymp_workers import monitoring as mon
from olymp_workers.intake import IntakeDataError, load_intake

DATA = Path(__file__).resolve().parents[3] / "data"


def row(
    vuz: int,
    year: int,
    n: int,
    *,
    percent: float = 0.0,
    score: float = 70.0,
    students: int = 1000,
    region: str = "Москва",
    district: str = "ЦФО",
    filial: int = 0,
    head: int = 0,
    profile: str = "profileHard",
) -> dict[str, Any]:
    r: dict[str, Any] = {
        "ID": vuz,
        "VUZ_name": f"Вуз {vuz}",
        "region": region,
        "fedDistrict": district,
        "year": year,
        "filial": filial,
        "headID": head,
        "students": students,
        mon.SCORE: score,
        mon.N: n,
        mon.PERCENT: percent,
        "profile": "",
    }
    for flag in mon.PROFILE_FLAGS:
        r[flag] = 1.0 if flag == profile else 0.0
    return r


def test_gini_extremes_and_ranks() -> None:
    assert mon.gini([5, 5, 5, 5]) == 0
    assert mon.gini([0, 0, 0, 10]) == pytest.approx(0.75)
    assert mon.gini([0, 0]) is None
    assert mon.ranks([10, 20, 20, 30]) == [1, 2.5, 2.5, 4]


def test_lorenz_ends_at_one_and_follows_small_first() -> None:
    points = mon.lorenz([1, 1, 1, 7], points=4)
    assert points[0] == [0, 0]
    assert points[-1] == [1, 1]
    assert points[3] == [0.75, 0.3]


def test_spearman_monotone_and_interval() -> None:
    perfect = mon.spearman([1, 2, 3, 4, 5], [10, 100, 1000, 5000, 9000])
    assert perfect["rho"] == 1.0
    inverse = mon.spearman([1, 2, 3, 4, 5], [9, 7, 5, 3, 1])
    assert inverse["rho"] == -1.0
    xs = [float(i) for i in range(30)]
    noisy = mon.spearman(xs, [x + (5 if i % 2 else -5) for i, x in enumerate(xs)])
    low, high = noisy["ci95"]
    assert low < noisy["rho"] < high
    assert math.isnan(0) is False
    assert mon.spearman([1, 1, 1], [1, 2, 3])["rho"] is None


def test_dynamics_counts_zero_gaps_and_never_reported() -> None:
    panel = [
        row(1, 2018, 10),
        row(1, 2019, 0),  # провал между годами с данными: вероятно, не заполнено
        row(1, 2020, 12),
        row(2, 2018, 0),
        row(2, 2019, 0),
        row(2, 2020, 0),
        row(3, 2019, 5),
        row(3, 2020, 8),
    ]
    d = mon.dynamics(panel)
    assert [r["total"] for r in d["by_year"]] == [10, 5, 20]
    assert [r["with_olympiads"] for r in d["by_year"]] == [1, 1, 2]
    assert d["growth_total_pct"] == 100.0
    assert d["never_reported"] == 1
    assert d["gap_years"] == 1
    # вуз 3 не во все годы: рост по полной панели считается без него
    assert d["balanced_universities"] == 2
    assert d["growth_balanced_pct"] == 20.0


def test_concentration_shares_and_groups() -> None:
    panel = [row(i, 2024, n) for i, n in enumerate([100, 50, 30, 10, 5, 3, 1, 1, 0, 0], 1)]
    panel.append(row(11, 2024, 200, region="Санкт-Петербург", district="СЗФО"))
    panel.append(row(12, 2024, 20, region="Томская область", district="СФО"))
    panel.append(row(13, 2024, 2))
    c = mon.concentration(panel)
    total = 100 + 50 + 30 + 10 + 5 + 3 + 1 + 1 + 200 + 20 + 2
    last = c["by_year"][-1]
    assert last["total"] == total
    assert last["top10_share"] == round((total - 1) / total, 4)
    groups = {g["name"]: g for g in c["region_groups"]}
    assert groups["Санкт-Петербург"]["total"] == 200
    assert groups["Остальные регионы"]["total"] == 20
    assert sum(g["total"] for g in groups.values()) == total
    assert sum(d["total"] for d in c["fed_districts"]) == total


def test_score_link_ignores_zero_shares_and_missing_scores() -> None:
    # доля растёт вместе с баллом; строки с нулевой долей и баллом 0 или 100 не участвуют
    panel = [row(i, 2024, 10, percent=i * 0.1, score=60 + i) for i in range(1, 21)]
    panel += [row(30, 2024, 0, percent=0.0, score=99), row(31, 2024, 5, percent=9.0, score=0)]
    panel += [row(32, 2024, 5, percent=9.0, score=100)]
    link = mon.score_link(panel)
    assert link["last_year"]["n"] == 20
    assert link["last_year"]["rho"] == 1.0
    assert link["excluded_zero_percent"] == 1
    assert link["excluded_no_score"] == 2
    assert len(link["points"]) == 20


def test_series_sums_filials_and_weights_score() -> None:
    panel = [
        row(10, 2024, 4, percent=2.0, score=60, students=1000),
        row(11, 2024, 6, percent=3.0, score=90, students=3000),
        row(11, 2023, 0, percent=0.0, score=80, students=3000),
    ]
    out = mon.university_series(panel, [10, 11], [2023, 2024])
    assert out[0] == {
        "year": 2023,
        "olympiad_students": None,
        "olympiad_share": None,
        "avg_score_budget": 80.0,
    }
    # 10 человек из 200 + 200 принятых: доля 10 / (200 + 200) = 2,5%; балл взвешен по студентам
    assert out[1]["olympiad_students"] == 10
    assert out[1]["olympiad_share"] == 2.5
    assert out[1]["avg_score_budget"] == 82.5


def write_mapping(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["university", "panel_ids", "kind", "panel_name", "comment"])
        w.writerows(rows)


def test_mapping_checks_kind_and_ids(tmp_path: Path) -> None:
    path = tmp_path / "m.csv"
    write_mapping(path, [["Вуз", "1", "none", "", ""]])
    with pytest.raises(mon.MonitoringDataError):
        mon.load_mapping(path)
    write_mapping(path, [["Вуз", "", "head", "", ""]])
    with pytest.raises(mon.MonitoringDataError):
        mon.load_mapping(path)
    write_mapping(path, [["Вуз", "1", "head", "", ""], ["Вуз", "2", "head", "", ""]])
    with pytest.raises(mon.MonitoringDataError):
        mon.load_mapping(path)


def make_xlsx(path: Path, rows: list[dict[str, Any]]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "panel"
    ws.append(list(mon.NEEDED))
    for r in rows:
        ws.append([r[c] for c in mon.NEEDED])
    wb.save(path)


def test_section_and_intake_from_xlsx(tmp_path: Path) -> None:
    panel = [
        row(1, y, n, percent=n / 10, score=80, students=2000) for y, n in ((2023, 20), (2024, 30))
    ]
    panel += [row(2, 2024, 70, percent=5.0, score=90), row(3, 2024, 0, score=60)]
    panel += [row(4, 2024, 0, score=0, filial=1, head=1)]
    xlsx = tmp_path / "panel.xlsx"
    make_xlsx(xlsx, panel)
    mapping = tmp_path / "m.csv"
    write_mapping(
        mapping,
        [["Наш один", "1", "head", "", ""], ["Наш чужой", "", "none", "", "АНО"]],
    )
    section, intake = mon.analyse_monitoring(xlsx, mapping)
    assert section["years"] == [2023, 2024]
    assert section["universities"] == 4
    base = section["our_base"]
    assert base["not_in_panel"] == ["Наш чужой"]
    # в базе 30 из 100 принятых олимпиадников 2024 года
    assert base["by_year"][-1]["share"] == 0.3
    assert base["top20_not_in_base"][0]["total"] == 70
    assert base["filials"]["all_total"] == 0
    assert [(r["university"], r["year"], r["olympiad_students"]) for r in intake] == [
        ("Наш один", 2023, 20),
        ("Наш один", 2024, 30),
    ]
    out = tmp_path / "intake.csv"
    mon.write_intake(intake, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(mon.INTAKE_FIELDS)
    assert lines[1] == "Наш один,2023,20,2.0,80.0"


def test_unknown_panel_id_stops_the_build(tmp_path: Path) -> None:
    mapping = tmp_path / "m.csv"
    write_mapping(mapping, [["Вуз", "999", "head", "", ""]])
    with pytest.raises(mon.MonitoringDataError):
        mon.build_intake([row(1, 2024, 1)], mon.load_mapping(mapping))


def test_committed_files_are_consistent() -> None:
    """Связка с панелью и загрузка в базу лежат в репозитории и не расходятся."""
    mapping = mon.load_mapping(DATA / "monitoring" / "universities.csv")
    names = {m["university"] for m in mapping}
    with (DATA / "monitoring" / "olympiad_intake.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    assert {r["university"] for r in rows} <= names
    assert {m["university"] for m in mapping if m["kind"] == "none"}.isdisjoint(
        {r["university"] for r in rows}
    )
    assert len({(r["university"], r["year"]) for r in rows}) == len(rows)


def test_mapping_covers_the_database_and_intake_is_loaded(built_database_url: str) -> None:
    mapping = mon.load_mapping(DATA / "monitoring" / "universities.csv")
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM universities")}
        loaded = conn.execute("SELECT COUNT(*) FROM university_intake").fetchone()[0]
    assert {m["university"] for m in mapping} == names
    with (DATA / "monitoring" / "olympiad_intake.csv").open(encoding="utf-8", newline="") as fh:
        assert loaded == len(list(csv.DictReader(fh)))


def test_intake_with_unknown_university_is_an_error(
    built_database_url: str, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    (data / "monitoring").mkdir(parents=True)
    shutil.copy(DATA / "monitoring" / "olympiad_intake.csv", data / "monitoring")
    path = data / "monitoring" / "olympiad_intake.csv"
    path.write_text(
        path.read_text(encoding="utf-8").replace("МФТИ", "Несуществующий вуз", 1),
        encoding="utf-8",
    )
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        conn.execute("DELETE FROM university_intake")
        with pytest.raises(IntakeDataError):
            load_intake(conn, data)
        assert load_intake(conn, tmp_path) == {"rows": 0, "universities": 0}  # файла нет
        conn.rollback()  # общая база тестов остаётся нетронутой
