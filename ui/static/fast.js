// AI Engineering Agent - fast mode page. Presentation only: all state comes from /api/design (agent.design_service).
// All user/AI text is inserted with textContent (never innerHTML).
"use strict";

const S = { runId: null, view: null, pollTimer: null, files: [], sending: false, openPart: null, drafts: {}, partsSig: null, revSig: null };
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

const STATUS_CLASS = { VERIFIED: "t-verified", NOT_VERIFIED: "t-notver", NON_COMPLIANT: "t-fail", ASSUMPTION: "t-assumption",
  NOT_APPLICABLE: "t-notver", done: "t-verified", failed: "t-fail", building: "t-assumption", todo: "t-notver" };
const chip = (text, cls, title) => el("span", { class: `tag ${cls || ""}`, text, title });
const fmtBox = (b) => b ? b.map((p) => "(" + p.map((v) => Math.round(v)).join(", ") + ")").join(" → ") : "—";

// ---------------------------------------------------------------- header
async function refreshStatus() {
  let st = null;
  try { st = await api("/api/status"); } catch { st = null; }
  const pb = $("pill-backend"), pr = $("pill-reasoner"), pf = $("pill-fusion");
  pb.className = "pill " + (st ? "ok" : "bad");
  pb.lastChild.textContent = st ? "Backend" : "Backend offline";
  document.body.classList.toggle("read-only", !!(st && st.read_only));
  if (st) {
    const claude = st.reasoner && st.reasoner.mode === "claude_code" && st.reasoner.available;
    pr.className = "pill " + (claude ? "ok" : "bad");
    pr.lastChild.textContent = claude ? "Claude Code" : "Claude unavailable";
    pr.title = st.reasoner ? st.reasoner.detail : "";
    const f = st.fusion;
    pf.className = "pill " + (f.connected ? "ok" : "bad");
    pf.lastChild.textContent = f.connected ? `Fusion 360 · ${f.version || "connected"}` : "Fusion 360 · offline";
    pf.title = f.connected ? `Active document at last check: ${f.document || "none"}` : f.error || "";
  }
  setTimeout(refreshStatus, 20000);
}

// ---------------------------------------------------------------- progress strip
const EMPTY_STRIP = [{ label: "Plan", state: "todo" }, { label: "Parts", state: "todo",
  chips: ["MON-001", "FWG-001", "FLR-001", "RWG-001"].map((id) => ({ id, state: "todo" })) },
  { label: "Assemble", state: "todo" }, { label: "Check", state: "todo" }, { label: "Done", state: "todo" }];
const STEP_NOTE = { done: "done", current: "in progress", waiting: "waiting for you", blocked: "blocked", failed: "failed", todo: "" };

function renderStrip(v) {
  const steps = v ? v.strip : EMPTY_STRIP;
  $("strip").replaceChildren(...steps.map((s, i) => el("div", { class: `step ${s.state}` },
    `${i + 1}. ${s.label}`, el("small", { text: STEP_NOTE[s.state] || "" }),
    s.chips ? el("span", { class: "part-chips" }, ...s.chips.map((c) => chip(c.id, `${STATUS_CLASS[c.state] || "t-notver"} ${c.state}`, c.state))) : null)));
}

// ---------------------------------------------------------------- main area
function renderBanner(v) {
  const show = v && (v.banner || v.status === "BLOCKED_FUSION");
  $("banner").hidden = !show;
  if (!show) return;
  $("banner-title").textContent = /output|budget/i.test(v.error || "") ? "Restart Fusion" : "Fusion needed";
  $("banner-text").textContent = `${v.banner || ""} (${v.error || ""})`;
  $("btn-continue").disabled = v.busy;
}

function renderQuestion(v) {
  $("qcard").hidden = !(v && v.question);
  if (v && v.question) $("q-text").textContent = v.question.text;
}

