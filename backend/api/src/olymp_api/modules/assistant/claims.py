"""Проверка утверждений ответа о льготах по базе (B7): самые дорогие ошибки помощника.

Фактчекер (factcheck.py) смотрит, есть ли названия и числа в данных диалога. Этого мало: каждое
слово может быть из базы, а утверждение — неверным. Здесь утверждения проверяются по строкам
условий самой базы:

- `role` — «победителям и призёрам», когда в базе только победители (и «только победителям»,
  когда призёры тоже есть);
- `benefit_type` — «100 баллов» вместо БВИ и наоборот;
- `threshold` — порог ЕГЭ не по тому предмету или не то число;
- `not_listed` — олимпиада, которой нет в перечне вуза.

Проверки консервативны: утверждение считается верным, если его подтверждает хоть одна строка,
а непонятное (нет роли, предмета или порога в строке) верным. Предложение с отрицанием не
проверяется. Если в предложении несколько вузов и несколько олимпиад, пара неоднозначна и
пропускается. Логика чистая; строки грузит `Ledger.ensure` одним запросом на ответ.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import structlog
from olymp_domain import squash
from sqlalchemy.ext.asyncio import AsyncSession

from olymp_api.db import fetch_all

from .factcheck import Mention, Violation, Vocabulary, _fact_numbers, sentences

log = structlog.get_logger()

BVI = "БВИ"
POINTS_100 = "100 баллов"
SPECIAL = "Особое право (БВИ/100)"  # подходит и как БВИ, и как 100 баллов
WINNERS, BOTH, PRIZERS, UNKNOWN = "winners", "both", "prizers", "unknown"

# предметы: ключ → слово в тексте ответа и в строках базы
SUBJECTS = {
    "математика": r"математик",
    "информатика": r"информатик|\bикт\b",
    "физика": r"физик(?!о)",
    "химия": r"хими",
    "биология": r"биолог",
    "история": r"истори",
    "обществознание": r"обществозн",
    "литература": r"литератур",
    "русский язык": r"русск\w+\s+язык",
    "иностранный язык": r"иностран|английск|немецк|французск|испанск|китайск",
    "география": r"географ",
}
_SUBJECT_RES = {key: re.compile(pattern, re.I) for key, pattern in SUBJECTS.items()}

_BVI = re.compile(r"(?<![а-яёА-ЯЁ])БВИ(?![а-яёА-ЯЁ])|без\s+вступительн\w*|без\s+экзамен\w*", re.I)
_POINTS_100 = re.compile(
    r"(?<!\d)100\s*(?:-?\s*)?(?:балл\w*|за\s+ЕГЭ)|стобалльн\w*|максимальн\w+\s+балл\w*", re.I
)
_WINNER = re.compile(r"победител\w*|победивш\w*", re.I)
_PRIZER = re.compile(r"призёр\w*|призер\w*", re.I)
_ONLY_WINNERS = re.compile(r"(?:только|лишь|исключительно)\s+(?:для\s+)?победител\w*", re.I)
_ONLY_WINNERS_ROW = re.compile(r"только\s+победител|призёр\w*\s+исключ|призер\w*\s+исключ", re.I)
# «не ниже», «не менее», «не только» отрицанием не считаются
_NEGATION = re.compile(
    r"(?<![а-яё])(?:не(?!\s+(?:ниже|менее|меньше|только|раньше|позже))|нет|ни|нельзя"
    r"|отсутств\w+|исключ\w+|без\s+данных)(?![а-яё])",
    re.I,
)
_CLAUSE = re.compile(r"[;,]|\s(?:а|но|однако)\s", re.I)
_BENEFIT_WORD = re.compile(
    r"льгот|даёт|дает|дают|принима\w+|засчитыва\w+|зачисл\w+|поступ\w+|без\s+(?:вступительн|экзамен)",
    re.I,
)
_LIST_ITEM = re.compile(r"[-•*–—]\s+\S")
_EGE_CONTEXT = re.compile(r"ЕГЭ|порог|подтвержд|минимум|баллов|балл", re.I)


def subjects_in(text: str) -> list[tuple[int, str]]:
    """Предметы в тексте: (позиция, ключ) в порядке появления."""
    found = [(m.start(), key) for key, rx in _SUBJECT_RES.items() for m in rx.finditer(text)]
    return sorted(found)


def role_kind(text: str) -> str:
    """Кому дают льготу по строке базы: winners / both / prizers / unknown (роль не указана)."""
    winners, prizers = bool(_WINNER.search(text)), bool(_PRIZER.search(text))
    if winners and prizers:
        return WINNERS if _ONLY_WINNERS_ROW.search(text) else BOTH
    if winners:
        return WINNERS
    return PRIZERS if prizers else UNKNOWN


@dataclass(frozen=True)
class Row:
    """Строка условий базы, свёрнутая до того, что проверяется: вуз, олимпиада, вид льготы, кому,
    подтверждающие предметы (пусто — не указаны) и порог ЕГЭ (None — не указан)."""

    university_id: int
    olympiad_id: int | None
    kind: str
    role: str  # winners / both / prizers / unknown
    subjects: frozenset[str] = frozenset()
    min_ege: int | None = None

    @classmethod
    def build(
        cls,
        university_id: int,
        olympiad_id: int | None,
        kind: str,
        role_text: str,
        subject_text: str,
        min_ege: int | None,
    ) -> "Row":
        return cls(
            university_id,
            olympiad_id,
            kind,
            role_kind(role_text or ""),
            frozenset(key for _, key in subjects_in(subject_text or "")),
            min_ege,
        )


def kind_matches(row: Row, kind: str) -> bool:
    return row.kind == kind or row.kind == SPECIAL


def label(kinds: Iterable[str]) -> str:
    return ", ".join(sorted(set(kinds))) or "—"


class Ledger:
    """Строки условий для вузов и олимпиад, которые названы в ответе.

    ensure() догружает строки; пока вуз или олимпиада не загружены, проверять по ним нельзя
    (`known`): иначе не загрузившаяся строка выглядела бы как «в перечне нет».
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session
        self.rows: list[Row] = []
        self.universities: set[int] = set()
        self.olympiads: set[int] = set()
        self._everything = False

    @classmethod
    def of(cls, rows: Iterable[Row]) -> "Ledger":
        """Готовый набор строк (тесты): загруженным считается всё."""
        ledger = cls()
        ledger.rows = list(rows)
        ledger._everything = True
        return ledger

    def known(self, universities: Iterable[int], olympiads: Iterable[int]) -> bool:
        return self._everything or (
            set(universities) <= self.universities and set(olympiads) <= self.olympiads
        )

    def select(self, universities: Iterable[int], olympiads: Iterable[int]) -> list[Row]:
        """Строки вузов и олимпиад; пустое множество — «любой». С олимпиадой — только строки,
        привязанные к ней."""
        unis, olys = set(universities), set(olympiads)
        return [
            row
            for row in self.rows
            if (not unis or row.university_id in unis)
            and (not olys or row.olympiad_id in olys)
            and (olys or unis)
        ]

    async def ensure(self, answer: str, vocab: Vocabulary) -> None:
        """Догружает строки для названий из ответа. Сбой базы проверку отключает, ответ нет."""
        if self.session is None or self._everything:
            return
        await self.load(*needed(answer, vocab))

    async def load(self, universities: set[int], olympiads: set[int]) -> None:
        """Все строки этих вузов и этих олимпиад (кроме уже загруженных)."""
        if self.session is None:
            return
        unis, olys = universities - self.universities, olympiads - self.olympiads
        if not unis and not olys:
            return
        try:
            rows = await fetch_all(self.session, LEDGER_SQL, {"u": list(unis), "o": list(olys)})
        except Exception as exc:  # noqa: BLE001 — проверка по базе не должна ломать ответ
            log.warning("assistant_claims_failed", reason=type(exc).__name__)
            return
        self.rows += [
            Row.build(
                r["university_id"],
                r["olympiad_id"],
                r["benefit_type"],
                r["role"],
                r["confirm_subject"],
                r["min_ege"],
            )
            for r in rows
        ]
        self.universities |= unis
        self.olympiads |= olys


