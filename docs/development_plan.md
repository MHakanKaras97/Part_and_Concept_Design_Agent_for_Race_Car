# Development Plan — AI F1 Engineering Agent (an experimental pipeline)

Last updated: 2026-10-12 (Milestone 2.0 fast mode complete; the Mini F1 was run with real Claude reasoning, extended to
18 parts and refined; see `docs/dev-log/`). Architecture: `docs/architecture.md`. Original brief:
`docs/dev-log/original_brief.md`. Commit hashes below refer to the private development archive, not to this
repository.

Principle: build vertically — one thin, real, end-to-end slice first, then widen. Every milestone ends with:
tests run, live Fusion run verified, docs updated, short report (works / doesn't / next step).

---

## Milestone 0 — Inspection & architecture — DONE

- Workspace, Python 3.13, packages, Fusion 2705.1.11 and its MCP server (`127.0.0.1:27182/mcp`) inspected.
- Decisions taken by the user: Claude Code as reasoner with a provider-agnostic core; FIA 2026 Section C as
  regulation source; git initialised; reuse the existing Fusion MCP integration unchanged.

## Milestone 1 — MVP vertical slice: engineering bracket (Prototype 1) — DONE

| Step | Status |
|---|---|
| Data model, statuses, persistence, registry, coordinate transforms (`vehicle/`) | IMPLEMENTED+TESTED |
| Rule schema/loader/evaluator, FIA source (Iss 20) + 6 verbatim rules, DFM rules, materials | IMPLEMENTED+TESTED |
| Fusion MCP client | IMPLEMENTED+TESTED (fake transport + live) |
| L-bracket generator + read-only inspection | IMPLEMENTED+TESTED (unit + live) |
| Validation (geometry, interfaces, DFM, hand calc, FIA applicability) | IMPLEMENTED+TESTED |
| Workflow engine with gates, file-exchange reasoning backend, CLI, report | IMPLEMENTED+TESTED |
| Live end-to-end run | DONE — run `20261005-203018-design-a-machined-alumin` → `BRK-001 rev 1` (CHECKED) |
| README | DONE |

**Demonstrated end to end (2026-10-05)** with the request
*"Design a machined aluminium L-bracket to mount a 2 kg sensor box to a flat plate with four M6 bolts."*:
analysis found the sensor-box interface missing (CRITICAL → asked the user), four IMPORTANT gaps stated as
assumptions; plan traced every parameter to R/M/A/rule ids; pre-CAD checks passed; Fusion built a fully
constrained parametric bracket; read-only inspection verified bbox, volume (1e-15 rel. deviation), 14/14
parameters and 6/6 interface holes; review accepted; component registered; report written.

**Tests:** 83 unit tests (`python -m pytest`), 4 live Fusion tests (`python -m pytest -m fusion`).

**Known limitations of M1**
- Only one generator (`l_bracket`, machined). `LoadCase` is bracket-style (plate bending).
- Rule transcriptions and material values are NOT_VERIFIED → rule-based passes are ASSUMPTION, not VERIFIED,
  until a human runs `rules-verify`.
- API reasoning backend not implemented (file exchange only).
- Bench components only (identity pose); vehicle placement path not yet exercised in Fusion.

(Historical record of Milestone 1 as delivered. The audit after M1 found that the M01 answer options had been
drafted by the same session that consumed them, and that "interface VERIFIED" overstated the evidence — fixed in MVP 1.1.)

## MVP 1.1 — User-answer provenance and evidence-specific validation — DONE (commit 54a3aba)

| Change | Status |
|---|---|
| Verbatim answers (`record_answer`: question, text, timestamp, entry channel; never overwritten) as the authoritative USER_ANSWER | IMPLEMENTED+TESTED |
| Requirements as AI interpretations with provenance (USER_REQUEST / USER_ANSWER quote + answer id / DERIVED) | IMPLEMENTED+TESTED |
| Gates: verbatim quote, no invented numbers, neutral questions (no suggestions/new numbers), every answer interpreted or followed up | IMPLEMENTED+TESTED |
| Evidence labels `{scope}_{status}`; interface `hole_geometry_status` vs `mating_status`; explicit MATING_INTERFACE / STRUCTURAL_ADEQUACY NOT_VERIFIED rows | IMPLEMENTED+TESTED |
| Schema 2 with read-only legacy mapping for BRK-001 (file unchanged) | IMPLEMENTED+TESTED |
| Live run `20261005-205141-…`: M01 asked neutrally, answer incomplete → follow-up M06, both answered by the user → `BRK-002 rev 1` | DONE |

## Milestone 1.2 — Engineering agent UI (web UI, Claude Code reasoning, image input) — DONE

| Change | Status |
|---|---|
| `ClaudeCodeBackend` (`claude -p --json-schema`, stream-json, tools disabled) + `FallbackBackend` → file exchange; `.meta.json` audit per answer; run log records which reasoner answered | IMPLEMENTED+TESTED (fake runner; live `-m claude`) |
| Verification of `claude -p` before implementation: 6/6 schema-valid on real MVP 1.1 tasks (analysis, plan, review), 19–62 s per task; image reading verified with stream-json image blocks | DONE |
| Fix: project identifiers (BRK-001, R01, rule ids) were counted as "new numbers" in questions | IMPLEMENTED+TESTED |
| Engine: cap on consecutive rejected responses (`max_response_rejections` = 3); `REASONING` status while a backend works | IMPLEMENTED+TESTED |
| `agent/service.py` facade + view model (no engineering logic) | IMPLEMENTED+TESTED |
| `ui/server.py` (stdlib HTTP, localhost only) + `ui/static` single-page UI; `python -m ui` | IMPLEMENTED+TESTED (HTTP API); page verified in headless Edge |
| Image attachments: UI attach + preview, CLI `--image`, stored with the run (hashed), sent to the reasoner, `IMAGE` requirement source and `IMAGE_EVIDENCE` parameter source with gates; components reference `source_attachments` | IMPLEMENTED+TESTED (unit + live `-m claude`) |
| Fix (found by E2E): Fusion name collision between projects → per-project `fusion_namespace`; build refuses to overwrite parameters in use | IMPLEMENTED+TESTED (unit + live `-m fusion`) |
| Fix (found by a new test): components built without explicit `schema_version` were treated as legacy → requirement sources relabelled `LEGACY_V1` | IMPLEMENTED+TESTED (code); BRK-002 data not modified — see architecture §12 |
| CLI unchanged by default; optional `--reasoner claude_code`, `new --image` | IMPLEMENTED+TESTED |
| E2E through the UI API: request + sketch → Claude Code analysis (IMAGE evidence) → 2 critical questions answered → plan → Fusion CAD → inspection → validation → review → `ui_e2e_test` BRK-001 rev 1 (scripted test customer, separate project) | DONE |
| User run `20261005-212523-…` (prototype_bench) started from the UI with Claude Code reasoning | open — waiting for the user's own answers |

**Tests:** 142 unit tests, 5 live Fusion tests (`-m fusion`), 2 live Claude Code tests (`-m claude`), plus the E2E run.

**Known limitations of M1.2**
- Automatic reasoning takes ~20–60 s per step; the UI polls and shows the agent as working.
- One question is answered at a time in the composer; the agent re-analyses after all open questions are answered.
- No automated JavaScript tests (no Node in the environment); the page is verified by rendering in headless Edge.
- The UI server is single-user and local (127.0.0.1); no authentication.
- Images: PNG/JPEG/GIF/WebP only, ≤ 5 MB, ≤ 4 per request; no PDF/CAD/video input.
- BRK-002 record carries `LEGACY_V1` requirement labels (code fixed; data correction pending a decision).

---

## Follow-ups from the Part 001 placement investigation (2026-10-10)

- [ ] **Load case optional / declined by user.** Make the load case explicitly optional in the plan schema, with a
  "declined by user" state (who declined, quote, when). Today a plan without a real load must carry a zero force,
  which the plate-bending hand calculation now reports as NOT_VERIFIED / NOT_RUN (advisory). An explicit state would make the report say
  *why* no structural check ran.
- [ ] Re-run Part 001 with generator 3 (anchor + read-back) after the fixes; the existing Part 001 record/run stay as
  historical evidence of the ignored placement.
- [ ] Keep an eye on the Fusion MCP add-in wrapper leak: restart Fusion before long live sessions; the canary live
  test reports when Fusion fixes the ignored-placement behaviour.

## Milestone 2 — F1 Engineering Agent V2: vehicle coordinate system + interfaces (Prototype 2) — NEXT

1. Decide VCS vs FIA frame and the X datum (architecture §13) — **user decision**.
2. Create a `vehicle` project (`data/<vehicle>/project.json`) with the documented datum and `docs/coordinate_system.md`.
3. An F1 mounting/interface component (e.g. front-wing mounting pylon or bulkhead mount plate) with a second
   generator; placed by `Pose` in the VCS. Non-identity placement of a single part is verified live (2026-10-10,
   with the anchor occurrence; architecture §2); a second generator must reuse the anchor + read-back.
4. Interface records that reference *another component's* interface; validation that mating mounting points
   coincide in VCS (position + axis) and hole sizes/fasteners match.
5. Iteration workflow on an existing component: "make it 2 mm thicker" → find component → change parameter →
   rebuild → revalidate → new revision → change report (`python -m agent revise <component> "..."`).
6. Optional: API reasoning backend (same `ReasoningBackend` interface; the UI and engine need no change).

## Milestone 3 — Nose (Prototype 3)

- First non-prismatic generator (lofts through named section sketches).
- Placed relative to a simplified survival-cell front bulkhead; interface to it.
- First FIA nose-region rules transcribed verbatim from Issue 20 (VERIFIED only after human review); first FIA
  geometric checker.

## Milestone 4 — Front wing (Prototype 4)

- Multi-element wing generator; FIA dimensional/envelope rules where structured; everything else NOT_VERIFIED.
- Interface to the nose; interference check between components (Fusion interference analysis).

## Milestone 5 — Multiple components / persistent state (Prototype 5)

- Rebuild the whole vehicle in an empty Fusion document from `data/` only.
- Clearance/interference checks between all neighbouring components; vehicle-level FIA layout checks
  (C2.3.x: width, wheelbase, cockpit and wheel positions).

## Milestone 6 — Concept assembly (Prototype 6)

- Monocoque, nose, front wing, floor, sidepods, engine cover, rear body, rear wing, simplified suspension and
  wheels in one Fusion assembly; vehicle-level report (components, interfaces, rule-status matrix, open assumptions).

## Later (designed for, not built)

CFD / FEA / thermal (Phase 7), optimisation loops (8), drawings (9), BOM (10).

---

## Risks / limitations

| Risk | Mitigation |
|---|---|
| Fusion MCP only exposes "run script" | Deterministic generators + one runner + read-only inspection; live tests per generator. |
| Script blocked while a command dialog is open in Fusion | Error is reported; close the dialog and `step` again. |
| Fusion document not saved (Autodesk MCP rule: save only on explicit request) | Records + generators rebuild any component. |
| FIA regulations revised frequently | Source stored with issue/date/hash; re-check fia.com before relying on a rule. |
| LLM output variability | Schema validation, code gates, bounded loops, full run log. |
| Windows/OneDrive file locks | Atomic write with retry; idempotent registration. |
| Fusion ignores `transform2` on the only root occurrence (2705.x, verified live) | Empty identity anchor occurrence + placement read-back that raises; non-strict canary live test. |
| Fusion MCP add-in leaks one stdout/stderr wrapper per script call; output is lost after a few hundred calls | `FusionOutputLost` → `BLOCKED_FUSION`; UI status poll without scripts; restart Fusion to reset. |
| Fusion MCP add-in rolls back a raising script's changes | Model-changing scripts end normally and report via `@@RESULT@@`. |

---

## Before making this repository public (done)

This public repository is a clean copy with a fresh history; development continued in a private archive.

- [x] **FIA source documents.** The FIA regulations PDF and its text extract are not included and are ignored by
  git. `scripts/fetch_fia_source.py` installs them locally (hash-checked, see `fia_rules/source/README.md`).
  Without them, retrieval returns no snippets and every fast-mode FIA status stays `NOT_VERIFIED`. The tests use a
  synthetic fixture (invented text, not FIA); tests that need the real document skip when it is absent.
- [x] **Manufacturing rule source.** The original rule notes were replaced with an English summary in our own
  words (`manufacturing/source/DFM_rules_summary.md`), with the same rule ids and values. Historical run records
  keep the quotations they were built with.
- [x] **Author email.** The single commit uses the GitHub no-reply address.
- [x] **Run metadata.** `data/` was reduced to an example set (whole files). Claude Code session IDs were blanked in
  the reasoning `*.meta.json` files and are no longer written; the reported cost per call is kept.
- [x] **Licence.** MIT for the code (`LICENSE`); it does not cover the FIA regulations.

## Milestone 2.0 — Fast mode: prompt → Fusion → assembled Mini F1 — DONE

| Phase | Commit |
|---|---|
| P0 audit (`docs/fast_mode_plan.md`) + two stale historical-record tests fixed | af509ca |
| P1 prelude, contract, safety validator, part runner, checks, registry, rebuild, live smoke | 7c9cd93 |
| P2 FIA snippet retrieval, lean `claude -p` reasoner, plan/part/repair prompts | f84b221 |
| P3 resumable orchestrator, CLI, optional visual review (+ run-id collision fix 99cf0eb) | ff34a89 |
| P4 design service, `/api/design`, revamped default UI (strict UI under `/advanced`) | ca1db4f |
| P5 docs, full unit suite, live suite | see `docs/dev-log/fast_mode_progress.md` |

Since then: the first real Mini F1 run (4 parts, 2026-10-10), a pose correction, the extension to 18 parts with
derived (mirrored) right-hand parts, part revision/revert, colour palette, local rendering and a refinement pass on
9 components (2026-10-12). Details: `docs/dev-log/`. Next: more render angles, FIA reference-volume checks.
