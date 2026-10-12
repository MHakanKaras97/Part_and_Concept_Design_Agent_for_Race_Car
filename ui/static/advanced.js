// AI Engineering Agent - web UI. Presentation only: all state comes from /api (agent.service).
// All user/AI text is inserted with textContent (never innerHTML).
"use strict";

const EXAMPLE = "Design a machined aluminium L-bracket to mount a 2 kg sensor box to a flat plate with four M6 bolts.";
const S = { runId: null, view: null, status: null, pollTimer: null, sending: false, files: [] };
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
const MAX_IMAGE_BYTES = 5 * 1024 * 1024, MAX_IMAGES = 4;
const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v; else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) n.append(c instanceof Node ? c : String(c));
  return n;
}

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const ct = r.headers.get("Content-Type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || `HTTP ${r.status}`);
  return data;
}

// ---------------------------------------------------------------- status / evidence helpers
function statusClass(status) {
  return { VERIFIED: "t-verified", ASSUMPTION: "t-assumption", NON_COMPLIANT: "t-fail",
           NOT_VERIFIED: "t-notver", NOT_APPLICABLE: "t-notver" }[status] || "t-system";
}
function labelStatus(label) {
  for (const s of ["NON_COMPLIANT", "NOT_VERIFIED", "NOT_APPLICABLE", "ASSUMPTION", "VERIFIED"]) if (label.endsWith(s)) return s;
  return "";
}
function chip(text, cls) { return el("span", { class: `tag ${cls}`, text }); }
function sourceChip(src) {
  return chip(src, { USER: "t-user", USER_ANSWER: "t-user", USER_REQUEST: "t-user", REQUIREMENT: "t-user",
    IMAGE: "t-image", IMAGE_EVIDENCE: "t-image",
    ASSUMPTION: "t-assumption", RULE: "t-verified", DERIVED: "t-decision", LEGACY_V1: "t-notver" }[src] || "t-system");
}
function fmt(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// ---------------------------------------------------------------- header
function renderStatus() {
  const st = S.status;
  const pb = $("pill-backend"), pr = $("pill-reasoner"), pf = $("pill-fusion");
  pb.className = "pill " + (st ? "ok" : "bad");
  pb.lastChild.textContent = st ? `Backend · ${st.project}` : "Backend offline";
  document.body.classList.toggle("read-only", !!(st && st.read_only));
  if (!st) return;
  const r = st.reasoner;
  pr.className = "pill " + (r.available ? (r.mode === "claude_code" ? "ok" : "warn") : "bad");
  pr.lastChild.textContent = r.mode === "claude_code" ? "Reasoner · Claude Code" : `Reasoner · ${r.mode.replace("_", " ")}`;
  pr.title = r.detail;
  const f = st.fusion;
  pf.className = "pill " + (f.connected ? "ok" : "bad");
  pf.lastChild.textContent = f.connected ? (f.version ? `Fusion 360 · ${f.version}` : "Fusion 360 · connected") : "Fusion 360 · offline";
  pf.title = f.connected ? `Active document at last check: ${f.document || "none"}` : f.error || "";
  $("p-fusion").replaceChildren(f.connected
    ? el("div", {}, chip("CONNECTED", "t-verified"), el("div", { class: "meta", text: `v${f.version || "?"} · ${f.document || "no document"} (at last check)` }))
    : el("div", {}, chip("OFFLINE", "t-fail"), el("div", { class: "meta", text: (f.error || "").slice(0, 120) })));
}

// ---------------------------------------------------------------- pipeline
const PIPE_EMPTY = ["REQUIREMENTS", "QUESTIONS", "ASSUMPTIONS", "ENGINEERING PLAN", "CAD GENERATION", "VALIDATION", "REVIEW", "REGISTERED"];
function renderPipeline(v) {
  const nav = $("pipeline");
  const steps = v ? v.pipeline : PIPE_EMPTY.map((l) => ({ label: l, state: "todo" }));
  const note = { done: "done", current: "in progress", waiting: "waiting", failed: "stopped", skipped: "not needed", todo: "" };
  nav.replaceChildren(...steps.map((s, i) =>
    el("div", { class: `step ${s.state}` }, `${i + 1}. ${s.label}`, el("small", { text: note[s.state] || "" }))));
}

// ---------------------------------------------------------------- chat
function msgHead(role, layerTag, title) {
  return el("div", { class: "msg-head" },
    el("span", { class: `role ${role}`, text: role === "user" ? "USER" : role === "agent" ? "AGENT" : "SYSTEM" }),
    layerTag, el("span", { class: "msg-title", text: title || "" }));
}

function renderMessage(m) {
  const cls = `msg ${m.role} l-${m.layer}${m.pending ? " pending" : ""}`;
  const box = el("div", { class: cls });
  switch (m.layer) {
    case "USER_REQUEST":
      box.append(msgHead("user", chip("user request", "t-user"), m.title), el("div", { class: "msg-text verbatim", text: m.text }));
      if (m.attachments && m.attachments.length) {
        box.append(el("div", { class: "msg-atts" }, ...m.attachments.map((a) =>
          el("figure", { style: "margin:0" },
            el("a", { href: a.url, target: "_blank", title: `${a.original_name} · sha256 ${a.sha256}` }, el("img", { src: a.url, alt: a.original_name })),
            el("figcaption", { text: `${a.id} · ${a.original_name} · source evidence` })))));
      }
      break;
    case "USER_ANSWER":
      box.append(msgHead("user", chip("user answer · verbatim · authoritative", "t-user"), m.title),
        el("div", { class: "msg-text verbatim", text: m.text }),
        m.received ? el("div", { class: "meta", text: `recorded ${m.received}` }) : null);
      break;
    case "QUESTION":
      if (m.pending) box.append(el("div", { class: "waiting-banner", text: "■ WAITING FOR YOUR ANSWER" }));
      box.append(msgHead("agent", chip(`question · ${m.criticality || ""}`, "t-question"), m.title),
        el("div", { class: "msg-text", text: m.text }),
        m.pending ? el("div", { class: "meta", text: "Answer in your own words below. Your text is stored verbatim; the agent will not fill gaps for you." }) : null);
      break;
    case "AI_INTERPRETATION": {
      box.append(msgHead("agent", chip("ai interpretation", "t-interp"), m.title), el("div", { class: "msg-text", text: m.text }));
      const t = el("table", { class: "kv" }, el("tr", {}, ...["ID", "Origin", "Source evidence (your words / image reading)", "AI interpretation", "Value"].map((h) => el("th", { text: h }))));
      for (const r of m.items) {
        const ev = r.source === "IMAGE"
          ? el("td", { class: "image-ev", text: `${r.attachment_id}: “${r.image_evidence}” (read by AI from your image)` })
          : el("td", { class: "quote", text: r.quote ? `“${r.quote}”` : "—" });
        t.append(el("tr", {},
          el("td", { class: "num", text: r.id }),
          el("td", {}, sourceChip(r.source), r.answer_id ? el("span", { class: "meta", text: ` ${r.answer_id}` }) : null),
          ev,
          el("td", { class: "interp", text: r.interpretation }),
          el("td", { class: "num", text: [fmt(r.value), r.unit || ""].join(" ").trim() })));
      }
      box.append(t);
      break;
    }
    case "ASSUMPTION":
      box.append(msgHead("agent", chip("assumption", "t-assumption"), m.title),
        el("table", { class: "kv" }, ...m.items.map((a) =>
          el("tr", {}, el("td", { class: "num", text: a.id }), el("td", { text: a.text }), el("td", { class: "meta", text: a.rationale })))));
      break;
    case "ENGINEERING_DECISION": {
      box.append(msgHead("agent", chip("engineering decision", "t-decision"), m.title), el("div", { class: "msg-text", text: m.text }));
      if (m.load_case) box.append(el("div", { class: "meta", text:
        `Load case: ${m.load_case.description} (F=${m.load_case.force_n} N, arm ${m.load_case.lever_arm_mm} mm, SF≥${m.load_case.required_safety_factor}; trace ${m.load_case.trace.join(", ")})` }));
      const t = el("table", { class: "kv" }, el("tr", {}, ...["Parameter", "Value", "Source", "Trace", "Rationale"].map((h) => el("th", { text: h }))));
      for (const p of m.items) {
        t.append(el("tr", {}, el("td", { class: "num", text: p.name }), el("td", { class: "num", text: `${p.value} ${p.unit}` }),
          el("td", {}, sourceChip(p.source)), el("td", { class: "num", text: p.trace.join(", ") }), el("td", { class: "meta", text: p.rationale })));
      }
      box.append(t);
      break;
    }
    case "VALIDATION": {
      box.append(msgHead("agent", chip("evidence", "t-verified"), m.title));
      const g = el("div", { class: "evidence" });
      for (const v of m.items) {
        g.append(chip(v.label, statusClass(v.status)),
          el("div", { class: "claim" }, `${v.check_id}: ${v.claim}`, el("small", { text: [v.severity, fmt(v.measured), v.message].filter(Boolean).join(" · ") })));
      }
      box.append(g);
      break;
    }
    case "REVIEW":
      box.append(msgHead("agent", chip("review", "t-decision"), m.title), el("div", { class: "msg-text", text: m.text }));
      break;
    case "RESULT":
      box.append(msgHead("agent", chip("result", "t-fail"), m.title), el("div", { class: "msg-text", text: m.text }));
      break;
    default:
      box.append(msgHead(m.role, chip(m.layer.toLowerCase(), "t-system"), m.title), el("div", { class: "msg-text", text: m.text || "" }));
  }
  return box;
}

function renderChat(v) {
  const chat = $("chat");
  const atBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 80;
  if (!v) {
    chat.replaceChildren(el("div", { class: "msg agent" },
      msgHead("agent", chip("ready", "t-decision"), "Engineering workflow"),
      el("div", { class: "msg-text", text:
        "Describe the component you need. I will extract requirements, ask for critical information I do not have, " +
        "state my assumptions, plan the design, build it in Fusion 360, validate it and report exactly what is verified, " +
        "assumed and not verified.\n\nCurrently supported: machined L-bracket (prototype)." }),
      el("div", { class: "meta" }, "Example: ", el("span", { class: "example", text: EXAMPLE, onclick: () => { $("input").value = EXAMPLE; $("input").focus(); } }))));
    return;
  }
  const items = v.messages.map(renderMessage);
  if (v.busy || v.status === "REASONING" || v.status === "IN_PROGRESS") {
    const what = v.status === "REASONING" && v.pending_reasoning ? `reasoning (${v.pending_reasoning.kind})` : `working · ${v.stage}`;
    items.push(el("div", { class: "msg system" }, msgHead("system", chip("working", "t-system"), `Agent ${what}…`),
      el("div", { class: "meta", text: "Automatic reasoning steps take roughly 20–60 s; CAD and inspection a few seconds." })));
  }
  if (v.status === "AWAITING_REASONING" && v.pending_reasoning) {
    items.push(el("div", { class: "msg system" }, msgHead("system", chip("file exchange", "t-assumption"), "Waiting for an external reasoner"),
      el("div", { class: "msg-text", text: `A reasoning task was written to ${v.pending_reasoning.request}. Answer it (e.g. from a Claude Code session), then press “Check again”.` })));
  }
  if (v.status === "BLOCKED_FUSION") {
    items.push(el("div", { class: "msg system" }, msgHead("system", chip("fusion offline", "t-fail"), "Fusion 360 not reachable"),
      el("div", { class: "msg-text", text: "Start Fusion 360 and enable Preferences › General › API › Fusion MCP Server, then press “Check again”." })));
  }
  if (v.error) items.push(el("div", { class: "msg system" }, msgHead("system", chip("error", "t-fail"), "Backend error"), el("div", { class: "msg-text", text: v.error })));
  chat.replaceChildren(...items);
  if (atBottom || S.sending) chat.scrollTop = chat.scrollHeight;
}

// ---------------------------------------------------------------- side panel
function kv(k, val) { return el("div", { class: "kvline" }, el("span", { text: k }), el("span", { class: "mono", text: val })); }

function renderPanel(v) {
  $("p-task").textContent = v ? v.request : "No task selected.";
  $("p-task").className = v ? "" : "muted";
  $("p-stage").textContent = v ? v.stage : "-";
  $("p-status").textContent = v ? (v.busy && v.status !== "REASONING" ? "WORKING" : v.status) : "-";
  const comp = $("p-component");
  if (v && v.component) {
    const c = v.component;
    comp.className = "";
    comp.replaceChildren(kv("ID", c.id), kv("Revision", `rev ${c.revision}`), kv("Lifecycle", c.lifecycle), kv("Mass", `${c.mass_kg} kg`),
      ...c.interfaces.map((i) => el("div", { class: "kvline" }, el("span", { text: i.id }),
        el("span", { class: "chips" }, chip(`HOLE_GEOMETRY_${i.hole_geometry}`, statusClass(i.hole_geometry)), chip(`MATING_${i.mating}`, statusClass(i.mating))))));
  } else {
    comp.className = "muted";
    comp.textContent = v && v.component_id ? `${v.component_id} (reserved, not registered)` : "-";
  }
  const val = $("p-validation");
  if (v && v.validation) {
    val.className = "";
    const entries = Object.entries(v.validation.labels).sort();
    val.replaceChildren(el("div", { class: "chips" }, ...entries.map(([lab, n]) => chip(n > 1 ? `${lab} ×${n}` : lab, statusClass(labelStatus(lab))))),
      el("div", { class: "meta", text: v.validation.blocking_failures.length ? `Blocking failures: ${v.validation.blocking_failures.join(", ")}` : "No blocking failures." }));
  } else { val.className = "muted"; val.textContent = "Not validated yet."; }
  const fia = $("p-fia");
  if (v && v.validation && v.validation.fia) { fia.className = ""; fia.replaceChildren(chip(v.validation.fia, statusClass(labelStatus(v.validation.fia)))); }
  else { fia.className = "muted"; fia.textContent = "Not evaluated"; }
  const ul = $("p-assumptions");
  ul.replaceChildren(...(v && v.assumptions.length ? v.assumptions.map((a) => el("li", {}, el("b", { text: a.id }), a.text))
    : [el("li", { class: "muted", text: "None." })]));
  const out = $("p-outputs");
  if (v && (v.has_report || v.has_screenshot)) {
    out.className = "";
    out.replaceChildren(
      v.has_report ? el("a", { href: `/api/runs/${v.run_id}/report`, target: "_blank", text: "Engineering report (report.md)" }) : null,
      v.has_screenshot ? el("img", { class: "shot", alt: "Fusion 360 screenshot", src: `/api/runs/${v.run_id}/screenshot` }) : null);
  } else { out.className = "muted"; out.textContent = "-"; }
  $("p-log").replaceChildren(...(v ? v.reasoning_log.map((t) => el("li", { text: t })) : []));
}

// ---------------------------------------------------------------- composer
function composerMode(v) {
  if (!v || v.status === "COMPLETED" || v.status === "STOPPED") return { mode: "request" };
  if (v.busy || ["REASONING", "IN_PROGRESS"].includes(v.status)) return { mode: "busy" };
  if (v.status === "AWAITING_USER" && v.open_questions.length) return { mode: "answer", q: v.open_questions[0] };
  if (v.status === "AWAITING_REASONING" || v.status === "BLOCKED_FUSION") return { mode: "retry" };
  return { mode: "busy" };
}

// ---------------------------------------------------------------- image attachments (request only)
function renderAttachments() {
  const box = $("attach-previews");
  box.hidden = !S.files.length;
  box.replaceChildren(...S.files.map((f, i) => el("div", { class: "att" },
    el("img", { src: f.dataUrl, alt: f.name }),
    el("span", { text: `${f.name} · ${(f.size / 1024).toFixed(0)} kB` }),
    el("button", { type: "button", title: "Remove", text: "×", onclick: () => { S.files.splice(i, 1); renderAttachments(); } }))));
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(new Error(`cannot read ${file.name}`));
    r.readAsDataURL(file);
  });
}