# одна строка на сочетание полей: у ВШЭ тысячи строк базы сворачиваются в десятки
LEDGER_SQL = """
SELECT DISTINCT p.university_id, bo.olympiad_id, b.benefit_type,
       COALESCE(NULLIF(b.winner_role, ''), bo.winner_role, '') AS role,
       b.confirm_subject,
       COALESCE(b.min_ege_score::int, NULLIF(substring(b.min_ege from '\\d+'), '')::int) AS min_ege
FROM benefits b
JOIN programs p ON p.id = b.program_id
LEFT JOIN benefit_olympiads bo ON bo.benefit_id = b.id
WHERE b.layer <> 'raw' AND (p.university_id = ANY(:u) OR bo.olympiad_id = ANY(:o))
"""


def needed(answer: str, vocab: Vocabulary) -> tuple[set[int], set[int]]:
    """Id вузов и олимпиад, названных в ответе."""
    unis: set[int] = set()
    olys: set[int] = set()
    for mention in vocab.find(answer):
        for entity in mention.entities:
            (unis if entity.kind == "university" else olys).add(entity.id)
    return unis, olys


# ---------------------------------------------------------------- утверждения ответа


@dataclass
class Claim:
    """Утверждение одной части предложения: о чём (вузы, олимпиады) и что сказано."""

    sentence: str
    clause: str
    universities: frozenset[int] = frozenset()
    olympiads: frozenset[int] = frozenset()
    types: frozenset[str] = frozenset()
    winners: bool = False
    prizers: bool = False
    only_winners: bool = False
    subjects: frozenset[str] = frozenset()
    thresholds: list[tuple[str | None, int, str]] = field(
        default_factory=list
    )  # (предмет, балл, текст)
    role_text: str = ""
    positive: bool = True
    asserts: bool = False  # говорит о льготе: назван вид льготы или «даёт», «поступить»…
    ambiguous: bool = False  # названо несколько вузов или олимпиад: какая пара — неясно


