"""Left/right derived parts: pure pose/spec mirroring, gate rules, derived mates, PART-DERIVED, staleness, and a full
fake 18-part run in which every right-hand part is derived with zero Claude calls."""
import itertools

import numpy as np
import pytest

from agent.design_run import Orchestrator, create_design_run, load_design_run
from agent.design_service import build_design_view
from agent.fast_prompts import PlanResponse, gate_plan, kit_for_brief
from agent.fast_reasoning import ScriptedReasoner
from agent.revise import Reviser
from fusion.part_runner import build_config
from fusion.prelude import compose_part_script
from tests.helpers import MINI_BOX_BODY, FakePartFusion, decode_part_cfg
from tests.test_kit_scaling import BRIEF18, plan18, snippets
from validation.part_checks import derived_check
from vehicle.mirror import S, derive_mates, derive_spec, derived_rotation, mirror_box, staleness
from vehicle.models import Status
from vehicle.parts import PartSpec
from vehicle.store import ProjectStore, read_json, write_json
from vehicle.transforms import pose_to_matrix, rotation_matrix, rotation_to_euler, transform_point

SX = np.diag([-1.0, 1.0, 1.0])


def spec(pid="SUF-L", pos=(-120.0, 480.0, 210.0), rot=(12.0, -25.0, 37.0), lo=(-300.0, 380.0, 100.0),
         hi=(100.0, 760.0, 400.0)) -> PartSpec:
    return PartSpec(id=pid, name=pid, role="test", dims={"length": 10.0}, position_mm=pos, rotation_deg=rot,
                    envelope_min=lo, envelope_max=hi)


def m4(s: PartSpec) -> np.ndarray:
    return pose_to_matrix(s.pose)


# ---------------------------------------------------------------- pure pose / spec mirroring
@pytest.mark.parametrize("rot", [(0, 0, 0), (12, -25, 37), (-170, 80, 5), (0, 90, 30), (0, -90, -120)])
def test_rotation_to_euler_round_trips(rot):
    r = rotation_matrix(*rot)
    assert np.allclose(rotation_matrix(*rotation_to_euler(r)), r, atol=1e-9)


def test_mirror_pose_is_s_p_s_for_a_rotated_pose():
    src = spec()
    d = derive_spec(src, "SUF-R", "mirror")
    assert d.rotation_deg == (-12.0, -25.0, -37.0) and d.position_mm == (-120.0, -480.0, 210.0)
    s4 = np.diag([1.0, -1.0, 1.0, 1.0])
    assert np.allclose(m4(d), s4 @ m4(src) @ s4, atol=1e-9)
    for q in itertools.product((-7.0, 31.0), (-4.0, 19.0), (2.0, 55.0)):      # world(derived, S·q) = S·world(src, q)
        sq = (q[0], -q[1], q[2])
        assert np.allclose(transform_point(m4(d), sq), S @ np.array(transform_point(m4(src), q)), atol=1e-9)
    assert (d.envelope_min, d.envelope_max) == ((-300.0, -760.0, 100.0), (100.0, -380.0, 400.0))
    lo, hi = src.local_envelope()
    assert np.allclose(d.local_envelope(), mirror_box(lo, hi), atol=1e-6)
    assert (d.mirror_of, d.mirror_mode, d.dims, d.reuse) == ("SUF-L", "mirror", src.dims, False)


@pytest.mark.parametrize("rot,expect", [((0, 0, 0), (0.0, 0.0, 180.0)), ((0, 0, 3), (0.0, 0.0, 177.0)),
                                        ((0, 0, -90), (0.0, 0.0, -90.0))])
def test_yaw180_pose_for_level_wheels(rot, expect):
    d = derive_spec(spec("WHL-FL", pos=(0.0, 925.0, 330.0), rot=rot), "WHL-FR", "yaw180")
    assert d.rotation_deg == expect and d.position_mm == (0.0, -925.0, 330.0)


