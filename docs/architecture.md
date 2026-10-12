# Architecture — AI F1 Engineering Agent (an experimental pipeline)

Last updated: 2026-10-12 (public release: UI request checks and read-only mode, display wording; fast mode is the
default path, §14; the strict workflow is kept behind Advanced). Original brief: `docs/dev-log/original_brief.md`.
History: Milestone 1 (MVP 1.0) bracket slice · MVP 1.1 user-answer provenance and evidence labels · Milestone 1.2
web UI, Claude Code reasoning backend, image attachments, per-project Fusion naming · Milestone 2.0 fast mode, then
the Mini F1 run with real Claude reasoning: 4 parts, extended to 18 (wheels, suspension, sidepods, engine cover, halo,
mirrors; right-hand parts derived by mirroring), revise/revert, palette and local rendering (2026-10-10 to 10-12).
Index of all documents: `docs/README.md`.

Status legend used in this document:
**IMPLEMENTED+TESTED** (code exists, unit and/or live tests pass) · **IMPLEMENTED** (works, not covered by automated tests) ·
**PARTIAL** · **PLANNED** (designed for, not built).

---

## 1. Core idea

**Project data is the source of truth; Fusion is a rendering of it; the AI is the reasoner, not the memory.**

- Every component is a JSON *record* + a deterministic *generator* + *parameters*. Running the generator
  from the record rebuilds the Fusion geometry, so nothing depends on chat memory or on the Fusion
  document having been saved.
- The AI produces **structured objects validated by pydantic** (requirements, missing information,
  assumptions, plan, review decision) — never free text that code has to trust.
- Python does everything that can be computed or checked deterministically, and enforces the workflow.
- Fusion builds the geometry and provides the authoritative measurements, reached only through `fusion/`.

```
 USER ─► web UI (ui/static, browser)  or  CLI (python -m agent)
           │ JSON over http://127.0.0.1:8765          │
         ui/server.py (routing only)                   │
           │                                           │
         agent/service.py (facade: start / answer / advance / view model — no engineering logic)
           │                                           │
           ▼                                           ▼
 agent/ WORKFLOW ENGINE (state machine, gates, run log in data/<project>/runs/<run>/)
                   │
                   ├─ ReasoningBackend  (AI-provider agnostic)  ── analysis / plan / review
                   │     ├─ ClaudeCodeBackend: `claude -p --json-schema`, stream-json with image blocks (UI default)
                   │     ├─ FileExchangeBackend: request.md → response.json (CLI default, UI fallback)
                   │     └─ (API backend — planned, same interface)
                   ├─ agent/provenance.py  quote / invented-number / leading-question checks
                   │
                   ├─ vehicle/        records, coordinate transforms, persistence, registry
                   ├─ fia_rules/      rule schema + loader + evaluator; FIA 2026 source + rule records
                   ├─ manufacturing/  DFM rule data, materials, DFM runner
                   ├─ validation/     geometry / interface / hand-calc checks → ValidationResult
                   └─ fusion/         MCP HTTP client, generators (script builders), read-only inspection
                                          │ JSON-RPC over HTTP
                                          ▼
                                 Autodesk Fusion MCP server  http://127.0.0.1:27182/mcp
```

## 2. Environment facts that shaped the design

