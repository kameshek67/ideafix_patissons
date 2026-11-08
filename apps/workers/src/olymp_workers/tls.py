"""TLS для запросов к сайтам вузов (T-078).

Сертификат проверяется всегда: подменённая ссылка на документ показывалась бы пользователю как
источник истины. Многие сайты вузов, как и API MAX, подписаны сертификатом Минцифры — его берём
из каталога `infra/certs` или `OLYMP_MAX_CA_DIR` (см. README, раздел «Мини-приложение MAX»). Без проверки —
только явным флагом `--insecure`.
"""

from __future__ import annotations

import os
import ssl
import urllib.parse as up
from pathlib import Path

from .max_bot import ssl_context

REPO = Path(__file__).resolve().parents[4]


def ca_dir() -> str:
    return os.environ.get("OLYMP_MAX_CA_DIR") or str(REPO / "infra" / "certs")


def web_context(insecure: bool = False) -> ssl.SSLContext:
    """Контекст для сайтов вузов: системные сертификаты плюс Минцифры; insecure — без проверки."""
    if not insecure:
        return ssl_context(ca_dir())
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def is_web_url(url: str) -> bool:
    """Только http(s) с адресом: javascript:, data:, mailto: и относительные отбрасываются."""
    parts = up.urlsplit((url or "").strip())
    return parts.scheme.lower() in ("http", "https") and bool(parts.netloc)


def is_tls_error(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, ssl.SSLError) or isinstance(exc, ssl.SSLError)
