"""
parser.py
=========
Deterministic extraction layer for messy construction/logistics documents.

The parser deliberately avoids an LLM. It turns a raw, email-style invoice or
shipping manifest into a stable Python dictionary that the rest of the pipeline
can trust. AI is used later for interpretation and recommended actions, never
for the arithmetic that drives purchasing decisions.

Design goals:
* No third-party dependencies.
* Tolerant of dot leaders, inconsistent spacing, currency symbols and commas.
* Explicit ``parse_warnings`` instead of silent failures.
* A stable output contract consumed by ``router.py`` and ``agent_hook.py``.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE_PATH = PROJECT_ROOT / "sample_data" / "mock_invoice.txt"

# A single regex for money values, including optional thousands separators.
_MONEY = r"\d[\d,]*(?:\.\d{1,2})?"
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")

# Line-item rows end with the shape:  <qty> <unit> @ <unit price> = <line total>
# Searching from the right side of the row makes dot leaders and extra spaces
# irrelevant. The description is simply everything before the matched quantity.
_LINE_ITEM_RE = re.compile(
    rf"(?P<quantity>{_MONEY})\s+"
    rf"(?P<unit>[A-Za-z]{{1,5}})\s*@\s*\$?\s*"
    rf"(?P<unit_price>{_MONEY})\s*=\s*\$?\s*"
    rf"(?P<line_total>{_MONEY})",
    re.IGNORECASE,
)


def _to_number(value: str | None) -> float | None:
    """Convert a messy money/quantity string such as ``$1,425.00`` to a float."""
    if value is None:
        return None
    cleaned = value.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _first_match(patterns: list[str], text: str) -> str | None:
    """Return the first captured group from a list of regex patterns."""
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


def _normalise_date(value: str | None) -> str | None:
    """
    Return an ISO date when the format is unambiguous.

    The sample is a US-format invoice. We try common formats and fall back to
    the original string so downstream systems never lose information.
    """
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return value.strip()


def _extract_supplier(text: str, emails: list[str]) -> dict[str, Any]:
    """Extract supplier identity using labelled fields and safe fallbacks."""
    supplier_name: str | None = None

    # Prefer an uppercase company-style line (e.g. "APEX STEEL & SUPPLY CO.").
    company_re = re.compile(
        r"(?m)^(?P<name>[A-Z][A-Z0-9 &'.,\-]{2,}"
        r"(?:CO|INC|LLC|CORP|LTD)\.?)\s*$"
    )
    company_match = company_re.search(text)
    if company_match:
        supplier_name = company_match.group("name").strip()

    # Fallbacks keep the pipeline useful even when the company line is missing.
    if not supplier_name:
        domain_match = re.search(
            r"(?im)^From:\s*[\w.+-]+@([\w-]+)\.[\w.-]+", text
        )
        if domain_match:
            supplier_name = domain_match.group(1).replace("-", " ").title()
        else:
            supplier_name = "UNKNOWN SUPPLIER"

    sender_match = re.search(
        r"(?im)^From:\s*.*?([\w.+-]+@[\w-]+\.[\w.-]+)", text
    )
    supplier_email = sender_match.group(1) if sender_match else (emails[0] if emails else None)

    phone_match = _PHONE_RE.search(text)
    phone = phone_match.group(0).strip() if phone_match else None

    # The line immediately after the supplier name is usually the remit address.
    address: str | None = None
    if company_match:
        tail = text[company_match.end():].splitlines()
        for line in tail:
            candidate = line.strip()
            if candidate and re.search(r"\d", candidate) and len(candidate) > 8:
                address = candidate
                break

    return {
        "name": supplier_name,
        "email": supplier_email,
        "phone": phone,
        "address": address,
    }


def _extract_notes(lines: list[str]) -> list[str]:
    """Collect bullet notes while excluding payment/remittance boilerplate."""
    notes: list[str] = []
    in_notes = False

    for line in lines:
        stripped = line.strip()
        if re.match(r"^notes?\s*:?\s*$", stripped, re.IGNORECASE):
            in_notes = True
            continue
        if in_notes and re.match(
            r"^(payment terms|terms|remit|thank you|regards)\b",
            stripped,
            re.IGNORECASE,
        ):
            break
        if in_notes and stripped:
            notes.append(re.sub(r"^[-*\u2022]\s*", "", stripped))

    return notes


def _extract_totals(text: str) -> dict[str, Any]:
    """Extract declared tax and totals. Values are verified later by router.py."""
    subtotal = _to_number(
        _first_match([r"^SUBTOTAL\s*[:\-]?\s*\$?\s*(" + _MONEY + r")"], text)
    )
    freight = _to_number(
        _first_match(
            [
                r"^(?:FREIGHT|DELIVERY|SHIPPING)[^\n:]*[:\-]?\s*\$?\s*("
                + _MONEY
                + r")"
            ],
            text,
        )
    )

    tax_rate: float | None = None
    tax_amount: float | None = None
    tax_line_match = re.search(
        r"(?im)^(?:[A-Z]{2}\s+)?(?:SALES\s+TAX|TAX)[^\n]*$", text
    )
    if tax_line_match:
        tax_line = tax_line_match.group(0)
        rate_match = re.search(r"\(\s*([\d.]+)\s*%\s*\)", tax_line)
        amount_match = re.search(r"\$\s*(" + _MONEY + r")", tax_line)
        if rate_match:
            tax_rate = _to_number(rate_match.group(1))
        if amount_match:
            tax_amount = _to_number(amount_match.group(1))

    total_due = _to_number(
        _first_match(
            [r"^(?<!SUB)TOTAL\s*(?:DUE|AMOUNT)?\s*[:\-]?\s*\$?\s*(" + _MONEY + r")"],
            text,
        )
    )

    return {
        "currency": "USD",
        "subtotal": subtotal,
        "freight": freight,
        "tax_rate_percent": tax_rate,
        "tax_amount": tax_amount,
        "total_due": total_due,
    }


def _parse_line_items(lines: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract numbered line items and return any row-level parse warnings."""
    items: list[dict[str, Any]] = []
    warnings: list[str] = []

    # If a LINE ITEMS header exists, only parse that section. Otherwise scan all
    # numbered rows, which supports simpler packing-slip formats.
    start = 0
    end = len(lines)
    for index, line in enumerate(lines):
        if re.match(r"^\s*line\s+items?\s*:?\s*$", line, re.IGNORECASE):
            start = index + 1
            break
    for index in range(start, len(lines)):
        if re.match(r"^\s*(subtotal|total|notes?)\b", lines[index], re.IGNORECASE):
            end = index
            break

    for raw_line in lines[start:end]:
        line = raw_line.strip()
        numbered = re.match(r"^(?P<index>\d+)[.)]\s+(?P<body>.+)$", line)
        if not numbered:
            continue

        body = numbered.group("body").strip()
        match = _LINE_ITEM_RE.search(body)
        if not match:
            warnings.append(f"Could not parse line-item row: {line!r}")
            continue

        description = body[: match.start()].strip()
        description = re.sub(r"[\s.]+$", "", description).strip()
        quantity = _to_number(match.group("quantity"))
        unit_price = _to_number(match.group("unit_price"))
        declared_line_total = _to_number(match.group("line_total"))
        computed_line_total = (
            round(quantity * unit_price, 2)
            if quantity is not None and unit_price is not None
            else None
        )

        if not description:
            warnings.append(f"Line item is missing a description: {line!r}")
        if (
            computed_line_total is not None
            and declared_line_total is not None
            and abs(computed_line_total - declared_line_total) > 0.02
        ):
            warnings.append(
                "Line-item arithmetic mismatch for "
                f"{description!r}: computed {computed_line_total:.2f}, "
                f"document says {declared_line_total:.2f}."
            )

        items.append(
            {
                "line_number": int(numbered.group("index")),
                "description": description,
                "quantity": quantity,
                "unit": match.group("unit").upper(),
                "unit_price": unit_price,
                "declared_line_total": declared_line_total,
                "computed_line_total": computed_line_total,
            }
        )

    return items, warnings


