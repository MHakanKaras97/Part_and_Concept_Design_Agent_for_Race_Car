"""Display wording (agent/display_labels.py): words only; the stored status values stay as they are."""
import json
from pathlib import Path

from agent.design_run import render_summary
from agent.design_service import build_design_view
from agent.display_labels import check_label, check_title, fia_label, fia_tooltip, mate_label

RUN = Path(__file__).resolve().parents[1] / "data/mini_f1/design_runs/20261012-080916-rebuild-assembly-of-20261012-073"


def test_part_checks_read_pass_only_when_verified():
    assert check_label("PART-BBOX", "VERIFIED") == "PASS"
    assert check_title("PART-BBOX", "VERIFIED") == "PART-BBOX: PASS (Fusion read-back matches the plan)"
    assert check_label("PART-BBOX", "NON_COMPLIANT") == "NON_COMPLIANT"
    assert check_label("PART-FEATURES", "NOT_VERIFIED") == "NOT_VERIFIED"
    assert check_label("MATE-A-B", "VERIFIED") == "VERIFIED"              # only per-part checks are renamed


def test_fia_width_is_a_measured_proxy_and_other_articles_keep_their_status():
    assert fia_label("C2.3.1", "VERIFIED") == "C2.3.1 width proxy MEASURED"
    assert fia_label("C2.3.1", "NON_COMPLIANT") == "C2.3.1 width proxy EXCEEDED"
    assert fia_label("C2.3.1", "NOT_VERIFIED") == "C2.3.1 width proxy NOT_VERIFIED"
    assert fia_label("C3.10.1", "NOT_VERIFIED") == "C3.10.1 NOT_VERIFIED"
    tip = fia_tooltip("C2.3.1", "note")
    assert "|Y| <= 950 mm" in tip and "whole car" in tip and "not" in tip and tip.endswith("note")
    assert fia_tooltip("C3.10.1", "note") == "note"


def test_mates_are_named_after_what_fusion_measured():
    def m(state, expect):
        return mate_label("VERIFIED", {"state": state}, {"expect": expect})
    assert m("touching", "touching") == "CONTACT_MEASURED"
    assert m("overlap", "touching") == "CONTACT_MEASURED"              # within the contact tolerance
    assert m("touching", "overlap") == "CONTACT_MEASURED"
    assert m("overlap", "overlap") == "PLANNED_OVERLAP_WITHIN_LIMIT"
    assert m("gap", "gap") == "GAP_WITHIN_LIMIT"
    assert m("gap", "clear") == "CLEARANCE_MEASURED"
    assert mate_label("NON_COMPLIANT", {"state": "gap"}, {"expect": "touching"}) == "NON_COMPLIANT"
    assert mate_label("NOT_VERIFIED", None, None) == "NOT_VERIFIED"


def test_recorded_run_view_and_summary_use_the_wording_but_keep_the_stored_statuses():
    d = json.loads((RUN / "run.json").read_text(encoding="utf-8"))
    v = build_design_view(d)
    mon = next(p for p in v["parts"] if p["id"] == "MON-001")
    assert {c["status"] for c in mon["checks"]} == {"VERIFIED"} and {c["label"] for c in mon["checks"]} == {"PASS"}
    width = next(f for f in mon["fia"] if f["article"] == "C2.3.1")
    assert width["status"] == "VERIFIED" and width["label"] == "C2.3.1 width proxy MEASURED"
    labels = {a["label"] for a in v["assembly"]}
    assert {"CONTACT_MEASURED", "PLANNED_OVERLAP_WITHIN_LIMIT", "CLEARANCE_MEASURED"} <= labels
    assert {a["status"] for a in v["assembly"]} == {"VERIFIED"}
    assert all(m["label"] for r in v["revisions"] for m in r["mates"])
    md = render_summary(d)
    assert "C2.3.1 width proxy MEASURED" in md and "PART-BBOX:PASS" in md and "CONTACT_MEASURED" in md
    assert "C2.3.1:VERIFIED" not in md and "PASS = the Fusion read-back matches the plan." in md
