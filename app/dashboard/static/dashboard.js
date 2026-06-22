const PROVIDERS = ["codex", "anthropic", "azure", "fusion"];
const WINDOW_STORAGE_KEY = "conduit-dashboard-window";
const GROUP_STORAGE_KEY = "conduit-dashboard-group";
const CHART_MODE_STORAGE_KEY = "conduit-dashboard-chart-modes";
const WINDOW_OPTIONS = [
  { value: "all", label: "Session", seconds: null },
  { value: "1800", label: "30 minutes", seconds: 1800 },
  { value: "3600", label: "60 minutes", seconds: 3600 },
  { value: "10800", label: "3 hours", seconds: 10800 },
  { value: "21600", label: "6 hours", seconds: 21600 },
  { value: "43200", label: "12 hours", seconds: 43200 },
  { value: "86400", label: "24 hours", seconds: 86400 },
  { value: "259200", label: "3 days", seconds: 259200 },
  { value: "604800", label: "7 days", seconds: 604800 },
  { value: "2592000", label: "1 month", seconds: 2592000 },
  { value: "7776000", label: "3 months", seconds: 7776000 },
];
const GROUP_OPTIONS = [
  { value: "none", label: "None" },
  { value: "provider", label: "Provider" },
  { value: "upstream", label: "Upstream" },
  { value: "model", label: "Model" },
  { value: "phase", label: "Phase" },
  { value: "tier", label: "Tier" },
  { value: "plan", label: "Plan" },
  { value: "status", label: "Status" },
];
const CHART_MODE_OPTIONS = ["area", "line", "bar"];
const COLORS = {
  codex: "#00c7e6",
  anthropic: "#e5534b",
  azure: "#1ce8ff",
  fusion: "#f5a623",
  panel: "#00c7e6",
  synthesizer: "#f5a623",
};
const PALETTE = ["#00c7e6", "#7ed321", "#f5a623", "#9966cc", "#e5534b", "#1ce8ff", "#c8e6a0", "#f8e08e"];

let lastSequence = null;
let lastSnapshot = null;
let lastRawSnapshot = null;
let refreshTimer = null;
let tokenHover = null;
let latencyBandsHover = null;
const chartHovers = {};
let selectedWindowValue = loadWindowValue();
let selectedGroupValue = loadGroupValue();
let chartModes = loadChartModes();

const $ = (id) => document.getElementById(id);

function setText(id, value) {
  const target = $(id);
  if (target) target.textContent = value;
}

function loadWindowValue() {
  try {
    const stored = window.sessionStorage.getItem(WINDOW_STORAGE_KEY);
    if (WINDOW_OPTIONS.some((item) => item.value === stored)) return stored;
  } catch (error) {
    // Session storage can fail in locked-down browsers; the dashboard can live without it.
  }
  return "10800";
}

function saveWindowValue(value) {
  selectedWindowValue = WINDOW_OPTIONS.some((item) => item.value === value) ? value : "10800";
  try {
    window.sessionStorage.setItem(WINDOW_STORAGE_KEY, selectedWindowValue);
  } catch (error) {
    // Non-fatal. A non-sticky dashboard is annoying, not broken.
  }
}

function selectedWindow() {
  return WINDOW_OPTIONS.find((item) => item.value === selectedWindowValue) || WINDOW_OPTIONS[0];
}

function loadGroupValue() {
  try {
    const stored = window.sessionStorage.getItem(GROUP_STORAGE_KEY);
    if (GROUP_OPTIONS.some((item) => item.value === stored)) return stored;
  } catch (error) {
    // Same deal as the window selector: storage failure is an annoyance, not a dashboard outage.
  }
  return "provider";
}

function saveGroupValue(value) {
  selectedGroupValue = GROUP_OPTIONS.some((item) => item.value === value) ? value : "provider";
  try {
    window.sessionStorage.setItem(GROUP_STORAGE_KEY, selectedGroupValue);
  } catch (error) {
    // Keep rendering. Browsers have opinions and some of them are terrible.
  }
}

function selectedGroup() {
  return GROUP_OPTIONS.find((item) => item.value === selectedGroupValue) || GROUP_OPTIONS[0];
}

function loadChartModes() {
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(CHART_MODE_STORAGE_KEY) || "{}");
    return Object.fromEntries(Object.entries(parsed).filter(([, value]) => CHART_MODE_OPTIONS.includes(value)));
  } catch (error) {
    return {};
  }
}

function saveChartModes() {
  try {
    window.sessionStorage.setItem(CHART_MODE_STORAGE_KEY, JSON.stringify(chartModes));
  } catch (error) {
    // Losing chart mode stickiness is not worth interrupting the dashboard.
  }
}

function chartMode(key) {
  return CHART_MODE_OPTIONS.includes(chartModes[key]) ? chartModes[key] : "area";
}

function setupWindowControl() {
  const select = $("window-select");
  if (!select) return;
  select.value = selectedWindowValue;
  select.addEventListener("change", () => {
    saveWindowValue(select.value);
    if (lastRawSnapshot) renderSnapshot(lastRawSnapshot);
  });
}

function setupGroupControl() {
  const select = $("group-select");
  if (!select) return;
  select.value = selectedGroupValue;
  select.addEventListener("change", () => {
    saveGroupValue(select.value);
    if (lastRawSnapshot) renderSnapshot(lastRawSnapshot);
  });
}

function setupChartModeControls() {
  document.querySelectorAll(".chart-mode-control").forEach((control) => {
    const key = control.getAttribute("data-chart-key");
    if (!key) return;
    control.querySelectorAll(".chart-mode-button").forEach((button) => {
      const mode = button.getAttribute("data-chart-mode");
      button.classList.toggle("active", mode === chartMode(key));
      button.addEventListener("click", () => {
        if (!CHART_MODE_OPTIONS.includes(mode)) return;
        chartModes = { ...chartModes, [key]: mode };
        saveChartModes();
        updateChartModeButtons();
        if (lastSnapshot) drawAllCharts(lastSnapshot.timeseries || []);
      });
    });
  });
}

function updateChartModeButtons() {
  document.querySelectorAll(".chart-mode-control").forEach((control) => {
    const key = control.getAttribute("data-chart-key");
    control.querySelectorAll(".chart-mode-button").forEach((button) => {
      button.classList.toggle("active", button.getAttribute("data-chart-mode") === chartMode(key));
    });
  });
}

function formatNumber(value) {
  const number = Number(value || 0);
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(number);
}

function formatCompact(value) {
  const number = Number(value || 0);
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(number);
}

function formatPct(value) {
  const number = Number(value || 0) * 100;
  return `${number.toFixed(number >= 10 ? 0 : 1)}%`;
}

function formatMs(value) {
  const number = Number(value || 0);
  if (number >= 1000) return `${(number / 1000).toFixed(1)}s`;
  return `${formatNumber(number)}ms`;
}