| Fact | Consequence |
|---|---|
| Fusion's MCP offers one real CAD capability: `fusion_mcp_execute` → run a Fusion-API Python script and return its `print()` output (plus read-only mode, screenshot, undo, API docs). | CAD layer = **script builder + runner + read-only inspection script**. No extra MCP infrastructure. |
| Python reaches that server directly (`127.0.0.1:27182/mcp`, session header, JSON-RPC). | The agent runs from a terminal; Claude Desktop is not needed. |
| Fusion's embedded Python is 3.14, the project's is 3.13. | Generated scripts use only stdlib + `adsk`; data crosses the boundary as JSON. |
| Fusion rejects two parallel sketch dimensions from the origin to points sharing a coordinate (`VCS_SKETCH_OVER_CONSTRAINTS`). | Hole patterns use chained design intent (anchor hole from origin, others by pitch + alignment constraints). |
| FIA 2026 Section C, Art. C2.1.1: Car Coordinate System X **rearwards**, Y to the driver's **right**, Z up. | Project VCS (original brief: +X front, +Y left, +Z up) kept; a fixed, tested transform maps VCS ↔ FIA (180° about Z + X-origin offset). **Open decision (see §9).** |
| OneDrive/antivirus can briefly lock files on Windows. | Atomic writes retry; registration is idempotent per run. |
| Claude Code 2.1.289 supports `claude -p --output-format json --json-schema <schema>`; the validated object is returned in `structured_output`. Verified 2026-10-05 on real analysis/plan/review tasks (6/6 schema-valid, 19–62 s each, engine gates passed). | A standalone reasoner without an API key: `ClaudeCodeBackend`, all tools disabled (`--tools ""`). |
| No Node.js; Python stdlib has an HTTP server. | UI = stdlib `ThreadingHTTPServer` + one static HTML/CSS/JS page; no new dependencies, no build step. |
| Fusion 2705.1.11 and 2705.1.30 (verified live 2026-10-10): `occurrence.transform2` set on the **only** root occurrence of a design is silently ignored. The part stays at identity with no error and no pending snapshot (Part 001 pose: 500 mm / 66° off). With any other root occurrence present, the same call is applied exactly. Grounding is not the cause; `computeAll` before the move, setting it twice and `addNewComponent(matrix)` do not help. | The generator keeps an empty identity **anchor occurrence** `VCS origin` as the first root occurrence (created once per document, never deleted by `remove_previous`). After the move it reads `transform2` back and raises *"Fusion did not apply the placement"* if it differs, so a regression fails loudly. A non-strict canary live test reports when a Fusion build fixes the behaviour. |
| The Fusion MCP add-in prepends code to every script that wraps `sys.stdout` **and** `sys.stderr` in one more `_NsSanitizedWriter` and never unwraps them (+1 layer per script call; MCP handshakes add none). After a few hundred calls printed output is lost: the call returns success with an empty message, or prints hit `RecursionError`. `__main__` globals also persist between script calls. | `run_script` raises `FusionOutputLost` on a success without `@@RESULT@@`, and the workflow maps it to `BLOCKED_FUSION`. The UI status poll uses the MCP handshake only (one script ping per (re)connection; a script ping per poll had added ~3 layers/min per open UI). Only a Fusion restart resets the depth, so keep the number of script calls low. |
| The MCP add-in **rolls back** a script's changes to an existing document when the script raises (verified: a parameter set to 9 mm in a raising script reads 8 mm afterwards). A document created in the raising script survives. | Scripts that change a model must end normally and report through `@@RESULT@@`. An exception is only a failure path (the build's partial-geometry cleanup still runs first). |
| A `transform2` that is not snapshotted at once is discarded when the next component is created (verified live 2026-10-10, 2705.1.30); `snapshots.add()` raises "Has no pending snapshot" if nothing moved. | The fast-mode prelude snapshots right after each move, guarded by `hasPendingSnapshot`, and reads the transform back. |
| `measureMinimumDistance(occA, occB)` returns the exact gap; `analyzeInterference` on more than two occurrences returns bodies that cannot be attributed to occurrences; screenshots add no stdout wrapper layer; the view cube "top" orientation depends on the previous camera. | Assembly is measured per part pair; each screenshot view uses an explicit camera script (3 script calls). |

## 3. Workflow engine — `agent/workflow.py` — IMPLEMENTED+TESTED

One task = one **run** = a resumable state machine persisted in `run.json`:

```
ANALYSIS (AI) ─► [AWAITING_USER] ─► PLAN (AI) ─► PRECHECK ─► CAD ─► INSPECT ─► VALIDATE ─► REVIEW (AI)
      ▲  answers re-run analysis      ▲   │ plan gate / DFM / hand-calc fail          │ REVISE (bounded)
      └──────────────────────────────┘   └──────────────── loop back ◄───────────────┘
                                                    REVIEW ACCEPT ─► REGISTER ─► REPORT ─► COMPLETED
                                                    REVIEW STOP / loop limit ─► REPORT ─► STOPPED
```

Gates enforced in code (each has a unit test):