async function onFilesChosen(ev) {
  const hint = $("composer-hint");
  for (const file of Array.from(ev.target.files || [])) {
    if (!IMAGE_TYPES.includes(file.type)) { hint.textContent = `${file.name}: only PNG, JPEG, GIF or WebP images.`; continue; }
    if (file.size > MAX_IMAGE_BYTES) { hint.textContent = `${file.name}: larger than 5 MB.`; continue; }
    if (S.files.length >= MAX_IMAGES) { hint.textContent = `At most ${MAX_IMAGES} images per request.`; break; }
    const dataUrl = await readFile(file);
    S.files.push({ name: file.name, size: file.size, type: file.type, dataUrl });
  }
  ev.target.value = "";
  renderAttachments();
}

function renderComposer(v) {
  const m = composerMode(v);
  const modeEl = $("composer-mode"), input = $("input"), send = $("btn-send"), retry = $("btn-retry"), hint = $("composer-hint");
  retry.hidden = m.mode !== "retry";
  $("btn-attach").disabled = m.mode !== "request";
  if (m.mode !== "request" && S.files.length) { S.files = []; renderAttachments(); }
  modeEl.className = "composer-mode" + (m.mode === "answer" ? " answer" : "");
  if (m.mode === "request") {
    modeEl.textContent = v ? "Run finished · start a new engineering request" : "New engineering request";
    input.disabled = false; send.disabled = false; send.textContent = "Send";
    input.placeholder = "Describe the component you need...";
    hint.textContent = "Engineering requests only (supported now: machined L-bracket). Optional: attach a sketch or drawing — values read from it are shown as IMAGE evidence, not as your words.";
  } else if (m.mode === "answer") {
    modeEl.textContent = `Answer to ${m.q.id}${m.q.follows_up ? ` (clarifies ${m.q.follows_up})` : ""} · stored verbatim`;
    input.disabled = false; send.disabled = false; send.textContent = `Answer ${m.q.id}`;
    input.placeholder = "Your answer in your own words...";
    hint.textContent = "Your exact words become the authoritative USER ANSWER. The agent's reading of it is shown separately as AI interpretation.";
  } else if (m.mode === "retry") {
    modeEl.textContent = v.status === "BLOCKED_FUSION" ? "Waiting for Fusion 360" : "Waiting for an external reasoner";
    input.disabled = true; send.disabled = true; hint.textContent = "";
  } else {
    modeEl.textContent = "Agent working…";
    input.disabled = true; send.disabled = true; hint.textContent = "";
  }
  return m;
}