def test_yaw180_is_the_rigid_pose_s_p_sx_also_when_rotated():
    """A wheel symmetric under x -> -x: derived(Sx·q) lands on S·source(q), i.e. P' = S·P·Sx (rigid)."""
    src = spec("WHL-FL", pos=(5.0, 925.0, 330.0), rot=(4.0, -2.0, 3.0))
    d = derive_spec(src, "WHL-FR", "yaw180")
    assert np.allclose(rotation_matrix(*d.rotation_deg), S @ rotation_matrix(*src.rotation_deg) @ SX, atol=1e-9)
    assert np.isclose(np.linalg.det(rotation_matrix(*d.rotation_deg)), 1.0)
    assert np.allclose(derived_rotation((0, 0, 0), "yaw180"), (0, 0, 180))


def test_derive_refuses_chains_and_self():
    d = derive_spec(spec(), "SUF-R", "mirror")
    with pytest.raises(ValueError):
        derive_spec(d, "SUF-X", "mirror")
    with pytest.raises(ValueError):
        derive_spec(spec(), "SUF-L", "mirror")


def test_derived_mates_map_ids_and_replace_planned_ones():
    mates = [{"a": "SUF-L", "b": "MON-001", "expect": "overlap", "value_mm": 5},
             {"a": "SUF-L", "b": "WHL-FL", "expect": "touching", "value_mm": 0},
             {"a": "SUF-R", "b": "MON-001", "expect": "touching", "value_mm": 0},          # replaced
             {"a": "MIR-L", "b": "MIR-R", "expect": "clear", "value_mm": 100}]            # own pair: kept
    out, notes = derive_mates(mates, {"SUF-R": "SUF-L", "WHL-FR": "WHL-FL", "MIR-R": "MIR-L"})
    pairs = {(m["a"], m["b"]): m for m in out}
    assert pairs[("SUF-R", "MON-001")]["expect"] == "overlap" and pairs[("SUF-R", "MON-001")]["value_mm"] == 5
    assert ("SUF-R", "WHL-FR") in pairs and ("MIR-L", "MIR-R") in pairs and len(out) == 5
    assert len(notes) == 1 and "SUF-R/MON-001 replaced" in notes[0]


# ---------------------------------------------------------------- plan gate
def derived_plan() -> dict:
    """plan18 with wheels centred on their axles and every right-hand part derived (id, name, role only)."""
    p = plan18()
    for part in p["parts"]:
        if part["id"] in ("WHL-FL", "WHL-RL"):
            lo, hi = part["envelope_min"], part["envelope_max"]
            part["position_mm"] = [(a + b) / 2 for a, b in zip(lo, hi)]
    mode = {"WHL": "yaw180"}
    for i, part in enumerate(p["parts"]):
        pid = part["id"]
        if pid.endswith("R") and pid[:3] in ("WHL", "SUF", "SUR", "SDP", "MIR"):
            p["parts"][i] = {"id": pid, "name": pid, "role": pid.lower(), "mirror_of": pid[:-1] + "L",
                             "mirror_mode": mode.get(pid[:3], "mirror")}
    derived = {q["id"] for q in p["parts"] if q.get("mirror_of")}
    p["mates"] = [m for m in p["mates"] if m["a"] not in derived and m["b"] not in derived]
    return p


def gate(plan):
    kit = kit_for_brief(BRIEF18)
    return gate_plan(PlanResponse.model_validate(plan), kit, set(), snippets(kit))


def test_gate_derives_right_parts_and_their_mates():
    specs, mates, problems, notes = gate(derived_plan())
    assert problems == [], problems
    by = {s.id: s for s in specs}
    assert len(specs) == 18 and {s.id for s in specs if s.mirror_of} == {"WHL-FR", "WHL-RR", "SUF-R", "SUR-R",
                                                                           "SDP-R", "MIR-R"}
    assert by["SDP-R"].envelope_min[1] == -by["SDP-L"].envelope_max[1] and by["WHL-FR"].rotation_deg[2] == 180.0
    assert len(mates) == 20                                         # 13 planned + 7 derived from the left side
    assert {"a": "MIR-R", "b": "HAL-001", "expect": "clear", "value_mm": 20} in mates


