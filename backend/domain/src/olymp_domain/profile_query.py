"""Профили олимпиады в запросе и на экране: разбор «олимпиада + профиль» и схлопывание дублей.

Профили собираются из таблиц вузов, поэтому у олимпиады вроде НТО их полсотни, среди них
обрывки («летающая») и опечатки («мобильных предложений»). Данные не меняем: лишнее прячем
при показе, а выбор схлопнутого профиля находит и строки его дублей.
"""

import re
from collections.abc import Collection, Iterable, Sequence
from difflib import SequenceMatcher
from typing import Any

from .olympiad_seeds import PROFILE_SYNONYMS
from .textutils import squash

Profile = dict[str, Any]

# обрывок («летающая») прячем, только если у него совсем мало строк
FRAGMENT_MAX_ROWS = 3
# две записи, различающиеся опечаткой («приложений» / «предложений»)
TYPO_RATIO = 0.93
TYPO_MIN_LENGTH = 12

RE_WORD = re.compile(r"[^\W\d_]+")
RE_ITEMS = re.compile(r"[,:;]")


def _words(name: str) -> list[str]:
    return RE_WORD.findall(name.lower().replace("ё", "е"))


def _rows(profile: Profile) -> int:
    return int(profile.get("mentions") or 0)


def collapse_profiles(
    profiles: Sequence[Profile], keep: Collection[int] = ()
) -> tuple[list[Profile], dict[int, list[int]]]:
    """Что показывать чипами: (профили, {id оставленного: [id спрятанных его дублей]}).

    Прячем профили без строк льгот, обрывки названий с парой строк, склейки «популярный
    профиль + лишнее слово» и опечатки. Профили из keep (выбранный пользователем) остаются.
    """
    shown = [p for p in profiles if _rows(p) > 0]
    keys = {p["id"]: squash(p["name"]) for p in shown}
    words = {p["id"]: _words(p["name"]) for p in shown}
    by_rows = sorted(shown, key=lambda p: (-_rows(p), p["name"]))
    merged_into: dict[int, int] = {}

    def owner_of(a: Profile) -> int | None:
        ak, aw = keys[a["id"]], words[a["id"]]
        for b in by_rows:
            bk, bw = keys[b["id"]], words[b["id"]]
            if b["id"] == a["id"] or ak == bk or _rows(b) <= _rows(a) or not ak:
                continue
            # обрывок: слова целиком входят в название популярного профиля, но сами не его пункт
            is_fragment = _rows(a) <= FRAGMENT_MAX_ROWS and (bk.startswith(ak) or set(aw) < set(bw))
            if is_fragment and ak not in {squash(item) for item in RE_ITEMS.split(b["name"])}:
                return int(b["id"])
            # склейка: популярный профиль и чужое слово или два (обрыв соседнего профиля)
            if len(bk) >= 8 and bk in ak and len(aw) > len(bw):
                front, _, back = ak.partition(bk)
                extra = len(aw) - len(bw)
                others = [k for i, k in keys.items() if i not in (a["id"], b["id"])]
                dangling = [x for x in (front, back) if x]
                glued = all(any(k.startswith(x) for k in others) for x in dangling)
                if (glued and extra <= (4 if front and back else 2)) or (not front and extra == 1):
                    return int(b["id"])
        return None

    for a in shown:
        if a["id"] not in keep and (owner := owner_of(a)) is not None:
            merged_into[a["id"]] = owner

    # опечатки: оставляем запись с уровнем из перечня 2026/27, затем с большим числом строк
    def better(p: Profile) -> tuple[bool, int]:
        return (bool(p.get("level_2026_27")), _rows(p))

    for i, a in enumerate(shown):
        for b in shown[i + 1 :]:
            if a["id"] in merged_into or b["id"] in merged_into:
                continue
            ak, bk = keys[a["id"]], keys[b["id"]]
            if min(len(ak), len(bk)) < TYPO_MIN_LENGTH or ak == bk:
                continue
            if SequenceMatcher(None, ak, bk).ratio() >= TYPO_RATIO:
                loser, winner = (a, b) if better(a) < better(b) else (b, a)
                if loser["id"] not in keep:
                    merged_into[loser["id"]] = winner["id"]

    def final(pid: int) -> int:
        seen = {pid}
        while pid in merged_into and merged_into[pid] not in seen:
            pid = merged_into[pid]
            seen.add(pid)
        return pid

    merged: dict[int, list[int]] = {}
    for hidden in merged_into:
        merged.setdefault(final(hidden), []).append(hidden)
    visible = [p for p in shown if p["id"] not in merged_into]
    return visible, merged


def _score(candidate: str, profile_words: list[str], key: str, is_list: bool) -> int:
    """Насколько запрос (squash) подходит профилю: 100 — точно, 0 — не подходит.

    Профиль-перечень («математика, физика, НТО (все профили)») ищем только по началу названия,
    иначе любое слово запроса находило бы такие списки.
    """
    if not candidate:
        return 0
    if key == candidate:
        return 100
    best = 0
    # слово запроса в другой форме: «мобильные» находит «мобильных приложений»
    forms = [(candidate, 0)] + ([(candidate[:-2], 10)] if len(candidate) >= 6 else [])
    for form, penalty in forms:
        if key.startswith(form):
            best = max(best, 80 - penalty)
        elif is_list:
            continue
        elif any("".join(profile_words[i:]).startswith(form) for i in range(1, len(profile_words))):
            best = max(best, 60 - penalty // 2)
        elif len(form) >= 5 and form in key:
            best = max(best, 40)
    return best


def match_profiles(rest: str, profiles: Iterable[Profile]) -> list[tuple[Profile, int]]:
    """Профили, подходящие под остаток запроса «нто ии» -> «ии», лучшие первыми.

    Остаток — это начало названия («матем»), начало любого слова («интеллект») или
    сокращение из PROFILE_SYNONYMS. Короткий остаток из двух букв — только по синонимам и началу.
    """
    key = squash(rest)
    if len(key) < 2:
        return []
    synonyms = PROFILE_SYNONYMS.get(key, ())
    found: list[tuple[Profile, int]] = []
    for profile in profiles:
        pkey, pwords = squash(profile["name"]), _words(profile["name"])
        is_list = len(RE_ITEMS.split(profile["name"])) >= 3
        score = (
            _score(key, pwords, pkey, is_list) if len(key) >= 3 else int(pkey.startswith(key)) * 80
        )
        for synonym in synonyms:
            score = max(score, 90 if pkey == synonym else 70 if pkey.startswith(synonym) else 0)
        if score:
            found.append((profile, score))
    found.sort(key=lambda hit: (-hit[1], -_rows(hit[0]), hit[0]["name"]))
    return found


def split_query(key: str, aliases: Iterable[tuple[int, str]]) -> list[tuple[int, str]]:
    """Делит запрос (squash) на олимпиаду и остаток: [(id олимпиады, остаток)].

    Сокращение олимпиады может стоять в начале или в конце запроса: «нто ии», «ии нто».
    Побеждают более длинные сокращения. Остаток короче двух букв не берём.
    """
    found: dict[tuple[int, str], int] = {}
    for olympiad_id, alias in aliases:
        if len(alias) < 2 or len(key) - len(alias) < 2:
            continue
        for rest in (
            (key[len(alias) :] if key.startswith(alias) else None),
            (key[: -len(alias)] if key.endswith(alias) else None),
        ):
            if rest:
                found[(olympiad_id, rest)] = max(found.get((olympiad_id, rest), 0), len(alias))
    return [pair for pair, _ in sorted(found.items(), key=lambda kv: -kv[1])]