function formatTime(epochSeconds) {
  if (!epochSeconds) return "never";
  return new Date(epochSeconds * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function statTile(label, value) {
  return `<div class="stat-tile"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

async function fetchSnapshot() {
  const response = await fetch("/dashboard/api/snapshot", { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function renderLoop() {
  try {
    const snapshot = await fetchSnapshot();
    lastRawSnapshot = snapshot;
    renderSnapshot(snapshot);
    setOnline(true);
  } catch (error) {
    setOnline(false, error.message);
  } finally {
    refreshTimer = window.setTimeout(renderLoop, 1000);
  }
}

function setOnline(online, detail = "") {
  const status = $("connection-status");
  const orb = $("connection-orb");
  if (!status || !orb) return;
  orb.classList.toggle("offline", !online);
  status.textContent = online ? "Live" : `Offline${detail ? ` - ${detail}` : ""}`;
}

function renderSnapshot(rawSnapshot) {
  const snapshot = applyWindowFilter(rawSnapshot);
  lastSnapshot = snapshot;
  lastSequence = rawSnapshot.sequence;
  renderTotals(snapshot.totals || {});
  renderLatencyMetric(snapshot.providers || {});
  renderOpsReview(snapshot.ops_review || {});
  renderProviders(snapshot.providers || {}, snapshot.timeseries || []);
  renderProviderPosture(snapshot.providers || {});
  renderProviderRunway(snapshot.providers || {}, snapshot.timeseries || []);
  renderProviderReadiness(snapshot.providers || {}, snapshot.recent_requests || [], snapshot.active_requests || []);
  renderRateLimits(snapshot.providers || {}, snapshot.rate_limit_note);
  renderFusionRuns(snapshot.fusion_runs || []);
  renderRequests("active-requests", snapshot.active_requests || [], true);
  renderRequests("recent-requests", snapshot.recent_requests || [], false);
  renderGroupPressure(snapshot.recent_requests || [], snapshot.active_requests || []);
  renderModelLeaderboard(snapshot.recent_requests || []);
  renderIssueQueue(snapshot.recent_requests || [], snapshot.active_requests || []);
  renderLatencyDistribution(snapshot.recent_requests || [], snapshot.active_requests || []);
  renderFailureTaxonomy(snapshot.recent_requests || [], snapshot.active_requests || []);
  renderFailureFingerprints(snapshot.recent_requests || [], snapshot.active_requests || []);
  renderContentionMap(snapshot.recent_requests || [], snapshot.active_requests || []);
  renderRouteMatrix(snapshot.recent_requests || [], snapshot.active_requests || []);
  renderRouteSloBoard(snapshot.recent_requests || [], snapshot.active_requests || []);
  renderTrafficHeatmap(snapshot.timeseries || [], snapshot.generated_at);
  renderExecutionTimeline(snapshot.recent_requests || [], snapshot.active_requests || [], snapshot.generated_at);
  renderStreamShape(snapshot.recent_requests || [], snapshot.active_requests || []);
  renderContent(snapshot.content_events || []);
  drawAllCharts(snapshot.timeseries || []);
  setText("chart-window", windowLabel(snapshot));
  setText("posture-window", windowLabel(snapshot));
  setText("runway-window", windowLabel(snapshot));
  setText("readiness-window", windowLabel(snapshot));
  setText("heatmap-window", windowLabel(snapshot));
  setText("slo-window", windowLabel(snapshot));
  setText("latency-bands-window", windowLabel(snapshot));
  setText("fingerprint-window", windowLabel(snapshot));
  setText("contention-window", windowLabel(snapshot));
  setText("timeline-window", windowLabel(snapshot));
  setText("stream-window", windowLabel(snapshot));
  setText("last-updated", `Updated ${formatTime(rawSnapshot.generated_at)} - sequence ${lastSequence ?? 0} - window ${windowLabel(snapshot)}`);
  const scope = snapshot.scope || {};
  setText("scope-note", `${scope.process_scope || "in-process"} - ${formatNumber(scope.uptime_seconds || 0)}s uptime`);
  updateMenuBadges(snapshot);
}

function applyWindowFilter(rawSnapshot) {
  const option = selectedWindow();
  const cutoff = option.seconds ? Number(rawSnapshot.generated_at || Date.now() / 1000) - option.seconds : null;
  const active = (rawSnapshot.active_requests || []).slice();
  const recent = cutoff == null
    ? (rawSnapshot.recent_requests || []).slice()
    : (rawSnapshot.recent_requests || []).filter((request) => recordInWindow(request, cutoff));
  const records = [...active, ...recent];
  const timeseries = cutoff == null
    ? (rawSnapshot.timeseries || []).slice()
    : (rawSnapshot.timeseries || []).filter((point) => Number(point.t || 0) >= cutoff);
  const contentEvents = cutoff == null
    ? (rawSnapshot.content_events || []).slice()
    : (rawSnapshot.content_events || []).filter((event) => Number(event.timestamp || 0) >= cutoff);

  const scoped = {
    ...rawSnapshot,
    active_requests: active,
    recent_requests: recent,
    content_events: contentEvents,
    timeseries,
    totals: totalSummary(records),
    providers: providerSummaries(records),
    fusion_runs: fusionSummaries(records, Number(rawSnapshot.generated_at || Date.now() / 1000)),
  };
  scoped.ops_review = buildClientOpsReview(scoped);
  scoped.scope = {
    ...(rawSnapshot.scope || {}),
    selected_window: option.value,
    selected_window_label: option.label,
    selected_window_seconds: option.seconds,
    cutoff,
  };
  return scoped;
}

function recordInWindow(record, cutoff) {
  return Number(record.ended_at || record.started_at || 0) >= cutoff;
}

function windowLabel(snapshot) {
  const scope = snapshot.scope || {};
  if (scope.selected_window_seconds) return scope.selected_window_label || selectedWindow().label;
  return "session";
}

function emptyUsage() {
  return {
    input_tokens: 0,
    output_tokens: 0,
    reasoning_tokens: 0,
    total_tokens: 0,
  };
}

function emptyCache() {
  return {
    read_tokens: 0,
    write_tokens: 0,
    write_5m_tokens: 0,
    write_1h_tokens: 0,
    hit_ratio: 0,
  };
}

function emptyProviderSummary(provider) {
  return {
    provider,
    label: providerLabel(provider),
    requests: 0,
    active: 0,
    errors: 0,
    success_rate: 0,
    latency_ms_avg: 0,
    latency_ms_p95: 0,
    usage: emptyUsage(),
    cache: emptyCache(),
    rate_limits: { status: "unknown" },
    models: {},
  };
}

function sumUsage(records) {
  const usage = emptyUsage();
  for (const record of records || []) {
    const item = record.usage || {};
    usage.input_tokens += Number(item.input_tokens || 0);
    usage.output_tokens += Number(item.output_tokens || 0);
    usage.reasoning_tokens += Number(item.reasoning_tokens || 0);
    usage.total_tokens += Number(item.total_tokens || 0);
  }
  return usage;
}

function sumCache(records) {
  const cache = emptyCache();
  for (const record of records || []) {
    const item = record.cache || {};
    cache.read_tokens += Number(item.read_tokens || 0);
    cache.write_tokens += Number(item.write_tokens || 0);
    cache.write_5m_tokens += Number(item.write_5m_tokens || 0);
    cache.write_1h_tokens += Number(item.write_1h_tokens || 0);
  }
  cache.hit_ratio = cacheRatio(records);
  return cache;
}

function cacheRatio(records) {
  const base = (records || []).reduce((sum, record) => {
    const usage = record.usage || {};
    const cache = record.cache || {};
    return sum
      + Number(usage.input_tokens || 0)
      + Number(cache.read_tokens || 0)
      + Number(cache.write_tokens || 0);
  }, 0);
  const read = (records || []).reduce((sum, record) => sum + Number((record.cache || {}).read_tokens || 0), 0);
  return base > 0 ? read / base : 0;
}

function totalSummary(records) {
  return {
    requests: (records || []).length,
    active: (records || []).filter((record) => record.active).length,
    errors: (records || []).filter(isErrorRecord).length,
    usage: sumUsage(records),
    cache: sumCache(records),
    estimated_spend_usd: null,
    estimated_spend_note: "No pricing table is configured; token burn is reported without fabricated spend.",
  };
}

function providerSummaries(records) {
  return Object.fromEntries(PROVIDERS.map((provider) => [
    provider,
    providerSummary(provider, (records || []).filter((record) => record.provider === provider)),
  ]));
}

function providerSummary(provider, records) {
  const summary = emptyProviderSummary(provider);
  if (!records.length) return summary;
  const completed = records.filter((record) => !record.active);
  const latencies = completed.map((record) => Number(record.duration_ms || 0)).filter((value) => value >= 0);
  const success = records.filter((record) => !isErrorRecord(record) && isSuccessRecord(record)).length;
  return {
    ...summary,
    requests: records.length,
    active: records.filter((record) => record.active).length,
    errors: records.filter(isErrorRecord).length,
    success_rate: records.length ? success / records.length : 0,
    latency_ms_avg: latencies.length ? Math.round(latencies.reduce((sum, value) => sum + value, 0) / latencies.length) : 0,
    latency_ms_p95: percentile(latencies, 0.95),
    usage: sumUsage(records),
    cache: sumCache(records),
    rate_limits: latestRateLimits(records),
    models: modelCounts(records),
  };
}

function isErrorRecord(record) {
  const status = Number(record.final_status || record.upstream_status || 0);
  return Boolean(record.error || record.ok === false || status >= 400);
}

function isSuccessRecord(record) {
  const status = Number(record.final_status || record.upstream_status || 0);
  if (record.active) return false;
  if (status === 0) return Boolean(record.ok);
  return status >= 200 && status < 400;
}

function latestRateLimits(records) {
  const sorted = (records || []).slice().sort((a, b) => Number(b.started_at || 0) - Number(a.started_at || 0));
  for (const record of sorted) {
    const limits = record.rate_limits || {};
    if (Object.keys(limits).some((key) => key !== "status")) return limits;
  }
  return { status: "unknown" };
}

function modelCounts(records) {
  const counts = new Map();
  for (const record of records || []) {
    const model = record.model || record.display_label || "unknown";
    counts.set(model, (counts.get(model) || 0) + 1);
  }
  return Object.fromEntries(Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 12));
}

function fusionSummaries(records, now) {
  const grouped = new Map();
  for (const record of records || []) {
    if (record.provider !== "fusion" || !record.run_id) continue;
    const calls = grouped.get(record.run_id) || [];
    calls.push(record);
    grouped.set(record.run_id, calls);
  }

  return Array.from(grouped.entries()).map(([runId, calls]) => {
    const ordered = calls.slice().sort((a, b) => (
      phaseRank(a.phase) - phaseRank(b.phase)
      || String(a.display_label || a.model || "").localeCompare(String(b.display_label || b.model || ""))
      || Number(a.started_at || 0) - Number(b.started_at || 0)
    ));
    const started = Math.min(...ordered.map((record) => Number(record.started_at || now)));
    const endedValues = ordered.map((record) => Number(record.ended_at || 0)).filter(Boolean);
    const active = ordered.filter((record) => record.active).length;
    const ended = endedValues.length ? Math.max(...endedValues) : null;
    const wallEnd = active ? now : ended || now;
    const errors = ordered.filter(isErrorRecord).length;
    return {
      run_id: runId,
      started_at: started,
      ended_at: ended,
      duration_ms: Math.max(0, Math.round((wallEnd - started) * 1000)),
      active,
      errors,
      ok: errors === 0 && ordered.every((record) => isSuccessRecord(record)),
      usage: sumUsage(ordered),
      cache: sumCache(ordered),
      slowest_label: slowestCallLabel(ordered),
      calls: ordered,
    };
  }).sort((a, b) => Number(b.started_at || 0) - Number(a.started_at || 0)).slice(0, 12);
}

function slowestCallLabel(records) {
  const slowest = (records || []).slice().sort((a, b) => Number(b.duration_ms || 0) - Number(a.duration_ms || 0))[0];
  return slowest ? slowest.display_label || slowest.label || slowest.model : null;
}

function buildClientOpsReview(snapshot) {
  const totals = snapshot.totals || {};
  const providers = snapshot.providers || {};
  const providerRows = PROVIDERS.map((provider) => providers[provider] || {});
  const requests = Number(totals.requests || 0);
  const errors = Number(totals.errors || 0);
  const active = Number(totals.active || 0);
  const p95 = Math.max(...providerRows.map((provider) => Number(provider.latency_ms_p95 || 0)), 0);
  const cacheHit = Number((totals.cache || {}).hit_ratio || 0);
  const fusionErrors = (snapshot.fusion_runs || []).reduce((sum, run) => sum + Number(run.errors || 0), 0);
  const findings = [];

  if (!requests) {
    findings.push(reviewFinding({
      severity: "warning",
      category: "Telemetry",
      title: `No traffic in ${windowLabel(snapshot)}`,
      detail: "The selected window does not include any active or completed requests.",
      evidence: "Requests: 0",
      action: "Widen the window or run a model call.",
    }));
  }
  if (errors) {
    findings.push(reviewFinding({
      severity: "error",
      category: "Routing",
      title: "Upstream errors present",
      detail: `${formatNumber(errors)} request${errors === 1 ? "" : "s"} failed in this window.`,
      evidence: `Error rate: ${formatPct(requests ? errors / requests : 0)}`,
      action: "Open the trouble queue and inspect status, provider, and preview details.",
    }));
  }
  if (active) {
    findings.push(reviewFinding({
      severity: "warning",
      category: "Streaming",
      title: "Active calls in flight",
      detail: `${formatNumber(active)} request${active === 1 ? " is" : "s are"} still running.`,
      evidence: `Active: ${formatNumber(active)}`,
      action: "Watch latency and stream chunk counters until completion.",
    }));
  }
  if (p95 >= 60_000) {
    findings.push(reviewFinding({
      severity: "warning",
      category: "Latency",
      title: "Latency p95 is high",
      detail: `Slowest provider p95 is ${formatMs(p95)}.`,
      evidence: `p95: ${formatMs(p95)}`,
      action: "Check provider spread and Fusion panel timing for the slowest route.",
    }));
  }
  if (requests >= 3 && cacheHit < 0.05) {
    findings.push(reviewFinding({
      severity: "warning",
      category: "Cache",
      title: "Cache is cold",
      detail: `Cache hit ratio is ${formatPct(cacheHit)} across visible traffic.`,
      evidence: `Cache hit: ${formatPct(cacheHit)}`,
      action: "Confirm prompt caching is expected for the selected providers and models.",
    }));
  }
  if (fusionErrors) {
    findings.push(reviewFinding({
      severity: "error",
      category: "Fusion",
      title: "Fusion run failures",
      detail: `${formatNumber(fusionErrors)} Fusion internal call${fusionErrors === 1 ? "" : "s"} failed.`,
      evidence: `Failed internal calls: ${formatNumber(fusionErrors)}`,
      action: "Inspect the Fusion runs panel for panel versus synthesizer failures.",
    }));
  }
  if (!findings.length) {
    findings.push(reviewFinding({
      severity: "healthy",
      category: "System",
      title: "No obvious problems",
      detail: "Visible traffic is completing without prominent latency or error signals.",
      evidence: "Primary signals clean",
      action: "Keep an eye on rate limits and cache ratio as load changes.",
    }));
  }

  const penalty = Math.min(70, errors * 18 + active * 4 + (p95 >= 60_000 ? 15 : 0) + (fusionErrors ? 14 : 0) + (!requests ? 18 : 0));
  const severity = errors || fusionErrors ? "attention" : (active || p95 >= 60_000 || !requests ? "watch" : "healthy");
  return {
    score: Math.max(0, 100 - penalty),
    severity,
    headline: reviewHeadline(severity, requests, errors, active),
    summary: `${windowLabel(snapshot)} - ${formatNumber(requests)} requests, ${formatNumber(errors)} errors, ${formatMs(p95)} p95`,
    risk_summary: reviewRiskSummary(findings, requests, errors, active, providerRows),
    signals: [
      { label: "Requests", value: formatNumber(requests), state: requests ? "good" : "muted" },
      { label: "Errors", value: formatNumber(errors), state: errors ? "bad" : "good" },
      { label: "Active", value: formatNumber(active), state: active ? "warn" : "good" },
      { label: "p95", value: formatMs(p95), state: p95 >= 60_000 ? "warn" : "good" },
      { label: "Cache", value: formatPct(cacheHit), state: cacheHit > 0.2 ? "good" : "muted" },
    ],
    findings,
    actions: reviewActions(findings, severity, requests),
    fix_queue: reviewFixQueue(findings, providerRows, requests),
    provider_posture: providerRows
      .filter((provider) => Number(provider.requests || 0) > 0)
      .map((provider) => reviewProviderPosture(provider)),
  };
}

function reviewFinding({ severity, category, title, detail, evidence, action }) {
  return { severity, category, title, detail, evidence, action };
}

function reviewHeadline(severity, requests, errors, active) {
  if (severity === "attention") return "Provider traffic needs inspection now.";
  if (active) return "Traffic is moving, with requests still in flight.";
  if (requests) return "The proxy is serving traffic in the selected window.";
  if (errors) return "No completed traffic remains visible, but errors were recorded.";
  return "No traffic yet in this dashboard window.";
}

function reviewActions(findings, severity, requests) {
  const rank = { error: 0, warning: 1, info: 2, healthy: 3 };
  const actions = (findings || [])
    .filter((finding) => finding.severity !== "healthy")
    .sort((a, b) => (rank[a.severity] ?? 4) - (rank[b.severity] ?? 4))
    .map((finding) => ({
      severity: finding.severity,
      label: finding.title,
      detail: finding.action,
    }));
  if (actions.length) return actions.slice(0, 5);
  return [{
    severity,
    label: "Next check",
    detail: requests ? "Let the proxy run; revisit this panel when traffic volume changes." : "Send a known-good smoke prompt through the proxy.",
  }];
}

function reviewRiskSummary(findings, requests, errors, active, providerRows) {
  const severityCounts = (findings || []).reduce((counts, finding) => {
    counts[finding.severity] = (counts[finding.severity] || 0) + 1;
    return counts;
  }, {});
  const troubledProviders = (providerRows || []).filter((provider) => {
    const posture = reviewProviderPosture(provider);
    return Number(provider.requests || 0) > 0 && !["ok", "healthy"].includes(posture.state);
  }).length;
  return [
    {
      label: "Blast radius",
      value: `${formatNumber(troubledProviders)} provider${troubledProviders === 1 ? "" : "s"}`,
      state: errors ? "bad" : (troubledProviders ? "warn" : "good"),
    },
    {
      label: "Open failures",
      value: formatNumber(errors),
      state: errors ? "bad" : "good",
    },
    {
      label: "In-flight risk",
      value: formatNumber(active),
      state: active ? "warn" : "good",
    },
    {
      label: "Review load",
      value: `${formatNumber(severityCounts.error || 0)}E / ${formatNumber(severityCounts.warning || 0)}W`,
      state: severityCounts.error ? "bad" : (severityCounts.warning ? "warn" : "good"),
    },
    {
      label: "Evidence base",
      value: `${formatNumber(requests)} call${requests === 1 ? "" : "s"}`,
      state: requests ? "neutral" : "muted",
    },
  ];
}

function reviewFixQueue(findings, providerRows, requests) {
  const rank = { error: 0, warning: 1, info: 2, healthy: 3 };
  const queue = (findings || [])
    .filter((finding) => finding.severity !== "healthy")
    .sort((a, b) => (rank[a.severity] ?? 4) - (rank[b.severity] ?? 4))
    .map((finding, index) => ({
      priority: String(index + 1),
      severity: finding.severity || "info",
      label: finding.title || "Review signal",
      why: finding.detail || "",
      next_step: finding.action || "",
      evidence: finding.evidence || "",
      source: finding.category || "Telemetry",
      impact: finding.severity === "error" ? "User-visible" : finding.severity === "warning" ? "Reliability" : "Operational",
      effort: index < 3 ? "Low" : "Medium",
    }));

  (providerRows || [])
    .filter((provider) => Number(provider.requests || 0) > 0)
    .map((provider) => reviewProviderPosture(provider))
    .filter((posture) => !["ok", "healthy"].includes(posture.state))
    .forEach((posture) => {
      queue.push({
        priority: String(queue.length + 1),
        severity: posture.state === "error" ? "error" : "warning",
        label: `${posture.label} posture`,
        why: `${posture.requests} calls, ${posture.errors} errors, ${posture.p95} p95.`,
        next_step: posture.action || "Inspect provider routing.",
        evidence: `Cache ${posture.cache}`,
        source: "Provider",
        impact: "Provider-specific",
        effort: "Low",
      });
    });

  if (queue.length) return queue.slice(0, 6);
  return [{
    priority: "1",
    severity: "healthy",
    label: "Keep watching",
    why: "No immediate action is visible in the current process window.",
    next_step: requests ? "Let traffic accumulate before changing routing." : "Run a known-good request and watch this panel.",
    evidence: `${formatNumber(requests)} tracked call${requests === 1 ? "" : "s"}`,
    source: "System",
    impact: "None",
    effort: "Low",
  }];
}

function reviewProviderPosture(provider) {
  const requests = Number(provider.requests || 0);
  const errors = Number(provider.errors || 0);
  const p95 = Number(provider.latency_ms_p95 || 0);
  const cache = Number((provider.cache || {}).hit_ratio || 0);
  let state = "ok";
  let action = "No immediate provider action.";
  if (errors) {
    state = "error";
    action = "Inspect failing rows, auth, model id, and rejected params.";
  } else if (p95 >= 60_000) {
    state = "slow";
    action = "Check model tier and streaming phase timing.";
  } else if (p95 >= 20_000 || (requests >= 3 && cache < 0.05)) {
    state = "watch";
    action = "Watch latency and cache behavior.";
  }
  return {
    provider: provider.provider,
    label: provider.label || providerLabel(provider.provider),
    state,
    requests: formatNumber(requests),
    errors: formatNumber(errors),
    p95: formatMs(p95),
    cache: formatPct(cache),
    action,
  };
}

function updateMenuBadges(snapshot) {
  const active = Number((snapshot.totals || {}).active || 0);
  const errors = Number((snapshot.totals || {}).errors || 0);
  document.querySelectorAll(".environment-chip .status-dot").forEach((dot) => {
    dot.classList.toggle("offline", Boolean(errors));
  });
  document.querySelectorAll('a[href="#review"]').forEach((link) => {
    link.classList.toggle("attention", Boolean(errors || active));
  });
}

function renderTotals(totals) {
  const usage = totals.usage || {};
  const cache = totals.cache || {};
  setText("metric-requests", formatNumber(totals.requests));
  setText("metric-active", `${formatNumber(totals.active)} active - ${formatNumber(totals.errors)} errors`);
  setText("metric-tokens", formatCompact(usage.total_tokens));
  setText("metric-token-split", `${formatCompact(usage.input_tokens)} in - ${formatCompact(usage.output_tokens)} out - ${formatCompact(usage.reasoning_tokens)} reasoning`);
  setText("metric-cache", formatPct(cache.hit_ratio));
  setText("metric-cache-detail", `${formatCompact(cache.read_tokens)} read - ${formatCompact(cache.write_tokens)} written`);
  setText("metric-spend", totals.estimated_spend_usd == null ? "Unknown" : `$${totals.estimated_spend_usd.toFixed(2)}`);
}

function renderLatencyMetric(providers) {
  const values = PROVIDERS.map((provider) => providers[provider] || {});
  const p95 = Math.max(...values.map((item) => Number(item.latency_ms_p95 || 0)), 0);
  const avgValues = values.map((item) => Number(item.latency_ms_avg || 0)).filter((value) => value > 0);
  const avg = avgValues.length ? avgValues.reduce((sum, value) => sum + value, 0) / avgValues.length : 0;
  setText("metric-latency", formatMs(p95));
  setText("metric-latency-detail", avg ? `${formatMs(avg)} avg across active providers` : "No completed calls");
}

function renderOpsReview(review) {
  const score = $("ops-score");
  const headline = $("ops-headline");
  const summary = $("ops-summary");
  const signals = $("ops-signals");
  const findings = $("ops-findings");
  const actions = $("ops-actions");
  const riskSummary = $("ops-risk-summary");
  const fixQueue = $("ops-fix-queue");
  const providerPosture = $("ops-provider-posture");
  const scoreBox = document.querySelector(".ops-score");
  if (!score || !headline || !summary || !signals || !findings || !actions || !riskSummary || !fixQueue || !providerPosture || !scoreBox) return;

  const severity = review.severity || "watch";
  scoreBox.classList.remove("healthy", "watch", "attention");
  scoreBox.classList.add(severity);
  score.textContent = Number.isFinite(Number(review.score)) ? String(review.score) : "--";
  headline.textContent = review.headline || "Waiting for telemetry.";
  summary.textContent = review.summary || "Waiting for telemetry.";
  signals.innerHTML = (review.signals || []).map((signal) => `
    <div class="ops-signal ${escapeHtml(signal.state || "neutral")}">
      <span>${escapeHtml(signal.label)}</span>
      <strong>${escapeHtml(signal.value)}</strong>
    </div>`).join("");
  riskSummary.innerHTML = (review.risk_summary || []).map((risk) => `
    <div class="ops-risk-tile ${escapeHtml(risk.state || "neutral")}">
      <span>${escapeHtml(risk.label || "Risk")}</span>
      <strong>${escapeHtml(risk.value || "-")}</strong>
    </div>`).join("");
  actions.innerHTML = (review.actions || []).map((action, index) => `
    <div class="ops-action ${escapeHtml(action.severity || "info")}">
      <span>${index + 1}</span>
      <div>
        <strong>${escapeHtml(action.label)}</strong>
        <em>${escapeHtml(action.detail)}</em>
      </div>
    </div>`).join("");
  fixQueue.innerHTML = (review.fix_queue || []).map((item) => `
    <div class="ops-fix-item ${escapeHtml(item.severity || "info")}">
      <span>${escapeHtml(item.priority || "-")}</span>
      <div>
        <small>${escapeHtml(item.source || "Signal")} - ${escapeHtml(item.impact || "Operational")} - ${escapeHtml(item.effort || "Low")} effort</small>
        <strong>${escapeHtml(item.label || "Review item")}</strong>
        <em>${escapeHtml(item.why || "")}</em>
        <code>${escapeHtml(item.evidence || "No extra evidence")}</code>
        <b>${escapeHtml(item.next_step || "")}</b>
      </div>
    </div>`).join("");
  providerPosture.innerHTML = (review.provider_posture || []).map((provider) => `
    <div class="ops-provider ${escapeHtml(provider.state || "ok")}">
      <span>${escapeHtml(provider.label)}</span>
      <strong>${escapeHtml(provider.state || "ok")}</strong>
      <em>${escapeHtml(provider.requests)} calls - ${escapeHtml(provider.errors)} errors - ${escapeHtml(provider.p95)} p95</em>
      <small>${escapeHtml(provider.cache)} cache - ${escapeHtml(provider.action)}</small>
    </div>`).join("");
  providerPosture.hidden = !(review.provider_posture || []).length;
  findings.innerHTML = (review.findings || []).map((finding) => `
    <div class="ops-finding ${escapeHtml(finding.severity || "info")}">
      <i aria-hidden="true"></i>
      <div>
        <small>${escapeHtml(finding.category || "Signal")}</small>
        <strong>${escapeHtml(finding.title)}</strong>
        <span>${escapeHtml(finding.detail)}</span>
        <code>${escapeHtml(finding.evidence || "No extra evidence")}</code>
        <em>${escapeHtml(finding.action)}</em>
      </div>
    </div>`).join("") || '<div class="empty-state">No ops findings yet.</div>';
}

function renderProviders(providers, timeseries) {
  for (const provider of PROVIDERS) {
    const target = $(`provider-${provider}`);
    if (!target) continue;
    const item = providers[provider] || {};
    const usage = item.usage || {};
    const cache = item.cache || {};
    target.innerHTML = [
      statTile("Requests", `${formatNumber(item.requests)} - ${formatNumber(item.active)} live`),
      statTile("Tokens", formatCompact(usage.total_tokens)),
      statTile("Cache", formatPct(cache.hit_ratio)),
      statTile("Latency avg", formatMs(item.latency_ms_avg)),
      statTile("Latency p95", formatMs(item.latency_ms_p95)),
      statTile("Success", formatPct(item.success_rate)),
    ].join("");
    drawSparkline($(`spark-${provider}`), timeseries.filter((point) => point.provider === provider), COLORS[provider]);
  }
}

function renderProviderPosture(providers) {
  const target = $("provider-posture");
  if (!target) return;
  const rows = PROVIDERS.map((provider) => providerPostureRow(provider, providers[provider] || emptyProviderSummary(provider)));
  const maxTokens = Math.max(...rows.map((row) => row.tokens), 1);
  target.innerHTML = `
    <div class="list-head posture-row">
      <span>Provider</span><span>State</span><span>Calls</span><span>Errors</span><span>Cache</span><span>p95</span><span>Tokens</span><span>Rate</span>
    </div>
    ${rows.map((row) => `
      <div class="list-row posture-row ${escapeHtml(row.severity)}">
        <div class="posture-provider">
          <i style="background:${row.color}; color:${row.color}"></i>
          <div>
            <strong>${escapeHtml(row.label)}</strong>
            <span>${escapeHtml(row.topModel)}</span>
          </div>
        </div>
        <span class="posture-state ${escapeHtml(row.severity)}">${escapeHtml(row.state)}</span>
        <span>${formatNumber(row.requests)} <em>${formatNumber(row.active)} live</em></span>
        <span>${formatNumber(row.errors)} <em>${formatPct(row.errorRate)}</em></span>
        <span>${formatPct(row.cacheRatio)} <em>${formatCompact(row.cacheRead)} read</em></span>
        <span>${formatMs(row.p95)} <em>${formatMs(row.avg)} avg</em></span>
        <span class="bar-stat"><i style="width:${Math.max(4, Math.min(100, (row.tokens / maxTokens) * 100))}%"></i><b>${formatCompact(row.tokens)}</b></span>
        <span>${escapeHtml(row.rate)}</span>
      </div>`).join("")}`;
}

function renderProviderRunway(providers, timeseries) {
  const target = $("provider-runway");
  if (!target) return;
  const rows = PROVIDERS.map((provider) => providerRunwayRow(provider, providers[provider] || emptyProviderSummary(provider), timeseries));
  target.innerHTML = rows.map((row) => `
    <article class="runway-card ${escapeHtml(row.severity)}">
      <div class="runway-card-head">
        <span style="--provider-color:${row.color}"></span>
        <div>
          <strong>${escapeHtml(row.label)}</strong>
          <small>${escapeHtml(row.summary)}</small>
        </div>
        <b>${escapeHtml(row.badge)}</b>
      </div>
      <div class="runway-bars">
        ${runwayBar("Latency", row.latencyTrend, row.latencyText, row.color)}
        ${runwayBar("Errors", row.errorTrend, row.errorText, COLORS.anthropic)}
        ${runwayBar("Tokens", row.tokenTrend, row.tokenText, COLORS.fusion)}
      </div>
      <div class="runway-foot">
        <span>${formatNumber(row.requests)} calls</span>
        <span>${formatMs(row.p95)} p95</span>
        <span>${formatPct(row.cacheRatio)} cache</span>
      </div>
    </article>`).join("");
}

function renderProviderReadiness(providers, recent, active) {
  const target = $("provider-readiness");
  if (!target) return;
  const records = [...(active || []), ...(recent || [])];
  const rows = PROVIDERS.map((provider) => providerReadinessRow(
    provider,
    providers[provider] || emptyProviderSummary(provider),
    records,
  ));
  const maxCalls = Math.max(...rows.map((row) => row.calls), 1);
  target.innerHTML = rows.map((row) => `
    <article class="readiness-card ${escapeHtml(row.state)}">
      <div class="readiness-head">
        <span style="--provider-color:${row.color}"></span>
        <div>
          <strong>${escapeHtml(row.label)}</strong>
          <small>${escapeHtml(row.model)}</small>
        </div>
        <em>${escapeHtml(row.badge)}</em>
      </div>
      <div class="readiness-meter" aria-label="${escapeHtml(row.label)} traffic share">
        <i style="width:${Math.max(4, Math.min(100, (row.calls / maxCalls) * 100))}%"></i>
      </div>
      <div class="readiness-facts">
        <span><b>${formatNumber(row.calls)}</b><small>calls</small></span>
        <span><b>${formatPct(row.successRate)}</b><small>success</small></span>
        <span><b>${formatMs(row.p95)}</b><small>p95</small></span>
        <span><b>${escapeHtml(row.rateLabel)}</b><small>rate</small></span>
      </div>
      <p>${escapeHtml(row.action)}</p>
      <footer>
        <span>${escapeHtml(row.lastSeen)}</span>
        <span>${escapeHtml(row.status)}</span>
      </footer>
    </article>`).join("");
}

function providerReadinessRow(provider, summary, allRecords) {
  const records = (allRecords || []).filter((record) => (
    record.provider === provider || record.upstream_provider === provider
  ));
  const directRequests = Number(summary.requests || 0);
  const calls = records.length || directRequests;
  const active = records.filter((record) => record.active).length || Number(summary.active || 0);
  const errors = records.filter(isErrorRecord).length || Number(summary.errors || 0);
  const completed = records.filter((record) => !record.active);
  const successes = records.filter((record) => !isErrorRecord(record) && isSuccessRecord(record)).length;
  const latencies = completed.map((record) => Number(record.duration_ms || 0)).filter((value) => value >= 0);
  const p95 = latencies.length ? percentile(latencies, 0.95) : Number(summary.latency_ms_p95 || 0);
  const latest = latestRecord(records);
  const rate = providerRateReadiness(summary.rate_limits || {});
  const state = providerReadinessState({ calls, active, errors, p95, latest, rateState: rate.state });
  return {
    provider,
    label: providerLabel(provider),
    color: COLORS[provider] || groupColor(provider),
    calls,
    active,
    errors,
    successRate: calls ? successes / calls : Number(summary.success_rate || 0),
    p95,
    state: state.state,
    badge: state.badge,
    model: readinessModelLabel(latest, summary),
    rateLabel: rate.label,
    lastSeen: latest ? `last ${formatTime(Number(latest.ended_at || latest.started_at || 0))}` : "no traffic",
    status: readinessStatusLabel(latest),
    action: providerReadinessAction({ provider, calls, active, errors, p95, latest, rateState: rate.state, state: state.state }),
  };
}

function latestRecord(records) {
  return (records || [])
    .slice()
    .sort((a, b) => Number(b.ended_at || b.started_at || 0) - Number(a.ended_at || a.started_at || 0))[0] || null;
}

function providerRateReadiness(limits) {
  const requestMetric = rateMetric(limits, "requests");
  const tokenMetric = rateMetric(limits, "tokens");
  const retryAfter = limits.retry_after || "";
  const metrics = [requestMetric, tokenMetric].filter(Boolean);
  const state = rateState(metrics, retryAfter);
  return {
    state,
    label: rateStateLabel(state),
  };
}

function providerReadinessState({ calls, active, errors, p95, latest, rateState }) {
  if (errors > 0 || (latest && isErrorRecord(latest))) return { state: "failing", badge: "fix" };
  if (active > 0) return { state: "live", badge: "live" };
  if (!calls) return { state: "silent", badge: "silent" };
  if (rateState === "blocked" || rateState === "tight") return { state: "watch", badge: "limit" };
  if (p95 >= 60_000) return { state: "watch", badge: "slow" };
  return { state: "ready", badge: "ready" };
}

function readinessModelLabel(latest, summary) {
  if (latest?.model) return latest.display_label || latest.label || latest.model;
  return topModelLabel(summary.models);
}

function readinessStatusLabel(latest) {
  if (!latest) return "status unknown";
  const status = latest.final_status || latest.upstream_status || (latest.active ? "active" : "done");
  if (latest.error) return `error ${status}`;
  return `status ${status}`;
}

function providerReadinessAction({ provider, calls, active, errors, p95, latest, rateState, state }) {
  if (state === "failing") {
    const error = String(latest?.error || "").toLowerCase();
    if (error.includes("prefill")) return "Strip assistant prefill before retrying Claude-family models.";
    if (error.includes("unsupported")) return "Check model parameters; upstream rejected this shape.";
    if (error.includes("auth") || error.includes("unauthor")) return "Refresh provider auth before routing more traffic.";
    return `Inspect the latest ${providerLabel(provider)} failure and rerun a smoke prompt.`;
  }
  if (active > 0) return "Live traffic is in flight. Watch stream and completion timing.";
  if (!calls) return `Send a small ${providerLabel(provider)} smoke prompt before trusting this lane.`;
  if (rateState === "blocked" || rateState === "tight") return "Rate headroom is tight. Reroute or slow callers.";
  if (p95 >= 60_000) return "Latency is high. Check tier choice before blaming the proxy.";
  if (provider === "fusion") return "Fusion path is available; verify panel and synthesizer timings after changes.";
  return "Ready based on recent telemetry. Leave this alone until it earns trouble.";
}

function providerRunwayRow(provider, item, timeseries) {
  const points = (timeseries || []).filter((point) => point.provider === provider);
  const halves = splitProviderPoints(points);
  const early = summarizeProviderPoints(halves.early);
  const recent = summarizeProviderPoints(halves.recent);
  const requests = Number(item.requests || 0);
  const errors = Number(item.errors || 0);
  const usage = item.usage || emptyUsage();
  const cache = item.cache || emptyCache();
  const latencyTrend = trendDelta(recent.avgLatency, early.avgLatency);
  const errorTrend = trendDelta(recent.errorRate, early.errorRate);
  const tokenTrend = trendDelta(recent.tokens, early.tokens);
  const severity = providerRunwaySeverity({ requests, errors, latencyTrend, errorTrend, p95: Number(item.latency_ms_p95 || 0) });
  return {
    provider,
    label: providerLabel(provider),
    color: COLORS[provider] || groupColor(provider),
    requests,
    p95: Number(item.latency_ms_p95 || 0),
    cacheRatio: Number(cache.hit_ratio || 0),
    latencyTrend,
    errorTrend,
    tokenTrend,
    latencyText: trendText(latencyTrend, "latency"),
    errorText: trendText(errorTrend, "errors"),
    tokenText: trendText(tokenTrend, "tokens"),
    severity,
    badge: runwayBadge(severity, requests),
    summary: runwaySummary({ provider, requests, errors, usage, early, recent, severity }),
  };
}

function splitProviderPoints(points) {
  if (!points.length) return { early: [], recent: [] };
  const sorted = points.slice().sort((a, b) => Number(a.t || 0) - Number(b.t || 0));
  const midpoint = Math.max(1, Math.floor(sorted.length / 2));
  return {
    early: sorted.slice(0, midpoint),
    recent: sorted.slice(midpoint),
  };
}

function summarizeProviderPoints(points) {
  const latencies = points.map((point) => Number(point.duration_ms || 0)).filter((value) => value > 0);
  const errors = points.filter((point) => point.ok === false || Number(point.status || 0) >= 400).length;
  const tokens = points.reduce((sum, point) => sum + Number(point.tokens || 0), 0);
  return {
    calls: points.length,
    errors,
    errorRate: points.length ? errors / points.length : 0,
    avgLatency: latencies.length ? latencies.reduce((sum, value) => sum + value, 0) / latencies.length : 0,
    tokens,
  };
}

function trendDelta(recent, early) {
  const oldValue = Number(early || 0);
  const newValue = Number(recent || 0);
  if (oldValue <= 0 && newValue <= 0) return 0;
  if (oldValue <= 0) return 1;
  return clamp((newValue - oldValue) / oldValue, -1, 1);
}

function trendText(delta, label) {
  if (Math.abs(delta) < 0.08) return `${label} flat`;
  const direction = delta > 0 ? "up" : "down";
  return `${label} ${direction} ${Math.abs(delta * 100).toFixed(0)}%`;
}

function providerRunwaySeverity({ requests, errors, latencyTrend, errorTrend, p95 }) {
  if (!requests) return "idle";
  if (errors > 0 || errorTrend > 0.2) return "error";
  if (p95 >= 60_000 || latencyTrend > 0.35) return "warning";
  if (latencyTrend < -0.2 && errorTrend <= 0) return "improving";
  return "healthy";
}

function runwayBadge(severity, requests) {
  if (!requests) return "idle";
  return {
    error: "degraded",
    warning: "watch",
    improving: "improving",
    healthy: "steady",
  }[severity] || "watch";
}

function runwaySummary({ provider, requests, errors, usage, early, recent, severity }) {
  if (!requests) return "No traffic in this window.";
  if (severity === "error") return `${formatNumber(errors)} errors; inspect ${providerLabel(provider)} auth, model, and upstream status.`;
  if (severity === "warning") return `Recent latency is heavier than the first half of the window.`;
  if (severity === "improving") return `Recent half is cleaner; leave the fix alone unless it gets cute.`;
  return `${formatCompact(usage.total_tokens)} tokens through a stable lane.`;
}

function runwayBar(label, delta, text, color) {
  const width = Math.max(6, Math.min(100, Math.abs(delta) * 100));
  const direction = delta > 0.08 ? "up" : delta < -0.08 ? "down" : "flat";
  return `
    <div class="runway-bar ${direction}">
      <span>${escapeHtml(label)}</span>
      <i><b style="width:${width}%; --runway-color:${color}"></b></i>
      <em>${escapeHtml(text)}</em>
    </div>`;
}

function providerPostureRow(provider, item) {
  const usage = item.usage || emptyUsage();
  const cache = item.cache || emptyCache();
  const requests = Number(item.requests || 0);
  const active = Number(item.active || 0);
  const errors = Number(item.errors || 0);
  const p95 = Number(item.latency_ms_p95 || 0);
  const state = providerState({ requests, active, errors, p95 });
  return {
    provider,
    label: providerLabel(provider),
    color: COLORS[provider] || groupColor(provider),
    requests,
    active,
    errors,
    errorRate: requests ? errors / requests : 0,
    cacheRatio: Number(cache.hit_ratio || 0),
    cacheRead: Number(cache.read_tokens || 0),
    p95,
    avg: Number(item.latency_ms_avg || 0),
    tokens: Number(usage.total_tokens || 0),
    topModel: topModelLabel(item.models),
    rate: rateLimitSummary(item.rate_limits || {}),
    state: state.label,
    severity: state.severity,
  };
}

function providerState({ requests, active, errors, p95 }) {
  if (errors > 0) return { label: "Error", severity: "error" };
  if (p95 >= 60_000) return { label: "Slow", severity: "warning" };
  if (active > 0) return { label: "Live", severity: "warning" };
  if (requests > 0) return { label: "Healthy", severity: "healthy" };
  return { label: "Idle", severity: "idle" };
}

function topModelLabel(models) {
  const [model, count] = Object.entries(models || {})[0] || [];
  if (!model) return "no model traffic";
  return `${model} - ${formatNumber(count)} call${Number(count) === 1 ? "" : "s"}`;
}

function rateLimitSummary(limits) {
  const entries = Object.entries(limits || {}).filter(([key]) => key !== "status" && limits[key] != null && limits[key] !== "");
  if (!entries.length) return "unknown";
  const priority = ["remaining_tokens", "remaining_requests", "reset_tokens", "reset_requests"];
  const sorted = entries.sort((a, b) => {
    const ai = priority.indexOf(a[0]);
    const bi = priority.indexOf(b[0]);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });
  return sorted.slice(0, 2).map(([key, value]) => `${key.replaceAll("_", " ")} ${value}`).join(" - ");
}

function parseLimitNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const cleaned = String(value).replaceAll(",", "").trim();
  if (!/^-?\d+(\.\d+)?$/.test(cleaned)) return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function rateMetric(limits, kind) {
  const remaining = parseLimitNumber(limits[`remaining_${kind}`]);
  const limit = parseLimitNumber(limits[`limit_${kind}`]);
  if (remaining === null || limit === null || limit <= 0) return null;
  return {
    kind,
    remaining,
    limit,
    ratio: Math.max(0, Math.min(1, remaining / limit)),
    reset: limits[`reset_${kind}`] || "",
  };
}

function rateState(metrics, retryAfter) {
  if (!metrics.length) return retryAfter ? "tight" : "unknown";
  const lowest = Math.min(...metrics.map((metric) => metric.ratio));
  if (retryAfter || lowest <= 0) return "blocked";
  if (lowest < 0.1) return "tight";
  if (lowest < 0.25) return "watch";
  return "healthy";
}

function rateStateLabel(state) {
  return {
    healthy: "healthy",
    watch: "watch",
    tight: "tight",
    blocked: "blocked",
    unknown: "unknown",
  }[state] || "unknown";
}

function rateSummary(metrics, retryAfter) {
  if (retryAfter) return `retry after ${retryAfter}`;
  if (!metrics.length) return "headers unavailable";
  return metrics
    .map((metric) => `${formatPct(metric.ratio)} ${metric.kind} headroom`)
    .join(" / ");
}

function rateOperatorAction(state, metrics) {
  if (state === "blocked") return "Back off or reroute this provider.";
  if (state === "tight") return "Near limit. Move traffic or slow callers.";
  if (state === "watch") return "Watch burn rate before long runs.";
  if (state === "healthy") return "Enough headroom for current traffic.";
  if (metrics.length) return "Partial headers only. Keep observing.";
  return "Provider did not expose useful limit headers.";
}

function rateBar(metric) {
  if (!metric) {
    return `
      <div class="rate-bar empty">
        <span>unknown</span>
        <i><b style="width:0%"></b></i>
        <em>no header</em>
      </div>`;
  }
  const width = `${Math.round(metric.ratio * 100)}%`;
  const reset = metric.reset ? ` reset ${escapeHtml(metric.reset)}` : "";
  return `
    <div class="rate-bar ${metric.ratio < 0.25 ? "low" : "ok"}">
      <span>${escapeHtml(metric.kind)}</span>
      <i><b style="width:${width}"></b></i>
      <em>${formatCompact(metric.remaining)} / ${formatCompact(metric.limit)}${reset}</em>
    </div>`;
}

function rateLimitCard(provider, providerSummary) {
  const limits = providerSummary.rate_limits || { status: "unknown" };
  const requestMetric = rateMetric(limits, "requests");
  const tokenMetric = rateMetric(limits, "tokens");
  const metrics = [requestMetric, tokenMetric].filter(Boolean);
  const retryAfter = limits.retry_after || "";
  const state = rateState(metrics, retryAfter);
  const hasHeaders = metrics.length > 0 || retryAfter;
  return `
    <article class="rate-headroom-card ${state}">
      <div class="rate-headroom-head">
        <div>
          <strong>${escapeHtml(providerLabel(provider))}</strong>
          <span>${escapeHtml(rateSummary(metrics, retryAfter))}</span>
        </div>
        <em>${escapeHtml(rateStateLabel(state))}</em>
      </div>
      <div class="rate-headroom-bars">
        ${rateBar(requestMetric)}
        ${rateBar(tokenMetric)}
      </div>
      <p>${escapeHtml(rateOperatorAction(state, metrics))}</p>
      ${hasHeaders ? "" : '<small>No upstream rate-limit headers seen for this provider yet.</small>'}
    </article>`;
}

function renderRateLimits(providers, note) {
  const target = $("rate-limits");
  if (!target) return;
  target.innerHTML = PROVIDERS
    .map((provider) => rateLimitCard(provider, providers[provider] || {}))
    .join("");
  setText("rate-note", note || "Only shown when upstream headers expose them.");
}

function phaseRank(phase) {
  return { panel: 0, synthesizer: 1 }[phase] ?? 9;
}

function renderFusionRuns(runs) {
  const target = $("fusion-runs");
  if (!target) return;
  if (!runs.length) {
    target.innerHTML = '<div class="empty-state">Fusion traces will appear here with private panel rows and the final synthesizer row.</div>';
    return;
  }
  target.innerHTML = runs.slice(0, 8).map((run) => {
    const usage = run.usage || {};
    const cache = run.cache || {};
    const status = run.active ? `${formatNumber(run.active)} live` : (run.ok ? "complete" : `${formatNumber(run.errors)} errors`);
    const calls = (run.calls || []).slice().sort((a, b) => phaseRank(a.phase) - phaseRank(b.phase));
    const rows = calls.map((call) => fusionCallRow(call)).join("");
    return `
      <div class="fusion-run">
        <div class="fusion-run-head">
          <div>
            <strong>Run ${escapeHtml(String(run.run_id || "").slice(0, 10))}</strong>
            <span>${formatTime(run.started_at)} - ${formatMs(run.duration_ms)} - ${formatCompact(usage.total_tokens)} tokens - ${formatPct(cache.hit_ratio)} cache</span>
          </div>
          <div class="fusion-run-meta">
            <span class="fusion-run-status ${run.ok ? "ok" : "error"}">${escapeHtml(status)}</span>
            ${run.slowest_label ? `<span class="fusion-slow">slowest: ${escapeHtml(run.slowest_label)}</span>` : ""}
          </div>
        </div>
        <div class="fusion-run-metrics">
          ${statTile("Input", formatCompact(usage.input_tokens))}
          ${statTile("Output", formatCompact(usage.output_tokens))}
          ${statTile("Cache read", formatCompact(cache.read_tokens))}
          ${statTile("Cache write", formatCompact(cache.write_tokens))}
        </div>
        <div class="fusion-call-list">${rows}</div>
      </div>`;
  }).join("");
}

function fusionCallRow(call) {
  const usage = call.usage || {};
  const cache = call.cache || {};
  const limits = call.rate_limits || {};
  const status = call.active ? "live" : (call.ok ? "ok" : "error");
  const upstream = call.upstream_provider ? providerLabel(call.upstream_provider) : providerLabel(call.provider);
  const limitText = limits.remaining_tokens ? `${limits.remaining_tokens} tok left` : (limits.remaining_requests ? `${limits.remaining_requests} req left` : "limits unknown");
  return `
    <div class="fusion-call ${escapeHtml(call.phase || "call")}">
      <div class="fusion-call-head">
        <span class="fusion-phase ${escapeHtml(call.phase || "call")}">${escapeHtml(call.phase || "call")}</span>
        <strong>${escapeHtml(call.display_label || call.model || "unknown model")}</strong>
        <span class="fusion-call-status ${status}">${escapeHtml(status)}</span>
      </div>
      <div class="fusion-call-metrics">
        <span>${escapeHtml(upstream)}</span>
        <span>${formatMs(call.duration_ms)}</span>
        <span>${formatCompact(usage.total_tokens)} tok</span>
        <span>${formatCompact(usage.input_tokens)} in</span>
        <span>${formatCompact(usage.output_tokens)} out</span>
        <span>${formatPct(cache.hit_ratio)} cache</span>
        <span>${escapeHtml(limitText)}</span>
      </div>
      ${call.error ? `<div class="fusion-error">${escapeHtml(call.error)}</div>` : ""}
    </div>`;
}

function renderRequests(id, requests, active) {
  const target = $(id);
  if (!target) return;
  if (!requests.length) {
    target.innerHTML = `<div class="empty-state">${active ? "No active model calls." : "No completed calls yet."}</div>`;
    return;
  }
  const rows = requests.slice(0, active ? 12 : 18);
  const maxTokens = Math.max(...rows.map((request) => Number((request.usage || {}).total_tokens || 0)), 1);
  target.innerHTML = `
    <div class="request-list-head request-list-row">
      <span>Route</span><span>State</span><span>Tokens</span><span>Cache</span><span>Latency</span><span>Started</span>
    </div>
    ${rows.map((request) => {
    const usage = request.usage || {};
    const cache = request.cache || {};
    const status = request.final_status || request.upstream_status || (request.active ? "live" : "done");
    const label = request.display_label || request.label || request.model || "unknown model";
    const detail = request.label && request.model ? `${request.model} - ` : "";
    const upstream = request.upstream_provider ? ` - ${providerLabel(request.upstream_provider)}` : "";
    const rowState = requestRowState(request);
    const statusState = statusStateFor(request);
    const tokens = Number(usage.total_tokens || 0);
    return `
      <details class="request-row ${rowState}">
        <summary class="request-list-row">
          <div class="request-route">
            <span class="badge ${escapeHtml(request.provider)}">${escapeHtml(request.provider)}</span>
            <div class="request-main">
              <strong>${escapeHtml(label)}${phaseChip(request.phase)}</strong>
              <span>${escapeHtml(detail)}${escapeHtml(request.operation || "request")}${escapeHtml(upstream)}</span>
            </div>
          </div>
          <span>${statusPill(status, statusState)}</span>
          <span class="bar-stat request-token-bar"><i style="width:${Math.max(4, Math.min(100, (tokens / maxTokens) * 100))}%"></i><b>${formatCompact(tokens)}</b></span>
          <span>${formatPct(cache.hit_ratio)}</span>
          <span>${formatMs(request.duration_ms)}</span>
          <span>${formatTime(request.started_at)}</span>
        </summary>
        ${requestDetails(request)}
      </details>`;
  }).join("")}`;
}

function requestRowState(request) {
  if (request.ok === false || request.error) return "error";
  if (request.active) return "live";
  if (Number(request.duration_ms || 0) >= 60_000) return "warning";
  return "";
}

function statusStateFor(request) {
  if (request.ok === false || request.error) return "error";
  if (request.active) return "live";
  const status = Number(request.final_status || request.upstream_status || 0);
  if (status >= 500) return "error";
  if (status >= 400) return "warning";
  return "ok";
}

function statusPill(status, state) {
  return `<span class="status-pill ${escapeHtml(state || "neutral")}">${escapeHtml(String(status || "-"))}</span>`;
}

function phaseChip(phase) {
  return phase ? ` <em class="phase-chip ${escapeHtml(phase)}">${escapeHtml(phase)}</em>` : "";
}

function requestDetails(request) {
  const usage = request.usage || {};
  const cache = request.cache || {};
  const stream = request.stream || {};
  const rateLimits = request.rate_limits || {};
  const rateLimitText = Object.entries(rateLimits)
    .filter(([key]) => key !== "status")
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`)
    .join(" | ") || (rateLimits.status || "unknown");
  return `
    <div class="request-details">
      <div class="detail-grid">
        ${detailCell("Request", String(request.id || "").slice(0, 12))}
        ${detailCell("Provider", providerLabel(request.provider))}
        ${detailCell("Upstream", request.upstream_provider ? providerLabel(request.upstream_provider) : "-")}
        ${detailCell("Model", request.model || "unknown")}
        ${detailCell("Phase", request.phase || "-")}
        ${detailCell("Started", formatTime(request.started_at))}
        ${detailCell("Path", request.path || "-")}
        ${detailCell("Final", request.final_status || "-")}
        ${detailCell("Upstream status", request.upstream_status || "-")}
        ${detailCell("Input", formatCompact(usage.input_tokens))}
        ${detailCell("Output", formatCompact(usage.output_tokens))}
        ${detailCell("Reasoning", formatCompact(usage.reasoning_tokens))}
        ${detailCell("Total", formatCompact(usage.total_tokens))}
        ${detailCell("Cache read", formatCompact(cache.read_tokens))}
        ${detailCell("Cache write", formatCompact(cache.write_tokens))}
        ${detailCell("Cache ratio", formatPct(cache.hit_ratio))}
        ${detailCell("Chunks", formatNumber(stream.chunks || 0))}
        ${detailCell("Text", `${formatCompact(stream.text_chars || 0)} chars`)}
        ${detailCell("Rate limits", rateLimitText, "detail-wide")}
      </div>
      ${request.content_preview ? `<pre class="request-detail-preview">${escapeHtml(request.content_preview)}</pre>` : ""}
      ${request.error ? `<div class="detail-error">${escapeHtml(request.error)}</div>` : ""}
    </div>`;
}

function detailCell(label, value, className = "") {
  return `<div class="detail-cell ${escapeHtml(className)}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function renderGroupPressure(recent, active) {
  const group = selectedGroup();
  const rows = groupRows(recent, active);
  const title = $("group-title");
  const meta = $("group-meta");
  const target = $("group-pressure");
  if (title) title.textContent = `Pressure by ${group.label.toLowerCase()}`;
  if (meta) meta.textContent = `${group.label.toLowerCase()} lens`;
  drawGroupChart($("group-chart"), rows);
  if (!target) return;
  if (!rows.length) {
    target.innerHTML = '<div class="empty-state">Grouped pressure appears after traffic hits the proxy.</div>';
    return;
  }
  const maxTokens = Math.max(...rows.map((row) => row.tokens), 1);
  target.innerHTML = `
    <div class="list-head group-pressure-row">
      <span>${escapeHtml(group.label)}</span><span>Calls</span><span>Errors</span><span>Active</span><span>Tokens</span><span>Cache</span><span>Avg</span><span>Latest</span>
    </div>
    ${rows.slice(0, 12).map((row) => {
      const state = row.errors ? "error" : row.active ? "warning" : "";
      return `
        <div class="list-row group-pressure-row ${state}">
          <strong class="group-name" title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</strong>
          <span>${formatNumber(row.calls)}</span>
          <span>${formatNumber(row.errors)}</span>
          <span>${formatNumber(row.active)}</span>
          <span class="bar-stat"><i style="width:${Math.max(4, Math.min(100, (row.tokens / maxTokens) * 100))}%; background:${row.color}55"></i><b>${formatCompact(row.tokens)}</b></span>
          <span>${formatPct(row.cacheRatio)}</span>
          <span>${formatMs(row.avgLatency)}</span>
          <span>${formatTime(row.latest)}</span>
        </div>`;
    }).join("")}`;
}

function groupRows(recent, active) {
  const grouped = new Map();
  for (const request of [...(active || []), ...(recent || [])]) {
    const group = requestGroup(request);
    const usage = request.usage || {};
    const cache = request.cache || {};
    const item = grouped.get(group.key) || {
      key: group.key,
      label: group.label,
      color: group.color,
      calls: 0,
      errors: 0,
      active: 0,
      tokens: 0,
      inputTokens: 0,
      outputTokens: 0,
      cacheRead: 0,
      cacheBase: 0,
      latencies: [],
      latest: 0,
    };
    item.calls += 1;
    item.errors += isErrorRecord(request) ? 1 : 0;
    item.active += request.active ? 1 : 0;
    item.tokens += Number(usage.total_tokens || 0);
    item.inputTokens += Number(usage.input_tokens || 0);
    item.outputTokens += Number(usage.output_tokens || 0);
    item.cacheRead += Number(cache.read_tokens || 0);
    item.cacheBase += Number(usage.input_tokens || 0) + Number(cache.read_tokens || 0) + Number(cache.write_tokens || 0);
    if (!request.active) item.latencies.push(Number(request.duration_ms || 0));
    item.latest = Math.max(item.latest, Number(request.ended_at || request.started_at || 0));
    grouped.set(group.key, item);
  }

  return Array.from(grouped.values()).map((item) => ({
    ...item,
    cacheRatio: item.cacheBase ? item.cacheRead / item.cacheBase : 0,
    avgLatency: item.latencies.length ? item.latencies.reduce((sum, value) => sum + value, 0) / item.latencies.length : 0,
    p95Latency: percentile(item.latencies, 0.95),
  })).sort((a, b) => (
    b.errors - a.errors
    || b.active - a.active
    || b.tokens - a.tokens
    || b.calls - a.calls
    || b.latest - a.latest
    || a.label.localeCompare(b.label)
  ));
}

function requestGroup(request) {
  const dimension = selectedGroupValue;
  let raw = "unknown";
  let label = "Unknown";
  if (dimension === "provider") {
    raw = request.provider || "unknown";
    label = providerLabel(raw);
  } else if (dimension === "upstream") {
    raw = request.upstream_provider || request.provider || "unknown";
    label = providerLabel(raw);
  } else if (dimension === "model") {
    raw = request.display_label || request.label || request.model || "unknown model";
    label = raw;
  } else if (dimension === "phase") {
    raw = request.phase || (request.provider === "fusion" ? "fusion-envelope" : "direct");
    label = raw === "fusion-envelope" ? "Fusion envelope" : raw;
  } else if (dimension === "tier") {
    raw = request.tier || "unknown";
    label = raw;
  } else if (dimension === "plan") {
    raw = request.plan || "unknown";
    label = raw;
  } else if (dimension === "status") {
    raw = request.final_status || request.upstream_status || (request.active ? "active" : "unknown");
    label = String(raw);
  } else if (dimension === "none") {
    raw = "all";
    label = "All traffic";
  }
  return {
    key: `${dimension}:${raw}`,
    label,
    color: groupColor(raw),
  };
}

function groupColor(value) {
  if (COLORS[value]) return COLORS[value];
  const text = String(value || "unknown");
  let hash = 0;
  for (let index = 0; index < text.length; index += 1) {
    hash = ((hash << 5) - hash) + text.charCodeAt(index);
    hash |= 0;
  }
  return PALETTE[Math.abs(hash) % PALETTE.length];
}

function drawGroupChart(canvas, rows) {
  if (!canvas) return;
  const ctx = scaleCanvas(canvas);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const plot = { left: 96, right: 18, top: 18, bottom: 24 };
  ctx.clearRect(0, 0, width, height);
  ctx.save();
  ctx.font = "10px JetBrains Mono, Cascadia Code, monospace";
  ctx.textBaseline = "middle";

  const visible = (rows || []).slice(0, 8);
  if (!visible.length) {
    ctx.fillStyle = "rgba(146,160,184,0.72)";
    ctx.textAlign = "center";
    ctx.fillText("No grouped traffic in this window", width / 2, height / 2);
    ctx.restore();
    return;
  }

  const maxValue = Math.max(...visible.map((row) => Math.max(row.tokens, row.calls)), 1);
  const rowHeight = (height - plot.top - plot.bottom) / visible.length;
  for (let i = 0; i <= 4; i += 1) {
    const x = plot.left + ((width - plot.left - plot.right) / 4) * i;
    const value = (maxValue / 4) * i;
    ctx.strokeStyle = "rgba(255,255,255,0.055)";
    ctx.beginPath();
    ctx.moveTo(x, plot.top);
    ctx.lineTo(x, height - plot.bottom);
    ctx.stroke();
    ctx.fillStyle = "rgba(146,160,184,0.66)";
    ctx.textAlign = i === 0 ? "left" : "center";
    ctx.fillText(formatCompact(value), x, height - 9);
  }

  visible.forEach((row, index) => {
    const y = plot.top + (rowHeight * index) + (rowHeight / 2);
    const value = Math.max(row.tokens, row.calls);
    const barWidth = ((width - plot.left - plot.right) * value) / maxValue;
    ctx.fillStyle = "rgba(146,160,184,0.74)";
    ctx.textAlign = "right";
    ctx.fillText(truncateLabel(row.label, 13), plot.left - 10, y);

    const gradient = ctx.createLinearGradient(plot.left, y, plot.left + barWidth, y);
    gradient.addColorStop(0, `${row.color}99`);
    gradient.addColorStop(1, `${row.color}22`);
    ctx.fillStyle = gradient;
    ctx.fillRect(plot.left, y - Math.max(5, rowHeight * 0.24), Math.max(2, barWidth), Math.max(10, rowHeight * 0.48));

    ctx.fillStyle = row.errors ? "#ff9c96" : "rgba(231,237,247,0.9)";
    ctx.textAlign = "left";
    const suffix = row.tokens ? `${formatCompact(row.tokens)} tok` : `${formatNumber(row.calls)} calls`;
    ctx.fillText(suffix, plot.left + barWidth + 8, y);
  });
  ctx.restore();
}

function truncateLabel(value, length) {
  const text = String(value || "");
  return text.length > length ? `${text.slice(0, Math.max(0, length - 3))}...` : text;
}

function renderModelLeaderboard(requests) {
  const target = $("model-leaderboard");
  if (!target) return;
  const rows = modelRows(requests);
  if (!rows.length) {
    target.innerHTML = '<div class="empty-state">Model stats will appear after completed calls.</div>';
    return;
  }
  target.innerHTML = `
    <div class="list-head model-row">
      <span>Model</span><span>Provider</span><span>Calls</span><span>Tokens</span><span>Cache</span><span>Avg</span><span>p95</span>
    </div>
    ${rows.slice(0, 12).map((row) => `
      <div class="list-row model-row">
        <strong>${escapeHtml(row.model)}</strong>
        <span>${escapeHtml(providerLabel(row.provider))}</span>
        <span>${formatNumber(row.calls)}</span>
        <span class="bar-stat"><i style="width:${Math.max(4, Math.min(100, row.tokenShare * 100))}%"></i><b>${formatCompact(row.tokens)}</b></span>
        <span>${formatPct(row.cacheRatio)}</span>
        <span>${formatMs(row.avgLatency)}</span>
        <span>${formatMs(row.p95Latency)}</span>
      </div>`).join("")}`;
}

function modelRows(requests) {
  const grouped = new Map();
  for (const request of requests || []) {
    const model = request.display_label || request.label || request.model || "unknown model";
    const provider = request.upstream_provider || request.provider || "unknown";
    const key = `${provider}:${model}`;
    const usage = request.usage || {};
    const cache = request.cache || {};
    const item = grouped.get(key) || {
      model,
      provider,
      calls: 0,
      tokens: 0,
      cacheRead: 0,
      cacheBase: 0,
      latencies: [],
    };
    item.calls += 1;
    item.tokens += Number(usage.total_tokens || 0);
    item.cacheRead += Number(cache.read_tokens || 0);
    item.cacheBase += Number(usage.input_tokens || 0) + Number(cache.read_tokens || 0) + Number(cache.write_tokens || 0);
    item.latencies.push(Number(request.duration_ms || 0));
    grouped.set(key, item);
  }
  const rows = Array.from(grouped.values()).map((item) => ({
    ...item,
    cacheRatio: item.cacheBase ? item.cacheRead / item.cacheBase : 0,
    avgLatency: item.latencies.length ? item.latencies.reduce((sum, value) => sum + value, 0) / item.latencies.length : 0,
    p95Latency: percentile(item.latencies, 0.95),
  })).sort((a, b) => b.tokens - a.tokens || b.calls - a.calls);
  const maxTokens = Math.max(...rows.map((row) => row.tokens), 1);
  return rows.map((row) => ({ ...row, tokenShare: row.tokens / maxTokens }));
}

function percentile(values, percentileValue) {
  if (!values.length) return 0;
  const sorted = values.slice().sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * percentileValue) - 1));
  return sorted[index];
}

function renderIssueQueue(recent, active) {
  const target = $("issue-queue");
  if (!target) return;
  const rows = issueRows(recent, active).slice(0, 14);
  if (!rows.length) {
    target.innerHTML = '<div class="empty-state">No errors or slow calls in the current telemetry buffer.</div>';
    return;
  }
  target.innerHTML = `
    <div class="list-head issue-row">
      <span>Type</span><span>Provider</span><span>Model</span><span>Status</span><span>Latency</span>
    </div>
    ${rows.map(({ type, request }) => {
      const status = request.final_status || request.upstream_status || (request.active ? "live" : "-");
      const rowState = type === "Error" ? "error" : "warning";
      return `
        <details class="list-row issue-row ${rowState}">
          <summary>
            <span>${escapeHtml(type)}</span>
            <span>${escapeHtml(providerLabel(request.upstream_provider || request.provider))}</span>
            <strong>${escapeHtml(request.display_label || request.label || request.model || "unknown model")}</strong>
            ${statusPill(status, statusStateFor(request))}
            <span>${formatMs(request.duration_ms)}</span>
          </summary>
          ${requestDetails(request)}
        </details>`;
    }).join("")}`;
}

function issueRows(recent, active) {
  const rows = [];
  const seen = new Set();
  const add = (type, request, rank) => {
    const id = request.id || `${type}:${request.provider}:${request.model}:${request.started_at}`;
    if (seen.has(id)) return;
    seen.add(id);
    rows.push({ type, request, rank });
  };
  for (const request of active || []) {
    if (Number(request.duration_ms || 0) >= 30_000) add("Slow active", request, 80 + Number(request.duration_ms || 0));
  }
  for (const request of recent || []) {
    if (request.ok === false || request.error) add("Error", request, 1000 + Number(request.duration_ms || 0));
  }
  for (const request of recent || []) {
    if (Number(request.duration_ms || 0) >= 60_000) add("Slow", request, 60 + Number(request.duration_ms || 0));
  }
  return rows.sort((a, b) => b.rank - a.rank);
}

function renderLatencyDistribution(recent, active) {
  const records = [...(active || []), ...(recent || [])];
  const completed = records.filter((request) => !request.active && Number(request.duration_ms || 0) >= 0);
  const summary = $("latency-band-summary");
  if (summary) {
    const p50 = percentile(completed.map((request) => Number(request.duration_ms || 0)), 0.5);
    const p95 = percentile(completed.map((request) => Number(request.duration_ms || 0)), 0.95);
    const slow = completed.filter((request) => Number(request.duration_ms || 0) >= 60_000).length;
    summary.innerHTML = `
      ${latencyBandStat("Completed", formatNumber(completed.length))}
      ${latencyBandStat("p50", formatMs(p50))}
      ${latencyBandStat("p95", formatMs(p95), p95 >= 60_000 ? "warning" : "")}
      ${latencyBandStat("Slow", formatNumber(slow), slow ? "warning" : "")}
    `;
  }
  drawLatencyBandsChart($("latency-bands-chart"), completed);
}

function latencyBandStat(label, value, state = "") {
  return `
    <div class="latency-band-stat ${escapeHtml(state)}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>`;
}

function latencyBandRows(records) {
  const bands = [
    { id: "fast", label: "<1s", min: 0, max: 1_000, color: COLORS.codex },
    { id: "ok", label: "1-5s", min: 1_000, max: 5_000, color: COLORS.azure },
    { id: "warm", label: "5-15s", min: 5_000, max: 15_000, color: "#7ed321" },
    { id: "slow", label: "15-60s", min: 15_000, max: 60_000, color: COLORS.fusion },
    { id: "bad", label: ">60s", min: 60_000, max: Number.POSITIVE_INFINITY, color: COLORS.anthropic },
  ];
  return bands.map((band) => {
    const items = records.filter((request) => {
      const duration = Number(request.duration_ms || 0);
      return duration >= band.min && duration < band.max;
    });
    const errors = items.filter(isErrorRecord).length;
    const tokens = items.reduce((sum, request) => sum + Number((request.usage || {}).total_tokens || 0), 0);
    const topProvider = topValue(items.map((request) => request.upstream_provider || request.provider || "unknown"));
    return {
      ...band,
      calls: items.length,
      errors,
      tokens,
      topProvider,
      avg: items.length ? Math.round(items.reduce((sum, request) => sum + Number(request.duration_ms || 0), 0) / items.length) : 0,
    };
  });
}

function drawLatencyBandsChart(canvas, records) {
  if (!canvas) return;
  const ctx = scaleCanvas(canvas);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const plot = { left: 54, right: 18, top: 18, bottom: 32 };
  const rows = latencyBandRows(records);
  const maxCalls = Math.max(...rows.map((row) => row.calls), 1);
  const baseline = height - plot.bottom;
  const plotWidth = width - plot.left - plot.right;
  const barGap = 12;
  const barWidth = Math.max(22, (plotWidth - (barGap * (rows.length - 1))) / rows.length);

  ctx.clearRect(0, 0, width, height);
  ctx.save();
  ctx.font = "10px JetBrains Mono, Cascadia Code, monospace";
  ctx.textBaseline = "middle";

  for (let i = 0; i <= 4; i += 1) {
    const y = plot.top + ((baseline - plot.top) / 4) * i;
    const value = maxCalls - ((maxCalls / 4) * i);
    ctx.strokeStyle = i === 4 ? "rgba(255,255,255,0.16)" : "rgba(255,255,255,0.08)";
    ctx.beginPath();
    ctx.moveTo(plot.left, y);
    ctx.lineTo(width - plot.right, y);
    ctx.stroke();
    ctx.fillStyle = "rgba(146,160,184,0.75)";
    ctx.textAlign = "right";
    ctx.fillText(formatNumber(value), plot.left - 8, y);
  }

  const bars = rows.map((row, index) => {
    const x = plot.left + (index * (barWidth + barGap));
    const barHeight = Math.max(row.calls ? 3 : 1, (row.calls / maxCalls) * (baseline - plot.top));
    const y = baseline - barHeight;
    const gradient = ctx.createLinearGradient(0, y, 0, baseline);
    gradient.addColorStop(0, `${row.color}d9`);
    gradient.addColorStop(1, `${row.color}33`);
    ctx.fillStyle = gradient;
    ctx.strokeStyle = `${row.color}aa`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(x, y, barWidth, barHeight, 5);
    ctx.fill();
    ctx.stroke();
    if (row.errors) {
      ctx.fillStyle = "rgba(229,83,75,0.92)";
      ctx.fillRect(x, y, barWidth, Math.min(barHeight, Math.max(2, (row.errors / Math.max(row.calls, 1)) * barHeight)));
    }
    ctx.fillStyle = "rgba(146,160,184,0.78)";
    ctx.textAlign = "center";
    ctx.fillText(row.label, x + (barWidth / 2), height - 12);
    return { ...row, x, y, width: barWidth, height: barHeight, cx: x + (barWidth / 2) };
  });

  const hovered = latencyBandsHover ? bars.find((bar) => (
    latencyBandsHover.x >= bar.x
    && latencyBandsHover.x <= bar.x + bar.width
    && latencyBandsHover.y >= plot.top
    && latencyBandsHover.y <= baseline
  )) : null;
  if (hovered) {
    ctx.strokeStyle = "rgba(255,255,255,0.32)";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(hovered.cx, plot.top);
    ctx.lineTo(hovered.cx, baseline);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(plot.left, latencyBandsHover.y);
    ctx.lineTo(width - plot.right, latencyBandsHover.y);
    ctx.stroke();
    ctx.setLineDash([]);
    showLatencyBandsTooltip(hovered, width, height);
  } else {
    hideLatencyBandsTooltip();
  }

  ctx.restore();
  renderLatencyBandsLegend(rows);
}

function showLatencyBandsTooltip(row, width, height) {
  const tooltip = $("latency-bands-tooltip");
  if (!tooltip) return;
  tooltip.innerHTML = `
    <strong>${escapeHtml(row.label)} latency</strong>
    <div class="chart-tooltip-row"><span>Calls</span><b>${formatNumber(row.calls)}</b></div>
    <div class="chart-tooltip-row"><span>Errors</span><b>${formatNumber(row.errors)}</b></div>
    <div class="chart-tooltip-row"><span>Avg</span><b>${formatMs(row.avg)}</b></div>
    <div class="chart-tooltip-row"><span>Tokens</span><b>${formatCompact(row.tokens)}</b></div>
    <div class="chart-tooltip-row"><span>Top route</span><b>${escapeHtml(providerLabel(row.topProvider || "-"))}</b></div>
  `;
  tooltip.hidden = false;
  const box = tooltip.getBoundingClientRect();
  const left = clamp(row.cx + 14, 8, Math.max(8, width - box.width - 8));
  const top = clamp(row.y - box.height - 12, 8, Math.max(8, height - box.height - 8));
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function hideLatencyBandsTooltip() {
  const tooltip = $("latency-bands-tooltip");
  if (tooltip) tooltip.hidden = true;
}

function renderLatencyBandsLegend(rows) {
  const target = $("latency-bands-legend");
  if (!target) return;
  target.innerHTML = rows.map((row) => `
    <span class="legend-item" style="color:${row.color}">
      <i class="chart-dot"></i>
      <span>${escapeHtml(row.label)} ${formatNumber(row.calls)}</span>
    </span>`).join("");
}

function renderFailureTaxonomy(recent, active) {
  const target = $("failure-taxonomy");
  const count = $("failure-taxonomy-count");
  if (!target) return;
  const rows = failureTaxonomyRows(recent, active);
  if (count) count.textContent = `${formatNumber(rows.length)} group${rows.length === 1 ? "" : "s"}`;
  if (!rows.length) {
    target.innerHTML = '<div class="empty-state">No failure groups in this window. Suspiciously pleasant.</div>';
    return;
  }
  target.innerHTML = `
    <div class="list-head failure-row">
      <span>Route</span><span>Status</span><span>Errors</span><span>Worst</span><span>Signature</span>
    </div>
    ${rows.map((row) => `
      <div class="list-row failure-row ${escapeHtml(row.severity)}">
        <div class="route-model">
          <span class="badge ${escapeHtml(row.provider)}">${escapeHtml(row.provider)}</span>
          <strong title="${escapeHtml(row.model)}">${escapeHtml(row.model)}</strong>
        </div>
        ${statusPill(row.status, row.severity === "error" ? "error" : "warning")}
        <span>${formatNumber(row.errors)}</span>
        <span>${formatMs(row.worstLatency)}</span>
        <span title="${escapeHtml(row.signature)}">${escapeHtml(row.signature)}</span>
      </div>`).join("")}`;
}

function failureTaxonomyRows(recent, active) {
  const grouped = new Map();
  for (const request of [...(active || []), ...(recent || [])]) {
    if (!isErrorRecord(request)) continue;
    const provider = request.upstream_provider || request.provider || "unknown";
    const model = request.display_label || request.label || request.model || "unknown model";
    const status = request.final_status || request.upstream_status || (request.active ? "live" : "-");
    const signature = errorSignature(request);
    const key = `${provider}:${model}:${status}:${signature}`;
    const item = grouped.get(key) || {
      provider,
      model,
      status,
      signature,
      errors: 0,
      worstLatency: 0,
      severity: Number(status) >= 500 || request.error ? "error" : "warning",
    };
    item.errors += 1;
    item.worstLatency = Math.max(item.worstLatency, Number(request.duration_ms || 0));
    if (Number(status) >= 500 || request.error) item.severity = "error";
    grouped.set(key, item);
  }
  return Array.from(grouped.values())
    .sort((a, b) => b.errors - a.errors || b.worstLatency - a.worstLatency)
    .slice(0, 12);
}

function errorSignature(request) {
  const error = String(request.error || "");
  if (error) return error.slice(0, 80);
  const status = request.final_status || request.upstream_status;
  if (status) return `HTTP ${status}`;
  if (request.ok === false) return "proxy marked request not ok";
  return "unknown failure";
}

function renderFailureFingerprints(recent, active) {
  const summaryTarget = $("fingerprint-summary");
  const tableTarget = $("failure-fingerprints");
  if (!summaryTarget || !tableTarget) return;

  const rows = failureFingerprintRows(recent, active);
  const errorRows = rows.filter((row) => row.state === "error");
  const watchRows = rows.filter((row) => row.state === "warning" || row.state === "watch");
  const affectedRoutes = new Set(rows.flatMap((row) => row.routes));

  summaryTarget.innerHTML = [
    fingerprintSummaryCard("Fingerprints", formatNumber(rows.length), rows.length ? "Recurring incident shapes" : "Nothing repeating", rows.length ? "watch" : "ok"),
    fingerprintSummaryCard("Errors", formatNumber(errorRows.length), errorRows.length ? "Breaks user flow" : "No hard failures", errorRows.length ? "bad" : "ok"),
    fingerprintSummaryCard("Watch", formatNumber(watchRows.length), watchRows.length ? "Latency or stream risk" : "No soft incidents", watchRows.length ? "watch" : "ok"),
    fingerprintSummaryCard("Routes", formatNumber(affectedRoutes.size), affectedRoutes.size ? "Impacted lanes" : "No impacted lanes"),
  ].join("");

  if (!rows.length) {
    tableTarget.innerHTML = '<div class="empty-state">No incident fingerprints in this window. Enjoy the silence while it lasts.</div>';
    return;
  }

  tableTarget.innerHTML = `
    <div class="list-head fingerprint-row">
      <span>Fingerprint</span><span>State</span><span>Count</span><span>Impacted</span><span>Last seen</span><span>Sample</span><span>Likely move</span>
    </div>
    ${rows.map((row) => `
      <details class="list-row fingerprint-row ${escapeHtml(row.state)}">
        <summary>
          <div class="fingerprint-kind">
            <i style="--fingerprint-color:${groupColor(row.kind)}"></i>
            <strong>${escapeHtml(row.label)}</strong>
            <small>${escapeHtml(row.category)}</small>
          </div>
          ${statusPill(row.stateLabel, row.state === "error" ? "error" : row.state === "ok" ? "ok" : "warning")}
          <span>${formatNumber(row.count)}</span>
          <span title="${escapeHtml(row.impactTitle)}">${escapeHtml(row.impactLabel)}</span>
          <span>${formatTime(row.lastSeen)}</span>
          <span class="fingerprint-sample" title="${escapeHtml(row.sample)}">${escapeHtml(row.sample)}</span>
          <span class="fingerprint-action" title="${escapeHtml(row.action)}">${escapeHtml(row.action)}</span>
        </summary>
        <div class="fingerprint-detail">
          <div><b>Providers</b><span>${escapeHtml(row.providers.join(", ") || "-")}</span></div>
          <div><b>Models</b><span>${escapeHtml(row.models.join(", ") || "-")}</span></div>
          <div><b>Routes</b><span>${escapeHtml(row.routes.join(", ") || "-")}</span></div>
          <div><b>Evidence</b><span>${escapeHtml(row.evidence)}</span></div>
        </div>
      </details>`).join("")}`;
}

function fingerprintSummaryCard(label, value, detail, state = "") {
  return `
    <div class="fingerprint-card ${escapeHtml(state)}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(detail)}</small>
    </div>`;
}

function failureFingerprintRows(recent, active) {
  const grouped = new Map();
  for (const request of [...(active || []), ...(recent || [])]) {
    const fingerprint = failureFingerprint(request);
    if (!fingerprint) continue;

    const provider = providerLabel(request.upstream_provider || request.provider || "unknown");
    const model = request.display_label || request.label || request.model || "unknown model";
    const route = request.operation || request.route || request.path || "unknown route";
    const timestamp = Number(request.ended_at || request.started_at || 0);
    const key = fingerprint.kind;
    const item = grouped.get(key) || {
      ...fingerprint,
      count: 0,
      providers: new Set(),
      models: new Set(),
      routes: new Set(),
      samples: [],
      lastSeen: 0,
      worstLatency: 0,
      maxStatus: 0,
      active: 0,
    };

    item.count += 1;
    item.providers.add(provider);
    item.models.add(model);
    item.routes.add(route);
    if (fingerprint.sample) item.samples.push(fingerprint.sample);
    item.lastSeen = Math.max(item.lastSeen, timestamp);
    item.worstLatency = Math.max(item.worstLatency, Number(request.duration_ms || 0));
    item.maxStatus = Math.max(item.maxStatus, Number(request.final_status || request.upstream_status || 0));
    item.active += request.active ? 1 : 0;
    grouped.set(key, item);
  }

  return Array.from(grouped.values()).map((item) => {
    const providers = sortedLimited(item.providers, 4);
    const models = sortedLimited(item.models, 4);
    const routes = sortedLimited(item.routes, 4);
    const sample = topValue(item.samples) || item.sample || item.label;
    const impactTitle = [
      providers.length ? `Providers: ${providers.join(", ")}` : "",
      models.length ? `Models: ${models.join(", ")}` : "",
      routes.length ? `Routes: ${routes.join(", ")}` : "",
    ].filter(Boolean).join(" | ");

    return {
      ...item,
      providers,
      models,
      routes,
      sample,
      impactTitle,
      impactLabel: `${providers.length || 0} provider${providers.length === 1 ? "" : "s"} / ${routes.length || 0} route${routes.length === 1 ? "" : "s"}`,
      stateLabel: item.state === "error" ? "error" : item.state === "watch" ? "watch" : "warning",
      evidence: fingerprintEvidence(item),
    };
  }).sort((a, b) => (
    fingerprintRank(b) - fingerprintRank(a)
    || b.count - a.count
    || b.lastSeen - a.lastSeen
  )).slice(0, 10);
}

function failureFingerprint(request) {
  const error = String(request.error || "");
  const message = `${error} ${request.content_preview || ""}`.toLowerCase();
  const status = Number(request.final_status || request.upstream_status || 0);
  const duration = Number(request.duration_ms || 0);
  const stream = request.stream || {};
  const chunks = Number(stream.chunks || 0);
  const textChars = Number(stream.text_chars || 0) + Number(stream.tool_chars || 0) + Number(stream.reasoning_chars || 0);

  if (message.includes("assistant message prefill") || message.includes("conversation must end with a user message") || message.includes("prefill")) {
    return fingerprintDefinition("assistant_prefill", "Assistant prefill rejected", "Protocol", "error", errorSignature(request), "Strip trailing assistant prefill before routing Anthropic-style requests.");
  }
  if (message.includes("unsupported") || message.includes("unsupportedparam") || message.includes("rejected request parameters")) {
    return fingerprintDefinition("unsupported_params", "Unsupported parameters", "Provider contract", "error", errorSignature(request), "Normalize provider-specific params before invoking the upstream model.");
  }
  if (status === 401 || status === 403 || message.includes("unauthorized") || message.includes("invalid api key") || message.includes("auth")) {
    return fingerprintDefinition("auth_failure", "Auth or token failure", "Credentials", "error", errorSignature(request), "Refresh provider auth and verify the selected profile token path.");
  }
  if (status === 429 || message.includes("rate limit") || message.includes("too many requests")) {
    return fingerprintDefinition("rate_limited", "Rate limited", "Capacity", "warning", errorSignature(request), "Back off, rotate provider lane, or lower Fusion concurrency for this route.");
  }
  if (status >= 500 || message.includes("upstream") || message.includes("502") || message.includes("503")) {
    return fingerprintDefinition("upstream_error", "Upstream error", "Provider health", "error", errorSignature(request), "Check provider status and failover this model lane if repeats persist.");
  }
  if (duration >= 90_000) {
    return fingerprintDefinition("slow_call", "Slow call", "Latency", "watch", `${formatMs(duration)} duration`, "Inspect model tier, Fusion phase timing, and provider latency before blaming the UI.");
  }
  if (textChars >= 1600 && chunks <= Math.max(1, Number(request.active ? 0 : 1))) {
    return fingerprintDefinition("buffered_stream", "Buffered stream", "Streaming", "watch", `${formatNumber(textChars)} chars / ${formatNumber(chunks)} chunks`, "Confirm chunks pass through as they arrive; buffered streaming makes users think the thing died.");
  }
  if (isErrorRecord(request)) {
    return fingerprintDefinition("unknown_error", "Unknown error", "Unhandled", "warning", errorSignature(request), "Open the request detail and teach this dashboard what this new nonsense means.");
  }
  return null;
}

function fingerprintDefinition(kind, label, category, state, sample, action) {
  return { kind, label, category, state, sample, action };
}

function fingerprintEvidence(row) {
  const parts = [
    `${formatNumber(row.count)} hit${row.count === 1 ? "" : "s"}`,
    row.maxStatus ? `HTTP ${row.maxStatus}` : "",
    row.worstLatency ? `worst ${formatMs(row.worstLatency)}` : "",
    row.active ? `${formatNumber(row.active)} live` : "",
  ];
  return parts.filter(Boolean).join(" - ");
}

function sortedLimited(values, limit) {
  return Array.from(values || [])
    .filter(Boolean)
    .sort((a, b) => String(a).localeCompare(String(b)))
    .slice(0, limit);
}

function fingerprintRank(row) {
  const stateRank = { error: 3, warning: 2, watch: 1, ok: 0 }[row.state] || 0;
  return (stateRank * 1000) + row.count;
}

function topValue(values) {
  const counts = new Map();
  for (const value of values || []) {
    counts.set(value, (counts.get(value) || 0) + 1);
  }
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])[0]?.[0] || "";
}

