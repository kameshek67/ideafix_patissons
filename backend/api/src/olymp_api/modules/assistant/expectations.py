"""Ожидания набора вопросов: факты из базы, которые должны быть в ответе, и запрещённые утверждения.

Ожидания не пишутся руками: их выводит `build_cases` запросами к собранной базе и кладёт в
файл случаев как данные. Здесь они читаются и сверяются с ответом. Сверка идёт по утверждениям
предложений (claims.extract): «вуз × олимпиада × вид льготы × кому × порог», а не по словам.

Факт или запрет (`Fact`) — одна и та же форма:
- `universities`, `olympiads` — названия из базы (короткие, как в словаре). Для факта нужно
  назвать `min` вузов из списка (по умолчанию один); олимпиада из вопроса может не
  повторяться в ответе, но названная другая не засчитывается. Для запрета нужен и вуз, и
  олимпиада из списков (если списки заданы);
- `benefit` — «БВИ» или «100 баллов»;
- `who` — кому: winners (только победителям), both и prizers (и призёрам), only_winners
  (запрет: «только победителям», когда призёры тоже есть);
- `min_ege`, `subject` — порог ЕГЭ и подтверждающий предмет;
- `db` — откуда ожидание (число строк, роли, пороги): для людей, в сверке не участвует.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .claims import Claim, by_sentence, extract
from .factcheck import Vocabulary

# «в базе нет данных» своими словами: так модель говорит, когда ничего не нашла
NO_DATA_MARKERS = re.compile(
    r"нет\s+данных|данных\s+нет|в\s+базе\s+(?:\w+\s+)?(?:этого\s+|этой\s+|таких\s+|такой\s+)?нет"
    r"|нет\s+в\s+базе|не\s+наш[ёеол]\w*|в\s+базе\s+не|не\s+указан\w*|отсутству\w+\s+в\s+базе"
    r"|не\s+(?:могу|смог\w*)\s+найти|не\s+знаю|не\s+вижу",
    re.I,
)
FACT_FIELDS = {"universities", "olympiads", "benefit", "who", "min_ege", "subject", "min", "db"}
DATA_MODES = ("present", "absent", "none")


@dataclass(frozen=True)
class Fact:
    universities: tuple[str, ...] = ()
    olympiads: tuple[str, ...] = ()
    benefit: str | None = None
    who: str | None = None
    min_ege: int | None = None
    subject: str | None = None
    min: int = 1
    db: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @classmethod
    def parse(cls, row: dict[str, Any]) -> "Fact":
        unknown = set(row) - FACT_FIELDS
        if unknown:
            raise ValueError(f"неизвестные поля факта: {sorted(unknown)}")
        return cls(
            universities=tuple(row.get("universities") or ()),
            olympiads=tuple(row.get("olympiads") or ()),
            benefit=row.get("benefit"),
            who=row.get("who"),
            min_ege=row.get("min_ege"),
            subject=row.get("subject"),
            min=int(row.get("min") or 1),
            db=dict(row.get("db") or {}),
        )

    def describe(self) -> str:
        parts = [
            "/".join(self.universities[:3]) + ("…" if len(self.universities) > 3 else ""),
            "/".join(self.olympiads[:2]),
            self.benefit or "",
            f"кому: {self.who}" if self.who else "",
            f"{self.subject or 'ЕГЭ'} ≥ {self.min_ege}" if self.min_ege else "",
        ]
        return " · ".join(part for part in parts if part)


@dataclass
class Spec:
    """Ожидания одного вопроса."""

    data: str = "none"  # present — в базе есть, absent — нет, none — вопрос не про данные
    facts: list[Fact] = field(default_factory=list)
    forbidden: list[Fact] = field(default_factory=list)
    forbidden_phrases: list[str] = field(default_factory=list)  # только для подмены правил
    refuse: bool = False  # ответ вежливо отказывает, без поиска
    clarify: bool = False  # ответ — уточняющий вопрос, без поиска

    @classmethod
    def parse(cls, row: dict[str, Any]) -> "Spec":
        unknown = set(row) - {
            "data",
            "facts",
            "forbidden",
            "forbidden_phrases",
            "refuse",
            "clarify",
        }
        if unknown:
            raise ValueError(f"неизвестные поля ожиданий: {sorted(unknown)}")
        data = row.get("data", "none")
        if data not in DATA_MODES:
            raise ValueError(f"data: одно из {DATA_MODES}, а не {data!r}")
        return cls(
            data=data,
            facts=[Fact.parse(f) for f in row.get("facts") or []],
            forbidden=[Fact.parse(f) for f in row.get("forbidden") or []],
            forbidden_phrases=list(row.get("forbidden_phrases") or []),
            refuse=bool(row.get("refuse")),
            clarify=bool(row.get("clarify")),
        )


@dataclass
class Assessment:
    """Что нашлось в ответе из ожиданий."""

    found: list[bool] = field(default_factory=list)  # по фактам
    missing: list[str] = field(default_factory=list)
    hits: list[str] = field(default_factory=list)  # сработавшие запреты
    hits_who: int = 0  # из них про «кому»
    hits_type: int = 0  # из них про вид льготы
    no_data: bool = False  # в ответе сказано «в базе нет данных»
    asserts: bool = False  # в ответе есть утверждение о льготе

    @property
    def facts_found(self) -> int:
        return sum(self.found)


def names(vocab: Vocabulary, kind: Any, labels: Sequence[str]) -> dict[str, frozenset[int]]:
    return {label: frozenset(e.id for e in vocab.entities(kind, label)) for label in labels}


def holds(fact: Fact, claim: Claim) -> bool:
    """Остальные поля факта в утверждении: вид льготы, кому, порог."""
    if fact.benefit and fact.benefit not in claim.types:
        return False
    if fact.who in {"both", "prizers"} and not claim.prizers:
        return False
    if fact.who == "winners" and not (claim.winners and not claim.prizers):
        return False
    if fact.who == "only_winners" and not (claim.only_winners and not claim.prizers):
        return False
    if fact.min_ege is not None:
        match = [
            (s, n)
            for s, n, _ in claim.thresholds
            if n == fact.min_ege and (fact.subject is None or s in (None, fact.subject))
        ]
        if not match:
            return False
    return True


def stated(fact: Fact, claims: Sequence[Claim], vocab: Vocabulary) -> bool:
    """Факт назван в ответе: нужное число названий из списка (min) и всё остальное — в одном
    предложении. Считаются названия того списка, где их больше: вузы для олимпиады или
    олимпиады для вуза."""
    unis = names(vocab, "university", fact.universities)
    olys = names(vocab, "olympiad", fact.olympiads)
    count_olympiads = len(olys) > len(unis)
    covered: set[str] = set()
    for claim in claims:
        if not claim.positive or not holds(fact, claim):
            continue
        if count_olympiads:
            if (
                unis
                and claim.universities
                and not any(claim.universities & i for i in unis.values())
            ):
                continue
            covered |= {n for n, ids in olys.items() if claim.olympiads & ids}
        else:
            if olys and claim.olympiads and not any(claim.olympiads & i for i in olys.values()):
                continue
            if unis:
                covered |= {n for n, ids in unis.items() if claim.universities & ids}
            elif fact.benefit or fact.who or fact.min_ege:
                covered.add("*")
    return len(covered) >= fact.min


def forbidden_hit(fact: Fact, claims: Sequence[Claim], vocab: Vocabulary) -> Claim | None:
    """Предложение, которое говорит запрещённое: названные в запрете вуз и олимпиада и всё
    остальное разом."""
    unis = names(vocab, "university", fact.universities)
    olys = names(vocab, "olympiad", fact.olympiads)
    # «ВШЭ» — это четыре кампуса: запрет срабатывает, только если запрещены все, о ком речь
    banned_unis = frozenset().union(*unis.values())
    banned_olys = frozenset().union(*olys.values())
    for claim in claims:
        if not claim.positive or not (claim.asserts or fact.benefit) or not holds(fact, claim):
            continue
        if unis and not (claim.universities and claim.universities <= banned_unis):
            continue
        if olys and not (claim.olympiads and claim.olympiads <= banned_olys):
            continue
        if not unis and not olys and not (fact.benefit or fact.who or fact.min_ege):
            continue
        return claim
    return None


def assess(spec: Spec, answer: str, vocab: Vocabulary) -> Assessment:
    """Сверка ответа с ожиданиями вопроса."""
    mentions = vocab.find(answer)
    claims = by_sentence(extract(answer, mentions))
    result = Assessment(no_data=bool(NO_DATA_MARKERS.search(answer)))
    result.asserts = any(c.positive and c.asserts and c.types for c in claims)
    for fact in spec.facts:
        ok = stated(fact, claims, vocab)
        result.found.append(ok)
        if not ok:
            result.missing.append(fact.describe())
    for fact in spec.forbidden:
        if claim := forbidden_hit(fact, claims, vocab):
            result.hits.append(f"{fact.describe()}: «{claim.sentence[:120]}»")
            result.hits_who += fact.who in {"prizers", "both", "only_winners", "winners"}
            result.hits_type += bool(fact.benefit) and not fact.who
    lowered = answer.lower()
    result.hits += [f"фраза «{p}»" for p in spec.forbidden_phrases if p.lower() in lowered]
    return result
