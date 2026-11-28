"""Сводная панель «Мониторинг эффективности вузов» 2018–2024: сколько олимпиадников принимают вузы.

Панель (xlsx) в репозиторий не кладём: источник и лицензия уточняются. Из неё считаются раздел
`monitoring` в data/analysis/results.json и небольшой файл data/monitoring/olympiad_intake.csv
только для вузов нашей базы (его загружает olymp-ingest). Связь «наш вуз → ID панели» —
data/monitoring/universities.csv, подбор по названию вручную и проверен глазами.

Оговорки, из-за которых цифры нельзя читать буквально:
  * year — отчётный год: Мониторинг года N описывает год N−1, то есть приём этого года;
  * ноль у олимпиадников может значить «нет», а может «не заполнено»: при связи с баллом нули
    исключаются, в динамике и концентрации остаются (на сумму они не влияют);
  * в панели только государственные вузы и их филиалы: Иннополиса и «Центрального университета» нет;
  * средний балл бюджета 0 и 100 — пропуск, а не значение.
"""

from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import openpyxl  # type: ignore[import-untyped]

from .ingest import DATA_DIR

MONITORING_DIR = DATA_DIR / "monitoring"
MAPPING_FILE = MONITORING_DIR / "universities.csv"
INTAKE_FILE = MONITORING_DIR / "olympiad_intake.csv"
INTAKE_FIELDS = ("university", "year", "olympiad_students", "olympiad_share", "avg_score_budget")
SOURCE = "Мониторинг эффективности деятельности вузов, сводная панель 2018–2024"
SOURCE_NOTE = "[источник панели — уточнить]"

N = "olympiadStudentsEnrolledNumber"
PERCENT = "olympiadStudentsPercent"
SCORE = "averageScoreBudget"
NEEDED = (
    "ID",
    "VUZ_name",
    "region",
    "fedDistrict",
    "year",
    "filial",
    "headID",
    "students",
    SCORE,
    N,
    PERCENT,
    "profile",
    "profileHard",
    "profileMed",
    "profileAgro",
    "profileEcon",
    "profileLaw",
    "profilePedagogy",
    "profileHum",
    "profileArtSport",
    "profileOther",
)
PROFILE_FLAGS = {
    "profileHard": "точные и инженерные науки",
    "profileMed": "медицина, фармация",
    "profileAgro": "сельское хозяйство",
    "profileEcon": "экономика и управление",
    "profileLaw": "юриспруденция",
    "profilePedagogy": "педагогика",
    "profileHum": "гуманитарные науки",
    "profileArtSport": "искусство и спорт",
    "profileOther": "прочее",
}
MIN_PROFILE_UNIVERSITIES = 15
BASE_GROUPS = ("Москва", "Санкт-Петербург", "Остальные регионы")
FED_ORDER = ("ЦФО", "СЗФО", "ЮФО", "СКФО", "ПФО", "УрФО", "СФО", "ДФО")


Row = dict[str, Any]


class MonitoringDataError(ValueError):
    """Панель или связка с нашими вузами не читаются."""


# ---------------------------------------------------------------- чтение


def num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return None if isinstance(value, float) and math.isnan(value) else float(value)
    try:
        return float(str(value).replace(",", ".").strip())
    except ValueError:
        return None


