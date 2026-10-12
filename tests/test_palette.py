"""Mini F1 palette (vehicle/palette.py) and Apply palette (fusion/paint.py, Orchestrator.recolor): file parsing and
validation, colour never touching part versions or hashes, recolour in place with read-back, derived parts following
their source's colour, CLI and the HTTP route - with the fake Fusion."""
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent import __main__ as cli
from agent.design_run import load_design_run
from fusion.paint import compare, recolor_script
from fusion.part_runner import build_config, build_part, to_record
from tests.helpers import MINI_BOX_BODY, decode_part_cfg
from tests.test_fast_parts import BOX, fake_for, spec
from tests.test_mirror import run18
from vehicle.palette import FINISHES, Paint, load_palette, paint_for, palette_path, parse_palette
from vehicle.store import ProjectStore

REPO_PALETTE = Path(__file__).resolve().parents[1] / "data" / "mini_f1" / "palette.json"


def write_palette(root: Path, parts: dict) -> None:
    Path(root).mkdir(parents=True, exist_ok=True)
    palette_path(root).write_text(json.dumps({"palette_version": 1, "parts": {
        k: {"color": c, "finish": f} for k, (c, f) in parts.items()}}), encoding="utf-8")


# ---------------------------------------------------------------- file parsing + validation
def test_repo_palette_is_valid_and_covers_the_mini_f1():
    p = load_palette(REPO_PALETTE.parent)
    assert len(p.parts) == 18 and {e.finish for e in p.parts.values()} == set(FINISHES)
    assert p.parts["MON-001"].color == "#B01E28" and p.parts["WHL-RR"].finish == "matte_rubber"
    assert p.parts["FLR-001"].finish == "satin" and p.parts["SUR-R"].color == "#4A4E55"
    assert [(z.rule, z.color) for z in p.parts["MON-001"].zones] == [("cockpit", "#CBD0D8")]
    assert all([(z.rule, z.color) for z in p.parts[w].zones] == [("wheel_rim", "#C8CCD2")]
               for w in ("WHL-FL", "WHL-FR", "WHL-RL", "WHL-RR"))


@pytest.mark.parametrize("entry,needle", [
    ({"color": "#12345", "finish": "satin"}, "hex"),
    ({"color": "red", "finish": "satin"}, "hex"),
    ({"color": "#GG0000", "finish": "satin"}, "hex"),
    ({"color": "#112233", "finish": "chrome"}, "finish"),
    ({"color": "#112233", "finish": "satin", "gloss": 1}, "gloss"),
])
def test_bad_entries_are_rejected(entry, needle):
    with pytest.raises(ValueError, match="invalid palette") as e:
        parse_palette({"parts": {"MON-001": entry}})
    assert needle in str(e.value)


def test_bad_part_id_and_bad_files(tmp_path):
    with pytest.raises(ValueError, match="not part ids"):
        parse_palette({"parts": {"monocoque": {"color": "#112233"}}})
    assert load_palette(tmp_path) is None                            # no file: built-in defaults
    palette_path(tmp_path).write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not JSON"):
        load_palette(tmp_path)


def test_paint_resolution_own_then_source_then_default():
    p = parse_palette({"parts": {"SUF-L": {"color": "#4a4e55", "finish": "satin"}}})
    assert paint_for("SUF-L", None, p) == Paint(hex="#4A4E55", finish="satin", source="palette")
    assert paint_for("SUF-R", "SUF-L", p) == Paint(hex="#4A4E55", finish="satin", source="palette (source SUF-L)")
    d = paint_for("WHL-FL", None, p)
    assert d.source == "default" and d.finish == "matte_rubber" and d.rgb == [25, 25, 25]
    assert paint_for("XYZ-001").hex == "#B4B4B9"


# ---------------------------------------------------------------- colour never touches versions or hashes
def test_colour_is_not_part_of_the_spec_script_or_version(tmp_path):
    store = ProjectStore("p", root=tmp_path)
    s = spec()
    red, blue = Paint(hex="#B01E28", finish="glossy_paint", source="palette"), \
        Paint(hex="#7FA3DB", finish="satin", source="palette")
    a = build_part(fake_for(s), s, BOX, "x", "t", paint=red)
    b = build_part(fake_for(s), s, BOX, "x", "t", paint=blue)
    assert decode_part_cfg(compose(s, red))["paint"]["hex"] == "#B01E28"
    assert decode_part_cfg(compose(s, blue))["paint"] == {"color": [127, 163, 219], "hex": "#7FA3DB",
                                                          "finish": "satin", "zones": []}
    ra, rb = to_record(a, "x", "r1", []), to_record(b, "x", "r2", [])
    assert ra.script_sha256 == rb.script_sha256 and ra.spec == rb.spec
    assert store.save_part(ra, "r1", "built").version == 1
    assert store.save_part(rb, "r2", "recoloured rebuild").version == 1          # same version, no history entry
    assert len(store.get_part("TST-001").history) == 1


