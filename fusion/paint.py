"""Apply palette: recolour every part of a run's Fusion design IN PLACE (no geometry change, no rebuild) in ONE script
call that ends normally and reports through @@RESULT@@, with a read-back of every body's applied colour.

The script refuses to touch anything above max_depth (MCP stdout wrapper leak) and writes only appearances: one
design appearance per finish + colour ("agent <finish> <RRGGBB>", fusion/prelude.py PAINT_HELPERS) assigned to the
bodies of each part's component, then to the faces of its zones (vehicle/palette.py rules). Face overrides of an
earlier palette are removed first, so a zone dropped from the palette does not leave its old colour behind.
"""
from __future__ import annotations

from typing import Optional

from fusion.assembly import _COMMON, _script
from fusion.client import FusionMCPClient
from fusion.prelude import PAINT_HELPERS, part_key
from vehicle.palette import Paint

_RECOLOR = _COMMON + PAINT_HELPERS + r'''
import time

def run(_context):
    t0 = time.time()
    res = {"ok": False, "depth": _depth(), "parts": {}}
    if res["depth"] > CFG["max_depth"]:
        res["error"] = "MCP stdout wrapper depth %d > %d: restart Fusion first" % (res["depth"], CFG["max_depth"])
        print(CFG["marker"] + json.dumps(res))
        return
    try:
        design = _design()
        root = design.rootComponent
        for pid, p in CFG["parts"].items():
            occ = _occ(root, p["key"])
            if occ is None:
                res["parts"][pid] = {"present": False}
                continue
            comp = occ.component
            bodies = [comp.bRepBodies.item(i) for i in range(comp.bRepBodies.count)]
            ap, fin = _paint_appearance(design, p["color"], p["finish"])
            zones, keep, cleared, clear_failed = [], set(), 0, 0
            if ap is not None:
                _set_body_paint(comp, ap)
                zones, keep = _paint_zones(design, comp, p.get("zones"))
                cleared, clear_failed = _clear_face_paint(comp, keep)     # overrides of an earlier palette only
            res["parts"][pid] = {"present": True, "bodies": len(bodies), "finish": fin,
                                 "applied": [_paint_of(b) for b in bodies], "zones": zones,
                                 "face_overrides": _override_count(comp), "cleared": cleared,
                                 "clear_failed": clear_failed}
        res["ok"] = True
    except Exception as e:
        res["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    res["seconds"] = round(time.time() - t0, 2)
    print(CFG["marker"] + json.dumps(res))
'''


def recolor_script(doc_tag: str, namespace: str, paints: dict[str, Paint], max_depth: int,
                   dims: Optional[dict[str, dict]] = None) -> str:
    """dims {part_id: spec dims}: the zone rules' parameters (vehicle.palette.zone_params)."""
    dims = dims or {}
    return _script(_RECOLOR, {"doc_tag": doc_tag, "recolor": True, "max_depth": max_depth,
                              "parts": {pid: dict(p.cfg(dims.get(pid)), key=part_key(namespace, pid))
                                        for pid, p in paints.items()}})


def recolor(client: FusionMCPClient, doc_tag: str, namespace: str, paints: dict[str, Paint], max_depth: int,
            dims: Optional[dict[str, dict]] = None) -> dict:
    return client.run_script(recolor_script(doc_tag, namespace, paints, max_depth, dims)).data or {}


def compare(paints: dict[str, Paint], data: dict) -> dict[str, dict]:
    """Per part: expected vs read back. ok = present, at least one body, every body has the expected colour, every
    zone painted at least one face in the zone colour, and no face outside the zones keeps an override. A finish
    that fell back to plain colour is a note, not a mismatch (the colour is still right)."""
    out = {}
    for pid, p in paints.items():
        got = (data.get("parts") or {}).get(pid)
        row = {"expected": {"hex": p.hex, "finish": p.finish, "source": p.source}, "got": None, "ok": False,
               "problem": None, "note": None}
        if got is None:
            row["problem"] = "not reported"
        elif not got.get("present"):
            row["problem"] = "part not in the Fusion design"
        else:
            hexes = sorted({(a.get("hex") or "?") for a in got.get("applied", [])})
            names = sorted({(a.get("appearance") or "?") for a in got.get("applied", [])})
            row["got"] = {"hex": hexes, "appearance": names, "finish": got.get("finish"), "bodies": got.get("bodies")}
            if not got.get("bodies"):
                row["problem"] = "no bodies"
            elif got.get("finish") is None:
                row["problem"] = "no usable appearance"
            elif hexes != [p.hex]:
                row["problem"] = f"colour read back {', '.join(hexes)} (expected {p.hex})"
            else:
                row["problem"] = _zone_problem(p, got, row)
                row["ok"] = row["problem"] is None
                notes = [f"finish {p.finish} unavailable: plain colour"] if got.get("finish") != p.finish else []
                notes += [f"zone {z['rule']}: finish {z.get('finish_expected')} unavailable: plain colour"
                          for z in row["got"]["zones"] if z.get("plain")]
                row["note"] = "; ".join(notes) or None
        out[pid] = row
    return out


def _zone_problem(p: Paint, got: dict, row: dict) -> Optional[str]:
    zones = {z["rule"]: z for z in got.get("zones") or []}
    row["expected"]["zones"] = [{"rule": z.rule, "hex": z.color, "finish": z.finish} for z in p.zones]
    row["got"]["zones"] = []
    problems, painted = [], 0
    for z in p.zones:
        g = zones.get(z.rule) or {"error": "not reported"}
        row["got"]["zones"].append({"rule": z.rule, "faces": g.get("faces", 0), "hex": g.get("hex", []),
                                    "plain": g.get("finish") == "plain", "finish_expected": z.finish,
                                    "error": g.get("error")})
        if g.get("error"):
            problems.append(f"zone {z.rule}: {g['error']}")
        elif g.get("hex") != [z.color]:
            problems.append(f"zone {z.rule}: colour read back {', '.join(g.get('hex') or ['?'])} (expected {z.color})")
        else:
            painted += g.get("faces", 0)
    row["got"]["face_overrides"] = got.get("face_overrides", 0)
    stray = got.get("face_overrides", 0) - painted
    if not problems and stray:
        problems.append(f"{stray} face(s) outside the zones keep an old colour")
    return "; ".join(problems) or None


def mismatches(rows: dict[str, dict]) -> list[str]:
    return [f"{pid}: {r['problem']}" for pid, r in rows.items() if not r["ok"]]


def recolor_summary(rows: dict[str, dict], error: Optional[str] = None) -> str:
    if error:
        return f"recolour failed: {error}"
    bad = mismatches(rows)
    return f"{len(rows) - len(bad)}/{len(rows)} parts recoloured as specified" + (f"; {'; '.join(bad)}" if bad else "")