@pytest.mark.parametrize("patch,needle", [
    ({"mirror_of": "SUF-X"}, "not a planned part"),
    ({"mirror_of": "SUF-R"}, "points to itself"),
    ({"mirror_of": "MIR-L"}, "different kind of part"),
    ({"mirror_mode": None}, "needs mirror_mode"),
    ({"mirror_mode": "yaw180"}, "wheels only"),
])
def test_gate_rejects_bad_mirror_of(patch, needle):
    plan = derived_plan()
    part = next(p for p in plan["parts"] if p["id"] == "SUF-R")
    part.update(patch)
    problems = gate(plan)[2]
    assert any(needle in p for p in problems), problems


def test_gate_rejects_a_mirror_of_a_derived_part_and_a_bare_mirror_mode():
    plan = derived_plan()
    src = next(p for p in plan["parts"] if p["id"] == "SUF-L")
    src.update(mirror_of="SUF-R", mirror_mode="mirror")
    assert any("itself derived" in p for p in gate(plan)[2])
    plan = derived_plan()
    next(p for p in plan["parts"] if p["id"] == "MON-001")["mirror_mode"] = "mirror"
    assert any("mirror_mode without mirror_of" in p for p in gate(plan)[2])


# ---------------------------------------------------------------- PART-DERIVED
SRC = {"volume_mm3": 123456.789, "solids": 1, "lumps": 1, "bbox_local": [[0, 0, 0], [100, 60, 35]],
       "bbox_world": [[10, 300, 50], [110, 360, 85]]}


def data(vol=123456.789, local=([0, -60, 0], [100, 0, 35]), world=([10, -360, 50], [110, -300, 85]), lumps=1):
    return {"bbox_local": [list(local[0]), list(local[1])],
            "measure": {"bodies": [{"name": "B", "solid": True, "volume_mm3": vol, "lumps": lumps}],
                        "bbox_world": [list(world[0]), list(world[1])]}}


@pytest.mark.parametrize("kw,ok,needle", [
    ({}, True, ""),
    ({"vol": 123456.789 * (1 + 2e-6)}, False, "volume"),
    ({"local": ([0, 0, 0], [100, 60, 35])}, False, "local bbox"),          # lug on the wrong side
    ({"world": ([10, 300, 50], [110, 360, 85])}, False, "world bbox"),
    ({"lumps": 2}, False, "lump"),
])
def test_derived_check_mirror(kw, ok, needle):
    r = derived_check("mirror", "TST-L", SRC, data(**kw))
    assert (r.status == Status.VERIFIED) is ok and needle in r.message


def test_derived_check_yaw180_wants_an_equal_local_bbox_and_a_known_source():
    assert derived_check("yaw180", "WHL-FL", SRC, data(local=([0, 0, 0], [100, 60, 35]))).status == Status.VERIFIED
    assert derived_check("yaw180", "WHL-FL", SRC, data()).status == Status.NON_COMPLIANT
    r = derived_check("mirror", "TST-L", {}, data())
    assert r.status == Status.NOT_VERIFIED and r.blocking_failure


def test_mirror_flag_reaches_the_prelude_only_for_mirror_mode():
    d = derive_spec(spec(), "SUF-R", "mirror")
    script = compose_part_script(MINI_BOX_BODY, build_config(d, "mf1", "t", True))
    compile(script, "derived", "exec")
    assert decode_part_cfg(script)["mirror"] is True and "_mirror_y(occ.component)" in script
    w = derive_spec(spec("WHL-FL", pos=(0.0, 925.0, 330.0), rot=(0, 0, 0)), "WHL-FR", "yaw180")
    assert decode_part_cfg(compose_part_script(MINI_BOX_BODY, build_config(w, "mf1", "t", True)))["mirror"] is False


