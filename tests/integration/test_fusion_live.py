"""Live integration tests against a running Fusion (python -m pytest -m fusion).

Every test runs in a THROWAWAY Fusion document that the tests create and tag (design attribute
agent_live_test/tag); every script is guarded so it refuses to run unless the active document carries the expected
tag, and the documents are closed without saving. A design the user has open (e.g. the "Untitled" document with
f1parts BRK-001) is never written to.

Fusion behaviour these tests pin down (verified live on 2705.1.11 and 2705.1.30):
- occurrence.transform2 on the ONLY root occurrence is silently ignored; the generator therefore keeps an empty identity
  anchor occurrence ("VCS origin") first and raises if the placement read-back differs.
- The Fusion MCP add-in rolls back a script's changes to an existing document when the script raises, and it leaks one
  stdout wrapper layer per script call (keep the number of calls low; restart Fusion before a full live run).
"""
import uuid
from contextlib import contextmanager

import numpy as np
import pytest

from fusion.client import FusionError, FusionMCPClient, FusionScriptError
from fusion.generators import l_bracket as g
from fusion.inspect import inspect_component
from tests.helpers import good_inputs
from validation.checks import ANGLE_TOL_DEG, LENGTH_TOL_MM, ExpectedGeometry, geometry_checks
from vehicle.models import Pose, Status
from vehicle.transforms import matrix_to_fusion_cm, pose_to_matrix

pytestmark = pytest.mark.fusion
CID, NAME = "BRK-999", "Integration test bracket"
POSE = Pose(position=(500.0, -250.0, 150.0), rotation_deg=(15.0, 35.0, 60.0))      # Part 001 test pose
PART001 = dict(leg_base_length=120, leg_upright_height=65, bracket_width=70, bracket_thickness=12,
               upright_thickness=10, bend_inner_radius=5, base_hole_diameter=10, base_hole_x0=70,
               base_hole_pitch_x=0, base_hole_pitch_y=40, upright_hole_diameter=8, upright_hole_z0=40,
               upright_hole_pitch_z=0, upright_hole_pitch_y=40, base_hole_rows=1, base_hole_cols=2,
               upright_hole_rows=1, upright_hole_cols=2)
FASTENERS = {"base_fastener": "M8", "upright_fastener": "M6"}
NS = "diag"                                    # throwaway namespace for the placement tests (DIAG-00x)

_GUARD = '''

_guarded_run = run
def run(_context: str):
    import adsk.core, adsk.fusion
    _d = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    _a = _d.attributes.itemByName("agent_live_test", "tag") if _d else None
    if _a is None or _a.value != "%s":
        raise RuntimeError("GUARD: the active Fusion document is not the live-test document %s")
    _guarded_run(_context)
'''

_NEW_DOC = '''
import adsk.core, adsk.fusion, json
def run(_context: str):
    app = adsk.core.Application.get()
    app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    adsk.fusion.Design.cast(app.activeProduct).attributes.add("agent_live_test", "tag", "%s")
    print("@@RESULT@@" + json.dumps({"document": app.activeDocument.name}))
'''

_CLOSE_DOC = '''
import adsk.core, adsk.fusion, json
def run(_context: str):
    app = adsk.core.Application.get()
    closed, back = 0, None
    for i in range(app.documents.count - 1, -1, -1):
        doc = app.documents.item(i)
        d = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
        a = d.attributes.itemByName("agent_live_test", "tag") if d else None
        if a is not None and a.value == "%s":
            doc.close(False)
            closed += 1
    for i in range(app.documents.count):
        doc = app.documents.item(i)
        d = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
        a = d.attributes.itemByName("agent_live_test", "tag") if d else None
        if a is not None and a.value == "%s":
            doc.activate()
            back = doc.name
    print("@@RESULT@@" + json.dumps({"closed": closed, "reactivated": back}))
'''


