"""Fast mode P1: prelude composition, static safety validator, part runner, deterministic checks, registry, rebuild."""
import json

import pytest

from fusion.assembly import assembly_script, camera_script, screenshot_views
from fusion.part_runner import build_part, compact_error, rebuild_part, to_record
from fusion.prelude import BODY_START, body_line_offset, compose_part_script
from fusion.script_safety import UnsafeScript, check_body, validate_body
from tests.helpers import FakePartFusion, decode_part_cfg
from validation.part_checks import mate_results, part_checks, repairable
from vehicle.models import Status
from vehicle.parts import PartSpec
from vehicle.store import ProjectStore

BOX = '''def build(part):
    L, W = part.p["length"], part.p["width"]
    sk = part.sketch(part.plane("z"), "SK_base")
    part.polygon(sk, [(0, -W / 2, 0), (L, -W / 2, 0), (L, W / 2, 0), (0, W / 2, 0)])
    part.extrude(part.profile(sk), "height", "EX_base")
'''


def spec(**over) -> PartSpec:
    d = dict(id="TST-001", name="Test box", role="smoke", dims={"length": 100.0, "width": 50.0, "height": 30.0},
             position_mm=(500.0, 0.0, 100.0), envelope_min=(500.0, -25.0, 100.0), envelope_max=(600.0, 25.0, 130.0))
    d.update(over)
    return PartSpec.model_validate(d)


def fake_for(s: PartSpec) -> FakePartFusion:
    return FakePartFusion(envelopes={s.id: (list(s.envelope_min), list(s.envelope_max))})


# ---------------------------------------------------------------- prelude
def test_composed_script_compiles_and_maps_body_lines():
    s = compose_part_script(BOX, {"doc_tag": "t", "create_doc": True, "part_id": "TST-001", "name": "box",
                                  "namespace": "x", "params": {"length": 1}, "matrix_cm": [1, 0, 0, 0] * 4,
                                  "paint": {"color": [1, 2, 3], "hex": "#010203", "finish": "satin"}})
    compile(s, "part", "exec")
    lines = s.split("\n")
    assert lines[body_line_offset() - 1] == BODY_START
    assert lines[body_line_offset()] == BOX.splitlines()[0]
    cfg = decode_part_cfg(s)
    assert cfg["key"] == "x TST-001 " and cfg["prefix"] == "x_tst001" and cfg["anchor"] == "VCS origin"
    assert cfg["body_offset"] == body_line_offset()


def test_prelude_never_saves_closes_or_raises_out_of_run():
    s = compose_part_script(BOX, {"doc_tag": "t", "part_id": "TST-001", "name": "b", "params": {},
                                  "matrix_cm": [0] * 16})
    for word in (".save(", ".saveAs(", ".close("):
        assert word not in s
    run = s[s.index("def run(_context)"):]
    assert "raise" not in run.replace("raise RuntimeError(\"build(part) created no body\")", "")


# ---------------------------------------------------------------- safety validator
def test_validator_accepts_the_contract_example():
    assert check_body(BOX) == []
    validate_body(BOX)


@pytest.mark.parametrize("body,needle", [
    ("import os\ndef build(part):\n    pass\n", "import 'os'"),
    ("import subprocess\ndef build(part):\n    pass\n", "import 'subprocess'"),
    ("def build(part):\n    open('x')\n", "name 'open'"),
    ("def build(part):\n    exec('1')\n", "name 'exec'"),
    ("def build(part):\n    eval('1')\n", "name 'eval'"),
    ("def build(part):\n    __import__('os')\n", "__import__"),
    ("def build(part):\n    part.comp.bRepBodies.item(0).deleteMe()\n", ".deleteMe"),
    ("def build(part):\n    part.comp.parentDesign.rootComponent\n", ".rootComponent"),
    ("def build(part):\n    adsk.core.Application.get().activeDocument.save('x')\n", ".save"),
    ("def build(part):\n    part.comp.__class__\n", "underscore attribute"),
    ("def build(part):\n    _depth()\n", "underscore name"),
    ("def build(part):\n    pass\ndef run(c):\n    pass\n", "prelude name 'run'"),
    ("def build(part):\n    print('@@RESULT@@{}')\n", "result markers"),
    ("def make(part):\n    pass\n", "must define build(part)"),
    ("def build(part):\n    x = (\n", "SyntaxError"),
    ("from os import path\ndef build(part):\n    pass\n", "import from 'os'"),
    ("for i in range(3):\n    pass\ndef build(part):\n    pass\n", "top level"),
])
def test_validator_rejects(body, needle):
    problems = check_body(body)
    assert any(needle in p for p in problems), problems
    with pytest.raises(UnsafeScript):
        validate_body(body)


def test_unsafe_body_never_reaches_fusion():
    s, fake = spec(), FakePartFusion()
    b = build_part(fake, s, "import os\ndef build(part):\n    os.remove('x')\n", "x", "t")
    assert not b.ok and b.stage == "validate" and fake.scripts == [] and b.script_calls == 0
    assert compact_error(b)["failing_lines"][0].startswith("   1>")


# ---------------------------------------------------------------- runner + checks
def test_build_part_one_call_and_all_checks_verified():
    s = spec()
    fake = fake_for(s)
    b = build_part(fake, s, BOX, "x", "t")
    assert b.ok and b.passed and b.script_calls == 1 and len(fake.scripts) == 1
    assert {c.check_id: c.status for c in b.checks} == {k: Status.VERIFIED for k in (
        "PART-BUILD", "PART-SOLID", "PART-FEATURES", "PART-BBOX", "PART-FRAME", "PART-PLACEMENT", "PART-PARAMS")}


