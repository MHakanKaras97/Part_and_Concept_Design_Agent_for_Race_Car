"""Assembly measurement and camera scripts for a design run's document (fast mode).

Verified live (2705.1.30, throwaway documents, 2026-10-10): MeasureManager.measureMinimumDistance(occA, occB) returns
the exact gap between two placed occurrences (50.0 mm for two cubes 50 mm apart; 0 when touching/overlapping);
Design.analyzeInterference on a collection of TWO occurrences returns the overlap body (volume, extents) - with more
than two its results cannot be attributed to occurrences, so it runs per pair. As-built rigid joints between placed
occurrences are created without moving them. Screenshots (fusion_mcp_read) add no stdout wrapper layer.

Pair cost (an 18-part car has 153 pairs): planned-mate pairs are always measured; any other pair only when the
occurrence bounding boxes are within PAIR_NEAR_MM (farther apart they cannot touch or interfere, so nothing is
lost). analyzeInterference, the slow call, runs only when the two bounding boxes overlap on all three axes.

Overlap depth (MEASURE_VERSION 2): for planned-overlap mates, every separate interference piece (lump) is measured on
its own - Fusion groups pieces into result bodies differently for mirrored parts - by a grid of rays along the
contact direction (from the planned envelopes, else the piece's thinnest side) through both parts: the depth is the
longest stretch inside both (DEPTH_HELPERS, pure and unit-tested). The old value (smallest bbox side of each result
body, version 1) stays in overlap_depth_mm; it overstates a thin strip along a tapered wall and grouped pieces.

Both scripts end normally and report through one @@RESULT@@ line.
"""
from __future__ import annotations

import base64
import json

from agent import fast_config

MEASURE_VERSION = 2

# Pure helpers, inserted verbatim into the assembly script and exec'd by the unit tests (tests/test_overlap_depth.py).
DEPTH_HELPERS = r'''
def ray_intervals(ts, eps=1e-4):
    """Hit coordinates along a ray that starts outside the solid -> inside intervals; None if the hits do not pair
    up (a grazing hit): that ray is not used."""
    out = []
    for t in sorted(ts):
        if not out or t - out[-1] > eps:              # a hit on an edge is reported by both faces
            out.append(t)
    if len(out) % 2:
        return None
    return [(out[i], out[i + 1]) for i in range(0, len(out), 2)]


def overlap_stretch(ia, ib, lo, hi):
    """Longest stretch inside both A and B that meets the piece's range [lo, hi] along the ray."""
    best = 0.0
    for a0, a1 in ia:
        for b0, b1 in ib:
            s, e = max(a0, b0), min(a1, b1)
            if e > s and e >= lo and s <= hi:
                best = max(best, e - s)
    return best


def piece_depth(box, axis, cast, n=9):
    """box: [[min], [max]] of ONE interference piece (mm). axis: 0/1/2 (contact direction) or None (the piece's
    thinnest side). cast(point, axis) -> (hits_a, hits_b): hit coordinates along axis of a ray through point
    parallel to axis, from outside both parts; None if the ray failed. Returns (depth_mm, rays_used, axis)."""
    lo, hi = box
    if axis is None:
        axis = min(range(3), key=lambda i: hi[i] - lo[i])
    u, v = [i for i in range(3) if i != axis]
    best, used = 0.0, 0
    for i in range(n):
        for j in range(n):
            p = [0.0, 0.0, 0.0]
            p[u] = lo[u] + (hi[u] - lo[u]) * (0.01 + 0.98 * i / (n - 1))
            p[v] = lo[v] + (hi[v] - lo[v]) * (0.01 + 0.98 * j / (n - 1))
            p[axis] = lo[axis]
            r = cast(p, axis)
            if r is None:
                continue
            ia, ib = ray_intervals(r[0]), ray_intervals(r[1])
            if ia is None or ib is None:
                continue
            used += 1
            best = max(best, overlap_stretch(ia, ib, lo[axis], hi[axis]))
    return best, used, axis


def pair_depth(pieces, axis, cast, n=9):
    """pieces: bboxes of every separate interference piece of the pair, however Fusion grouped them.
    Returns (depth_mm or None if undetermined, per-piece rows, note)."""
    rows, depth = [], 0.0
    for box in pieces:
        d, used, ax = piece_depth(box, axis, cast, n)
        rows.append({"bbox": [[round(x, 3) for x in box[0]], [round(x, 3) for x in box[1]]], "axis": "XYZ"[ax],
                     "depth_mm": round(d, 4), "rays": used})
        if used == 0 or d <= 0.0:
            return None, rows, "piece %d: no ray found a stretch inside both parts" % len(rows)
        depth = max(depth, d)
    if not rows:
        return None, rows, "no interference piece"
    return depth, rows, ""
'''
from fusion.client import RESULT_MARKER, FusionMCPClient
from fusion.prelude import DOC_ATTR_GROUP, DOC_ATTR_NAME, part_key

