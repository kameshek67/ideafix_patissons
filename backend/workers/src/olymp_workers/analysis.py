"""Анализ собранных данных: четыре разреза по базе и сводка метрик ИИ-части из data/eval.

    olymp-analysis                         # пересчитать data/analysis/results.json по базе
    olymp-analysis --charts                # плюс графики в docs/img (нужен matplotlib)
    olymp-analysis --charts-only           # только графики из готового results.json

Разрезы:
  prize_2027      — сколько строк БВИ для призёров перечневых олимпиад станут «100 баллов» по проекту 2027;
  old_table       — чем строки старой таблицы (слои detailed и derived) отличаются от эталона документов;
  list_2026_27    — что потеряли олимпиады, не вошедшие в перечень 2026/27;
  concentration   — на каких олимпиадах и профилях держатся льготы.
Подбор по диплому не переписан: роли — roles_allowed, судьба БВИ — bvi_change из olymp_domain.diplomas.
Считаются видимые строки (слой не raw); результат не зависит от времени запуска.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import psycopg
from olymp_db.session import psycopg_dsn
from olymp_domain.diplomas import (
    RULES_2027_FROM_YEAR,
    VSOSH_KEY,
    Change,
    Diploma,
    Role,
    bvi_change,
    is_real_profile,
    roles_allowed,
)
from olymp_domain.ege import subject_of_profile
from olymp_domain.extraction import ExtractionFile, load_dir
from psycopg.rows import dict_row

from .eval_extract import (
    ANY_CODE,
    DB_TYPES,
    RE_CODE,
    Row,
    _tail,
    db_raw,
    db_rows,
    in_scope,
    match_rows,
    pick_university,
    row_of,
)
from .ingest import DATA_DIR

RESULTS_FILE = DATA_DIR / "analysis" / "results.json"
EVAL_DIR = DATA_DIR / "eval"
IMG_DIR = DATA_DIR.parent / "docs" / "img"
OLD_LAYERS = ("detailed", "derived")  # старая таблица: без слоя document
BVI = "БВИ"
TOP = 10
# перечневые олимпиады: сами олимпиады РСОШ и строки «любая олимпиада из перечня»
LISTED_KINDS = ("rsosh", "other")
# допущение для цены помощника: сколько сообщений школьник пишет за год
MESSAGES_PER_STUDENT = (3, 10, 30)
BASE_MESSAGES = 10

LINKS_SQL = """
SELECT b.id AS benefit_id, b.benefit_type, p.id AS program_id, u.id AS university_id,
       COALESCE(NULLIF(u.short_name, ''), u.name) AS university,
       o.id AS olympiad_id, COALESCE(NULLIF(o.short_name, ''), o.canonical_name) AS olympiad,
       o.kind, o.squash_key, o.in_rsosh_2026_27,
       bo.profile_id, COALESCE(pr.name, bo.profile, '') AS profile,
       COALESCE(NULLIF(bo.winner_role, ''), b.winner_role) AS role,
       b.confirm_subjects
FROM benefit_olympiads bo
JOIN benefits b ON b.id = bo.benefit_id
JOIN programs p ON p.id = b.program_id
JOIN universities u ON u.id = p.university_id
JOIN olympiads o ON o.id = bo.olympiad_id
LEFT JOIN olympiad_profiles pr ON pr.id = bo.profile_id
WHERE b.layer <> 'raw' AND b.benefit_type IN ('БВИ', '100 баллов')
ORDER BY b.id, bo.id
"""


def load_links(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    """Связи «строка льготы — олимпиада» видимой выдачи."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(LINKS_SQL).fetchall()


def share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def top(counter: Counter[Any], n: int = TOP) -> list[tuple[Any, int]]:
    """Первые n по убыванию; при равенстве — по названию, чтобы результат не плавал."""
    return sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))[:n]


def prize_roles(link: dict[str, Any]) -> frozenset[Role] | None:
    """Кому дана льгота по строке; None — «кому» не указано или только сборным."""
    role = (link["role"] or "").strip()
    return roles_allowed(role) if role else None


# ---------------------------------------------------------------- 1. правила 2027


