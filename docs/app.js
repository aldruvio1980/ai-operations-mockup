/*
 * app.js
 * ------
 * UI controller for the static browser demo. It renders the same state that
 * the Python CLI produces: parsed entities, deterministic validation, and the
 * simulated local-agent output.
 */
(function () {
  "use strict";

  const Engine = window.OpsEngine;
  if (!Engine) {
    document.body.innerHTML = "<p style='padding:2rem;color:#ff6464'>Engine failed to load.</p>";
    return;
  }

  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  const state = {
    rawText: Engine.SAMPLE_INVOICE,
    source: "sample_invoice.txt",
    parsed: null,
    validation: null,
    agent: null,
    report: null,
    demoToken: 0
  };

  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const scrollBehavior = reduceMotion ? "auto" : "smooth";
  let toastTimer = null;

  const els = {
    heroStatus: $("#hero-status"),
    heroTotal: $("#hero-total"),
    heroSub: $("#hero-sub"),
    heroRisk: $("#hero-risk"),
    heroRiskBar: $("#hero-risk-bar"),
    kpiInvoice: $("#kpi-invoice"),
    kpiPo: $("#kpi-po"),
    kpiSupplier: $("#kpi-supplier"),
    kpiExceptions: $("#kpi-exceptions"),
    sourceMeta: $("#source-meta"),
    rawPreview: $("#raw-preview"),
    parseWarnings: $("#parse-warnings"),
    dropzone: $("#dropzone"),
    fileInput: $("#file-input"),
    identityGrid: $("#identity-grid"),
    truthStatus: $("#truth-status"),
    truthStats: $("#truth-stats"),
    totalsList: $("#totals-list"),
    approvalRow: $("#approval-row"),
    itemCount: $("#item-count"),
    lineItemsBody: $("#line-items-body"),
    lineItemsFoot: $("#line-items-foot"),
    rulesVersion: $("#rules-version"),
    routingReason: $("#routing-reason"),
    validationSummary: $("#validation-summary"),
    findingsList: $("#findings-list"),
    aiSummary: $("#ai-summary"),
    agentMeta: $("#agent-meta"),
    insightsList: $("#insights-list"),
    actionsList: $("#actions-list"),
    fieldBrief: $("#field-brief"),
    followupDetails: $("#followup-details"),
    followupContent: $("#followup-content"),
    actionLog: $("#action-log"),
    toast: $("#toast"),
    runDemo: $("#run-demo"),
    resetSample: $("#reset-sample"),
    downloadJson: $("#download-json")
  };

  function esc(value) {
    return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, (character) => {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character];
    });
  }

  function fmtMoney(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
    const sign = Number(value) < 0 ? "-" : "";
    return `${sign}$${Math.abs(Number(value)).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })}`;
  }

  function fmtQty(value) {
    if (value === null || value === undefined) return "—";
    return Number(value).toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  function setBadge(element, status) {
    const classes = {
      AUTO_APPROVE: "status-auto",
      REVIEW: "status-review",
      ESCALATE: "status-escalate"
    };
    element.className = `status-badge ${classes[status] || "status-ready"}`;
    element.textContent = status || "READY";
  }

  function statusClass(status) {
    return status === "AUTO_APPROVE" ? "good" : status === "ESCALATE" ? "bad" : "warn";
  }

  function severityClass(severity) {
    return String(severity || "").toLowerCase();
  }

  function toast(message, isError) {
    if (!els.toast) return;
    window.clearTimeout(toastTimer);
    els.toast.textContent = message;
    els.toast.className = `toast is-visible${isError ? " is-error" : ""}`;
    toastTimer = window.setTimeout(() => {
      els.toast.className = "toast";
    }, 3600);
  }

  function markStagesComplete() {
    $$(".stage").forEach((stage) => {
      stage.classList.add("is-complete");
      stage.classList.remove("is-active");
    });
  }

  function clearStages() {
    $$(".stage").forEach((stage) => stage.classList.remove("is-active", "is-complete"));
  }

  function runPipeline(rawText, source, options) {
    const opts = options || {};
    try {
      const parsed = Engine.parseInvoice(rawText, source);
      const validation = Engine.validateAndRoute(parsed);
      const agent = Engine.runLocalAgent(parsed, validation);

      state.rawText = rawText;
      state.source = source;
      state.parsed = parsed;
      state.validation = validation;
      state.agent = agent;
      state.report = {
        project: "ai-operations-mockup",
        generated_at: new Date().toISOString(),
        parsed: parsed,
        validation: validation,
        agent: agent
      };
      window.__opsReport = state.report;
      renderAll();
      if (!opts.keepStages) markStagesComplete();
      if (!opts.silent) toast(`Pipeline complete · ${agent.summary.invoice_number} routed to ${validation.status}.`);
      return true;
    } catch (error) {
      toast(error.message || "Pipeline failed.", true);
      return false;
    }
  }

  function renderAll() {
    renderHero();
    renderRaw();
    renderIdentity();
    renderTruthStats();
    renderTotals();
    renderLineItems();
    renderFindings();
    renderAgent();
    renderActionLog();
  }

  function renderHero() {
    if (!state.parsed || !state.validation || !state.agent) return;
    const parsed = state.parsed;
    const validation = state.validation;
    const agent = state.agent;
    const exceptions = agent.insights.filter((insight) => insight.severity === "high" || insight.severity === "medium").length;

    setBadge(els.heroStatus, validation.status);
    els.heroTotal.textContent = fmtMoney(validation.totals.computed_total_due);
    els.heroSub.textContent = `${parsed.metadata.invoice_number} · ${parsed.supplier.name} · ${parsed.line_items.length} line items`;
    els.heroRisk.textContent = `${validation.risk_score}/100 · ${agent.risk_level}`;
    els.heroRiskBar.style.width = `${Math.max(0, Math.min(100, validation.risk_score))}%`;
    els.kpiInvoice.textContent = parsed.metadata.invoice_number || "—";
    els.kpiPo.textContent = parsed.metadata.po_number || "—";
    els.kpiSupplier.textContent = parsed.supplier.name || "—";
    els.kpiExceptions.textContent = String(exceptions);
  }

  function renderRaw() {
    els.rawPreview.textContent = state.rawText;
    els.sourceMeta.textContent = state.source;

    const warnings = (state.parsed && state.parsed.parse_warnings) || [];
    if (!warnings.length) {
      const count = state.parsed ? state.parsed.line_items.length : 0;
      els.parseWarnings.innerHTML = `<div class="success-note">Parser clean · ${count} line item(s) extracted · 0 warnings</div>`;
      return;
    }
    els.parseWarnings.innerHTML = warnings
      .map((warning) => `<div class="warning-item"><span aria-hidden="true">!</span><span>${esc(warning)}</span></div>`)
      .join("");
  }

  function renderIdentity() {
    if (!state.parsed) return;
    const parsed = state.parsed;
    const metadata = parsed.metadata;
    const supplier = parsed.supplier;
    setBadge(els.truthStatus, state.validation.status);

    const entries = [
      ["Supplier", supplier.name],
      ["Invoice", metadata.invoice_number],
      ["PO", metadata.po_number],
      ["Project", metadata.project],
      ["Invoice date", metadata.invoice_date],
      ["Due date", metadata.due_date],
      ["Ship via", metadata.ship_via],
      ["Payment terms", metadata.payment_terms]
    ];

    els.identityGrid.innerHTML = entries
      .map(([label, value]) => {
        const wide = label === "Project" ? " wide" : "";
        return `<div class="identity-item${wide}"><span>${esc(label)}</span><strong title="${esc(value)}">${esc(value || "—")}</strong></div>`;
      })
      .join("");

    const approvalNames = state.validation.approvals_required.length
      ? state.validation.approvals_required.join(" · ")
      : "none";
    els.approvalRow.innerHTML = [
      `<span class="approval-chip">Queue <strong>${esc(state.validation.queue)}</strong></span>`,
      `<span class="approval-chip">Approvals <strong>${esc(approvalNames)}</strong></span>`
    ].join("");
  }

  function renderTruthStats() {
    if (!state.validation) return;
    const totals = state.validation.totals;
    const variance = totals.total_variance;
    const varianceOk = variance !== null && variance !== undefined && Math.abs(variance) <= 0.02;
    const stats = [
      { label: "Materials", value: fmtMoney(totals.computed_subtotal), sub: "computed truth", cls: "" },
      { label: "Freight", value: fmtMoney(totals.freight), sub: "document value", cls: "" },
      { label: "Sales tax", value: fmtMoney(totals.computed_tax), sub: `${totals.tax_rate_percent !== null ? totals.tax_rate_percent : "n/a"}% rate`, cls: "" },
      {
        label: "Variance",
        value: fmtMoney(variance),
        sub: varianceOk ? "within tolerance" : "review required",
        cls: varianceOk ? "good" : "bad"
      }
    ];

    els.truthStats.innerHTML = stats
      .map(
        (stat) => `<div class="stat-card ${stat.cls}"><span>${esc(stat.label)}</span><strong>${esc(stat.value)}</strong><small>${esc(stat.sub)}</small></div>`
      )
      .join("");
  }

  function renderTotals() {
    if (!state.validation) return;
    const totals = state.validation.totals;
    const rate = totals.tax_rate_percent;
    const rows = [];

    rows.push(totalRow("Materials subtotal", totals.computed_subtotal, totals.declared_subtotal));
    rows.push(totalRow("Freight", totals.freight, null));
    rows.push(totalRow(`Sales tax ${rate !== null ? `(${rate}%)` : ""}`, totals.computed_tax, totals.declared_tax));
    rows.push(totalRow("Total due", totals.computed_total_due, totals.declared_total_due, "grand"));

    const variance = totals.total_variance;
    const varianceOk = variance !== null && variance !== undefined && Math.abs(variance) <= 0.02;
    rows.push(
      `<div class="variance-note ${varianceOk ? "ok" : "bad"}">${
        varianceOk ? "Reconciled" : "Reconciliation required"
      } · variance ${fmtMoney(variance)} vs document</div>`
    );
    els.totalsList.innerHTML = rows.join("");
  }

  function totalRow(label, value, declared, extraClass) {
    const declaredText = declared === null || declared === undefined ? "" : `doc ${fmtMoney(declared)}`;
    return `<div class="total-row ${extraClass || ""}"><span>${esc(label)}</span><strong>${esc(
      fmtMoney(value)
    )}</strong><em>${esc(declaredText)}</em></div>`;
  }

  function renderLineItems() {
    if (!state.parsed) return;
    const items = state.parsed.line_items;
    els.itemCount.textContent = `${items.length} line item${items.length === 1 ? "" : "s"}`;

    els.lineItemsBody.innerHTML = items
      .map(
        (item) => `<tr>
          <td class="num">${esc(item.line_number)}</td>
          <td>${esc(item.description)}</td>
          <td class="num">${esc(fmtQty(item.quantity))}</td>
          <td>${esc(item.unit)}</td>
          <td class="num">${esc(fmtMoney(item.unit_price))}</td>
          <td class="num line-total">${esc(fmtMoney(item.computed_line_total))}</td>
        </tr>`
      )
      .join("");

    const total = items.reduce((sum, item) => sum + (Number(item.computed_line_total) || 0), 0);
    els.lineItemsFoot.innerHTML = `<tr><td colspan="5" class="foot-label">Computed line-item total</td><td class="num foot-value">${esc(
      fmtMoney(total)
    )}</td></tr>`;
  }

  function renderFindings() {
    if (!state.validation) return;
    const validation = state.validation;
    els.rulesVersion.textContent = `rules ${validation.rules_version}`;
    els.routingReason.textContent = validation.reason;

    const counts = validation.severity_counts;
    els.validationSummary.innerHTML = [
      `<span class="summary-chip critical">${counts.critical} critical</span>`,
      `<span class="summary-chip warning">${counts.warning} warning</span>`,
      `<span class="summary-chip info">${counts.info} info</span>`,
      `<span class="summary-chip neutral">risk ${validation.risk_score}/100</span>`,
      `<span class="summary-chip neutral">${esc(validation.queue)}</span>`
    ].join("");

    if (!validation.findings.length) {
      els.findingsList.innerHTML = `<div class="success-note">All deterministic controls passed.</div>`;
      return;
    }

    els.findingsList.innerHTML = validation.findings
      .map((item) => {
        const severity = severityClass(item.severity);
        return `<div class="finding ${severity}">
          <div class="finding-top">
            <span class="severity ${severity}">${esc(item.severity)}</span>
            <span class="finding-rule">${esc(item.rule_id)}</span>
          </div>
          <p>${esc(item.message)}</p>
        </div>`;
      })
      .join("");
  }

  function renderAgent() {
    if (!state.agent) return;
    const agent = state.agent;
    els.aiSummary.textContent = agent.executive_summary;
    els.agentMeta.innerHTML = [
      `<span>Risk <strong>${esc(agent.risk_level.toUpperCase())}</strong></span>`,
      `<span>Confidence <strong>${Math.round(agent.confidence * 100)}%</strong></span>`,
      `<span>Network calls <strong>${agent.agent.network_calls}</strong></span>`,
      `<span>Model <strong>${esc(agent.agent.name)}</strong></span>`
    ].join("");

    els.insightsList.innerHTML = agent.insights
      .map((insight) => {
        const severity = severityClass(insight.severity);
        return `<div class="insight">
          <div class="insight-top">
            <span class="severity ${severity}">${esc(insight.severity)}</span>
            <strong>${esc(insight.title)}</strong>
            <span class="finding-rule">${esc(insight.id)}</span>
          </div>
          <p>${esc(insight.detail)}</p>
          <p class="impact"><strong>Impact:</strong> ${esc(insight.impact)}</p>
        </div>`;
      })
      .join("");

    els.actionsList.innerHTML = agent.recommended_actions
      .map(
        (action) => `<div class="action">
          <span class="priority ${esc(action.priority.toLowerCase())}">${esc(action.priority)}</span>
          <div class="action-body"><strong>${esc(action.owner)}</strong><span>${esc(action.action)}</span></div>
          <span class="action-due">${esc(action.due)}</span>
        </div>`
      )
      .join("");

    els.fieldBrief.textContent = agent.field_brief;

    if (agent.supplier_followup) {
      const followup = agent.supplier_followup;
      els.followupDetails.hidden = false;
      els.followupContent.innerHTML = `
        <p class="followup-meta">To: ${esc(followup.to)}<br>Subject: ${esc(followup.subject)}</p>
        <p class="followup-body">${esc(followup.body)}</p>
        <button class="btn btn-small btn-secondary" type="button" data-copy-followup>Copy draft</button>
      `;
    } else {
      els.followupDetails.hidden = true;
      els.followupContent.innerHTML = "";
    }
  }

  function renderActionLog() {
    if (!state.agent) return;
    els.actionLog.innerHTML = state.agent.action_log
      .map((event) => {
        const severity = severityClass(event.severity);
        return `<div class="log-entry ${severity}">
          <span class="log-time">${esc(formatTimestamp(event.timestamp))}</span>
          <span class="log-event">${esc(event.event)}</span>
          <span class="log-detail">${esc(event.detail)}</span>
        </div>`;
      })
      .join("");
  }

  function formatTimestamp(iso) {
    if (!iso) return "";
    return `${iso.slice(0, 10)} ${iso.slice(11, 19)}`;
  }

  function setStage(index) {
    const stages = $$(".stage");
    stages.forEach((stage, stageIndex) => {
      stage.classList.toggle("is-active", stageIndex === index);
      if (stageIndex < index) stage.classList.add("is-complete");
    });
  }

  function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  async function runGuidedDemo() {
    const token = ++state.demoToken;
    const stages = $$(".stage");
    clearStages();
    const ok = runPipeline(Engine.SAMPLE_INVOICE, "sample_invoice.txt", { silent: true, keepStages: true });
    if (!ok) return;

    for (let index = 0; index < stages.length; index += 1) {
      if (token !== state.demoToken) return;
      setStage(index);
      const target = document.getElementById(stages[index].dataset.target);
      if (target) {
        target.classList.add("spotlight");
        target.scrollIntoView({ behavior: scrollBehavior, block: "center" });
      }
      await delay(560);
      if (target) target.classList.remove("spotlight");
      stages[index].classList.remove("is-active");
      stages[index].classList.add("is-complete");
    }

    if (token !== state.demoToken) return;
    const total = state.validation ? state.validation.totals.computed_total_due : null;
    toast(`Real-time truth ready · ${fmtMoney(total)} · ${state.validation.status}.`);
    const truth = document.getElementById("truth-panel");
    if (truth) truth.scrollIntoView({ behavior: scrollBehavior, block: "center" });
  }

  function handleFile(file) {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      toast("Please use a text file under 2 MB.", true);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      state.demoToken += 1;
      const raw = String(reader.result || "");
      if (!raw.trim()) {
        toast("The selected file is empty.", true);
        return;
      }
      const ok = runPipeline(raw, file.name, { silent: false });
      if (ok) toast(`Loaded ${file.name} · ${state.validation.status} · ${fmtMoney(state.validation.totals.computed_total_due)}.`);
    };
    reader.onerror = () => toast("Could not read that file.", true);
    reader.readAsText(file);
  }

  function downloadReport() {
    if (!state.report) return;
    const blob = new Blob([JSON.stringify(state.report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "operations_report.json";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("JSON report downloaded.");
  }

  function copyFollowup(button) {
    if (!state.agent || !state.agent.supplier_followup) return;
    const text = state.agent.supplier_followup.body;
    const done = () => toast("Supplier follow-up copied.");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
    } else {
      fallbackCopy(text, done);
    }
    button.blur();
  }

  function fallbackCopy(text, done) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
      done();
    } catch (error) {
      toast("Copy failed. Select the draft manually.", true);
    }
    textarea.remove();
  }

  function bindEvents() {
    els.runDemo.addEventListener("click", runGuidedDemo);
    els.resetSample.addEventListener("click", () => {
      state.demoToken += 1;
      els.fileInput.value = "";
      const ok = runPipeline(Engine.SAMPLE_INVOICE, "sample_invoice.txt", { silent: false });
      if (ok) {
        clearStages();
        markStagesComplete();
        const source = document.getElementById("source-panel");
        if (source) source.scrollIntoView({ behavior: scrollBehavior, block: "start" });
      }
    });

    els.fileInput.addEventListener("change", (event) => {
      const file = event.target.files && event.target.files[0];
      handleFile(file);
    });

    els.downloadJson.addEventListener("click", downloadReport);

    document.addEventListener("click", (event) => {
      const copyButton = event.target.closest("[data-copy-followup]");
      if (copyButton) copyFollowup(copyButton);
    });

    $$(".stage").forEach((stage) => {
      stage.addEventListener("click", () => {
        state.demoToken += 1;
        const target = document.getElementById(stage.dataset.target);
        $$(".stage").forEach((item) => item.classList.remove("is-active"));
        stage.classList.add("is-active");
        if (target) {
          target.classList.add("spotlight");
          target.scrollIntoView({ behavior: scrollBehavior, block: "center" });
          window.setTimeout(() => target.classList.remove("spotlight"), 1200);
        }
      });
    });

    ["dragenter", "dragover"].forEach((eventName) => {
      els.dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        els.dropzone.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach((eventName) => {
      els.dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        els.dropzone.classList.remove("is-dragover");
      });
    });
    els.dropzone.addEventListener("drop", (event) => {
      const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
      handleFile(file);
    });

    window.addEventListener("dragover", (event) => event.preventDefault());
    window.addEventListener("drop", (event) => event.preventDefault());
  }

  function init() {
    bindEvents();
    const ok = runPipeline(Engine.SAMPLE_INVOICE, "sample_invoice.txt", { silent: true });
    if (ok) markStagesComplete();
    window.__opsState = state;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