| Gate | Rule |
|---|---|
| Analysis | Response schema valid; ids unique; every generator `REQUIRED_INFO` key covered by a requirement or a missing-info item; ASSUME items reference an existing assumption; **CRITICAL items must be ASK** (project policy). |
| Provenance (MVP 1.1) | Requirements attributed to the user (`USER_REQUEST` / `USER_ANSWER`) must quote the user's words verbatim (checked against request/answer text); every number in the interpretation must appear in the quote; `DERIVED` needs `derived_from`. Questions may not contain suggestion markers ("e.g.", "for example", …) or numbers the user did not write (project identifiers such as BRK-001/R01 are ignored); policy `allow_suggested_values_in_questions` can relax this. Every answered question must be interpreted (`answer_id`) or followed up by a new question (`follows_up`). |
| User questions | Run stops in `AWAITING_USER` until every ASK item is answered; answers are stored verbatim (`record_answer`: question, text, timestamp, entry channel; never overwritten) and fed back into a new analysis. |
| Response rejections | A rejected response produces a new task with the errors as feedback; more than `policy.max_response_rejections` (3) consecutive rejections stop the run (protects against an automatic reasoner looping). |
| Plan | Exactly the generator's parameter set; every parameter/load-case trace id exists (R/M/A/rule ids); material and process known; generator inputs valid; geometric feasibility (holes clear of bend, inside legs, pitches > diameters). |
| Pre-CAD | DFM rules + bending hand calc; a blocking failure loops back to PLAN with the findings, **before Fusion is touched**. |
| CAD | Fusion script failure → partial geometry deleted by the script, failure recorded, goes to REVIEW. Fusion unreachable → `BLOCKED_FUSION`, state kept, `step` retries. |
| Review | ACCEPT is **refused** while any blocking check is NON_COMPLIANT or NOT_VERIFIED; REVISE changes are re-gated; loops limited by `policy.max_revision_loops` (3). |
| Register | Only after ACCEPT; idempotent per run (a resumed run never creates a bogus revision). |

## 4. Reasoning layer — `agent/reasoning.py`, `agent/prompts/` — IMPLEMENTED+TESTED

- `ReasoningTask` = instructions (provider-neutral Markdown prompts) + context JSON + JSON schema of the answer.
- `ReasoningBackend.request(task) -> dict | None` (None = not answered yet). Every backend leaves the same audit
  trail in `reasoning/`: `NN_<kind>.request.md/.json`, `NN_<kind>.response.json`, and for automatic backends
  `NN_<kind>.meta.json` (answered_by, models, duration, reported cost). The run log records which backend answered.
- **FileExchangeBackend** — IMPLEMENTED+TESTED: writes the request, reads the response file. Any reasoner (a Claude
  Code session, a human, another model) can answer. Default of the CLI; fallback of the UI.
- **ClaudeCodeBackend** — IMPLEMENTED+TESTED (unit with fake runner; live `pytest -m claude`): runs
  `claude -p --json-schema <schema> --input-format stream-json --output-format stream-json --verbose --tools ""
  --no-session-persistence --strict-mcp-config`; one stream-json user message on stdin carries the prompt and any
  image blocks; the `result` event's `structured_output` is the answer. Uses the local Claude Code login (no API key). Failure (missing CLI, non-zero exit, no
  `structured_output`) raises `ReasoningBackendError`.
- **FallbackBackend** — IMPLEMENTED+TESTED: primary (Claude Code) → fallback (file exchange) on `ReasoningBackendError`.
- **API backend — PLANNED**: implement `request()` with any LLM API (structured output against `response_schema`).
  No engine or UI change needed. Integration point: `Engine(backend_factory=...)` / `AgentService`.
- Response models: `AnalysisResponse`, `PlanResponse` (incl. `LoadCase` — currently bracket-style plate bending), `ReviewResponse`.

## 5. Engineering data — `vehicle/` — IMPLEMENTED+TESTED