@dataclass(frozen=True)
class Group:
    """Одно названное в тексте место или вуз: id и как названо."""

    ids: frozenset[int]
    fragment: str


def mention_ids(mention: Mention, kind: str) -> frozenset[int]:
    """Id сущностей названия. У «НИЯУ МИФИ» есть ещё «МИФИ — филиалы», у «ВШЭ» — четыре кампуса:
    если название совпало с подписью ровно одной сущности, речь о ней."""
    entities = [e for e in mention.entities if e.kind == kind]
    exact = [e for e in entities if squash(e.label) == squash(mention.fragment)]
    return frozenset(e.id for e in (exact if len(exact) == 1 else entities))


def mention_groups(mentions: Sequence[Mention], kind: str, start: int, end: int) -> list[Group]:
    """Различные названия нужного вида внутри [start, end); неоднозначные (вуз и олимпиада) —
    пропускаются."""
    groups: dict[frozenset[int], Group] = {}
    for m in mentions:
        if not start <= m.start < end:
            continue
        if {e.kind for e in m.entities} != {kind}:
            continue
        ids = mention_ids(m, kind)
        groups.setdefault(ids, Group(ids, m.fragment))
    return list(groups.values())


def resolve(
    mentions: Sequence[Mention], kind: str, clause: tuple[int, int], sentence: tuple[int, int]
) -> list[Group]:
    """Вуз или олимпиада, о которых говорит часть предложения: из неё самой, иначе из
    предложения. Названий может быть несколько («в ИТМО и МФТИ»); [] — не названо."""
    for span in (clause, sentence):
        if found := mention_groups(mentions, kind, *span):
            return found
    return []


def last_group(mentions: Sequence[Mention], kind: str, before: int) -> Group | None:
    """Последнее до позиции названное место или вуз: «- **ВШЭ**: БВИ…» после «Высшая проба даёт…»"""
    for m in reversed(mentions):
        if m.end <= before and {e.kind for e in m.entities} == {kind}:
            return Group(mention_ids(m, kind), m.fragment)
    return None


def clauses(text: str, a: int, b: int) -> list[tuple[int, int]]:
    """Части предложения [a, b): по запятым, точкам с запятой, скобкам и «а», «но»."""
    spans, start = [], a
    for match in _CLAUSE.finditer(text, a, b):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, b))
    return [(x, y) for x, y in spans if text[x:y].strip()]


def kinds_in(text: str) -> frozenset[str]:
    return frozenset(
        [
            *([BVI] if _BVI.search(text) else []),
            *([POINTS_100] if _POINTS_100.search(text) else []),
        ]
    )


def thresholds_in(text: str, fallback: Sequence[str]) -> list[tuple[str | None, int, str]]:
    """Пороги ЕГЭ в тексте: (предмет, балл, как написано). Предмет — ближайший в тексте, а если
    его нет — единственный предмет предложения (fallback)."""
    found = subjects_in(text)
    out = []
    for what, match, values in _fact_numbers(text):
        if what != "балл ЕГЭ" or not _EGE_CONTEXT.search(text):
            continue
        near = min(found, key=lambda s: abs(s[0] - match.start()), default=None)
        if near is not None and abs(near[0] - match.start()) <= 60:
            subject: str | None = near[1]
        else:
            subject = fallback[0] if len(fallback) == 1 else None
        out.append((subject, values[0], match.group(0).strip()))
    return out