def load_panel(path: Path) -> list[Row]:
    """Лист panel: строка = вуз-год. Читаются только нужные колонки."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if "panel" not in wb.sheetnames:
            raise MonitoringDataError(f"{path}: нет листа panel")
        rows = wb["panel"].iter_rows(values_only=True)
        header = [str(c) if c is not None else "" for c in next(rows)]
        missing = [c for c in NEEDED if c not in header]
        if missing:
            raise MonitoringDataError(f"{path}: нет колонок {', '.join(missing)}")
        index = {c: header.index(c) for c in NEEDED}
        out: list[Row] = []
        for raw in rows:
            if raw[index["ID"]] is None:
                continue
            row: Row = {c: raw[i] for c, i in index.items()}
            for c in ("ID", "year", "filial", "headID", "students", N):
                row[c] = int(num(row[c]) or 0)
            for c in (SCORE, PERCENT, *PROFILE_FLAGS):
                row[c] = num(row[c]) or 0.0
            row["VUZ_name"] = str(row["VUZ_name"] or "")
            row["region"] = str(row["region"] or "").strip()
            row["fedDistrict"] = str(row["fedDistrict"] or "").strip()
            out.append(row)
    finally:
        wb.close()
    return out


def load_mapping(path: Path = MAPPING_FILE) -> list[Row]:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["ids"] = [int(x) for x in r["panel_ids"].split("|") if x]
        if r["kind"] not in ("head", "filial", "none"):
            raise MonitoringDataError(f"{path}: вид «{r['kind']}» у «{r['university']}»")
        if (r["kind"] == "none") != (not r["ids"]):
            raise MonitoringDataError(f"{path}: «{r['university']}» — вид и ID не согласованы")
    names = [r["university"] for r in rows]
    if len(set(names)) != len(names):
        raise MonitoringDataError(f"{path}: повтор названия вуза")
    return rows


# ---------------------------------------------------------------- простая статистика


def share(part: float, whole: float) -> float | None:
    return round(part / whole, 4) if whole else None


def growth(new: float, old: float) -> float | None:
    """Прирост в процентах."""
    return round((new / old - 1) * 100, 1) if old else None


def gini(values: Sequence[float]) -> float | None:
    """Коэффициент Джини: 0 — поровну, 1 — всё у одного."""
    xs = sorted(values)
    total = sum(xs)
    if not xs or total <= 0:
        return None
    n = len(xs)
    weighted = sum((i + 1) * x for i, x in enumerate(xs))
    return round(2 * weighted / (n * total) - (n + 1) / n, 4)


def lorenz(values: Sequence[float], points: int = 50) -> list[list[float]]:
    """Кривая Лоренца: [доля вузов, доля олимпиадников у самых «малых» вузов]."""
    xs = sorted(values)
    total = sum(xs)
    n = len(xs)
    if not n or total <= 0:
        return []
    cum = [0.0]
    for x in xs:
        cum.append(cum[-1] + x)
    out = []
    for k in range(points + 1):
        i = round(k * n / points)
        out.append([round(i / n, 4), round(cum[i] / total, 4)])
    return out


def ranks(values: Sequence[float]) -> list[float]:
    """Ранги со средним при совпадениях."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / math.sqrt(sxx * syy)


def spearman(xs: Sequence[float], ys: Sequence[float]) -> dict[str, Any]:
    """Ранговая корреляция, число вузов и приближённый 95%-интервал (преобразование Фишера)."""
    n = len(xs)
    rho = pearson(ranks(xs), ranks(ys))
    if rho is None:
        return {"n": n, "rho": None, "ci95": None}
    ci = None
    if n > 3 and abs(rho) < 1:
        z, se = math.atanh(rho), 1.06 / math.sqrt(n - 3)
        ci = [round(math.tanh(z - 1.96 * se), 2), round(math.tanh(z + 1.96 * se), 2)]
    return {"n": n, "rho": round(rho, 3), "ci95": ci}


def short_name(name: str) -> str:
    """«Федеральное государственное … образовательное учреждение высшего образования «МГУ…»» -> «МГУ…»."""
    name = re.sub(r"^.*?высшего образования\s*", "", name, flags=re.S)
    name = re.sub(r"\s+", " ", name).replace('"', "").replace("«", "").replace("»", "")
    return name.strip(" .") or name


def base_group(region: str) -> str:
    return region if region in ("Москва", "Санкт-Петербург") else "Остальные регионы"


def by_year(panel: Iterable[Row]) -> dict[int, list[Row]]:
    out: dict[int, list[Row]] = defaultdict(list)
    for r in panel:
        out[r["year"]].append(r)
    return dict(sorted(out.items()))


# ---------------------------------------------------------------- разрезы