# ---------------------------------------------------------------- full fake run, staleness, rebuild-mirror
def run18(tmp_path, **fake_kw):
    plan = derived_plan()
    store = ProjectStore("mini_f1", root=tmp_path)
    specs = {s.id: s for s in gate(plan)[0]}
    fake = FakePartFusion(envelopes={k: (list(s.envelope_min), list(s.envelope_max)) for k, s in specs.items()},
                          geometric_mates=True, **fake_kw)
    reasoner = ScriptedReasoner({"plan": [plan], "part": [{"body": MINI_BOX_BODY}] * 12})
    orch = Orchestrator(store, fusion=fake, reasoner_factory=lambda run: reasoner)
    return store, fake, reasoner, orch, orch.advance(create_design_run(store, BRIEF18))


def test_18_part_run_derives_right_parts_with_zero_claude_calls(tmp_path):
    store, fake, reasoner, orch, run = run18(tmp_path)
    d = run.data
    assert d["status"] == "DONE", (d["error"], d["events"][-4:])
    assert d["counters"]["claude_calls"] == reasoner.calls == 13                   # plan + 12 source parts
    assert not [c for c in reasoner.log if c["name"].endswith(("-R", "WHL-FR", "WHL-RR"))]
    assert d["counters"]["script_calls"] == 18 + 1 + 3
    for pid, mode in (("SUF-R", "mirror"), ("WHL-FR", "yaw180"), ("MIR-R", "mirror")):
        st = d["parts"][pid]
        assert st["state"] == "done" and st["attempts"] == [st["attempts"][0]] and st["attempts"][0]["kind"] == "derive"
        assert {c["check_id"]: c["status"] for c in st["checks"]}["PART-DERIVED"] == "VERIFIED"
        rec = store.get_part(pid)
        src = store.get_part(pid[:-1] + "L")
        assert rec.script_body == src.script_body and rec.spec.mirror_mode == mode
        assert rec.derived == {"source_id": src.id, "source_version": 1, "mode": mode,
                               "note": f"derived from {src.id} v1 ({mode})"}
        assert rec.history[-1].summary == rec.derived["note"] and rec.geometry["volume_mm3"] == 1000.0
    assert fake.built["SUF-R"]["mirror"] is True and fake.built["WHL-FR"]["mirror"] is False
    mates = [r for r in d["assembly"]["results"] if r["check_id"].startswith("MATE-")]
    assert len(mates) == 20 and all(r["status"] == "VERIFIED" for r in mates), \
        [(r["check_id"], r["message"]) for r in mates if r["status"] != "VERIFIED"]
    assert any(r["check_id"] == "MATE-HAL-001-MIR-R" for r in mates)
    view = build_design_view(d, registry={"SUF-R": {"active": 1, "versions": [], "derived": staleness(
        store.list_parts())["SUF-R"]}})
    row = next(r for r in view["parts"] if r["id"] == "SUF-R")
    assert row["derived"]["stale"] is False and row["derived"]["source_id"] == "SUF-L"


