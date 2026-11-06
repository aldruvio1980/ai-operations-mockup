"""
router.py
=========
Deterministic validation, arithmetic, and routing for parsed invoices.

This module is the "rules engine" of the mockup. It is intentionally boring:
purchasing teams need repeatable answers, auditable thresholds, and no
hallucinated math. Every decision can be traced to a rule below.

The output contract is consumed by the local AI agent and the terminal UI.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

RULES_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Tunable business thresholds. In production these would live in config or the
# ERP, and changes would be reviewed/versioned like any other business control.
# ---------------------------------------------------------------------------
RULES: dict[str, Any] = {
    "required_metadata": ["invoice_number", "invoice_date", "po_number", "project"],
    "max_auto_approve_total": 25_000.00,
    "high_value_line_threshold": 10_000.00,
    "bulk_quantity_threshold": 200,
    "money_tolerance": 0.02,
    "allowed_units": {"EA", "CY", "LF", "SF", "SY", "TON", "PR", "BX", "PK", "GAL", "LB"},
    "price_envelopes": [
        {"keywords": ("STEEL BEAM", "W24", "W18", "W21"), "min": 900.0, "max": 1800.0, "unit": "EA"},
        {"keywords": ("CONCRETE", "READY-MIX"), "min": 140.0, "max": 240.0, "unit": "CY"},
        {"keywords": ("REBAR", "#5", "#4", "#6"), "min": 12.0, "max": 30.0, "unit": "EA"},
        {"keywords": ("HARD HAT", "ANSI Z89.1"), "min": 8.0, "max": 25.0, "unit": "EA"},
        {"keywords": ("GLOVE",), "min": 4.0, "max": 20.0, "unit": "PR"},
        {"keywords": ("RESPIRATOR", "N95", "MASK"), "min": 0.50, "max": 3.00, "unit": "EA"},
    ],
    "exception_keywords": (
        "late",
        "delay",
        "short",
        "substitut",
        "damage",
        "missing",
        "verify",
    ),
}


def _dec(value: Any) -> Decimal | None:
    """Safely convert a numeric value to Decimal for exact money arithmetic."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return None