class GuardedClient(FusionMCPClient):
    """Appends the document guard to every script (build, inspection, helpers) while a test document is active."""
    tag = None

    def run_script(self, script, read_only=False, expect_result=True):
        if self.tag:
            script = script + _GUARD % (self.tag, self.tag)
        return super().run_script(script, read_only=read_only, expect_result=expect_result)

    def raw(self, script):
        return FusionMCPClient.run_script(self, script)


@contextmanager
def fresh_document(client, label):
    """A new tagged Fusion design for one test; closed without saving afterwards."""
    outer, tag = client.tag, f"{label}:{uuid.uuid4().hex[:8]}"
    client.raw(_NEW_DOC % tag)
    client.tag = tag
    try:
        yield tag
    finally:
        client.tag = outer
        client.raw(_CLOSE_DOC % (tag, outer))


@pytest.fixture(scope="module")
def client():
    c = GuardedClient()
    try:
        c.ping()
    except FusionError as e:
        pytest.skip(f"Fusion not available: {e}")
    tag = f"module:{uuid.uuid4().hex[:8]}"
    c.raw(_NEW_DOC % tag)
    c.tag = tag
    yield c
    c.tag = None
    c.raw(_CLOSE_DOC % (tag, ""))


def test_ping(client):
    info = client.ping()
    assert info["fusion_version"]


def test_build_inspect_validate(client):
    p = good_inputs()
    client.run_script(g.build_script(CID, NAME, p, matrix_to_fusion_cm(pose_to_matrix(Pose()))))
    rep = inspect_component(client, g.fusion_component_name(CID, NAME), g.param_prefix(CID))
    exp = ExpectedGeometry(bbox_local=g.expected_bbox_local(p), volume_mm3=g.expected_volume_mm3(p),
                           holes_local=g.expected_holes_local(p), parameters=g.fusion_parameters(CID, p))
    results = geometry_checks(rep, exp)
    failed = {r.check_id: r.message for r in results if r.status != Status.VERIFIED}
    assert not failed, failed


def test_parameters_drive_the_model(client):
    """Changing a Fusion user parameter must regenerate a healthy model with the analytic volume."""
    script = '''
import adsk.core, adsk.fusion, json
def run(_context: str):
    d = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    prm = d.userParameters.itemByName("brk999_bracket_thickness")
    prm.expression = "8 mm"
    occ = [d.rootComponent.occurrences.item(i) for i in range(d.rootComponent.occurrences.count)
           if d.rootComponent.occurrences.item(i).component.name == "%s"][0]
    vol = occ.bRepBodies.item(0).getPhysicalProperties(adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy).volume * 1000
    tl = d.timeline
    bad = [tl.item(i).name for i in range(tl.count) if tl.item(i).healthState != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState]
    prm.expression = "6 mm"
    print("@@RESULT@@" + json.dumps({"volume": vol, "unhealthy": bad}))
''' % g.fusion_component_name(CID, NAME)
    data = client.run_script(script).data
    assert data["unhealthy"] == []
    assert abs(data["volume"] - g.expected_volume_mm3(good_inputs(bracket_thickness=8))) < 1e-3


def test_failed_build_leaves_no_partial_component(client):
    p = good_inputs()
    bad = g.build_script("BRK-998", "Broken", p, matrix_to_fusion_cm(pose_to_matrix(Pose())))
    bad = bad.replace('ex.name = "EX_L_profile"', 'ex.name = "EX_L_profile"\n    raise RuntimeError("injected failure")')
    with pytest.raises(FusionError):
        client.run_script(bad)
    rep = inspect_component(client, g.fusion_component_name("BRK-998", "Broken"), "brk998")
    assert rep.found is False and rep.parameters == {}


