# Fast mode plan (Phase 0 audit) — prompt → Fusion → assembled Mini F1

Date: 2026-10-10. Baseline: commit 3e05f46 (203 unit tests green after fixing two stale historical-record test
expectations; no data changed). Progress of the implementation is tracked in `docs/dev-log/fast_mode_progress.md`.

## Goal

One brief in the web UI → PLAN (1 Claude call) → [≤ 1 blocking question] → BUILD PARTS (1 Claude call per part,
≤ 2 repairs each) → ASSEMBLE → CHECK (deterministic) → SCREENSHOT → DONE, all in one Fusion design. First target:
"Mini F1" = MON-001 monocoque, FWG-001 front wing, FLR-001 floor, RWG-001 rear wing. Concept level only.

The 8-stage strict workflow (`agent/workflow.py`, L-bracket generator) stays intact behind **Advanced** (UI) and the
existing CLI commands; it is no longer the default path.

## New modules

| File | Purpose |
|---|---|
| `fusion/prelude.py` | Prelude source every free-form part script runs inside: `mm()`, `ensure_anchor()`, `begin_part()` (component at identity + per-part user parameters), `finish_part()` (transform2 + snapshot + read-back, reported, never raised), colouring, measurement, `emit()` (one `@@RESULT@@` line). Composes prelude + Claude's body into one script. Build + place + measure = **one script call per part**. |
| `fusion/script_safety.py` | Static AST validator for Claude's body (allow-listed imports, forbidden names/attributes). |
| `fusion/assembly.py` | One read-only script call measuring mates (minimum distance + interference) and one call fitting the camera. |
| `docs/fusion_script_contract.md` | The contract Claude writes against (< 120 lines; also the static prompt prefix). |
| `fia_rules/retrieval.py` | Keyword retrieval of ≤ 6 verbatim snippets (≤ 400 chars, article id, page, hash) per part. |
| `validation/part_checks.py` | Deterministic per-part and assembly checks from Fusion measurements. |
| `vehicle/parts.py` | `PartRecord` registry record for free-form parts (id, version, exact script, parameters, pose, bbox, checks, FIA refs). Stored in `data/<project>/components/<ID>.json` with `record_type: "part"`; `ProjectStore.list_components()` keeps returning only the strict `Component` records. |
| `agent/fast_reasoning.py` | Lean `claude -p` call: `--system-prompt-file` with an identical static prefix (prompt caching), compact JSON schema, no history, plain-text input, tools disabled. Reuses `ClaudeCodeBackend`'s runner and result parsing. Model = Claude Code's default, `AGENT_MODEL` overrides. |
| `agent/fast_prompts.py` + `agent/prompts/fast_*.md` | Plan / part / repair prompts and pydantic schemas. |
| `agent/design_run.py` | Orchestrator, resumable via `data/<project>/design_runs/<run_id>/run.json`; registry integration; `rebuild <id>` with zero Claude calls; script-call counter and wrapper-depth tracking. |
| `docs/coordinate_system.md` | VCS definition and its verbatim relation to FIA C2.1.1 / C2.2. |

## Existing files: reused / changed / removed

