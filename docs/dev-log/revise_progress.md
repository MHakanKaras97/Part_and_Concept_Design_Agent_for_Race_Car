> Historical development diary, not maintained; hashes refer to a private archive.

# Revise progress (fast-mode part revision)

Resume from here in a new session. Spec: the "Implement Fast Mode Part Revision" brief (2026-10-10) + addendum A-F.
Baseline before this work: commit 4edfc70, 286 unit tests passed.

| # | Item | State | Commit |
|---|---|---|---|
| 1 | Frame contract + frame validation + MON-001 v1 regression + MON-001 v2 legacy_world | DONE | 6adf0e6 |
| 2 | Revise core: CLI + registry v+1 + failure rollback + gates | DONE | a64762c |
| 3 | Revert / `rebuild PART --version N` | DONE | a64762c (shares the transaction code with 2) |
| 4 | API route + UI (part Revise box, Revert, before/after screenshots) | DONE | b63a1ae |
| 5 | Advisory mate-face check | DONE | 2d78670 |
| 6 | Run selector status bug | DONE | 780339a |
| 7 | One live test (only if wrapper depth < 100) | DONE | (this commit) |

## Done

### 1. Frame contract
- `docs/fusion_script_contract.md`: scripts build in the part-local frame; never encode the world position; pose
  alone places the part; world envelope = local geometry transformed by the pose; no double offsets; legacy section.
- Prompts: plan notes must give part-frame coordinates; the part payload carries `world_to_local` (pose).
- `fusion/prelude.py`: the build script measures `bbox_local` (native bodies, identity, before placement) - same
  script call, fail-soft.
- `validation/part_checks.py::frame_check` -> check `PART-FRAME` (blocking, repairable), tolerance `BBOX_TOL_MM`
  (the PART-BBOX per-side allowance). part_local: local bbox inside the inverse-pose envelope (8 corners), plus
  frame-mismatch detection (box inside the world envelope and more faces on the world envelope than on the local one
  -> `FRAME_MISMATCH` diagnostic with expected and measured bounds). legacy_world: identity pose only.
- `PartRecord.frame_mode` (`part_local` default | `legacy_world`) + `frame_note`; `build_part(..., frame_mode)`,
  `rebuild_part` uses the record's mode; `compact_error` carries `measured_bbox_local` / `expected_local_envelope`.
- `data/mini_f1/components/MON-001.json` (v2, active): added `frame_mode: legacy_world` + note only (script, pose,
  version, history unchanged; `history/MON-001.v1.json` untouched).
- Tests: `tests/test_frame.py` (MON-001 v1 double offset from the real history record, MON-001 v2 legacy rebuild,
  rotated pose, design-run repair with the diagnostic). Two existing check-set expectations gained PART-FRAME.

### 2 + 3. Revise core and revert (`agent/revise.py`)
- `Reviser.revise(run, PART|assembly, instruction)` / `Reviser.revert(run, part, N)`; CLI
  `python -m agent revise <run> <PART-ID|assembly> "<instruction>"`, `python -m agent rebuild PART --version N [--run R]`
  (without --run: the run that registered the active version).
- Transaction: preflight probe (1 read-only script: document open, depth <= REVISE_MAX_DEPTH=100) -> 1 Claude call
  (static `revise_system()` prefix shared with repairs; context = part spec + script + measurements + mated
  neighbours' boxes + planned mates + the part's FIA snippets + the instruction) -> gates -> build in the run's design
  (create_doc=False; <= 2 repairs, repair gets compact error + the failed body) -> neighbour pose changes -> mates
  (1 script, regressions fail) -> commit (v+1 each, `revision` dict + history kind/instruction) -> after screenshots.
- Gates (no Fusion, no repair call on rejection): schema/scope, one-line summary, dims, envelope, legacy_world identity
  pose, `mate_consistency` (the plan gate) + minimum unambiguous neighbour shift (one axis, one direction, neighbour's
  other mates still possible, not legacy_world), FIA C2.3.1 on the planned envelope.
- Failure after Fusion was touched -> rollback (rebuild base records, re-measure mates) -> FAILED; rollback failure or
  lost Fusion output -> CRITICAL + run banner; registry untouched in all failure cases.
- Script budget REVISE_SCRIPT_BUDGET=10 per step with the rollback reserved; assembly = ';' clauses, one part each,
  `<ID> position=x,y,z` / `move=dx,dy,dz` deterministic, otherwise a single-part revise; one transaction.