| Record | Key fields |
|---|---|
| `Project` | id, kind (bench/vehicle), coordinate-system note, regulation, policy (critical-must-ask, max loops) |
| `Component` | id (`BRK-001`), type, revision, lifecycle (IN_WORK/CHECKED/REJECTED/HUMAN_RELEASED), pose in VCS, generator id+version, parameters (value, unit, source, trace, rationale), interfaces, requirements, assumptions, applicable rules, manufacturing, validation results, derived (Fusion volume, mass, bbox), Fusion reference, provenance tags, history |
| `Interface` / `MountingPoint` | id, type (BOLTED/…), mates_with, origin, outward normal, mounting points (position, axis, hole Ø, fastener), **`hole_geometry_status`** (own holes measured) and **`mating_status`** (fit with the mating part) — never one broad status |
| `Requirement` | the **AI's interpretation** (`interpreted_by: AI`) with provenance: `source` USER_REQUEST / USER_ANSWER / DERIVED (/ LEGACY_V1 for schema-1 records), verbatim `quote`, `answer_id`, `derived_from` |
| `MissingInfo` / `Assumption` | M-, A-ids; ASK needs a question, ASSUME needs an assumption id; `follows_up` links a clarification question to the answer it clarifies |
| `ValidationResult` | check id, category, **`scope` + `claim`** (exactly what the result establishes), status, severity, method, measured, limit, unit, rule id, message; label = `{scope}_{status}` |

Schema version 2 (MVP 1.1). Schema-1 records (BRK-001) are read unchanged: requirements map to `LEGACY_V1`,
interface `status` maps to `hole_geometry_status` with `mating_status = NOT_VERIFIED`; files are not rewritten.

**Statuses** (one function, `check_status`): failed → `NON_COMPLIANT`; passed + rule human-verified + no assumed
inputs → `VERIFIED`; passed otherwise → `ASSUMPTION`; not checkable → `NOT_VERIFIED`; `NOT_APPLICABLE`.
Provenance tags: AI_GENERATED, RULE_CHECKED, ASSUMPTION_BASED, GEOMETRY_VALIDATED, SIMULATION_VALIDATED, HUMAN_VERIFIED.

**Coordinates** (`vehicle/transforms.py`): VCS +X front, +Y left, +Z up, mm. Component pose = R(roll,pitch,yaw)
(R = Rz·Ry·Rx) + position; local↔VCS, bbox transform, VCS↔FIA, mm↔cm, Fusion `Matrix3D` array. Bench
components use the identity pose. Non-identity placement (occurrence `transform2` + position snapshot) is
IMPLEMENTED+TESTED live: exact to 0.0 mm / 0.0° for the Part 001 pose, after build, after `computeAll`, after a re-run,
after delete + rebuild and after a parameter edit. This relies on the anchor occurrence (§2). Several placed
components in one design: fast mode (§14); the Mini F1 has 18.

**Persistence** (`vehicle/store.py`): `data/<project>/project.json`, `components/<ID>.json`, `runs/<run>/`
(`run.json`, `reasoning/`, `scripts/NN_build.py`, `geometry_report.json`, `screenshot.png`, `report.md`).
Atomic writes with retry on transient Windows locks.

## 6. Rule layer — `fia_rules/`, `manufacturing/` — IMPLEMENTED+TESTED (content PARTIAL)

- `Rule`: id, title, authority (REGULATION / STANDARD / PROJECT_RULE / GUIDELINE), verbatim `requirement_text`,
  `applies_to`, optional process, `constraint` (min / max / range / table_match / info, quantity, value, unit),
  severity, validation method, `source` (document, issue, date, article, page, file, sha256, url),
  `verification_status` of the transcription (+ verified_by/on).
- `python -m agent rules-verify <id> --by <name>` records a human review of a transcription.
- **FIA source**: 2026 F1 Regulations – Section C [Technical], **Issue 20, 2026-08-05** (latest on fia.com at download),
  recorded with its SHA-256 in `fia_rules/source/SOURCE.md` (the document itself is not included; see
  `fia_rules/source/README.md`). Six rules transcribed verbatim (C2.1.1, C2.3.1,
  C2.3.3–C2.3.6), all `NOT_VERIFIED` and vehicle-level. When the FIA source is installed
  (`fia_rules/source/README.md`; not included), tests check every quoted FIA text exists in the PDF text and that
  the PDF hash matches. FIA checkers (`VEHICLE_LAYOUT_CHECK`, reference volumes) — **PLANNED**.