def dynamics(panel: list[Row]) -> dict[str, Any]:
    years = by_year(panel)
    first, last = next(iter(years)), next(reversed(years))
    all_years = set(years)
    seen: dict[int, set[int]] = defaultdict(set)
    for r in panel:
        seen[r["ID"]].add(r["year"])
    balanced = {i for i, ys in seen.items() if ys == all_years}
    rows = []
    prev: int | None = None
    for y, rs in years.items():
        total = sum(r[N] for r in rs)
        bal = sum(r[N] for r in rs if r["ID"] in balanced)
        rows.append(
            {
                "year": y,
                "universities": len(rs),
                "total": total,
                "with_olympiads": sum(1 for r in rs if r[N] > 0),
                "yoy_pct": growth(total, prev) if prev is not None else None,
                "balanced_total": bal,
            }
        )
        prev = total
    for r in rows:  # прирост по вузам, которые есть во все годы: состав панели не меняется
        r["growth_vs_first_pct"] = growth(r["total"], rows[0]["total"])
        r["balanced_growth_vs_first_pct"] = growth(r["balanced_total"], rows[0]["balanced_total"])
    # нули: вуз ни разу не указал олимпиадников, и нули в «провалах» между годами с данными
    per_vuz: dict[int, dict[int, int]] = defaultdict(dict)
    for r in panel:
        per_vuz[r["ID"]][r["year"]] = r[N]
    never = sum(1 for v in per_vuz.values() if not any(v.values()))
    gaps = 0
    for v in per_vuz.values():
        ys = sorted(v)
        for a, b, c in zip(ys, ys[1:], ys[2:], strict=False):
            if v[a] > 0 and v[c] > 0 and v[b] == 0:
                gaps += 1
    return {
        "by_year": rows,
        "first_year": first,
        "last_year": last,
        "growth_total_pct": growth(rows[-1]["total"], rows[0]["total"]),
        "growth_balanced_pct": rows[-1]["balanced_growth_vs_first_pct"],
        "balanced_universities": len(balanced),
        "universities_ever": len(per_vuz),
        "never_reported": never,
        "gap_years": gaps,
    }


def concentration(panel: list[Row]) -> dict[str, Any]:
    years = by_year(panel)
    last = next(reversed(years))
    out_years = []
    for y, rs in years.items():
        values = sorted((r[N] for r in rs), reverse=True)
        total = sum(values)
        out_years.append(
            {
                "year": y,
                "total": total,
                "top10_share": share(sum(values[:10]), total),
                "top20_share": share(sum(values[:20]), total),
                "gini_all": gini(values),
                "gini_positive": gini([v for v in values if v > 0]),
            }
        )
    lorenz_years = {}
    for y in (next(iter(years)), last):
        lorenz_years[str(y)] = lorenz([r[N] for r in years[y] if r[N] > 0])
    rs = years[last]
    total, students = sum(r[N] for r in rs), sum(r["students"] for r in rs)

    def block(group: list[Row]) -> dict[str, Any]:
        s = sum(r[N] for r in group)
        st = sum(r["students"] for r in group)
        return {
            "universities": len(group),
            "with_olympiads": sum(1 for r in group if r[N] > 0),
            "total": s,
            "share": share(s, total),
            "students_share": share(st, students),
            "per_1000_students": round(s / st * 1000, 2) if st else None,
        }

    districts = {d: [r for r in rs if r["fedDistrict"] == d] for d in FED_ORDER}
    other = [r for r in rs if r["fedDistrict"] not in FED_ORDER]
    fed = [{"name": d, **block(g)} for d, g in districts.items() if g]
    if other:
        fed.append({"name": "прочие", **block(other)})
    groups = [
        {"name": g, **block([r for r in rs if base_group(r["region"]) == g])} for g in BASE_GROUPS
    ]
    top = sorted(rs, key=lambda r: -r[N])[:10]
    return {
        "year": last,
        "by_year": out_years,
        "lorenz": lorenz_years,
        "fed_districts": fed,
        "region_groups": groups,
        "top": [
            {
                "id": r["ID"],
                "name": short_name(r["VUZ_name"]),
                "filial": bool(r["filial"]),
                "total": r[N],
            }
            for r in top
        ],
    }


def valid_score(r: Row) -> bool:
    return bool(0 < r[SCORE] < 100)