async function onSubmit(ev) {
  ev.preventDefault();
  const text = $("input").value.trim();
  if (!text || S.sending) return;
  const m = composerMode(S.view);
  S.sending = true; $("btn-send").disabled = true;
  try {
    if (m.mode === "answer") {
      await api(`/api/runs/${S.runId}/answer`, { method: "POST", body: JSON.stringify({ question_id: m.q.id, text }) });
    } else if (m.mode === "request") {
      const attachments = S.files.map((f) => ({ filename: f.name, data_base64: f.dataUrl.split(",", 2)[1] }));
      const r = await api("/api/runs", { method: "POST", body: JSON.stringify({ request: text, attachments }) });
      S.runId = r.run_id;
      S.files = []; renderAttachments();
      await loadRuns();
    }
    $("input").value = "";
    await refresh();
  } catch (e) {
    $("composer-hint").textContent = `Not sent: ${e.message}`;
  } finally { S.sending = false; }
}

// ---------------------------------------------------------------- data flow
async function loadRuns() {
  const runs = await api("/api/runs");
  const sel = $("run-select");
  sel.replaceChildren(el("option", { value: "", text: "New engineering task" }),
    ...runs.map((r) => el("option", { value: r.run_id, text: `${r.run_id} · ${r.status}${r.component ? " · " + r.component : ""}` })));
  sel.value = S.runId || "";
}

