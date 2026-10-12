> Historical development diary, not maintained; hashes refer to a private archive.

# Fast mode progress

Resume from here in a new session. Plan: `docs/fast_mode_plan.md`.

## Where we are / next steps (2026-10-11)

**State**
- 18-part Mini F1 assembly: 4 core parts (MON-001, FLR-001, FWG-001, RWG-001) + wheels, suspension, sidepods, engine
  cover, halo, mirrors; right-hand parts derived from the left (mirror / yaw180, zero Claude calls).
- Revise / Revert per part, plate-bending fix, colour palette `data/mini_f1/palette.json` (FLR-001 now #4A4F58) and
  Apply palette (recolour in place, read back).
- Render pipeline (`fusion/render.py`, `agent/render_run.py`, CLI `python -m agent render`, UI Render button):
  long-lens camera (true 50 mm distance, narrowed angle; Fusion moves the eye back - read back and noted),
  Photobooth environment, solid #3A3F47 background, ground reflections on, presets draft / standard / final,
  custom size up to the 4000 px API limit, PIL crop around the measured car (`fusion/render_crop.py`), framing
  calibration keyed by camera, aspect ratio and viewport size 1920x841 (`fusion/render_calibration.json`).
- Current run: `20261011-201406-rebuild-assembly-of-20261011-185`. Last render: RD09 (draft q25, 3600x2400,
  cropped natively to 1551x1034). The final render was NOT run (not needed).

**Facts to remember**
- Fusion runs on an expired-trial licence, but local rendering works.
- The MCP stdout wrapper depth rises about 1 per script call: restart Fusion before long sessions, then Rebuild
  assembly from the UI (zero Claude calls) and continue on the new run.
- Never resize the Fusion window: the render calibration is keyed to the viewport size (1920x841).
- The Fusion document cannot be saved; the registry (`data/mini_f1/components/`) is the source of truth.

**Open items (priority order)**
1. UI screenshots can come out in a white / edge-line style (viewport visual style): the screenshot path should
   set the visual style explicitly and restore it afterwards (the document / viewport only, not global preferences).
2. Refinement round: front-wing flaps as separate stepped elements, sidepod edges / undercut, floor edge, engine
   cover, suspension readability.
3. More render angles: front three-quarter, side profile, top.
4. Optional higher-resolution render (4000 px per side is the API limit; a quality-75 final needs a longer timeout).
5. Register a free Fusion licence only when no work is running.

| Phase | State | Commit |
|---|---|---|
| P0 audit → `docs/fast_mode_plan.md` | DONE | af509ca |
| P1 prelude, contract, validator, part runner, checks, registry, rebuild, live smoke | DONE | 7c9cd93 |
| P2 FIA retrieval, prompts, schemas | DONE | f84b221 |
| P3 `agent/design_run.py` orchestrator | DONE | ff34a89, 99cf0eb |
| P4 service + UI revamp | DONE | ca1db4f |
| P5 cleanup, docs, full suites | DONE | a4bc429 |

## Open issues

- Two historical-record tests were stale on 3e05f46 (they predated the generator-3 BRK-001 record); test
  expectations fixed, data unchanged.

## P1 results

- New: `fusion/prelude.py`, `fusion/script_safety.py`, `fusion/part_runner.py`, `fusion/assembly.py`,
  `validation/part_checks.py`, `vehicle/parts.py`, `agent/fast_config.py`, `docs/fusion_script_contract.md`,
  `docs/coordinate_system.md`; `ProjectStore.list_parts/get_part/save_part` (strict `list_components` unchanged).
- Unit: `tests/test_fast_parts.py` (31). Live: `tests/integration/test_fast_live.py` passed on 2705.1.30 —
  3 hand-written parts (box with negative-distance cut, symmetric wing with joined endplates, rotated loft) all
  checks VERIFIED, idempotent rebuild, mate measurement (touching + 170.000 mm gap), as-built rigid joint,
  3 screenshots. One part = 1 script call (build + place + measure). Whole smoke run ≈ 9 script calls.
- Live facts found: (1) an uncaptured `transform2` is discarded when the next component is created → the
  prelude snapshots immediately after each move; (2) `snapshots.add()` raises "Has no pending snapshot" when
  nothing moved → guarded by `hasPendingSnapshot`; (3) interference results with > 2 occurrences cannot be
  attributed → measured per pair; (4) screenshots add no wrapper layer; (5) the view cube "top" came out rotated
  180° after a custom camera → every view uses an explicit camera script (3 calls).

## P2 results

- `fia_rules/retrieval.py`: articles parsed from the extracted text (page header blocks removed, TOC pages and
  C18 appendix lists skipped); per part ≤ 6 verbatim snippets ≤ 400 chars with article, page, SHA-256; C2.3.1
  (structured rule) always first. `fia_status`: VERIFIED/NON_COMPLIANT only for measured extent rules
  (C2.3.1, max |Y| 950 mm per part), else NOT_VERIFIED.
- `agent/fast_reasoning.py`: `claude -p --system-prompt-file … --json-schema … --output-format json --tools ""`;
  responses cached per call name (resume = zero calls); meta records tokens incl. cache reads.
- `agent/fast_prompts.py`: Mini F1 kit, plan/part/repair prompts (part + repair share one static system prompt =
  instructions + `docs/fusion_script_contract.md`), schemas, deterministic plan gate.
- Unit: `tests/test_fast_reasoning.py` (17). Paid plumbing call 1/2: OK (claude-opus-5-5, 8.6 s, 1150 cache-creation
  tokens, $0.01 reported).

## P3 results

- `agent/design_run.py`: `create_design_run` / `Orchestrator.advance` / `record_answer` / `Orchestrator.rebuild`;
  state in `data/<project>/design_runs/<run>/run.json` (default project `mini_f1`, Fusion namespace `mf1`, one
  tagged Fusion document per run `mf1:<run_id>`). Plan gets one retry on schema/gate rejection; one blocking
  question max (a second one is ignored and recorded); parts: 1 call + ≤ 2 repairs (compact error only), unsafe
  bodies never reach Fusion, non-repairable failures (placement) fail the part; failed parts don't stop the run.
  FusionOutputLost / FusionUnavailable / script budget → `BLOCKED_FUSION` + restart banner; resume repeats no
  Claude call and no finished part. Brief naming a registered part id → rebuilt from its stored script.
  `summary.md` is a Python template. Optional `--visual-review` (off): one advisory call with the iso image.
- CLI: `python -m agent design | design-step | design-answer | design-status | rebuild | parts`.
- Unit: `tests/test_design_run.py` (13).

## P4 results

- `agent/design_service.py` (one run at a time in a background thread; view model from run.json only) and
  `/api/design...` routes in `ui/server.py`; strict routes unchanged.
- `ui/static/index.html` + `fast.js` = new default page: brief box + Run (+ image attach, visual-review toggle),
  progress strip PLAN · PARTS (4 chips) · ASSEMBLE · CHECK · DONE, last 15 log lines, one question card,
  "Restart Fusion" banner + Continue, results (iso large, front/top thumbnails, parts table with check/FIA chips
  and Rebuild buttons, assembly results, assumptions, counts, summary.md). Strict UI moved to `/advanced`
  (`advanced.html` / `advanced.js`). Rendered in headless Edge from a fake-backed run with real Fusion
  screenshots; fixed `[hidden]` being overridden by flex rules.
- Unit: `tests/test_design_service.py` (7); `tests/test_service_and_ui.py` updated for `/advanced`.
- ff34a89 was committed while one test failed intermittently (run-id collision); fixed in 99cf0eb.

## P5 results

- Cleanup: the P0 audit found no code unreachable from both fast and strict mode; nothing removed. Strict UI moved
  to `/advanced`; docs updated (README, architecture §2 + §13 + §14, development plan Milestone 2.0).
- Paid plumbing call 2/2: one real part call (TST-010 test floor) with the production part system prompt → valid
  body first try (12 s, 681 output tokens, 3724 cache-creation tokens, $0.043 reported); stored verbatim in
  `tests/integration/fixtures/` and built by the live suite.
- Unit suite: 272 passed. Live suite (`python -m pytest -m fusion`, throwaway tagged documents): 13 passed + 1
  expected XFAIL (canary: Fusion still ignores transform2 on the only root occurrence). Fusion 2705.1.30, process
  started 10:52 — NOT freshly restarted (not restarted by the agent; 0 documents open). Wrapper depth 32 before →
  108 after (≈ 76 script calls).

## Next

- **Restart Fusion** (depth is 108), then run the Mini F1 from the UI (README §6).
- After the first real run: compare plan envelopes vs. real geometry, mates vs. measured contacts, repair counts.

## Open issues

- The Fusion-side checks are concept-level; mates are measured, not constrained (as-built rigid joints only).
- FIA: only C2.3.1 (per-part |Y| ≤ 950 mm) is measurable; all other cited articles stay NOT_VERIFIED.
- `/api/status` Claude pill reflects the strict-mode reasoner selection (auto → Claude Code when available).

## First real Mini F1 run and correction pass (2026-10-10)

- Run `20261010-145347-…` (d936e28): 4 parts built first try, 5 Claude calls, 8 script calls; MON-001/FLR-001
  measured 28.46 mm apart. Root cause: MON-001 v1 script hard-codes world Z in the part frame (zb = 30) while the
  plan pose adds Z = 30 again → tub bottom Z = 60; 28.46 mm = distance from the tub's rear-bottom edge to the
  diffuser ramp (30·cos(atan 1/3)); flat-floor gap 30 mm.
- Correction (31bde80): MON-001 pose Z 30 → 0 = v2 (script unchanged; v1 kept in components/history). Live on a fresh
  Fusion (depth 1 → 18): all three mates touching, gap 0.0 mm.
- New: Rebuild assembly (93872d3; CLI, API, UI button) - registry → fresh Fusion design, zero Claude calls.
- New: plan gate checks planned envelopes per mate (80a25d9).
- Open: a part that is smaller than its envelope on a mating face still passes PART-BBOX; the mate measurement is
  what catches it. Candidate: an advisory "reaches the envelope on mate faces" check.

## 18-part readiness (2026-10-10, unit-tested only, no live run)

- Kit: `MINI_F1_CATALOG` = the 4 core parts + 14 optional ones (WHL-FL/FR/RL/RR, SUF-L/R, SUR-L/R, SDP-L/R,
  ENG-001, HAL-001, MIR-L/R). A run's kit = core + every optional id the brief names (`kit_for_brief`); the gate
  still requires exactly the kit. Part ids may carry a side/corner suffix (`[A-Z]{3}-(\d{3}|[A-Z]{1,2})`).
- Mates: new `clear` (keep-clear, value_mm = minimum clearance; measured, never jointed, no mate face).
- Assembly: far-apart unmated pairs skipped (bbox prefilter, PAIR_NEAR_MM = 10), interference only for
  bbox-overlapping pairs; the synthetic 18-part layout measures 22 of 153 pairs. The in-script
  `occurrence.boundingBox` prefilter is NOT yet verified live.
- Budget: per segment; resuming a BLOCKED_FUSION run starts a new segment.
- Wheels get no C2.3.1 snippet (the rule excepts wheels).
- Not done: mirror/clone helper for left/right parts (each side is its own Claude call).

## Derived left/right parts (2026-10-10)

- Plan: a right part may carry `mirror_of: <LEFT-ID>` + `mirror_mode: mirror | yaw180`; Claude designs only the
  source. The gate rejects a mirror_of that is missing, itself, a derived part, another kind of part, a bare
  mirror_mode, and yaw180 for non-wheels. Derived mates = the source's mates with ids mapped (vehicle/mirror.py).
- mirror (handed parts): the source script builds in the derived part's own component, then a Mirror feature of
  all bodies about the component XZ plane + a Remove feature per source body (fusion/prelude.py `_mirror_y`), then
  the mirrored pose S·P·S = (x,-y,z), (-roll, pitch, -yaw). Chosen over negating Y in the point helpers because a
  body script also uses planes, extrude directions, revolve axes and raw API calls that a point-helper flip does
  not mirror; the feature acts on the finished bodies and stays parametric.
- yaw180 (wheels): same script, rigid pose S·P·Sx (level wheel: y -> -y, yaw -> 180 - yaw); hub boss stays inboard.
- PART-DERIVED: volume within 1e-6 relative, same solids/lumps, local bbox mirrored / equal, world bbox = source
  mirrored about Y = 0. Records carry `derived` {source_id, source_version, mode, note} and exact `geometry`.
- STALE is computed on read (source has a newer version); `python -m agent rebuild-mirror <PART-ID>` / UI
  "Re-derive" re-derives from the latest source (new version, history kept). Derived parts cannot be revised or
  moved directly.
- Live (2705.1.30, throwaway doc, tests/integration/test_mirror_live.py): asymmetric box+lug at pose
  (200,300,50)/(10,20,30) mirrored, wheel disc with inboard hub boss yaw180: volume rel dev 0, local bbox dev 0,
  world bbox dev 0, placement dev 0, lug at local -Y, right hub boss inboard (y -540..-440), keep-clear mates
  measured (600 / 880 mm). Depth 8 -> 14 for the passing run (14 script calls across 3 attempts).
- Fusion facts found: a ROTATED occurrence's world bbox is the axis-aligned box of its transformed LOCAL bbox
  (not the tight geometry box: +7.8 / +16.1 mm for the test part) - rotated parts need envelopes sized to that;
  MirrorFeature.bodies reports 2 for one input body; removed bodies leave comp.bRepBodies.

## Overlap depth, measurement version 2 (2026-10-10)

- Planned-overlap mates: each interference piece (lump) is measured on its own with a 9 x 9 grid of rays along the
  contact direction (planned envelopes, else the piece's thinnest side) through both parts; depth = the longest
  stretch inside both. Version 1 (smallest bbox side of each Fusion result body) stays in overlap_depth_bbox_mm.
  Rays that cannot decide -> ADVISORY / NOT_VERIFIED with the bbox value and a note. Results carry
  measure_version 2 and depth_method; old runs are not re-evaluated.
- Live, read-only, run 20261010-222202 (9 overlap pairs, 36 s, depth 38 -> 39), ray vs v1:
  SDP-L 20.5 vs 164.5 (VERIFIED, <= 25) · SUF-L 40.8 vs 88.9 · SUR-L 25.2 vs 25.2 · MIR-L 21.3 vs 21.3 ·
  ENG-001 47.0 vs 47.3; every right-hand part identical to its left. Fusion grouped SUF-L's pieces differently
  between two calls (v1: 50.75 earlier, 88.855 now), which confirms that v1 depended on grouping.
- Limits: the grid can miss a sharp corner (SUF-L 40.8 vs ~43-44 at the deepest beam corner); the thinnest-side
  fallback measures a beam's own thickness when a beam enters at a shallow angle (not the case here: every piece
  is thinnest along Y, the wall normal).

## Colour palette and Apply palette (2026-10-11)

- `data/<project>/palette.json` (vehicle/palette.py): part id -> `{"color": "#RRGGBB", "finish": glossy_paint |
  matte_rubber | satin}`; bad hex, unknown finish, unknown keys and non-part ids are rejected. Used by every build,
  rebuild, derive and revision; a derived part not listed uses its source's entry; a part listed nowhere gets the
  built-in default of its prefix. An invalid file never stops a build (default colours, logged once) but is refused
  by Apply palette.
- Colour lives only in the build script's config (`paint`), never in the spec or the script body, so it never
  changes the script hash or the part version; changing the palette creates no new versions.
- Fusion: one design appearance per finish + colour, `agent <finish> <RRGGBB>`, copied from a library base with its
  colour property overridden (`opaque_albedo`, or `metal_f0` for the satin metals): glossy_paint = Paint - Enamel
  Glossy, matte_rubber = Rubber - Soft, satin = Steel - Satin. An unavailable finish falls back to plain colour on
  the paint base (a read-back note, not a mismatch).
- Apply palette (`python -m agent recolor <run>`, `POST /api/design/<id>/recolor`, UI button next to Rebuild
  assembly): ONE script recolours every built part in the run's open design in place (no geometry change, refuses
  above REVISE_MAX_DEPTH), reads back each body's appearance + colour, then re-shoots iso/front/top (3 calls).
  Recorded as `run["recolors"][Cnn]`, shots in `recolors/Cnn/` and as the run's current screenshots.