function renderWorking(v) {
  const w = $("working");
  if (v && (v.busy || v.status === "RUNNING")) {
    w.hidden = false;
    w.textContent = `Working · ${v.phase} · ${v.log.length ? v.log[v.log.length - 1] : ""}`;
  } else if (v && v.status === "FAILED") {
    w.hidden = false; w.textContent = `Run failed: ${v.error || ""}`;
  } else if (v && v.error && !v.banner) {
    w.hidden = false; w.textContent = `Error: ${v.error}`;
  } else w.hidden = true;
}

// ---------------------------------------------------------------- revise / revert (agent/revise.py via the service)
const fmtVec = (a) => a ? "(" + a.map((x) => (Math.round(x * 10) / 10).toString()).join(", ") + ")" : "—";

function reviseRow(p, v) {
  const ta = el("textarea", { rows: "2", placeholder: `Revise ${p.id} in words, e.g. "make the span 1700 mm" (one Claude call; only what you ask changes)` });
  ta.value = S.drafts[p.id] || "";
  ta.addEventListener("input", () => { S.drafts[p.id] = ta.value; });
  const can = p.revisable && v.revisable;
  const go = el("button", { type: "button", text: `Revise ${p.id}`, disabled: !can, onclick: async () => {
    const text = ta.value.trim();
    if (!text) return;
    await post(`/api/design/${v.run_id}/revise`, { target: p.id, instruction: text });
    S.drafts[p.id] = ""; S.partsSig = null;
  } });
  const reverts = (p.revert_versions || []).map((n) => el("button", { type: "button", class: "ghost small", text: `Revert to v${n}`,
    disabled: !can, title: `Rebuild v${n} in this run's Fusion design, verify it, and register it as a NEW version (history is kept)`,
    onclick: () => { if (window.confirm(`Revert ${p.id} to v${n}? It is rebuilt in the Fusion design and registered as a new version.`)) post(`/api/design/${v.run_id}/revert`, { part_id: p.id, version: n }); } }));
  return el("tr", { class: "revise-row" }, el("td", { colspan: "6" }, el("div", { class: "revise-box" }, ta,
    el("div", { class: "revise-actions" }, go, ...reverts,
      el("span", { class: "meta", text: `active v${p.active_version ?? "?"}` + (can ? "" : " · revise needs a finished, idle run") })))));
}

