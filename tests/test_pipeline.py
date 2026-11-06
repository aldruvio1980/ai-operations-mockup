"""Fast, dependency-free regression tests for the demo pipeline."""

from __future__ import annotations

import copy
import unittest

from modules.agent_hook import run_local_agent
from modules.parser import parse_invoice_file
from modules.router import validate_and_route


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


if __name__ == "__main__":
    unittest.main()