- Live (2705.1.30, run 20261011-140553, 18 parts): 18/18 read back exactly, 4 script calls (wrapper depth 41 at the recolour call).
- Face zones (palette entry `zones: [{rule, color, finish}]`, appearance overrides on faces, geometry untouched):
  `wheel_rim` = faces within radius rim_diameter/2 (+0.5 mm) of the local Y axle that start no deeper than the
  recessed rim face (width/2 - rim_recess_depth, -2 mm); `cockpit` = the only planar face at the body's top Z is
  the rim top, every face whose XY bbox lies inside it (+1 mm) is selected (rim ring, cockpit walls and floor).
  Dry run on the live design: 23 faces per wheel (nearest tyre face 10 mm outside the radius), 10 on MON-001.
  A rule that cannot decide (missing dims, no unique top face, no face) is reported as a mismatch, never guessed.
- Fusion fact: `BRepFace.appearance` returns the EFFECTIVE appearance (never None); only
  `appearanceSourceType` (Override / Face source) identifies an override. A first version cleared "overrides" on
  every face (~900 writes) and the call exceeded the 180 s client timeout (C02, recorded as failed; Fusion still
  finished it). Writes are now made only where the value differs.
- Live C03 (zones): 18/18 parts and all zones read back exactly (cockpit 10 faces #CBD0D8, each wheel 23 faces
  #C8CCD2, no stray overrides), 4 script calls.

## Render pipeline (2026-10-11, unit-tested; live render pending)

- `fusion/render.py` + `agent/render_run.py` (`Orchestrator.render`, `python -m agent render <run> [--views iso,front,top]
  [--quality 50|75] [--environment NAME]`, `POST /api/design/<id>/render`, UI "Render" next to Rebuild assembly with
  view checkboxes, quality 50/75, progress bar + state per view, finished image shown large).
- API checked against the local Fusion API stubs (adsk/fusion.py): Design.renderManager -> sceneSettings,
  renderEnvironments, rendering; Rendering.aspectRatio / resolutionWidth / resolutionHeight / renderQuality (25-100,
  75 = Final) / startLocalRender(filename, camera) -> RenderFuture (renderState Queued/Processing/Finished/Failed,
  progress 0..1). No cancel call exists.
- Flow: PREFLIGHT (read-only: depth, document by tag, is it active, environment names, scene) -> refused above
  RENDER_MAX_DEPTH 100 or when the document is not open (nothing rendered, nothing shot). Per view: START (activate
  by tag, the view's screenshot camera via the shared `CAMERA_HELPERS`, scene camera type orthographic in the run's
  document, aspect ratio CUSTOM before the resolution 1920x1280, quality, startLocalRender to an ASCII temp path; the
  RenderFuture is kept in a module attribute `adsk._agent_render_jobs`) -> POLL once per minute -> copy to
  `renders/RDnn/<view>.png`. Refused / failed / 15-min timeout -> MCP screenshot 2400x1600, recorded as
  `screenshot_fallback` with the reason and a "NOT a render" note. A lost RenderFuture completes from the output file.
- run.json `renders[RDnn]`: status, preflight, items {view, path, size_bytes, width, height, quality, seconds, method,
  state, progress, settings read-back, note, error}, script_calls, depth. No geometry change, no registry write.
- Environment choice: only names from the last preflight's library list (none guessed); default = the document's scene.
- Unit: `tests/test_render.py` (16).
- Live RD01 (2705.1.30, run 20261011-185334, iso, quality 50): preflight depth 24, the run's document active (by tag,
  1 document open); read back custom aspect, 1920x1280, quality 50; rendered first try in 304.4 s (state checks
  every 60 s), PNG 1920x1280, 285 289 bytes, 7 script calls (depth 25 -> 31). Scene: solid-colour background, ground
  shown, ground reflections off, camera type already orthographic. Environment library: Sharp Highlights, Rim
  Highlights, Cool Light, Warm Light, Soft Light, Grid Light, Custom..., Crossroads, Dry lake bed, Field, Photobooth,
  Plaza, Skylight, Snow Field ("Photobooth", one word; "Custom..." is a placeholder, not an environment).
