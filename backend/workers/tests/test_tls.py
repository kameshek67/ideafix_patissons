import ssl
import urllib.error
from pathlib import Path

import pytest
from olymp_workers.refresh_sources import documents_on_page
from olymp_workers.tls import is_tls_error, is_web_url, web_context

PAGE = """
<a href="/docs/olimpiady-2026.pdf">Перечень олимпиад 2026</a>
<a href="javascript:alert(1)//olimpiady.pdf">Перечень олимпиад (вредная)</a>
<a href=" JavaScript:void(0)//olimpiady.pdf">Олимпиады</a>
<a href="data:application/pdf;base64,AAAA//olimpiady.pdf">Олимпиады (data)</a>
<a href="mailto:pk@uni.ru?subject=olimpiady.pdf">Олимпиады (почта)</a>
<a href="https://other.example/priem/olimpiady.pdf">Особые права олимпиад</a>
"""


def test_only_http_links_become_documents() -> None:
    urls = [url for _, url in documents_on_page(PAGE, "https://uni.example/priem/")]
    assert urls == [
        "https://uni.example/docs/olimpiady-2026.pdf",
        "https://other.example/priem/olimpiady.pdf",
    ]


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://uni.ru/a.pdf", True),
        ("HTTP://uni.ru/a.pdf", True),
        ("javascript:alert(1)//a.pdf", False),
        ("data:application/pdf;base64,AA", False),
        ("ftp://uni.ru/a.pdf", False),
        ("/relative/a.pdf", False),
        ("", False),
    ],
)
def test_is_web_url(url: str, ok: bool) -> None:
    assert is_web_url(url) is ok


def test_context_verifies_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLYMP_MAX_CA_DIR", str(tmp_path))  # пустой каталог: только системные
    context = web_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    insecure = web_context(insecure=True)
    assert insecure.verify_mode == ssl.CERT_NONE


def test_tls_errors_are_recognized() -> None:
    cert = ssl.SSLCertVerificationError("certificate verify failed")
    assert is_tls_error(cert)
    assert is_tls_error(urllib.error.URLError(cert))
    assert not is_tls_error(urllib.error.URLError(TimeoutError()))