| File | Verdict | Notes |
|---|---|---|
| `fusion/client.py` | REUSED, small change | `run_script` unchanged; fast mode counts calls in the orchestrator. Screenshot directions `iso-top-right`, `front`, `top` exist in the MCP schema (checked via `tools/list`). |
| `fusion/inspect.py` | REUSED (strict) | Fast mode measures inside the build script instead (saves one call per part). |
| `fusion/generators/l_bracket.py` | REUSED (strict) | `ANCHOR_NAME` and the anchor/placement pattern are reused by the prelude (same name "VCS origin"). |
| `vehicle/models.py` | REUSED | `Pose`, `Status`, `ValidationResult` reused by the fast checks. |
| `vehicle/transforms.py` | REUSED | `pose_to_matrix`, `matrix_to_fusion_cm`, `bbox_to_vcs`. |
| `vehicle/store.py` | CHANGED | `list_components()` skips `record_type: "part"` files; part registry helpers. |
| `fia_rules/rules.py`, `fia_rules/rules/*.yaml`, `fia_rules/source/*` | REUSED | Retrieval reads the structured rules first, then the extracted text; verbatim + hash mechanism reused. |
| `validation/checks.py` | REUSED | Strict checks; fast checks reuse its tolerances (`LENGTH_TOL_MM`, `ANGLE_TOL_DEG`). |
| `agent/reasoning.py` | REUSED | `ClaudeCodeBackend`/`FileExchangeBackend` stay for strict mode; fast reasoner reuses `_subprocess_runner` and `ClaudeCodeBackend.result_event`. |
| `agent/workflow.py`, `agent/report.py`, `agent/provenance.py`, `agent/attachments.py`, `agent/prompts/{analysis,plan,review,common}.md` | REUSED (strict) | Unchanged. Attachments reused by fast mode for the brief's images (stored with the run; not sent to Claude unless `--visual-review`). |
| `manufacturing/*` | REUSED (strict) | DFM is not part of fast mode (concept geometry). |
| `agent/service.py` | CHANGED | Adds fast-mode endpoints (start design run, answer, rebuild, run view, screenshots, Fusion banner). Strict API kept under `/api/strict/...`-compatible routes (existing routes unchanged). |
| `agent/__main__.py` | CHANGED | New commands `design`, `design-step`, `design-answer`, `rebuild`; strict commands unchanged. |
| `ui/server.py`, `ui/static/*` | CHANGED | Revamped default screen (brief box + Run, progress strip, log, results); strict UI moved under Advanced. |
| `tests/*` | KEPT + NEW | All existing tests stay (strict mode and historical records). New tests for every new module. |
| `data/**` | UNTOUCHED | Historical records. Fast runs go to a new project `mini_f1` (Fusion namespace `mf1`). |
| `root.txt` | MOVED | Master specification (historical), now `docs/dev-log/original_brief.md`. |
| `README.md`, `docs/architecture.md`, `docs/development_plan.md` | CHANGED in P5 | Fast mode documented as the default. |

### Removal candidates

Nothing in the repo is unreachable from both the strict path and the new fast path: every module is imported by
strict mode, its CLI, its UI, or the historical-record tests. **No code is removed.** Uncertain / kept on purpose:

- `agent/prompts/*.md` (strict prompts) — needed by strict mode.
- `FileExchangeBackend` — strict default and CLI default; kept.
- The strict UI page — kept as the Advanced view (moved to `/advanced`), not deleted.
- `docs/architecture.md` §12/§13 open decisions — still open; kept.

## Fusion facts honoured (from docs/architecture.md §2)

- Empty identity anchor "VCS origin" first; each part built at identity in its own component, then placed with
  `transform2` + `snapshots.add()` + read-back. A mismatch is **reported** in `@@RESULT@@`, not raised (a raise rolls
  back the model in an existing document).
- Body exceptions are caught by the prelude: the partial component is removed, the script ends normally and reports
  a compact error (type, message, failing body line numbers).
- Wrapper leak: every result carries the measured `sys.stdout` wrapper depth; the orchestrator counts script calls
  (budget 35 per run, nominal ≈ 7) and raises a "Restart Fusion" banner on `FusionOutputLost`.
- Each design run gets its own tagged Fusion document (attribute `agent_design/run`), created in the first part
  script; every script activates/validates that document first, so the user's other documents are never written.
  Documents are never saved or closed.

## Call budget

Planned: 1 plan call + 4 part calls + ≤ 8 repairs. Measured later in the recorded runs: 5 Claude calls for
the 4-part run `20261010-145347`, 10 for the 18-part extension `20261010-222202` (4 parts reused, 6 derived by
mirroring with no call), 0 for assembly rebuilds and 1 per revision. Static system prompt (contract + rules of the
game) identical across part and repair calls; per-call input = part spec + ≤ 6 FIA snippets (+ compact error and failing lines for repairs).
No images to Claude by default.

## Open questions recorded (not blocking)

- Rigid joints: attempted once in the live exploration; placement-based assembly is the accepted fallback.
- FIA "Z = 0" (C2.2 a) is the bottom of the sprung part; VCS Z = 0 is the project reference plane — treated as
  coincident by project convention (see `docs/coordinate_system.md`).
