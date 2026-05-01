"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const els = {
  form:       $("#address-form"),
  uri:        $("#uri"),
  format:     $("#format"),
  go:         $("#go"),
  menuBtn:    $("#menu-btn"),
  menu:       $("#menu"),
  advanced:   $("#advanced"),
  registry:   $("#registry"),
  insecure:   $("#insecure"),
  skip:       $("#skip-verify"),
  status:     $("#status"),
  prettyPre:  $("#pretty-pre"),
  prettyIfr:  $("#pretty-iframe"),
  raw:        $("#raw"),
  headers:    $("#headers"),
  agentTabs:  $("#agent-tabs"),
  newTab:     $("#new-tab"),
  histPanel:  $("#history-panel"),
  histList:   $("#history-list"),
  histEmpty:  $("#history-empty"),
  histClose:  $("#hist-close"),
};

const state = {
  tabs: [],         // [{ id, uri, format, registry, insecure, skip, result, status }]
  activeId: null,
  history: [],
  respPane: "pretty",
};

let tabCounter = 0;
const newId = () => `t${++tabCounter}`;

// ---------- API readiness ----------
function whenApiReady() {
  return new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) return resolve();
    window.addEventListener("pywebviewready", () => resolve(), { once: true });
  });
}

// ---------- helpers ----------
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function shortUri(uri) {
  if (!uri) return "(new tab)";
  const m = uri.match(/^agtp:\/\/([0-9a-f]{1,64})(.*)$/i);
  if (m) return `agtp://${m[1].slice(0, 10)}…${m[2]}`;
  return uri.length > 32 ? uri.slice(0, 30) + "…" : uri;
}

// Pull a human-readable agent name from a successful response body. Falls
// back to null if the format isn't easily parseable or the field is absent.
function nameFromBody(body, format) {
  if (!body) return null;
  try {
    if (format === "json") {
      const obj = JSON.parse(body);
      return typeof obj?.name === "string" ? obj.name.trim() : null;
    }
    if (format === "yaml") {
      // First top-level `name: ...` line. Strips optional quotes.
      const m = body.match(/^name:\s*"?([^"\n#]+?)"?\s*(?:#.*)?$/m);
      return m ? m[1].trim() : null;
    }
    if (format === "html") {
      // Use <title> minus any " — ..." / " - ..." suffix.
      const m = body.match(/<title>([^<]+)<\/title>/i);
      if (!m) return null;
      const raw = m[1].trim();
      return raw.split(/\s+[—-]\s+/)[0].trim() || null;
    }
  } catch {
    /* ignore */
  }
  return null;
}

function highlightJson(str) {
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\],]/g;
  return str.replace(re, (match, strLit, colon) => {
    if (strLit !== undefined) {
      const cls = colon ? "j-key" : "j-str";
      const tail = colon ? `<span class="j-punct">${colon}</span>` : "";
      return `<span class="${cls}">${escapeHtml(strLit)}</span>${tail}`;
    }
    if (match === "true" || match === "false") return `<span class="j-bool">${match}</span>`;
    if (match === "null") return `<span class="j-null">${match}</span>`;
    if (/^[{}\[\],]$/.test(match)) return `<span class="j-punct">${match}</span>`;
    return `<span class="j-num">${match}</span>`;
  });
}

// ---------- tab state ----------
function getActive() {
  return state.tabs.find((t) => t.id === state.activeId);
}

function snapshotFormToTab(tab) {
  if (!tab) return;
  tab.uri = els.uri.value;
  tab.format = els.format.value;
  tab.registry = els.registry.value;
  tab.insecure = els.insecure.checked;
  tab.skip = els.skip.checked;
}

function loadTabIntoForm(tab) {
  els.uri.value = tab.uri || "";
  els.format.value = tab.format || "json";
  els.registry.value = tab.registry || "";
  els.insecure.checked = !!tab.insecure;
  els.skip.checked = !!tab.skip;
  renderResponse(tab);
  setStatus(tab.status?.text ?? "Ready.", tab.status?.kind ?? "idle");
}

function newTab(opts = {}) {
  const tab = {
    id: newId(),
    uri: opts.uri ?? "",
    format: opts.format ?? "json",
    registry: opts.registry ?? "",
    insecure: false,
    skip: false,
    result: null,
    status: null,
  };
  state.tabs.push(tab);
  switchTab(tab.id, { skipSnapshot: true });
  renderTabStrip();
  return tab;
}