def score_link(panel: list[Row]) -> dict[str, Any]:
    """Доля олимпиадников и средний балл ЕГЭ принятых на бюджет.

    Единица — вуз: по годам, где доля больше нуля и балл заполнен, берётся среднее; так один вуз
    не считается несколько раз. Нули доли исключаются: это может быть «не заполнено».
    """
    years = by_year(panel)
    last = next(reversed(years))

    def usable(r: Row) -> bool:
        return r[PERCENT] > 0 and valid_score(r)

    def corr(rs: list[Row]) -> dict[str, Any]:
        rs = [r for r in rs if usable(r)]
        return spearman([r[SCORE] for r in rs], [r[PERCENT] for r in rs])

    last_rows = years[last]
    # по вузам: среднее по годам с данными
    per_vuz: dict[int, list[Row]] = defaultdict(list)
    for r in panel:
        if usable(r):
            per_vuz[r["ID"]].append(r)
    units = []
    for rs in per_vuz.values():
        latest = max(rs, key=lambda r: r["year"])  # профиль вуза бывает разным по годам
        units.append(
            {
                "score": sum(r[SCORE] for r in rs) / len(rs),
                "percent": sum(r[PERCENT] for r in rs) / len(rs),
                "profile": next((p for p in PROFILE_FLAGS if latest[p]), ""),
            }
        )
    profiles = []
    for flag, label in PROFILE_FLAGS.items():
        group = [u for u in units if u["profile"] == flag]
        if len(group) >= MIN_PROFILE_UNIVERSITIES:
            profiles.append(
                {
                    "profile": label,
                    **spearman([u["score"] for u in group], [u["percent"] for u in group]),
                    "median_percent": round(median([u["percent"] for u in group]), 2),
                    "median_score": round(median([u["score"] for u in group]), 1),
                }
            )
    # внутри вуза: меняются ли доля и балл в одну сторону от года к году
    deltas_x: list[float] = []
    deltas_y: list[float] = []
    for rs in per_vuz.values():
        rs = sorted(rs, key=lambda r: r["year"])
        for a, b in zip(rs, rs[1:], strict=False):
            if b["year"] == a["year"] + 1:
                deltas_x.append(b[SCORE] - a[SCORE])
                deltas_y.append(b[PERCENT] - a[PERCENT])
    # по четвертям вузов по баллу (последний год)
    quartiles = []
    usable_last = sorted((r for r in last_rows if usable(r)), key=lambda r: r[SCORE])
    q = len(usable_last)
    for i in range(4):
        part = usable_last[i * q // 4 : (i + 1) * q // 4]
        if part:
            quartiles.append(
                {
                    "score_from": round(part[0][SCORE], 1),
                    "score_to": round(part[-1][SCORE], 1),
                    "universities": len(part),
                    "median_percent": round(median([r[PERCENT] for r in part]), 2),
                }
            )
    return {
        "year": last,
        "excluded_zero_percent": sum(1 for r in last_rows if r[PERCENT] <= 0),
        "excluded_no_score": sum(1 for r in last_rows if r[PERCENT] > 0 and not valid_score(r)),
        "last_year": corr(last_rows),
        "by_year": [{"year": y, **corr(rs)} for y, rs in years.items()],
        "per_university": spearman([u["score"] for u in units], [u["percent"] for u in units]),
        "within_university_changes": spearman(deltas_x, deltas_y),
        "by_profile": profiles,
        "quartiles": quartiles,
        "points": [
            {"score": r[SCORE], "percent": round(r[PERCENT], 3)} for r in last_rows if usable(r)
        ],
    }


def median(values: Sequence[float]) -> float:
    xs = sorted(values)
    n = len(xs)
    if not n:
        return 0.0
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


# ---------------------------------------------------------------- наши вузы


def university_series(
    panel: list[Row], ids: Sequence[int], years: Sequence[int]
) -> list[dict[str, Any]]:
    """Ряд по годам для вуза или суммы нескольких организаций (филиалы)."""
    by_id: dict[tuple[int, int], Row] = {(r["ID"], r["year"]): r for r in panel}
    out = []
    for y in years:
        rs = [by_id[(i, y)] for i in ids if (i, y) in by_id]
        if not rs:
            continue
        n = sum(r[N] for r in rs)
        # знаменатель доли в панели не дан; берём его из доли каждой организации
        base = sum(r[N] / r[PERCENT] * 100 for r in rs if r[PERCENT] > 0 and r[N] > 0)
        scored = [r for r in rs if valid_score(r) and r["students"] > 0]
        weight = sum(r["students"] for r in scored)
        score = sum(r[SCORE] * r["students"] for r in scored) / weight if weight else None
        out.append(
            {
                "year": y,
                "olympiad_students": n or None,
                "olympiad_share": round(n / base * 100, 2) if n and base else None,
                "avg_score_budget": round(score, 2) if score else None,
            }
        )
    return out


def build_intake(panel: list[Row], mapping: list[Row]) -> list[dict[str, Any]]:
    """Строки olympiad_intake.csv: только вузы базы, у которых есть пара в панели."""
    ids = {r["ID"] for r in panel}
    years = sorted({r["year"] for r in panel})
    out: list[dict[str, Any]] = []
    for m in mapping:
        unknown = [i for i in m["ids"] if i not in ids]
        if unknown:
            raise MonitoringDataError(f"«{m['university']}»: в панели нет ID {unknown}")
        for row in university_series(panel, m["ids"], years):
            if row["olympiad_students"] or row["olympiad_share"] or row["avg_score_budget"]:
                out.append({"university": m["university"], **row})
    return out


def write_intake(rows: list[dict[str, Any]], path: Path = INTAKE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=INTAKE_FIELDS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: "" if r[k] is None else r[k] for k in INTAKE_FIELDS})