function renderContentionMap(recent, active) {
  const table = $("contention-map");
  const actions = $("contention-actions");
  if (!table || !actions) return;

  const rows = contentionRows(recent, active);
  if (!rows.length) {
    table.innerHTML = '<div class="empty-state">Hot routes will appear once traffic hits the proxy.</div>';
    actions.innerHTML = `
      <div class="contention-empty">
        <strong>No pressure yet</strong>
        <span>Send GPT, Claude, or Fusion traffic through the proxy and this panel will rank the noisy routes.</span>
      </div>`;
    return;
  }

  const maxScore = Math.max(...rows.map((row) => row.score), 1);
  table.innerHTML = `
    <div class="list-head contention-row">
      <span>Route</span><span>Score</span><span>Calls</span><span>Errors</span><span>Active</span><span>Tokens</span><span>Cache</span><span>p95</span><span>Likely move</span>
    </div>
    ${rows.slice(0, 16).map((row) => `
      <details class="list-row contention-row ${escapeHtml(row.state)}">
        <summary>
          <div class="route-model">
            <span class="badge ${escapeHtml(row.provider)}">${escapeHtml(row.provider)}</span>
            <strong title="${escapeHtml(row.model)}">${escapeHtml(row.model)}</strong>
          </div>
          <span class="bar-stat score-bar"><i style="width:${Math.max(4, Math.min(100, (row.score / maxScore) * 100))}%; background:${row.color}55"></i><b>${formatNumber(row.score)}</b></span>
          <span>${formatNumber(row.calls)}</span>
          <span>${formatNumber(row.errors)}</span>
          <span>${formatNumber(row.active)}</span>
          <span>${formatCompact(row.tokens)}</span>
          <span>${formatPct(row.cacheRatio)}</span>
          <span>${formatMs(row.p95Latency)}</span>
          <span class="contention-action-label">${escapeHtml(row.action)}</span>
        </summary>
        <div class="contention-details">
          ${detailCell("Upstream", row.upstream)}
          ${detailCell("Phase", row.phase || "-")}
          ${detailCell("Avg latency", formatMs(row.avgLatency))}
          ${detailCell("Latest", formatTime(row.latest))}
          ${detailCell("Input", formatCompact(row.inputTokens))}
          ${detailCell("Output", formatCompact(row.outputTokens))}
          ${detailCell("Cache read", formatCompact(row.cacheRead))}
          ${detailCell("Cache base", formatCompact(row.cacheBase))}
          ${detailCell("Pressure", row.reason, "detail-wide")}
        </div>
      </details>`).join("")}`;

  actions.innerHTML = rows.slice(0, 5).map((row, index) => `
    <div class="contention-card ${escapeHtml(row.state)}">
      <span>${formatNumber(index + 1).padStart(2, "0")}</span>
      <div>
        <strong>${escapeHtml(row.action)}</strong>
        <p>${escapeHtml(row.reason)}</p>
        <small>${escapeHtml(row.model)} - ${escapeHtml(row.upstream)} - score ${formatNumber(row.score)}</small>
      </div>
    </div>`).join("");
}

