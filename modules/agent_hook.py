"""
agent_hook.py
=============
Simulated local AI agent layer for real-time operational decision support.

Important: this module makes **no network calls** and uses **no third-party
model SDK**. It emulates the behaviour of a local LLM/agent (for example a
quantised Llama or Mistral model served by Ollama) using transparent heuristics.
That keeps the demo fast, free, reproducible, and safe for sensitive invoice
data.

Production integration seam
---------------------------
Replace the private ``_synthesise`` function with a local-model adapter. Keep
the public ``run_local_agent`` output contract unchanged so the UI, ERP hooks,
and audit log continue to work. The agent never changes deterministic totals; it
only interprets context and proposes actions for humans.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

AGENT_NAME = "local-ops-copilot"
AGENT_VERSION = "1.0.0-simulation"

# Category mapping used to turn line-item text into an operations profile.
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "structural steel": ("STEEL BEAM", "BEAM", "W24", "W18", "W21"),
    "concrete": ("CONCRETE", "READY-MIX"),
    "rebar": ("REBAR", "#5 REBAR", "#4 REBAR", "#6 REBAR"),
    "safety equipment": ("HARD HAT", "ANSI Z89.1", "GLOVE", "RESPIRATOR", "N95", "MASK"),
}


def _money(value: float | None) -> str:
    """Format a number for narrative output."""
    return f"${value:,.2f}" if value is not None else "n/a"


def _classify_item(description: str) -> str:
    """Assign a procurement category from deterministic keyword matching."""
    upper = description.upper()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in upper for keyword in keywords):
            return category
    return "other materials"


def _line_total(item: dict[str, Any]) -> float:
    """Prefer the deterministic computed total, then the declared value."""
    total = item.get("computed_line_total")
    if total is None:
        total = item.get("declared_line_total")
    if total is None:
        total = (item.get("quantity") or 0) * (item.get("unit_price") or 0)
    return float(total)


def _build_operational_profile(parsed: dict[str, Any]) -> dict[str, Any]:
    """Build a compact profile of spend, quantities, and exception signals."""
    category_spend: dict[str, float] = {}
    bulk_items: list[dict[str, Any]] = []
    high_value_items: list[dict[str, Any]] = []

    for item in parsed.get("line_items", []):
        category = _classify_item(str(item.get("description", "")))
        total = _line_total(item)
        category_spend[category] = round(category_spend.get(category, 0.0) + total, 2)
        if (item.get("quantity") or 0) >= 200:
            bulk_items.append(
                {
                    "description": item.get("description"),
                    "quantity": item.get("quantity"),
                    "unit": item.get("unit"),
                }
            )
        if total >= 10_000:
            high_value_items.append(
                {"description": item.get("description"), "line_total": total}
            )

    return {
        "category_spend": category_spend,
        "bulk_items": bulk_items,
        "high_value_items": high_value_items,
    }


def _build_insights(
    parsed: dict[str, Any], validation: dict[str, Any], profile: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    Convert deterministic signals into contextual, human-readable insights.

    This is the part a local LLM would phrase in natural language. The demo uses
    rules so reviewers can see exactly why the agent recommends an action.
    """
    insights: list[dict[str, Any]] = []
    notes = parsed.get("notes", [])
    invoice = parsed.get("metadata", {}).get("invoice_number", "the invoice")
    supplier = parsed.get("supplier", {}).get("name", "the supplier")

    def add(
        insight_id: str,
        category: str,
        severity: str,
        title: str,
        detail: str,
        impact: str,
        evidence: str,
    ) -> None:
        insights.append(
            {
                "id": insight_id,
                "category": category,
                "severity": severity,
                "title": title,
                "detail": detail,
                "impact": impact,
                "evidence": evidence,
            }
        )

    # Delivery exceptions are the richest source of field context in the sample.
    for note in notes:
        lowered = note.lower()
        if "late" in lowered or "delay" in lowered:
            add(
                "AI-01",
                "schedule",
                "high",
                "Delivery delay detected on structural material",
                f"A field note on {invoice} records a late delivery and a forklift "
                "constraint at the receiving yard.",
                "Potential impact to the erection sequence. Confirm the revised "
                "look-ahead schedule before releasing payment.",
                note,
            )
        if "short" in lowered or "missing" in lowered or "verify" in lowered:
            add(
                "AI-02",
                "receiving",
                "high",
                "Possible quantity shortage requires physical verification",
                "The document flags a possible short shipment, so invoiced "
                "quantities may not match what the site actually received.",
                "Paying in full before verification creates an overpayment and "
                "safety-stock risk. Reconcile against the packing slip today.",
                note,
            )
        if "substitut" in lowered:
            add(
                "AI-03",
                "quality",
                "medium",
                "Material substitution needs quality sign-off",
                f"{supplier} substituted an equivalent grade and references "
                "attached mill certificates.",
                "Confirm the substitution was approved by engineering and that the "
                "mill certs are in the quality package before closeout.",
                note,
            )

    # High-value lines are the main cash-flow and approval concern.
    if profile["high_value_items"]:
        top = max(profile["high_value_items"], key=lambda item: item["line_total"])
        total = validation.get("totals", {}).get("computed_total_due") or 0
        share = (top["line_total"] / total * 100) if total else 0
        add(
            "AI-04",
            "financial",
            "medium",
            "Concentrated spend on one material line",
            f"{top['description']} accounts for {_money(top['line_total'])}, or "
            f"{share:.1f}% of the invoice value.",
            "Requires procurement sign-off and confirms the invoice is correctly "
            "routed to the review queue rather than auto-posted.",
            f"Line total {_money(top['line_total'])}",
        )

    # Bulk quantities affect yard capacity, receiving labour, and reorder policy.
    if profile["bulk_items"]:
        labels = ", ".join(
            f"{item['quantity']:g} {item['unit']} {item['description']}"
            for item in profile["bulk_items"]
        )
        add(
            "AI-05",
            "logistics",
            "low",
            "Bulk materials require staged receiving",
            f"Bulk lines detected: {labels}.",
            "Confirm yard capacity and split deliveries so crews are not waiting "
            "on unloading equipment during peak hours.",
            "Quantity exceeds the 200-unit bulk threshold.",
        )

    # Surface reconciliation anomalies only when they are outside tolerance.
    totals = validation.get("totals", {})
    for field, label in (("subtotal_variance", "subtotal"), ("total_variance", "grand total")):
        variance = totals.get(field)
        if variance is not None and abs(variance) > 0.02:
            add(
                "AI-06",
                "financial",
                "high",
                f"Reconciliation variance in {label}",
                f"Computed {label} differs from the document by {_money(variance)}.",
                "Payment should be soft-held until finance reconciles the source PDF.",
                f"Variance {_money(variance)}",
            )

    if not insights:
        add(
            "AI-00",
            "controls",
            "info",
            "No operational exceptions detected",
            "The document passed deterministic controls with no contextual "
            "delivery, safety, or reconciliation exceptions.",
            "Eligible for normal straight-through processing.",
            "All rule checks passed.",
        )

    return insights


