#!/usr/bin/env python3
"""
main.py
=======
Interactive entry point for the ai-operations-mockup.

Run:
    python3 main.py              # interactive menu (TTY) or guided demo
    python3 main.py --demo       # force the full guided walkthrough
    python3 main.py --json       # machine-readable pipeline report
    python3 main.py --save       # write output/operations_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.agent_hook import run_local_agent
from modules.parser import parse_invoice_file
from modules.router import validate_and_route

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = PROJECT_ROOT / "output" / "operations_report.json"
WIDTH = max(72, min(92, shutil.get_terminal_size((84, 24)).columns))


class Colour:
    """Tiny ANSI helper with graceful fallback for pipes, CI, and NO_COLOR."""

    ENABLED = sys.stdout.isatty() and os.getenv("NO_COLOR") is None

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GREY = "\033[90m"

    @classmethod
    def paint(cls, text: str, colour: str) -> str:
        return f"{colour}{text}{cls.RESET}" if cls.ENABLED else text


def c(text: str, colour: str) -> str:
    """Short alias used throughout the UI."""
    return Colour.paint(text, colour)


def _truncate(text: str, width: int) -> str:
    """Trim long descriptions without breaking table alignment."""
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def _wrap(text: str, indent: str = "") -> str:
    """Wrap prose to the current terminal width."""
    return textwrap.fill(
        text,
        width=WIDTH,
        initial_indent=indent,
        subsequent_indent=indent,
        replace_whitespace=False,
    )


def _fmt_money(value: float | None) -> str:
    """Format a money value with a leading minus sign for negative variances."""
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _rule(title: str = "") -> None:
    """Print a visual section separator."""
    if not title:
        print(c("─" * WIDTH, Colour.GREY))
        return
    label = f" {title} "
    remaining = max(0, WIDTH - len(label) - 2)
    print(c(f"──{label}" + "─" * remaining, Colour.GREY))


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _visible_len(text: str) -> int:
    """Measure printable width while ignoring ANSI colour sequences."""
    return len(_ANSI_RE.sub("", text))


def _box(title: str, lines: list[str]) -> None:
    """Render a simple full-width box with a right border."""
    inner = WIDTH - 2
    print(c("╔" + "═" * inner + "╗", Colour.CYAN))
    print(c("║ " + title.ljust(inner - 1) + "║", Colour.BOLD + Colour.CYAN))
    print(c("╠" + "═" * inner + "╣", Colour.CYAN))
    for line in lines:
        padding = max(0, inner - 1 - _visible_len(line))
        print(c("║ ", Colour.CYAN) + line + " " * padding + c("║", Colour.CYAN))
    print(c("╚" + "═" * inner + "╝", Colour.CYAN))


def _status_colour(status: str) -> str:
    return {
        "AUTO_APPROVE": Colour.GREEN,
        "REVIEW": Colour.YELLOW,
        "ESCALATE": Colour.RED,
    }.get(status, Colour.GREY)


def _severity_colour(severity: str) -> str:
    return {
        "critical": Colour.RED,
        "high": Colour.RED,
        "warning": Colour.YELLOW,
        "medium": Colour.YELLOW,
        "info": Colour.CYAN,
        "low": Colour.GREY,
    }.get(severity.lower(), Colour.GREY)


def _risk_bar(score: int) -> str:
    bounded = max(0, min(100, int(score)))
    filled = round(bounded / 5)
    colour = Colour.GREEN if bounded < 25 else Colour.YELLOW if bounded < 60 else Colour.RED
    return c("█" * filled + "░" * (20 - filled), colour) + f" {bounded}/100"


class OpsDemo:
    """Holds pipeline state and renders each stage of the demo."""

    def __init__(self, input_path: str | Path | None = None, no_pause: bool = False):
        self.input_path = Path(input_path) if input_path else None
        self.no_pause = no_pause or not sys.stdin.isatty()
        self.raw_text: str | None = None
        self.parsed: dict[str, Any] | None = None
        self.validation: dict[str, Any] | None = None
        self.agent: dict[str, Any] | None = None
        self.banner_printed = False

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def load_raw(self) -> str:
        """Read the raw document once and keep it for the ingest preview."""
        if self.raw_text is None:
            parsed = parse_invoice_file(self.input_path)
            self.raw_text = parsed["raw_text"]
            self.parsed = parsed
        return self.raw_text

    def ensure_parsed(self) -> dict[str, Any]:
        if self.parsed is None:
            self.parsed = parse_invoice_file(self.input_path)
            self.raw_text = self.parsed["raw_text"]
        return self.parsed

    def ensure_validation(self) -> dict[str, Any]:
        if self.validation is None:
            self.validation = validate_and_route(self.ensure_parsed())
        return self.validation

    def ensure_agent(self) -> dict[str, Any]:
        if self.agent is None:
            self.agent = run_local_agent(self.ensure_parsed(), self.ensure_validation())
        return self.agent

    def reset(self) -> None:
        self.raw_text = None
        self.parsed = None
        self.validation = None
        self.agent = None

    # ------------------------------------------------------------------
    # Presentation helpers
    # ------------------------------------------------------------------
    def print_banner(self) -> None:
        if self.banner_printed:
            return
        self.banner_printed = True
        print()
        _box(
            "AI OPERATIONS MOCKUP  ·  Construction & Logistics",
            [
                c("From PDFs, spreadsheets and email → to one real-time truth.", Colour.BOLD),
                c("Deterministic controls for money. Local AI for context and action.", Colour.DIM),
                "",
                f"{c('Pipeline', Colour.CYAN)}  ingest → extract → validate → augment → act",
                f"{c('Safety', Colour.CYAN)}    zero network calls · zero third-party packages",
            ],
        )

    def pause(self, message: str = "Press Enter to continue") -> None:
        if self.no_pause:
            return
        try:
            input(c(f"\n{message}... ", Colour.DIM))
        except EOFError:
            self.no_pause = True

    def stage_header(self, step: int, title: str, subtitle: str) -> None:
        print()
        _rule(f"STEP {step}/5 · {title}")
        print(c(subtitle, Colour.DIM))
        print()

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------
    def show_ingest(self) -> None:
        raw = self.load_raw()
        lines = raw.splitlines()
        size_kb = len(raw.encode("utf-8")) / 1024
        print(f"{c('Source', Colour.BOLD):<20} {self.input_path or 'sample_data/mock_invoice.txt'}")
        print(f"{c('Document', Colour.BOLD):<20} {len(lines)} lines · {size_kb:.1f} KB · raw email/PDF text")
        print(f"{c('Challenge', Colour.BOLD):<20} dot leaders, irregular spacing, mixed units, free-text notes")
        print()
        print(c("Raw preview (first 9 lines):", Colour.DIM))
        for line in lines[:9]:
            print(c("  │ ", Colour.GREY) + _truncate(line, WIDTH - 5))
        if len(lines) > 9:
            print(c("  │ …", Colour.GREY))

    def show_parse(self) -> None:
        parsed = self.ensure_parsed()
        supplier = parsed["supplier"]
        meta = parsed["metadata"]

        print(f"{c('Supplier', Colour.BOLD):<20} {supplier.get('name')}  <{supplier.get('email')}>")
        print(f"{c('Invoice', Colour.BOLD):<20} {meta.get('invoice_number')}  ·  date {meta.get('invoice_date')}")
        print(f"{c('Purchase order', Colour.BOLD):<20} {meta.get('po_number')}")
        print(f"{c('Project', Colour.BOLD):<20} {meta.get('project')}")
        print(f"{c('Line items', Colour.BOLD):<20} {len(parsed['line_items'])}")
        print()
        self.print_line_items(parsed["line_items"])

        warnings = parsed.get("parse_warnings", [])
        print()
        if warnings:
            print(c(f"Parser warnings ({len(warnings)}):", Colour.YELLOW))
            for warning in warnings:
                print(c("  ! ", Colour.YELLOW) + _wrap(warning, "    "))
        else:
            print(c("Parser warnings: none", Colour.GREEN))

    def print_line_items(self, items: list[dict[str, Any]]) -> None:
        desc_width = max(22, WIDTH - 48)
        header = (
            f"{'#':>2}  {'ITEM':<{desc_width}} {'QTY':>6} {'UNIT':<4} "
            f"{'UNIT PRICE':>11} {'LINE TOTAL':>12}"
        )
        print(c(_truncate(header, WIDTH), Colour.BOLD))
        print(c("─" * WIDTH, Colour.GREY))
        for item in items:
            quantity = item.get("quantity")
            quantity_text = f"{quantity:g}" if isinstance(quantity, (int, float)) else "?"
            unit_price = item.get("unit_price")
            line_total = item.get("computed_line_total")
            price_text = f"${unit_price:,.2f}" if unit_price is not None else "?"
            total_text = f"${line_total:,.2f}" if line_total is not None else "?"
            row = (
                f"{item.get('line_number', '?'):>2}  "
                f"{_truncate(str(item.get('description', '')), desc_width):<{desc_width}} "
                f"{quantity_text:>6} {str(item.get('unit', '')):<4} "
                f"{price_text:>11} {total_text:>12}"
            )
            print(_truncate(row, WIDTH))

    def show_validation(self) -> None:
        validation = self.ensure_validation()
        totals = validation["totals"]

        status = validation["status"]
        print(
            f"{c('Decision', Colour.BOLD):<20} "
            f"{c(status, _status_colour(status) + Colour.BOLD)}  ·  "
            f"queue: {validation['queue']}  ·  risk: {_risk_bar(validation['risk_score'])}"
        )
        print(f"{c('Rules version', Colour.BOLD):<20} {validation['rules_version']}")
        print(c('Why', Colour.BOLD))
        print(_wrap(validation["reason"], "  "))
        print()
        print(c("Deterministic financial truth", Colour.BOLD))
        print(
            f"  {'Materials subtotal':<27} "
            f"{c(_fmt_money(totals['computed_subtotal']), Colour.BOLD)}"
            f"   (document: {_fmt_money(totals['declared_subtotal'])})"
        )
        print(f"  {'Freight':<27} {_fmt_money(totals['freight'])}")
        rate = totals.get("tax_rate_percent")
        rate_text = f"{rate:g}%" if rate is not None else "n/a"
        print(
            f"  {('Sales tax ' + rate_text):<27} "
            f"{c(_fmt_money(totals['computed_tax']), Colour.BOLD)}"
            f"   (document: {_fmt_money(totals['declared_tax'])})"
        )
        print(
            f"  {'TOTAL DUE':<27} {c(_fmt_money(totals['computed_total_due']), Colour.BOLD)}"
            f"   (document: {_fmt_money(totals['declared_total_due'])})"
        )
        variance_ok = abs(totals['total_variance'] or 0) <= 0.02
        variance_note = (
            c('within tolerance ($0.02)', Colour.GREEN)
            if variance_ok
            else c('REVIEW REQUIRED', Colour.RED)
        )
        print(f"  Variance             {_fmt_money(totals['total_variance'])}  {variance_note}")
        print()
        print(c("Rule findings", Colour.BOLD))
        for finding in validation["findings"]:
            tag = finding["severity"].upper()
            print(
                c(f"  [{tag:<8}]", _severity_colour(finding["severity"]))
                + f" {finding['rule_id']}"
            )
            print(_wrap(finding["message"], "             "))

    def show_agent(self) -> None:
        agent = self.ensure_agent()
        meta = agent["agent"]

        print(
            f"{c('Agent', Colour.BOLD):<20} {meta['name']} {meta['version']}  ·  "
            f"{c('offline simulation', Colour.MAGENTA)}  ·  "
            f"{meta['network_calls']} network calls"
        )
        print(
            f"{c('Risk level', Colour.BOLD):<20} {agent['risk_level'].upper()}  ·  "
            f"confidence {agent['confidence'] * 100:.0f}%"
        )
        print()
        print(c("Executive summary", Colour.BOLD))
        print(c(_wrap(agent["executive_summary"], "  "), Colour.CYAN))
        print()
        print(c("Contextual insights", Colour.BOLD))
        for insight in agent["insights"]:
            severity = insight["severity"].upper()
            print(
                c(f"  [{severity:<6}]", _severity_colour(insight["severity"]))
                + f" {insight['id']} {c(insight['title'], Colour.BOLD)}"
            )
            print(_wrap(insight["detail"], "           "))
            print(c(_wrap(f"Impact: {insight['impact']}", "           "), Colour.DIM))
        print()
        print(c("Recommended actions", Colour.BOLD))
        for action in agent["recommended_actions"]:
            line = (
                f"[{action['priority']}] {action['owner']}: "
                f"{action['action']} ({action['due']})"
            )
            print(c(_wrap(line, "  "), Colour.YELLOW if action["priority"] == "P0" else Colour.RESET))
        print()
        print(c("Field brief", Colour.BOLD))
        print(_wrap(agent["field_brief"], "  "))
        print()
        print(c("Automated action log", Colour.BOLD))
        for event in agent["action_log"]:
            print(
                c(f"  {event['timestamp']}  ", Colour.GREY)
                + c(event["event"], _severity_colour(event["severity"]))
            )
            print(_wrap(event["detail"], "    "))
        followup = agent.get("supplier_followup")
        if followup:
            print()
            print(c("Draft supplier follow-up (human approval required)", Colour.BOLD))
            print(f"  To:      {followup['to']}")
            print(f"  Subject: {followup['subject']}")
            print()
            for line in followup["body"].splitlines():
                print(_wrap(line, "  ") if line else "")

    def show_dashboard(self) -> None:
        parsed = self.ensure_parsed()
        validation = self.ensure_validation()
        agent = self.ensure_agent()
        meta = parsed["metadata"]
        supplier = parsed["supplier"]
        totals = validation["totals"]
        status = validation["status"]

        print()
        title = "REAL-TIME TRUTH DASHBOARD"
        inner = WIDTH - 2
        print(c("╔" + "═" * inner + "╗", Colour.CYAN))
        print(c("║ " + title.ljust(inner - 1) + "║", Colour.BOLD + Colour.CYAN))
        print(c("╚" + "═" * inner + "╝", Colour.CYAN))
        print(
            c(
                f"  Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}"
                f"  ·  source: {Path(parsed['source']).name}",
                Colour.DIM,
            )
        )
        print()

        _rule("Document identity")
        print(f"  {c('Supplier', Colour.BOLD):<16} {supplier.get('name')}")
        print(f"  {c('Invoice', Colour.BOLD):<16} {meta.get('invoice_number')}   {c('PO', Colour.BOLD)} {meta.get('po_number')}")
        print(f"  {c('Project', Colour.BOLD):<16} {meta.get('project')}")
        print(f"  {c('Invoice date', Colour.BOLD):<16} {meta.get('invoice_date')}   {c('Due', Colour.BOLD)} {meta.get('due_date')}")
        print(f"  {c('Status', Colour.BOLD):<16} {c(status, _status_colour(status) + Colour.BOLD)}  ·  queue {validation['queue']}  ·  risk {_risk_bar(validation['risk_score'])}")

        print()
        _rule("Financial truth (deterministic)")
        print(f"  Materials subtotal          {c(_fmt_money(totals['computed_subtotal']).rjust(13), Colour.BOLD)}")
        print(f"  Freight                     {c(_fmt_money(totals['freight']).rjust(13), Colour.BOLD)}")
        rate = totals.get("tax_rate_percent")
        rate_text = f"({rate:g}%)" if rate is not None else ""
        print(f"  Sales tax {rate_text:<19} {c(_fmt_money(totals['computed_tax']).rjust(13), Colour.BOLD)}")
        print(c("  " + "─" * 46, Colour.GREY))
        print(f"  {'TOTAL DUE':<28} {c(_fmt_money(totals['computed_total_due']).rjust(13), Colour.CYAN + Colour.BOLD)}")
        variance = totals.get("total_variance") or 0.0
        declared_total = _fmt_money(totals.get("declared_total_due"))
        if abs(variance) <= 0.02:
            variance_note = c(
                f"vs document {declared_total} · variance {_fmt_money(variance)} within tolerance",
                Colour.GREEN,
            )
        else:
            variance_note = c(
                f"vs document {declared_total} · variance {_fmt_money(variance)} — REVIEW",
                Colour.RED,
            )
        print(f"  {variance_note}")

        print()
        _rule("Extracted line items")
        self.print_line_items(parsed["line_items"])

        print()
        _rule("Control findings")
        counts = validation["severity_counts"]
        critical_text = c(f"{counts['critical']} critical", Colour.RED)
        warning_text = c(f"{counts['warning']} warning", Colour.YELLOW)
        info_text = c(f"{counts['info']} info", Colour.CYAN)
        approvals = ", ".join(validation["approvals_required"]) or "none"
        print(
            f"  {critical_text}  ·  {warning_text}  ·  {info_text}  ·  "
            f"approvals: {approvals}"
        )
        for finding in validation["findings"]:
            if finding["severity"] == "info":
                continue
            print(
                c(f"  [{finding['severity'].upper():<8}]", _severity_colour(finding["severity"]))
                + " "
                + finding["rule_id"]
            )
            print(_wrap(finding["message"], "             "))

        print()
        _rule("Local AI agent · contextual action layer")
        print(f"  {c('Risk', Colour.BOLD)} {agent['risk_level'].upper()}   {c('Confidence', Colour.BOLD)} {agent['confidence'] * 100:.0f}%   {c('Network calls', Colour.BOLD)} {agent['agent']['network_calls']}")
        print()
        print(c(_wrap(agent["executive_summary"], "  "), Colour.CYAN))
        print()
        print(c("  Top actions", Colour.BOLD))
        for action in agent["recommended_actions"][:6]:
            line = (
                f"[{action['priority']}] {action['owner']} — "
                f"{action['action']} ({action['due']})"
            )
            print(c(_wrap(line, "  "), Colour.YELLOW if action["priority"] == "P0" else Colour.RESET))
        print()
        print(c("  Field brief", Colour.BOLD))
        print(c(_wrap(agent["field_brief"], "  "), Colour.GREEN))
        followup = agent.get("supplier_followup")
        if followup:
            print()
            print(
                c("  Draft supplier follow-up: ", Colour.BOLD)
                + f"{followup['subject']} → {followup['to']}"
            )

        print()
        _rule()
        print(
            c(
                "  Deterministic code owns money and routing. The local AI layer owns "
                "context, prioritisation, and draft actions.",
                Colour.DIM,
            )
        )
        print(
            c(
                "  Every recommendation is traceable to a rule, a note, or a source line.",
                Colour.DIM,
            )
        )
        print()

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------
    def run_full_demo(self) -> None:
        self.print_banner()
        self.reset()
        self.load_raw()

        self.stage_header(1, "INGEST", "Load the raw, messy document exactly as it arrived.")
        self.show_ingest()
        self.pause()

        self.stage_header(2, "EXTRACT", "Deterministic parser converts unstructured text into trusted entities.")
        self.show_parse()
        self.pause()

        self.stage_header(3, "VALIDATE", "Business rules recalculate money, check thresholds, and route the work.")
        self.show_validation()
        self.pause()

        self.stage_header(4, "AUGMENT", "A local AI layer adds context, owners, and next actions — without touching the math.")
        self.show_agent()
        self.pause()

        self.stage_header(5, "ACT", "One dashboard: the real-time truth for field, purchasing, and finance.")
        self.show_dashboard()

    def build_report(self) -> dict[str, Any]:
        parsed = self.ensure_parsed()
        validation = self.ensure_validation()
        agent = self.ensure_agent()
        return {
            "project": "ai-operations-mockup",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "parsed": parsed,
            "validation": validation,
            "agent": agent,
        }

    def export_report(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else DEFAULT_OUTPUT
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.build_report(), indent=2), encoding="utf-8")
        return target

    def interactive_menu(self) -> None:
        self.print_banner()
        options = [
            ("1", "Run the full guided demo", self.run_full_demo),
            ("2", "Load + parse the sample document", self.show_parse),
            ("3", "Run deterministic validation", self.show_validation),
            ("4", "Run the local AI agent layer", self.show_agent),
            ("5", "Show the real-time truth dashboard", self.show_dashboard),
            ("6", "Export the full JSON report", lambda: self._menu_export()),
            ("0", "Exit", None),
        ]

        while True:
            print()
            _rule("INTERACTIVE MENU")
            for key, label, _ in options:
                print(f"  {c(key, Colour.CYAN)}  {label}")
            print()
            try:
                choice = input(c("Select an option: ", Colour.BOLD)).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                return

            match = next((item for item in options if item[0] == choice), None)
            if match is None:
                print(c("Unknown option. Choose 0-6.", Colour.YELLOW))
                continue
            if match[0] == "0":
                print(c("Goodbye. The truth is already in the terminal.", Colour.DIM))
                return

            try:
                match[2]()
            except (FileNotFoundError, ValueError) as exc:
                print(c(f"Pipeline error: {exc}", Colour.RED))
            except KeyboardInterrupt:
                print(c("\nInterrupted. Returning to menu.", Colour.DIM))
                continue

            if match[0] != "6":
                self.pause("Press Enter to return to the menu")
            else:
                self.pause("Press Enter to return to the menu")

    def _menu_export(self) -> None:
        target = self.export_report()
        print(c(f"Report written to {target}", Colour.GREEN))
        print(c(f"Size: {target.stat().st_size / 1024:.1f} KB", Colour.DIM))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AI operations mockup for construction and logistics invoices.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 main.py                 interactive menu\n"
            "  python3 main.py --demo          full guided walkthrough\n"
            "  python3 main.py --json          machine-readable report\n"
            "  python3 main.py --save report.json\n"
        ),
    )
    parser.add_argument("--demo", action="store_true", help="run the full guided demo and exit")
    parser.add_argument("--json", action="store_true", help="print the complete JSON pipeline report")
    parser.add_argument("--save", nargs="?", const=str(DEFAULT_OUTPUT), metavar="PATH", help="save the JSON report")
    parser.add_argument("--input", metavar="PATH", help="parse a different text invoice/manifest")
    parser.add_argument("--no-pause", action="store_true", help="do not wait for Enter between demo steps")
    parser.add_argument("--reset", action="store_true", help="harmless flag for CI readability")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    demo = OpsDemo(input_path=args.input, no_pause=args.no_pause)

    try:
        if args.json:
            demo.ensure_parsed()
            demo.ensure_validation()
            demo.ensure_agent()
            print(json.dumps(demo.build_report(), indent=2))
            return 0

        if args.save:
            demo.ensure_parsed()
            demo.ensure_validation()
            demo.ensure_agent()
            target = demo.export_report(args.save)
            print(c(f"Report written to {target}", Colour.GREEN))
            return 0

        if args.demo or not sys.stdin.isatty():
            demo.run_full_demo()
            return 0

        demo.interactive_menu()
        return 0
    except (FileNotFoundError, ValueError) as exc:
        print(c(f"Error: {exc}", Colour.RED), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(c("\nInterrupted.", Colour.DIM))
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
