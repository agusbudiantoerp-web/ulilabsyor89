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
ALLOWED_HOSTS = {"bri.co.id", "www.bri.co.id", "ir-bri.com", "www.ir-bri.com", "bankmandiri.co.id", "www.bankmandiri.co.id"}
BANK_FILING_REGISTRY = {"BBRI": {
    "issuer": "PT Bank Rakyat Indonesia (Persero) Tbk",
    "title": "Laporan Rasio Keuangan BRI per 30 September 2026",
    "period": "2026-09-30",
    "url": "https://bri.co.id/web/guest/api/files?path=%2Fsites%2Fdefault%2Ffiles%2Fdocuments%2FBRI+Lapkeu+Q3+2026+Ind.pdf",
    "source_name": "BRI Q3 2026 Financial Ratio Report",
}, "BMRI": {
    "issuer": "PT Bank Mandiri (Persero) Tbk",
    "title": "3Q 2026 Results Presentation — Bank Mandiri",
    "period": "2026-09-30",
    "url": "https://www.bankmandiri.co.id/documents/38265486/0/3Q26%2BAnalyst%2BMeeting%2B-%2BLong%2BForm%2B%281%29.pdf/f895d89c-5482-c853-6157-f8c06bdf34fb?t=1792746870722",
    "source_name": "Bank Mandiri 3Q 2026 Results Presentation — Bank-Only Ratios",
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
    table_lines = lines  # Keep continuation lookup aligned with the same extracted page-aware text.
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
                for following in table_lines[index + 1:index + 4]:
                    if re.search(r"\[\[PAGE:\d+\]\]", following):
                        break
                    if re.search(r"\b(?:NPL\s+gross|KPMM|NIM|LDR|ROE|Loan\s+to\s+Deposit|Capital\s+Adequacy)\b", following, re.I):
                        break
                    if not re.fullmatch(r"[\s|0-9.,%\-]+", following.strip()):
                        break
                    continuation.append(following)
                match = re.search(number, " ".join(continuation))
            if match:
                value = _decimal(match.group(1))
                if value is not None:
                    return value, current_page
    return None

def extract_metrics_from_pdf_text(text: str, *, source_url: str, source_name: str,
                                  period: str, document_sha256: str | None = None,
                                  roe_definition_mode: str = "explicit") -> dict:
    lines = [re.sub(r"\s+", " ", x).strip() for x in str(text or "").splitlines()]
    specs = {
        "NPL gross (%)": ((r"\bNPL\s+gross\b",), ()),
        "CAR (%)": ((r"\bKPMM\b", r"Capital\s+Adequacy\s+Ratio"), ()),
        "NIM (%)": ((r"\bNIM\b", r"Net\s+Interest\s+Margin"), ()),
        "LDR (%)": ((r"\bLDR\b", r"Loan\s+to\s+Deposit\s+Ratio"), ()),
    }
    if roe_definition_mode == "bri_q3_2026":
        # Footnote 4 is average total equity only in this registered BRI Q3 2026 report.
        specs["Official reported ROE (%)"] = ((r"\bROE\b.*4\)",), (r"Tier\s*1",))
    else:
        # For other issuers, require the equity basis to be explicit in the same row.
        specs["Official reported ROE (%)"] = (
            (r"\bROE\b.*(?:average\s+(?:total\s+)?equity|rata[- ]rata\s+(?:total\s+)?ekuitas)",),
            (r"Tier\s*1",),
        )
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

def extract_bmri_q3_2026_metrics_from_pdf_text(text: str, *, source_url: str,
                                                   source_name: str, period: str,
                                                   document_sha256: str | None = None) -> dict:
    """Extract only the explicitly labelled Bank-Only 9M26 column from BMRI's registered 3Q26 presentation."""
    lines = [re.sub(r"\s+", " ", x).strip() for x in str(text or "").splitlines()]
    row_specs = {
        "Official reported ROE (%)": (r"RoE\s*[–-]\s*after tax\s*\(excl\.\s*MI\)", "YTD average monthly equity excluding minority interest"),
        "CAR (%)": (r"\bCAR\b", "Bank-Only CAR"),
        "NIM (%)": (r"\bNIM\b", "Bank-Only net interest margin"),
        "LDR (%)": (r"Loan to Deposit Ratio \(LDR\)\s*[-–]\s*Bank Entity", "Bank-Entity LDR"),
    }
    table_start = next(
        (index for index, line in enumerate(lines) if "Ratios (in %)" in line),
        None,
    )
    if table_start is None:
        table_start = next(
            (index for index, line in enumerate(lines) if "Key profitability ratios" in line),
            0,
        )
    table_lines = lines[table_start:]
    metrics = {}
    page_markers = [
        int(match.group(1))
        for line in lines[:table_start + 1]
        for match in [re.search(r"\[\[PAGE:(\d+)\]\]", line)]
        if match
    ]
    current_page = page_markers[-1] if page_markers else 1
    numeric = re.compile(r"(?<![A-Za-z])[-+]?\d{1,3}(?:[.,]\d+)?")
    for key, (pattern, basis) in row_specs.items():
        found = None
        page_no = None
        for index, line in enumerate(table_lines):
            marker = re.search(r"\[\[PAGE:(\d+)\]\]", line)
            if marker:
                current_page = int(marker.group(1))
                line = line[marker.end():]
            if not re.search(pattern, line, re.I):
                continue
            values = numeric.findall(line)
            if len(values) < 5:
                for following in lines[index + 1:index + 4]:
                    if re.search(r"\[\[PAGE:\d+\]\]", following):
                        break
                    values.extend(numeric.findall(following))
                    if len(values) >= 6:
                        break
            if len(values) >= 5:
                parsed = _decimal(values[4])
                if parsed is not None:
                    found, page_no = parsed, current_page
                    break
        if found is not None:
            metrics[key] = {
                "value": found, "unit": "%", "period": period,
                "source_url": source_url, "source_name": source_name,
                "page": page_no, "extraction_method": "BMRI registered 3Q26 Bank-Only 9M26 table column",
                "confidence": "REVIEW",
                "definition": basis,
            }
    required = ("NPL gross (%)", "CAR (%)", "LDR (%)", "NIM (%)", "Official reported ROE (%)")
    return {
        "source_name": source_name, "source_url": source_url, "source_period": period,
        "document_sha256": document_sha256, "metrics": metrics,
        "missing_metrics": [key for key in required if key not in metrics],
        "analyst_review_required": True, "status": "REVIEW REQUIRED",
        "scope": "Bank-only; 9M26; analyst presentation",
        "notes": ["NPL Ratio is not mapped to NPL gross because the registered source row does not explicitly identify the gross basis."],
    }


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
    if key == "BMRI":
        result = extract_bmri_q3_2026_metrics_from_pdf_text(
            text, source_url=final_url, source_name=config["source_name"],
            period=config["period"], document_sha256=sha256(content).hexdigest(),
        )
    else:
        result = extract_metrics_from_pdf_text(text, source_url=final_url,
            source_name=config["source_name"], period=config["period"],
            document_sha256=sha256(content).hexdigest(),
            roe_definition_mode="bri_q3_2026")
    result.update({"ticker": key, "issuer": config["issuer"], "document_title": config["title"],
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "pages_read": len(reader.pages),
        "extraction_method": (
            "BMRI registered 3Q26 Bank-Only 9M26 table extraction"
            if key == "BMRI" else "PDF text / registered BRI Q3 2026 metric extraction"
        )})
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
