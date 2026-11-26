from pathlib import Path

import httpx
import pytest
from olymp_workers.ai import documents
from olymp_workers.ai.documents import DocumentError, DocumentStore, html_text, safe_url


def tiny_pdf(*pages: list[str]) -> bytes:
    """Настоящий PDF со шрифтом Helvetica: по странице на список строк (только ASCII)."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    font = 3 + 2 * len(pages)
    for i, lines in enumerate(pages):
        body = (
            "BT /F1 12 Tf 72 720 Td " + " ".join(f"({line}) Tj 0 -16 Td" for line in lines) + " ET"
        )
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 {font} 0 R >> >> >>"
        )
        objects.append(f"<< /Length {len(body)} >>\nstream\n{body}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def store(tmp_path: Path, handler: object) -> DocumentStore:
    return DocumentStore(tmp_path, transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_pdf_pages_are_extracted_and_cached(tmp_path: Path) -> None:
    calls: list[str] = []
    pdf = tiny_pdf(["General rules"], ["Olympiad MOSH gives BVI", "code 01.03.02"])

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["user-agent"].startswith("OlympBot/")
        return httpx.Response(
            200, content=pdf, headers={"content-type": "application/octet-stream"}
        )

    first = store(tmp_path, handle).get("https://uni.example/doc.pdf")
    assert first.kind == "pdf"
    assert len(first.pages) == 2
    assert "Olympiad MOSH gives BVI" in first.pages[1]

    again = store(tmp_path, handle)
    assert again.get("https://uni.example/doc.pdf").pages == first.pages
    assert again.downloads == 0
    assert len(calls) == 1


def test_html_disguised_as_pdf(tmp_path: Path) -> None:
    html = "<html><body><script>x()</script><p>Победителям МОШ</p><table><tr><td>БВИ</td></tr></table></body></html>"

    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=html.encode(), headers={"content-type": "application/pdf"}
        )

    document = store(tmp_path, handle).get("https://uni.example/rules.pdf")
    assert document.kind == "html"
    assert "Победителям МОШ" in document.pages[0]
    assert "x()" not in document.pages[0]


def test_cp1251_page() -> None:
    assert html_text("<p>Олимпиада</p>".encode("cp1251"), None) == "Олимпиада"


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(404), "HTTP 404"),
        (httpx.Response(200, content=b"PK\x03\x04 zip"), "формат не поддерживается"),
        (httpx.Response(200, content=b"%PDF-1.4 broken"), "PDF не разбирается"),
        (httpx.Response(200, content=b"%PDF", headers={"content-length": str(10**9)}), "25 МБ"),
    ],
)
def test_bad_documents(tmp_path: Path, response: httpx.Response, reason: str) -> None:
    with pytest.raises(DocumentError, match=reason):
        store(tmp_path, lambda _: response).get("https://uni.example/x.pdf")


def test_size_limit_without_content_length(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documents, "MAX_BYTES", 10)
    with pytest.raises(DocumentError, match="25 МБ"):
        store(tmp_path, lambda _: httpx.Response(200, content=b"%PDF-" + b"x" * 100)).get(
            "https://uni.example/big.pdf"
        )


def test_failure_is_remembered_within_run_but_not_cached(tmp_path: Path) -> None:
    calls: list[int] = []

    def handle(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    s = store(tmp_path, handle)
    for _ in range(2):
        with pytest.raises(DocumentError):
            s.get("https://uni.example/x.pdf")
    assert len(calls) == 1
    assert not any(tmp_path.iterdir())


def test_network_errors_are_reasons(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]", request=request)

    with pytest.raises(DocumentError, match="--insecure"):
        store(tmp_path, handle).get("https://uni.example/x.pdf")


@pytest.mark.parametrize("url", ["ftp://x/y.pdf", "file:///etc/passwd", "javascript:alert(1)", ""])
def test_only_http(url: str) -> None:
    with pytest.raises(DocumentError):
        safe_url(url)


def test_cyrillic_url_is_encoded() -> None:
    url = safe_url("https://www.rsuh.ru/upload/2026_БАК_СПЕЦ.pdf?a=б")
    assert url.isascii()
    assert safe_url(url) == url
