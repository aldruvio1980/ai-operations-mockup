# ai-operations-mockup

> **From PDFs, spreadsheets, and email → to one real-time truth.**
> A lightweight, local-first demo of an AI-assisted operations system for construction and logistics.

---

## Executive summary

Construction and logistics teams still run critical purchasing decisions through a fragile chain of scanned PDFs, forwarded email threads, supplier spreadsheets, and "please verify" notes from the field. Accounts Payable cannot tell whether an invoiced quantity was actually received. Procurement cannot see which delivery exception threatens the schedule. Finance cannot release payment without manually rebuilding the math.

**ai-operations-mockup** demonstrates a different operating model in a single terminal session:

1. A messy supplier invoice is ingested as raw text.
2. Deterministic code extracts the operational entities and **recalculates every dollar**.
3. A rules engine validates thresholds, reconciles totals, and routes the invoice.
4. A local AI agent layer adds context from field notes, prioritises actions, and drafts the supplier follow-up.
5. A "real-time truth" dashboard gives field, purchasing, and finance the same view.

The result is not a chatbot bolted onto AP. It is an **auditable decision pipeline** where deterministic code owns money and compliance, while AI owns interpretation, prioritisation, and communication.

### What the demo finds in the sample invoice

| Signal | Result |
|---|---|
| Supplier | APEX STEEL & SUPPLY CO. |
| Invoice / PO | INV-88421 / NC-2026-0447 |
| Project | Northline Tower - Phase 2 |
| Extracted line items | 6 |
| Computed total | **$45,342.64** (document: $45,342.63; $0.01 variance within tolerance) |
| Routing decision | **REVIEW** → `procurement-review` queue |
| Risk score | 66 / 100 |
| Top operational risks | Late beam drop, possible 12-unit hard-hat shortage, rebar substitution needing QC sign-off |
| AI output | Prioritised actions, field brief, timestamped action log, draft supplier email |

The invoice is routed to a human not because the math is wrong, but because **operational context matters**: a critical-path delivery slipped, safety equipment may be short, and a material substitution needs documentation before payment release.

---

## Why this architecture

Most "AI for operations" demos put a language model in the middle of the financial calculation. That is the wrong control boundary.

This project separates the problem into two layers:

| Layer | Owns | Why |
|---|---|---|
| **Deterministic code** | Extraction, arithmetic, tax, thresholds, routing, audit trail | Repeatable, testable, explainable, and safe for money |
| **Local AI agent** | Narrative, context from notes, prioritisation, owner assignment, draft communication | Handles ambiguity and free text without changing the financial truth |

The agent can never overwrite a computed total. Every recommendation is traceable to a parsed field, a rule, or a source note. The entire demo runs **offline with zero network calls and zero third-party Python packages**.

### Architecture at a glance

```text
sample_data/mock_invoice.txt
            │
            ▼
┌──────────────────────────────┐
│ modules/parser.py            │  Deterministic extraction
│ supplier · PO · line items   │  dot leaders, messy spacing, notes
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ modules/router.py            │  Deterministic validation
│ arithmetic · thresholds      │  price bands · reconciliation
│ routing · audit findings     │  risk score · approvals
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ modules/agent_hook.py        │  Local AI simulation
│ insights · actions · brief   │  action log · draft follow-up
│ 0 network calls              │  human approval required
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ main.py                      │  Interactive terminal experience
│ guided demo · menu · JSON    │  real-time truth dashboard
└──────────────────────────────┘
```

---

## Quick start (under 60 seconds)

**Requirements:** Python 3.10+ and a terminal. No database, API key, Docker, or cloud account.

```bash
git clone <your-repository-url> ai-operations-mockup
cd ai-operations-mockup
python3 main.py
```

That is the entire setup. `requirements.txt` intentionally contains no runtime dependencies.