function contentionRows(recent, active) {
  return routeRows(recent, active).map((row) => {
    const cacheMiss = row.cacheBase > 0 ? 1 - row.cacheRatio : 0;
    const latencyScore = Math.min(120, Math.round((row.p95Latency || 0) / 750));
    const tokenScore = Math.min(90, Math.round(Math.log10(Math.max(row.tokens, 1)) * 16));
    const score = Math.round(
      row.errors * 120
      + row.active * 35
      + latencyScore
      + tokenScore
      + Math.round(cacheMiss * 35)
      + Math.min(30, row.calls * 2)
    );
    const diagnosis = contentionDiagnosis(row, score);
    return {
      ...row,
      score,
      action: diagnosis.action,
      reason: diagnosis.reason,
      state: diagnosis.state,
      color: COLORS[String(row.upstream || "").toLowerCase()] || COLORS[row.provider] || groupColor(row.model),
    };
  }).filter((row) => row.score > 0).sort((a, b) => (
    b.score - a.score
    || b.errors - a.errors
    || b.active - a.active
    || b.tokens - a.tokens
    || a.model.localeCompare(b.model)
  ));
}

function contentionDiagnosis(row, score) {
  if (row.errors > 0) {
    return {
      state: "error",
      action: "Fix failing route",
      reason: `${formatNumber(row.errors)} failed call${row.errors === 1 ? "" : "s"} on ${row.model}; inspect upstream error body and auth/model mapping first.`,
    };
  }
  if (row.active > 2) {
    return {
      state: "live",
      action: "Watch live fan-out",
      reason: `${formatNumber(row.active)} live call${row.active === 1 ? "" : "s"} are stacked on this route. Fusion fan-out or a stuck stream may be holding the lane open.`,
    };
  }
  if (row.p95Latency >= 60_000) {
    return {
      state: "warning",
      action: "Profile slow provider",
      reason: `p95 is ${formatMs(row.p95Latency)}. That is not latency; that is a coffee break wearing a trench coat.`,
    };
  }
  if (row.cacheBase > 0 && row.cacheRatio < 0.08 && row.tokens >= 10_000) {
    return {
      state: "warning",
      action: "Improve cache reuse",
      reason: `${formatCompact(row.tokens)} tokens with only ${formatPct(row.cacheRatio)} cache reuse. Prompt shape may be drifting or cache headers are not landing.`,
    };
  }
  if (row.tokens >= 50_000) {
    return {
      state: "watch",
      action: "Review token burn",
      reason: `${formatCompact(row.tokens)} tokens moved through this route. Valid if intentional; expensive if a loop is chewing glass.`,
    };
  }
  return {
    state: score >= 85 ? "watch" : "ok",
    action: score >= 85 ? "Keep an eye on it" : "Healthy enough",
    reason: "No hard failure signal. Score is mostly call volume, modest latency, or ordinary cache misses.",
  };
}