def test_same_component_id_in_another_project_namespace_does_not_collide(client):
    """Regression (Milestone 1.2 E2E): BRK-001 of a second project must not touch an existing BRK-001 in the
    same Fusion document."""
    ns, name = "itest", "Namespace test"
    p = good_inputs()
    client.run_script(g.build_script("BRK-001", "Existing", p, matrix_to_fusion_cm(pose_to_matrix(Pose()))))
    before = client.run_script(_SNAPSHOT, read_only=True).data
    try:
        client.run_script(g.build_script("BRK-001", name, p, matrix_to_fusion_cm(pose_to_matrix(Pose())), namespace=ns))
        rep = inspect_component(client, g.fusion_component_name("BRK-001", name, ns), g.param_prefix("BRK-001", ns))
        exp = ExpectedGeometry(bbox_local=g.expected_bbox_local(p), volume_mm3=g.expected_volume_mm3(p),
                               holes_local=g.expected_holes_local(p), parameters=g.fusion_parameters("BRK-001", p, ns))
        failed = {r.check_id: r.message for r in geometry_checks(rep, exp) if r.status != Status.VERIFIED}
        assert not failed, failed
    finally:
        client.run_script(_CLEANUP % (g.component_key("BRK-001", ns), g.param_prefix("BRK-001", ns) + "_"))
    after = client.run_script(_SNAPSHOT, read_only=True).data
    assert after == before          # everything that existed before (the other BRK-001, the anchor) is unchanged
    assert g.ANCHOR_NAME in after["occurrences"]


def _assert_pose(data, expected):
    """Production tolerances (validation.checks): 1e-3 mm, 1e-4 deg."""
    m = np.array(data["transform"]).reshape(4, 4)
    m[:3, 3] *= 10.0                                                          # cm -> mm
    assert np.abs(m[:3, 3] - expected[:3, 3]).max() <= LENGTH_TOL_MM
    cos = np.clip((np.trace(expected[:3, :3].T @ m[:3, :3]) - 1) / 2, -1, 1)
    assert np.degrees(np.arccos(cos)) <= ANGLE_TOL_DEG                        # geodesic rotation error
    assert data["pending_snapshot"] is False
    local = np.array(data["local_vertices"]) * 10.0
    world = np.array(data["world_vertices"]) * 10.0
    assert len(local) == len(world) > 0
    placed = np.array([(expected @ np.array([*v, 1.0]))[:3] for v in local])
    assert np.linalg.norm(placed[:, None] - world[None], axis=2).min(axis=1).max() <= LENGTH_TOL_MM


def test_non_identity_pose_is_applied_and_survives_recompute(client):
    """Regression: a non-identity pose applied by the production generator (transform2 + captured position snapshot)
    must be exactly the pose matrix, leave nothing pending, and survive a recompute. (An uncaptured transform2 change
    is discarded by computeAll - verified live 2026-10-06.)"""
    cid, name = "BRK-997", "Pose regression"
    expected = pose_to_matrix(POSE)
    p = good_inputs()
    try:
        client.run_script(g.build_script(cid, name, p, matrix_to_fusion_cm(expected)))
        reads = [client.run_script(_PLACEMENT % g.fusion_component_name(cid, name), read_only=True).data]
        client.run_script(_RECOMPUTE)
        reads.append(client.run_script(_PLACEMENT % g.fusion_component_name(cid, name), read_only=True).data)
        for data in reads:
            _assert_pose(data, expected)
        rep = inspect_component(client, g.fusion_component_name(cid, name), g.param_prefix(cid))
        exp = ExpectedGeometry(bbox_local=g.expected_bbox_local(p), volume_mm3=g.expected_volume_mm3(p),
                               holes_local=g.expected_holes_local(p), parameters=g.fusion_parameters(cid, p), pose=POSE)
        failed = {r.check_id: r.message for r in geometry_checks(rep, exp) if r.status != Status.VERIFIED}
        assert not failed, failed          # incl. GEO-BBOX (component frame) and GEO-PLACEMENT on the rotated part
    finally:
        client.run_script(_CLEANUP % (g.component_key(cid), g.param_prefix(cid) + "_"))