def _build_agent_actions(insights: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Translate agent insights into prioritised actions with clear ownership."""
    actions: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(priority: str, owner: str, action: str, due: str, source: str) -> None:
        key = (owner, action)
        if key not in seen:
            seen.add(key)
            actions.append(
                {
                    "priority": priority,
                    "owner": owner,
                    "action": action,
                    "due": due,
                    "source": source,
                }
            )

    for insight in insights:
        if insight["category"] == "receiving":
            add(
                "P0",
                "Site Superintendent",
                "Count hard hats, gloves, and masks against the packing slip before the next shift.",
                "today",
                insight["id"],
            )
            add(
                "P0",
                "Accounts Payable",
                "Do not release final payment until the receiving count is signed off.",
                "before payment release",
                insight["id"],
            )
        elif insight["category"] == "schedule":
            add(
                "P0",
                "Field Operations",
                "Log the beam-delivery delay and confirm the revised erection sequence.",
                "within 24 hours",
                insight["id"],
            )
        elif insight["category"] == "quality":
            add(
                "P1",
                "Quality Control",
                "Verify the rebar substitution approval and attach mill certificates to the QC record.",
                "within 48 hours",
                insight["id"],
            )
        elif insight["category"] == "financial":
            add(
                "P1",
                "Procurement Lead",
                "Approve the high-value steel line and document the commercial rationale.",
                "before payment release",
                insight["id"],
            )
        elif insight["category"] == "logistics":
            add(
                "P2",
                "Logistics Coordinator",
                "Confirm yard capacity and the staged delivery plan for bulk materials.",
                "this week",
                insight["id"],
            )

    if not actions:
        add(
            "P3",
            "Automation",
            "Continue straight-through processing and archive the audit record.",
            "automatic",
            "AI-00",
        )

    return actions


def _build_action_log(
    parsed: dict[str, Any], validation: dict[str, Any], insights: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Create a timestamped, audit-friendly stream of agent decisions."""
    invoice = parsed.get("metadata", {}).get("invoice_number", "UNKNOWN")
    supplier = parsed.get("supplier", {}).get("name", "UNKNOWN")
    status = validation.get("status", "UNKNOWN")
    queue = validation.get("queue", "UNKNOWN")
    risk = validation.get("risk_score", 0)
    item_count = len(parsed.get("line_items", []))
    warning_count = len(parsed.get("parse_warnings", []))
    base = datetime.now(timezone.utc)

    events: list[dict[str, Any]] = [
        {
            "event": "DOCUMENT_RECEIVED",
            "severity": "info",
            "detail": f"{invoice} received from {supplier}; source={parsed.get('source', 'unknown')}.",
        },
        {
            "event": "EXTRACTION_COMPLETE",
            "severity": "info",
            "detail": f"{item_count} line items parsed with {warning_count} parser warning(s).",
        },
        {
            "event": "DETERMINISTIC_VALIDATION",
            "severity": "warning" if status != "AUTO_APPROVE" else "info",
            "detail": f"Rules engine returned {status} (risk {risk}/100).",
        },
    ]

    for insight in insights:
        if insight["severity"] in {"high", "medium"}:
            events.append(
                {
                    "event": "CONTEXT_FLAG",
                    "severity": insight["severity"],
                    "detail": f"{insight['id']} {insight['title']}: {insight['impact']}",
                }
            )

    events.append(
        {
            "event": "ROUTING_DECISION",
            "severity": "warning" if status != "AUTO_APPROVE" else "info",
            "detail": f"Queued in '{queue}'. {validation.get('reason', '')}",
        }
    )

    log: list[dict[str, Any]] = []
    for index, event in enumerate(events, start=1):
        timestamp = base + timedelta(milliseconds=120 * index)
        event["sequence"] = index
        event["timestamp"] = timestamp.isoformat().replace("+00:00", "Z")
        log.append(event)
    return log


def _build_supplier_followup(
    parsed: dict[str, Any], insights: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Draft a follow-up message when exceptions need supplier confirmation."""
    exception_categories = {item["category"] for item in insights}
    if not exception_categories.intersection({"receiving", "schedule", "quality"}):
        return None

    metadata = parsed.get("metadata", {})
    supplier = parsed.get("supplier", {})
    invoice = metadata.get("invoice_number", "the invoice")
    po = metadata.get("po_number", "the referenced PO")
    project = metadata.get("project", "the project")

    asks: list[str] = []
    if "receiving" in exception_categories:
        asks.append(
            "confirm the delivered hard-hat quantity against the packing slip and "
            "advise whether a 12-unit shortage will be credited or replaced"
        )
    if "schedule" in exception_categories:
        asks.append(
            "confirm the carrier's explanation for the delayed beam drop and the "
            "revised delivery ticket"
        )
    if "quality" in exception_categories:
        asks.append(
            "provide the approved substitution record and mill certificates for the rebar"
        )

    body = (
        f"Hello {supplier.get('name', 'team')},\n\n"
        f"We are reconciling invoice {invoice} against {po} for {project}. "
        "Before we release the balance, please help us close the following items:\n\n"
        + "\n".join(f"{index}. {ask.capitalize()}" for index, ask in enumerate(asks, start=1))
        + "\n\nPlease reply with the supporting documents or a corrected invoice.\n\n"
        "Thank you,\nProcurement Operations"
    )

    return {
        "to": supplier.get("email"),
        "subject": f"{invoice} - delivery exception follow-up ({po})",
        "body": body,
        "status": "draft_only",
    }


def _synthesise(
    parsed: dict[str, Any], validation: dict[str, Any]
) -> dict[str, Any]:
    """
    Private synthesis seam.

    Replace this function with a local LLM adapter (e.g. Ollama) that receives
    the parsed JSON plus validator output and returns the same shape. The rest of
    the application does not need to change.
    """
    totals = validation.get("totals", {})
    metadata = parsed.get("metadata", {})
    supplier = parsed.get("supplier", {})
    profile = _build_operational_profile(parsed)
    insights = _build_insights(parsed, validation, profile)
    actions = _build_agent_actions(insights)
    action_log = _build_action_log(parsed, validation, insights)
    followup = _build_supplier_followup(parsed, insights)

    invoice = metadata.get("invoice_number", "UNKNOWN")
    project = metadata.get("project", "unassigned project")
    po = metadata.get("po_number", "no PO")
    total = totals.get("computed_total_due")
    status = validation.get("status", "UNKNOWN")
    risk_score = validation.get("risk_score", 0)
    queue = validation.get("queue", "unknown")

    high_insights = [item for item in insights if item["severity"] == "high"]
    context_clause = (
        " The highest-impact context is " + " and ".join(
            item["title"].lower() for item in high_insights[:2]
        ) + "."
        if high_insights
        else " No high-severity field exceptions were detected."
    )

    executive_summary = (
        f"{supplier.get('name', 'The supplier')} submitted {invoice} against {po} "
        f"for {project}. The deterministic truth is {_money(total)} across "
        f"{len(parsed.get('line_items', []))} line items. Controls routed the "
        f"invoice to {status} (risk {risk_score}/100) in the '{queue}' queue."
        f"{context_clause}"
    )

    # Confidence reflects document quality and control outcomes, not model ego.
    confidence = 0.95
    confidence -= 0.10 * len(parsed.get("parse_warnings", []))
    confidence -= 0.25 if validation.get("severity_counts", {}).get("critical") else 0.0
    for variance_key in ("subtotal_variance", "tax_variance", "total_variance"):
        if totals.get(variance_key) is not None and abs(totals[variance_key]) > 0.02:
            confidence -= 0.05
    confidence = round(max(0.35, min(0.99, confidence)), 2)

    if status == "ESCALATE":
        risk_level = "critical"
    elif risk_score >= 50:
        risk_level = "elevated"
    elif status == "REVIEW":
        risk_level = "moderate"
    else:
        risk_level = "low"

    brief_parts: list[str] = []
    for insight in insights:
        if insight["category"] == "receiving":
            brief_parts.append("verify safety-gear counts against the packing slip before the next shift")
        elif insight["category"] == "schedule":
            brief_parts.append("log the beam-delivery delay and re-check the erection sequence")
        elif insight["category"] == "quality":
            brief_parts.append("collect the rebar substitution approval and mill certificates")
    field_brief = (
        "Site brief: " + "; ".join(brief_parts) + "."
        if brief_parts
        else "Site brief: no field-side exceptions; continue normal receiving."
    )

    return {
        "agent": {
            "name": AGENT_NAME,
            "version": AGENT_VERSION,
            "mode": "offline-simulation",
            "llm_calls": 0,
            "network_calls": 0,
            "note": (
                "Transparent local heuristics stand in for a local LLM. No invoice "
                "data leaves this machine; swap _synthesise() for a local model "
                "adapter while preserving this output contract."
            ),
        },
        "summary": {
            "invoice_number": invoice,
            "supplier": supplier.get("name"),
            "po_number": po,
            "project": project,
            "computed_total_due": total,
            "status": status,
            "queue": queue,
            "risk_score": risk_score,
            "line_item_count": len(parsed.get("line_items", [])),
            "exception_count": len([item for item in insights if item["severity"] in {"high", "medium"}]),
        },
        "executive_summary": executive_summary,
        "confidence": confidence,
        "risk_level": risk_level,
        "operational_profile": profile,
        "insights": insights,
        "recommended_actions": actions,
        "action_log": action_log,
        "field_brief": field_brief,
        "supplier_followup": followup,
        "guardrails": [
            "Deterministic totals are never overwritten by the agent.",
            "All recommendations require named human ownership.",
            "The agent is simulation-only in this demo and makes zero network calls.",
        ],
    }


def run_local_agent(
    parsed: dict[str, Any], validation: dict[str, Any]
) -> dict[str, Any]:
    """
    Public agent entry point.

    Parameters
    ----------
    parsed:
        Parsed invoice dictionary from ``modules.parser``.
    validation:
        Deterministic routing output from ``modules.router``.

    Returns
    -------
    dict
        Structured AI summary, insight stream, action log, and draft follow-up.
    """
    if not isinstance(parsed, dict) or not isinstance(validation, dict):
        raise ValueError("run_local_agent expects parsed and validation dictionaries.")
    return _synthesise(parsed, validation)


if __name__ == "__main__":
    # Quick manual check: python -m modules.agent_hook
    import json

    from modules.parser import parse_invoice_file
    from modules.router import validate_and_route

    parsed_invoice = parse_invoice_file()
    routed = validate_and_route(parsed_invoice)
    print(json.dumps(run_local_agent(parsed_invoice, routed), indent=2))