function closeTab(id) {
  const i = state.tabs.findIndex((t) => t.id === id);
  if (i < 0) return;
  state.tabs.splice(i, 1);

  if (state.tabs.length === 0) {
    newTab();
    return;
  }
  if (state.activeId === id) {
    const next = state.tabs[Math.min(i, state.tabs.length - 1)];
    switchTab(next.id, { skipSnapshot: true });
  }
  renderTabStrip();
}

function switchTab(id, { skipSnapshot = false } = {}) {
  if (!skipSnapshot) snapshotFormToTab(getActive());
  state.activeId = id;
  const tab = getActive();
  if (tab) loadTabIntoForm(tab);
  renderTabStrip();
}

function renderTabStrip() {
  els.agentTabs.innerHTML = "";
  for (const tab of state.tabs) {
    const div = document.createElement("div");
    div.className = "agent-tab" + (tab.id === state.activeId ? " active" : "");
    div.title = tab.uri || "(new tab)";

    const label = document.createElement("span");
    label.className = "label";
    label.textContent = tab.name || shortUri(tab.uri);

    const close = document.createElement("button");
    close.className = "close";
    close.type = "button";
    close.textContent = "×";
    close.addEventListener("click", (e) => {
      e.stopPropagation();
      closeTab(tab.id);
    });

    div.appendChild(label);
    div.appendChild(close);
    div.addEventListener("click", () => switchTab(tab.id));

    els.agentTabs.appendChild(div);
  }
}

// ---------- response panes ----------
function showPrettyAs(mode) {
  if (mode === "iframe") {
    els.prettyPre.classList.add("hidden");
    els.prettyIfr.classList.remove("hidden");
  } else {
    els.prettyIfr.classList.add("hidden");
    els.prettyPre.classList.remove("hidden");
  }
}

function clearResponsePanes() {
  els.prettyPre.textContent = "";
  els.prettyIfr.srcdoc = "";
  els.raw.textContent = "";
  els.headers.textContent = "";
  showPrettyAs("pre");
}

function renderResponse(tab) {
  clearResponsePanes();
  const r = tab?.result;
  if (!r) return;

  if (!r.ok) {
    els.prettyPre.textContent = r.error || "(error)";
    els.raw.textContent = r.error || "";
    els.headers.textContent = `error during ${r.stage || "?"}`;
    showPrettyAs("pre");
    return;
  }

  els.raw.textContent = r.body;

  // Headers pane
  const hLines = [];
  hLines.push(`AGTP/1.0 ${r.status_code} ${r.status_text}`);
  for (const [k, v] of Object.entries(r.headers || {})) {
    hLines.push(`${k}: ${v}`);
  }
  hLines.push("");
  hLines.push(`# resolved: ${r.host}:${r.port}`);
  hLines.push(`# agent_id: ${r.agent_id}`);
  els.headers.textContent = hLines.join("\n");

  // Pretty pane: rendered HTML for html, syntax-highlighted for json, plain for yaml
  if (r.format === "html") {
    els.prettyIfr.srcdoc = r.body;
    showPrettyAs("iframe");
  } else if (r.format === "json") {
    try {
      const obj = JSON.parse(r.body);
      els.prettyPre.innerHTML = highlightJson(JSON.stringify(obj, null, 2));
    } catch {
      els.prettyPre.textContent = r.body;
    }
    showPrettyAs("pre");
  } else {
    els.prettyPre.textContent = r.body;
    showPrettyAs("pre");
  }
}

// response-tab switching
$$(".rtab").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.disabled || btn.classList.contains("disabled")) return;
    $$(".rtab").forEach((b) => b.classList.remove("active"));
    $$(".pane").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#pane-${btn.dataset.tab}`).classList.add("active");
    state.respPane = btn.dataset.tab;
  });
});

// ---------- status ----------
function setStatus(text, kind = "idle") {
  els.status.textContent = text;
  els.status.className = `status ${kind}`;
  const tab = getActive();
  if (tab) tab.status = { text, kind };
}

// ---------- history ----------
async function refreshHistory() {
  state.history = await window.pywebview.api.history_load();
  renderHistory();
}