def test_revised_source_marks_derived_stale_and_rebuild_mirror_re_derives(tmp_path):
    store, fake, reasoner, orch, run = run18(tmp_path)
    src = store.get_part("SUF-L")
    revised = src.model_copy(update={"script_body": src.script_body + "    # revised\n",
                                     "script_sha256": "0" * 64})
    store.save_part(revised, "test", "revised source (test)")
    assert store.get_part("SUF-L").version == 2
    st = staleness(store.list_parts())
    assert st["SUF-R"] == {"source_id": "SUF-L", "source_version": 1, "latest_source_version": 2,
                           "mode": "mirror", "stale": True}
    assert not st["SDP-R"]["stale"]
    with pytest.raises(ValueError, match="derived from SUF-L"):
        Reviser(store, fusion=fake).revise(load_design_run(store, run.id), "SUF-R", "make it thicker")
    calls = reasoner.calls
    run = orch.rebuild(load_design_run(store, run.id), "SUF-R", latest_source=True)
    assert run["status"] == "DONE", run["error"]
    rec = store.get_part("SUF-R")
    assert rec.version == 2 and rec.derived["source_version"] == 2 and rec.script_body.endswith("# revised\n")
    assert [h.version for h in rec.history] == [1, 2] and store.get_part_version("SUF-R", 1).derived["source_version"] == 1
    assert not staleness(store.list_parts())["SUF-R"]["stale"] and reasoner.calls == calls
    run = orch.rebuild(load_design_run(store, run.id), "SUF-R")          # plain rebuild: same version, re-verified
    assert store.get_part("SUF-R").version == 2
    assert {c["check_id"]: c["status"] for c in run["parts"]["SUF-R"]["checks"]}["PART-DERIVED"] == "VERIFIED"


# ---------------------------------------------------------------- source revised in the SAME run, then rebuild-mirror
def sdp_v1_v2():
    """SDP-L's local box as first built (= its planned local envelope) and after a coke-bottle style revision
    (outer wall 10 mm in, top 20 mm lower); volumes 1000 -> 900 mm3."""
    lo, hi = {s.id: s for s in gate(derived_plan())[0]}["SDP-L"].local_envelope()
    v1 = ([float(v) for v in lo], [float(v) for v in hi])
    v2 = (v1[0], [v1[1][0], v1[1][1] - 10.0, v1[1][2] - 20.0])
    return v1, v2


def revised_sdp_run(tmp_path):
    """18-part run, then SDP-L revised to v2 in the same run (its Fusion geometry really changes)."""
    from tests.test_revise import resp
    v1, v2 = sdp_v1_v2()
    store, fake, reasoner, orch, run = run18(tmp_path, local_bboxes={"SDP-L": v1, "SDP-R": v1},
                                             volumes={"SDP-L": 1000.0, "SDP-R": 1000.0})
    assert run["status"] == "DONE", run["error"]
    fake.local_bboxes.update({"SDP-L": v2, "SDP-R": v2})           # the derived build mirrors the source's script
    fake.volumes.update({"SDP-L": 900.0, "SDP-R": 900.0})
    rs = ScriptedReasoner({"revise": [resp(MINI_BOX_BODY + "    # coke bottle\n", "coke bottle")]})
    rev = Reviser(store, fusion=fake, reasoner_factory=lambda d: rs).revise(load_design_run(store, run.id), "SDP-L",
                                                                           "Coke-bottle sidepod.")
    assert rev["state"] == "DONE", (rev["error"], rev["events"][-4:])
    assert store.get_part("SDP-L").version == 2 and store.get_part("SDP-L").geometry["volume_mm3"] == 900.0
    return store, fake, reasoner, orch, load_design_run(store, run.id)


def derived_of(run, pid="SDP-R") -> dict:
    return {c["check_id"]: c for c in run["parts"][pid]["checks"]}["PART-DERIVED"]


def test_revision_updates_the_run_geometry_and_rebuild_mirror_passes_in_the_same_run(tmp_path):
    store, fake, reasoner, orch, run = revised_sdp_run(tmp_path)
    assert run["parts"]["SDP-L"]["version"] == 2
    assert run["parts"]["SDP-L"]["geometry"] == store.get_part("SDP-L").geometry       # A: same measurement
    calls = reasoner.calls
    run = orch.rebuild(run, "SDP-R", latest_source=True)
    assert run["status"] == "DONE", run["error"]
    chk = derived_of(run)
    assert chk["status"] == "VERIFIED", chk["message"]
    assert chk["measured"]["volume_rel_dev"] == 0.0 and chk["measured"]["bbox_local_dev_mm"] == 0.0
    assert chk["limit"]["source"]["volume_mm3"] == 900.0
    rec = store.get_part("SDP-R")
    assert rec.version == 2 and rec.derived["source_version"] == 2 and rec.geometry["volume_mm3"] == 900.0
    assert reasoner.calls == calls and not staleness(store.list_parts())["SDP-R"]["stale"]