_COMMON = r'''import base64, json, sys, traceback
import adsk.core, adsk.fusion

CFG = json.loads(base64.b64decode("__CFG_B64__").decode("utf-8"))


def _depth():
    d, s = 0, sys.stdout
    while hasattr(s, "_original") and d < 100000:
        d += 1
        s = s._original
    return d


def _design():
    app = adsk.core.Application.get()
    for i in range(app.documents.count):
        doc = app.documents.item(i)
        d = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
        a = d.attributes.itemByName(CFG["attr"][0], CFG["attr"][1]) if d else None
        if a is not None and a.value == CFG["doc_tag"]:
            if app.activeDocument != doc:
                doc.activate()
            return adsk.fusion.Design.cast(app.activeProduct)
    raise RuntimeError("design document '%s' is not open in Fusion" % CFG["doc_tag"])


def _occ(root, key):
    for i in range(root.occurrences.count):
        o = root.occurrences.item(i)
        if o.component.name.startswith(key):
            return o
    return None
'''

_ASSEMBLY = _COMMON + DEPTH_HELPERS + r'''

def _ray_cast(root, occ_a, occ_b, start):
    """cast(point, axis) for piece_depth: one findBRepUsingRay along +axis from start (below both parts)."""
    names = (occ_a.name, occ_b.name)                      # occurrence names are unique in the root

    def cast(p, axis):
        o = list(p)
        o[axis] = start[axis]
        d = [0.0, 0.0, 0.0]
        d[axis] = 1.0
        pts = adsk.core.ObjectCollection.create()
        try:
            faces = root.findBRepUsingRay(adsk.core.Point3D.create(o[0] / 10.0, o[1] / 10.0, o[2] / 10.0),
                                          adsk.core.Vector3D.create(d[0], d[1], d[2]),
                                          adsk.fusion.BRepEntityTypes.BRepFaceEntityType, -1.0, False, pts)
        except Exception:
            return None
        ha, hb = [], []
        for k in range(faces.count):
            ctx = faces.item(k).assemblyContext
            if ctx is None:
                continue
            c = [pts.item(k).x * 10.0, pts.item(k).y * 10.0, pts.item(k).z * 10.0][axis]
            if ctx.name == names[0]:
                ha.append(c)
            elif ctx.name == names[1]:
                hb.append(c)
        return ha, hb
    return cast


def run(_context):
    res = {"ok": False, "depth": _depth(), "pairs": [], "joints": [], "measure_version": CFG["measure_version"]}
    try:
        app = adsk.core.Application.get()
        design = _design()
        root = design.rootComponent
        occs = {pid: _occ(root, key) for pid, key in CFG["keys"].items()}
        res["missing"] = [pid for pid, o in occs.items() if o is None]
        mm = app.measureManager
        ids = sorted(pid for pid, o in occs.items() if o is not None)
        always = set(tuple(sorted(p)) for p in CFG["pairs"])
        boxes = {}
        for pid in ids:
            try:
                bb = occs[pid].boundingBox
                boxes[pid] = ([bb.minPoint.x * 10.0, bb.minPoint.y * 10.0, bb.minPoint.z * 10.0],
                              [bb.maxPoint.x * 10.0, bb.maxPoint.y * 10.0, bb.maxPoint.z * 10.0])
            except Exception:
                boxes[pid] = None                        # unknown box: the pair is measured in full
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                p = {"a": a, "b": b}
                if boxes[a] is None or boxes[b] is None:
                    sep = [0.0, 0.0, 0.0]
                else:
                    (alo, ahi), (blo, bhi) = boxes[a], boxes[b]
                    sep = [max(alo[k] - bhi[k], blo[k] - ahi[k]) for k in range(3)]
                if (a, b) not in always and max(sep) > CFG["near_mm"]:
                    p["skipped"], p["bbox_gap_mm"] = "bounding boxes apart", round(max(sep), 3)
                    res["pairs"].append(p)
                    continue
                try:
                    p["min_distance_mm"] = round(mm.measureMinimumDistance(occs[a], occs[b]).value * 10.0, 4)
                    vol, depth, pieces = 0.0, 0.0, []
                    inter = []
                    if max(sep) <= 0.01:                 # boxes overlap or touch on every axis
                        coll = adsk.core.ObjectCollection.create()
                        coll.add(occs[a]); coll.add(occs[b])
                        inter = design.analyzeInterference(design.createInterferenceInput(coll))
                        inter = [inter.item(k) for k in range(inter.count)]
                    else:
                        p["interference"] = "not run: bounding boxes disjoint"
                    for item in inter:
                        body = item.interferenceBody
                        vol += body.volume * 1000.0
                        bb = body.boundingBox
                        ext = [(bb.maxPoint.x - bb.minPoint.x) * 10.0, (bb.maxPoint.y - bb.minPoint.y) * 10.0,
                               (bb.maxPoint.z - bb.minPoint.z) * 10.0]
                        depth = max(depth, min(ext))
                        for k in range(body.lumps.count):    # every separate piece, however Fusion grouped them
                            lb = body.lumps.item(k).boundingBox
                            pieces.append([[lb.minPoint.x * 10.0, lb.minPoint.y * 10.0, lb.minPoint.z * 10.0],
                                           [lb.maxPoint.x * 10.0, lb.maxPoint.y * 10.0, lb.maxPoint.z * 10.0]])
                    p["overlap_mm3"], p["overlap_depth_mm"] = round(vol, 3), round(depth, 4)
                    key = a + "|" + b
                    if key in CFG["overlaps"] and vol > CFG["noise_mm3"]:
                        ax = CFG["overlaps"][key]
                        try:
                            start = [min(boxes[a][0][k], boxes[b][0][k]) - 50.0 for k in range(3)]
                            d, rows, note = pair_depth(pieces, ax, _ray_cast(root, occs[a], occs[b], start),
                                                       CFG["ray_grid"])
                        except Exception as e:
                            d, rows, note = None, [], "ray measurement failed: %s" % str(e)[:160]
                        p["depth_pieces"] = rows
                        if d is None:
                            p["depth_method"], p["depth_note"] = "bbox_fallback", note
                        else:
                            p["depth_method"], p["overlap_depth_ray_mm"] = "ray", round(d, 4)
                except Exception as e:
                    p["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
                res["pairs"].append(p)
        if CFG.get("joints"):
            for i in range(root.asBuiltJoints.count - 1, -1, -1):
                jt = root.asBuiltJoints.item(i)
                if jt.name.startswith("MATE "):
                    jt.deleteMe()
            for a, b in CFG["joints"]:
                if occs.get(a) is None or occs.get(b) is None:
                    continue
                try:
                    ji = root.asBuiltJoints.createInput(occs[a], occs[b], None)
                    ji.setAsRigidJointMotion()
                    jt = root.asBuiltJoints.add(ji)
                    jt.name = "MATE %s %s" % (a, b)
                    res["joints"].append([a, b])
                except Exception as e:
                    res.setdefault("joint_errors", []).append("%s-%s: %s" % (a, b, str(e)[:120]))
        res["ok"] = True
    except Exception as e:
        res["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    print(CFG["marker"] + json.dumps(res))
'''