def test_v2_two_thickness_bracket_rotated_passes_every_check_before_and_after_recompute(client):
    """Generator v2 (base 12 mm, upright 10 mm, R5 bend) at the Part 001 test pose: every geometry check VERIFIED,
    fillets healthy, upright thickness drives the model, and the result survives a recompute."""
    cid, name = "BRK-996", "V2 rotated"
    p = g.BracketInputs.from_values(PART001, FASTENERS)
    exp = ExpectedGeometry(bbox_local=g.expected_bbox_local(p), volume_mm3=g.expected_volume_mm3(p),
                           holes_local=g.expected_holes_local(p), parameters=g.fusion_parameters(cid, p), pose=POSE)
    comp_name = g.fusion_component_name(cid, name)
    try:
        client.run_script(g.build_script(cid, name, p, matrix_to_fusion_cm(pose_to_matrix(POSE))))
        for when in ("after build", "after recompute"):
            rep = inspect_component(client, comp_name, g.param_prefix(cid))
            failed = {r.check_id: r.message for r in geometry_checks(rep, exp) if r.status != Status.VERIFIED}
            assert not failed, (when, failed)
            feats = {f["name"]: f["health"] for f in rep.features}
            assert feats.get("FL_bend_inner") == "HEALTHY" and feats.get("FL_bend_outer") == "HEALTHY", feats
            assert rep.parameters["brk996_bend_outer_radius"]["expression"].replace(" ", "") == \
                "brk996_bend_inner_radius+max(brk996_bracket_thickness;brk996_upright_thickness)"
            client.run_script(_RECOMPUTE)
        # upright_thickness is a live Fusion parameter: changing it regenerates the analytic volume
        data = client.run_script(_SET_PARAM % (comp_name, "brk996_upright_thickness", "8 mm")).data
        assert data["unhealthy"] == []
        assert abs(data["volume"] - g.expected_volume_mm3(g.BracketInputs.from_values(
            dict(PART001, upright_thickness=8), FASTENERS))) < 1e-3
    finally:
        client.run_script(_CLEANUP % (g.component_key(cid), g.param_prefix(cid) + "_"))


# ---------------- placement of a part that is alone in its document (anchor workaround) ----------------

def _part001(**over):
    return g.BracketInputs.from_values(dict(PART001, **over), FASTENERS)


def _assert_placed_alone(client, cid, name, p, when):
    """The part sits exactly at the planned pose, the empty anchor stays first at identity, every geometry and hole
    check (incl. GEO-PLACEMENT, GEO-BBOX, IFC-HOLE-GEOMETRY, GEO-VOLUME) is VERIFIED."""
    comp_name = g.fusion_component_name(cid, name, NS)
    data = client.run_script(_LAYOUT % comp_name, read_only=True).data
    roots = data["roots"]
    assert [r["comp"] for r in roots] == [g.ANCHOR_NAME, comp_name], (when, roots)
    assert roots[0]["bodies"] == 0 and roots[0]["transform"] == np.eye(4).reshape(-1).tolist(), (when, roots[0])
    _assert_pose(data, pose_to_matrix(POSE))
    rep = inspect_component(client, comp_name, g.param_prefix(cid, NS))
    exp = ExpectedGeometry(bbox_local=g.expected_bbox_local(p), volume_mm3=g.expected_volume_mm3(p),
                           holes_local=g.expected_holes_local(p), parameters=g.fusion_parameters(cid, p, NS), pose=POSE)
    results = {r.check_id: r for r in geometry_checks(rep, exp)}
    assert {"GEO-PLACEMENT", "GEO-BBOX", "GEO-VOLUME", "IFC-HOLE-GEOMETRY"} <= set(results), when
    failed = {k: r.message for k, r in results.items() if r.status != Status.VERIFIED}
    assert not failed, (when, failed)


def test_posed_part_alone_in_a_fresh_document_is_placed_exactly(client):
    """Regression (Fusion 2705.x): before the anchor, a posed part built as the only root occurrence stayed at
    identity (500 mm / 66 deg off) with no error."""
    cid, name, p = "DIAG-001", "alone", _part001()
    with fresh_document(client, "alone"):
        client.run_script(g.build_script(cid, name, p, matrix_to_fusion_cm(pose_to_matrix(POSE)), namespace=NS))
        _assert_placed_alone(client, cid, name, p, "after build")
        client.run_script(_RECOMPUTE)
        _assert_placed_alone(client, cid, name, p, "after computeAll")