function renderTrafficHeatmap(points, generatedAt) {
  const target = $("traffic-heatmap");
  const summaryTarget = $("heatmap-summary");
  if (!target || !summaryTarget) return;

  const matrix = trafficHeatmapMatrix(points, generatedAt);
  if (!matrix.totalCalls) {
    summaryTarget.innerHTML = `
      <div class="heatmap-summary-card empty">
        <span>Traffic</span>
        <strong>0 calls</strong>
        <small>No completed calls in this window.</small>
      </div>`;
    target.innerHTML = '<div class="empty-state">Traffic cells will light up as requests complete.</div>';
    return;
  }

  summaryTarget.innerHTML = heatmapSummaryCards(matrix);
  target.style.setProperty("--heatmap-columns", String(matrix.bucketCount));
  target.innerHTML = `
    <div class="heatmap-row heatmap-axis" style="--heatmap-columns:${matrix.bucketCount}">
      <span class="heatmap-provider-label">Provider</span>
      ${matrix.buckets.map((bucket, index) => `
        <span class="heatmap-tick" title="${escapeHtml(formatHeatmapRange(bucket.start, bucket.end))}">
          ${index % matrix.tickEvery === 0 ? escapeHtml(formatHeatmapTick(bucket.start)) : ""}
        </span>`).join("")}
    </div>
    ${matrix.rows.map((row) => `
      <div class="heatmap-row" style="--heatmap-columns:${matrix.bucketCount}">
        <span class="heatmap-provider-label">
          <i style="background:${COLORS[row.provider] || groupColor(row.provider)}"></i>
          ${escapeHtml(providerLabel(row.provider))}
        </span>
        ${row.cells.map((cell, index) => heatmapCell(row.provider, matrix.buckets[index], cell, matrix.maxCount)).join("")}
      </div>`).join("")}`;
}

