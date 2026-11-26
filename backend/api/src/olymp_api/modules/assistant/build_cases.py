"""Сборка набора вопросов помощника (B7): `just assistant-cases`.

Вопросы пишут люди: backend/api/tests/assistant_questions.jsonl. Ожидания — какие факты должны быть
в ответе и каких утверждений быть не должно — команда выводит запросами к собранной базе и пишет
в backend/api/tests/assistant_cases.jsonl как данные. Руками из головы их не пишем: после пересборки
базы команда запускается снова, а `git diff` набора показывает, что в данных изменилось.

Строка вопросов — JSON: `id`, `persona` (школьник, родитель…), `kind`, `turns` (реплики ученика),
`about` (о чём вопрос: названия как в базе), необязательные `tools`, `max_tools`. Виды:

- `pair` — вуз × олимпиада (`university`, `olympiad`, `benefit`, `threshold`, `data`): что даёт и кому;
  пары без строк в базе — вопрос «без данных»;
- `olympiad_unis` — в каких вузах олимпиада даёт льготу (`olympiad`, `benefit`, `who`,
  `city`): вузы из базы и запрет на вузы вне перечня олимпиады;
- `uni_olympiads` и `program` — какие олимпиады дают льготу в вузе (на направлении `like`);
- `hobby` — подбор по увлечению (`like`: куски названий профилей и олимпиад);
- `no_data_olympiad` — олимпиады нет в базе (`probe`: куски названия; в базе их быть не должно);
- `refuse`, `clarify` — не про данные (`forbidden_phrases` — только для подмены правил).
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from olymp_api.db import fetch_all, make_engine
from olymp_api.settings import Settings

from .claims import BVI, POINTS_100, SPECIAL, Ledger, Row
from .evaluate import CASES_SET, QUESTIONS_SET

THRESHOLDS = (70, 75, 80, 85, 90, 95)  # из них запрещаются не названные в базе
MAX_NAMES = 40  # названий в одном запрете: самые частые в ответах
OTHER = {BVI: POINTS_100, POINTS_100: BVI}


class Base:
    """Справочники и строки условий всей базы: ожидания считаются по ним."""

    def __init__(self) -> None:
        self.universities: dict[int, str] = {}
        self.cities: dict[int, str] = {}
        self.olympiads: dict[int, str] = {}
        self.mentions: dict[int, int] = {}
        self.ledger = Ledger()

    async def load(self, session: AsyncSession) -> None:
        for row in await fetch_all(session, "SELECT id, name, short_name, city FROM universities"):
            short = row["short_name"]
            self.universities[row["id"]] = (
                row["name"] if short.endswith("…") else short or row["name"]
            )
            self.cities[row["id"]] = row["city"]
        for row in await fetch_all(
            session, "SELECT id, short_name, canonical_name, mentions FROM olympiads"
        ):
            self.olympiads[row["id"]] = row["short_name"] or row["canonical_name"]
            self.mentions[row["id"]] = row["mentions"]
        loader = Ledger(session)
        await loader.load(set(self.universities), set(self.olympiads))
        self.ledger.rows = loader.rows
        self.ledger._everything = True

    def uni(self, name: str) -> int:
        return one(self.universities, name, "вуз")

    def oly(self, name: str) -> int:
        return one(self.olympiads, name, "олимпиада")

    def rows(self, unis: set[int] | None = None, olys: set[int] | None = None) -> list[Row]:
        found = self.ledger.select(unis or set(), olys or set())
        return found if unis or olys else self.ledger.rows

    def linked(self, olympiad: int, benefit: str | None = None) -> dict[int, list[Row]]:
        """Вузы, у которых есть строки этой олимпиады: вуз → строки."""
        out: dict[int, list[Row]] = {}
        for row in self.ledger.rows:
            if row.olympiad_id == olympiad and (not benefit or fits(row, benefit)):
                out.setdefault(row.university_id, []).append(row)
        return out


def one(names: dict[int, str], name: str, what: str) -> int:
    found = [i for i, n in names.items() if n == name]
    if len(found) != 1:
        raise ValueError(f"{what} «{name}»: в базе {len(found)} совпадений по короткому названию")
    return found[0]


def fits(row: Row, benefit: str) -> bool:
    return row.kind == benefit or row.kind == SPECIAL


def prizer_capable(row: Row) -> bool:
    return row.role in {"both", "prizers"}


def summary(rows: list[Row]) -> dict[str, Any]:
    """Откуда ожидание: сколько строк, кому, какие пороги и предметы."""
    return {
        "rows": len(rows),
        "kinds": dict(Counter(r.kind for r in rows)),
        "roles": dict(Counter(r.role for r in rows)),
        "min_ege": sorted({r.min_ege for r in rows if r.min_ege is not None}),
    }


def pure_role(rows: list[Row]) -> str | None:
    roles = {r.role for r in rows}
    return roles.pop() if len(roles) == 1 and "unknown" not in roles else None


def names_of(base: Base, ids: Any) -> list[str]:
    """Названия вузов по id: по алфавиту, чтобы набор не менялся от порядка в базе."""
    return sorted(base.universities[i] for i in ids)


def popular(base: Base, ids: Any, limit: int | None = None) -> list[str]:
    """Названия олимпиад: сначала самые частые в данных (их модель назовёт скорее всего)."""
    ordered = sorted(ids, key=lambda i: (-base.mentions[i], base.olympiads[i]))
    return [base.olympiads[i] for i in ordered[:limit]]


def pair_expect(base: Base, row: dict[str, Any]) -> dict[str, Any]:
    about = row["about"]
    uni, oly = base.uni(about["university"]), base.oly(about["olympiad"])
    uname, oname = about["university"], about["olympiad"]
    rows = base.rows({uni}, {oly})
    if about.get("data") and about["data"] != ("present" if rows else "absent"):
        raise ValueError(f"{row['id']}: в базе по этой паре {'есть' if rows else 'нет'} строк")
    facts: list[dict[str, Any]] = []
    forbidden: list[dict[str, Any]] = []
    if not rows:
        forbidden = [
            {"universities": [uname], "olympiads": [oname], "benefit": kind}
            for kind in (BVI, POINTS_100)
        ]
        return {"data": "absent", "forbidden": forbidden}
    # без вида льготы в вопросе в ответе обязательна главная: БВИ, а если её нет — 100 баллов
    required = about.get("benefit") or (BVI if any(fits(r, BVI) for r in rows) else POINTS_100)
    for kind in (BVI, POINTS_100):
        typed = [r for r in rows if fits(r, kind)]
        if not typed:
            forbidden.append({"universities": [uname], "olympiads": [oname], "benefit": kind})
            continue
        role = pure_role(typed)
        if kind == required:
            fact: dict[str, Any] = {
                "universities": [uname],
                "olympiads": [oname],
                "benefit": kind,
                "db": summary(typed),
            }
            if role:
                fact["who"] = role
            scores = {r.min_ege for r in typed}
            if about.get("threshold") and len(scores) == 1 and None not in scores:
                fact["min_ege"] = scores.pop()
            facts.append(fact)
        if role == "winners":
            forbidden.append(
                {"universities": [uname], "olympiads": [oname], "benefit": kind, "who": "prizers"}
            )
        elif role in {"both", "prizers"}:
            forbidden.append(
                {
                    "universities": [uname],
                    "olympiads": [oname],
                    "benefit": kind,
                    "who": "only_winners",
                }
            )
    if about.get("threshold"):
        known = {r.min_ege for r in rows if r.min_ege is not None}
        forbidden += [
            {"universities": [uname], "olympiads": [oname], "min_ege": n}
            for n in THRESHOLDS
            if known and n not in known
        ]
    return {"data": "present", "facts": facts, "forbidden": forbidden}


def olympiad_unis_expect(base: Base, row: dict[str, Any]) -> dict[str, Any]:
    about = row["about"]
    oly, oname = base.oly(about["olympiad"]), about["olympiad"]
    kind = about.get("benefit", BVI)
    linked = base.linked(oly, kind)
    prizer = about.get("who") == "prizers"
    if prizer:
        suited = {u: rs for u, rs in linked.items() if any(prizer_capable(r) for r in rs)}
    else:
        suited = linked
    city = about.get("city")
    if city:
        suited = {u: rs for u, rs in suited.items() if base.cities[u] == city}
    if not suited:
        raise ValueError(f"{row['id']}: в базе нет вузов под условия {about}")
    facts: list[dict[str, Any]] = [
        {
            "universities": names_of(base, suited),
            "olympiads": [oname],
            "benefit": kind,
            "min": min(2, len(suited)),
            "db": {
                "universities": len(suited),
                **summary([r for rs in suited.values() for r in rs]),
            },
        }
    ]
    other = [u for u in base.universities if u not in base.linked(oly)]
    forbidden: list[dict[str, Any]] = [
        {"universities": names_of(base, other), "olympiads": [oname]}
    ]
    if prizer:
        winners_only = [
            u
            for u, rs in linked.items()
            if not any(prizer_capable(r) or r.role == "unknown" for r in rs)
        ]
        if winners_only:
            forbidden.append(
                {
                    "universities": names_of(base, winners_only),
                    "olympiads": [oname],
                    "benefit": kind,
                    "who": "prizers",
                }
            )
    if not any(fits(r, OTHER[kind]) for r in base.rows(None, {oly})):
        forbidden.append({"olympiads": [oname], "benefit": OTHER[kind]})
    return {"data": "present", "facts": facts, "forbidden": forbidden}


async def program_olympiads(
    session: AsyncSession, uni: int, like: str, benefit: str | None
) -> Counter[int]:
    rows = await fetch_all(
        session,
        """SELECT bo.olympiad_id FROM benefits b
           JOIN programs p ON p.id = b.program_id
           JOIN benefit_olympiads bo ON bo.benefit_id = b.id
           WHERE p.university_id = :u AND p.faculty_or_direction ILIKE :like
             AND b.layer <> 'raw' AND (CAST(:t AS text) IS NULL OR b.benefit_type = :t)""",
        {"u": uni, "like": f"%{like}%", "t": benefit},
    )
    return Counter(r["olympiad_id"] for r in rows)


async def uni_olympiads_expect(
    session: AsyncSession, base: Base, row: dict[str, Any]
) -> dict[str, Any]:
    about = row["about"]
    uni, uname = base.uni(about["university"]), about["university"]
    kind = about.get("benefit")
    if about.get("like"):
        counts = await program_olympiads(session, uni, about["like"], kind)
    else:
        counts = Counter(
            r.olympiad_id
            for r in base.rows({uni})
            if r.olympiad_id is not None and (not kind or fits(r, kind))
        )
    if not counts:
        raise ValueError(f"{row['id']}: в базе нет олимпиад под условия {about}")
    mine = {r.olympiad_id for r in base.rows({uni}) if r.olympiad_id is not None}
    unlinked = [o for o in base.olympiads if o not in mine]
    fact: dict[str, Any] = {
        "universities": [uname],
        "olympiads": popular(base, counts),
        "min": min(2, len(counts)),
        "db": {"olympiads": len(counts), "rows": sum(counts.values())},
    }
    if kind:
        fact["benefit"] = kind
    forbidden: list[dict[str, Any]] = [
        {"universities": [uname], "olympiads": popular(base, unlinked, MAX_NAMES)}
    ]
    return {"data": "present", "facts": [fact], "forbidden": forbidden}


async def hobby_expect(session: AsyncSession, base: Base, row: dict[str, Any]) -> dict[str, Any]:
    patterns = [f"%{item}%" for item in row["about"]["like"]]
    found = await fetch_all(
        session,
        """SELECT DISTINCT o.id FROM olympiads o
           LEFT JOIN olympiad_profiles pr ON pr.olympiad_id = o.id
           LEFT JOIN olympiad_tracks t ON t.olympiad_id = o.id
           WHERE pr.name ILIKE ANY(:p) OR t.name ILIKE ANY(:p) OR o.canonical_name ILIKE ANY(:p)""",
        {"p": patterns},
    )
    ids = [r["id"] for r in found]
    if not ids:
        raise ValueError(f"{row['id']}: в базе нет олимпиад по {patterns}")
    fact = {
        "olympiads": popular(base, ids),
        "min": 1,
        "db": {"olympiads": len(ids)},
    }
    return {"data": "present", "facts": [fact]}


async def no_data_olympiad_expect(session: AsyncSession, row: dict[str, Any]) -> dict[str, Any]:
    probe = [f"%{item}%" for item in row["about"]["probe"]]
    found = await fetch_all(
        session,
        """SELECT o.canonical_name FROM olympiads o WHERE o.canonical_name ILIKE ANY(:p)
           OR o.short_name ILIKE ANY(:p)
           UNION SELECT alias FROM olympiad_aliases WHERE alias ILIKE ANY(:p)""",
        {"p": probe},
    )
    if found:
        raise ValueError(f"{row['id']}: в базе есть {[r['canonical_name'] for r in found][:3]}")
    return {"data": "absent"}


async def build_one(session: AsyncSession, base: Base, row: dict[str, Any]) -> dict[str, Any]:
    kind = row["kind"]
    match kind:
        case "pair":
            expect = pair_expect(base, row)
        case "olympiad_unis":
            expect = olympiad_unis_expect(base, row)
        case "uni_olympiads" | "program":
            expect = await uni_olympiads_expect(session, base, row)
        case "hobby":
            expect = await hobby_expect(session, base, row)
        case "no_data_olympiad":
            expect = await no_data_olympiad_expect(session, row)
        case "refuse":
            expect = {"refuse": True, "forbidden_phrases": row["about"].get("forbidden", [])}
        case "clarify":
            expect = {"clarify": True}
        case _:
            raise ValueError(f"{row['id']}: неизвестный вид {kind!r}")
    case: dict[str, Any] = {
        key: row[key] for key in ("id", "kind", "persona", "turns") if key in row
    }
    case.update({key: row[key] for key in ("tools", "max_tools") if key in row})
    case["about"] = row.get("about", {})
    case["expect"] = expect
    return case


async def build(session: AsyncSession, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = Base()
    await base.load(session)
    ids = [q["id"] for q in questions]
    if len(set(ids)) != len(ids):
        raise ValueError(f"повторяются id: {[i for i, n in Counter(ids).items() if n > 1]}")
    cases, errors = [], []
    for row in questions:
        try:
            cases.append(await build_one(session, base, row))
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        raise ValueError("\n".join(errors))
    return cases


def load_questions(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def dump(cases: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=QUESTIONS_SET)
    parser.add_argument("--out", type=Path, default=CASES_SET)
    args = parser.parse_args()
    engine = make_engine(Settings())
    if engine is None:
        print("Нужен OLYMP_DATABASE_URL (собранная база)")
        return 2
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        cases = await build(session, load_questions(args.questions))
    await engine.dispose()
    args.out.write_text(dump(cases), encoding="utf-8")
    kinds = Counter(case["kind"] for case in cases)
    print(f"{len(cases)} вопросов -> {args.out}: {dict(kinds)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