def test_rebuild_mirror_uses_the_registry_not_a_stale_run_copy(tmp_path):
    store, fake, reasoner, orch, run = revised_sdp_run(tmp_path)
    run["parts"]["SDP-L"]["geometry"] = store.get_part_version("SDP-L", 1).geometry   # v2 state, v1 geometry
    run.save()
    run = orch.rebuild(load_design_run(store, run.id), "SDP-R", latest_source=True)
    chk = derived_of(run)
    assert chk["status"] == "VERIFIED", chk["message"]
    assert chk["limit"]["source"] == {k: store.get_part("SDP-L").geometry[k] for k in chk["limit"]["source"]}
    assert store.get_part("SDP-R").version == 2


@pytest.mark.parametrize("asym,needle", [
    ({"volumes": 900.0 * (1 + 2e-6)}, "volume"),                                   # just above DERIVED_VOLUME_REL
    ({"local_bboxes": "outer wall 1 mm out"}, "local bbox"),
])
def test_rebuild_mirror_still_fails_a_truly_asymmetric_derived_part(tmp_path, asym, needle):
    store, fake, reasoner, orch, run = revised_sdp_run(tmp_path)
    if "volumes" in asym:
        fake.volumes["SDP-R"] = asym["volumes"]
    else:
        lo, hi = fake.local_bboxes["SDP-R"]
        fake.local_bboxes["SDP-R"] = (lo, [hi[0], hi[1] + 1.0, hi[2]])
    run = orch.rebuild(run, "SDP-R", latest_source=True)
    st = run["parts"]["SDP-R"]
    chk = derived_of(run)
    assert st["state"] == "failed" and chk["status"] == "NON_COMPLIANT" and needle in chk["message"]
    assert store.get_part("SDP-R").version == 1                                       # registry untouched
    assert st["geometry"] is None and st["fia"] == []                                  # no stale v1 data left behind


def test_a_part_that_succeeds_after_a_failed_attempt_shows_no_error(tmp_path, capsys):
    from agent.__main__ import _print_design
    store, fake, reasoner, orch, run = revised_sdp_run(tmp_path)
    good = fake.volumes["SDP-R"]
    fake.volumes["SDP-R"] = good * (1 + 2e-6)                                   # derived part: fails first ...
    run = orch.rebuild(run, "SDP-R", latest_source=True)
    fake.fail_next["SUF-L"] = "    x = 1  # FAIL_AT_RUNTIME"                     # built part: fails first ...
    run = orch.rebuild(run, "SUF-L")
    assert run["parts"]["SDP-R"]["error"] and run["parts"]["SUF-L"]["error"]
    fake.volumes["SDP-R"] = good                                                # ... then both succeed
    run = orch.rebuild(run, "SDP-R", latest_source=True)
    run = orch.rebuild(run, "SUF-L")
    run = load_design_run(store, run.id)
    capsys.readouterr()
    _print_design(run)
    out = capsys.readouterr().out
    rows = {r["id"]: r for r in build_design_view(run.data)["parts"]}
    for pid in ("SDP-R", "SUF-L"):
        st = run["parts"][pid]
        assert st["state"] == "done" and [a["passed"] for a in st["attempts"]][-2:] == [False, True]
        assert st["error"] is None and rows[pid]["error"] is None
        line = next(ln for ln in out.splitlines() if ln.strip().startswith(pid + ":"))
        assert "(" not in line, line