def parse_invoice(raw_text: str, source: str = "<memory>") -> dict[str, Any]:
    """
    Parse a raw invoice/manifest string into the pipeline's stable contract.

    Parameters
    ----------
    raw_text:
        Unstructured text extracted from a PDF, email body, or scanner.
    source:
        Human-readable source label used in reports and dashboards.

    Returns
    -------
    dict
        Supplier, metadata, line items, declared totals, notes, and warnings.
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("Input document is empty; nothing to parse.")

    lines = raw_text.splitlines()
    emails = list(dict.fromkeys(_EMAIL_RE.findall(raw_text)))

    metadata = {
        "invoice_number": _first_match(
            [r"^INVOICE\s*(?:NO|NUMBER|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]*)",], raw_text
        ),
        "invoice_date": _normalise_date(
            _first_match([r"^INVOICE\s*DATE\s*[:\-]?\s*([\d/.\-]+)"], raw_text)
        ),
        "due_date": _normalise_date(
            _first_match([r"^DUE\s*DATE\s*[:\-]?\s*([\d/.\-]+)"], raw_text)
        ),
        "po_number": _first_match(
            [r"^P\.?O\.?\s*(?:NUMBER|NO|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]*)",],
            raw_text,
        ),
        "project": _first_match([r"^PROJECT\s*[:\-]\s*(.+)$"], raw_text),
        "ship_via": _first_match([r"^SHIP\s*VIA\s*[:\-]\s*(.+)$"], raw_text),
        "payment_terms": _first_match(
            [r"^(?:PAYMENT\s+TERMS|TERMS)\s*[:\-]\s*(.+)$"], raw_text
        ),
    }

    line_items, parse_warnings = _parse_line_items(lines)
    if not line_items:
        parse_warnings.append(
            "No line items were detected. Check the document layout or extend "
            "the parser patterns."
        )

    return {
        "source": source,
        "raw_text": raw_text,
        "supplier": _extract_supplier(raw_text, emails),
        "metadata": metadata,
        "line_items": line_items,
        "totals_declared": _extract_totals(raw_text),
        "notes": _extract_notes(lines),
        "emails": emails,
        "parse_warnings": parse_warnings,
    }


def parse_invoice_file(path: str | Path | None = None) -> dict[str, Any]:
    """Read a text document from disk and parse it."""
    target = Path(path) if path else DEFAULT_SAMPLE_PATH
    if not target.exists():
        raise FileNotFoundError(f"Invoice source not found: {target}")
    raw_text = target.read_text(encoding="utf-8", errors="replace")
    return parse_invoice(raw_text, source=str(target))


if __name__ == "__main__":
    # Allow quick manual inspection: python -m modules.parser
    import json

    print(json.dumps(parse_invoice_file(), indent=2))