- **Manufacturing**: `manufacturing/rules/machined.yaml` (project rules from `manufacturing/source/DFM_rules_summary.md`, generic guidance, ISO 273
  clearance holes, hole-edge-distance guideline) and `materials.yaml` (handbook values, NOT_VERIFIED).

## 7. CAD layer — `fusion/` — IMPLEMENTED+TESTED (live)

| Part | Status |
|---|---|
| `client.py` — MCP JSON-RPC client: session, `run_script` (read-only flag), `@@RESULT@@` JSON protocol, screenshot, undo, ping, error mapping (unavailable / script error / `FusionOutputLost` = success without a result) | IMPLEMENTED+TESTED (fake transport + live) |
| `generators/l_bracket.py` — inputs model, feasibility, DFM quantities, analytic volume/bbox/holes, interfaces, structural section, Fusion script | IMPLEMENTED+TESTED (unit + live) |
| Generated model: named component, 14 prefixed user parameters (`brk001_bracket_thickness`, …, derived `…_bend_outer_radius`), fully constrained sketches, named features (`SK_L_profile`, `EX_L_profile`, `FL_bend_inner/outer`, `SK/CUT_base_holes`, `SK/CUT_upright_holes`), cut features limited to own body, Fusion material; rebuild replaces the previous build; failure deletes partial geometry; generator 3: empty identity anchor occurrence `VCS origin` first + placement read-back that raises if Fusion ignored the move | IMPLEMENTED+TESTED (live, in throwaway tagged documents) |
| `inspect.py` — read-only inspection: bodies (VeryHigh accuracy volume/area, bbox in world), cylinders (centre/axis/radius/concave), feature health, sketch constraint status, parameter values; the Fusion build that inspected (`fusion_version`) and the one that ran the CAD build (`build_fusion_version`), with a logged/report warning when they differ | IMPLEMENTED+TESTED (live) |
| Multi-component assembly, joints, interference analysis | IMPLEMENTED+TESTED in fast mode (§14: per-pair minimum distance and interference, as-built rigid joints for planned mates); not used by the strict path |
| Free-form (AI-authored) geometry scripts | IMPLEMENTED+TESTED in fast mode (§14: Claude writes the part body; `fusion/script_safety.py` validates it, `fusion/prelude.py` wraps it). The validator catches model mistakes; it is not a sandbox |

Document policy: the agent works in the active Fusion design (creates one if none is open) and never saves or closes
documents — the record + generator can always rebuild the model. Every design it builds in gets one empty identity
occurrence `VCS origin` (the placement anchor, §2); it holds no geometry and is ignored by inspection.
Live tests never use the user's design: each test creates its own tagged document, every script is guarded on that
tag, and the documents are closed without saving.

## 8. Validation layer — `validation/checks.py` — IMPLEMENTED+TESTED

| Group | Checks now | Later |
|---|---|---|
| Process | CAD build succeeded | |
| Geometry (Fusion-measured) | body count, feature health, sketches fully constrained (advisory), bbox vs design (1 µm), volume vs analytic (1e-4 rel), Fusion parameters = record | symmetry, thickness sampling |
| Interface | `HOLE_GEOMETRY`: every own mounting hole found as a concave cylinder with designed Ø, axis and position (1 µm). `MATING_INTERFACE`: explicitly NOT_VERIFIED while the mating part is not modelled | mating with other components, clearance |
| Manufacturing | `MANUFACTURING_RULE`: rule-driven parameter checks (min wall, internal radius, fatigue ratio, ISO 273 holes, edge distance) | B-rep based checks, tool access |
| Structural | `STRUCTURAL_CHECK`: plate-bending hand calc vs yield with required SF (ASSUMPTION when inputs are assumed; no load case, i.e. zero force or lever arm → NOT_VERIFIED / NOT_RUN, advisory — never a passed check). `STRUCTURAL_ADEQUACY`: explicitly NOT_VERIFIED (bolts, base leg, fatigue, FEA not analysed) | FEA (Phase 7) |
| FIA | `FIA`: applicability statement; never a blanket compliance claim | vehicle layout + reference-volume checkers |