- Open: FRAMING. The render does not keep the fitted viewport extents: the car fills ~38 % of the width (centred),
  while the screenshot of the same camera fills the frame. Candidate: set the orthographic camera's viewExtents from
  the assembly bbox (with margin) for the render instead of isFitView.

## Render framing, background, light and presets (2026-10-11, unit-tested; live comparison pending)

- Presets: draft (quality 25, 1280x853), standard (50, 1920x1280, default), final (75, 2400x1600); the render record
  carries preset, quality, resolution, all options, per-item seconds and the total seconds.
- Render camera (renders only; screenshots unchanged): same view direction / up as the screenshot of that view,
  framed from the 8 corners of every built part's measured world bbox so the larger relative side fills
  RENDER_FILL 0.8 with an even margin (`fusion/render_frame.py`, pure helpers run inside Fusion and in
  `tests/test_render_frame.py`; perspective distance and sideways target shift both found by bisection, eye always
  in front of the nearest point). Perspective (default, focal 35..85 mm, default 50): sceneSettings.cameraFocalLength
  is set, the viewport camera's perspectiveAngle is read back and matched to a 36x24 mm film axis (recorded as
  frame.axis; no match within 2 % -> vertical assumed, noted). Orthographic: setExtents on a camera copy that is
  not assigned to the viewport. The framed camera object goes to startLocalRender.