function trafficHeatmapMatrix(points, generatedAt) {
  const validPoints = (points || [])
    .filter((point) => Number.isFinite(Number(point.t)))
    .map((point) => ({
      ...point,
      t: Number(point.t),
      provider: point.provider || "unknown",
      latency_ms: Number(point.latency_ms || 0),
      tokens: Number(point.tokens || 0),
      ok: point.ok !== false,
    }))
    .sort((a, b) => a.t - b.t);
  const now = Number(generatedAt || validPoints[validPoints.length - 1]?.t || Date.now() / 1000);
  const option = selectedWindow();
  const defaultSpan = option.seconds || Math.max(300, now - Number(validPoints[0]?.t || now - 300));
  const start = option.seconds ? now - option.seconds : Number(validPoints[0]?.t || now - defaultSpan);
  const end = Math.max(now, start + 60);
  const span = Math.max(60, end - start);
  const bucketCount = heatmapBucketCount(span);
  const bucketSize = span / bucketCount;
  const buckets = Array.from({ length: bucketCount }, (_, index) => ({
    start: start + index * bucketSize,
    end: start + (index + 1) * bucketSize,
  }));
  const rows = PROVIDERS.map((provider) => ({
    provider,
    cells: buckets.map(() => ({
      count: 0,
      errors: 0,
      tokens: 0,
      latencySum: 0,
      maxLatency: 0,
    })),
  }));
  const rowMap = new Map(rows.map((row) => [row.provider, row]));

  for (const point of validPoints) {
    if (point.t < start || point.t > end) continue;
    const provider = PROVIDERS.includes(point.provider) ? point.provider : "unknown";
    let row = rowMap.get(provider);
    if (!row) {
      row = {
        provider,
        cells: buckets.map(() => ({
          count: 0,
          errors: 0,
          tokens: 0,
          latencySum: 0,
          maxLatency: 0,
        })),
      };
      rowMap.set(provider, row);
      rows.push(row);
    }
    const index = clamp(Math.floor(((point.t - start) / span) * bucketCount), 0, bucketCount - 1);
    const cell = row.cells[index];
    cell.count += 1;
    cell.errors += point.ok ? 0 : 1;
    cell.tokens += point.tokens;
    cell.latencySum += point.latency_ms;
    cell.maxLatency = Math.max(cell.maxLatency, point.latency_ms);
  }

  for (const row of rows) {
    for (const cell of row.cells) {
      cell.avgLatency = cell.count ? cell.latencySum / cell.count : 0;
    }
  }

  const allCells = rows.flatMap((row) => row.cells.map((cell, index) => ({ ...cell, provider: row.provider, index })));
  const maxCount = Math.max(...allCells.map((cell) => cell.count), 1);
  const totalCalls = allCells.reduce((sum, cell) => sum + cell.count, 0);
  const peak = allCells.slice().sort((a, b) => (
    b.count - a.count
    || b.errors - a.errors
    || b.tokens - a.tokens
    || b.avgLatency - a.avgLatency
  ))[0] || null;

  return {
    rows,
    buckets,
    bucketCount,
    maxCount,
    totalCalls,
    peak,
    hotCells: allCells.filter((cell) => cell.count > 0 && cell.count >= maxCount * 0.65).length,
    errorCells: allCells.filter((cell) => cell.errors > 0).length,
    slowCells: allCells.filter((cell) => cell.avgLatency >= 30_000).length,
    tickEvery: Math.max(1, Math.ceil(bucketCount / 6)),
  };
}

function heatmapBucketCount(spanSeconds) {
  if (spanSeconds <= 300) return 10;
  if (spanSeconds <= 900) return 15;
  if (spanSeconds <= 3600) return 18;
  return 24;
}

function heatmapSummaryCards(matrix) {
  const peak = matrix.peak && matrix.peak.count > 0 ? matrix.peak : null;
  const peakBucket = peak ? matrix.buckets[peak.index] : null;
  return `
    <div class="heatmap-summary-card">
      <span>Calls</span>
      <strong>${formatNumber(matrix.totalCalls)}</strong>
      <small>${formatNumber(matrix.hotCells)} hot cells</small>
    </div>
    <div class="heatmap-summary-card">
      <span>Peak lane</span>
      <strong>${peak ? escapeHtml(providerLabel(peak.provider)) : "none"}</strong>
      <small>${peakBucket ? `${formatNumber(peak.count)} calls at ${escapeHtml(formatHeatmapTick(peakBucket.start))}` : "No peak detected"}</small>
    </div>
    <div class="heatmap-summary-card ${matrix.errorCells ? "bad" : "ok"}">
      <span>Error cells</span>
      <strong>${formatNumber(matrix.errorCells)}</strong>
      <small>${matrix.errorCells ? "Inspect red cells first." : "No error buckets."}</small>
    </div>
    <div class="heatmap-summary-card ${matrix.slowCells ? "watch" : "ok"}">
      <span>Slow cells</span>
      <strong>${formatNumber(matrix.slowCells)}</strong>
      <small>${matrix.slowCells ? "Average latency over 30s." : "No slow buckets."}</small>
    </div>`;
}

function heatmapCell(provider, bucket, cell, maxCount) {
  const state = heatmapCellState(cell, maxCount);
  const color = COLORS[provider] || groupColor(provider);
  const intensity = cell.count ? clamp(cell.count / Math.max(maxCount, 1), 0.12, 1) : 0;
  const label = cell.count ? formatNumber(cell.count) : "";
  const title = [
    providerLabel(provider),
    formatHeatmapRange(bucket.start, bucket.end),
    `${formatNumber(cell.count)} call${cell.count === 1 ? "" : "s"}`,
    `${formatCompact(cell.tokens)} tokens`,
    `${formatMs(cell.avgLatency || 0)} avg`,
    cell.errors ? `${formatNumber(cell.errors)} errors` : "0 errors",
  ].join(" - ");
  return `
    <span class="heatmap-cell ${state}" title="${escapeHtml(title)}" style="--heatmap-color:${color}; --heatmap-intensity:${intensity}">
      <b>${escapeHtml(label)}</b>
    </span>`;
}

function heatmapCellState(cell, maxCount) {
  if (!cell.count) return "empty";
  if (cell.errors > 0) return "error";
  if ((cell.avgLatency || 0) >= 30_000) return "slow";
  if (cell.count >= maxCount * 0.65) return "hot";
  return "warm";
}

