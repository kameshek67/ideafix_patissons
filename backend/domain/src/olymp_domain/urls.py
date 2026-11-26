"""Адреса документов: одна нормальная форма, чтобы одна ссылка не лежала в базе дважды."""

import re
import urllib.parse as up


def normalize_url(url: str) -> str:
    """Проверяет схему и кодирует кириллицу и пробелы в адресе, не трогая уже закодированное.

    ValueError — адрес не http(s)."""
    url = url.strip()
    parts = up.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("адрес не http(s)")
    return up.urlunsplit(
        (
            parts.scheme,
            parts.netloc.encode("idna").decode("ascii")
            if not parts.netloc.isascii()
            else parts.netloc,
            up.quote(parts.path, safe="/%:@!$&'()*+,;=-._~"),
            up.quote(parts.query, safe="=&%:@!$'()*+,;/?-._~"),
            "",
        )
    )


# списки поступающих, рейтинги и приказы о зачислении — в них фамилии живых людей,
# в справочник им не место (в кэше, лежащем в публичном репозитории, тем более)
RE_PERSONAL_LIST = re.compile(
    r"спис(?:ок|к\w*)\s+(?:\w+\s+)?(?:победител|призер|подавш|поступающ|зачисл|абитуриент|рекомендован)"
    r"|подавш\w+\s+документ"
    r"|конкурсн\w+\s+спис(?:ок|к)"
    r"|рейтинг\w*\s+спис(?:ок|к)"
    r"|рейтинг\w*\s+(?:поступающ|абитуриент)"
    r"|приказ\w*\s+(?:\S+\s+){0,4}?о\s+зачисл"
    r"|приказ\w*\s+(?:\S+\s+){0,4}?о\s+рекомендаци"
    r"|(?<![a-z])(?:spisok|spiski|spisky|reiting|rating|ranzh|zachisl)",
    re.IGNORECASE,
)
RE_RANKING_RULE = re.compile(r"ранжировани\w*\s+списк\w*", re.IGNORECASE)


def is_personal_list(title: str, url: str) -> bool:
    """Список поступающих, рейтинг или приказ о зачислении: персональные данные."""
    haystack = f"{title} {up.unquote(url)}".replace("_", " ").replace("ё", "е").replace("Ё", "Е")
    # «приоритетность испытаний при ранжировании списков поступающих» — это правила, не список
    haystack = RE_RANKING_RULE.sub(" ", haystack)
    return bool(RE_PERSONAL_LIST.search(haystack))