def extract(answer: str, mentions: Sequence[Mention]) -> list[Claim]:
    """Утверждения ответа: по части предложения, со своим вузом и олимпиадой."""
    claims: list[Claim] = []
    for a, b in sentences(answer):
        sentence = answer[a:b].strip()
        sentence_kinds = kinds_in(sentence)
        sentence_subjects = list(dict.fromkeys(key for _, key in subjects_in(sentence)))
        for x, y in clauses(answer, a, b):
            text = answer[x:y]
            universities = resolve(mentions, "university", (x, y), (a, b))
            olympiads = resolve(mentions, "olympiad", (x, y), (a, b))
            if not universities and olympiads and (last := last_group(mentions, "university", a)):
                universities = [last]
            if not olympiads and universities and (last := last_group(mentions, "olympiad", a)):
                olympiads = [last]
            kinds = kinds_in(text) or (sentence_kinds if len(sentence_kinds) == 1 else frozenset())
            claim = Claim(
                sentence,
                text.strip(),
                frozenset(i for g in universities for i in g.ids),
                frozenset(i for g in olympiads for i in g.ids),
                kinds,
                winners=bool(_WINNER.search(text)),
                prizers=bool(_PRIZER.search(text)),
                only_winners=bool(_ONLY_WINNERS.search(text)),
                subjects=frozenset(key for _, key in subjects_in(text)),
                thresholds=thresholds_in(text, sentence_subjects),
                positive=not _NEGATION.search(text),
                asserts=bool(kinds)
                or bool(_BENEFIT_WORD.search(text))
                or bool(_LIST_ITEM.match(sentence)),
                ambiguous=len(universities) > 1 or len(olympiads) > 1,
            )
            if match := (_PRIZER.search(text) or _WINNER.search(text)):
                claim.role_text = text[match.start() : match.end()]
            claims.append(claim)
    return claims


def by_sentence(claims: Sequence[Claim]) -> list[Claim]:
    """Утверждения предложения одним: так проверяется «вуз + олимпиада + вид + кому + порог» из
    разных частей одного предложения. Предложение с отрицанием остаётся отрицательным."""
    merged: dict[str, Claim] = {}
    for claim in claims:
        into = merged.get(claim.sentence)
        if into is None:
            merged[claim.sentence] = Claim(
                claim.sentence,
                claim.sentence,
                claim.universities,
                claim.olympiads,
                claim.types,
                claim.winners,
                claim.prizers,
                claim.only_winners,
                claim.subjects,
                list(claim.thresholds),
                claim.role_text,
                claim.positive,
                claim.asserts,
                claim.ambiguous,
            )
            continue
        into.universities |= claim.universities
        into.olympiads |= claim.olympiads
        into.types |= claim.types
        into.winners |= claim.winners
        into.prizers |= claim.prizers
        into.only_winners |= claim.only_winners
        into.subjects |= claim.subjects
        into.thresholds += claim.thresholds
        into.role_text = into.role_text or claim.role_text
        into.positive = into.positive and claim.positive
        into.asserts = into.asserts or claim.asserts
        into.ambiguous = into.ambiguous or claim.ambiguous
    return list(merged.values())


# ---------------------------------------------------------------- проверки по базе


def check_claims(answer: str, vocab: Vocabulary, ledger: Ledger) -> list[Violation]:
    """Нарушения по базе: кому, вид льготы, предмет и порог, перечень вуза."""
    mentions = vocab.find(answer)
    if not mentions:
        return []
    violations: list[Violation] = []
    for claim in extract(answer, mentions):
        if claim.ambiguous or not claim.positive or not (claim.universities or claim.olympiads):
            continue
        if not ledger.known(claim.universities, claim.olympiads):
            continue
        rows = ledger.select(claim.universities, claim.olympiads)
        if not rows:
            continue  # пустой набор: «не в перечне» решает check_pairs, остальное не проверить
        violations += check_type(claim, rows)
        typed = [r for r in rows if not claim.types or any(kind_matches(r, k) for k in claim.types)]
        violations += check_role(claim, typed)
        violations += check_threshold(claim, typed)
    violations += check_pairs(answer, mentions, ledger)
    unique: dict[tuple[str, str], Violation] = {}
    for item in violations:
        unique.setdefault((item.kind, item.fragment.lower()), item)
    return list(unique.values())