function revisionCard(r, v, open) {
  const c = r.counters || {};
  const body = [
    el("div", { class: "msg-text verbatim", text: r.instruction }),
    r.steps.length ? el("ul", {}, ...r.steps.map((s) => el("li", {},
      el("b", { text: `${s.part_id} v${s.base_version} → ${s.new_version ? "v" + s.new_version : "—"}` }), ` ${s.change_summary || ""}`,
      s.bbox_delta ? el("span", { class: "meta", text: ` · bbox Δmin ${fmtVec(s.bbox_delta.min)} Δmax ${fmtVec(s.bbox_delta.max)} mm` }) : null,
      ...(s.assumptions || []).map((a) => el("div", {}, chip("ASSUMPTION", "t-assumption"), " ", a))))) : null,
    r.neighbour_adjustments.length ? el("ul", {}, ...r.neighbour_adjustments.map((a) => el("li", {}, chip("NEIGHBOUR POSE", "t-decision"),
      ` ${a.part_id} ${fmtVec(a.position_from)} → ${fmtVec(a.position_to)} mm`, a.new_version ? ` (v${a.base_version} → v${a.new_version})` : "",
      el("div", { class: "meta", text: a.reason }))) ) : null,
    r.mates.length ? el("div", {}, ...r.mates.map((m) => el("div", { class: "asm-row" }, chip(m.label || m.status, STATUS_CLASS[m.status]),
      el("span", { text: ` ${m.title}` }), el("span", { class: "meta", text: ` before ${m.before || "—"} · ${m.measured ? JSON.stringify(m.measured) : ""} ${m.message || ""}` })))) : null,
    (r.mate_faces || []).length ? el("div", {}, el("div", { class: "meta", text: "Mate faces (advisory, from bounding boxes; the Fusion mate measurement decides)" }),
      ...r.mate_faces.map((f) => el("div", { class: "asm-row" }, chip(f.status, f.status === "PASS" ? "t-verified" : f.status === "WARNING" ? "t-assumption" : "t-notver"),
        el("span", { class: "meta", text: ` ${f.face} · ${f.note}` })))) : null,
    r.rollback ? el("div", { class: r.rollback.verified ? "meta" : "crit", text: `Rollback: ${r.rollback.verified ? "verified" : "NOT verified"} · ` +
      r.rollback.parts.map((x) => `${x.part_id} v${x.restored_version} ${x.passed ? "restored" : "FAILED"}`).join(", ") }) : null,
    r.error ? el("div", { class: r.state === "CRITICAL" ? "crit" : "meta err", text: r.error }) : null,
    ...r.notes.map((n) => el("div", { class: "meta", text: n })),
    r.pairs.length ? el("div", { class: "pairs" }, ...r.pairs.map((pp) => el("div", { class: "pair" },
      pp.before ? el("figure", {}, el("a", { href: pp.before, target: "_blank" }, el("img", { src: pp.before, alt: `${pp.view} before` })), el("figcaption", { text: `${pp.view} · before` }))
        : el("div", { class: "none", text: `no ${pp.view} picture before` }),
      el("figure", {}, el("a", { href: pp.after, target: "_blank" }, el("img", { src: pp.after, alt: `${pp.view} after` })), el("figcaption", { text: `${pp.view} · after` }))))) : null,
    r.stale_run_views.length ? el("div", { class: "meta", text: `Run pictures not re-shot (no change in their plane): ${r.stale_run_views.join(", ")}` }) : null,
    r.state === "RUNNING" ? el("ol", { class: "log" }, ...r.events.map((t) => el("li", { text: t }))) : null,
    el("div", { class: "meta", text: `Claude calls ${c.claude_calls ?? 0} · Fusion script calls ${c.script_calls ?? 0} · MCP wrapper depth ${c.depth_first ?? "?"} → ${c.depth_last ?? "?"}` }),
  ];
  const head = el("summary", {}, chip(r.state, r.state === "DONE" ? "t-verified" : r.state === "RUNNING" ? "t-assumption" : r.state === "REJECTED" ? "t-notver" : "t-fail"),
    el("b", { text: ` ${r.id} · ${r.kind} ${r.target}` }), el("span", { class: "meta", text: ` ${r.created || ""}` }));
  return el("details", { class: `rev-card s-${r.state}`, open: open ? "" : null }, head, ...body);
}

function renderRevisions(v) {
  const revs = (v.revisions || []).slice().reverse();
  $("revisions-head").hidden = !revs.length;
  const sig = JSON.stringify(revs);
  if (sig === S.revSig) return;
  S.revSig = sig;
  $("revisions").replaceChildren(...revs.map((r, i) => revisionCard(r, v, i === 0)));
}

