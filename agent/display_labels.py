"""Display wording for stored check results (presentation only).

The stored records, the internal status values (VERIFIED, NON_COMPLIANT, NOT_VERIFIED, ...) and the code that judges
them are unchanged; these functions only choose the words a reader sees in the UI and in summary.md. They say what
was measured instead of using the word "verified" for a measurement that matched a plan.
"""
from __future__ import annotations

PART_CHECK_PASS = "PASS (Fusion read-back matches the plan)"
PART_CHECK_LEGEND = "PASS = the Fusion read-back matches the plan."

FIA_WIDTH_ARTICLE = "C2.3.1"
FIA_WIDTH_TOOLTIP = ("Width proxy: this part's world bounding box measured by Fusion against |Y| <= 950 mm. The rule "
                     "applies to the whole car, with exceptions; nothing here is an FIA compliance check.")

# measured mate state (validation/part_checks.mate_results) -> wording for a mate within its planned limit
_MATE_PASS = {"touching": "CONTACT_MEASURED", "overlap": "PLANNED_OVERLAP_WITHIN_LIMIT"}
_MATE_PASS_GAP = {"gap": "GAP_WITHIN_LIMIT", "clear": "CLEARANCE_MEASURED"}


def check_label(check_id: str, status: str) -> str:
    """Per-part check (PART-*): a VERIFIED result reads PASS; anything else keeps its status."""
    if check_id.startswith("PART-") and status == "VERIFIED":
        return "PASS"
    return status


def check_title(check_id: str, status: str, message: str = "") -> str:
    text = PART_CHECK_PASS if check_label(check_id, status) == "PASS" else status
    return f"{check_id}: {text}" + (f" {message}" if message else "")


def fia_label(article: str, status: str) -> str:
    """C2.3.1 is measured per part as a width proxy; other articles keep their status (NOT_VERIFIED)."""
    if article == FIA_WIDTH_ARTICLE:
        word = {"VERIFIED": "MEASURED", "NON_COMPLIANT": "EXCEEDED"}.get(status, status)
        return f"{article} width proxy {word}"
    return f"{article} {status}"


def fia_tooltip(article: str, note: str = "") -> str:
    head = FIA_WIDTH_TOOLTIP if article == FIA_WIDTH_ARTICLE else ""
    return "\n\n".join(x for x in (head, note) if x)


def mate_label(status: str, measured: dict | None, limit: dict | None) -> str:
    """Planned mate: a VERIFIED result is named after what Fusion measured; anything else keeps its status."""
    if status != "VERIFIED" or not measured:
        return status
    state = measured.get("state")
    if state == "gap":
        expect = (limit or {}).get("expect")
        return _MATE_PASS_GAP.get(expect, "GAP_WITHIN_LIMIT")
    if state == "overlap" and (limit or {}).get("expect") != "overlap":
        return "CONTACT_MEASURED"                       # a touching mate within the contact tolerance
    return _MATE_PASS.get(state, status)