def our_base(panel: list[Row], mapping: list[Row]) -> dict[str, Any]:
    years = by_year(panel)
    last = next(reversed(years))
    head_ids = {i for m in mapping if m["kind"] == "head" for i in m["ids"]}
    filial_ids = {i for m in mapping if m["kind"] == "filial" for i in m["ids"]}
    ours = head_ids | filial_ids
    per_year = []
    for y, rs in years.items():
        total = sum(r[N] for r in rs)
        heads = sum(r[N] for r in rs if r["ID"] in head_ids)
        fil = sum(r[N] for r in rs if r["ID"] in filial_ids)
        per_year.append(
            {
                "year": y,
                "total": total,
                "heads": heads,
                "filials": fil,
                "share": share(heads + fil, total),
            }
        )
    rs = years[last]
    all_filials = sum(r[N] for r in rs if r["filial"])
    # филиалы вузов нашей базы, которых самих в базе нет
    own_filials = [r for r in rs if r["filial"] and r["headID"] in head_ids and r["ID"] not in ours]
    ranked = sorted(rs, key=lambda r: (-r[N], r["ID"]))
    tops = {}
    for k in (10, 20, 50):
        group = ranked[:k]
        tops[str(k)] = {
            "in_base": sum(1 for r in group if r["ID"] in ours),
            "intake_share": share(
                sum(r[N] for r in group if r["ID"] in ours), sum(r[N] for r in group)
            ),
        }
    missing = [
        {
            "id": r["ID"],
            "name": short_name(r["VUZ_name"]),
            "filial": bool(r["filial"]),
            "total": r[N],
        }
        for r in ranked[:20]
        if r["ID"] not in ours
    ]
    return {
        "year": last,
        "universities_in_base": len(mapping),
        "found_in_panel": sum(1 for m in mapping if m["kind"] != "none"),
        "heads": sum(1 for m in mapping if m["kind"] == "head"),
        "filial_rows": sum(1 for m in mapping if m["kind"] == "filial"),
        "not_in_panel": [m["university"] for m in mapping if m["kind"] == "none"],
        "panel_organizations_with_olympiads": sum(1 for r in rs if r[N] > 0),
        "organizations_in_base_with_olympiads": sum(1 for r in rs if r["ID"] in ours and r[N] > 0),
        "by_year": per_year,
        "top": tops,
        "top20_not_in_base": missing,
        "filials": {
            "all_total": all_filials,
            "all_share": share(all_filials, sum(r[N] for r in rs)),
            "of_base_universities_not_in_base": sum(r[N] for r in own_filials),
        },
    }


# ---------------------------------------------------------------- сборка раздела


def analyse_monitoring(
    panel_path: Path, mapping_path: Path = MAPPING_FILE
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Раздел results.json и строки olympiad_intake.csv."""
    panel = load_panel(panel_path)
    if not panel:
        raise MonitoringDataError(f"{panel_path}: пустая панель")
    mapping = load_mapping(mapping_path)
    years = sorted({r["year"] for r in panel})
    section = {
        "source": SOURCE,
        "source_note": SOURCE_NOTE,
        "years": [years[0], years[-1]],
        "rows": len(panel),
        "universities": len({r["ID"] for r in panel}),
        "dynamics": dynamics(panel),
        "concentration": concentration(panel),
        "score_link": score_link(panel),
        "our_base": our_base(panel, mapping),
    }
    return section, build_intake(panel, mapping)