function partRow(p, v) {
  const checks = el("span", { class: "chips" }, ...p.checks.map((c) => chip(c.id.replace("PART-", ""), STATUS_CLASS[c.status], c.title || `${c.id}: ${c.status} ${c.message || ""}`)));
  const fia = el("span", { class: "chips" }, ...p.fia.map((f) => chip(f.label || `${f.article} ${f.status}`, STATUS_CLASS[f.status], `${f.tooltip || f.note}\n\n“${f.text}”`)));
  const btn = el("button", { type: "button", class: "ghost small", text: "Rebuild", disabled: !p.rebuildable || v.busy || !v.terminal,
    title: "Rebuild from the stored script (no Claude call), then re-measure and re-shoot",
    onclick: async () => { try { await api(`/api/design/${v.run_id}/rebuild`, { method: "POST", body: JSON.stringify({ part_id: p.id }) }); } catch (e) { $("toolbar-note").textContent = e.message; } refresh(); } });
  const dv = p.derived;
  const rederive = dv && dv.stale ? el("button", { type: "button", class: "ghost small", text: `Re-derive from ${dv.source_id} v${dv.latest_source_version}`,
    disabled: v.busy || !v.terminal, title: "Rebuild this mirrored part from the source's latest version (no Claude call; a new version, history kept)",
    onclick: async () => { try { await api(`/api/design/${v.run_id}/rebuild-mirror`, { method: "POST", body: JSON.stringify({ part_id: p.id }) }); } catch (e) { $("toolbar-note").textContent = e.message; } refresh(); } }) : null;
  const derivedTag = dv ? [chip(dv.mode === "yaw180" ? "YAW180" : "MIRROR", "t-decision", `derived from ${dv.source_id}${dv.source_version ? " v" + dv.source_version : ""} (${dv.mode}); zero Claude calls`),
    dv.stale ? chip("STALE", "t-assumption", `${dv.source_id} is now v${dv.latest_source_version}; this part was derived from v${dv.source_version}`) : null] : [];
  const open = S.openPart === p.id;
  return el("tr", { class: `${p.revisable ? "clickable" : ""} ${open ? "open" : ""}`, title: p.revisable ? "Click to revise / revert this part" : null,
    onclick: (e) => { if (!p.revisable || e.target.closest("button, a")) return; S.openPart = open ? null : p.id; S.partsSig = null; renderResults(S.view); } },
    el("td", { class: "num" }, el("b", { text: p.id }), el("div", { class: "meta", text: p.name })),
    el("td", {}, chip(p.state.toUpperCase(), STATUS_CLASS[p.state]), p.reuse ? chip("REUSED", "t-decision") : null, ...derivedTag,
      p.version ? el("div", { class: "meta", text: `v${p.version} · ${p.attempts.join(" → ")}` }) : null,
      p.error ? el("div", { class: "meta err", text: p.error }) : null),
    el("td", { class: "num", text: fmtBox(p.bbox) }),
    el("td", {}, checks), el("td", {}, fia), el("td", {}, btn, rederive));
}

function renderResults(v) {
  const r = $("results");
  const show = v && (v.parts.length && (v.terminal || v.status === "BLOCKED_FUSION" || Object.keys(v.screenshots).length));
  r.hidden = !show;
  if (!show) return;
  const bust = `?t=${encodeURIComponent(v.counters.script_calls)}`;
  for (const view of ["iso", "front", "top"]) {
    const img = $(`shot-${view}`), link = $(`${view}-link`);
    if (v.screenshots[view]) { img.src = v.screenshots[view] + bust; link.href = v.screenshots[view]; img.hidden = false; }
    else { img.removeAttribute("src"); img.hidden = true; }
  }
  const partsSig = JSON.stringify([v.parts, v.busy, v.terminal, v.revisable, S.openPart]);
  if (partsSig !== S.partsSig) {                 // re-render only on change: an open Revise box keeps focus and text
    S.partsSig = partsSig;
    $("parts-table").replaceChildren(
      el("tr", {}, ...["Part", "State", "World bbox (mm)", "Checks", "FIA", ""].map((h) => el("th", { text: h }))),
      ...v.parts.flatMap((p) => S.openPart === p.id ? [partRow(p, v), reviseRow(p, v)] : [partRow(p, v)]));
  }
  $("btn-revise-asm").disabled = !v.revisable;
  renderRevisions(v);
  const asm = $("assembly");
  asm.replaceChildren(
    el("div", { class: "meta", text: v.assembly_method || "" }),
    ...v.assembly.map((a) => el("div", { class: "asm-row" }, chip(a.label || a.status, STATUS_CLASS[a.status]),
      el("span", { text: ` ${a.title}` }), el("span", { class: "meta", text: ` ${a.measured ? JSON.stringify(a.measured) : ""} ${a.message || ""}` }))),
    ...(v.mate_faces || []).map((f) => el("div", { class: "asm-row" }, chip(f.status, f.status === "PASS" ? "t-verified" : f.status === "WARNING" ? "t-assumption" : "t-notver"),
      el("span", { text: ` mate face ${f.face}` }), el("span", { class: "meta", text: ` (advisory) ${f.note}` }))),
    ...v.skipped_mates.map((m) => el("div", { class: "asm-row" }, chip("NOT_VERIFIED", "t-notver"), el("span", { text: ` ${m.a} / ${m.b}: a part was not built` }))));
  $("assumptions").replaceChildren(...(v.assumptions.length ? v.assumptions.map((a) => el("li", {}, el("b", { text: a.id }), chip("ASSUMPTION", "t-assumption"), " ", a.text))
    : [el("li", { class: "muted", text: "None." })]));
  const vr = $("visual-review-box");
  vr.replaceChildren(...(v.visual_review_issues ? [el("h2", { class: "section", text: "Visual review (advisory, AI)" }),
    el("ul", { class: "assumption-list" }, ...(v.visual_review_issues.length ? v.visual_review_issues.map((t) => el("li", { text: t })) : [el("li", { class: "muted", text: "No issues reported." })]))] : []));
  $("btn-rebuild-assembly").disabled = v.busy || !v.terminal;
  $("btn-recolor").disabled = v.busy || !v.terminal;
  renderRender(v);
  const rc = (v.recolors || []).slice(-1)[0];
  $("recolor-note").textContent = !rc ? "" : rc.error ? `${rc.id}: palette not applied - ${rc.error}`
    : `${rc.id}: ${rc.parts - rc.mismatches.length}/${rc.parts} parts recoloured` + (rc.mismatches.length ? ` · mismatch: ${rc.mismatches.join("; ")}` : "")
      + (rc.notes.length ? ` · ${rc.notes.join("; ")}` : "");
  $("rebuild-note").textContent = v.mode === "assembly_rebuild"
    ? `Assembly rebuild of ${v.source_run}${v.correction ? " · correction: " + v.correction.reason : ""}` : "";
  const c = v.counters;
  $("counts").replaceChildren(`Claude calls ${c.claude_calls} · Fusion script calls ${c.script_calls} · MCP wrapper depth ${c.depth_first ?? "?"} → ${c.depth_last ?? "?"} · `,
    v.has_summary ? el("a", { href: `/api/design/${v.run_id}/summary`, target: "_blank", text: "summary.md" }) : "");
}