def prize_change_of(link: dict[str, Any]) -> Change | None:
    """Что проект 2027 делает с БВИ призёра по этой связи (диплом призёра олимпиады 2026/27)."""
    diploma = Diploma(
        olympiad_id=link["olympiad_id"],
        profile_id=link["profile_id"],
        profile_keys=frozenset(),
        role=Role.PRIZE,
        grade=None,
        year=RULES_2027_FROM_YEAR,
        international=link["kind"] == "international",
        vsosh=link["squash_key"] == VSOSH_KEY,
    )
    # профильный предмет ЕГЭ: назван в колонке подтверждения или следует из профиля олимпиады
    has_subject = bool(link["confirm_subjects"]) or subject_of_profile(link["profile"]) is not None
    return bvi_change([diploma], has_subject)


def prize_2027(links: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Строки и направления с БВИ, доступным призёрам, и какая часть станет «100 баллов»."""
    bvi_rows: set[int] = set()
    prize_rows: set[int] = set()
    prize_programs: set[int] = set()
    changed_rows: set[int] = set()
    check_rows: set[int] = set()
    stays: dict[int, int] = defaultdict(int)  # направление -> сколько связей призёра остаются БВИ
    hundred_links: dict[int, int] = defaultdict(int)
    check_links: dict[int, int] = defaultdict(int)
    unstated_rows: set[int] = set()
    by_kind: Counter[str] = Counter()
    programs_by_uni: dict[int, set[int]] = defaultdict(set)
    prize_programs_by_uni: dict[int, set[int]] = defaultdict(set)
    uni_names: dict[int, str] = {}
    prog_by_olymp: dict[int, set[int]] = defaultdict(set)
    rows_by_olymp: dict[int, set[int]] = defaultdict(set)
    unis_by_olymp: dict[int, set[int]] = defaultdict(set)
    olymp_names: dict[int, str] = {}

    for link in links:
        if link["benefit_type"] != BVI:
            continue
        benefit, program = link["benefit_id"], link["program_id"]
        bvi_rows.add(benefit)
        roles = prize_roles(link)
        if roles is None:
            if not (link["role"] or "").strip():
                unstated_rows.add(benefit)
            continue
        if Role.PRIZE not in roles:
            continue
        prize_rows.add(benefit)
        prize_programs.add(program)
        uni = link["university_id"]
        uni_names[uni] = link["university"]
        prize_programs_by_uni[uni].add(program)
        change = prize_change_of(link)
        if change is None:
            stays[program] += 1
        elif change is Change.HUNDRED:
            hundred_links[program] += 1
            if link["kind"] in LISTED_KINDS:
                changed_rows.add(benefit)
                by_kind[link["kind"]] += 1
                olympiad = link["olympiad_id"]
                olymp_names[olympiad] = link["olympiad"]
                prog_by_olymp[olympiad].add(program)
                rows_by_olymp[olympiad].add(benefit)
                unis_by_olymp[olympiad].add(uni)
                programs_by_uni[uni].add(program)
        else:
            check_rows.add(benefit)
            check_links[program] += 1

    changed_programs = {p for uni in programs_by_uni.values() for p in uni}
    # все БВИ призёра на направлении превращаются в «100 баллов»: БВИ у призёра не остаётся
    fully = {p for p in changed_programs if not stays.get(p) and not check_links.get(p)}
    top_unis = sorted(
        programs_by_uni, key=lambda u: (-len(programs_by_uni[u]), uni_names.get(u, ""))
    )[:TOP]
    top_olymps = sorted(
        prog_by_olymp, key=lambda o: (-len(prog_by_olymp[o]), olymp_names.get(o, ""))
    )[:TOP]
    return {
        "bvi_rows": len(bvi_rows),
        "prize_bvi_rows": len(prize_rows),
        "prize_bvi_programs": len(prize_programs),
        "to_hundred_rows": len(changed_rows),
        "to_hundred_rows_share": share(len(changed_rows), len(prize_rows)),
        "to_hundred_programs": len(changed_programs),
        "to_hundred_programs_share": share(len(changed_programs), len(prize_programs)),
        "fully_to_hundred_programs": len(fully),
        "fully_to_hundred_programs_share": share(len(fully), len(prize_programs)),
        "to_hundred_universities": len(programs_by_uni),
        "check_rows": len(check_rows),
        "role_unstated_rows": len(unstated_rows),
        "to_hundred_links_by_kind": dict(sorted(by_kind.items())),
        "top_universities": [
            {
                "name": uni_names[u],
                "programs": len(programs_by_uni[u]),
                "prize_programs": len(prize_programs_by_uni[u]),
                "share": share(len(programs_by_uni[u]), len(prize_programs_by_uni[u])),
            }
            for u in top_unis
        ],
        "top_olympiads": [
            {
                "name": olymp_names[o],
                "programs": len(prog_by_olymp[o]),
                "rows": len(rows_by_olymp[o]),
                "universities": len(unis_by_olymp[o]),
            }
            for o in top_olymps
        ],
    }


# ---------------------------------------------------------------- 2. старая таблица и документы

DIFF_TYPES = ("missing", "extra", "role", "ege", "grade_level", "detail")
DIFF_TITLES = {
    "missing": "нет строки в таблице",
    "extra": "лишняя строка в таблице",
    "role": "другое «кому»",
    "ege": "другой порог или предмет ЕГЭ",
    "grade_level": "другой класс или уровень",
    "detail": "группа направлений вместо кода",
}


def _olympiad_type(raw: dict[str, Any]) -> tuple[str, str] | None:
    """(ключ олимпиады, тип льготы) строки базы — как в ключе эталона."""
    from olymp_domain.extraction import olympiad_key

    btype = DB_TYPES.get(raw["benefit_type"])
    if btype is None or not raw["olympiad"]:
        return None
    return olympiad_key(raw["olympiad"]), btype


def classify_document(
    gold: ExtractionFile, old_rows: Sequence[Row], raw: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    """Расхождения старой таблицы с эталоном одного документа.

    Запись эталона бывает верной, неверной в поле (берётся одна главная причина: «кому», потом
    ЕГЭ, потом класс и уровень), отсутствует в таблице или записана группой направлений.
    Строки таблицы без пары в эталоне — лишние, но только если олимпиада и тип льготы есть среди
    записей эталона: таблица не хранит страниц, и остальные строки могут стоять на страницах
    документа, которые не размечены (их число — в extra_unverifiable)."""
    gold_rows = [row_of(r) for r in gold.records]
    pairs = match_rows(gold_rows, old_rows, loose_profile=True)
    paired_gold = {id(g) for g, _ in pairs}
    paired_old = {id(p) for _, p in pairs}
    # строки без кода направления: таблица держит льготу по группе, а не по направлению
    grouped: set[tuple[str, str]] = set()
    listed: set[tuple[str, str]] = (
        set()
    )  # олимпиада и тип льготы, о которых у вуза в таблице что-то есть
    for r in raw:
        ot = _olympiad_type(r)
        if ot is None:
            continue
        listed.add(ot)
        if not RE_CODE.search(f"{r['code'] or ''} {r['direction'] or ''}"):
            grouped.add(ot)

    counts: Counter[str] = Counter()
    fields: Counter[str] = Counter()
    ok = 0
    for g, p in pairs:
        diffs = []
        if g.winner_role != p.winner_role:
            diffs.append("role")
        if g.ege_min != p.ege_min or g.ege_subjects != p.ege_subjects:
            diffs.append("ege")
        if g.grades != p.grades or g.levels != p.levels:
            diffs.append("grade_level")
        fields.update(diffs)
        if diffs:
            counts[diffs[0]] += 1
        else:
            ok += 1
    no_olympiad = 0
    for g in gold_rows:
        if id(g) in paired_gold:
            continue
        ot = (g.key[2], g.key[4])
        counts["detail" if ot in grouped else "missing"] += 1
        no_olympiad += ot not in listed
    any_code = {_tail(g.key) for g in gold_rows if g.key[1] == ANY_CODE}
    gold_olymp_type = {(g.key[2], g.key[4]) for g in gold_rows}
    unverifiable = 0
    for p in old_rows:
        if id(p) in paired_old or _tail(p.key) in any_code:
            continue
        if (p.key[2], p.key[4]) in gold_olymp_type:
            counts["extra"] += 1
        else:
            unverifiable += 1
    return {
        "gold": len(gold_rows),
        "table_rows": len(old_rows),
        "ok": ok,
        "counts": {t: counts.get(t, 0) for t in DIFF_TYPES},
        "field_diffs_any": {t: fields.get(t, 0) for t in ("role", "ege", "grade_level")},
        "extra_unverifiable": unverifiable,
        "unmatched_no_olympiad": no_olympiad,
    }


def old_table(
    conn: psycopg.Connection[Any], sets: dict[str, Path], layers: Sequence[str] = OLD_LAYERS
) -> dict[str, Any]:
    """Сравнение слоёв старой таблицы с эталонными наборами (по документам и итог)."""
    result: dict[str, Any] = {"layers": list(layers), "types": DIFF_TITLES, "sets": {}}
    grand: Counter[str] = Counter()
    for name, directory in sets.items():
        gold_files = load_dir(directory)
        docs: dict[str, Any] = {}
        total: Counter[str] = Counter()
        for doc_name, gold in gold_files.items():
            rows, note = db_rows(conn, gold, layers)
            rows = in_scope(rows, gold.document.pages, gold.document.rows)
            found = pick_university(conn, gold.document.university)
            raw = db_raw(conn, found[0], layers) if found else []
            part = classify_document(gold, rows, raw)
            part["university"] = gold.document.university
            part["note"] = note
            docs[doc_name] = part
            for key in ("gold", "table_rows", "ok", "extra_unverifiable", "unmatched_no_olympiad"):
                total[key] += part[key]
            for t in DIFF_TYPES:
                total[t] += part["counts"][t]
            for t, n in part["field_diffs_any"].items():
                total[f"field_{t}"] += n
        entry = _summary(total)
        entry["documents"] = docs
        result["sets"][name] = entry
        grand.update(total)
    result["total"] = _summary(grand)
    return result


def _summary(total: Counter[str]) -> dict[str, Any]:
    problems = sum(total[t] for t in DIFF_TYPES)
    matched = total["gold"] - total["missing"] - total["detail"]
    return {
        "gold": total["gold"],
        "table_rows": total["table_rows"],
        "gold_matched": matched,
        "gold_matched_share": share(matched, total["gold"]),
        "gold_ok": total["ok"],
        "gold_ok_share": share(total["ok"], total["gold"]),
        "gold_missing_share": share(total["missing"], total["gold"]),
        "gold_detail_share": share(total["detail"], total["gold"]),
        "unmatched_no_olympiad": total["unmatched_no_olympiad"],
        "field_diffs_any": {t: total[f"field_{t}"] for t in ("role", "ege", "grade_level")},
        "problems": problems,
        "counts": {t: total[t] for t in DIFF_TYPES},
        "shares": {t: share(total[t], problems) for t in DIFF_TYPES},
        "extra_unverifiable": total["extra_unverifiable"],
    }


# ---------------------------------------------------------------- 3. перечень 2026/27


def list_change(links: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Олимпиады РСОШ вне перечня 2026/27: сколько у них строк, направлений и вузов с льготами."""
    rows_all: set[int] = set()
    out_rows: set[int] = set()
    out_programs: set[int] = set()
    out_unis: set[int] = set()
    bvi_out_programs: set[int] = set()
    bvi_out_rows: set[int] = set()
    bvi_other_programs: set[int] = (
        set()
    )  # БВИ направления по олимпиадам, которых изменение не касается
    per: dict[int, dict[str, set[int]]] = defaultdict(
        lambda: {"rows": set(), "programs": set(), "unis": set(), "bvi": set(), "bvi_rows": set()}
    )
    names: dict[int, str] = {}
    listed = {"in": set(), "out": set()}  # type: ignore[var-annotated]
    for link in links:
        if link["kind"] != "rsosh":
            if link["benefit_type"] == BVI:
                bvi_other_programs.add(link["program_id"])
            continue
        rows_all.add(link["benefit_id"])
        in_list = link["in_rsosh_2026_27"]
        if in_list is None:
            continue
        listed["in" if in_list else "out"].add(link["olympiad_id"])
        if in_list:
            if link["benefit_type"] == BVI:
                bvi_other_programs.add(link["program_id"])
            continue
        o = link["olympiad_id"]
        names[o] = link["olympiad"]
        out_rows.add(link["benefit_id"])
        out_programs.add(link["program_id"])
        out_unis.add(link["university_id"])
        per[o]["rows"].add(link["benefit_id"])
        per[o]["programs"].add(link["program_id"])
        per[o]["unis"].add(link["university_id"])
        if link["benefit_type"] == BVI:
            bvi_out_programs.add(link["program_id"])
            bvi_out_rows.add(link["benefit_id"])
            per[o]["bvi"].add(link["program_id"])
            per[o]["bvi_rows"].add(link["benefit_id"])
    lost = bvi_out_programs - bvi_other_programs
    ranked = sorted(per, key=lambda o: (-len(per[o]["bvi"]), names[o]))[:TOP]
    return {
        "olympiads_in_list_with_rows": len(listed["in"]),
        "olympiads_out_of_list_with_rows": len(listed["out"]),
        "rsosh_rows": len(rows_all),
        "out_rows": len(out_rows),
        "out_rows_share": share(len(out_rows), len(rows_all)),
        "out_programs": len(out_programs),
        "out_universities": len(out_unis),
        "bvi_out_rows": len(bvi_out_rows),
        "bvi_out_programs": len(bvi_out_programs),
        "bvi_lost_programs": len(lost),
        "top": [
            {
                "name": names[o],
                "rows": len(per[o]["rows"]),
                "programs": len(per[o]["programs"]),
                "universities": len(per[o]["unis"]),
                "bvi_programs": len(per[o]["bvi"]),
                "bvi_rows": len(per[o]["bvi_rows"]),
            }
            for o in ranked
        ],
    }


# ---------------------------------------------------------------- 4. где сосредоточены льготы

NO_PROFILE = "(профиль не указан)"


def concentration(links: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Пары «олимпиада + профиль» по числу направлений с БВИ — для победителей и для призёров."""
    pairs: dict[str, dict[tuple[str, str], set[int]]] = {
        "winners": defaultdict(set),
        "prizes": defaultdict(set),
    }
    unstated: set[int] = set()
    by_olympiad: dict[str, set[tuple[int, int]]] = defaultdict(set)
    all_links: set[tuple[int, int]] = set()
    for link in links:
        if link["benefit_type"] != BVI:
            continue
        key = (link["program_id"], link["olympiad_id"])
        all_links.add(key)
        by_olympiad[link["olympiad"]].add(key)
        roles = prize_roles(link)
        if roles is None:
            if not (link["role"] or "").strip():
                unstated.add(link["benefit_id"])
            continue
        profile = link["profile"].strip() if is_real_profile(link["profile"]) else NO_PROFILE
        pair = (link["olympiad"], profile)
        if Role.WINNER in roles:
            pairs["winners"][pair].add(link["program_id"])
        if Role.PRIZE in roles:
            pairs["prizes"][pair].add(link["program_id"])

    ordered = sorted(by_olympiad.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    cumulative, running = [], 0
    for _, keys in ordered:
        running += len(keys)
        cumulative.append(round(running / len(all_links), 4))
    out: dict[str, Any] = {
        "bvi_links": len(all_links),
        "olympiads_with_bvi": len(ordered),
        "role_unstated_rows": len(unstated),
        "top_olympiads": [{"name": n, "links": len(k)} for n, k in ordered[:TOP]],
        "top10_share": cumulative[TOP - 1] if len(cumulative) >= TOP else None,
        "olympiads_for_50": next((i + 1 for i, c in enumerate(cumulative) if c >= 0.5), None),
        "olympiads_for_80": next((i + 1 for i, c in enumerate(cumulative) if c >= 0.8), None),
        "cumulative": cumulative[:30],
    }
    for role, found in pairs.items():
        ranked = sorted(found.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        total = sum(len(v) for v in found.values())
        out[role] = {
            "pairs": len(found),
            "top": [{"olympiad": o, "profile": p, "programs": len(v)} for (o, p), v in ranked[:15]],
            "top15_share": share(sum(len(v) for _, v in ranked[:15]), total),
        }
    return out


# ---------------------------------------------------------------- 5. ИИ-часть по готовым отчётам

FIELD_TITLES = {
    "winner_role": "кому",
    "levels": "уровень",
    "grades": "класс",
    "ege_min": "порог ЕГЭ",
    "ege_subjects": "предметы ЕГЭ",
}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def ai_metrics(eval_dir: Path = EVAL_DIR) -> dict[str, Any]:
    """Метрики извлечения и помощника из сохранённых отчётов; новых прогонов нет."""
    out: dict[str, Any] = {"extraction": {}, "assistant": {}}
    for name, directory, kind in (
        ("dev_extract", "extraction", "baseline-extract.json"),
        ("dev_table", "extraction", "baseline-xlsx.json"),
        ("holdout_extract", "holdout", "baseline-extract.json"),
        ("holdout_table", "holdout", "baseline-xlsx.json"),
    ):
        total = _read(eval_dir / directory / kind)["total"]
        out["extraction"][name] = {
            "gold": total["gold"],
            "pred": total["pred"],
            "matched": total["matched"],
            "precision": _round(total["precision"]),
            "recall": _round(total["recall"]),
            "role_wrong": total["role_wrong"],
            "fields": {f: _round(v) for f, v in total["fields"].items()},
        }
    summary = _read(eval_dir / "assistant" / "summary.json")
    models = []
    for m in summary["models"]:
        cost = m["cost_per_answer"]
        models.append(
            {
                **{k: m[k] for k in ("model", "cases", "passed_share", "error_share_raw")},
                "error_share_final": m["error_share_final"],
                "answer_p95": round(m["answer_p95"], 1),
                "cost_per_answer": cost,
                "cost_per_student_year": {str(n): round(cost * n, 4) for n in MESSAGES_PER_STUDENT},
                "gate_passed": m["gate_passed"],
            }
        )
    chosen = summary["summary"]
    out["assistant"] = {
        "selected": summary["selected"],
        "messages_per_student": list(MESSAGES_PER_STUDENT),
        "base_messages": BASE_MESSAGES,
        "models": models,
        "selected_summary": {k: _round(v) for k, v in chosen.items()},
        "selected_cost_per_student_year": round(chosen["cost_per_answer"] * BASE_MESSAGES, 4),
        "selected_cost_per_1000_students": round(
            chosen["cost_per_answer"] * BASE_MESSAGES * 1000, 1
        ),
    }
    return out


def _round(value: Any) -> Any:
    return round(value, 4) if isinstance(value, float) else value


# ---------------------------------------------------------------- запуск


def analyse(
    conn: psycopg.Connection[Any],
    eval_dir: Path = EVAL_DIR,
    old_conn: psycopg.Connection[Any] | None = None,
) -> dict[str, Any]:
    """old_conn — база без слоя document (сборка из одного XLSX); без неё старая таблица
    берётся из основной базы, где документы уже заменили часть её строк."""
    links = load_links(conn)
    return {
        "database": {
            "links": len(links),
            "programs": len({r["program_id"] for r in links}),
            "universities": len({r["university_id"] for r in links}),
        },
        "prize_2027": prize_2027(links),
        "old_table": old_table(
            old_conn or conn,
            {"development": eval_dir / "extraction", "holdout": eval_dir / "holdout"},
        ),
        "list_2026_27": list_change(links),
        "concentration": concentration(links),
        "ai": ai_metrics(eval_dir),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="olymp-analysis", description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=RESULTS_FILE)
    ap.add_argument("--eval-dir", type=Path, default=EVAL_DIR)
    ap.add_argument("--img-dir", type=Path, default=IMG_DIR)
    ap.add_argument("--charts", action="store_true", help="после расчёта нарисовать графики")
    ap.add_argument("--charts-only", action="store_true", help="графики из готового файла --out")
    ap.add_argument("--db-url", help="по умолчанию OLYMP_DATABASE_URL")
    ap.add_argument(
        "--old-db-url",
        help="база, собранная из одного XLSX (OLYMP_DATA_DIR с пустым extracted/): старая таблица",
    )
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.charts_only:
        with psycopg.connect(psycopg_dsn(args.db_url)) as conn:
            if args.old_db_url:
                with psycopg.connect(psycopg_dsn(args.old_db_url)) as old_conn:
                    results = analyse(conn, args.eval_dir, old_conn)
            else:
                results = analyse(conn, args.eval_dir)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(results, ensure_ascii=False, indent=1, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        print(f"Результаты: {args.out}")
    if args.charts or args.charts_only:
        try:
            from .analysis_charts import draw_all
        except ImportError as exc:
            print(
                f"Нужен matplotlib: uv run --with matplotlib olymp-analysis ({exc})",
                file=sys.stderr,
            )
            return 1
        for path in draw_all(json.loads(args.out.read_text(encoding="utf-8")), args.img_dir):
            print(f"График: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