Evidence labels seen in a bracket run: `CAD_BUILD_VERIFIED`, `GEOMETRY_VERIFIED`, `PARAMETERS_VERIFIED`,
`HOLE_GEOMETRY_VERIFIED`, `MATING_INTERFACE_NOT_VERIFIED`, `MANUFACTURING_RULE_ASSUMPTION`,
`STRUCTURAL_CHECK_ASSUMPTION`, `STRUCTURAL_ADEQUACY_NOT_VERIFIED`, `FIA_NOT_APPLICABLE`.

## 9. User interface — `agent/service.py`, `ui/` — IMPLEMENTED+TESTED (Milestone 1.2)

The UI is a frontend for the existing workflow, not a second implementation of it.

| Part | Responsibility | Status |
|---|---|---|
| `agent/service.py` `AgentService` | start a run, record a verbatim answer (`entered_via: "ui: web interface"`), advance a run in a background thread (one worker per run), choose the reasoner (`auto` = Claude Code if `claude --version` works, else file exchange; Claude Code itself falls back to file exchange per task), Fusion status (MCP handshake per poll, cached 60 s; Fusion version and active document from one script ping per (re)connection, because every script call leaks a wrapper layer in the MCP add-in), and `build_run_view()` — a view model built only from `run.json` + component records | IMPLEMENTED+TESTED |
| `ui/server.py` | stdlib `ThreadingHTTPServer`, binds to 127.0.0.1 only; JSON API: `GET /api/status`, `GET/POST /api/runs`, `GET /api/runs/<id>`, `POST /api/runs/<id>/answer`, `POST /api/runs/<id>/advance`, `GET …/report`, `GET …/screenshot`; static files with path-traversal protection; body size limit | IMPLEMENTED+TESTED (in-process HTTP tests) |
| `ui/static/` | one page: header (backend / reasoner / Fusion status), 8-step pipeline (REQUIREMENTS → … → REGISTERED, current step highlighted, waiting/failed states), chat with layer-tagged messages (USER REQUEST, QUESTION, USER ANSWER (verbatim), AI INTERPRETATION with quotes, ASSUMPTION, ENGINEERING DECISION with source/trace, VALIDATION evidence labels, REVIEW, RESULT), right panel (task, stage, agent status, component/revision with hole-geometry vs mating status, evidence labels, FIA status, Fusion, assumptions, report/screenshot, reasoning log); all text inserted with `textContent` | IMPLEMENTED; rendered and checked in headless Edge (no console errors); no automated JS tests |

Request checks (2026-10-12): every request needs Host `127.0.0.1:<port>` or `localhost:<port>`; an `Origin` from any
other site is refused (403); every POST needs `Content-Type: application/json` (415). `python -m ui --read-only`
serves the recorded runs and refuses every POST (403), so nothing is started or written. IMPLEMENTED+TESTED.

The composer is context-sensitive: a new request when idle (optionally with image attachments), an answer to the
open question (one at a time, stored verbatim) when the agent waits, disabled while the agent works, "Check again"
when waiting for a file-exchange reasoner or for Fusion. Free chat outside the workflow is intentionally not supported.

Verified end to end on 2026-10-05: project `ui_e2e_test`, run `20261005-220102-…` driven through the HTTP API the page
uses, with a sketch attached, real Claude Code reasoning and real Fusion → `BRK-001 rev 1` CHECKED; the finished run
rendered in headless Edge without console errors. The answers in that run are a **scripted test customer** (marked
in every answer text) — it is test data, kept in its own project.

## 10. Image attachments — `agent/attachments.py` — IMPLEMENTED+TESTED

Workflow: IMAGE → engineering information extraction (AI) → ambiguities / questions → requirements → plan → CAD → validation.
An image never becomes geometry by itself.

