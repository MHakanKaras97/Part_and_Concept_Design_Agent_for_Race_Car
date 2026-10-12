# Learning guide

A short path into the code for students and researchers. You need no Fusion and no Claude for anything here: the
tests use a fake Fusion (`tests/helpers.py: FakePartFusion`) and a scripted reasoner
(`agent/fast_reasoning.py: ScriptedReasoner`).

## How a request flows (fast mode)

```
brief ──► PLAN      agent/fast_prompts.py   plan prompt + JSON schema; gate_plan() checks ids, dims, envelopes, mates
      ──► PARTS     agent/design_run.py     one Claude call per part: the body of build(part)
                    fusion/script_safety.py static check of that body (catches model mistakes; NOT a sandbox)
                    fusion/prelude.py       wraps the body: document, anchor, component, parameters, placement,
                                            colour, measurement, one @@RESULT@@ line
                    fusion/part_runner.py   runs it through fusion/client.py (MCP), up to 2 repairs on failure
                    validation/part_checks.py  PART-* checks on what Fusion measured
                    vehicle/store.py        registry: data/<project>/components/<ID>.json (+ history/)
      ──► ASSEMBLE  fusion/assembly.py      minimum distance / interference per part pair
      ──► CHECK     validation/part_checks.py  mate_results(): touching / overlap / gap / clear
      ──► DONE      agent/design_run.py     render_summary() writes summary.md from a template
```

The AI never calls Fusion and never judges a result: Python decides every PASS/FAIL from Fusion's measurements.
`agent/design_service.py` turns `run.json` into the view the web page shows (`ui/static/fast.js`).

## Read these first

1. `docs/architecture.md` §1, §2 and §14: the core idea, the Fusion facts that shaped the design, fast mode.
2. `docs/fusion_script_contract.md`: what an AI-written part script may and may not do.
3. `agent/design_run.py`: `Orchestrator.advance()` is the whole pipeline in one place.
4. `validation/part_checks.py`: how a measurement becomes a result.
5. `tests/test_design_run.py`: a complete run with fakes, in a few dozen lines.

Then browse a real run: `python -m ui --read-only` (see the top-level README), or open
`data/mini_f1/design_runs/<run>/run.json` and `reasoning/` next to it.

## Five small exercises

Run `python -m pytest` before and after each one.

1. **Add a part kind.** Add an entry to `MINI_F1_OPTIONAL` in `agent/fast_prompts.py` (the id must match
   `PART_ID_PATTERN` in `vehicle/parts.py`, e.g. `BRG-001`). A brief that names the id now plans it
   (`kit_for_brief`). Write a test like those in `tests/test_kit_scaling.py`.
2. **Add a validation check.** In `part_checks()` (`validation/part_checks.py`), add e.g. `PART-VOLUME`: the solid
   volume must be above a minimum. Use `_res(...)` like the other checks, and test it with `FakePartFusion`.
   Think about scope: what does your check establish, and what does it not?
3. **Change the palette.** Edit `data/mini_f1/palette.json` (colours are cosmetic; no part version changes). Read
   `vehicle/palette.py` to see how zones such as `wheel_rim` and `cockpit` are chosen, and run `tests/test_palette.py`.
4. **Write a new mate rule.** Mates are `touching | overlap | gap | clear` (`PlanMate` in `agent/fast_prompts.py`,
   judged in `mate_results()`). Add one, for example `aligned` (same Y centre within a tolerance), to the schema, the
   judge and `agent/display_labels.py: mate_label()`, with tests.
5. **Replace the reasoner.** Any object with `calls` and
   `call(name, system, user, schema, images) -> dict` is a `Reasoner` (`agent/fast_reasoning.py`). Write one for
   another LLM provider and pass it as `reasoner_factory` to `Orchestrator` or `DesignService`. The answer must
   validate against `schema`; `ScriptedReasoner` shows the minimum.

## Common pitfalls

- **Treating the validator as a sandbox.** `fusion/script_safety.py` rejects obvious mistakes (imports other than
  adsk/math/json/re/traceback, file and process access, saving or closing documents, reaching outside the part). It does not make untrusted code safe. Only rebuild registries you trust.
- **Raising inside a Fusion script.** The MCP add-in rolls back a raising script's changes; report through
  `@@RESULT@@` instead (architecture §2).
- **Too many script calls.** Each call leaks one stdout wrapper in the MCP add-in; after a few hundred, output is lost
  until Fusion restarts. Budgets in `agent/fast_config.py` exist for this reason.
- **World coordinates in a part script.** Build in the part-local frame; the pose places the part (`PART-FRAME`).
- **Reading "PASS" as "correct".** PASS means the Fusion read-back matches the plan. It says nothing about
  structural adequacy or FIA compliance.
- **Editing stored records.** Runs and registry files are evidence; a change is a new version or a new run.