def test_runtime_error_is_compact_and_repairable():
    s = spec()
    body = BOX.replace('    part.extrude(', '    x = 1  # FAIL_AT_RUNTIME\n    part.extrude(')
    b = build_part(fake_for(s), s, body, "x", "t")
    assert not b.ok and repairable(b.checks)
    e = compact_error(b)
    assert e["stage"] == "body" and "test failure" in e["error"]
    assert any(">" in ln and "FAIL_AT_RUNTIME" in ln for ln in e["failing_lines"])
    assert len(json.dumps(e)) < 1500


def test_bbox_outside_envelope_fails_and_is_repairable():
    s = spec()
    b = build_part(fake_for(s), s, BOX + "    # BBOX_TOO_BIG\n", "x", "t")
    bad = {c.check_id: c for c in b.checks if c.blocking_failure}
    assert set(bad) == {"PART-BBOX", "PART-FRAME"} and "X+ by 100.0 mm" in bad["PART-BBOX"].message
    assert "outside the local envelope" in bad["PART-FRAME"].message
    assert repairable(b.checks)


def test_placement_and_param_mismatch_detected():
    s = spec()
    data = build_part(fake_for(s), s, BOX, "x", "t").data
    data["measure"]["transform"][3] += 0.01
    data["measure"]["params"]["length"] = 99.0
    res = {c.check_id: c for c in part_checks(s, data)}
    assert res["PART-PLACEMENT"].status == Status.NON_COMPLIANT
    assert res["PART-PARAMS"].status == Status.NON_COMPLIANT
    assert not repairable(list(res.values()))           # placement is ours, not Claude's


def test_mate_results_states():
    pairs = {"pairs": [
        {"a": "A", "b": "B", "min_distance_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0},
        {"a": "A", "b": "C", "min_distance_mm": 12.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0},
        {"a": "B", "b": "C", "min_distance_mm": 0.0, "overlap_mm3": 500.0, "overlap_depth_mm": 3.0}]}
    res = {r.check_id: r for r in mate_results(
        [{"a": "A", "b": "B", "expect": "touching"}, {"a": "C", "b": "A", "expect": "gap", "value_mm": 10}], pairs)}
    assert res["MATE-A-B"].status == Status.VERIFIED
    assert res["MATE-A-C"].status == Status.NON_COMPLIANT and res["MATE-A-C"].measured["state"] == "gap"
    assert res["OVERLAP-B-C"].severity.value == "ADVISORY" and res["OVERLAP-B-C"].status == Status.NON_COMPLIANT
    res = mate_results([{"a": "B", "b": "C", "expect": "overlap", "value_mm": 5}], pairs)
    assert res[0].status == Status.VERIFIED


def test_assembly_and_camera_scripts_compile():
    compile(assembly_script("t", "x", ["MON-001", "FWG-001"], [("MON-001", "FWG-001")]), "a", "exec")
    for v in ("iso", "front", "top"):
        cfg = decode_part_cfg(camera_script("t", v, (0, 0, 0)))
        assert cfg["doc_tag"] == "t" and len(cfg["eye"]) == 3


def test_screenshots_use_an_explicit_camera_per_view():
    fake = FakePartFusion()
    images, calls, errors = screenshot_views(fake, "t", (0, 0, 0))
    assert set(images) == {"iso", "front", "top"} and calls == 3 and not errors
    assert fake.screens == ["current"] * 3 and len(fake.scripts) == 3


# ---------------------------------------------------------------- registry + rebuild
def test_registry_versions_and_strict_components_unaffected(tmp_path):
    store = ProjectStore("p", root=tmp_path)
    s = spec()
    fake = fake_for(s)
    rec = store.save_part(to_record(build_part(fake, s, BOX, "x", "t"), "x", "run1", []), "run1", "built")
    assert rec.version == 1 and store.list_components() == [] and [p.id for p in store.list_parts()] == ["TST-001"]
    again = store.save_part(to_record(build_part(fake, s, BOX, "x", "t"), "x", "run2", []), "run2", "rebuilt")
    assert again.version == 1                                  # same script + spec
    changed = store.save_part(to_record(build_part(fake, s, BOX + "    pass\n", "x", "t"), "x", "run3", []), "run3", "v2")
    assert changed.version == 2 and [h.version for h in changed.history] == [1, 2]
    stored = store.get_part("TST-001")
    assert stored.script_body == BOX + "    pass\n" and stored.params == s.dims and stored.bbox_world


def test_rebuild_uses_the_stored_script_with_zero_reasoning(tmp_path):
    store = ProjectStore("p", root=tmp_path)
    s = spec()
    store.save_part(to_record(build_part(fake_for(s), s, BOX, "x", "t"), "x", "run1", []), "run1", "built")
    moved = s.model_copy(update={"position_mm": (0.0, 0.0, 0.0), "envelope_min": (0.0, -25.0, 0.0),
                                 "envelope_max": (100.0, 25.0, 30.0)})
    fake = fake_for(moved)
    b = rebuild_part(fake, store.get_part("TST-001"), "x", "t2", spec=moved)
    assert b.passed and len(fake.scripts) == 1 and BOX in fake.scripts[0]
    assert decode_part_cfg(fake.scripts[0])["doc_tag"] == "t2"


def test_part_records_cannot_overwrite_strict_components(tmp_path):
    store = ProjectStore("p", root=tmp_path)
    store.components_dir.mkdir(parents=True)
    (store.components_dir / "TST-001.json").write_text('{"id": "TST-001"}', encoding="utf-8")
    s = spec()
    with pytest.raises(ValueError):
        store.save_part(to_record(build_part(fake_for(s), s, BOX, "x", "t"), "x", "r", []), "r", "x")
