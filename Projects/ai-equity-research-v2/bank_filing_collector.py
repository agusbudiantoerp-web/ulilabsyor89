"""Allow-listed official bank filing retrieval; extracted values remain review-only."""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
import requests
from pypdf import PdfReader

MAX_PDF_BYTES = 25 * 1024 * 1024
ALLOWED_HOSTS = {"bri.co.id", "www.bri.co.id", "ir-bri.com", "www.ir-bri.com"}
BANK_FILING_REGISTRY = {"BBRI": {
    "issuer": "PT Bank Rakyat Indonesia (Persero) Tbk",
    "title": "Laporan Rasio Keuangan BRI per 30 September 2026",
    "period": "2026-09-30",
    "url": "https://bri.co.id/web/guest/api/files?path=%2Fsites%2Fdefault%2Ffiles%2Fdocuments%2FBRI+Lapkeu+Q3+2026+Ind.pdf",
    "source_name": "BRI Q3 2026 Financial Ratio Report",
}}

class FilingRetrievalError(ValueError):
    pass

def _validate_official_url(url: str) -> None:
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme.lower() != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise FilingRetrievalError("URL bukan HTTPS dari domain penerbit yang diizinkan.")
    if parsed.username or parsed.password:
        raise FilingRetrievalError("URL dengan username/password tidak diizinkan.")

def download_official_pdf(url: str, timeout: int = 20) -> tuple[bytes, str]:
    current = str(url or "").strip()
    session = requests.Session()
    session.headers.update({"User-Agent": "AdvancedEquityIntelligence/1.0"})
    for _ in range(4):
        _validate_official_url(current)
        try:
            response = session.get(current, timeout=timeout, allow_redirects=False, stream=True)
        except requests.RequestException as exc:
            raise FilingRetrievalError(f"Gagal menghubungi situs penerbit: {exc}") from exc
        if response.is_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise FilingRetrievalError("Redirect tidak memiliki alamat tujuan.")
            current = urljoin(current, location)
            continue
        if response.status_code != 200:
            status = response.status_code
            response.close()
            raise FilingRetrievalError(f"Situs penerbit mengembalikan HTTP {status}.")
        length = response.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > MAX_PDF_BYTES:
            response.close()
            raise FilingRetrievalError("Ukuran dokumen melebihi batas 25 MB.")
        chunks, total = [], 0
        try:
            for chunk in response.iter_content(65536):
                if chunk:
                    total += len(chunk)
                    if total > MAX_PDF_BYTES:
                        raise FilingRetrievalError("Ukuran dokumen melebihi batas 25 MB.")
                    chunks.append(chunk)
        finally:
            response.close()
        content = b"".join(chunks)
        if not content.startswith(b"%PDF"):
            raise FilingRetrievalError("Dokumen yang diterima bukan PDF yang valid.")
        return content, current
    raise FilingRetrievalError("Terlalu banyak pengalihan URL.")

def _decimal(token: str) -> float | None:
    token = token.strip().replace("%", "").replace(" ", "")
    if "," in token and "." in token:
        token = token.replace(".", "").replace(",", ".")
    elif "," in token:
        token = token.replace(",", ".")
    try:
        value = float(token)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 1000 else None

def _find_metric(lines: list[str], patterns: tuple[str, ...], exclude: tuple[str, ...] = ()):
    number = r"([0-9]{1,3}(?:[.,][0-9]{1,3})?)"
    current_page = 1
    for index, line in enumerate(lines):
        marker = re.search(r"\[\[PAGE:(\d+)\]\]", line)
        if marker:
            current_page = int(marker.group(1))
            line = line[marker.end():]
        compact = re.sub(r"\s+", " ", line).strip()
        if not compact or any(re.search(x, compact, re.I) for x in exclude):
            continue
        for pattern in patterns:
            label = re.search(pattern, compact, re.I)
            if not label:
                continue
            tail = compact[label.end():]
            match = re.search(number, tail)
            if not match:
                # Some PDF text extractors put table labels and values on separate lines.
                continuation = []
                for following in lines[index + 1:index + 4]:
                    if re.search(r"\[\[PAGE:\d+\]\]", following):
                        break
                    if re.search(r"\b(?:NPL\s+gross|KPMM|NIM|LDR|ROE|Loan\s+to\s+Deposit|Capital\s+Adequacy)\b", following, re.I):
                        break
                    continuation.append(following)
                match = re.search(number, " ".join(continuation))
            if match:
                value = _decimal(match.group(1))
                if value is not None:
                    return value, current_page
    return None