def check_type(claim: Claim, rows: list[Row]) -> list[Violation]:
    """«100 баллов» вместо БВИ и наоборот."""
    if not claim.types or any(kind_matches(r, k) for r in rows for k in claim.types):
        return []
    have = label(r.kind for r in rows)
    wrong = label(claim.types)
    return [
        Violation(
            "benefit_type",
            wrong,
            claim.sentence,
            f"в базе по этой паре только {have}, а не {wrong}",
        )
    ]


def check_role(claim: Claim, rows: list[Row]) -> list[Violation]:
    """«Победителям и призёрам», когда в базе только победители, и «только победителям», когда
    призёры тоже есть."""
    if not rows:
        return []
    roles = {r.role for r in rows}
    if claim.prizers and roles <= {WINNERS}:
        return [
            Violation(
                "role",
                claim.role_text or "призёр",
                claim.sentence,
                "в базе по этой паре льгота только победителям, призёрам её не дают",
            )
        ]
    if claim.only_winners and not claim.prizers and roles <= {BOTH, PRIZERS}:
        fragment = _ONLY_WINNERS.search(claim.clause)
        return [
            Violation(
                "role",
                fragment.group(0) if fragment else "только победителям",
                claim.sentence,
                "в базе по этой паре льгота не только победителям: призёрам её тоже дают",
            )
        ]
    return []


def check_threshold(claim: Claim, rows: list[Row]) -> list[Violation]:
    """Порог ЕГЭ не по тому предмету или не то число."""
    if not rows:
        return []
    out = []
    for subject, score, text in claim.thresholds:
        scored = [r for r in rows if r.min_ege is not None]
        if subject is None:
            if scored and len(scored) == len(rows) and score not in {r.min_ege for r in rows}:
                have = sorted({r.min_ege for r in rows if r.min_ege is not None})
                out.append(
                    Violation(
                        "threshold",
                        text,
                        claim.sentence,
                        f"в базе по этой паре порог ЕГЭ: {', '.join(map(str, have))}",
                    )
                )
            continue
        # строка без предметов подходит любому предмету: про неё базе нечего возразить
        named = [r for r in rows if subject in r.subjects]
        if any(not r.subjects for r in rows):
            continue
        if not named:
            have_subjects = sorted({s for r in rows for s in r.subjects})
            out.append(
                Violation(
                    "threshold",
                    text,
                    claim.sentence,
                    f"в базе по этой паре ЕГЭ подтверждают по предметам: {', '.join(have_subjects)}",
                )
            )
        elif all(r.min_ege is not None for r in named) and score not in {r.min_ege for r in named}:
            have = sorted({r.min_ege for r in named if r.min_ege is not None})
            out.append(
                Violation(
                    "threshold",
                    text,
                    claim.sentence,
                    f"в базе порог по предмету «{subject}»: {', '.join(map(str, have))}",
                )
            )
    return out


def check_pairs(answer: str, mentions: Sequence[Mention], ledger: Ledger) -> list[Violation]:
    """Олимпиада, которой нет в перечне вуза: пара из одного предложения, по которой в базе нет ни
    одной строки. Вузов и олимпиад в предложении несколько — пара неоднозначна, не проверяем."""
    out = []
    for a, b in sentences(answer):
        sentence = answer[a:b].strip()
        asserted = (
            kinds_in(sentence) or _BENEFIT_WORD.search(sentence) or _LIST_ITEM.match(sentence)
        )
        if _NEGATION.search(sentence) or not asserted:
            continue
        unis = mention_groups(mentions, "university", a, b)
        olys = mention_groups(mentions, "olympiad", a, b)
        if not unis and olys and (last := last_group(mentions, "university", a)):
            unis = [last]
        if not olys and unis and (last := last_group(mentions, "olympiad", a)):
            olys = [last]
        if not unis or not olys or (len(unis) > 1 and len(olys) > 1):
            continue
        for u in unis:
            for o in olys:
                if ledger.known(u.ids, o.ids) and not ledger.select(u.ids, o.ids):
                    out.append(
                        Violation(
                            "not_listed",
                            u.fragment,
                            sentence,
                            f"в базе нет льгот для «{o.fragment}» в вузе «{u.fragment}»",
                        )
                    )
    return out