const fmtBytes = (n) => n == null ? "?" : n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round(n / 1024)} kB`;
const RENDER_STATE = { pending: "waiting", starting: "starting", queued: "queued", processing: "processing",
  finished: "finished", fallback: "screenshot fallback", failed: "failed", refused: "refused", skipped: "skipped" };

// Render: controls, live progress of the latest render (queued / processing n% / finished) and its images, large.
function renderRender(v) {
  $("btn-render").disabled = v.busy || !v.terminal;
  const envSel = $("render-env"), envs = v.render_environments || [];
  const envSig = JSON.stringify(envs);
  if (envSel.dataset.sig !== envSig) {                 // only names Fusion listed; never guessed
    const keep = envSel.value;
    envSel.replaceChildren(el("option", { value: "", text: "default scene" }), ...envs.map((n) => el("option", { value: n, text: n })));
    envSel.value = envs.includes(keep) ? keep : "";
    envSel.dataset.sig = envSig;
  }
  envSel.hidden = !envs.length;
  const rd = (v.renders || []).slice(-1)[0];
  $("render-status").hidden = !rd;
  if (rd) {
    const cur = rd.items.find((i) => !["finished", "fallback", "failed", "refused", "skipped"].includes(i.state));
    const done = rd.items.filter((i) => ["finished", "fallback", "failed", "refused", "skipped"].includes(i.state)).length;
    const prog = cur ? (done + (cur.progress || 0)) / rd.items.length : 1;
    $("render-progress").value = prog;
    const o = rd.options || {};
    $("render-note").textContent = `${rd.id} (${rd.preset || "quality " + rd.quality}${o.camera ? ", " + o.camera + (o.camera === "perspective" ? " " + o.focal_mm + " mm" : "") : ""}${rd.environment ? ", " + rd.environment : ""}${o.background ? ", bg " + o.background : ""}): `
      + rd.items.map((i) => `${i.view} ${RENDER_STATE[i.state] || i.state}` + (i.state === "processing" ? ` ${Math.round((i.progress || 0) * 100)}%` : "")
        + (i.seconds != null ? ` (${i.seconds} s)` : "")).join(" · ")
      + (rd.seconds != null && rd.finished ? ` · total ${rd.seconds} s` : "") + (rd.error ? ` · ${rd.error}` : "");
    $("render-note").className = rd.status === "refused" || rd.status === "failed" ? "meta err" : "meta";
  }
  const box = $("render-box");
  const shown = rd ? rd.items.filter((i) => i.url) : [];
  const sig = JSON.stringify(shown.map((i) => [rd.id, i.view, i.url, i.method, i.size_bytes]));
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  box.hidden = !shown.length;
  box.replaceChildren(...shown.map((i) => el("figure", {},
    el("a", { href: i.url, target: "_blank" }, el("img", { src: `${i.url}?t=${encodeURIComponent(rd.id + i.size_bytes)}`, alt: `${i.view} ${i.method}` })),
    el("figcaption", { class: i.method === "render" ? "" : "fallback" },
      `${rd.id} ${i.view} · ${i.method === "render" ? "render" : "SCREENSHOT FALLBACK (not a render)"} · ${rd.preset || ""} · ${i.width}×${i.height} · ${fmtBytes(i.size_bytes)} · quality ${i.quality} · ${i.seconds} s`
        + (i.method !== "render" && i.error ? ` · reason: ${i.error}` : "") + (i.note ? ` · ${i.note}` : ""),
      i.url_full ? el("span", {}, " · ", el("a", { href: i.url_full, target: "_blank", text: `full render ${(i.full_size || []).join("×")}` })) : null))));
}

function render() {
  const v = S.view;
  renderStrip(v); renderBanner(v); renderQuestion(v); renderWorking(v); renderResults(v);
  $("brief-form").hidden = !!v;
  $("p-brief").textContent = v ? v.brief : "No run selected.";
  $("p-brief").className = v ? "" : "muted";
  $("log").replaceChildren(...(v ? v.log.map((t) => el("li", { text: t })) : []));
  $("toolbar-note").textContent = v ? `${v.run_id} · ${v.status}` : "";
}

function resetRunState() { S.openPart = null; S.drafts = {}; S.partsSig = null; S.revSig = null; }

// ---------------------------------------------------------------- attachments
function renderAttachments() {
  const box = $("attach-previews");
  box.hidden = !S.files.length;
  box.replaceChildren(...S.files.map((f, i) => el("div", { class: "att" },
    el("img", { src: f.dataUrl, alt: f.name }), el("span", { text: `${f.name} · ${(f.size / 1024).toFixed(0)} kB` }),
    el("button", { type: "button", title: "Remove", text: "×", onclick: () => { S.files.splice(i, 1); renderAttachments(); } }))));
}
const readFile = (file) => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = () => rej(new Error(`cannot read ${file.name}`)); r.readAsDataURL(file); });
async function onFilesChosen(ev) {
  for (const file of Array.from(ev.target.files || [])) {
    if (!IMAGE_TYPES.includes(file.type)) { $("brief-hint").textContent = `${file.name}: only PNG, JPEG, GIF or WebP images.`; continue; }
    if (file.size > MAX_IMAGE_BYTES) { $("brief-hint").textContent = `${file.name}: larger than 5 MB.`; continue; }
    if (S.files.length >= MAX_IMAGES) { $("brief-hint").textContent = `At most ${MAX_IMAGES} images.`; break; }
    S.files.push({ name: file.name, size: file.size, type: file.type, dataUrl: await readFile(file) });
  }
  ev.target.value = ""; renderAttachments();
}

// ---------------------------------------------------------------- actions
async function onRun(ev) {
  ev.preventDefault();
  const brief = $("brief").value.trim();
  if (!brief || S.sending) return;
  S.sending = true; $("btn-run").disabled = true;
  try {
    const attachments = S.files.map((f) => ({ filename: f.name, data_base64: f.dataUrl.split(",", 2)[1] }));
    const r = await api("/api/design", { method: "POST", body: JSON.stringify({ brief, attachments, visual_review: $("visual-review").checked }) });
    S.runId = r.run_id; S.files = []; renderAttachments(); $("brief").value = "";
    await loadRuns(); await refresh();
  } catch (e) { $("brief-hint").textContent = `Not started: ${e.message}`; }
  finally { S.sending = false; $("btn-run").disabled = false; }
}

async function post(path, body) {
  try { await api(path, { method: "POST", body: JSON.stringify(body || {}) }); } catch (e) { $("toolbar-note").textContent = e.message; }
  refresh();
}

async function loadRuns() {
  const runs = await api("/api/design");
  $("run-select").replaceChildren(el("option", { value: "", text: "New design" }),
    ...runs.map((r) => el("option", { value: r.run_id, text: r.label })));
  $("run-select").value = S.runId || "";
}

// The option list is a cache of /api/design: when the polled view's label differs from the selected option (the run
// finished, a revision or rebuild changed its status), reload the list from the server instead of keeping stale text.
function syncRunOption(v) {
  if (!v) return;
  const opt = Array.from($("run-select").options).find((o) => o.value === v.run_id);
  if (!opt || opt.textContent !== v.run_label) loadRuns().catch((e) => { $("toolbar-note").textContent = e.message; });
}

async function refresh() {
  clearTimeout(S.pollTimer);
  try { S.view = S.runId ? await api(`/api/design/${S.runId}`) : null; }
  catch (e) { S.view = null; $("toolbar-note").textContent = e.message; }
  render();
  syncRunOption(S.view);
  const v = S.view;
  S.pollTimer = setTimeout(refresh, v && (v.busy || v.status === "RUNNING") ? 1500 : 6000);
}

window.addEventListener("DOMContentLoaded", async () => {
  $("brief-form").addEventListener("submit", onRun);
  $("brief").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onRun(e); });
  $("btn-attach").addEventListener("click", () => $("file-input").click());
  $("file-input").addEventListener("change", onFilesChosen);
  $("btn-new").addEventListener("click", () => { S.runId = null; $("run-select").value = ""; resetRunState(); refresh(); });
  $("run-select").addEventListener("change", (e) => { S.runId = e.target.value || null; resetRunState(); refresh(); });
  $("btn-revise-asm").addEventListener("click", async () => {
    const text = $("asm-instruction").value.trim();
    if (!text || !S.runId) return;
    await post(`/api/design/${S.runId}/revise`, { target: "assembly", instruction: text });
    $("asm-instruction").value = "";
  });
  $("btn-continue").addEventListener("click", () => post(`/api/design/${S.runId}/continue`));
  $("btn-rebuild-assembly").addEventListener("click", async () => {
    try {
      const r = await api(`/api/design/${S.runId}/rebuild-assembly`, { method: "POST", body: "{}" });
      S.runId = r.run_id; await loadRuns();
    } catch (e) { $("toolbar-note").textContent = e.message; }
    refresh();
  });
  $("btn-recolor").addEventListener("click", () => { if (S.runId) post(`/api/design/${S.runId}/recolor`); });
  $("btn-render").addEventListener("click", () => {
    const views = Array.from(document.querySelectorAll(".render-view:checked")).map((c) => c.value);
    if (!S.runId || !views.length) { $("toolbar-note").textContent = "Render: choose at least one view"; return; }
    post(`/api/design/${S.runId}/render`, { views, preset: $("render-preset").value, environment: $("render-env").value || null,
      camera: $("render-camera").value, focal_mm: Number($("render-focal").value), background: $("render-bg").value.toUpperCase(),
      brightness_lux: Number($("render-brightness").value), light_angle_deg: Number($("render-light").value),
      ground_reflections: $("render-refl").checked, ground_roughness: Number($("render-rough").value) });
  });
  $("btn-answer").addEventListener("click", () => {
    const text = $("q-answer").value.trim();
    if (text) { $("q-answer").value = ""; post(`/api/design/${S.runId}/answer`, { text }); }
  });
  S.runId = new URLSearchParams(location.search).get("run") || null;
  await refreshStatus();
  try { await loadRuns(); } catch (e) { $("toolbar-note").textContent = e.message; }
  if (document.body.classList.contains("read-only") && !S.runId && $("run-select").options.length > 1) {
    S.runId = $("run-select").options[1].value; $("run-select").value = S.runId;   // read-only: open the latest run
  }
  refresh();
});