def test_derive_refuses_a_source_record_without_geometry(tmp_path):
    store, fake, reasoner, orch, run = run18(tmp_path)
    path = store.component_path("SDP-L")
    write_json(path, {**read_json(path), "geometry": {}})                            # a pre-geometry record
    assert run["parts"]["SDP-L"]["geometry"]                                          # the run copy is there ...
    n = len(fake.scripts)
    run = orch.rebuild(load_design_run(store, run.id), "SDP-R", latest_source=True)
    st = run["parts"]["SDP-R"]
    assert st["state"] == "failed" and "rebuild the source first" in st["error"]        # ... and is not used
    assert st["geometry"] is None and st["fia"] == []
    assert not [sc for sc in fake.scripts[n:] if decode_part_cfg(sc).get("part_id") == "SDP-R"]
    assert store.get_part("SDP-R").version == 1


def test_rebuild_mirror_refuses_a_designed_part(tmp_path):
    store, fake, reasoner, orch, run = run18(tmp_path)
    with pytest.raises(ValueError, match="not a derived"):
        orch.rebuild(load_design_run(store, run.id), "SUF-L", latest_source=True)


# ---------------------------------------------------------------- service + page (STALE badge, Re-derive button)
def _stale_service(tmp_path):
    """A service whose SUF-R is stale (its source SUF-L got a new version after the run)."""
    from agent.design_service import DesignService
    plan = derived_plan()
    specs = {s.id: s for s in gate(plan)[0]}
    fake = FakePartFusion(envelopes={k: (list(s.envelope_min), list(s.envelope_max)) for k, s in specs.items()})
    rs = ScriptedReasoner({"plan": [plan], "part": [{"body": MINI_BOX_BODY}] * 12})
    svc = DesignService(project="mini_f1", root=tmp_path, fusion=fake, reasoner_factory=lambda r: rs, background=False)
    run_id = svc.start(BRIEF18)
    src = svc.store.get_part("SUF-L")
    svc.store.save_part(src.model_copy(update={"script_body": src.script_body + "    # revised\n",
                                               "script_sha256": "1" * 64}), "t", "test")
    return svc, run_id


def test_service_marks_stale_and_re_derive_clears_it(tmp_path):
    svc, run_id = _stale_service(tmp_path)
    row = next(r for r in svc.run_view(run_id)["parts"] if r["id"] == "SUF-R")
    assert row["derived"]["stale"] and row["derived"]["latest_source_version"] == 2
    with pytest.raises(ValueError):
        svc.rebuild_mirror(run_id, "SUF-L")
    svc.rebuild_mirror(run_id, "SUF-R")
    assert svc.store.get_part("SUF-R").derived["source_version"] == 2
    assert not next(r for r in svc.run_view(run_id)["parts"] if r["id"] == "SUF-R")["derived"]["stale"]


def test_page_offers_re_derive_for_a_stale_part(tmp_path):
    """Real page in headless Edge/Chromium: STALE badge and Re-derive button."""
    import subprocess
    import threading

    from agent.service import AgentService
    from tests.helpers import FakeFusion, ScriptedBackend
    from tests.test_run_selector import EDGE
    import ui.server as server
    if not EDGE:
        pytest.skip("no headless Edge/Chromium available")
    svc, run_id = _stale_service(tmp_path)
    strict = AgentService(project="bench", root=tmp_path, fusion=FakeFusion(),
                          backend_factory=lambda r: ScriptedBackend({}), background=False)
    srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(strict, svc))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        out = subprocess.run([EDGE, "--headless=new", "--disable-gpu", f"--user-data-dir={tmp_path / 'edge'}",
                              "--virtual-time-budget=8000", "--dump-dom",
                              f"http://127.0.0.1:{srv.server_address[1]}/?run={run_id}"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90).stdout
    finally:
        srv.shutdown()
        srv.server_close()
    assert "Re-derive from SUF-L v2" in out and ">STALE<" in out and ">YAW180<" in out, out[-500:]