# Sets the active viewport camera from CFG eye/target/up (mm), orthographic and fitted; shared by the camera script
# and the render start script (fusion/render.py), so a render uses exactly the screenshot camera of its view.
CAMERA_HELPERS = r'''

def _aim_camera(app, design):
    try:                                             # clean picture: no selection highlight, no joint glyphs
        app.userInterface.activeSelections.clear()
        design.rootComponent.isJointsFolderLightBulbOn = False
        for i in range(design.allComponents.count):
            c = design.allComponents.item(i)
            c.isSketchFolderLightBulbOn = False
            c.isConstructionFolderLightBulbOn = False
    except Exception:
        pass
    vp = app.activeViewport
    cam = vp.camera
    e, t, u = CFG["eye"], CFG["target"], CFG["up"]
    cam.eye = adsk.core.Point3D.create(e[0] / 10.0, e[1] / 10.0, e[2] / 10.0)
    cam.target = adsk.core.Point3D.create(t[0] / 10.0, t[1] / 10.0, t[2] / 10.0)
    cam.upVector = adsk.core.Vector3D.create(u[0], u[1], u[2])
    cam.cameraType = adsk.core.CameraTypes.OrthographicCameraType
    cam.isFitView = True
    vp.camera = cam
    vp.refresh()
    return vp
'''