def compose(s, paint):
    from fusion.prelude import compose_part_script
    return compose_part_script(BOX, build_config(s, "x", "t", True, paint))


def test_builds_use_the_palette_and_a_palette_change_creates_no_version(tmp_path):
    write_palette(tmp_path / "mini_f1", {"MON-001": ("#B01E28", "glossy_paint"), "SUF-L": ("#4A4E55", "satin")})
    store, fake, reasoner, orch, run = run18(tmp_path)
    assert run["status"] == "DONE", run["error"]
    assert fake.built["MON-001"]["paint"]["hex"] == "#B01E28"
    assert fake.built["SUF-L"]["paint"] == {"color": [74, 78, 85], "hex": "#4A4E55", "finish": "satin", "zones": []}
    assert fake.built["SUF-R"]["paint"]["hex"] == "#4A4E55"                       # derived: the source's colour
    assert fake.built["WHL-FL"]["paint"]["finish"] == "matte_rubber"              # not listed: default
    before = {p.id: (p.version, p.script_sha256) for p in store.list_parts()}
    write_palette(store.root, {"MON-001": ("#00FF00", "satin")})
    run = orch.rebuild(load_design_run(store, run.id), "MON-001")
    assert fake.built["MON-001"]["paint"]["hex"] == "#00FF00"
    assert {p.id: (p.version, p.script_sha256) for p in store.list_parts()} == before


def test_an_invalid_palette_never_stops_a_build(tmp_path):
    (tmp_path / "mini_f1").mkdir(parents=True)
    palette_path(tmp_path / "mini_f1").write_text('{"parts": {"MON-001": {"color": "bad"}}}', encoding="utf-8")
    store, fake, reasoner, orch, run = run18(tmp_path)
    assert run["status"] == "DONE" and fake.built["MON-001"]["paint"]["hex"] == "#DC1E28"
    assert sum("Palette ignored" in e["msg"] for e in run["events"]) == 1


# ---------------------------------------------------------------- apply palette (recolour in place)
def test_recolor_recolours_every_part_in_one_call_and_reshoots(tmp_path):
    store, fake, reasoner, orch, run = run18(tmp_path)
    write_palette(store.root, {"MON-001": ("#B01E28", "glossy_paint"), "SUR-L": ("#4A4E55", "satin"),
                               "WHL-FL": ("#101113", "matte_rubber")})
    files = {p.name: p.read_bytes() for p in store.components_dir.glob("*.json")}
    n0, claude0 = len(fake.scripts), reasoner.calls
    rc = orch.recolor(load_design_run(store, run.id))
    assert rc["error"] is None and rc["mismatches"] == [] and rc["script_calls"] == 4 == len(fake.scripts) - n0
    assert len(fake.recolors) == 1 and set(fake.recolors[0]["parts"]) == set(run["parts"])
    assert rc["parts"]["SUR-R"]["expected"] == {"hex": "#4A4E55", "finish": "satin", "source": "palette (source SUR-L)",
                                                "zones": []}
    assert rc["parts"]["WHL-FR"]["got"]["hex"] == ["#101113"] and rc["parts"]["WHL-FR"]["ok"]
    assert rc["parts"]["FWG-001"]["expected"]["source"] == "default"
    run = load_design_run(store, run.id)
    assert run["recolors"][-1]["id"] == "C01" and set(rc["screenshots"]) == {"iso", "front", "top"}
    assert (run.dir / "recolors" / "C01" / "iso.png").exists() and fake.screens[-3:] == ["current"] * 3
    assert {p.name: p.read_bytes() for p in store.components_dir.glob("*.json")} == files      # registry untouched
    assert reasoner.calls == claude0 and "C01: apply palette - 18/18 parts" in run["events"][-1]["msg"]


def test_recolor_reports_mismatches_and_finish_fallbacks(tmp_path):
    store, fake, reasoner, orch, run = run18(tmp_path)
    write_palette(store.root, {"MON-001": ("#B01E28", "glossy_paint"), "FLR-001": ("#23262B", "satin")})
    fake.recolor_override["MON-001"] = "#000000"
    fake.missing_finishes.add("satin")
    rc = orch.recolor(load_design_run(store, run.id))
    assert rc["mismatches"] == ["MON-001: colour read back #000000 (expected #B01E28)"]
    assert rc["parts"]["FLR-001"]["ok"] and "FLR-001: finish satin unavailable: plain colour" in rc["notes"]