- Scene (run's document only): environment (lighting; library name, "Custom..." placeholder rejected) set BEFORE
  backgroundSolidColor (default #3A3F47), brightness (default 1000 lux), lightAngle (default 30 deg, provisional),
  ground shown, ground reflections on by default with roughness 0.15. Read back: scene, environment (expected
  unreadable with a solid background), settings, frame.
- UI: preset select, environment select (real names only), "Render settings" (camera, focal, background colour,
  brightness, light angle, ground reflections, roughness). Unit: test_render (16, updated) + test_render_frame (15).
- Live 2026-10-11 (2705.1.30, run 20261011-201406, draft iso, perspective 50 mm, #3A3F47, reflections on):
  - RD01-RD03: start script returned success with EMPTY output in < 1.5 s, nothing rendered (no file). The script had
    one 5.8 KB base64 CFG line (144 corners). Fixed (bc13478): boxes rounded to 0.1 mm, longest line 2.1 KB.
  - RD04 Soft Light 245.7 s, RD05 Photobooth 306.9 s, RD06 Skylight 309.3 s (draft is not faster than standard was).
  - perspectiveAngle for 50 mm read back 0.69111 = 2 atan(18/50): Fusion's focal -> angle uses the HORIZONTAL 36 mm
    axis (error 0.0).
  - Framing NOT as planned: planned 78 % x 80 %; measured (PIL) 33.6-35.2 % x 35.4-36.6 %, centred within 1 %.
    The render keeps direction / target but is 2.25x wider (= aspect 1.5 squared) than the planned field; the
    viewport screenshot of the same camera measured ~51 % (1.5x). Hypothesis, not verified: the angle is applied
    to the other axis (once in the viewport, again in the render). Calibration needs a verification render.
  - Solid background with an environment: backgroundEnvironment is unreadable afterwards (RuntimeError), but the
    environment still lights the scene: the three renders differ clearly and cameraExposure read back 9.53 / 8.84 /
    13.37 EV. Skylight at 1000 lux is badly underexposed.
- Calibration (a5420f8, 685b093): fusion/render_calibration.json, perspective 3:2 field_scale 2.3277 x 2.2549 from
  RD04-RD06 (mean planned / measured fill); no entry -> uncorrected + note. Start path: the empty start results WERE
  caught as FusionOutputLost (expect_result=True through run_script); gaps closed: lost calls now counted, no
  "restart Fusion" advice below the depth limit, scripts with a line > MAX_LINE 2500 are never sent.
- Read-only camera probe: viewport 1920x841 (2.283:1); Rendering settings at rest = current-viewport aspect,
  1920x841. Both "3:2 applied twice" (2.25) and "angle applied to the viewport's vertical, the render keeps that
  horizontal field" (2.283) fit the measurements; the second would make the factor depend on the window size
  (viewport now recorded per render; a render after resizing the window would decide).
- RD07 (draft, Photobooth, calibrated, floor #4A4F58 via Apply palette C01): measured 75.2 % x 81.4 % (planned
  75.3 % x 80.0 %), centred +0.2 % / +1.2 %, 242.8 s. Side effect: the eye moved from 906 to 419 cm, so the
  picture has a wide-angle look (~22 mm equivalent field), not a 50 mm look. Candidate fix: narrow the camera's
  perspectiveAngle by the measured factor at the 50 mm distance instead of moving the eye.
- Angle-based framing (75311e1) live RD08 (draft, Photobooth, viewport 1920x841 unchanged, camera unmoved since
  RD07): distance set 905.97 cm (true 50 mm), angle narrowed 0.6911 -> 0.3166 rad (nominal 112.75 mm; scene focal
  read back 112.745). Fusion MOVED THE EYE to 2042.9 cm = 905.97 x 2.2549 (exactly the tangent ratio), so the field
  was unchanged: measured 33.3 % x 34.2 %, centred +1.0 % / -1.9 %, 122.6 s, telephoto look. The RD08 note "50 mm
  lens at 905.97 cm" is wrong (fe80e8d now reads the distance back and reports a moved eye). Conclusion so far: on
  assignment Fusion keeps the camera's visible extent; neither the eye distance (RD07: worked, wide-angle) nor the
  angle alone gives a 50 mm look at 80 % fill. Untested candidate: assign the narrowed angle first, then the eye
  in a second assignment, and read both back.
- Crop (9e24029): the long-lens render (RD08 camera) is cropped in PIL around the measured car (3:2, car 80 %, even
  margin, background padding at an edge, resize down only). API: Rendering width / height 108..4000 px (docs);
  the largest RenderResolutions preset is 3300x2550; 4800x3200 is outside the documented range and was not tried.
- Live RD09 (draft q25, 3600x2400, Photobooth): settings read back 3600x2400 custom; 663.8 s (progress 12.9 % at
  ~10 min, then fast: not linear); full PNG 843 kB, car 33.4 % x 34.5 %; crop box [1062, 640, 2613, 1674], native
  1551x1034, kept (NOT upscaled; target 2400x1600), 560 kB, car 77.5 % x 79.9 %. 1:1: clean anti-aliased edges, no
  visible noise (background std ~0.1 per channel), faint tessellation facets on the curved white sidepods.
  Consequence for the final: at the 4000 px API limit the native crop is ~1720x1150, below 2400x1600; a quality-75
  final at that size will very likely exceed the 15-min timeout (RENDER_TIMEOUT_S is configurable).