_CAMERA = _COMMON + CAMERA_HELPERS + r'''

def run(_context):
    res = {"ok": False, "depth": _depth()}
    try:
        app = adsk.core.Application.get()
        _aim_camera(app, _design())
        res["ok"] = True
    except Exception as e:
        res["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    print(CFG["marker"] + json.dumps(res))
'''

_PROBE = _COMMON + r'''

def run(_context):
    res = {"ok": False, "depth": _depth(), "present": {}}
    try:
        root = _design().rootComponent
        res["present"] = {pid: _occ(root, key) is not None for pid, key in CFG["keys"].items()}
        res["ok"] = True
    except Exception as e:
        res["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    print(CFG["marker"] + json.dumps(res))
'''

# camera eye directions in VCS (+X front, +Y left, +Z up); "front" looks at the car from ahead of it
VIEWS = {"iso": ((1.0, 1.0, 0.8), (0, 0, 1)), "front": ((1.0, 0.0, 0.0), (0, 0, 1)), "top": ((0.0, 0.0, 1.0), (1, 0, 0))}


def _script(template: str, cfg: dict) -> str:
    cfg = dict(cfg, attr=[DOC_ATTR_GROUP, DOC_ATTR_NAME], marker=RESULT_MARKER)
    return template.replace("__CFG_B64__", base64.b64encode(json.dumps(cfg).encode("utf-8")).decode("ascii"))


def assembly_script(doc_tag: str, namespace: str, part_ids: list[str], joints: list[tuple[str, str]],
                    pairs: list[tuple[str, str]] | None = None, near_mm: float | None = None,
                    overlaps: dict | None = None) -> str:
    """joints: pairs that get an as-built rigid joint (none: the script writes nothing); pairs: pairs always
    measured (default: the joints); overlaps {(a, b): axis 0/1/2 or None}: planned-overlap pairs whose depth is
    ray-measured (overlap_axes)."""
    near = fast_config.get("PAIR_NEAR_MM") if near_mm is None else near_mm
    ov = {"|".join(sorted(k)): v for k, v in (overlaps or {}).items()}
    return _script(_ASSEMBLY, {"doc_tag": doc_tag, "keys": {p: part_key(namespace, p) for p in part_ids},
                               "joints": [list(j) for j in joints],
                               "pairs": [list(p) for p in (joints if pairs is None else pairs)], "near_mm": near,
                               "overlaps": ov, "ray_grid": fast_config.get("DEPTH_RAY_GRID"),
                               "noise_mm3": fast_config.get("OVERLAP_IGNORE_MM3"), "measure_version": MEASURE_VERSION})