function renderHistory() {
  els.histList.innerHTML = "";
  if (!state.history.length) {
    els.histEmpty.classList.remove("hidden");
    return;
  }
  els.histEmpty.classList.add("hidden");

  for (const h of state.history) {
    const li = document.createElement("li");
    const klass = h.ok ? "h-ok" : "h-err";
    const status = h.ok ? `${h.status_code}` : "ERR";
    const when = h.ts ? new Date(h.ts * 1000).toLocaleString() : "";
    li.innerHTML =
      `<div>${escapeHtml(h.uri)}</div>` +
      `<span class="h-meta">` +
      `<span class="${klass}">${status}</span> · ${escapeHtml(h.format || "")}` +
      (h.host ? ` · ${escapeHtml(h.host)}:${h.port}` : "") +
      (when ? ` · ${escapeHtml(when)}` : "") +
      `</span>`;
    li.addEventListener("click", () => {
      const tab = getActive();
      if (tab) {
        tab.uri = h.uri;
        tab.format = h.format || "json";
        loadTabIntoForm(tab);
        renderTabStrip();
        doFetch();
      }
    });
    els.histList.appendChild(li);
  }
}

async function pushHistory(entry) {
  state.history = await window.pywebview.api.history_add(entry);
  renderHistory();
}

async function clearHistory() {
  state.history = await window.pywebview.api.history_clear();
  renderHistory();
}

function toggleHistory(force) {
  const show = force === undefined
    ? els.histPanel.classList.contains("hidden")
    : !!force;
  els.histPanel.classList.toggle("hidden", !show);
}

// ---------- menu ----------
function toggleMenu(force) {
  const show = force === undefined
    ? els.menu.classList.contains("hidden")
    : !!force;
  els.menu.classList.toggle("hidden", !show);
}

els.menuBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleMenu();
});

document.addEventListener("click", (e) => {
  if (!els.menu.contains(e.target) && e.target !== els.menuBtn) {
    toggleMenu(false);
  }
});

$$(".menu-item").forEach((item) => {
  item.addEventListener("click", () => {
    const action = item.dataset.action;
    toggleMenu(false);
    if (action === "toggle-history") toggleHistory();
    if (action === "clear-history") clearHistory();
    if (action === "toggle-advanced") els.advanced.classList.toggle("hidden");
  });
});

els.histClose.addEventListener("click", () => toggleHistory(false));

// ---------- new tab ----------
els.newTab.addEventListener("click", () => newTab());

// ---------- main fetch ----------
async function doFetch() {
  const tab = getActive();
  if (!tab) return;
  snapshotFormToTab(tab);

  const uri = tab.uri.trim();
  if (!uri) {
    setStatus("Enter an agtp:// URI.", "err");
    return;
  }

  tab.name = null;
  els.go.disabled = true;
  setStatus(`Resolving ${uri} …`, "working");

  let result;
  try {
    result = await window.pywebview.api.fetch(
      uri,
      tab.format,
      tab.registry,
      tab.insecure,
      tab.skip,
    );
  } catch (e) {
    setStatus(`bridge error: ${e}`, "err");
    els.go.disabled = false;
    return;
  } finally {
    els.go.disabled = false;
  }

  // Stash on the tab — but only if the user hasn't already switched away.
  // (We keyed by tab.id at the time of the call.)
  tab.result = result;
  tab.uri = uri;
  if (result.ok) {
    tab.name = nameFromBody(result.body, result.format);
  }
  renderTabStrip();

  if (state.activeId === tab.id) {
    if (!result.ok) {
      setStatus(`[${result.stage}] ${result.error}`, "err");
    } else {
      const kind = result.status_code === 200 ? "ok" : "err";
      setStatus(
        `${result.status_code} ${result.status_text} · ${result.host}:${result.port} · ${result.content_type || "no content-type"}`,
        kind,
      );
    }
    renderResponse(tab);
  }

  await pushHistory({
    uri,
    format: tab.format,
    ok: !!result.ok,
    status_code: result.status_code,
    host: result.host,
    port: result.port,
    agent_id: result.agent_id,
    error: result.ok ? null : result.error,
  });
}

els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  doFetch();
});

// ---------- boot ----------
(async function init() {
  await whenApiReady();
  const [initialUri, defaultRegistry] = await Promise.all([
    window.pywebview.api.get_initial_uri(),
    window.pywebview.api.get_default_registry(),
  ]);
  els.registry.placeholder = defaultRegistry || "https://registry.agtp.io";

  await refreshHistory();

  newTab({ uri: initialUri || "" });

  if (initialUri) {
    doFetch();
  } else {
    setStatus("Ready. Enter an agtp:// URI and press Go.", "idle");
    els.uri.focus();
  }
})();