- Revert = new version (force_new) "reverted to vN"; reverting to the active version is rejected.
- Registry: `PartRecord.revision`, `PartHistory.kind/instruction`, `save_part(force_new=...)`. run.json `revisions`;
  `design_runs/<run>/revisions/Rnn/` (snapshot.json, reasoning/, parts/<id>/attempt_N.py, before_/after_<view>.png,
  diagnostic.json on failure). summary.md lists revisions.
- Tests: `tests/test_revise.py` (25). Fake Fusion: `from_params`, `geometric_mates`, documents, probe.

### 4. API + UI
- `DesignService.revise/revert/revision_image` (input checked synchronously, work in the one-at-a-time worker);
  routes `POST /api/design/<id>/revise {target, instruction}`, `POST /api/design/<id>/revert {part_id, version}`,
  `GET /api/design/<id>/revisions/<Rnn>/<before|after>_<view>.png`. View model: per part `revisable`,
  `active_version`, `revert_versions`; `revisions` (steps, bbox delta, neighbour adjustments, mates before/after,
  rollback, notes, counts, before/after image pairs, live events).
- `fast.js`: click a part row -> Revise box + "Revert to vN" buttons; "Revise assembly" box; revision cards (newest
  open). Parts table / cards re-render only when their data changes (an open box keeps focus and text).
- Checked in headless Edge with a fake-backed server (scratch harness): row click opens the box, the draft survives a
  poll, cards render, no JS errors. Fix found there: Claude-call count is per revision even with a shared reasoner.
- Tests: `test_http_revise_then_revert`, per-revision call count.

### 5. Advisory mate-face check
- `validation/part_checks.mate_face_checks`: per planned mate, the contact face from the planned envelopes (exactly
  one axis inside the contact window, overlap on the other two); per part expected envelope face vs measured bbox
  face -> PASS (|dev| <= TOUCH_TOL_MM) / WARNING / NOT_CHECKABLE (no unique face, e.g. MON/FLR whose envelopes
  interpenetrate, or edge contact; or no bbox). Never replaces the MATE-* Fusion measurement.
- In the design run CHECK phase (`assembly.mate_faces`, summary.md, UI assembly list) and in every revision
  (`rev.mate_faces` for the changed parts). Real Mini F1 registry: FWG/MON and RWG/MON faces PASS, MON/FLR NOT_CHECKABLE.
- Tests: `tests/test_mate_faces.py` (5) + one in test_revise.

### 6. Run selector status bug
- Root cause: `fast.js` built the run `<select>` once (page load / after starting a run); `refresh()` never updated
  it, so an option loaded while RUNNING kept saying RUNNING after the run finished (server data was correct).
- Fix: `design_service.run_label` feeds both `/api/design` (label) and the run view (`run_label`); after every poll
  `syncRunOption` reloads the list from the server when the selected option differs from the view.
- Tests: `tests/test_run_selector.py` - label contract, static wiring, and a headless-Edge test that loads the page
  while RUNNING, finishes the run and expects DONE (verified to fail with the old fast.js: "RUNNING then RUNNING");
  skipped when no Edge/Chromium is installed.

### 7. Live test (2026-10-10, Fusion 2705.1.30)
- Gate: read-only probe -> depth 19 (< 100), 2 user documents open ("Untitled", "Untitled").
- `tests/integration/test_revise_live.py`, ONE run: throwaway document `livetest-revise:<uuid>`, 2-part design run
  (scripted plan, no Claude), PART-FRAME VERIFIED with the real local bbox (TST-102 at pose (50,0,40): local
  (0,-30,0)..(100,30,30)); stand-in revision (scripted, no paid call) TST-102 height 30 -> 50: v2, bbox z 70 -> 90,
  mate touching VERIFIED before/after, mate faces PASS, 5 script calls; revert to v1 -> v3, bbox z back to 70, mate
  VERIFIED, 5 script calls. v1 kept. Document closed; user documents unchanged. Depth 20 -> 37. 1 passed.
- Paid plumbing: 1 `claude -p` call (revise prompt + ReviseResponse schema, no Fusion): valid output, minimal delta
  (height 50 + envelope), body unchanged and safe; 8.8 s, 5522 cache-creation tokens, $0.052 reported.

## Next
- Restart Fusion when convenient (depth 37 after the live test), then try Revise in the UI on the latest
  assembly-rebuild run (all parts at their active versions).

## Open issues
- A mate that breaks after the build is rolled back, not repaired (keeps the script budget <= 10).
- The revise repair call receives the failed body (needed to keep the unchanged features); the design-run repair does
  not.
- Frame mismatch detection is a bbox heuristic (face coincidence); a world-coordinate script whose box does not sit
  on the world envelope is still caught by the containment test only if it leaves the local envelope.