def extract_metrics_from_pdf_text(text: str, *, source_url: str, source_name: str,
                                  period: str, document_sha256: str | None = None) -> dict:
    lines = [re.sub(r"\s+", " ", x).strip() for x in str(text or "").splitlines()]
    specs = {
        "NPL gross (%)": ((r"\bNPL\s+gross\b",), ()),
        "CAR (%)": ((r"\bKPMM\b", r"Capital\s+Adequacy\s+Ratio"), ()),
        "NIM (%)": ((r"\bNIM\b", r"Net\s+Interest\s+Margin"), ()),
        "LDR (%)": ((r"\bLDR\b", r"Loan\s+to\s+Deposit\s+Ratio"), ()),
        # In the registered BRI ratio report, footnote 4 is ROE / average total equity.
        "Official reported ROE (%)": ((r"\bROE\b.*4\)",), (r"Tier\s*1",)),
    }
    metrics = {}
    for key, (patterns, exclude) in specs.items():
        found = _find_metric(lines, patterns, exclude)
        if found:
            value, page_no = found
            metrics[key] = {"value": value, "unit": "%", "period": period,
                "source_url": source_url, "source_name": source_name, "page": page_no,
                "extraction_method": "PDF text / label match", "confidence": "REVIEW"}
    required = ("NPL gross (%)", "CAR (%)", "LDR (%)", "NIM (%)", "Official reported ROE (%)")
    return {"source_name": source_name, "source_url": source_url, "source_period": period,
        "document_sha256": document_sha256, "metrics": metrics,
        "missing_metrics": [key for key in required if key not in metrics],
        "analyst_review_required": True, "status": "REVIEW REQUIRED"}

def extract_official_bank_filing(ticker: str) -> dict:
    key = str(ticker or "").upper().replace(".JK", "").strip()
    config = BANK_FILING_REGISTRY.get(key)
    if not config:
        raise FilingRetrievalError(f"Belum ada konektor sumber resmi terdaftar untuk {key or 'ticker ini'}. Gunakan input manual.")
    content, final_url = download_official_pdf(config["url"])
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        text = "\n".join(f"[[PAGE:{index}]]\n{page.extract_text() or ''}" for index, page in enumerate(reader.pages, start=1))
    except Exception as exc:
        raise FilingRetrievalError(f"PDF diunduh tetapi teks tidak dapat dibaca: {exc}") from exc
    result = extract_metrics_from_pdf_text(text, source_url=final_url,
        source_name=config["source_name"], period=config["period"],
        document_sha256=sha256(content).hexdigest())
    result.update({"ticker": key, "issuer": config["issuer"], "document_title": config["title"],
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "pages_read": len(reader.pages)})
    return result

def extract_uploaded_bank_filing(pdf_bytes: bytes, *, ticker: str, source_name: str,
                                 period: str, source_url: str = "") -> dict:
    """Parse an analyst-uploaded issuer PDF; extracted values remain review-only."""
    if not isinstance(pdf_bytes, (bytes, bytearray)) or not pdf_bytes.startswith(b"%PDF"):
        raise FilingRetrievalError("File unggahan bukan PDF yang valid.")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise FilingRetrievalError("Ukuran PDF unggahan melebihi batas 25 MB.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(period or "")):
        raise FilingRetrievalError("Periode laporan harus menggunakan format YYYY-MM-DD.")
    try:
        reader = PdfReader(BytesIO(pdf_bytes), strict=False)
        text = "\n".join(
            f"[[PAGE:{index}]]\n{page.extract_text() or ''}"
            for index, page in enumerate(reader.pages, start=1)
        )
    except Exception as exc:
        raise FilingRetrievalError(f"PDF unggahan tidak dapat dibaca: {exc}") from exc
    key = str(ticker or "").upper().replace(".JK", "").strip()
    result = extract_metrics_from_pdf_text(
        text, source_url=str(source_url or "").strip(),
        source_name=str(source_name or "Uploaded bank filing").strip(),
        period=period, document_sha256=sha256(pdf_bytes).hexdigest(),
    )
    result.update({
        "ticker": key, "issuer": key,
        "document_title": str(source_name or "Uploaded bank filing"),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "pages_read": len(reader.pages),
        "extraction_method": "Uploaded PDF text extraction",
    })
    return result