def camera_cfg(view: str, center_mm=(0.0, 0.0, 0.0), distance_mm: float = 8000.0) -> dict:
    d, up = VIEWS[view]
    n = sum(c * c for c in d) ** 0.5
    eye = [center_mm[i] + d[i] / n * distance_mm for i in range(3)]
    return {"eye": eye, "target": list(center_mm), "up": list(up)}


def camera_script(doc_tag: str, view: str, center_mm=(0.0, 0.0, 0.0), distance_mm: float = 8000.0) -> str:
    return _script(_CAMERA, dict(camera_cfg(view, center_mm, distance_mm), doc_tag=doc_tag))


def probe_script(doc_tag: str, namespace: str, part_ids: list[str]) -> str:
    return _script(_PROBE, {"doc_tag": doc_tag, "probe": True, "keys": {p: part_key(namespace, p) for p in part_ids}})


def probe_design(client: FusionMCPClient, doc_tag: str, namespace: str, part_ids: list[str]) -> dict:
    """Read-only: is the run's tagged document open, which parts does it hold, and the stdout wrapper depth.
    Never creates a document (a revision works only in the run's existing design)."""
    return client.run_script(probe_script(doc_tag, namespace, part_ids)).data or {}


def mate_pairs(mates: list[dict]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(joints, measured pairs) for planned mates: every mate is measured; a keep-clear mate gets no rigid joint."""
    return ([(m["a"], m["b"]) for m in mates if m["expect"] != "clear"], [(m["a"], m["b"]) for m in mates])


def overlap_axes(mates: list[dict], specs: dict) -> dict:
    """{(a, b): contact axis} for planned-overlap mates: the axis from the planned envelopes when it is unique
    (validation.part_checks.planned_contact_axis), else None (piece_depth then takes each piece's thinnest side)."""
    from validation.part_checks import planned_contact_axis
    out = {}
    for m in mates:
        if m["expect"] != "overlap":
            continue
        sa, sb = specs.get(m["a"]), specs.get(m["b"])
        out[(m["a"], m["b"])] = planned_contact_axis(m, sa, sb) if sa is not None and sb is not None else None
    return out


def measure_assembly(client: FusionMCPClient, doc_tag: str, namespace: str, part_ids: list[str],
                     joints: list[tuple[str, str]], pairs: list[tuple[str, str]] | None = None,
                     overlaps: dict | None = None) -> dict:
    return client.run_script(assembly_script(doc_tag, namespace, part_ids, joints, pairs,
                                             overlaps=overlaps)).data or {}


def screenshot_views(client: FusionMCPClient, doc_tag: str, center_mm, views=("iso", "front", "top"),
                     width: int = 1400, height: int = 900) -> tuple[dict[str, bytes], int, list[str]]:
    """Per view: one camera script (explicit eye/target/up, fitted) + one screenshot of the current view. The view
    cube is not used: its orientation depends on the previous camera (a "top" shot came out rotated 180 deg).
    Returns (images, script_calls, errors)."""
    images, calls, errors = {}, 0, []
    for v in views:
        calls += 1
        r = client.run_script(camera_script(doc_tag, v, center_mm)).data or {}
        if not r.get("ok"):
            errors.append(f"{v}: {r.get('error', 'camera failed')}")
            continue
        try:
            images[v] = client.screenshot(direction="current", width=width, height=height)
        except Exception as e:                           # screenshot failures are reported, never fatal
            errors.append(f"{v}: {e}")
    return images, calls, errors
