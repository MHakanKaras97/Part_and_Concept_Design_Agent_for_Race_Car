"""ONE live revise test against a running Fusion (python -m pytest -m fusion tests/integration/test_revise_live.py).

A two-part design run is built into a throwaway document tagged "livetest-revise:<uuid>" (scripted plan, no Claude);
then a deterministic stand-in revision (no paid Claude call) raises the top block, and a revert brings v1 back as v3.
Every script activates the tagged document first; the user's documents are never written. The document is closed
without saving at the end (test cleanup only). Refuses to run above wrapper depth 100 (it costs about 20 layers).
"""
import json
import uuid

import pytest

from agent.design_run import Orchestrator, create_design_run, load_design_run
from agent.fast_reasoning import ScriptedReasoner
from agent.revise import Reviser
from fusion.client import RESULT_MARKER, FusionError, FusionMCPClient
from vehicle.store import ProjectStore

pytestmark = pytest.mark.fusion

BOX = '''def build(part):
    L, W, H = part.p["length"], part.p["width"], part.p["height"]
    sk = part.sketch(part.plane("z"), "SK_base")
    part.polygon(sk, [(0, -W / 2, 0), (L, -W / 2, 0), (L, W / 2, 0), (0, W / 2, 0)])
    part.extrude(part.profile(sk), "height", "EX_base")
'''
KIT = [{"id": "TST-101", "name": "Base block", "role": "base"}, {"id": "TST-102", "name": "Top block", "role": "top"}]


def _part(pid, name, pos, lo, hi):
    return {"id": pid, "name": name, "role": name.lower(), "notes": "", "position_mm": list(pos),
            "rotation_deg": [0, 0, 0], "envelope_min": list(lo), "envelope_max": list(hi),
            "dims": {"length": hi[0] - lo[0], "width": hi[1] - lo[1], "height": hi[2] - lo[2]},
            "fia_refs_used": [], "reuse": False}


PLAN = {"question": None, "assumptions": ["live test geometry"],
        "parts": [_part("TST-101", "Base block", (0, 0, 0), (0, -50, 0), (200, 50, 40)),
                  _part("TST-102", "Top block", (50, 0, 40), (50, -30, 40), (150, 30, 70))],
        "mates": [{"a": "TST-101", "b": "TST-102", "expect": "touching", "value_mm": 0}]}
STAND_IN = {"spec_delta": {"dims": {"height": 50.0}, "envelope_min": [50.0, -30.0, 40.0],
                           "envelope_max": [150.0, 30.0, 90.0]},
            "body": BOX + "    # live stand-in revision: taller top block\n",
            "change_summary": "top block height 30 -> 50 mm", "assumptions": [], "neighbour_adjustments": []}

_STATE = ("import adsk.core, adsk.fusion, json, sys\n"
          "def run(_context: str):\n"
          "    d, s = 0, sys.stdout\n"
          "    while hasattr(s, '_original') and d < 100000:\n"
          "        d += 1; s = s._original\n"
          "    app = adsk.core.Application.get()\n"
          "    closed = 0\n"
          "    for i in range(app.documents.count - 1, -1, -1):\n"
          "        doc = app.documents.item(i)\n"
          "        dz = adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))\n"
          "        a = dz.attributes.itemByName('agent_design', 'run') if dz else None\n"
          "        if CLOSE and a is not None and a.value == TAG:\n"
          "            doc.close(False); closed += 1\n"
          "    docs = [app.documents.item(i).name for i in range(app.documents.count)]\n"
          f"    print('{RESULT_MARKER}' + json.dumps({{'depth': d, 'documents': docs, 'closed': closed}}))\n")


def _state(client, tag, close):
    return client.run_script(f"TAG = {json.dumps(tag)}\nCLOSE = {close}\n" + _STATE).data or {}


def test_live_revise_and_revert_in_a_throwaway_document(tmp_path):
    client = FusionMCPClient()
    try:
        client.connect()
    except FusionError as e:
        pytest.skip(f"Fusion not available: {e}")
    tag = f"livetest-revise:{uuid.uuid4().hex[:8]}"
    start = _state(client, tag, False)
    if start["depth"] >= 100:
        pytest.skip(f"wrapper depth {start['depth']} >= 100: restart Fusion first")
    report = {"depth_start": start["depth"], "user_documents_before": start["documents"]}
    try:
        store = ProjectStore("livetest_revise", root=tmp_path)
        run = create_design_run(store, "Live revise test", kit=KIT)
        run.data["doc_tag"] = tag                                      # the throwaway document's tag
        run.save()
        rs = ScriptedReasoner({"plan": [PLAN], "part": [{"body": BOX}] * 2})
        run = Orchestrator(store, fusion=client, reasoner_factory=lambda r: rs).advance(run)
        assert run["status"] == "DONE", (run["error"], run["events"][-4:])
        assert [r["status"] for r in run["assembly"]["results"]] == ["VERIFIED"], run["assembly"]["results"]
        frame = {pid: next(c for c in st["checks"] if c["check_id"] == "PART-FRAME") for pid, st in run["parts"].items()}
        assert all(f["status"] == "VERIFIED" for f in frame.values()), frame   # real local bbox from Fusion
        report["frame_local_bbox_TST-102"] = frame["TST-102"]["measured"]["bbox_local"]

        stand_in = ScriptedReasoner({"revise": [STAND_IN]})
        rev = Reviser(store, fusion=client, reasoner_factory=lambda d: stand_in).revise(
            run, "TST-102", "Make the top block 50 mm tall.", entered_via="live test (stand-in, no Claude)")
        assert rev["state"] == "DONE", (rev["error"], rev["events"][-6:])
        v2 = store.get_part("TST-102")
        assert v2.version == 2 and v2.bbox_world[1][2] == pytest.approx(90.0, abs=1e-3)
        assert store.get_part_version("TST-102", 1).bbox_world[1][2] == pytest.approx(70.0, abs=1e-3)   # v1 kept
        assert [m["status"] for m in rev["mates_after"]] == ["VERIFIED"]
        report["revise"] = {"counters": rev["counters"], "bbox_before": rev["steps"][0]["bbox_before"],
                            "bbox_after": rev["steps"][0]["bbox_after"], "mates": rev["mates_after"],
                            "mate_faces": rev["mate_faces"], "views": sorted(rev["screenshots"]["after"])}

        back = Reviser(store, fusion=client).revert(load_design_run(store, run.id), "TST-102", 1,
                                                   entered_via="live test")
        assert back["state"] == "DONE", (back["error"], back["events"][-6:])
        v3 = store.get_part("TST-102")
        assert v3.version == 3 and v3.history[-1].summary == "reverted to v1"
        assert v3.bbox_world[1][2] == pytest.approx(70.0, abs=1e-3)
        assert [m["status"] for m in back["mates_after"]] == ["VERIFIED"]
        report["revert"] = {"counters": back["counters"], "bbox_after": back["steps"][0]["bbox_after"],
                            "mates": back["mates_after"]}
    finally:
        end = _state(client, tag, True)
        report.update(depth_end=end["depth"], closed=end["closed"], user_documents_after=end["documents"])
        print("LIVE_REPORT " + json.dumps(report))
    assert end["closed"] == 1 and end["documents"] == start["documents"]       # user documents untouched