def test_placement_holds_after_rerun_and_after_delete_and_rebuild(client):
    """The UI re-run cases: remove_previous replaces the part (the anchor survives), and an explicit delete of the
    part followed by a new posed build."""
    cid, name, p = "DIAG-002", "rerun", _part001()
    script = g.build_script(cid, name, p, matrix_to_fusion_cm(pose_to_matrix(POSE)), namespace=NS)
    with fresh_document(client, "rerun"):
        client.run_script(script)
        client.run_script(script)                                              # re-run via remove_previous
        _assert_placed_alone(client, cid, name, p, "after re-run")
        client.run_script(_DELETE_PART % g.component_key(cid, NS))             # delete the part, keep the anchor
        client.run_script(script)
        _assert_placed_alone(client, cid, name, p, "after delete + rebuild")
        client.run_script(_RECOMPUTE)
        _assert_placed_alone(client, cid, name, p, "after delete + rebuild + computeAll")


def test_parameter_edit_keeps_the_pose(client):
    """upright_thickness 10 -> 8 mm on the posed part (in a script that ends normally: the MCP add-in rolls back a
    raising script's changes): pose kept, volume = analytic, features healthy, all checks VERIFIED."""
    cid, name = "DIAG-003", "edit"
    with fresh_document(client, "edit"):
        client.run_script(g.build_script(cid, name, _part001(), matrix_to_fusion_cm(pose_to_matrix(POSE)), namespace=NS))
        comp_name = g.fusion_component_name(cid, name, NS)
        data = client.run_script(_SET_PARAM % (comp_name, g.param_prefix(cid, NS) + "_upright_thickness", "8 mm")).data
        assert data["unhealthy"] == []
        assert abs(data["volume"] - g.expected_volume_mm3(_part001(upright_thickness=8))) < 1e-3
        _assert_placed_alone(client, cid, name, _part001(upright_thickness=8), "after edit")
        client.run_script(_RECOMPUTE)
        _assert_placed_alone(client, cid, name, _part001(upright_thickness=8), "after edit + computeAll")


@pytest.mark.xfail(strict=False, raises=FusionScriptError,
                   reason="Fusion 2705.1.11/2705.1.30 ignore transform2 on the only root occurrence (canary: an XPASS "
                          "means this Fusion build fixed it; the anchor then stays as harmless protection)")
def test_canary_fusion_places_the_only_root_occurrence_without_anchor(client):
    with fresh_document(client, "canary"):
        client.run_script(g.build_script("DIAG-004", "canary", _part001(), matrix_to_fusion_cm(pose_to_matrix(POSE)),
                                         namespace=NS, anchor=False))


def test_ignored_placement_fails_loud_and_leaves_no_part(client):
    """Without the anchor the placement read-back must raise, and the failed build must leave no part and no
    parameters behind."""
    cid, name = "DIAG-005", "fail loud"
    with fresh_document(client, "failloud"):
        try:
            client.run_script(g.build_script(cid, name, _part001(), matrix_to_fusion_cm(pose_to_matrix(POSE)),
                                             namespace=NS, anchor=False))
        except FusionScriptError as e:
            assert "Fusion did not apply the placement" in e.output, e.output[-500:]
        else:
            pytest.skip("this Fusion build applied the placement without an anchor; the fail-loud path cannot be "
                        "triggered (see the canary)")
        data = client.run_script(_LAYOUT % g.fusion_component_name(cid, name, NS), read_only=True).data
        assert data["roots"] == [] and data["params"] == []


_SET_PARAM = '''
import adsk.core, adsk.fusion, json
def run(_context: str):
    d = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    r = d.rootComponent
    occ = [r.occurrences.item(i) for i in range(r.occurrences.count) if r.occurrences.item(i).component.name == "%s"][0]
    d.userParameters.itemByName("%s").expression = "%s"
    vol = occ.bRepBodies.item(0).getPhysicalProperties(adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy).volume * 1000
    tl = d.timeline
    bad = [tl.item(i).name for i in range(tl.count) if tl.item(i).healthState != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState]
    print("@@RESULT@@" + json.dumps({"volume": vol, "unhealthy": bad}))
'''