| Aspect | Implementation |
|---|---|
| Input | UI attach button (PNG/JPEG/GIF/WebP, ≤ 5 MB, ≤ 4 per request, previewed before sending) or `python -m agent new … --image file`; type checked by magic bytes, not by file name |
| Persistence | `runs/<run>/attachments/IMG-01.<ext>` + record in `run.json["attachments"]` (id, file, original name, media type, bytes, SHA-256, time, entry channel); component records list them in `source_attachments`; report shows them |
| Reasoning | images go with the **analysis** and **plan** tasks: Claude Code receives image blocks (stream-json input; file re-hashed before sending); file exchange lists `../attachments/IMG-nn.ext` in the request. `meta.json` records `attachments_sent` |
| Provenance | Requirement source `IMAGE` (`attachment_id` + `image_evidence` = what the AI read). Gates: the attachment must belong to the run; numbers in the interpretation must appear in `image_evidence`; a question may repeat an image value only if it names the image (IMG-nn); plan parameters from images use source `IMAGE_EVIDENCE` and must trace to an IMAGE requirement; parameters labelled USER/REQUIREMENT must trace to the user's request or answers. Image values can never become a USER_ANSWER |
| Not in scope | PDF, video, CAD upload, OCR pipelines, automatic image-to-geometry |

## 11. Fusion naming across projects

Fusion has one name space per document, component ids are unique per project. `Project.fusion_namespace` prefixes
Fusion component and parameter names (`uie2etest BRK-001 …`, `uie2etest_brk001_*`). New projects get one derived from
their id; the original `prototype_bench` has none, so BRK-001/BRK-002 keep their names. The build script replaces only
its own component (matched by namespace + id) and refuses to continue if a parameter it wants to replace is still used
elsewhere. Found by the E2E test (a second project's BRK-001 collided with the existing one; the build failed safely).

## 12. Known data issue (not modified, awaiting decision)

`data/prototype_bench/components/BRK-002.json` (MVP 1.1) stores its requirement sources as `LEGACY_V1` instead of
USER_REQUEST/USER_ANSWER — the legacy mapping treated a component built without an explicit `schema_version` as
schema 1. Quotes and answer ids are intact, and the run record (`runs/20261005-205141-…/run.json`) has the correct
sources. The code is fixed and covered by a regression test; the stored file was **not** changed (historical data).
Correcting it needs a decision: a documented data repair from the run record, or a new revision.

## 13. Open decisions

1. ~~Vehicle coordinate system vs FIA~~ — DECIDED 2026-10-10 (user): keep the VCS (+X front, +Y left, +Z up) with
   the tested transform to the FIA Car Coordinate System. See `docs/coordinate_system.md`.
2. ~~Vehicle X datum~~ — DECIDED 2026-10-10 (user): VCS origin on the front-axle centreline (relation to FIA XF = 0
   NOT_VERIFIED: the concept wheels WHL-* exist and are centred on VCS X = 0, but nothing is checked against the FIA
   wheel definition), Y = 0 plane of symmetry, Z = 0 reference plane. See `docs/coordinate_system.md`.

## 14. Fast mode (default path) — `agent/design_run.py` — IMPLEMENTED+TESTED (Milestone 2.0)

One brief → an assembled concept in ONE Fusion design. Plan and file-by-file audit: `docs/fast_mode_plan.md`;
progress log: `docs/dev-log/fast_mode_progress.md`; coordinates: `docs/coordinate_system.md`; script contract:
`docs/fusion_script_contract.md`.

```
 brief (UI / CLI) ─► DesignService (one run at a time, background thread) ─► Orchestrator (run.json after every step)
   PLAN      1 Claude call (PLAN_SYSTEM + brief + kit + <= 6 verbatim FIA snippets per part + registry)
             -> deterministic gate (exact part ids, dims, envelopes, refs ⊆ snippets); 1 retry; <= 1 question
   PARTS     per part: 1 Claude call (static contract system prompt + part spec only) -> AST validator
             -> prelude script (document, anchor, component at identity, user params, build(part), transform2 +
             snapshot + read-back, colour, measurement, one @@RESULT@@) -> deterministic checks
             -> <= 2 repairs from a compact error -> registry (data/<project>/components/<ID>.json, record_type part)
   ASSEMBLE  1 script: minimum distance for planned-mate pairs + pairs whose bboxes are within PAIR_NEAR_MM,
             interference only where the bboxes overlap; as-built rigid joints for planned mates (not keep-clear)
   CHECK     validation/part_checks.mate_results (touching / gap <= v / overlap <= depth / clear >= v,
             unintended overlaps advisory)
   SCREENSHOT 3 camera scripts + 3 screenshots (iso, front, top) -> run folder
   DONE      summary.md from a Python template
```

| Part | Status |
|---|---|
| `fusion/prelude.py`, `fusion/script_safety.py`, `fusion/part_runner.py`, `fusion/assembly.py` | IMPLEMENTED+TESTED (unit + live) |
| `validation/part_checks.py`, `vehicle/parts.py`, `ProjectStore.list_parts/get_part/save_part` | IMPLEMENTED+TESTED |
| `fia_rules/retrieval.py` (verbatim snippets, extent-rule statuses) | IMPLEMENTED+TESTED |
| `agent/fast_reasoning.py` (`claude -p --system-prompt-file … --json-schema …`, cached per call) | IMPLEMENTED+TESTED (fake runner + 2 real calls) |
| `agent/fast_prompts.py`, `agent/design_run.py`, `agent/design_service.py`, `/api/design`, `ui/static/index.html` + `fast.js` | IMPLEMENTED+TESTED (fake Fusion + scripted Claude; page rendered in headless Edge) |
| Full Mini F1 with real Claude reasoning | DONE 2026-10-10 to 10-12, started by the user from the UI; recorded runs in `data/mini_f1/design_runs/` |
| Derived parts (`vehicle/mirror.py`: right-hand parts mirrored or yawed 180° from the left, zero Claude calls), palette (`vehicle/palette.py`, `fusion/paint.py`), local render (`agent/render_run.py`, `fusion/render*.py`) | IMPLEMENTED+TESTED (unit; live test for mirroring only; palette and render were used live in the recorded runs) |

Rules kept from the strict path: Claude never calls Fusion; every script is ours or validated; no script saves or
closes a document; model-changing scripts end normally; the user's other documents are never touched (each run has
its own tagged document); results are measured by Fusion and judged by code, never by the AI. FIA statuses:
VERIFIED only for an unambiguous extent rule measured on the part (C2.3.1, |Y| ≤ 950 mm), NON_COMPLIANT if that
measurement fails, everything else NOT_VERIFIED. No FIA compliance, structural adequacy or race readiness claim.

