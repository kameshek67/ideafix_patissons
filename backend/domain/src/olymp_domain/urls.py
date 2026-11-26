"""Адреса документов: одна нормальная форма, чтобы одна ссылка не лежала в базе дважды."""

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
