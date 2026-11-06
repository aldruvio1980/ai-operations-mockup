"""Fast, dependency-free regression tests for the demo pipeline."""

from __future__ import annotations

import copy
import unittest

from modules.agent_hook import run_local_agent
from modules.parser import parse_invoice, parse_invoice_file
from modules.router import validate_and_route

MARKDOWN_INVOICE = """# INVOICE

**Invoice Number:** INV-2026-001
**Invoice Date:** November 6, 2026
**Due Date:** December 6, 2026

### Billed By (Vendor):
**Acme Solutions LLC**
123 Business Rd, Suite 100
New York, NY 10001
Email: billing@acmesolutions.com
Phone: (555) 019-2831

### Billed To (Client):
**Cambridge West NYC**
456 Midtown Ave, Floor 12
New York, NY 10018

### Description of Services

| Item | Description | Quantity | Rate | Amount |
| :--- | :--- | :---: | :---: | :---: |
| 1 | Operations & Workflow Automation Consulting | 10 hrs | $150.00 | $1,500.00 |
| 2 | Data Pipeline Integration & Testing | 1 | $750.00 | $750.00 |
| 3 | System Configuration & Setup | 1 | $500.00 | $500.00 |

### Summary

* **Subtotal:** $2,750.00
* **Tax (8.875%):** $244.06
* **Total Due:** **$2,994.06**

### Payment Terms & Notes
* Payment is due within 30 days of invoice date.
"""


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parsed = parse_invoice_file()
        cls.validation = validate_and_route(cls.parsed)
        cls.agent = run_local_agent(cls.parsed, cls.validation)

    def test_supplier_and_metadata_extracted(self) -> None:
        self.assertEqual(self.parsed["supplier"]["name"], "APEX STEEL & SUPPLY CO.")
        self.assertEqual(self.parsed["metadata"]["invoice_number"], "INV-88421")
        self.assertEqual(self.parsed["metadata"]["po_number"], "NC-2026-0447")
        self.assertEqual(self.parsed["metadata"]["invoice_date"], "2026-11-03")

    def test_line_items_are_parsed_cleanly(self) -> None:
        items = self.parsed["line_items"]
        self.assertEqual(len(items), 6)
        self.assertEqual(items[0]["description"], "W24x76 A992 STEEL BEAM, 24 ft")
        self.assertEqual(items[0]["quantity"], 18)
        self.assertEqual(items[0]["unit"], "EA")
        self.assertEqual(items[3]["unit"], "EA")
        self.assertFalse(self.parsed["parse_warnings"])

    def test_deterministic_totals(self) -> None:
        totals = self.validation["totals"]
        self.assertEqual(totals["computed_subtotal"], 41353.00)
        self.assertEqual(totals["computed_tax"], 2739.64)
        self.assertEqual(totals["computed_total_due"], 45342.64)
        self.assertLessEqual(abs(totals["total_variance"]), 0.02)

    def test_sample_routes_to_review(self) -> None:
        self.assertEqual(self.validation["status"], "REVIEW")
        self.assertEqual(self.validation["queue"], "procurement-review")
        self.assertGreater(self.validation["risk_score"], 0)
        self.assertIn("Procurement Lead", self.validation["approvals_required"])

    def test_agent_is_local_and_contextual(self) -> None:
        self.assertEqual(self.agent["agent"]["network_calls"], 0)
        self.assertEqual(self.agent["agent"]["llm_calls"], 0)
        self.assertEqual(self.agent["risk_level"], "elevated")
        categories = {insight["category"] for insight in self.agent["insights"]}
        self.assertIn("schedule", categories)
        self.assertIn("receiving", categories)
        self.assertTrue(any(action["priority"] == "P0" for action in self.agent["recommended_actions"]))
        self.assertIn("supplier_followup", self.agent)

    def test_missing_po_escalates(self) -> None:
        broken = copy.deepcopy(self.parsed)
        broken["metadata"]["po_number"] = None
        result = validate_and_route(broken)
        self.assertEqual(result["status"], "ESCALATE")
        self.assertTrue(
            any(finding["rule_id"] == "R1_REQUIRED_FIELD" for finding in result["findings"])
        )

    def test_line_arithmetic_mismatch_is_flagged(self) -> None:
        broken = copy.deepcopy(self.parsed)
        broken["line_items"][0]["declared_line_total"] = 1.00
        result = validate_and_route(broken)
        self.assertTrue(
            any(finding["rule_id"] == "R4_LINE_ARITHMETIC" for finding in result["findings"])
        )

    def test_markdown_table_invoice_is_supported(self) -> None:
        parsed = parse_invoice(MARKDOWN_INVOICE, "markdown_invoice.md")
        self.assertEqual(parsed["supplier"]["name"], "Acme Solutions LLC")
        self.assertEqual(parsed["supplier"]["email"], "billing@acmesolutions.com")
        self.assertEqual(parsed["metadata"]["invoice_number"], "INV-2026-001")
        self.assertEqual(parsed["metadata"]["invoice_date"], "2026-11-06")
        self.assertEqual(parsed["metadata"]["due_date"], "2026-12-06")
        self.assertEqual(parsed["metadata"]["payment_terms"], "Payment is due within 30 days of invoice date.")
        self.assertEqual(len(parsed["line_items"]), 3)
        self.assertEqual(parsed["line_items"][0]["unit"], "HRS")
        self.assertEqual(parsed["line_items"][0]["quantity"], 10)
        self.assertEqual(parsed["line_items"][0]["unit_price"], 150.00)
        self.assertEqual(parsed["line_items"][0]["computed_line_total"], 1500.00)
        self.assertEqual(parsed["totals_declared"]["subtotal"], 2750.00)
        self.assertEqual(parsed["totals_declared"]["tax_rate_percent"], 8.875)
        self.assertEqual(parsed["totals_declared"]["tax_amount"], 244.06)
        self.assertEqual(parsed["totals_declared"]["total_due"], 2994.06)
        self.assertFalse(parsed["parse_warnings"])

        validation = validate_and_route(parsed)
        self.assertEqual(validation["totals"]["computed_subtotal"], 2750.00)
        self.assertEqual(validation["totals"]["computed_total_due"], 2994.06)
        self.assertEqual(validation["status"], "ESCALATE")


if __name__ == "__main__":
    unittest.main()