def test_recolor_refuses_a_deep_wrapper_and_an_invalid_palette(tmp_path):
    store, fake, reasoner, orch, run = run18(tmp_path)
    fake.depth = 500
    n0 = len(fake.scripts)
    rc = orch.recolor(load_design_run(store, run.id))
    assert "restart Fusion" in rc["error"] or "depth" in rc["error"]
    assert rc["script_calls"] == 1 == len(fake.scripts) - n0 and not rc["screenshots"] and not fake.recolors
    palette_path(store.root).write_text('{"parts": {"MON-001": {"color": "#12"}}}', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid palette"):
        orch.recolor(load_design_run(store, run.id))
    assert len(fake.scripts) == n0 + 1


def test_recolor_script_compiles_and_carries_keys(tmp_path):
    s = recolor_script("mf1:x", "mf1", {"SUF-R": Paint(hex="#4A4E55", finish="satin", source="palette")}, 100)
    compile(s, "recolor", "exec")
    cfg = decode_part_cfg(s)
    assert cfg["recolor"] and cfg["max_depth"] == 100 and cfg["parts"]["SUF-R"]["key"] == "mf1 SUF-R "
    rows = compare({"SUF-R": Paint(hex="#4A4E55", finish="satin", source="palette")},
                   {"parts": {"SUF-R": {"present": False}}})
    assert rows["SUF-R"]["problem"] == "part not in the Fusion design"


def test_cli_recolor_prints_the_read_back_and_signals_mismatches(tmp_path, monkeypatch, capsys):
    store, fake, reasoner, orch, run = run18(tmp_path)
    write_palette(store.root, {"MON-001": ("#B01E28", "glossy_paint")})
    monkeypatch.setattr("vehicle.store.DATA_ROOT", tmp_path)
    monkeypatch.setattr("agent.design_run.Orchestrator.fusion", lambda self: fake)
    assert cli.main(["recolor", run.id]) == 0
    out = capsys.readouterr().out
    assert "apply palette C01: done  script_calls=4" in out and "MON-001  #B01E28 glossy_paint" in out
    fake.recolor_override["MON-001"] = "#000000"
    assert cli.main(["recolor", run.id]) == 1
    assert "MISMATCH: colour read back #000000" in capsys.readouterr().out


# ---------------------------------------------------------------- face zones
WHEEL_DIMS = {"rim_diameter": 460.0, "width": 300.0, "rim_recess_depth": 30.0}


@pytest.mark.parametrize("zones,needle", [
    ([{"rule": "hubcap", "color": "#C8CCD2"}], "rule"),
    ([{"rule": "wheel_rim", "color": "#C8CC"}], "hex"),
    ([{"rule": "wheel_rim", "color": "#C8CCD2"}, {"rule": "wheel_rim", "color": "#000000"}], "once per part"),
])
def test_bad_zones_are_rejected(zones, needle):
    with pytest.raises(ValueError, match="invalid palette") as e:
        parse_palette({"parts": {"WHL-FL": {"color": "#101113", "zones": zones}}})
    assert needle in str(e.value)


def test_zone_parameters_come_from_the_part_dims():
    p = parse_palette({"parts": {"WHL-FL": {"color": "#101113", "finish": "matte_rubber",
                                            "zones": [{"rule": "wheel_rim", "color": "#c8ccd2", "finish": "satin"}]},
                                 "MON-001": {"color": "#B01E28", "zones": [{"rule": "cockpit", "color": "#CBD0D8"}]}}})
    z = paint_for("WHL-FR", "WHL-FL", p).cfg(WHEEL_DIMS)["zones"]                 # derived wheel: source's zones
    assert z == [{"rule": "wheel_rim", "color": [200, 204, 210], "hex": "#C8CCD2", "finish": "satin",
                  "rim_radius": 230.0, "rim_face_y": 120.0}]
    assert paint_for("WHL-FL", None, p).cfg({"width": 300.0})["zones"][0]["skip"].startswith("wheel_rim needs")
    assert paint_for("MON-001", None, p).cfg({})["zones"] == [{"rule": "cockpit", "color": [203, 208, 216],
                                                              "hex": "#CBD0D8", "finish": "glossy_paint"}]


def zone_palette(root):
    palette_path(root).parent.mkdir(parents=True, exist_ok=True)
    palette_path(root).write_text(json.dumps({"parts": {
        "MON-001": {"color": "#B01E28", "zones": [{"rule": "cockpit", "color": "#CBD0D8"}]},
        "WHL-FL": {"color": "#101113", "finish": "matte_rubber",
                   "zones": [{"rule": "wheel_rim", "color": "#C8CCD2", "finish": "satin"}]}}}), encoding="utf-8")


def test_recolor_paints_zones_and_checks_them(tmp_path):
    store, fake, reasoner, orch, run = run18(tmp_path)
    zone_palette(store.root)
    rc = orch.recolor(load_design_run(store, run.id))
    mon, fl, fr = rc["parts"]["MON-001"], rc["parts"]["WHL-FL"], rc["parts"]["WHL-FR"]
    assert mon["ok"] and mon["got"]["zones"] == [{"rule": "cockpit", "faces": 3, "hex": ["#CBD0D8"], "plain": False,
                                                  "finish_expected": "glossy_paint", "error": None}]
    cfg = fake.recolors[-1]["parts"]
    assert cfg["WHL-FR"]["zones"][0]["rule"] == "wheel_rim"                         # derived wheel follows WHL-FL
    # the test plan's wheels have no rim dims: the rule is skipped and that is reported, never silently ignored
    assert not fl["ok"] and "zone wheel_rim: skipped: wheel_rim needs the dims rim_diameter" in fl["problem"]
    assert not fr["ok"] and len(rc["mismatches"]) == 2                              # WHL-FL + derived WHL-FR
    fake.stray_overrides["MON-001"] = 2
    fake.missing_finishes.add("glossy_paint")
    rc = orch.recolor(load_design_run(store, run.id))
    assert rc["parts"]["MON-001"]["problem"] == "2 face(s) outside the zones keep an old colour"
    fake.stray_overrides.clear()
    rc = orch.recolor(load_design_run(store, run.id))
    mon = rc["parts"]["MON-001"]
    assert mon["ok"] and "zone cockpit: finish glossy_paint unavailable" in mon["note"]


def test_build_config_carries_zone_parameters_from_the_spec():
    p = parse_palette({"parts": {"TST-001": {"color": "#101113",
                                             "zones": [{"rule": "wheel_rim", "color": "#C8CCD2"}]}}})
    s = spec(dims=dict(WHEEL_DIMS, length=100.0, height=30.0))
    z = decode_part_cfg(compose(s, paint_for("TST-001", None, p)))["paint"]["zones"]
    assert z[0]["rim_radius"] == 230.0 and z[0]["rim_face_y"] == 120.0


# ---------------------------------------------------------------- HTTP route
def test_http_recolor_route(tmp_path):
    from agent.design_service import DesignService
    from agent.fast_reasoning import ScriptedReasoner
    from agent.service import AgentService
    from tests.helpers import FakeFusion, FakePartFusion, ScriptedBackend
    from tests.test_kit_scaling import BRIEF18
    from tests.test_mirror import derived_plan, gate
    from ui.server import make_server
    plan = derived_plan()
    specs = {s.id: s for s in gate(plan)[0]}
    fake = FakePartFusion(envelopes={k: (list(s.envelope_min), list(s.envelope_max)) for k, s in specs.items()})
    rs = ScriptedReasoner({"plan": [plan], "part": [{"body": MINI_BOX_BODY}] * 12})
    svc = DesignService(project="mini_f1", root=tmp_path, fusion=fake, reasoner_factory=lambda r: rs, background=False)
    run_id = svc.start(BRIEF18)
    write_palette(svc.store.root, {"MON-001": ("#B01E28", "glossy_paint")})
    strict = AgentService(project="bench", root=tmp_path, fusion=FakeFusion(),
                          backend_factory=lambda r: ScriptedBackend({}), background=False)
    srv = make_server(strict, port=0, design=svc)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert post(f"{base}/api/design/{run_id}/recolor") == (202, {"ok": True})
        view = json.loads(urllib.request.urlopen(f"{base}/api/design/{run_id}", timeout=10).read())
        assert view["recolors"][-1]["id"] == "C01" and view["recolors"][-1]["mismatches"] == []
        assert view["recolors"][-1]["parts"] == 18 and fake.built["MON-001"]["paint"]["hex"] == "#B01E28"
        palette_path(svc.store.root).write_text('{"parts": {"MON-001": {"color": "x"}}}', encoding="utf-8")
        code, body = post(f"{base}/api/design/{run_id}/recolor")
        assert code == 400 and "invalid palette" in body["error"]
        page = urllib.request.urlopen(f"{base}/", timeout=10).read().decode()
        assert 'id="btn-recolor"' in page and "Apply palette" in page
    finally:
        srv.shutdown()
        srv.server_close()


def post(url):
    req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