function formatHeatmapTick(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatHeatmapRange(start, end) {
  return `${formatHeatmapTick(start)} - ${formatHeatmapTick(end)}`;
}

function renderRouteMatrix(recent, active) {
  const target = $("route-matrix");
  if (!target) return;
  const rows = routeRows(recent, active);
  if (!rows.length) {
    target.innerHTML = '<div class="empty-state">Route rows will appear after model traffic hits the proxy.</div>';
    return;
  }
  const maxTokens = Math.max(...rows.map((row) => row.tokens), 1);
  target.innerHTML = `
    <div class="list-head route-row">
      <span>Route</span><span>Upstream</span><span>Phase</span><span>Calls</span><span>Errors</span><span>Active</span><span>Tokens</span><span>Cache</span><span>p95</span>
    </div>
    ${rows.slice(0, 18).map((row) => {
      const state = row.errors ? "error" : row.active ? "warning" : "";
      return `
        <div class="list-row route-row ${state}">
          <div class="route-model">
            <span class="badge ${escapeHtml(row.provider)}">${escapeHtml(row.provider)}</span>
            <strong title="${escapeHtml(row.model)}">${escapeHtml(row.model)}</strong>
          </div>
          <span>${escapeHtml(row.upstream)}</span>
          <span>${row.phase ? phaseChip(row.phase) : "-"}</span>
          <span>${formatNumber(row.calls)}</span>
          <span>${formatNumber(row.errors)}</span>
          <span>${formatNumber(row.active)}</span>
          <span class="bar-stat"><i style="width:${Math.max(4, Math.min(100, (row.tokens / maxTokens) * 100))}%"></i><b>${formatCompact(row.tokens)}</b></span>
          <span>${formatPct(row.cacheRatio)}</span>
          <span>${formatMs(row.p95Latency)}</span>
        </div>`;
    }).join("")}`;
}

function routeRows(recent, active) {
  const grouped = new Map();
  for (const request of [...(active || []), ...(recent || [])]) {
    const provider = request.provider || "unknown";
    const upstreamProvider = request.upstream_provider || request.provider || "unknown";
    const model = request.display_label || request.label || request.model || "unknown model";
    const phase = request.phase || "";
    const key = `${provider}:${upstreamProvider}:${phase}:${model}`;
    const usage = request.usage || {};
    const cache = request.cache || {};
    const item = grouped.get(key) || {
      provider,
      upstream: providerLabel(upstreamProvider),
      phase,
      model,
      calls: 0,
      errors: 0,
      active: 0,
      tokens: 0,
      cacheRead: 0,
      cacheBase: 0,
      latencies: [],
      latest: 0,
    };
    item.calls += 1;
    item.errors += request.ok === false || request.error ? 1 : 0;
    item.active += request.active ? 1 : 0;
    item.tokens += Number(usage.total_tokens || 0);
    item.cacheRead += Number(cache.read_tokens || 0);
    item.cacheBase += Number(usage.input_tokens || 0) + Number(cache.read_tokens || 0) + Number(cache.write_tokens || 0);
    item.latencies.push(Number(request.duration_ms || 0));
    item.latest = Math.max(item.latest, Number(request.ended_at || request.started_at || 0));
    grouped.set(key, item);
  }
  return Array.from(grouped.values()).map((item) => ({
    ...item,
    cacheRatio: item.cacheBase ? item.cacheRead / item.cacheBase : 0,
    avgLatency: item.latencies.length ? item.latencies.reduce((sum, value) => sum + value, 0) / item.latencies.length : 0,
    p95Latency: percentile(item.latencies, 0.95),
  })).sort((a, b) => (
    b.errors - a.errors
    || b.active - a.active
    || b.tokens - a.tokens
    || b.calls - a.calls
    || b.latest - a.latest
  ));
}

function renderRouteSloBoard(recent, active) {
  const summaryTarget = $("route-slo-summary");
  const boardTarget = $("route-slo-board");
  if (!summaryTarget || !boardTarget) return;
  const rows = routeSloRows(recent, active);

  if (!rows.length) {
    summaryTarget.innerHTML = [
      routeSloSummaryCard("Routes", "0", "No traffic in window"),
      routeSloSummaryCard("Breaches", "0", "Nothing to triage", "ok"),
      routeSloSummaryCard("Worst p95", "0ms", "No completed calls"),
      routeSloSummaryCard("Stream risk", "0", "No buffering signals"),
    ].join("");
    boardTarget.innerHTML = '<div class="empty-state">Route guardrails will appear after model traffic hits the proxy.</div>';
    return;
  }

  const breachCount = rows.filter((row) => row.state === "bad" || row.state === "watch").length;
  const worstP95 = Math.max(...rows.map((row) => row.p95Latency), 0);
  const brickRisk = rows.filter((row) => row.brickRisk).length;
  const maxTokens = Math.max(...rows.map((row) => row.tokens), 1);

  summaryTarget.innerHTML = [
    routeSloSummaryCard("Routes", formatNumber(rows.length), "Grouped provider/model lanes"),
    routeSloSummaryCard("Breaches", formatNumber(breachCount), breachCount ? "Needs operator review" : "All clear", breachCount ? "watch" : "ok"),
    routeSloSummaryCard("Worst p95", formatMs(worstP95), worstP95 >= 60_000 ? "User-visible drag" : "Current window"),
    routeSloSummaryCard("Stream risk", formatNumber(brickRisk), brickRisk ? "Possible buffered output" : "Chunking looks sane", brickRisk ? "watch" : "ok"),
  ].join("");

  boardTarget.innerHTML = `
    <div class="list-head route-slo-row">
      <span>Route</span><span>Provider</span><span>Calls</span><span>Error</span><span>p95</span><span>Stream</span><span>Cache</span><span>Action</span>
    </div>
    ${rows.slice(0, 16).map((row) => {
      const stateClass = routeSloStateClass(row);
      return `
        <div class="list-row route-slo-row ${escapeHtml(row.state)}">
          <div class="route-slo-route">
            <strong title="${escapeHtml(row.model)}">${escapeHtml(row.model)}</strong>
            <small>${escapeHtml(row.provider)} / ${escapeHtml(row.upstream)}${row.phase ? phaseChip(row.phase) : ""}</small>
          </div>
          <span class="route-provider-dot" style="--provider-color:${groupColor(row.upstreamRaw || row.provider)}">${escapeHtml(row.upstream)}</span>
          <span>${formatNumber(row.calls)}${row.active ? ` <small>${formatNumber(row.active)} live</small>` : ""}</span>
          <span>${formatPct(row.errorRate)}</span>
          <span>${formatMs(row.p95Latency)}</span>
          <span>${statusPill(routeSloStreamLabel(row), stateClass)}</span>
          <span class="bar-stat route-slo-cache"><i style="width:${Math.max(4, Math.min(100, row.cacheRatio * 100))}%"></i><b>${formatPct(row.cacheRatio)}</b></span>
          <span class="bar-stat route-slo-action"><i style="width:${Math.max(4, Math.min(100, (row.tokens / maxTokens) * 100))}%"></i><b title="${escapeHtml(row.action)}">${escapeHtml(row.action)}</b></span>
        </div>`;
    }).join("")}`;
}

function routeSloRows(recent, active) {
  const grouped = new Map();
  for (const request of [...(active || []), ...(recent || [])]) {
    const provider = request.provider || "unknown";
    const upstreamRaw = request.upstream_provider || request.provider || "unknown";
    const upstream = providerLabel(upstreamRaw);
    const model = request.display_label || request.label || request.model || "unknown model";
    const phase = request.phase || "";
    const key = `${provider}:${upstreamRaw}:${phase}:${model}`;
    const usage = request.usage || {};
    const cache = request.cache || {};
    const stream = request.stream || {};
    const item = grouped.get(key) || {
      provider,
      upstream,
      upstreamRaw,
      phase,
      model,
      calls: 0,
      active: 0,
      errors: 0,
      tokens: 0,
      cacheRead: 0,
      cacheBase: 0,
      chunks: 0,
      textChars: 0,
      toolChunks: 0,
      toolChars: 0,
      reasoningChars: 0,
      latencies: [],
      latest: 0,
    };

    item.calls += 1;
    item.active += request.active ? 1 : 0;
    item.errors += isErrorRecord(request) ? 1 : 0;
    item.tokens += Number(usage.total_tokens || 0);
    item.cacheRead += Number(cache.read_tokens || 0);
    item.cacheBase += Number(usage.input_tokens || 0) + Number(cache.read_tokens || 0) + Number(cache.write_tokens || 0);
    item.chunks += Number(stream.chunks || 0);
    item.textChars += Number(stream.text_chars || 0);
    item.toolChunks += Number(stream.tool_chunks || 0);
    item.toolChars += Number(stream.tool_chars || 0);
    item.reasoningChars += Number(stream.reasoning_chars || 0);
    if (!request.active) {
      item.latencies.push(Number(request.duration_ms || 0));
    }
    item.latest = Math.max(item.latest, Number(request.ended_at || request.started_at || 0));
    grouped.set(key, item);
  }

  return Array.from(grouped.values()).map((item) => {
    const errorRate = item.calls ? item.errors / item.calls : 0;
    const p95Latency = percentile(item.latencies, 0.95);
    const cacheRatio = item.cacheBase ? item.cacheRead / item.cacheBase : 0;
    const totalChars = item.textChars + item.toolChars + item.reasoningChars;
    const brickRisk = totalChars >= 1000 && item.chunks <= Math.max(1, item.calls);
    const streamEfficiency = item.chunks ? totalChars / item.chunks : totalChars;
    const row = {
      ...item,
      errorRate,
      p95Latency,
      cacheRatio,
      totalChars,
      brickRisk,
      streamEfficiency,
    };
    row.state = routeSloState(row);
    row.action = routeSloAction(row);
    return row;
  }).sort((a, b) => (
    routeSloSeverityRank(b) - routeSloSeverityRank(a)
    || b.errors - a.errors
    || b.active - a.active
    || b.p95Latency - a.p95Latency
    || b.tokens - a.tokens
    || b.latest - a.latest
    || a.model.localeCompare(b.model)
  ));
}

function routeSloState(row) {
  if (row.errors > 0 || row.errorRate >= 0.05 || row.p95Latency >= 60_000) return "bad";
  if (row.brickRisk || row.p95Latency >= 20_000 || row.cacheRatio < 0.05 && row.calls >= 3) return "watch";
  if (row.active > 0) return "live";
  return "healthy";
}

function routeSloSeverityRank(row) {
  return {
    bad: 4,
    watch: 3,
    live: 2,
    healthy: 1,
  }[row.state] || 0;
}

function routeSloStateClass(row) {
  return {
    bad: "error",
    watch: "warning",
    live: "live",
    healthy: "ok",
  }[row.state] || "neutral";
}

function routeSloAction(row) {
  if (row.errors > 0) return "Inspect auth, model id, and rejected params.";
  if (row.p95Latency >= 60_000) return "Move traffic or downgrade tier.";
  if (row.brickRisk) return "Check stream adapter buffering.";
  if (row.p95Latency >= 20_000) return "Watch upstream latency.";
  if (row.cacheRatio < 0.05 && row.calls >= 3) return "Review prompt cache eligibility.";
  if (row.active > 1) return "Watch concurrent in-flight requests.";
  return "No immediate action.";
}

function routeSloStreamLabel(row) {
  if (row.brickRisk) return "buffer risk";
  if (!row.chunks && !row.totalChars) return "none";
  if (row.toolChunks > row.chunks * 0.5) return "tool heavy";
  return `${formatCompact(row.chunks)} chunks`;
}

function routeSloSummaryCard(label, value, detail, state = "") {
  return `
    <div class="route-slo-card ${escapeHtml(state)}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(detail)}</small>
    </div>`;
}

function renderExecutionTimeline(recent, active, generatedAt) {
  const target = $("execution-timeline");
  if (!target) return;
  const rows = timelineRows(recent, active, generatedAt);
  if (!rows.length) {
    target.innerHTML = '<div class="empty-state">Execution lanes will appear after requests hit the proxy.</div>';
    return;
  }

  const minTime = Math.min(...rows.map((row) => row.start));
  const maxTime = Math.max(...rows.map((row) => row.end));
  const span = Math.max(1, maxTime - minTime);
  const ticks = timelineTicks(minTime, maxTime);

  target.innerHTML = `
    <div class="timeline-axis">
      ${ticks.map((tick) => {
        const left = clamp(((tick - minTime) / span) * 100, 0, 100);
        return `<span style="left:${left}%">${escapeHtml(formatTimelineTick(tick))}</span>`;
      }).join("")}
    </div>
    ${rows.map((row) => {
      const left = clamp(((row.start - minTime) / span) * 100, 0, 100);
      const width = clamp(((row.end - row.start) / span) * 100, 0.8, Math.max(0.8, 100 - left));
      const color = row.color || COLORS[row.provider] || COLORS[row.upstream] || PALETTE[0];
      return `
        <div class="timeline-row ${escapeHtml(row.state)}">
          <div class="timeline-label">
            <span class="badge ${escapeHtml(row.provider)}">${escapeHtml(row.provider)}</span>
            <div>
              <strong title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</strong>
              <span>${escapeHtml(row.meta)}</span>
            </div>
          </div>
          <div class="timeline-track" aria-label="${escapeHtml(row.label)} ${escapeHtml(row.durationLabel)}">
            <i
              class="timeline-bar"
              style="left:${left}%;width:${width}%;--timeline-color:${color}"
              title="${escapeHtml(row.title)}"
            ><span>${escapeHtml(row.durationLabel)}</span></i>
          </div>
          <div class="timeline-tail">
            ${statusPill(row.status, row.statusState)}
            <span>${escapeHtml(row.tail)}</span>
          </div>
        </div>`;
    }).join("")}`;
}

function timelineRows(recent, active, generatedAt) {
  const now = Number(generatedAt || Date.now() / 1000);
  const merged = [
    ...(active || []).map((request) => ({ ...request, active: true })),
    ...(recent || []).map((request) => ({ ...request, active: Boolean(request.active) })),
  ];
  const seen = new Set();
  const rows = [];
  for (const request of merged) {
    const id = request.id || `${request.provider}:${request.model}:${request.started_at}:${request.phase || ""}`;
    if (seen.has(id)) continue;
    seen.add(id);
    const start = Number(request.started_at || 0);
    if (!Number.isFinite(start) || start <= 0) continue;
    const endFromRecord = Number(request.ended_at || 0);
    const durationSeconds = Number(request.duration_ms || 0) / 1000;
    const end = request.active
      ? now
      : (endFromRecord > start ? endFromRecord : start + Math.max(durationSeconds, 0.1));
    const safeEnd = Math.max(start + 0.1, end);
    const status = request.final_status || request.upstream_status || (request.active ? "live" : "done");
    const state = timelineState(request);
    const provider = request.provider || "unknown";
    const upstream = request.upstream_provider || request.provider || "unknown";
    const label = request.display_label || request.label || request.model || "unknown model";
    const usage = request.usage || {};
    const cache = request.cache || {};
    const phase = request.phase ? ` - ${request.phase}` : "";
    const meta = `${providerLabel(upstream)} - ${request.operation || "request"}${phase}`;
    rows.push({
      provider,
      upstream,
      label,
      meta,
      status,
      statusState: statusStateFor(request),
      state,
      start,
      end: safeEnd,
      durationLabel: formatMs(Math.max(Number(request.duration_ms || 0), (safeEnd - start) * 1000)),
      tail: `${formatCompact(usage.total_tokens)} tok - ${formatPct(cache.hit_ratio)} cache`,
      title: `${label} - ${meta} - ${formatTime(start)} to ${formatTime(safeEnd)}`,
      color: timelineColor(request, state),
    });
  }
  return rows.sort((a, b) => b.start - a.start).slice(0, 24);
}

function timelineState(request) {
  if (isErrorRecord(request)) return "error";
  if (request.active) return "live";
  if (Number(request.duration_ms || 0) >= 60_000) return "warning";
  return "ok";
}

function timelineColor(request, state) {
  if (state === "error") return COLORS.anthropic;
  if (state === "warning") return COLORS.fusion;
  if (state === "live") return "#7ed321";
  return COLORS[request.upstream_provider] || COLORS[request.provider] || PALETTE[0];
}

function timelineTicks(minTime, maxTime) {
  const span = Math.max(1, maxTime - minTime);
  return Array.from({ length: 5 }, (_, index) => minTime + (span / 4) * index);
}

function formatTimelineTick(epochSeconds) {
  if (!epochSeconds) return "";
  return new Date(epochSeconds * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderStreamShape(recent, active) {
  const table = $("stream-shape");
  const summary = $("stream-summary");
  if (!table || !summary) return;
  const rows = streamRows(recent, active);
  const totals = rows.reduce((acc, row) => ({
    calls: acc.calls + row.calls,
    streamed: acc.streamed + row.streamed,
    chunks: acc.chunks + row.chunks,
    chars: acc.chars + row.chars,
    seconds: acc.seconds + row.seconds,
    brickRisk: acc.brickRisk + row.brickRisk,
    toolChunks: acc.toolChunks + row.toolChunks,
  }), { calls: 0, streamed: 0, chunks: 0, chars: 0, seconds: 0, brickRisk: 0, toolChunks: 0 });

  summary.innerHTML = `
    ${streamStat("Streamed calls", `${formatNumber(totals.streamed)} / ${formatNumber(totals.calls)}`)}
    ${streamStat("Chunks", formatCompact(totals.chunks))}
    ${streamStat("Chunk rate", `${formatNumber(totals.seconds ? totals.chunks / totals.seconds : 0)}/s`)}
    ${streamStat("Brick risk", formatNumber(totals.brickRisk), totals.brickRisk ? "warning" : "ok")}
    ${streamStat("Tool deltas", formatCompact(totals.toolChunks))}
  `;

  if (!rows.length) {
    table.innerHTML = '<div class="empty-state">Stream cadence rows appear once completed or live streaming traffic is observed.</div>';
    return;
  }

  const maxChunks = Math.max(...rows.map((row) => row.chunks), 1);
  table.innerHTML = `
    <div class="list-head stream-row">
      <span>Route</span><span>Calls</span><span>Streamed</span><span>Chunks</span><span>Rate</span><span>Chars</span><span>Tools</span><span>Risk</span>
    </div>
    ${rows.slice(0, 14).map((row) => {
      const state = row.brickRisk ? "warning" : row.errors ? "error" : row.active ? "live" : "";
      return `
        <div class="list-row stream-row ${state}">
          <div class="stream-route">
            <span class="badge ${escapeHtml(row.provider)}">${escapeHtml(row.provider)}</span>
            <div>
              <strong title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</strong>
              <span>${escapeHtml(row.meta)}</span>
            </div>
          </div>
          <span>${formatNumber(row.calls)}</span>
          <span>${formatNumber(row.streamed)}</span>
          <span class="bar-stat"><i style="width:${Math.max(4, Math.min(100, (row.chunks / maxChunks) * 100))}%; background:${row.color}55"></i><b>${formatCompact(row.chunks)}</b></span>
          <span>${formatNumber(row.seconds ? row.chunks / row.seconds : 0)}/s</span>
          <span>${formatCompact(row.chars)}</span>
          <span>${formatCompact(row.toolChunks)}</span>
          <span>${row.brickRisk ? statusPill(row.brickRisk, "warning") : statusPill("clear", "ok")}</span>
        </div>`;
    }).join("")}`;
}

function streamRows(recent, active) {
  const grouped = new Map();
  for (const request of [...(active || []), ...(recent || [])]) {
    const stream = request.stream || {};
    const chunks = Number(stream.chunks || 0);
    const toolChunks = Number(stream.tool_chunks || 0);
    const chars = Number(stream.text_chars || 0) + Number(stream.reasoning_chars || 0) + Number(stream.tool_chars || 0);
    const durationMs = Number(request.duration_ms || 0);
    const isStreamingRelevant = chunks > 0 || toolChunks > 0 || chars > 0 || durationMs > 0 || request.active;
    if (!isStreamingRelevant) continue;
    const provider = request.provider || "unknown";
    const upstream = request.upstream_provider || request.provider || "unknown";
    const label = request.display_label || request.label || request.model || "unknown model";
    const phase = request.phase || "";
    const key = `${provider}:${upstream}:${phase}:${label}`;
    const item = grouped.get(key) || {
      provider,
      upstream,
      phase,
      label,
      meta: `${providerLabel(upstream)} - ${phase || request.operation || "request"}`,
      color: COLORS[upstream] || COLORS[provider] || groupColor(label),
      calls: 0,
      streamed: 0,
      chunks: 0,
      chars: 0,
      seconds: 0,
      toolChunks: 0,
      brickRisk: 0,
      active: 0,
      errors: 0,
      latest: 0,
    };
    item.calls += 1;
    item.streamed += chunks > 0 || chars > 0 ? 1 : 0;
    item.chunks += chunks;
    item.chars += chars;
    item.seconds += Math.max(durationMs / 1000, 0);
    item.toolChunks += toolChunks;
    item.brickRisk += durationMs >= 10_000 && chunks <= 1 ? 1 : 0;
    item.active += request.active ? 1 : 0;
    item.errors += isErrorRecord(request) ? 1 : 0;
    item.latest = Math.max(item.latest, Number(request.ended_at || request.started_at || 0));
    grouped.set(key, item);
  }
  return Array.from(grouped.values()).sort((a, b) => (
    b.brickRisk - a.brickRisk
    || b.errors - a.errors
    || b.active - a.active
    || b.chunks - a.chunks
    || b.latest - a.latest
    || a.label.localeCompare(b.label)
  ));
}

function streamStat(label, value, state = "") {
  return `
    <div class="stream-stat ${escapeHtml(state)}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>`;
}

function renderContent(events) {
  const target = $("content-feed");
  if (!events.length) {
    target.innerHTML = '<div class="empty-state">Content previews will appear when model traffic flows through Conduit.</div>';
    return;
  }
  target.innerHTML = events.slice(0, 28).map((event) => {
    const label = event.label || event.model || "unknown model";
    const upstream = event.upstream_provider ? ` - ${providerLabel(event.upstream_provider)}` : "";
    return `
    <div class="content-row">
      <strong>${escapeHtml(providerLabel(event.provider))} - ${escapeHtml(event.kind)} - ${escapeHtml(label)}</strong>
      <div class="content-meta">${formatTime(event.timestamp)} - ${formatNumber(event.chars)} chars${escapeHtml(upstream)}${event.truncated ? " - truncated" : ""}</div>
      <pre>${escapeHtml(event.preview)}</pre>
    </div>`;
  }).join("");
}

function providerLabel(provider) {
  return {
    codex: "GPT / Codex",
    anthropic: "Claude",
    azure: "Azure GPT",
    fusion: "Fusion",
  }[provider] || provider;
}

function drawSparkline(canvas, points, color) {
  if (!canvas) return;
  const ctx = scaleCanvas(canvas);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  ctx.clearRect(0, 0, width, height);
  drawSparkGrid(ctx, width, height, 4);
  const values = points.slice(-40).map((point) => Number(point.tokens || 0));
  drawLine(ctx, values, width, height, color, true);
}

function drawTokenChart(canvas, points) {
  if (!canvas) return;
  const ctx = scaleCanvas(canvas);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const plot = { left: 52, right: 16, top: 14, bottom: 28 };
  const prepared = prepareTokenSeries(points, width, height, plot);

  ctx.clearRect(0, 0, width, height);
  drawTokenGrid(ctx, width, height, plot, prepared);
  renderTokenLegend();

  const mode = chartMode("token");
  for (const [index, provider] of PROVIDERS.entries()) {
    const series = prepared.series[provider] || [];
    if (mode === "bar") {
      drawTimeBars(ctx, series, COLORS[provider], plot, index, PROVIDERS.length);
    } else {
      drawTimeLine(ctx, series, COLORS[provider], prepared.maxY, plot, mode === "area");
    }
  }

  if (tokenHover && prepared.points.length) {
    const nearest = findNearestPoint(prepared.points, tokenHover.x, tokenHover.y);
    if (nearest) {
      const siblingValues = nearestValuesByProvider(prepared, nearest.t);
      drawChartNeedle(ctx, width, height, plot, nearest, tokenHover.y, siblingValues);
      showTokenTooltip(nearest, siblingValues, width, height);
    }
  } else {
    hideTokenTooltip();
  }
}

function prepareTokenSeries(points, width, height, plot) {
  const sorted = (points || [])
    .filter((point) => Number.isFinite(Number(point.t)))
    .slice(-120)
    .sort((a, b) => Number(a.t) - Number(b.t));
  const minT = sorted.length ? Number(sorted[0].t) : Date.now() / 1000 - 60;
  const maxT = sorted.length ? Number(sorted[sorted.length - 1].t) : Date.now() / 1000;
  const span = Math.max(1, maxT - minT);
  const maxY = Math.max(...sorted.map((point) => Number(point.tokens || 0)), 1);
  const series = Object.fromEntries(PROVIDERS.map((provider) => [provider, []]));
  const screenPoints = [];

  for (const point of sorted) {
    const provider = PROVIDERS.includes(point.provider) ? point.provider : "codex";
    const x = plot.left + ((Number(point.t) - minT) / span) * (width - plot.left - plot.right);
    const y = height - plot.bottom - (Number(point.tokens || 0) / maxY) * (height - plot.top - plot.bottom);
    const normalized = { ...point, provider, x, y };
    series[provider].push(normalized);
    screenPoints.push(normalized);
  }

  return { minT, maxT, maxY, series, points: screenPoints, plot };
}

function drawTokenGrid(ctx, width, height, plot, prepared) {
  ctx.save();
  ctx.lineWidth = 1;
  ctx.font = "10px JetBrains Mono, Cascadia Code, monospace";
  ctx.textBaseline = "middle";

  for (let i = 0; i <= 4; i += 1) {
    const y = plot.top + ((height - plot.top - plot.bottom) / 4) * i;
    const value = prepared.maxY - (prepared.maxY / 4) * i;
    ctx.strokeStyle = i === 4 ? "rgba(255,255,255,0.16)" : "rgba(255,255,255,0.085)";
    ctx.beginPath();
    ctx.moveTo(plot.left, y);
    ctx.lineTo(width - plot.right, y);
    ctx.stroke();
    ctx.fillStyle = "rgba(146,160,184,0.78)";
    ctx.textAlign = "right";
    ctx.fillText(formatCompact(value), plot.left - 9, y);
  }

  for (let i = 0; i <= 5; i += 1) {
    const x = plot.left + ((width - plot.left - plot.right) / 5) * i;
    const t = prepared.minT + ((prepared.maxT - prepared.minT) / 5) * i;
    ctx.strokeStyle = "rgba(255,255,255,0.045)";
    ctx.beginPath();
    ctx.moveTo(x, plot.top);
    ctx.lineTo(x, height - plot.bottom);
    ctx.stroke();
    ctx.fillStyle = "rgba(146,160,184,0.7)";
    ctx.textAlign = i === 0 ? "left" : i === 5 ? "right" : "center";
    ctx.fillText(formatTime(t).replace(/:\d{2}\s/, " "), x, height - 10);
  }

  ctx.restore();
}

function drawTimeLine(ctx, points, color, maxY, plot, fill) {
  if (!points.length) return;
  ctx.save();
  ctx.lineWidth = 1.8;
  ctx.strokeStyle = color;
  ctx.beginPath();
  points.forEach((point, index) => {
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
  ctx.stroke();

  if (fill && points.length > 1) {
    const last = points[points.length - 1];
    const first = points[0];
    ctx.lineTo(last.x, ctx.canvas.clientHeight - plot.bottom);
    ctx.lineTo(first.x, ctx.canvas.clientHeight - plot.bottom);
    ctx.closePath();
    const gradient = ctx.createLinearGradient(0, plot.top, 0, ctx.canvas.clientHeight - plot.bottom);
    gradient.addColorStop(0, `${color}33`);
    gradient.addColorStop(1, `${color}00`);
    ctx.fillStyle = gradient;
    ctx.fill();
  }

  ctx.restore();
}

function drawTimeBars(ctx, points, color, plot, seriesIndex = 0, seriesCount = 1) {
  if (!points.length) return;
  const baseline = ctx.canvas.clientHeight - plot.bottom;
  const plotWidth = ctx.canvas.clientWidth - plot.left - plot.right;
  const barSlot = plotWidth / Math.max(12, points.length);
  const width = Math.max(2, Math.min(12, (barSlot * 0.72) / Math.max(1, seriesCount)));
  const offset = (seriesIndex - ((seriesCount - 1) / 2)) * (width + 1);
  ctx.save();
  const gradient = ctx.createLinearGradient(0, plot.top, 0, baseline);
  gradient.addColorStop(0, `${color}cc`);
  gradient.addColorStop(1, `${color}33`);
  ctx.fillStyle = gradient;
  for (const point of points) {
    const barHeight = Math.max(1.5, baseline - point.y);
    ctx.fillRect(point.x - (width / 2) + offset, baseline - barHeight, width, barHeight);
  }
  ctx.restore();
}

function drawChartNeedle(ctx, width, height, plot, nearest, mouseY, dots = [nearest]) {
  const y = Math.max(plot.top, Math.min(mouseY, height - plot.bottom));
  ctx.save();
  ctx.strokeStyle = "rgba(255,255,255,0.28)";
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(nearest.x, plot.top);
  ctx.lineTo(nearest.x, height - plot.bottom);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(plot.left, y);
  ctx.lineTo(width - plot.right, y);
  ctx.stroke();
  ctx.setLineDash([]);
  drawHoverDots(ctx, dots.map((point) => ({
    x: point.x,
    y: point.y,
    color: COLORS[point.provider] || "#00c7e6",
    active: point.provider === nearest.provider,
  })));
  ctx.restore();
}

function findNearestPoint(points, x, y) {
  let nearest = null;
  let best = Number.POSITIVE_INFINITY;
  for (const point of points) {
    const distance = Math.abs(point.x - x) * 1.4 + Math.abs(point.y - y) * 0.35;
    if (distance < best) {
      best = distance;
      nearest = point;
    }
  }
  return nearest;
}

function showTokenTooltip(nearest, siblingValues, width, height) {
  const tooltip = $("token-tooltip");
  if (!tooltip) return;
  tooltip.innerHTML = [
    `<strong>${escapeHtml(formatTime(nearest.t))}</strong>`,
    ...siblingValues.map((point) => `
      <div class="chart-tooltip-row">
        <span style="color:${COLORS[point.provider] || "#00c7e6"}"><i class="chart-dot"></i>${escapeHtml(providerLabel(point.provider))}</span>
        <b>${escapeHtml(formatCompact(point.tokens || 0))}</b>
      </div>`),
  ].join("");
  tooltip.hidden = false;

  const box = tooltip.getBoundingClientRect();
  const anchor = tooltipAnchor(
    { x: nearest.x, y: nearest.y, value: Number(nearest.tokens || 0) },
    tokenHover || { x: nearest.x, y: nearest.y },
  );
  const left = clamp(anchor.x + 14, 8, Math.max(8, width - box.width - 8));
  const top = clamp(anchor.y - box.height - 14, 8, Math.max(8, height - box.height - 8));
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function nearestValuesByProvider(prepared, timestamp) {
  return PROVIDERS.map((provider) => {
    const points = prepared.series[provider] || [];
    let nearest = null;
    let best = Number.POSITIVE_INFINITY;
    for (const point of points) {
      const distance = Math.abs(Number(point.t) - Number(timestamp));
      if (distance < best) {
        nearest = point;
        best = distance;
      }
    }
    return nearest;
  }).filter(Boolean);
}

function hideTokenTooltip() {
  const tooltip = $("token-tooltip");
  if (tooltip) tooltip.hidden = true;
}

function renderTokenLegend() {
  const target = $("token-legend");
  if (!target) return;
  target.innerHTML = PROVIDERS.map((provider) => `
    <span class="legend-item" style="color:${COLORS[provider]}">
      <i class="chart-dot"></i>
      <span>${escapeHtml(providerLabel(provider))}</span>
    </span>`).join("");
}

function drawAllCharts(points) {
  drawTokenChart($("token-chart"), points);
  drawMetricChart("traffic", buildTrafficSeries(points), "count");
  drawMetricChart("latency", buildLatencySeries(points), "ms");
  drawMetricChart("cache", buildCacheSeries(points), "compact");
  drawMetricChart("phase", buildPhaseLatencySeries(points), "ms");
  drawEfficiencyChart($("efficiency-chart"), points);
}

function buildTrafficSeries(points) {
  const sorted = sortedPoints(points);
  return [
    {
      id: "requests",
      label: "Requests",
      color: "#00c7e6",
      points: sorted.map((point) => ({ t: point.t, value: 1 })),
    },
    {
      id: "errors",
      label: "Errors",
      color: "#e5534b",
      points: sorted.map((point) => ({ t: point.t, value: point.ok === false ? 1 : 0 })),
    },
  ];
}

function buildLatencySeries(points) {
  const sorted = sortedPoints(points);
  return PROVIDERS.map((provider) => ({
    id: provider,
    label: providerLabel(provider),
    color: COLORS[provider],
    points: sorted
      .filter((point) => point.provider === provider)
      .map((point) => ({ t: point.t, value: Number(point.latency_ms || 0) })),
  }));
}

function buildCacheSeries(points) {
  const sorted = sortedPoints(points);
  return [
    {
      id: "input",
      label: "Input",
      color: "#00c7e6",
      points: sorted.map((point) => ({ t: point.t, value: Number(point.input_tokens || 0) })),
    },
    {
      id: "output",
      label: "Output",
      color: "#9966cc",
      points: sorted.map((point) => ({ t: point.t, value: Number(point.output_tokens || 0) })),
    },
    {
      id: "cache",
      label: "Cache read",
      color: "#7ed321",
      points: sorted.map((point) => ({ t: point.t, value: Number(point.cached_tokens || 0) })),
    },
  ];
}

function buildPhaseLatencySeries(points) {
  const sorted = sortedPoints(points).filter((point) => point.provider === "fusion" && point.phase);
  return ["panel", "synthesizer"].map((phase) => ({
    id: phase,
    label: phase === "synthesizer" ? "Synthesizer" : "Panels",
    color: COLORS[phase],
    points: sorted
      .filter((point) => point.phase === phase)
      .map((point) => ({ t: point.t, value: Number(point.latency_ms || 0) })),
  }));
}

function sortedPoints(points) {
  return (points || [])
    .filter((point) => Number.isFinite(Number(point.t)))
    .slice(-160)
    .sort((a, b) => Number(a.t) - Number(b.t));
}

function drawEfficiencyChart(canvas, points) {
  if (!canvas) return;
  const ctx = scaleCanvas(canvas);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const plot = { left: 58, right: 18, top: 14, bottom: 34 };
  const prepared = prepareEfficiencyPoints(points, width, height, plot);

  ctx.clearRect(0, 0, width, height);
  drawEfficiencyGrid(ctx, width, height, plot, prepared);
  renderEfficiencyLegend(prepared.providers);

  ctx.save();
  for (const point of prepared.points) {
    const color = COLORS[point.provider] || groupColor(point.provider);
    const gradient = ctx.createRadialGradient(point.x, point.y, 0, point.x, point.y, point.radius + 7);
    gradient.addColorStop(0, `${color}ee`);
    gradient.addColorStop(0.46, `${color}99`);
    gradient.addColorStop(1, `${color}00`);
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.arc(point.x, point.y, point.radius + 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = color;
    ctx.strokeStyle = "rgba(7,9,14,0.92)";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.arc(point.x, point.y, point.radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
  ctx.restore();

  const hover = chartHovers.efficiency;
  if (hover && prepared.points.length) {
    const nearest = findNearestPoint(prepared.points, hover.x, hover.y);
    if (nearest) {
      drawEfficiencyNeedle(ctx, width, height, plot, nearest, hover);
      showEfficiencyTooltip(nearest, width, height);
      return;
    }
  }
  hideEfficiencyTooltip();
}

function prepareEfficiencyPoints(points, width, height, plot) {
  const rows = sortedPoints(points).map((point) => {
    const inputTokens = Number(point.input_tokens || 0);
    const cachedTokens = Number(point.cached_tokens || 0);
    const outputTokens = Number(point.output_tokens || 0);
    const tokens = Number(point.tokens || inputTokens + outputTokens + cachedTokens);
    const cacheBase = inputTokens + cachedTokens;
    const cacheRatio = cacheBase > 0 ? cachedTokens / cacheBase : 0;
    return {
      ...point,
      provider: PROVIDERS.includes(point.provider) ? point.provider : "codex",
      cacheRatio: clamp(cacheRatio, 0, 1),
      latency: Math.max(0, Number(point.latency_ms || 0)),
      tokens: Math.max(0, tokens),
    };
  }).filter((point) => Number.isFinite(point.cacheRatio) && Number.isFinite(point.latency));

  const maxLatency = Math.max(...rows.map((point) => point.latency), 1);
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const providers = [...new Set(rows.map((point) => point.provider))];
  const screenPoints = rows.map((point) => ({
    ...point,
    x: plot.left + point.cacheRatio * plotWidth,
    y: height - plot.bottom - (point.latency / maxLatency) * plotHeight,
    radius: clamp(3 + Math.sqrt(point.tokens) / 45, 3.5, 11),
    color: COLORS[point.provider] || groupColor(point.provider),
    value: point.latency,
  }));

  return { points: screenPoints, maxLatency, providers, plot };
}

function drawEfficiencyGrid(ctx, width, height, plot, prepared) {
  ctx.save();
  ctx.lineWidth = 1;
  ctx.font = "10px JetBrains Mono, Cascadia Code, monospace";
  ctx.textBaseline = "middle";

  for (let i = 0; i <= 4; i += 1) {
    const y = plot.top + ((height - plot.top - plot.bottom) / 4) * i;
    const value = prepared.maxLatency - (prepared.maxLatency / 4) * i;
    ctx.strokeStyle = i === 4 ? "rgba(255,255,255,0.16)" : "rgba(255,255,255,0.085)";
    ctx.beginPath();
    ctx.moveTo(plot.left, y);
    ctx.lineTo(width - plot.right, y);
    ctx.stroke();
    ctx.fillStyle = "rgba(146,160,184,0.78)";
    ctx.textAlign = "right";
    ctx.fillText(formatMs(value), plot.left - 9, y);
  }

  for (let i = 0; i <= 4; i += 1) {
    const x = plot.left + ((width - plot.left - plot.right) / 4) * i;
    ctx.strokeStyle = "rgba(255,255,255,0.045)";
    ctx.beginPath();
    ctx.moveTo(x, plot.top);
    ctx.lineTo(x, height - plot.bottom);
    ctx.stroke();
    ctx.fillStyle = "rgba(146,160,184,0.7)";
    ctx.textAlign = i === 0 ? "left" : i === 4 ? "right" : "center";
    ctx.fillText(formatPct(i / 4), x, height - 12);
  }

  ctx.fillStyle = "rgba(146,160,184,0.62)";
  ctx.textAlign = "left";
  ctx.fillText("cache hit ratio", plot.left, height - 24);
  ctx.restore();
}

function drawEfficiencyNeedle(ctx, width, height, plot, nearest, hover) {
  const y = Math.max(plot.top, Math.min(hover.y, height - plot.bottom));
  ctx.save();
  ctx.strokeStyle = "rgba(255,255,255,0.26)";
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(nearest.x, plot.top);
  ctx.lineTo(nearest.x, height - plot.bottom);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(plot.left, y);
  ctx.lineTo(width - plot.right, y);
  ctx.stroke();
  ctx.setLineDash([]);
  drawHoverDots(ctx, [{
    x: nearest.x,
    y: nearest.y,
    color: nearest.color,
    active: true,
  }]);
  ctx.restore();
}

function showEfficiencyTooltip(nearest, width, height) {
  const tooltip = $("efficiency-tooltip");
  if (!tooltip) return;
  const label = nearest.label || nearest.model || "unknown model";
  tooltip.innerHTML = [
    `<strong>${escapeHtml(providerLabel(nearest.provider))} - ${escapeHtml(formatTime(nearest.t))}</strong>`,
    `<div class="chart-tooltip-row"><span style="color:${nearest.color}"><i class="chart-dot"></i>${escapeHtml(label)}</span><b>${escapeHtml(formatMs(nearest.latency))}</b></div>`,
    `<div class="chart-tooltip-row"><span>Cache hit</span><b>${escapeHtml(formatPct(nearest.cacheRatio))}</b></div>`,
    `<div class="chart-tooltip-row"><span>Tokens</span><b>${escapeHtml(formatCompact(nearest.tokens))}</b></div>`,
  ].join("");
  tooltip.hidden = false;

  const box = tooltip.getBoundingClientRect();
  const anchor = tooltipAnchor(nearest, chartHovers.efficiency || { x: nearest.x, y: nearest.y });
  const left = clamp(anchor.x + 14, 8, Math.max(8, width - box.width - 8));
  const top = clamp(anchor.y - box.height - 14, 8, Math.max(8, height - box.height - 8));
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function hideEfficiencyTooltip() {
  const tooltip = $("efficiency-tooltip");
  if (tooltip) tooltip.hidden = true;
}

function renderEfficiencyLegend(providers) {
  const target = $("efficiency-legend");
  if (!target) return;
  const values = providers.length ? providers : PROVIDERS;
  target.innerHTML = values.map((provider) => ` 
    <span class="legend-item" style="color:${COLORS[provider] || groupColor(provider)}">
      <i class="chart-dot"></i>
      <span>${escapeHtml(providerLabel(provider))}</span>
    </span>`).join("");
}

function drawMetricChart(key, seriesDefs, unit) {
  const canvas = $(`${key}-chart`);
  if (!canvas) return;
  const ctx = scaleCanvas(canvas);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const plot = { left: 52, right: 16, top: 14, bottom: 28 };
  const prepared = prepareMetricSeries(seriesDefs, width, height, plot);

  ctx.clearRect(0, 0, width, height);
  drawMetricGrid(ctx, width, height, plot, prepared, unit);
  renderMetricLegend(key, prepared.seriesDefs);

  const mode = chartMode(key);
  for (const [index, series] of prepared.seriesDefs.entries()) {
    const points = prepared.series[series.id] || [];
    if (mode === "bar") {
      drawTimeBars(ctx, points, series.color, plot, index, prepared.seriesDefs.length);
    } else {
      drawTimeLine(ctx, points, series.color, prepared.maxY, plot, mode === "area");
    }
  }

  const hover = chartHovers[key];
  if (hover && prepared.points.length) {
    const nearest = findNearestPoint(prepared.points, hover.x, hover.y);
    if (nearest) {
      const values = nearestValuesBySeries(prepared, nearest.t);
      drawGenericNeedle(ctx, width, height, plot, nearest, hover.y, values);
      showMetricTooltip(key, nearest, values, width, height, unit);
      return;
    }
  }
  hideMetricTooltip(key);
}

function prepareMetricSeries(seriesDefs, width, height, plot) {
  const all = seriesDefs.flatMap((series) => series.points || []);
  const minT = all.length ? Math.min(...all.map((point) => Number(point.t))) : Date.now() / 1000 - 60;
  const maxT = all.length ? Math.max(...all.map((point) => Number(point.t))) : Date.now() / 1000;
  const span = Math.max(1, maxT - minT);
  const maxY = Math.max(...all.map((point) => Number(point.value || 0)), 1);
  const series = {};
  const screenPoints = [];

  for (const seriesDef of seriesDefs) {
    const normalized = (seriesDef.points || []).map((point) => {
      const value = Number(point.value || 0);
      const x = plot.left + ((Number(point.t) - minT) / span) * (width - plot.left - plot.right);
      const y = height - plot.bottom - (value / maxY) * (height - plot.top - plot.bottom);
      return { ...point, value, x, y, seriesId: seriesDef.id, label: seriesDef.label, color: seriesDef.color };
    });
    series[seriesDef.id] = normalized;
    screenPoints.push(...normalized);
  }

  return { minT, maxT, maxY, series, seriesDefs, points: screenPoints, plot };
}

function drawMetricGrid(ctx, width, height, plot, prepared, unit) {
  ctx.save();
  ctx.lineWidth = 1;
  ctx.font = "10px JetBrains Mono, Cascadia Code, monospace";
  ctx.textBaseline = "middle";

  for (let i = 0; i <= 4; i += 1) {
    const y = plot.top + ((height - plot.top - plot.bottom) / 4) * i;
    const value = prepared.maxY - (prepared.maxY / 4) * i;
    ctx.strokeStyle = i === 4 ? "rgba(255,255,255,0.16)" : "rgba(255,255,255,0.085)";
    ctx.beginPath();
    ctx.moveTo(plot.left, y);
    ctx.lineTo(width - plot.right, y);
    ctx.stroke();
    ctx.fillStyle = "rgba(146,160,184,0.78)";
    ctx.textAlign = "right";
    ctx.fillText(formatChartValue(value, unit), plot.left - 9, y);
  }

  for (let i = 0; i <= 4; i += 1) {
    const x = plot.left + ((width - plot.left - plot.right) / 4) * i;
    const t = prepared.minT + ((prepared.maxT - prepared.minT) / 4) * i;
    ctx.strokeStyle = "rgba(255,255,255,0.045)";
    ctx.beginPath();
    ctx.moveTo(x, plot.top);
    ctx.lineTo(x, height - plot.bottom);
    ctx.stroke();
    ctx.fillStyle = "rgba(146,160,184,0.7)";
    ctx.textAlign = i === 0 ? "left" : i === 4 ? "right" : "center";
    ctx.fillText(formatTime(t).replace(/:\d{2}\s/, " "), x, height - 10);
  }

  ctx.restore();
}

function drawGenericNeedle(ctx, width, height, plot, nearest, mouseY, dots = [nearest]) {
  const y = Math.max(plot.top, Math.min(mouseY, height - plot.bottom));
  ctx.save();
  ctx.strokeStyle = "rgba(255,255,255,0.26)";
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(nearest.x, plot.top);
  ctx.lineTo(nearest.x, height - plot.bottom);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(plot.left, y);
  ctx.lineTo(width - plot.right, y);
  ctx.stroke();
  ctx.setLineDash([]);
  drawHoverDots(ctx, dots.map((point) => ({
    x: point.x,
    y: point.y,
    color: point.color || "#00c7e6",
    active: point.seriesId === nearest.seriesId,
  })));
  ctx.restore();
}

function drawHoverDots(ctx, dots) {
  for (const dot of dots) {
    if (!Number.isFinite(dot.x) || !Number.isFinite(dot.y)) continue;
    ctx.fillStyle = dot.color;
    ctx.strokeStyle = dot.active ? "#f3f7ff" : "#101620";
    ctx.lineWidth = dot.active ? 2.2 : 1.5;
    ctx.beginPath();
    ctx.arc(dot.x, dot.y, dot.active ? 4.8 : 3.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
}

function tooltipAnchor(point, cursor) {
  if (Math.abs(Number(point.value || 0)) > 1e-9) {
    return { x: point.x, y: point.y };
  }
  const cursorWeight = 0.72;
  const pointWeight = 1 - cursorWeight;
  return {
    x: (point.x * pointWeight) + (cursor.x * cursorWeight),
    y: (point.y * pointWeight) + (cursor.y * cursorWeight),
  };
}

function showMetricTooltip(key, nearest, values, width, height, unit) {
  const tooltip = $(`${key}-tooltip`);
  if (!tooltip) return;
  tooltip.innerHTML = [
    `<strong>${escapeHtml(formatTime(nearest.t))}</strong>`,
    ...values.map((point) => `
      <div class="chart-tooltip-row">
        <span style="color:${point.color || "#00c7e6"}"><i class="chart-dot"></i>${escapeHtml(point.label)}</span>
        <b>${escapeHtml(formatChartValue(point.value || 0, unit))}</b>
      </div>`),
  ].join("");
  tooltip.hidden = false;

  const box = tooltip.getBoundingClientRect();
  const anchor = tooltipAnchor(nearest, chartHovers[key] || { x: nearest.x, y: nearest.y });
  const left = clamp(anchor.x + 14, 8, Math.max(8, width - box.width - 8));
  const top = clamp(anchor.y - box.height - 14, 8, Math.max(8, height - box.height - 8));
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function nearestValuesBySeries(prepared, timestamp) {
  return prepared.seriesDefs.map((seriesDef) => {
    const points = prepared.series[seriesDef.id] || [];
    let nearest = null;
    let best = Number.POSITIVE_INFINITY;
    for (const point of points) {
      const distance = Math.abs(Number(point.t) - Number(timestamp));
      if (distance < best) {
        nearest = point;
        best = distance;
      }
    }
    return nearest;
  }).filter(Boolean);
}

function hideMetricTooltip(key) {
  const tooltip = $(`${key}-tooltip`);
  if (tooltip) tooltip.hidden = true;
}

function renderMetricLegend(key, seriesDefs) {
  const target = $(`${key}-legend`);
  if (!target) return;
  target.innerHTML = seriesDefs.map((series) => `
    <span class="legend-item" style="color:${series.color}">
      <i class="chart-dot"></i>
      <span>${escapeHtml(series.label)}</span>
    </span>`).join("");
}

function formatChartValue(value, unit) {
  if (unit === "ms") return formatMs(value);
  if (unit === "count") return formatNumber(value);
  return formatCompact(value);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(value, max));
}

function drawSparkGrid(ctx, width, height, lines) {
  ctx.save();
  ctx.strokeStyle = "rgba(255,255,255,0.07)";
  ctx.lineWidth = 1;
  for (let i = 1; i < lines; i += 1) {
    const y = (height / lines) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
  ctx.restore();
}

function drawLine(ctx, values, width, height, color, fill) {
  if (!values.length) return;
  const max = Math.max(...values, 1);
  const step = values.length <= 1 ? width : width / (values.length - 1);
  ctx.save();
  ctx.lineWidth = 1.8;
  ctx.strokeStyle = color;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = index * step;
    const y = height - (value / max) * (height - 16) - 8;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  if (fill) {
    ctx.lineTo(width, height);
    ctx.lineTo(0, height);
    ctx.closePath();
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, `${color}2b`);
    gradient.addColorStop(1, `${color}00`);
    ctx.fillStyle = gradient;
    ctx.fill();
  }
  ctx.restore();
}

function scaleCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(1, Math.floor(rect.width));
  const height = Math.max(1, Math.floor(rect.height || canvas.height));
  if (canvas.width !== width * ratio || canvas.height !== height * ratio) {
    canvas.width = width * ratio;
    canvas.height = height * ratio;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return ctx;
}

async function resetTelemetry() {
  const button = $("reset-button");
  button.disabled = true;
  try {
    const response = await fetch("/dashboard/api/reset", { method: "POST" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    lastSnapshot = null;
    lastRawSnapshot = null;
    tokenHover = null;
    latencyBandsHover = null;
    await renderLoopOnce();
  } finally {
    button.disabled = false;
  }
}

async function renderLoopOnce() {
  const snapshot = await fetchSnapshot();
  lastRawSnapshot = snapshot;
  renderSnapshot(snapshot);
}

function setupChartInteraction() {
  for (const key of ["token", "traffic", "latency", "cache", "phase", "efficiency"]) {
    const canvas = $(`${key}-chart`);
    if (!canvas) continue;
    canvas.addEventListener("mousemove", (event) => {
      const rect = canvas.getBoundingClientRect();
      chartHovers[key] = {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      };
      if (key === "token") tokenHover = chartHovers[key];
      if (lastSnapshot) drawAllCharts(lastSnapshot.timeseries || []);
    });
    canvas.addEventListener("mouseleave", () => {
      delete chartHovers[key];
      if (key === "token") {
        tokenHover = null;
        hideTokenTooltip();
      } else if (key === "efficiency") {
        hideEfficiencyTooltip();
      } else {
        hideMetricTooltip(key);
      }
      if (lastSnapshot) drawAllCharts(lastSnapshot.timeseries || []);
    });
  }
  const latencyBands = $("latency-bands-chart");
  if (latencyBands) {
    latencyBands.addEventListener("mousemove", (event) => {
      const rect = latencyBands.getBoundingClientRect();
      latencyBandsHover = {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      };
      if (lastSnapshot) renderLatencyDistribution(lastSnapshot.recent_requests || [], lastSnapshot.active_requests || []);
    });
    latencyBands.addEventListener("mouseleave", () => {
      latencyBandsHover = null;
      hideLatencyBandsTooltip();
      if (lastSnapshot) renderLatencyDistribution(lastSnapshot.recent_requests || [], lastSnapshot.active_requests || []);
    });
  }
}

function setupMenuNavigation() {
  const links = Array.from(document.querySelectorAll(".rail-item, .menu-link"));
  const sections = links
    .map((link) => document.querySelector(link.getAttribute("href") || ""))
    .filter(Boolean);
  const activate = (id) => {
    links.forEach((link) => link.classList.toggle("active", link.getAttribute("href") === `#${id}`));
  };
  for (const link of links) {
    link.addEventListener("click", () => {
      const id = (link.getAttribute("href") || "").slice(1);
      if (id) activate(id);
    });
  }
  window.addEventListener("scroll", () => {
    const current = sections
      .map((section) => ({ id: section.id, top: Math.abs(section.getBoundingClientRect().top - 92) }))
      .sort((a, b) => a.top - b.top)[0];
    if (current) activate(current.id);
  }, { passive: true });
}

async function refreshOpsReview() {
  const button = $("ops-review-button");
  if (button) button.disabled = true;
  try {
    const response = await fetch("/dashboard/api/ops-review", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderOpsReview(await response.json());
  } finally {
    if (button) button.disabled = false;
  }
}

$("ops-review-button")?.addEventListener("click", refreshOpsReview);

window.addEventListener("resize", () => {
  if (lastRawSnapshot) renderSnapshot(lastRawSnapshot);
});

window.addEventListener("beforeunload", () => {
  if (refreshTimer) window.clearTimeout(refreshTimer);
});

$("reset-button")?.addEventListener("click", resetTelemetry);
setupWindowControl();
setupGroupControl();
setupChartModeControls();
setupChartInteraction();
setupMenuNavigation();
renderLoop();