function render() {
  const v = S.view;
  renderPipeline(v); renderChat(v); renderPanel(v); renderComposer(v);
  $("toolbar-note").textContent = v ? `${v.run_id} · loops ${v.loops}` : "";
}

async function refresh() {
  clearTimeout(S.pollTimer);
  try {
    S.view = S.runId ? await api(`/api/runs/${S.runId}`) : null;
  } catch (e) { S.view = null; $("toolbar-note").textContent = e.message; }
  render();
  const v = S.view;
  const active = v && (v.busy || ["REASONING", "IN_PROGRESS"].includes(v.status));
  S.pollTimer = setTimeout(refresh, active ? 1500 : 6000);
}

async function refreshStatus() {
  try { S.status = await api("/api/status"); } catch { S.status = null; }
  renderStatus();
  setTimeout(refreshStatus, 20000);
}

window.addEventListener("DOMContentLoaded", async () => {
  $("composer").addEventListener("submit", onSubmit);
  $("btn-attach").addEventListener("click", () => $("file-input").click());
  $("file-input").addEventListener("change", onFilesChosen);
  $("input").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onSubmit(e); });
  $("btn-new").addEventListener("click", () => { S.runId = null; $("run-select").value = ""; refresh(); });
  $("run-select").addEventListener("change", (e) => { S.runId = e.target.value || null; refresh(); });
  $("btn-retry").addEventListener("click", async () => {
    try { await api(`/api/runs/${S.runId}/advance`, { method: "POST", body: "{}" }); } catch (e) { $("composer-hint").textContent = e.message; }
    refresh();
  });
  S.runId = new URLSearchParams(location.search).get("run") || null;   // optional deep link: /?run=<id>
  await refreshStatus();
  try { await loadRuns(); } catch (e) { $("toolbar-note").textContent = e.message; }
  if (document.body.classList.contains("read-only") && !S.runId && $("run-select").options.length > 1) {
    S.runId = $("run-select").options[1].value; $("run-select").value = S.runId;   // read-only: open the latest run
  }
  refresh();
});