If you prefer an isolated environment:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python3 main.py
```

### Run modes

```bash
python3 main.py                 # interactive menu
python3 main.py --demo          # full guided walkthrough
python3 main.py --demo --no-pause
python3 main.py --json          # full machine-readable pipeline report
python3 main.py --save          # write output/operations_report.json
python3 main.py --input path/to/other_invoice.txt
python3 -m unittest discover -s tests -v
```

### Interactive menu

```text
1  Run the full guided demo
2  Load + parse the sample document
3  Run deterministic validation
4  Run the local AI agent layer
5  Show the real-time truth dashboard
6  Export the full JSON report
0  Exit
```

The guided demo walks through five stages: **ingest → extract → validate → augment → act**.

---

## How deterministic code and AI work together

### Deterministic path (the source of truth)

`modules/parser.py`
- Reads the raw email/PDF text.
- Extracts supplier identity, invoice metadata, PO, project, line items, units, prices, totals, and notes.
- Handles dot leaders, irregular spacing, currency symbols, thousands separators, and missing fields.
- Emits explicit parse warnings instead of silently guessing.

`modules/router.py`
- Recalculates each line as `quantity × unit price`.
- Recomputes subtotal, tax, freight, and grand total independently.
- Reconciles computed values against the supplier's declared values.
- Applies business thresholds and category price envelopes.
- Converts findings into a routing decision, risk score, required approvals, and owner-assigned actions.

**The dashboard's "real-time truth" total comes from this layer, not from the AI.**

### AI agent path (the context layer)

`modules/agent_hook.py`
- Detects operational context in free-text notes: late deliveries, shortages, substitutions, and reconciliation anomalies.
- Builds a spend and quantity profile for the invoice.
- Explains why an exception matters to the schedule, safety, cash flow, or quality.
- Produces a timestamped action log, prioritised actions with named owners and due windows, a field brief, and a draft supplier follow-up.
- Makes **no network calls** and uses **no model SDK** in this demo. The heuristics simulate a local LLM adapter while keeping the output contract stable.

**Production seam:** replace the private `_synthesise()` function with an adapter for a local model (for example Ollama or llama.cpp) that returns the same JSON shape. The deterministic parser, router, dashboard, and audit contract do not change.

### Separation of responsibilities

| Decision | Owner |
|---|---|
| What quantity and price were extracted | Deterministic parser |
| What the invoice actually totals | Deterministic router |
| Whether the invoice needs review | Deterministic router |
| Which exception matters most right now | Local AI agent |
| Who should act and by when | Local AI agent (human approves) |
| Whether to release payment | Human approver |
| What gets posted to the ERP | Existing ERP workflow, after approval |

---

## Business rules in the demo

Thresholds live at the top of `modules/router.py` so they are easy to review and change.

| Rule | Control |
|---|---|
| R1 | Required metadata, supplier, and line items must be present |
| R2 | Every line must have a description, positive quantity, and valid price |
| R3 | Unit of measure must be recognised |
| R4 | Line total must equal quantity × unit price |
| R5 | Unit price must sit inside a category-specific envelope |
| R6 | Bulk quantities (200+ units) require receiving/logistics review |
| R7 | Line values over $10,000 require procurement sign-off |
| R8 | Computed subtotal must reconcile with the declared subtotal |
| R9 | Computed tax must reconcile with the declared tax |
| R10 | Computed grand total must reconcile with the declared total |
| R11 | Free-text field exceptions are surfaced for follow-up |
| R12 | Severity and value determine queue, risk score, and approvals |

In the sample, the tax variance is **$0.01**, inside the configured **$0.02** tolerance. The invoice still routes to **REVIEW** because of the high-value steel line, bulk quantities, and three documented field exceptions.

---

## Project structure

```text
ai-operations-mockup/
├── main.py                     # interactive CLI + dashboard
├── requirements.txt            # no runtime dependencies
├── README.md
├── modules/
│   ├── __init__.py
│   ├── parser.py               # deterministic extraction
│   ├── router.py               # rules, arithmetic, routing
│   └── agent_hook.py           # local AI simulation layer
├── sample_data/
│   └── mock_invoice.txt        # messy construction/logistics invoice
├── tests/
│   └── test_pipeline.py        # dependency-free regression tests
└── output/                     # created on export (git-ignored)
```

### Output contract

`main.py --json` returns a single report with three sections:

```json
{
  "project": "ai-operations-mockup",
  "generated_at": "…",
  "parsed": { "supplier": {}, "metadata": {}, "line_items": [], "notes": [] },
  "validation": { "status": "REVIEW", "risk_score": 66, "totals": {}, "findings": [] },
  "agent": { "executive_summary": "…", "insights": [], "recommended_actions": [], "action_log": [] }
}
```

This is the integration seam for an ERP, AP workflow, data warehouse, or a future web UI.

---

## Design principles

- **Local-first:** sensitive invoices never leave the machine.
- **Zero dependencies:** stdlib only, so reviewers can run it immediately.
- **Auditable:** raw text, parsed entities, computed totals, findings, and agent actions are all preserved.
- **Explainable:** every routing decision maps to a numbered rule.
- **Human-in-the-loop:** AI drafts and prioritises; humans approve money movement.
- **Extensible:** adapters can add OCR, a local LLM, an ERP connector, or real messaging without rewriting the core.

## Production extensions

- Replace the text sample with OCR output from scanned PDFs.
- Add supplier/master-data lookup and PO three-way matching.
- Store thresholds and approvals in versioned configuration.
- Add authentication, role-based approvals, and a durable audit store.
- Swap the heuristic agent for a local model with JSON-schema-constrained output.
- Connect approved invoices to an ERP or accounting system.
- Add automated tests around parser fixtures and rule thresholds.

## Security and limitations

This is a mockup, not a production AP system. It contains synthetic data, no authentication, no persistence, and a simulated AI layer. The included invoice and supplier details are fictional. The architecture is intentionally small so engineering leads can inspect every decision path in a single sitting.

---

## Repository location

On this machine the project lives at:

```text
~/Desktop/ai-operations-mockup
```

To publish it to GitHub after creating an empty repository:

```bash
cd ~/Desktop/ai-operations-mockup
git init
git add .
git commit -m "Build AI operations mockup for construction logistics"
git branch -M main
git remote add origin https://github.com/<your-account>/ai-operations-mockup.git
git push -u origin main
```

Or with the GitHub CLI:

```bash
gh repo create ai-operations-mockup --public --source=. --remote=origin --push
```
