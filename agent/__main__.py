"""Command line interface.

Fast mode (default path; project mini_f1):
    python -m agent design "Mini F1: ..." [--image ref.png]     # plan -> parts -> assembly -> checks -> screenshots
    python -m agent design-step <run_id>          # continue (after Fusion restart / answer)
    python -m agent design-answer <run_id> "<answer>"
    python -m agent design-status [<run_id>]
    python -m agent rebuild <PART-ID> [--run <run_id>]   # from the stored script, zero Claude calls
    python -m agent revise <run_id> <PART-ID|assembly> "<instruction>"   # v+1 in the run's Fusion design, or rollback
    python -m agent rebuild <PART-ID> --version N [--run <run_id>]       # revert: vN rebuilt, registered as a NEW version
    python -m agent rebuild-assembly <run_id> [--pose MON-001=0,0,0 --reason "..."]   # fresh Fusion design
    python -m agent rebuild-mirror <PART-ID> [--run <run_id>]   # re-derive from the source's latest version
    python -m agent recolor <run_id>              # apply data/<project>/palette.json to the run's open design
    python -m agent render <run_id> [--views iso,front,top] [--preset draft|standard|final] [--environment NAME]
                          [--camera perspective|orthographic] [--focal 50] [--background "#3A3F47"]
                          [--brightness LUX] [--light-angle DEG] [--no-ground-reflections] [--roughness 0.15]
                                                  # local render of the run's open design (screenshot fallback)
    python -m agent parts

Strict mode (Advanced; project prototype_bench):
    python -m agent new "Design a machined aluminium L-bracket ..." [--image drawing.png]
    python -m agent step <run_id>                 # continue after a reasoning response / answers
    python -m agent answer <run_id> M01="..." M02="..."
    python -m agent status [<run_id>]
    python -m agent components
    python -m agent rules [--type l_bracket]
    python -m agent rules-verify <rule_id> --by "<name>"
    python -m agent fusion-check
Global options: --project <id> (default: mini_f1 for fast mode, prototype_bench for strict mode)
                --reasoner file_exchange|claude_code (default: file_exchange; claude_code falls back to file exchange)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from agent.design_run import (DEFAULT_PROJECT, Orchestrator, create_assembly_rebuild, create_design_run,
                              load_design_run, record_answer as record_design_answer, runs_dir)
from agent.reasoning import ClaudeCodeBackend, FallbackBackend, FileExchangeBackend
from agent.workflow import Engine, create_run, load_run, record_answer
from fia_rules.rules import RuleSet
from fusion.client import FusionError, FusionMCPClient
from vehicle.mirror import staleness
from vehicle.palette import load_palette, paint_for
from vehicle.store import ProjectStore


def _print_state(run) -> None:
    d = run.data
    print(f"run {d['run_id']}  stage={d['stage']}  status={d['status']}  loops={d['loops']}")
    if d["status"] == "AWAITING_REASONING" and d.get("pending"):
        req = run.dir / d["pending"]["request"]
        print(f"  waiting for reasoning: {req}")
        print(f"  write the response to: {req.with_name(req.name.replace('.request.md', '.response.json'))}")
        print(f"  then: python -m agent step {d['run_id']}")
    elif d["status"] == "AWAITING_USER":
        print("  questions for the user (answer in your own words; your text is stored verbatim):")
        for q in d.get("questions", []):
            if q["id"] not in d["user_answers"]:
                print(f"    {q['id']} [{q['criticality']}] {q['question']}")
        open_ids = [q["id"] for q in d.get("questions", []) if q["id"] not in d["user_answers"]] or ["M01"]
        print(f"  answer with: python -m agent answer {d['run_id']} {open_ids[0]}=\"<your answer>\"")
    elif d["status"] == "BLOCKED_FUSION":
        print("  Fusion not reachable. Start Fusion, enable Preferences > General > API > Fusion MCP Server,")
        print(f"  then: python -m agent step {d['run_id']}")
    elif d["status"] in ("COMPLETED", "STOPPED"):
        print(f"  report: {run.dir / 'report.md'}")
        if d.get("registered"):
            print(f"  registered: {d['registered']['id']} rev {d['registered']['revision']}")
        if d.get("stop_reason"):
            print(f"  stop reason: {d['stop_reason']}")


FAST_COMMANDS = {"design", "design-step", "design-answer", "design-status", "rebuild", "rebuild-assembly",
                 "rebuild-mirror", "recolor", "render", "parts",
                 "revise"}


def _print_recolor(rc: dict) -> None:
    print(f"apply palette {rc['id']}: {'FAILED: ' + rc['error'] if rc['error'] else 'done'}  "
          f"script_calls={rc['script_calls']}  depth={rc['depth']}  palette sha256 {str(rc['palette_sha256'])[:12]}")
    for pid, r in rc["parts"].items():
        e, g = r["expected"], r["got"] or {}
        print(f"  {pid:8s} {e['hex']} {e['finish']:12s} -> {', '.join(g.get('hex') or ['-'])}  "
              f"{', '.join(g.get('appearance') or ['-'])}  {'OK' if r['ok'] else 'MISMATCH: ' + r['problem']}"
              + (f"  ({r['note']})" if r.get("note") else ""))
    for n in rc["notes"]:
        print(f"  note: {n}")
    if rc["screenshots"]:
        print(f"  screenshots: {', '.join(rc['screenshots'].values())}")


def _print_revision(rev: dict) -> None:
    c = rev["counters"]
    print(f"revision {rev['id']} {rev['kind']} {rev['target']}: {rev['state']}  claude_calls={c['claude_calls']}  "
          f"script_calls={c['script_calls']}  depth={c['depth_first']}->{c['depth_last']}")
    for s in rev["steps"]:
        print(f"  {s['part_id']}: v{s['base_version']} -> " + (f"v{s['new_version']}" if s["new_version"] else "-")
              + f"  {s['change_summary']}" + (f"  bbox delta {s['bbox_delta']}" if s.get("bbox_delta") else ""))
    for a in rev["neighbour_adjustments"]:
        print(f"  neighbour {a['part_id']}: pose {a['position_from']} -> {a['position_to']} ({a['reason']})")
    for m in rev["mates_after"]:
        print(f"  mate {m['title']}: {m['status']} (before {m.get('before')}) {m.get('measured')}")
    for n in rev["notes"]:
        print(f"  note: {n}")
    if rev.get("rollback"):
        rb = rev["rollback"]
        print(f"  rollback: {'verified' if rb['verified'] else 'NOT VERIFIED'} {rb['parts']}")
    if rev.get("error"):
        print(f"  {rev['error']}")


def _print_design(run) -> None:
    d = run.data
    c = d["counters"]
    print(f"design run {d['run_id']}  phase={d['phase']}  status={d['status']}  "
          f"claude_calls={c['claude_calls']}  script_calls={c['script_calls']}  depth={c['depth_first']}->{c['depth_last']}")
    for pid, st in d["parts"].items():
        print(f"  {pid}: {st['state']}" + (f"  v{st['version']}" if st.get("version") else "")
              + (f"  ({st['error']})" if st.get("error") else ""))
    if d["status"] == "AWAITING_USER":
        print(f"  QUESTION: {d['question']['text']}")
        print(f"  answer with: python -m agent design-answer {d['run_id']} \"<your answer>\"")
    if d.get("banner"):
        print(f"  {d['banner']}")
    if d.get("error"):
        print(f"  error: {d['error']}")
    if d["status"] == "DONE":
        print(f"  summary: {run.dir / 'summary.md'}")


def _fast(args) -> int:
    store = ProjectStore(args.project or DEFAULT_PROJECT)
    orch = Orchestrator(store)
    if args.cmd == "design":
        images = []
        for path in args.image:
            with open(path, "rb") as f:
                images.append((f.read(), os.path.basename(path)))
        run = create_design_run(store, args.brief, images=images, entered_via="cli: python -m agent design",
                                visual_review=args.visual_review)
        _print_design(orch.advance(run, on_step=lambda r: print(f"  .. {r['phase']} {r['events'][-1]['msg']}")))
    elif args.cmd == "design-step":
        _print_design(orch.advance(load_design_run(store, args.run_id)))
    elif args.cmd == "design-answer":
        run = load_design_run(store, args.run_id)
        record_design_answer(run, args.answer, entered_via="cli: python -m agent design-answer")
        _print_design(orch.advance(run))
    elif args.cmd == "design-status":
        ids = [args.run_id] if args.run_id else sorted(p.parent.name for p in runs_dir(store).glob("*/run.json"))
        for rid in ids:
            _print_design(load_design_run(store, rid))
    elif args.cmd == "revise":
        from agent.revise import Reviser
        run = load_design_run(store, args.run_id)
        _print_revision(Reviser(store, fusion=orch.fusion()).revise(run, args.target, args.instruction,
                                                                     entered_via="cli: python -m agent revise"))
    elif args.cmd == "rebuild" and args.version is not None:
        from agent.revise import Reviser, find_run_for_part
        run = load_design_run(store, args.run or find_run_for_part(store, args.part_id))
        _print_revision(Reviser(store, fusion=orch.fusion()).revert(run, args.part_id, args.version,
                                                                     entered_via="cli: python -m agent rebuild --version"))
    elif args.cmd == "rebuild":
        if args.run:
            _print_design(orch.rebuild(load_design_run(store, args.run), args.part_id))
        else:
            from fusion.part_runner import rebuild_part
            ns = store.load_project().fusion_namespace
            rec0 = store.get_part(args.part_id)
            b = rebuild_part(orch.fusion(), rec0, ns, f"{ns}:rebuild",
                             paint=paint_for(rec0.id, rec0.spec.mirror_of, load_palette(store.root)))
            rec = None
            if b.passed:
                from fusion.part_runner import to_record
                old = store.get_part(args.part_id)
                rec = store.save_part(to_record(b, ns, None, old.fia, frame_note=old.frame_note), None,
                                      "rebuilt from the stored script (cli)")
            print(f"{args.part_id}: {'rebuilt, all checks pass' if b.passed else 'FAILED: ' + (b.error or str([c.check_id for c in b.checks if c.blocking_failure]))}"
                  + (f" (v{rec.version}, document tag {ns}:rebuild)" if rec else ""))
    elif args.cmd == "recolor":
        rc = orch.recolor(load_design_run(store, args.run_id))
        _print_recolor(rc)
        return 0 if not rc["error"] and not rc["mismatches"] else 1
    elif args.cmd == "render":
        from agent.render_run import summary
        opts = {"preset": args.preset, "environment": args.environment, "camera": args.camera,
                "focal_mm": args.focal, "background": args.background, "brightness_lux": args.brightness,
                "light_angle_deg": args.light_angle, "ground_roughness": args.roughness,
                "ground_reflections": False if args.no_ground_reflections else None,
                "size": args.size, "crop_output": args.crop_output, "crop": False if args.no_crop else None}
        rd = orch.render(load_design_run(store, args.run_id), [v.strip() for v in args.views.split(",") if v.strip()],
                         {k: v for k, v in opts.items() if v is not None})
        print(f"render {rd['id']}: {rd['status']}  preset {rd['preset']}  {rd['seconds']} s  "
              f"script_calls={rd['script_calls']}  depth={rd['depth_first']}->{rd['depth_last']}")
        print(f"  {summary(rd)}")
        for it in rd["items"]:
            if it.get("render_full"):
                c = it.get("crop") or {}
                print(f"  {it['view']:5s} full    {it['render_full']}  {it.get('full_size')}  car share "
                      f"{c.get('car_fill_full')}  crop box {c.get('box')} native {c.get('native_size')} -> "
                      f"{c.get('output_size')} (factor {c.get('factor')}, {c.get('resized')}), car share after "
                      f"{c.get('car_fill_cropped')}")
            print(f"  {it['view']:5s} {it['method'] or '-':20s} {it['path'] or '-'}  {it['width']}x{it['height']}  "
                  f"{it['size_bytes']} bytes  quality {it['quality']}  {it['seconds']} s"
                  + (f"  NOTE: {it['note']}" if it.get("note") else ""))
        envs = (rd.get("preflight") or {}).get("environments")
        if envs:
            print(f"  environment library: {', '.join(envs)}")
        return 0 if rd["status"] == "done" and all(i["method"] == "render" for i in rd["items"]) else 1
    elif args.cmd == "rebuild-assembly":
        poses = {}
        for item in args.pose:
            pid, _, xyz = item.partition("=")
            vals = [float(v) for v in xyz.split(",")]
            if len(vals) != 3:
                raise ValueError(f"--pose {item}: expected ID=x,y,z (mm)")
            poses[pid.strip()] = vals
        run = create_assembly_rebuild(store, args.run_id, poses, args.reason,
                                      entered_via="cli: python -m agent rebuild-assembly")
        _print_design(orch.advance(run, on_step=lambda r: print(f"  .. {r['phase']} {r['events'][-1]['msg']}")))
    elif args.cmd == "rebuild-mirror":
        from agent.revise import find_run_for_part
        run = load_design_run(store, args.run or find_run_for_part(store, args.part_id))
        _print_design(orch.rebuild(run, args.part_id, latest_source=True))
    elif args.cmd == "parts":
        parts = store.list_parts()
        stale = staleness(parts)
        for p in parts:
            ok = all(c.status.value == "VERIFIED" for c in p.checks)
            s = stale.get(p.id)
            tag = (f"  {p.derived.get('note')}" + (f"  STALE (source is v{s['latest_source_version']}; "
                                                    f"python -m agent rebuild-mirror {p.id})" if s["stale"] else "")
                   if s else "")
            print(f"{p.id} v{p.version}  {p.name:20s} {'checks ok' if ok else 'checks FAILED'}  bbox {p.bbox_world}{tag}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agent", description="AI Engineering Agent")
    ap.add_argument("--project", default=None)
    ap.add_argument("--reasoner", choices=["file_exchange", "claude_code"], default="file_exchange")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new"); p.add_argument("request")
    p.add_argument("--image", action="append", default=[], help="attach an image (PNG/JPEG/GIF/WebP); repeatable")
    p = sub.add_parser("step"); p.add_argument("run_id")
    p = sub.add_parser("answer"); p.add_argument("run_id"); p.add_argument("answers", nargs="+")
    p = sub.add_parser("status"); p.add_argument("run_id", nargs="?")
    sub.add_parser("components")
    p = sub.add_parser("rules"); p.add_argument("--type")
    p = sub.add_parser("rules-verify"); p.add_argument("rule_id"); p.add_argument("--by", required=True)
    sub.add_parser("fusion-check")
    p = sub.add_parser("design"); p.add_argument("brief")
    p.add_argument("--image", action="append", default=[], help="reference image stored with the run (not sent to Claude)")
    p.add_argument("--visual-review", action="store_true", help="one extra Claude call with the iso screenshot (advisory); off by default")
    p = sub.add_parser("design-step"); p.add_argument("run_id")
    p = sub.add_parser("design-answer"); p.add_argument("run_id"); p.add_argument("answer")
    p = sub.add_parser("design-status"); p.add_argument("run_id", nargs="?")
    p = sub.add_parser("rebuild"); p.add_argument("part_id"); p.add_argument("--run")
    p.add_argument("--version", type=int, default=None, help="revert to this version (registered as a new version)")
    p = sub.add_parser("revise"); p.add_argument("run_id"); p.add_argument("target", help="PART-ID or 'assembly'")
    p.add_argument("instruction")
    p = sub.add_parser("rebuild-assembly"); p.add_argument("run_id")
    p.add_argument("--pose", action="append", default=[], help="position correction ID=x,y,z in mm (repeatable)")
    p.add_argument("--reason", default="", help="why the pose is corrected (required with --pose)")
    p = sub.add_parser("rebuild-mirror"); p.add_argument("part_id"); p.add_argument("--run")
    p = sub.add_parser("recolor"); p.add_argument("run_id")
    p = sub.add_parser("render"); p.add_argument("run_id"); p.add_argument("--views", default="iso")
    p.add_argument("--preset", default=None, choices=["draft", "standard", "final"])
    p.add_argument("--environment", default=None); p.add_argument("--camera", choices=["perspective", "orthographic"])
    p.add_argument("--focal", type=float); p.add_argument("--background"); p.add_argument("--brightness", type=float)
    p.add_argument("--light-angle", type=float); p.add_argument("--roughness", type=float)
    p.add_argument("--no-ground-reflections", action="store_true")
    p.add_argument("--size", help="custom render size WxH, each side 108..4000 px (API limit)")
    p.add_argument("--crop-output", help="crop target size WxH (default: the preset's resolution)")
    p.add_argument("--no-crop", action="store_true")
    sub.add_parser("parts")
    args = ap.parse_args(argv)
    if args.cmd in FAST_COMMANDS:
        try:
            return _fast(args)
        except (KeyError, ValueError) as e:
            print(f"rejected: {e}", file=sys.stderr)
            return 2
    store = ProjectStore(args.project or "prototype_bench")
    if args.reasoner == "claude_code":
        factory = lambda run: FallbackBackend(ClaudeCodeBackend(run.dir), FileExchangeBackend(run.dir))  # noqa: E731
    else:
        factory = None                                   # engine default: file exchange (unchanged)

    if args.cmd == "new":
        images = []
        for path in args.image:
            with open(path, "rb") as f:
                images.append((f.read(), os.path.basename(path)))
        try:
            run = create_run(store, args.request, images=images, entered_via="cli: python -m agent new --image")
        except ValueError as e:
            print(f"request rejected: {e}", file=sys.stderr)
            return 2
        _print_state(Engine(store, backend_factory=factory).advance(run))
    elif args.cmd == "step":
        _print_state(Engine(store, backend_factory=factory).advance(load_run(store, args.run_id)))
    elif args.cmd == "answer":
        run = load_run(store, args.run_id)
        for a in args.answers:
            key, _, text = a.partition("=")
            try:
                record_answer(run, key, text, entered_via="cli: python -m agent answer")
            except (ValueError, StopIteration) as e:
                print(f"answer rejected: {e}", file=sys.stderr)
                return 2
        run.save()
        _print_state(Engine(store, backend_factory=factory).advance(run))
    elif args.cmd == "status":
        if args.run_id:
            _print_state(load_run(store, args.run_id))
        else:
            for d in sorted(store.runs_dir.glob("*/run.json")) if store.runs_dir.exists() else []:
                _print_state(load_run(store, d.parent.name))
    elif args.cmd == "components":
        for c in store.list_components():
            print(f"{c.id} rev {c.revision}  {c.lifecycle:8s}  {c.type:10s}  {c.name}  "
                  f"mass {c.derived.get('mass_kg')} kg  fusion: {c.fusion_ref.component_name if c.fusion_ref else '-'}")
    elif args.cmd == "rules":
        rs = RuleSet.load()
        for r in rs.rules.values():
            if args.type and args.type not in r.applies_to and "any_component" not in r.applies_to:
                continue
            print(f"{r.id:28s} {r.authority:12s} {r.verification_status:12s} {r.title}  [{r.source.document} {r.source.article or ''}]")
    elif args.cmd == "rules-verify":
        r = RuleSet.load().mark_verified(args.rule_id, args.by)
        print(f"{r.id} marked VERIFIED by {r.verified_by} on {r.verified_on}")
    elif args.cmd == "fusion-check":
        try:
            print(json.dumps(FusionMCPClient().ping(), indent=2))
        except FusionError as e:
            print(f"Fusion not available: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