_PLACEMENT = '''
import adsk.core, adsk.fusion, json
def run(_context: str):
    d = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    r = d.rootComponent
    occ = [r.occurrences.item(i) for i in range(r.occurrences.count) if r.occurrences.item(i).component.name == "%s"][0]
    native = occ.component.bRepBodies.item(0)
    print("@@RESULT@@" + json.dumps({
        "transform": occ.transform2.asArray(),
        "pending_snapshot": d.snapshots.hasPendingSnapshot,
        "local_vertices": [[v.geometry.x, v.geometry.y, v.geometry.z] for v in native.vertices],
        "world_vertices": [[v.geometry.x, v.geometry.y, v.geometry.z] for v in occ.bRepBodies.item(0).vertices]}))
'''

# root occurrences (name, bodies, transform), user parameters, and the part's placement if it exists
_LAYOUT = '''
import adsk.core, adsk.fusion, json
def run(_context: str):
    d = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    r = d.rootComponent
    occs = [r.occurrences.item(i) for i in range(r.occurrences.count)]
    out = {"roots": [{"comp": o.component.name, "bodies": o.component.bRepBodies.count,
                      "transform": [round(v, 12) for v in o.transform2.asArray()]} for o in occs],
           "params": [d.userParameters.item(i).name for i in range(d.userParameters.count)],
           "pending_snapshot": d.snapshots.hasPendingSnapshot}
    hits = [o for o in occs if o.component.name == "%s"]
    if hits:
        occ = hits[0]
        out["transform"] = occ.transform2.asArray()
        out["local_vertices"] = [[v.geometry.x, v.geometry.y, v.geometry.z] for v in occ.component.bRepBodies.item(0).vertices]
        out["world_vertices"] = [[v.geometry.x, v.geometry.y, v.geometry.z] for v in occ.bRepBodies.item(0).vertices]
    print("@@RESULT@@" + json.dumps(out))
'''

_RECOMPUTE = '''
import adsk.core, adsk.fusion, json
def run(_context: str):
    adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct).computeAll()
    print("@@RESULT@@" + json.dumps({"recomputed": True}))
'''

_DELETE_PART = '''
import adsk.core, adsk.fusion, json
def run(_context: str):
    r = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct).rootComponent
    n = 0
    for i in range(r.occurrences.count - 1, -1, -1):
        if r.occurrences.item(i).component.name.startswith("%s"):
            r.occurrences.item(i).deleteMe()
            n += 1
    print("@@RESULT@@" + json.dumps({"deleted": n}))
'''

_SNAPSHOT = '''
import adsk.core, adsk.fusion, json
def run(_context: str):
    d = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    r = d.rootComponent
    occ = sorted(r.occurrences.item(i).component.name for i in range(r.occurrences.count))
    prm = sorted((d.userParameters.item(i).name, d.userParameters.item(i).expression) for i in range(d.userParameters.count))
    print("@@RESULT@@" + json.dumps({"occurrences": occ, "params": prm}))
'''

_CLEANUP = '''
import adsk.core, adsk.fusion, json
def run(_context: str):
    d = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    r = d.rootComponent
    for i in range(r.occurrences.count - 1, -1, -1):
        if r.occurrences.item(i).component.name.startswith("%s"):
            r.occurrences.item(i).deleteMe()
    ups = d.userParameters
    names = sorted([ups.item(i).name for i in range(ups.count) if ups.item(i).name.startswith("%s")],
                   key=lambda n: 0 if n.endswith("outer_radius") else 1 if n.endswith("_upright_thickness") else 2)
    for n in names:
        ups.itemByName(n).deleteMe()
    print("@@RESULT@@" + json.dumps({"cleaned": True}))
'''
