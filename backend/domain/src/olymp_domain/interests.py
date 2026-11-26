"""Поиск профилей олимпиад по увлечениям ученика (инструмент find_profiles помощника).

Модель передаёт темы словами или короткими фразами: «мобильные приложения», «робот», «биолог».
Профиль подходит к фразе, если каждое её слово совпадает по основе с каким-нибудь словом в
названии профиля — в любом порядке и с любыми окончаниями: «мобильная разработка» находит
«разработка мобильных приложений». Склеенная строка без пробелов этого не умела.
"""

import re

from .textutils import PROFILE_SYNONYMS

# слова, которые модель добавляет к теме, но которых нет в названиях профилей
STOP_STEMS = ("олимпиад", "профил", "направлен", "школьн", "предмет", "задач")
STOP_WORDS = frozenset({"для", "или", "как", "что", "это", "про", "при", "над", "под", "без"})
# основа слова не длиннее STEM_LEN букв (как profile_stems в textutils), окончание может отличаться
STEM_LEN = 6
# «профиль» из обрывка разбора: перечень десятка предметов через запятую
LIST_PROFILE_COMMAS = 6

RE_WORD = re.compile(r"[^\W\d_]+")

# увлечение -> школьный профиль РСОШ, который так называется в перечне: «программирование»
# у большинства олимпиад — профиль «информатика», и без этого олимпиада ИТМО и ВсОШ
# по информатике на «люблю программировать» не находились
INTEREST_SUBJECTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("программ", "кодинг", "код", "разработ", "алгоритм"), "информатика"),
    (("нейросет", "ии", "машинн", "искусствен"), "искусственный интеллект"),
    (("хакер", "кибер"), "информационная безопасность"),
    (("робот",), "робототехника"),
)


def words_of(text: str) -> list[str]:
    """Слова длиннее двух букв в нижнем регистре, ё → е."""
    return [w for w in RE_WORD.findall(text.lower().replace("ё", "е")) if len(w) > 2]


def query_words(keyword: str) -> list[str]:
    """Значимые слова темы: без служебных и без «олимпиада», «профиль» и т. п."""
    return [w for w in words_of(keyword) if w not in STOP_WORDS and not w.startswith(STOP_STEMS)]


def expand_keywords(keywords: list[str]) -> list[str]:
    """Темы модели плюс школьные профили, которыми их называет перечень."""
    out = list(keywords)
    for keyword in keywords:
        words = words_of(keyword) or [keyword.lower()]
        for stems, subject in INTEREST_SUBJECTS:
            hit = any(w == s or (len(s) > 3 and w.startswith(s)) for w in words for s in stems)
            if hit and subject not in out:
                out.append(subject)
    return out


def word_matches(query: str, word: str) -> bool:
    """Одно слово по основе: «мобильная» ~ «мобильных», «игры» ~ «игр», «химия» ~ «химический»."""
    common = 0
    for a, b in zip(query, word, strict=False):
        if a != b:
            break
        common += 1
    # тема может быть основой («хим», «программир»), а вот слово названия не должно быть
    # обрывком длинного слова темы («моб» — не «мобильные»)
    need = max(3, min(len(query), STEM_LEN) - 1)
    if len(word) < len(query) and len(word) < need:
        return False
    return common >= min(need, len(word))


def phrase_matches(words: list[str], name_words: list[str]) -> bool:
    """Каждое слово темы нашлось в названии профиля."""
    return bool(words) and all(any(word_matches(q, w) for w in name_words) for q in words)


def is_list_profile(name: str) -> bool:
    """Обрывок разбора таблицы: в «профиле» перечислено много предметов через запятую."""
    return name.count(",") >= LIST_PROFILE_COMMAS


def display_name(name: str) -> str:
    """Название профиля для ученика: известные опечатки и сокращения таблиц — полностью."""
    return PROFILE_SYNONYMS.get(name.strip().lower(), name)
