"""Advisory mate-face check (validation/part_checks.mate_face_checks)."""
from agent.design_run import Orchestrator, create_design_run
from agent.fast_reasoning import ScriptedReasoner
from tests.helpers import MINI_BOX_BODY, FakePartFusion, mini_f1_plan
from validation.part_checks import mate_face_checks
from vehicle.parts import PartSpec
from vehicle.store import ProjectStore


def specs_of(plan):
    return {p["id"]: PartSpec.model_validate({k: v for k, v in p.items()}) for p in plan["parts"]}


def by_face(res):
    return {r["face"]: r for r in res}


def test_touching_faces_pass_and_a_short_solid_warns():
    plan = mini_f1_plan()
    specs = specs_of(plan)
    boxes = {pid: [list(s.envelope_min), list(s.envelope_max)] for pid, s in specs.items()}
    mate = [{"a": "MON-001", "b": "FWG-001", "expect": "touching", "value_mm": 0}]
    r = by_face(mate_face_checks(mate, specs, boxes))
    assert r["MON-001 +X"]["status"] == "PASS" and r["FWG-001 -X"]["status"] == "PASS"
    assert r["MON-001 +X"]["expected_mm"] == 600.0 and "Fusion mate measurement" in r["MON-001 +X"]["note"]
    boxes["FWG-001"][0][0] = 620.0                                     # the wing's solid starts 20 mm forward
    w = by_face(mate_face_checks(mate, specs, boxes))["FWG-001 -X"]
    assert w["status"] == "WARNING" and w["measured_mm"] == 620.0 and w["deviation_mm"] == 20.0
    assert "stops short of the planned face by 20.00 mm" in w["note"]
    boxes["MON-001"][1][0] = 590.0                                     # the nose is 10 mm short too
    m = by_face(mate_face_checks(mate, specs, boxes))["MON-001 +X"]
    assert m["status"] == "WARNING" and m["deviation_mm"] == -10.0 and "stops short" in m["note"]


def test_edge_contact_and_missing_measurement_are_not_checkable():
    specs = specs_of(mini_f1_plan())
    boxes = {pid: [list(x.envelope_min), list(x.envelope_max)] for pid, x in specs.items()}
    edge = mate_face_checks([{"a": "RWG-001", "b": "FLR-001", "expect": "gap", "value_mm": 50}], specs, boxes)
    assert len(edge) == 1 and edge[0]["status"] == "NOT_CHECKABLE"          # meet on X and Z: only an edge
    boxes["FWG-001"] = None
    r = by_face(mate_face_checks([{"a": "MON-001", "b": "FWG-001", "expect": "touching"}], specs, boxes))
    assert r["FWG-001 -X"]["status"] == "NOT_CHECKABLE" and r["FWG-001 -X"]["note"] == "part not measured"
    assert r["MON-001 +X"]["status"] == "PASS"


def test_gap_mate_face_is_checked_across_the_gap():
    a = PartSpec(id="TST-001", name="a", role="t", dims={"l": 1}, position_mm=(0, 0, 0),
                 envelope_min=(0, -10, 0), envelope_max=(100, 10, 10))
    b = PartSpec(id="TST-002", name="b", role="t", dims={"l": 1}, position_mm=(130, 0, 0),
                 envelope_min=(130, -10, 0), envelope_max=(200, 10, 10))
    r = by_face(mate_face_checks([{"a": "TST-001", "b": "TST-002", "expect": "gap", "value_mm": 40}],
                                 {"TST-001": a, "TST-002": b},
                                 {"TST-001": [[0, -10, 0], [100, 10, 10]], "TST-002": [[135, -10, 0], [200, 10, 10]]}))
    assert r["TST-001 +X"]["status"] == "PASS" and r["TST-002 -X"]["status"] == "WARNING"
    assert r["TST-002 -X"]["deviation_mm"] == 5.0


def test_real_mini_f1_registry_faces():
    """The registered Mini F1: wing/nose and rear-wing/tub faces are identifiable and reached; the floor's diffuser
    envelope reaches into the tub's, so MON/FLR has no unique face -> NOT_CHECKABLE (the Fusion measurement decides)."""
    store = ProjectStore("mini_f1")
    recs = {p.id: p for p in store.list_parts()}
    mates = [{"a": "FWG-001", "b": "MON-001", "expect": "touching"}, {"a": "MON-001", "b": "FLR-001", "expect": "touching"},
             {"a": "RWG-001", "b": "MON-001", "expect": "touching"}]
    res = mate_face_checks(mates, {k: r.spec for k, r in recs.items()}, {k: r.bbox_world for k, r in recs.items()})
    r = by_face(res)
    assert r["FWG-001 -X"]["status"] == r["MON-001 +X"]["status"] == "PASS"
    assert r["RWG-001 +X"]["status"] == r["MON-001 -X"]["status"] == "PASS" and r["MON-001 -X"]["expected_mm"] == -3700.0
    nc = r["MON-001/FLR-001"]
    assert nc["status"] == "NOT_CHECKABLE" and "geometric / Fusion-level check" in nc["note"]


def test_design_run_and_summary_carry_mate_faces(tmp_path):
    plan = mini_f1_plan()
    store = ProjectStore("mini_f1", root=tmp_path)
    rs = ScriptedReasoner({"plan": [plan], "part": [{"body": MINI_BOX_BODY}] * 4})
    run = Orchestrator(store, fusion=FakePartFusion(from_params=True, geometric_mates=True),
                       reasoner_factory=lambda r: rs).advance(create_design_run(store, "Mini F1"))
    faces = run["assembly"]["mate_faces"]
    assert faces and {f["status"] for f in faces} <= {"PASS", "NOT_CHECKABLE"}
    assert "mate face (advisory) MON-001 +X: PASS" in (run.dir / "summary.md").read_text(encoding="utf-8")
