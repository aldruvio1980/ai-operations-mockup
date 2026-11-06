/*
 * engine.js
 * ---------
 * Browser-side port of the deterministic parser, rules engine, and simulated
 * local AI agent. The logic mirrors modules/parser.py, modules/router.py, and
 * modules/agent_hook.py so the static demo behaves like the Python CLI.
 *
 * Everything runs locally in the browser: no network calls, no dependencies.
 */
(function (global) {
  "use strict";

  const SAMPLE_INVOICE = `From: billing@apexsteelsupply.com
To: accounts@northlineconstruct.com
Subject: INVOICE INV-88421 / PO NC-2026-0447 - Northline Tower Phase 2
Date: Tue, 03 Nov 2026 09:14:22 -0500

Hi Accounts,

Please find the scanned invoice below for the Northline Tower Phase 2 job.
The original PDF was forwarded from the site office, so the formatting is a
little rough. Deliveries were split between Yard B and the 14th Street gate.

------------------------------------------------------------
APEX STEEL & SUPPLY CO.
1420 Foundry Road, Newark, NJ 07105
billing@apexsteelsupply.com  |  (973) 555-0184
------------------------------------------------------------

INVOICE NO: INV-88421
INVOICE DATE: 11/03/2026
DUE DATE: 12/03/2026
PO NUMBER: NC-2026-0447
PROJECT: Northline Tower - Phase 2
SHIP VIA: Flatbed (3 drops)

LINE ITEMS
1. W24x76 A992 STEEL BEAM, 24 ft ....... 18 EA @ $1,425.00 = $25,650.00
2. 5000 PSI CONCRETE MIX (ready-mix) ... 42 CY @ $185.50 = $7,791.00
3. #5 REBAR, 20 ft sticks ............... 260 EA @ $18.75 = $4,875.00
4. ANSI Z89.1 HARD HATS - HI-VIS ORANGE  120 EA @ $14.25 = $1,710.00
5. Cut-resistant gloves (pair), L ....... 80 PR @ $9.40 = $752.00
6. 3M N95 RESPIRATOR MASKS ............... 500 EA @ $1.15 = $575.00

SUBTOTAL: $41,353.00
FREIGHT / DELIVERY: $1,250.00
NJ SALES TAX (6.625%): $2,739.63
TOTAL DUE: $45,342.63

Notes:
- Beam drop 2 arrived 2 days late; driver noted a forklift delay at Yard B.
- Hard hat count may be short by 12 units. Please verify against packing slip.
- Rebar was substituted with an equivalent grade; mill certs attached in PDF.
- Contact site super M. Alvarez (m.alvarez@northlineconstruct.com) for delivery questions.

Payment terms: Net 30. Remit to billing@apexsteelsupply.com`;

  const RULES = {
    requiredMetadata: ["invoice_number", "invoice_date", "po_number", "project"],
    maxAutoApproveTotal: 25000.0,
    highValueLineThreshold: 10000.0,
    bulkQuantityThreshold: 200,
    moneyTolerance: 0.02,
    allowedUnits: new Set(["EA", "CY", "LF", "SF", "SY", "TON", "PR", "BX", "PK", "GAL", "LB"]),
    priceEnvelopes: [
      { keywords: ["STEEL BEAM", "W24", "W18", "W21"], min: 900.0, max: 1800.0, unit: "EA" },
      { keywords: ["CONCRETE", "READY-MIX"], min: 140.0, max: 240.0, unit: "CY" },
      { keywords: ["REBAR", "#5", "#4", "#6"], min: 12.0, max: 30.0, unit: "EA" },
      { keywords: ["HARD HAT", "ANSI Z89.1"], min: 8.0, max: 25.0, unit: "EA" },
      { keywords: ["GLOVE"], min: 4.0, max: 20.0, unit: "PR" },
      { keywords: ["RESPIRATOR", "N95", "MASK"], min: 0.5, max: 3.0, unit: "EA" }
    ],
    exceptionKeywords: ["late", "delay", "short", "substitut", "damage", "missing", "verify"]
  };

  const MONEY = "\\d[\\d,]*(?:\\.\\d{1,2})?";
  const EMAIL_RE = /[\w.+-]+@[\w-]+\.[\w.-]+/g;
  const PHONE_RE = /(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}/;
  const LINE_ITEM_RE = new RegExp(
    "(" + MONEY + ")\\s+([A-Za-z]{1,5})\\s*@\\s*\\$?\\s*(" + MONEY + ")\\s*=\\s*\\$?\\s*(" + MONEY + ")",
    "i"
  );

  function round2(value) {
    return Math.round((Number(value) + Number.EPSILON) * 100) / 100;
  }

  function toNumber(value) {
    if (value === null || value === undefined) return null;
    const cleaned = String(value).replace(/[$,]/g, "").trim();
    if (!cleaned) return null;
    const parsed = Number(cleaned);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function firstMatch(patterns, text) {
    for (const pattern of patterns) {
      const match = text.match(new RegExp(pattern, "im"));
      if (match && match[1] !== undefined) return match[1].trim();
    }
    return null;
  }

  function normaliseDate(value) {
    if (!value) return null;
    const text = value.trim();
    let match = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (match) {
      const month = Number(match[1]);
      const day = Number(match[2]);
      if (month >= 1 && month <= 12 && day >= 1 && day <= 31) {
        return `${match[3]}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      }
    }
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
    return text;
  }

  function extractSupplier(text, emails) {
    let supplierName = null;
    const companyRe = /^([A-Z][A-Z0-9 &'.,\-]{2,}(?:CO|INC|LLC|CORP|LTD)\.?)[ \t]*$/m;
    const companyMatch = text.match(companyRe);

    if (companyMatch) {
      supplierName = companyMatch[1].trim();
    } else {
      const domainMatch = text.match(/^From:\s*[\w.+-]+@([\w-]+)\.[\w.-]+/im);
      supplierName = domainMatch ? domainMatch[1].replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : "UNKNOWN SUPPLIER";
    }

    const senderMatch = text.match(/^From:\s*.*?([\w.+-]+@[\w-]+\.[\w.-]+)/im);
    const supplierEmail = senderMatch ? senderMatch[1] : (emails[0] || null);
    const phoneMatch = text.match(PHONE_RE);

    let address = null;
    if (companyMatch) {
      const tail = text.slice(companyMatch.index + companyMatch[0].length).split(/\r?\n/);
      for (const line of tail) {
        const candidate = line.trim();
        if (candidate && /\d/.test(candidate) && candidate.length > 8) {
          address = candidate;
          break;
        }
      }
    }

    return {
      name: supplierName,
      email: supplierEmail,
      phone: phoneMatch ? phoneMatch[0].trim() : null,
      address: address
    };
  }

  function extractNotes(lines) {
    const notes = [];
    let inNotes = false;
    for (const line of lines) {
      const stripped = line.trim();
      if (/^notes?\s*:?\s*$/i.test(stripped)) {
        inNotes = true;
        continue;
      }
      if (inNotes && /^(payment terms|terms|remit|thank you|regards)\b/i.test(stripped)) break;
      if (inNotes && stripped) notes.push(stripped.replace(/^[-*\u2022]\s*/, ""));
    }
    return notes;
  }

  function extractTotals(text) {
    const lines = text.split(/\r?\n/);
    let subtotal = null;
    let freight = null;
    let taxRate = null;
    let taxAmount = null;
    let totalDue = null;
    let taxLine = null;

    for (const line of lines) {
      const trimmed = line.trim();
      if (/^SUBTOTAL\s*[:\-]?\s*\$?\s*/i.test(trimmed) && subtotal === null) {
        const match = trimmed.match(new RegExp("^SUBTOTAL\\s*[:\\-]?\\s*\\$?\\s*(" + MONEY + ")", "i"));
        if (match) subtotal = toNumber(match[1]);
      }
      if (/^(FREIGHT|DELIVERY|SHIPPING)/i.test(trimmed) && freight === null) {
        const match = trimmed.match(new RegExp("^(?:FREIGHT|DELIVERY|SHIPPING)[^:]*[:\\-]?\\s*\\$?\\s*(" + MONEY + ")", "i"));
        if (match) freight = toNumber(match[1]);
      }
      if (/^(?:[A-Z]{2}\s+)?(?:SALES\s+TAX|TAX)\b/i.test(trimmed) && taxLine === null) {
        taxLine = trimmed;
      }
      if (/^TOTAL\b/i.test(trimmed) && !/^SUBTOTAL\b/i.test(trimmed) && totalDue === null) {
        const match = trimmed.match(new RegExp("^TOTAL\\s*(?:DUE|AMOUNT)?\\s*[:\\-]?\\s*\\$?\\s*(" + MONEY + ")", "i"));
        if (match) totalDue = toNumber(match[1]);
      }
    }

    if (taxLine) {
      const rateMatch = taxLine.match(/\(\s*([\d.]+)\s*%\s*\)/);
      const amountMatch = taxLine.match(new RegExp("\\$\\s*(" + MONEY + ")"));
      if (rateMatch) taxRate = toNumber(rateMatch[1]);
      if (amountMatch) taxAmount = toNumber(amountMatch[1]);
    }

    return {
      currency: "USD",
      subtotal: subtotal,
      freight: freight,
      tax_rate_percent: taxRate,
      tax_amount: taxAmount,
      total_due: totalDue
    };
  }

  function parseLineItems(lines) {
    const items = [];
    const warnings = [];
    let start = 0;
    let end = lines.length;

    for (let index = 0; index < lines.length; index += 1) {
      if (/^\s*line\s+items?\s*:?\s*$/i.test(lines[index])) {
        start = index + 1;
        break;
      }
    }
    for (let index = start; index < lines.length; index += 1) {
      if (/^\s*(subtotal|total|notes?)\b/i.test(lines[index])) {
        end = index;
        break;
      }
    }

    for (const rawLine of lines.slice(start, end)) {
      const line = rawLine.trim();
      const numbered = line.match(/^(\d+)[.)]\s+(.+)$/);
      if (!numbered) continue;

      const body = numbered[2].trim();
      const match = LINE_ITEM_RE.exec(body);
      if (!match) {
        warnings.push(`Could not parse line-item row: ${line}`);
        continue;
      }

      const description = body
        .slice(0, match.index)
        .replace(/[\s.]+$/, "")
        .trim();
      const quantity = toNumber(match[1]);
      const unit = match[2].toUpperCase();
      const unitPrice = toNumber(match[3]);
      const declaredTotal = toNumber(match[4]);
      const computedTotal = quantity !== null && unitPrice !== null ? round2(quantity * unitPrice) : null;

      if (!description) warnings.push(`Line item is missing a description: ${line}`);
      if (
        computedTotal !== null &&
        declaredTotal !== null &&
        Math.abs(computedTotal - declaredTotal) > RULES.moneyTolerance
      ) {
        warnings.push(
          `Line-item arithmetic mismatch for ${description}: computed ${computedTotal.toFixed(2)}, document says ${declaredTotal.toFixed(2)}.`
        );
      }

      items.push({
        line_number: Number(numbered[1]),
        description: description,
        quantity: quantity,
        unit: unit,
        unit_price: unitPrice,
        declared_line_total: declaredTotal,
        computed_line_total: computedTotal
      });
    }

    return { items, warnings };
  }

  function parseInvoice(rawText, source) {
    if (typeof rawText !== "string" || !rawText.trim()) {
      throw new Error("Input document is empty; nothing to parse.");
    }

    const lines = rawText.split(/\r?\n/);
    const emails = Array.from(new Set(rawText.match(EMAIL_RE) || []));
    const metadata = {
      invoice_number: firstMatch(["^INVOICE\\s*(?:NO|NUMBER|#)\\.?\\s*[:\\-]?\\s*([A-Z0-9][A-Z0-9/\\-]*)"], rawText),
      invoice_date: normaliseDate(firstMatch(["^INVOICE\\s*DATE\\s*[:\\-]?\\s*([\\d/.\\-]+)"], rawText)),
      due_date: normaliseDate(firstMatch(["^DUE\\s*DATE\\s*[:\\-]?\\s*([\\d/.\\-]+)"], rawText)),
      po_number: firstMatch(["^P\\.?O\\.?\\s*(?:NUMBER|NO|#)?\\.?\\s*[:\\-]?\\s*([A-Z0-9][A-Z0-9/\\-]*)"], rawText),
      project: firstMatch(["^PROJECT\\s*[:\\-]\\s*(.+)$"], rawText),
      ship_via: firstMatch(["^SHIP\\s*VIA\\s*[:\\-]\\s*(.+)$"], rawText),
      payment_terms: firstMatch(["^(?:PAYMENT\\s+TERMS|TERMS)\\s*[:\\-]\\s*(.+)$"], rawText)
    };

    const lineResult = parseLineItems(lines);
    if (!lineResult.items.length) {
      lineResult.warnings.push(
        "No line items were detected. Check the document layout or extend the parser patterns."
      );
    }

    return {
      source: source || "mock_invoice.txt",
      raw_text: rawText,
      supplier: extractSupplier(rawText, emails),
      metadata: metadata,
      line_items: lineResult.items,
      totals_declared: extractTotals(rawText),
      notes: extractNotes(lines),
      emails: emails,
      parse_warnings: lineResult.warnings
    };
  }

  function finding(ruleId, severity, message, field, details) {
    return {
      rule_id: ruleId,
      severity: severity,
      field: field || null,
      message: message,
      details: details || {}
    };
  }

  function validateRequiredFields(parsed) {
    const findings = [];
    const metadata = parsed.metadata || {};
    const supplier = parsed.supplier || {};

    for (const field of RULES.requiredMetadata) {
      if (!metadata[field]) {
        findings.push(
          finding("R1_REQUIRED_FIELD", "critical", `Required field '${field}' is missing; invoice cannot be posted.`, field)
        );
      }
    }
    if (!supplier.name || supplier.name === "UNKNOWN SUPPLIER") {
      findings.push(finding("R1_REQUIRED_FIELD", "critical", "Supplier name could not be identified.", "supplier.name"));
    }
    if (!parsed.line_items || !parsed.line_items.length) {
      findings.push(finding("R1_REQUIRED_FIELD", "critical", "No line items were extracted; totals cannot be trusted.", "line_items"));
    }
    return findings;
  }

  function validateLineItems(parsed) {
    const findings = [];

    for (const item of parsed.line_items || []) {
      const label = `line ${item.line_number} (${item.description || "unknown"})`;
      const quantity = item.quantity;
      const unitPrice = item.unit_price;
      const declared = item.declared_line_total;
      const computed = item.computed_line_total;

      if (!item.description) {
        findings.push(finding("R2_LINE_DATA", "critical", `${label} has no description.`, "description"));
      }
      if (quantity === null || quantity <= 0) {
        findings.push(finding("R2_LINE_DATA", "critical", `${label} has an invalid quantity.`, "quantity"));
        continue;
      }
      if (unitPrice === null || unitPrice < 0) {
        findings.push(finding("R2_LINE_DATA", "critical", `${label} has an invalid unit price.`, "unit_price"));
        continue;
      }
      if (!RULES.allowedUnits.has(item.unit)) {
        findings.push(
          finding("R3_UNKNOWN_UNIT", "warning", `${label} uses unrecognised unit '${item.unit}'; verify UOM.`, "unit")
        );
      }
      if (declared !== null && computed !== null && Math.abs(declared - computed) > RULES.moneyTolerance) {
        findings.push(
          finding("R4_LINE_ARITHMETIC", "warning", `${label} total does not equal quantity x unit price.`, "line_total", {
            declared: declared,
            computed: computed
          })
        );
      }

      const descriptionUpper = String(item.description || "").toUpperCase();
      for (const envelope of RULES.priceEnvelopes) {
        if (envelope.keywords.some((keyword) => descriptionUpper.includes(keyword))) {
          if (item.unit !== envelope.unit) {
            findings.push(
              finding("R5_UNIT_MISMATCH", "warning", `${label} has unit ${item.unit}; expected ${envelope.unit}.`, "unit")
            );
          } else if (unitPrice < envelope.min || unitPrice > envelope.max) {
            findings.push(
              finding(
                "R5_PRICE_ENVELOPE",
                "warning",
                `${label} unit price $${unitPrice.toFixed(2)} is outside the expected $${envelope.min.toFixed(2)}-$${envelope.max.toFixed(2)} band.`,
                "unit_price",
                { unit_price: unitPrice, envelope: envelope }
              )
            );
          }
          break;
        }
      }

      if (quantity >= RULES.bulkQuantityThreshold) {
        findings.push(
          finding(
            "R6_BULK_QUANTITY",
            "info",
            `${label} is a bulk quantity (${quantity} ${item.unit}); confirm delivery capacity and staged receiving.`,
            "quantity",
            { quantity: quantity, unit: item.unit }
          )
        );
      }
      if (computed !== null && computed >= RULES.highValueLineThreshold) {
        findings.push(
          finding(
            "R7_HIGH_VALUE_LINE",
            "warning",
            `${label} exceeds the $${RULES.highValueLineThreshold.toFixed(2)} line-value review threshold.`,
            "line_total",
            { line_total: computed }
          )
        );
      }
    }
    return findings;
  }

  function calculateTotals(parsed) {
    const declared = parsed.totals_declared || {};
    let computedSubtotal = 0;
    let declaredLineSum = 0;

    for (const item of parsed.line_items || []) {
      const quantity = item.quantity || 0;
      const price = item.unit_price || 0;
      computedSubtotal += quantity * price;
      declaredLineSum += item.declared_line_total || 0;
    }

    computedSubtotal = round2(computedSubtotal);
    const declaredSubtotal = declared.subtotal;
    const freight = declared.freight || 0;
    const rate = declared.tax_rate_percent;
    const declaredTax = declared.tax_amount;
    const declaredTotal = declared.total_due;

    const computedTax = rate !== null && rate !== undefined ? round2((computedSubtotal * rate) / 100) : declaredTax;
    const computedTotal = round2(computedSubtotal + freight + (computedTax || 0));

    return {
      currency: declared.currency || "USD",
      computed_subtotal: computedSubtotal,
      declared_subtotal: declaredSubtotal,
      subtotal_variance: declaredSubtotal !== null && declaredSubtotal !== undefined ? round2(computedSubtotal - declaredSubtotal) : null,
      declared_line_sum: round2(declaredLineSum),
      freight: round2(freight),
      tax_rate_percent: rate !== null && rate !== undefined ? Number(rate) : null,
      computed_tax: computedTax,
      declared_tax: declaredTax,
      tax_variance: computedTax !== null && declaredTax !== null && declaredTax !== undefined ? round2(computedTax - declaredTax) : null,
      computed_total_due: computedTotal,
      declared_total_due: declaredTotal,
      total_variance: declaredTotal !== null && declaredTotal !== undefined ? round2(computedTotal - declaredTotal) : null
    };
  }

  function validateTotals(totals) {
    const findings = [];
    const tolerance = RULES.moneyTolerance;

    function compare(ruleId, field, label, computed, declared) {
      if (computed === null || computed === undefined || declared === null || declared === undefined) {
        findings.push(finding(ruleId, "warning", `${label} is missing from the document.`, field));
        return;
      }
      const variance = round2(computed - declared);
      if (Math.abs(variance) > tolerance) {
        findings.push(
          finding(ruleId, "warning", `${label} mismatch: computed $${computed.toFixed(2)}, document $${declared.toFixed(2)}.`, field, {
            computed: computed,
            declared: declared,
            variance: variance
          })
        );
      }
    }

    compare("R8_SUBTOTAL_RECONCILIATION", "subtotal", "Subtotal", totals.computed_subtotal, totals.declared_subtotal);
    compare("R9_TAX_RECONCILIATION", "tax_amount", "Sales tax", totals.computed_tax, totals.declared_tax);
    compare("R10_TOTAL_RECONCILIATION", "total_due", "Grand total", totals.computed_total_due, totals.declared_total_due);
    return findings;
  }

  function validateNotes(parsed) {
    const findings = [];
    for (const note of parsed.notes || []) {
      const lowered = note.toLowerCase();
      const matched = RULES.exceptionKeywords.filter((keyword) => lowered.includes(keyword));
      if (matched.length) {
        findings.push(
          finding("R11_DOCUMENTED_EXCEPTION", "warning", `Operational exception noted: ${note}`, "notes", {
            keywords: matched,
            note: note
          })
        );
      }
    }
    return findings;
  }

  function buildRouting(findings, totals) {
    const criticalCount = findings.filter((item) => item.severity === "critical").length;
    const warningCount = findings.filter((item) => item.severity === "warning").length;
    const infoCount = findings.filter((item) => item.severity === "info").length;
    const riskScore = Math.min(100, criticalCount * 40 + warningCount * 15 + infoCount * 3);
    const total = totals.computed_total_due || 0;

    let status;
    let queue;
    let approvals;
    let reason;
    if (criticalCount) {
      status = "ESCALATE";
      queue = "procurement-escalation";
      approvals = ["Procurement Manager", "Finance Controller"];
      reason = "Critical data gaps prevent safe straight-through processing.";
    } else if (warningCount || total > RULES.maxAutoApproveTotal) {
      status = "REVIEW";
      queue = "procurement-review";
      approvals = ["Procurement Lead"];
      if (total > RULES.maxAutoApproveTotal) approvals.push("Finance Controller");
      reason = "Invoice requires human review due to exceptions, value thresholds, or reconciliation differences.";
    } else {
      status = "AUTO_APPROVE";
      queue = "auto-post-eligible";
      approvals = [];
      reason = "All required fields and deterministic controls passed.";
    }

    return {
      status: status,
      queue: queue,
      reason: reason,
      risk_score: riskScore,
      severity_counts: { critical: criticalCount, warning: warningCount, info: infoCount },
      value_band: total <= RULES.maxAutoApproveTotal ? "under_25k" : "over_25k",
      approvals_required: approvals,
      thresholds: {
        max_auto_approve_total: RULES.maxAutoApproveTotal,
        high_value_line_threshold: RULES.highValueLineThreshold,
        bulk_quantity_threshold: RULES.bulkQuantityThreshold
      }
    };
  }

  function buildActions(findings, routing) {
    const actions = [];
    const seen = new Set();

    function add(owner, action) {
      const key = `${owner}|${action}`;
      if (!seen.has(key)) {
        seen.add(key);
        actions.push({ owner: owner, action: action });
      }
    }

    for (const item of findings) {
      if (item.rule_id === "R1_REQUIRED_FIELD") {
        add("Accounts Payable", "Request a corrected invoice from the supplier before posting.");
      } else if (item.rule_id === "R4_LINE_ARITHMETIC") {
        add("AP Analyst", "Reconcile the line-item total with the supplier's source PDF.");
      } else if (item.rule_id === "R5_PRICE_ENVELOPE") {
        add("Procurement", "Confirm the quoted unit price against the active PO or contract.");
      } else if (item.rule_id === "R7_HIGH_VALUE_LINE") {
        add("Procurement Lead", "Approve the high-value material line before payment release.");
      } else if (item.rule_id === "R8_SUBTOTAL_RECONCILIATION") {
        add("AP Analyst", "Recompute subtotal from the packing slip and invoice.");
      } else if (item.rule_id === "R9_TAX_RECONCILIATION") {
        add("Finance", "Verify the tax jurisdiction and rate before posting.");
      } else if (item.rule_id === "R10_TOTAL_RECONCILIATION") {
        add("Finance", "Place a soft hold until the grand total is reconciled.");
      } else if (item.rule_id === "R11_DOCUMENTED_EXCEPTION") {
        const note = (item.details.note || "").toLowerCase();
        if (note.includes("late") || note.includes("delay")) {
          add("Field Operations", "Log the delivery delay and update the look-ahead schedule.");
        }
        if (note.includes("short") || note.includes("missing")) {
          add("Site Superintendent", "Verify received quantities against the packing slip.");
        }
        if (note.includes("substitut")) {
          add("Quality Control", "Review substitution approval and attached mill certificates.");
        }
      } else if (item.rule_id === "R6_BULK_QUANTITY") {
        add("Logistics", "Confirm yard capacity and staged delivery plan for bulk materials.");
      }
    }

    if (routing.status === "ESCALATE") {
      add("Procurement Manager", "Resolve critical data gaps before the invoice enters the ERP.");
    }
    if (routing.status === "REVIEW") {
      add("Procurement Lead", `Review and sign off in the '${routing.queue}' queue.`);
    }
    if (!actions.length && routing.status === "AUTO_APPROVE") {
      add("Automation", "Post invoice via the straight-through-processing workflow.");
    }
    return actions;
  }

  function validateAndRoute(parsed) {
    if (!parsed || !Array.isArray(parsed.line_items)) {
      throw new Error("validateAndRoute expects a parsed invoice object.");
    }

    const findings = [];
    findings.push(...validateRequiredFields(parsed));
    findings.push(...validateLineItems(parsed));
    const totals = calculateTotals(parsed);
    findings.push(...validateTotals(totals));
    findings.push(...validateNotes(parsed));
    const routing = buildRouting(findings, totals);
    const actions = buildActions(findings, routing);

    return {
      rules_version: "1.0.0-web",
      status: routing.status,
      queue: routing.queue,
      reason: routing.reason,
      risk_score: routing.risk_score,
      severity_counts: routing.severity_counts,
      value_band: routing.value_band,
      approvals_required: routing.approvals_required,
      thresholds: routing.thresholds,
      totals: totals,
      findings: findings,
      recommended_actions: actions
    };
  }

  /* ------------------------------------------------------------------ */
  /* Simulated local AI agent                                            */
  /* ------------------------------------------------------------------ */

  const AGENT_NAME = "local-ops-copilot";
  const AGENT_VERSION = "1.0.0-web-simulation";
  const CATEGORY_KEYWORDS = {
    "structural steel": ["STEEL BEAM", "BEAM", "W24", "W18", "W21"],
    concrete: ["CONCRETE", "READY-MIX"],
    rebar: ["REBAR", "#5 REBAR", "#4 REBAR", "#6 REBAR"],
    "safety equipment": ["HARD HAT", "ANSI Z89.1", "GLOVE", "RESPIRATOR", "N95", "MASK"]
  };

  function money(value) {
    if (value === null || value === undefined) return "n/a";
    const sign = value < 0 ? "-" : "";
    return `${sign}$${Math.abs(value).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })}`;
  }

  function formatQty(value) {
    return Number.isInteger(value) ? String(value) : String(value);
  }

  function classifyItem(description) {
    const upper = String(description).toUpperCase();
    for (const [category, keywords] of Object.entries(CATEGORY_KEYWORDS)) {
      if (keywords.some((keyword) => upper.includes(keyword))) return category;
    }
    return "other materials";
  }

  function lineTotal(item) {
    if (item.computed_line_total !== null && item.computed_line_total !== undefined) return Number(item.computed_line_total);
    if (item.declared_line_total !== null && item.declared_line_total !== undefined) return Number(item.declared_line_total);
    return (item.quantity || 0) * (item.unit_price || 0);
  }

  function buildOperationalProfile(parsed) {
    const categorySpend = {};
    const bulkItems = [];
    const highValueItems = [];

    for (const item of parsed.line_items || []) {
      const category = classifyItem(item.description || "");
      const total = lineTotal(item);
      categorySpend[category] = round2((categorySpend[category] || 0) + total);
      if ((item.quantity || 0) >= 200) {
        bulkItems.push({ description: item.description, quantity: item.quantity, unit: item.unit });
      }
      if (total >= 10000) highValueItems.push({ description: item.description, line_total: total });
    }

    return { category_spend: categorySpend, bulk_items: bulkItems, high_value_items: highValueItems };
  }

  function buildInsights(parsed, validation, profile) {
    const insights = [];
    const notes = parsed.notes || [];
    const invoice = (parsed.metadata && parsed.metadata.invoice_number) || "the invoice";
    const supplier = (parsed.supplier && parsed.supplier.name) || "the supplier";

    function add(id, category, severity, title, detail, impact, evidence) {
      insights.push({ id, category, severity, title, detail, impact, evidence });
    }

    for (const note of notes) {
      const lowered = note.toLowerCase();
      if (lowered.includes("late") || lowered.includes("delay")) {
        add(
          "AI-01",
          "schedule",
          "high",
          "Delivery delay detected on structural material",
          `A field note on ${invoice} records a late delivery and a forklift constraint at the receiving yard.`,
          "Potential impact to the erection sequence. Confirm the revised look-ahead schedule before releasing payment.",
          note
        );
      }
      if (lowered.includes("short") || lowered.includes("missing") || lowered.includes("verify")) {
        add(
          "AI-02",
          "receiving",
          "high",
          "Possible quantity shortage requires physical verification",
          "The document flags a possible short shipment, so invoiced quantities may not match what the site actually received.",
          "Paying in full before verification creates an overpayment and safety-stock risk. Reconcile against the packing slip today.",
          note
        );
      }
      if (lowered.includes("substitut")) {
        add(
          "AI-03",
          "quality",
          "medium",
          "Material substitution needs quality sign-off",
          `${supplier} substituted an equivalent grade and references attached mill certificates.`,
          "Confirm the substitution was approved by engineering and that the mill certs are in the quality package before closeout.",
          note
        );
      }
    }

    if (profile.high_value_items.length) {
      const top = profile.high_value_items.reduce((best, item) => (item.line_total > best.line_total ? item : best));
      const total = (validation.totals && validation.totals.computed_total_due) || 0;
      const share = total ? (top.line_total / total) * 100 : 0;
      add(
        "AI-04",
        "financial",
        "medium",
        "Concentrated spend on one material line",
        `${top.description} accounts for ${money(top.line_total)}, or ${share.toFixed(1)}% of the invoice value.`,
        "Requires procurement sign-off and confirms the invoice is correctly routed to the review queue rather than auto-posted.",
        `Line total ${money(top.line_total)}`
      );
    }

    if (profile.bulk_items.length) {
      const labels = profile.bulk_items
        .map((item) => `${formatQty(item.quantity)} ${item.unit} ${item.description}`)
        .join(", ");
      add(
        "AI-05",
        "logistics",
        "low",
        "Bulk materials require staged receiving",
        `Bulk lines detected: ${labels}.`,
        "Confirm yard capacity and split deliveries so crews are not waiting on unloading equipment during peak hours.",
        "Quantity exceeds the 200-unit bulk threshold."
      );
    }

    const totals = validation.totals || {};
    for (const [field, label] of [
      ["subtotal_variance", "subtotal"],
      ["total_variance", "grand total"]
    ]) {
      const variance = totals[field];
      if (variance !== null && variance !== undefined && Math.abs(variance) > 0.02) {
        add(
          "AI-06",
          "financial",
          "high",
          `Reconciliation variance in ${label}`,
          `Computed ${label} differs from the document by ${money(variance)}.`,
          "Payment should be soft-held until finance reconciles the source PDF.",
          `Variance ${money(variance)}`
        );
      }
    }

    if (!insights.length) {
      add(
        "AI-00",
        "controls",
        "info",
        "No operational exceptions detected",
        "The document passed deterministic controls with no contextual delivery, safety, or reconciliation exceptions.",
        "Eligible for normal straight-through processing.",
        "All rule checks passed."
      );
    }
    return insights;
  }

  function buildAgentActions(insights) {
    const actions = [];
    const seen = new Set();

    function add(priority, owner, action, due, source) {
      const key = `${owner}|${action}`;
      if (!seen.has(key)) {
        seen.add(key);
        actions.push({ priority, owner, action, due, source });
      }
    }

    for (const insight of insights) {
      if (insight.category === "receiving") {
        add("P0", "Site Superintendent", "Count hard hats, gloves, and masks against the packing slip before the next shift.", "today", insight.id);
        add("P0", "Accounts Payable", "Do not release final payment until the receiving count is signed off.", "before payment release", insight.id);
      } else if (insight.category === "schedule") {
        add("P0", "Field Operations", "Log the beam-delivery delay and confirm the revised erection sequence.", "within 24 hours", insight.id);
      } else if (insight.category === "quality") {
        add("P1", "Quality Control", "Verify the rebar substitution approval and attach mill certificates to the QC record.", "within 48 hours", insight.id);
      } else if (insight.category === "financial") {
        add("P1", "Procurement Lead", "Approve the high-value steel line and document the commercial rationale.", "before payment release", insight.id);
      } else if (insight.category === "logistics") {
        add("P2", "Logistics Coordinator", "Confirm yard capacity and the staged delivery plan for bulk materials.", "this week", insight.id);
      }
    }

    if (!actions.length) {
      add("P3", "Automation", "Continue straight-through processing and archive the audit record.", "automatic", "AI-00");
    }
    return actions;
  }

  function buildActionLog(parsed, validation, insights) {
    const invoice = (parsed.metadata && parsed.metadata.invoice_number) || "UNKNOWN";
    const supplier = (parsed.supplier && parsed.supplier.name) || "UNKNOWN";
    const status = validation.status || "UNKNOWN";
    const queue = validation.queue || "UNKNOWN";
    const risk = validation.risk_score || 0;
    const itemCount = (parsed.line_items || []).length;
    const warningCount = (parsed.parse_warnings || []).length;
    const base = Date.now();

    const events = [
      {
        event: "DOCUMENT_RECEIVED",
        severity: "info",
        detail: `${invoice} received from ${supplier}; source=${parsed.source || "unknown"}.`
      },
      {
        event: "EXTRACTION_COMPLETE",
        severity: "info",
        detail: `${itemCount} line items parsed with ${warningCount} parser warning(s).`
      },
      {
        event: "DETERMINISTIC_VALIDATION",
        severity: status !== "AUTO_APPROVE" ? "warning" : "info",
        detail: `Rules engine returned ${status} (risk ${risk}/100).`
      }
    ];

    for (const insight of insights) {
      if (insight.severity === "high" || insight.severity === "medium") {
        events.push({
          event: "CONTEXT_FLAG",
          severity: insight.severity,
          detail: `${insight.id} ${insight.title}: ${insight.impact}`
        });
      }
    }

    events.push({
      event: "ROUTING_DECISION",
      severity: status !== "AUTO_APPROVE" ? "warning" : "info",
      detail: `Queued in '${queue}'. ${validation.reason || ""}`
    });

    return events.map((event, index) => ({
      ...event,
      sequence: index + 1,
      timestamp: new Date(base + 120 * (index + 1)).toISOString()
    }));
  }

  function buildSupplierFollowup(parsed, insights) {
    const categories = new Set(insights.map((item) => item.category));
    if (!["receiving", "schedule", "quality"].some((category) => categories.has(category))) return null;

    const metadata = parsed.metadata || {};
    const supplier = parsed.supplier || {};
    const invoice = metadata.invoice_number || "the invoice";
    const po = metadata.po_number || "the referenced PO";
    const project = metadata.project || "the project";
    const asks = [];

    if (categories.has("receiving")) {
      asks.push("confirm the delivered hard-hat quantity against the packing slip and advise whether a 12-unit shortage will be credited or replaced");
    }
    if (categories.has("schedule")) {
      asks.push("confirm the carrier's explanation for the delayed beam drop and the revised delivery ticket");
    }
    if (categories.has("quality")) {
      asks.push("provide the approved substitution record and mill certificates for the rebar");
    }

    const body =
      `Hello ${supplier.name || "team"},\n\n` +
      `We are reconciling invoice ${invoice} against ${po} for ${project}. ` +
      "Before we release the balance, please help us close the following items:\n\n" +
      asks.map((ask, index) => `${index + 1}. ${ask.charAt(0).toUpperCase()}${ask.slice(1)}`).join("\n") +
      "\n\nPlease reply with the supporting documents or a corrected invoice.\n\nThank you,\nProcurement Operations";

    return {
      to: supplier.email,
      subject: `${invoice} - delivery exception follow-up (${po})`,
      body: body,
      status: "draft_only"
    };
  }

  function synthesise(parsed, validation) {
    const totals = validation.totals || {};
    const metadata = parsed.metadata || {};
    const supplier = parsed.supplier || {};
    const profile = buildOperationalProfile(parsed);
    const insights = buildInsights(parsed, validation, profile);
    const actions = buildAgentActions(insights);
    const actionLog = buildActionLog(parsed, validation, insights);
    const followup = buildSupplierFollowup(parsed, insights);

    const invoice = metadata.invoice_number || "UNKNOWN";
    const project = metadata.project || "unassigned project";
    const po = metadata.po_number || "no PO";
    const total = totals.computed_total_due;
    const status = validation.status || "UNKNOWN";
    const riskScore = validation.risk_score || 0;
    const queue = validation.queue || "unknown";
    const highInsights = insights.filter((item) => item.severity === "high");
    const contextClause = highInsights.length
      ? " The highest-impact context is " +
        highInsights.slice(0, 2).map((item) => item.title.toLowerCase()).join(" and ") +
        "."
      : " No high-severity field exceptions were detected.";

    const executiveSummary =
      `${supplier.name || "The supplier"} submitted ${invoice} against ${po} for ${project}. ` +
      `The deterministic truth is ${money(total)} across ${(parsed.line_items || []).length} line items. ` +
      `Controls routed the invoice to ${status} (risk ${riskScore}/100) in the '${queue}' queue.${contextClause}`;

    let confidence = 0.95;
    confidence -= 0.1 * (parsed.parse_warnings || []).length;
    confidence -= validation.severity_counts && validation.severity_counts.critical ? 0.25 : 0;
    for (const key of ["subtotal_variance", "tax_variance", "total_variance"]) {
      if (totals[key] !== null && totals[key] !== undefined && Math.abs(totals[key]) > 0.02) confidence -= 0.05;
    }
    confidence = Math.round(Math.max(0.35, Math.min(0.99, confidence)) * 100) / 100;

    let riskLevel;
    if (status === "ESCALATE") riskLevel = "critical";
    else if (riskScore >= 50) riskLevel = "elevated";
    else if (status === "REVIEW") riskLevel = "moderate";
    else riskLevel = "low";

    const briefParts = [];
    for (const insight of insights) {
      if (insight.category === "receiving") briefParts.push("verify safety-gear counts against the packing slip before the next shift");
      else if (insight.category === "schedule") briefParts.push("log the beam-delivery delay and re-check the erection sequence");
      else if (insight.category === "quality") briefParts.push("collect the rebar substitution approval and mill certificates");
    }
    const fieldBrief = briefParts.length
      ? `Site brief: ${briefParts.join("; ")}.`
      : "Site brief: no field-side exceptions; continue normal receiving.";

    return {
      agent: {
        name: AGENT_NAME,
        version: AGENT_VERSION,
        mode: "offline-simulation",
        llm_calls: 0,
        network_calls: 0,
        note: "Transparent local heuristics stand in for a local LLM. No invoice data leaves this browser; swap synthesise() for a local model adapter while preserving this output contract."
      },
      summary: {
        invoice_number: invoice,
        supplier: supplier.name,
        po_number: po,
        project: project,
        computed_total_due: total,
        status: status,
        queue: queue,
        risk_score: riskScore,
        line_item_count: (parsed.line_items || []).length,
        exception_count: insights.filter((item) => item.severity === "high" || item.severity === "medium").length
      },
      executive_summary: executiveSummary,
      confidence: confidence,
      risk_level: riskLevel,
      operational_profile: profile,
      insights: insights,
      recommended_actions: actions,
      action_log: actionLog,
      field_brief: fieldBrief,
      supplier_followup: followup,
      guardrails: [
        "Deterministic totals are never overwritten by the agent.",
        "All recommendations require named human ownership.",
        "The agent is simulation-only in this demo and makes zero network calls."
      ]
    };
  }

  function runLocalAgent(parsed, validation) {
    if (!parsed || !validation) throw new Error("runLocalAgent expects parsed and validation objects.");
    return synthesise(parsed, validation);
  }

  const api = {
    SAMPLE_INVOICE: SAMPLE_INVOICE,
    RULES: RULES,
    parseInvoice: parseInvoice,
    validateAndRoute: validateAndRoute,
    runLocalAgent: runLocalAgent
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  global.OpsEngine = api;
})(typeof window !== "undefined" ? window : globalThis);