def _money(value: Decimal | None) -> float | None:
    """Round a Decimal to cents using commercial (half-up) rounding."""
    if value is None:
        return None
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _finding(
    rule_id: str,
    severity: str,
    message: str,
    field: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a consistently shaped audit finding."""
    return {
        "rule_id": rule_id,
        "severity": severity,
        "field": field,
        "message": message,
        "details": details or {},
    }


def _validate_required_fields(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """R1: Missing identifiers block straight-through processing."""
    findings: list[dict[str, Any]] = []
    metadata = parsed.get("metadata", {})
    supplier = parsed.get("supplier", {})

    for field in RULES["required_metadata"]:
        if not metadata.get(field):
            findings.append(
                _finding(
                    "R1_REQUIRED_FIELD",
                    "critical",
                    f"Required field '{field}' is missing; invoice cannot be posted.",
                    field=field,
                )
            )

    if not supplier.get("name") or supplier.get("name") == "UNKNOWN SUPPLIER":
        findings.append(
            _finding(
                "R1_REQUIRED_FIELD",
                "critical",
                "Supplier name could not be identified.",
                field="supplier.name",
            )
        )

    if not parsed.get("line_items"):
        findings.append(
            _finding(
                "R1_REQUIRED_FIELD",
                "critical",
                "No line items were extracted; totals cannot be trusted.",
                field="line_items",
            )
        )

    return findings


def _validate_line_items(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """R2/R3/R4: Validate row completeness, arithmetic, units and price bands."""
    findings: list[dict[str, Any]] = []

    for item in parsed.get("line_items", []):
        label = f"line {item.get('line_number')} ({item.get('description', 'unknown')})"
        quantity = item.get("quantity")
        unit_price = item.get("unit_price")
        declared_total = item.get("declared_line_total")
        computed_total = item.get("computed_line_total")

        if not item.get("description"):
            findings.append(
                _finding("R2_LINE_DATA", "critical", f"{label} has no description.", field="description")
            )
        if quantity is None or quantity <= 0:
            findings.append(
                _finding("R2_LINE_DATA", "critical", f"{label} has an invalid quantity.", field="quantity")
            )
            continue
        if unit_price is None or unit_price < 0:
            findings.append(
                _finding("R2_LINE_DATA", "critical", f"{label} has an invalid unit price.", field="unit_price")
            )
            continue

        if item.get("unit") not in RULES["allowed_units"]:
            findings.append(
                _finding(
                    "R3_UNKNOWN_UNIT",
                    "warning",
                    f"{label} uses unrecognised unit '{item.get('unit')}'; verify UOM.",
                    field="unit",
                )
            )

        if (
            declared_total is not None
            and computed_total is not None
            and abs(Decimal(str(declared_total)) - Decimal(str(computed_total)))
            > Decimal(str(RULES["money_tolerance"]))
        ):
            findings.append(
                _finding(
                    "R4_LINE_ARITHMETIC",
                    "warning",
                    f"{label} total does not equal quantity x unit price.",
                    field="line_total",
                    details={"declared": declared_total, "computed": computed_total},
                )
            )

        # Price-envelope checks are category-aware. They intentionally produce
        # warnings (human review) rather than silently changing the invoice.
        description_upper = str(item.get("description", "")).upper()
        for envelope in RULES["price_envelopes"]:
            if any(keyword in description_upper for keyword in envelope["keywords"]):
                if item.get("unit") != envelope["unit"]:
                    findings.append(
                        _finding(
                            "R5_UNIT_MISMATCH",
                            "warning",
                            f"{label} has unit {item.get('unit')}; expected {envelope['unit']}.",
                            field="unit",
                        )
                    )
                elif not (envelope["min"] <= unit_price <= envelope["max"]):
                    findings.append(
                        _finding(
                            "R5_PRICE_ENVELOPE",
                            "warning",
                            f"{label} unit price ${unit_price:,.2f} is outside the "
                            f"expected ${envelope['min']:,.2f}-${envelope['max']:,.2f} band.",
                            field="unit_price",
                            details={"unit_price": unit_price, "envelope": envelope},
                        )
                    )
                break

        if quantity >= RULES["bulk_quantity_threshold"]:
            findings.append(
                _finding(
                    "R6_BULK_QUANTITY",
                    "info",
                    f"{label} is a bulk quantity ({quantity:g} {item.get('unit')}); "
                    "confirm delivery capacity and staged receiving.",
                    field="quantity",
                    details={"quantity": quantity, "unit": item.get("unit")},
                )
            )

        if computed_total is not None and computed_total >= RULES["high_value_line_threshold"]:
            findings.append(
                _finding(
                    "R7_HIGH_VALUE_LINE",
                    "warning",
                    f"{label} exceeds the ${RULES['high_value_line_threshold']:,.2f} "
                    "line-value review threshold.",
                    field="line_total",
                    details={"line_total": computed_total},
                )
            )

    return findings


def _calculate_totals(parsed: dict[str, Any]) -> dict[str, Any]:
    """
    Recalculate all totals independently of the supplier's declared values.

    Line totals are recomputed from quantity x unit price. Tax is recalculated
    from the declared rate, then compared to the supplier's numbers. The
    dashboard uses these computed values as the "real-time truth".
    """
    declared = parsed.get("totals_declared", {})
    tolerance = Decimal(str(RULES["money_tolerance"]))

    computed_subtotal = Decimal("0.00")
    declared_line_sum = Decimal("0.00")
    for item in parsed.get("line_items", []):
        quantity = _dec(item.get("quantity")) or Decimal("0")
        price = _dec(item.get("unit_price")) or Decimal("0")
        computed_subtotal += quantity * price
        declared_line_sum += _dec(item.get("declared_line_total")) or Decimal("0")

    computed_subtotal = computed_subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    declared_subtotal = _dec(declared.get("subtotal"))
    freight = _dec(declared.get("freight")) or Decimal("0.00")
    rate = _dec(declared.get("tax_rate_percent"))
    declared_tax = _dec(declared.get("tax_amount"))
    declared_total = _dec(declared.get("total_due"))

    computed_tax = (
        (computed_subtotal * rate / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if rate is not None
        else declared_tax
    )
    computed_total = (
        computed_subtotal + freight + (computed_tax or Decimal("0.00"))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "currency": declared.get("currency", "USD"),
        "computed_subtotal": _money(computed_subtotal),
        "declared_subtotal": _money(declared_subtotal),
        "subtotal_variance": _money(
            computed_subtotal - declared_subtotal if declared_subtotal is not None else None
        ),
        "declared_line_sum": _money(declared_line_sum),
        "freight": _money(freight),
        "tax_rate_percent": float(rate) if rate is not None else None,
        "computed_tax": _money(computed_tax),
        "declared_tax": _money(declared_tax),
        "tax_variance": _money(
            computed_tax - declared_tax
            if computed_tax is not None and declared_tax is not None
            else None
        ),
        "computed_total_due": _money(computed_total),
        "declared_total_due": _money(declared_total),
        "total_variance": _money(
            computed_total - declared_total if declared_total is not None else None
        ),
        "_tolerance": float(tolerance),
    }


def _validate_totals(totals: dict[str, Any]) -> list[dict[str, Any]]:
    """R8/R9/R10: Compare recomputed totals with the document's declared totals."""
    findings: list[dict[str, Any]] = []
    tolerance = Decimal(str(totals["_tolerance"]))

    def compare(rule_id: str, field: str, label: str, computed: float | None, declared: float | None) -> None:
        if computed is None or declared is None:
            findings.append(
                _finding(rule_id, "warning", f"{label} is missing from the document.", field=field)
            )
            return
        variance = Decimal(str(computed)) - Decimal(str(declared))
        if abs(variance) > tolerance:
            findings.append(
                _finding(
                    rule_id,
                    "warning",
                    f"{label} mismatch: computed ${computed:,.2f}, document ${declared:,.2f}.",
                    field=field,
                    details={"computed": computed, "declared": declared, "variance": float(variance)},
                )
            )

    compare(
        "R8_SUBTOTAL_RECONCILIATION",
        "subtotal",
        "Subtotal",
        totals["computed_subtotal"],
        totals["declared_subtotal"],
    )
    compare(
        "R9_TAX_RECONCILIATION",
        "tax_amount",
        "Sales tax",
        totals["computed_tax"],
        totals["declared_tax"],
    )
    compare(
        "R10_TOTAL_RECONCILIATION",
        "total_due",
        "Grand total",
        totals["computed_total_due"],
        totals["declared_total_due"],
    )
    return findings


def _validate_notes(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """R11: Surface operational exceptions that require field-team follow-up."""
    findings: list[dict[str, Any]] = []
    for note in parsed.get("notes", []):
        lowered = note.lower()
        matched = [keyword for keyword in RULES["exception_keywords"] if keyword in lowered]
        if matched:
            findings.append(
                _finding(
                    "R11_DOCUMENTED_EXCEPTION",
                    "warning",
                    f"Operational exception noted: {note}",
                    field="notes",
                    details={"keywords": matched, "note": note},
                )
            )
    return findings


def _build_routing(
    parsed: dict[str, Any],
    findings: list[dict[str, Any]],
    totals: dict[str, Any],
) -> dict[str, Any]:
    """R12: Convert severity and value into an actionable routing decision."""
    critical_count = sum(1 for item in findings if item["severity"] == "critical")
    warning_count = sum(1 for item in findings if item["severity"] == "warning")
    info_count = sum(1 for item in findings if item["severity"] == "info")

    risk_score = min(100, critical_count * 40 + warning_count * 15 + info_count * 3)
    total = totals.get("computed_total_due") or 0.0

    if critical_count:
        status = "ESCALATE"
        queue = "procurement-escalation"
        approvals = ["Procurement Manager", "Finance Controller"]
        reason = "Critical data gaps prevent safe straight-through processing."
    elif warning_count or total > RULES["max_auto_approve_total"]:
        status = "REVIEW"
        queue = "procurement-review"
        approvals = ["Procurement Lead"]
        if total > RULES["max_auto_approve_total"]:
            approvals.append("Finance Controller")
        reason = (
            "Invoice requires human review due to exceptions, value thresholds, "
            "or reconciliation differences."
        )
    else:
        status = "AUTO_APPROVE"
        queue = "auto-post-eligible"
        approvals = []
        reason = "All required fields and deterministic controls passed."

    if total <= RULES["max_auto_approve_total"]:
        value_band = "under_25k"
    else:
        value_band = "over_25k"

    return {
        "status": status,
        "queue": queue,
        "reason": reason,
        "risk_score": risk_score,
        "severity_counts": {
            "critical": critical_count,
            "warning": warning_count,
            "info": info_count,
        },
        "value_band": value_band,
        "approvals_required": approvals,
        "thresholds": {
            "max_auto_approve_total": RULES["max_auto_approve_total"],
            "high_value_line_threshold": RULES["high_value_line_threshold"],
            "bulk_quantity_threshold": RULES["bulk_quantity_threshold"],
        },
    }


def _build_actions(
    parsed: dict[str, Any], findings: list[dict[str, Any]], routing: dict[str, Any]
) -> list[dict[str, str]]:
    """Translate findings into concrete, owner-assigned next actions."""
    actions: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(owner: str, action: str) -> None:
        key = f"{owner}|{action}"
        if key not in seen:
            seen.add(key)
            actions.append({"owner": owner, "action": action})

    for finding in findings:
        rule = finding["rule_id"]
        if rule == "R1_REQUIRED_FIELD":
            add("Accounts Payable", "Request a corrected invoice from the supplier before posting.")
        elif rule == "R4_LINE_ARITHMETIC":
            add("AP Analyst", "Reconcile the line-item total with the supplier's source PDF.")
        elif rule == "R5_PRICE_ENVELOPE":
            add("Procurement", "Confirm the quoted unit price against the active PO or contract.")
        elif rule == "R7_HIGH_VALUE_LINE":
            add("Procurement Lead", "Approve the high-value material line before payment release.")
        elif rule == "R8_SUBTOTAL_RECONCILIATION":
            add("AP Analyst", "Recompute subtotal from the packing slip and invoice.")
        elif rule == "R9_TAX_RECONCILIATION":
            add("Finance", "Verify the tax jurisdiction and rate before posting.")
        elif rule == "R10_TOTAL_RECONCILIATION":
            add("Finance", "Place a soft hold until the grand total is reconciled.")
        elif rule == "R11_DOCUMENTED_EXCEPTION":
            note = finding["details"].get("note", "")
            if "late" in note.lower() or "delay" in note.lower():
                add("Field Operations", "Log the delivery delay and update the look-ahead schedule.")
            if "short" in note.lower() or "missing" in note.lower():
                add("Site Superintendent", "Verify received quantities against the packing slip.")
            if "substitut" in note.lower():
                add("Quality Control", "Review substitution approval and attached mill certificates.")
        elif rule == "R6_BULK_QUANTITY":
            add("Logistics", "Confirm yard capacity and staged delivery plan for bulk materials.")

    if routing["status"] == "ESCALATE":
        add("Procurement Manager", "Resolve critical data gaps before the invoice enters the ERP.")
    if routing["status"] == "REVIEW":
        add("Procurement Lead", f"Review and sign off in the '{routing['queue']}' queue.")

    if not actions and routing["status"] == "AUTO_APPROVE":
        add("Automation", "Post invoice via the straight-through-processing workflow.")

    return actions


def validate_and_route(parsed: dict[str, Any]) -> dict[str, Any]:
    """
    Run every deterministic rule and return the auditable routing decision.

    Parameters
    ----------
    parsed:
        Output from ``modules.parser.parse_invoice``.

    Returns
    -------
    dict
        ``status``, ``queue``, ``risk_score``, ``findings``, ``totals``,
        ``approvals_required``, and owner-assigned ``recommended_actions``.
    """
    if not isinstance(parsed, dict) or "line_items" not in parsed:
        raise ValueError("validate_and_route expects a parsed invoice dictionary.")

    findings: list[dict[str, Any]] = []
    findings.extend(_validate_required_fields(parsed))
    findings.extend(_validate_line_items(parsed))

    totals = _calculate_totals(parsed)
    findings.extend(_validate_totals(totals))
    findings.extend(_validate_notes(parsed))

    routing = _build_routing(parsed, findings, totals)
    actions = _build_actions(parsed, findings, routing)

    # Remove internal-only keys before exposing the totals contract.
    public_totals = {key: value for key, value in totals.items() if not key.startswith("_")}

    return {
        "rules_version": RULES_VERSION,
        "status": routing["status"],
        "queue": routing["queue"],
        "reason": routing["reason"],
        "risk_score": routing["risk_score"],
        "severity_counts": routing["severity_counts"],
        "value_band": routing["value_band"],
        "approvals_required": routing["approvals_required"],
        "thresholds": routing["thresholds"],
        "totals": public_totals,
        "findings": findings,
        "recommended_actions": actions,
    }


if __name__ == "__main__":
    # Quick manual check: python -m modules.router
    import json

    from modules.parser import parse_invoice_file

    print(json.dumps(validate_and_route(parse_invoice_file()), indent=2))