Budgets per run: 1 plan call (+1 retry, +1 after an answer), 1 call per part, ≤ 2 repairs per part; ≤ 35 Fusion
script calls (nominal Mini F1: 4 parts + 1 assembly + 3 cameras = 8). Measured wrapper depth is stored per run.
Measured in the recorded runs (`data/mini_f1/design_runs/`): 4-part run 5 Claude calls / 8 script calls; 18-part
extension 10 Claude calls / 37 script calls (it hit the 35-call budget, was blocked and resumed; the budget counts
from each start or resume; 4 parts reused, 6 mirrored with no Claude call); assembly rebuilds 0 Claude calls; each
revision 1 Claude call / 4 script calls.

### 14.1 Coordinate frame and revision — `agent/revise.py` — IMPLEMENTED+TESTED (unit + one live test)

- Frame contract: part scripts build in the part-local frame; the pose alone places the part. The build script
  measures the local bbox (identity, before placement); `PART-FRAME` compares it with the envelope taken back by the
  inverse pose and diagnoses world-coordinate scripts (the MON-001 v1 double offset). `frame_mode: legacy_world`
  (MON-001 v2) is an explicit exception: VCS-coordinate script, identity pose only.
- Revise = a transaction in the run's current Fusion design: preflight probe (document, depth ≤ 100) → 1 Claude call
  (static `revise_system()`; selected part spec + script + measurements, mated neighbours, planned mates, its FIA
  snippets, the instruction) → deterministic gates (schema/scope, frame, plan mate consistency + minimum unambiguous
  neighbour pose shift, FIA width) → build (≤ 2 repairs) → mates re-measured → commit v+1 → screenshots. Failure →
  rollback to the stored records, re-verified; rollback failure → CRITICAL. ≤ 10 script calls per step, rollback
  reserved. Revert = new version "reverted to vN". Advisory mate-face check per planned mate (PASS / WARNING /
  NOT_CHECKABLE). Progress log: `docs/dev-log/revise_progress.md`.
