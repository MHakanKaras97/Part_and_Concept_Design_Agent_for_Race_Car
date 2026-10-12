"""Prelude for free-form part scripts (fast mode). Contract: docs/fusion_script_contract.md.

compose_part_script(body, cfg) returns ONE Fusion script that, in a single script call:
  1. finds (or creates) the design run's own tagged document and makes it active - never another document;
  2. removes the previous build of this part (idempotent rebuild) and keeps the identity anchor "VCS origin" first;
  3. begin_part: new component at IDENTITY + the part's user parameters (<prefix>_<name>, mm);
  4. runs the body's build(part) - Claude writes only that body; a derived "mirror" part (cfg mirror=True) then
     mirrors every body about the component-local XZ plane and removes the source bodies (_mirror_y);
  5. finish_part: transform2 + snapshot + read-back (reported, never raised: a raise rolls back an existing document);
  6. measures the part-LOCAL bbox before placement (frame check), colours the bodies, measures (bodies, world
     bbox, feature health, parameters, transform) and
  7. emit()s exactly one @@RESULT@@ line, also on failure (compact error + failing body lines).

Every result carries the MCP add-in's stdout wrapper depth (one layer is leaked per script call).
"""
from __future__ import annotations

import base64
import json

from fusion.client import RESULT_MARKER
from fusion.generators.l_bracket import ANCHOR_NAME

DOC_ATTR_GROUP, DOC_ATTR_NAME = "agent_design", "run"
BODY_START = "# ---- BODY START ----"


def part_key(namespace: str, part_id: str) -> str:
    """Leading part of the Fusion component name: identifies the part regardless of its title."""
    return f"{namespace} {part_id} " if namespace else f"{part_id} "


def param_prefix(namespace: str, part_id: str) -> str:
    base = part_id.lower().replace("-", "")                  # MON-001 -> mon001
    return f"{namespace}_{base}" if namespace else base


def compose_part_script(body: str, cfg: dict) -> str:
    """cfg keys: doc_tag, create_doc, part_id, name, namespace, params {name: mm}, matrix_cm (16 floats),
    paint {color [r, g, b], hex, finish} (vehicle.palette.Paint.cfg). The body is inserted verbatim; validate it
    with fusion.script_safety first."""
    full = dict(cfg, key=part_key(cfg.get("namespace", ""), cfg["part_id"]),
                prefix=param_prefix(cfg.get("namespace", ""), cfg["part_id"]), anchor=ANCHOR_NAME,
                attr=[DOC_ATTR_GROUP, DOC_ATTR_NAME], marker=RESULT_MARKER, body_offset=body_line_offset())
    cfg_b64 = base64.b64encode(json.dumps(full).encode("utf-8")).decode("ascii")
    head = PRELUDE.replace("__CFG_B64__", cfg_b64) + "\n" + BODY_START + "\n"
    return head + body.rstrip() + "\n# ---- BODY END ----\n" + RUNNER


def body_line_offset() -> int:
    """Body line n is composed-script line body_line_offset() + n."""
    return (PRELUDE + "\n" + BODY_START + "\n").count("\n")


# --------------------------------------------------------------------------------------------------------------
# Fusion-side code. Names starting with "_" are prelude internals; the safety validator forbids them in the body.
# --------------------------------------------------------------------------------------------------------------

# Paint (vehicle/palette.py): one design appearance per finish + colour, "agent <finish> <RRGGBB>", copied from a
# library base with its colour overridden. Shared by the part prelude and the recolour script (fusion/paint.py).
# Unavailable finish -> plain colour on the glossy paint base ("plain"); nothing usable -> (None, None).
PAINT_HELPERS = r'''
_FINISH_BASES = {"glossy_paint": ["Paint - Enamel Glossy (Red)"],
                 "matte_rubber": ["Rubber - Soft", "Rubber - Hard", "Plastic - Matte (Black)"],
                 "satin": ["Steel - Satin", "Aluminum - Satin", "Plastic - Matte (Gray)"]}
_PLAIN_BASE = "Paint - Enamel Glossy (Red)"
_COLOR_PROPS = ("opaque_albedo", "metal_f0")


def _lib_appearance(name):
    lib = adsk.core.Application.get().materialLibraries.itemByName("Fusion Appearance Library")
    try:
        return lib.appearances.itemByName(name) if lib else None
    except Exception:                                    # itemByName raises on an unknown name
        return None


def _color_prop(ap):
    pp = ap.appearanceProperties
    for pid in _COLOR_PROPS:
        try:
            p = pp.itemById(pid)
        except Exception:
            p = None
        cp = adsk.core.ColorProperty.cast(p) if p else None
        if cp:
            return cp
    return None


def _paint_appearance(design, rgb, finish):
    hexs = "%02X%02X%02X" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    for fin, bases in ((finish, _FINISH_BASES.get(finish, [])), ("plain", [_PLAIN_BASE])):
        nm = "agent %s %s" % (fin, hexs)
        try:
            ap = design.appearances.itemByName(nm)
        except Exception:
            ap = None
        if ap is None:
            base = None
            for b in bases:
                base = _lib_appearance(b)
                if base is not None:
                    break
            if base is None:
                continue
            ap = design.appearances.addByCopy(base, nm)
        cp = _color_prop(ap)
        if cp is None:
            continue
        cp.value = adsk.core.Color.create(int(rgb[0]), int(rgb[1]), int(rgb[2]), 255)
        return ap, fin
    return None, None


def _paint_of(ent):
    """Read back a body's (or a face's override) appearance name and colour (#RRGGBB; None without a colour)."""
    ap = ent.appearance
    if ap is None:
        return {"appearance": None, "hex": None}
    cp = _color_prop(ap)
    c = cp.value if cp else None
    return {"appearance": ap.name, "hex": ("#%02X%02X%02X" % (c.red, c.green, c.blue)) if c else None}


def _bb_mm(b):
    return ([b.minPoint.x * 10.0, b.minPoint.y * 10.0, b.minPoint.z * 10.0],
            [b.maxPoint.x * 10.0, b.maxPoint.y * 10.0, b.maxPoint.z * 10.0])


def _zone_faces(comp, z):
    """(body index, face) pairs of the component's bodies (component space = the part's build frame) selected by
    zone rule z (vehicle/palette.py). Raises when the rule cannot decide (reported by the caller; nothing painted)."""
    bodies = [comp.bRepBodies.item(i) for i in range(comp.bRepBodies.count)]
    faces = []
    if z["rule"] == "wheel_rim":
        rr, yf = z["rim_radius"], z["rim_face_y"]
        for bi, b in enumerate(bodies):
            for f in b.faces:
                lo, hi = _bb_mm(f.boundingBox)
                if max(abs(lo[0]), abs(hi[0]), abs(lo[2]), abs(hi[2])) <= rr + 0.5 and lo[1] >= yf - 2.0:
                    faces.append((bi, f))
    elif z["rule"] == "cockpit":
        for bi, b in enumerate(bodies):
            zmax = _bb_mm(b.boundingBox)[1][2]
            tops = []
            for f in b.faces:
                lo, hi = _bb_mm(f.boundingBox)
                if f.geometry.objectType.endswith("Plane") and abs(lo[2] - zmax) < 0.01 and abs(hi[2] - zmax) < 0.01:
                    tops.append(f)
            if len(tops) != 1:
                raise RuntimeError("no unique planar top face (found %d)" % len(tops))
            flo, fhi = _bb_mm(tops[0].boundingBox)
            for f in b.faces:
                lo, hi = _bb_mm(f.boundingBox)
                if lo[0] >= flo[0] - 1 and hi[0] <= fhi[0] + 1 and lo[1] >= flo[1] - 1 and hi[1] <= fhi[1] + 1:
                    faces.append((bi, f))
    else:
        raise RuntimeError("unknown zone rule %s" % z["rule"])
    return faces


def _is_override(f):
    """face.appearance is the EFFECTIVE appearance; only appearanceSourceType tells an override from the body's."""
    st = getattr(adsk.core, "AppearanceSourceTypes", None) or getattr(adsk.fusion, "AppearanceSourceTypes", None)
    try:
        return f.appearanceSourceType in (st.OverrideAppearanceSource, st.FaceAppearanceSource)
    except Exception:
        return False


def _face_key(bi, f):
    return "%d:%d" % (bi, f.tempId)


def _set_body_paint(comp, ap):
    """Body appearance, written only where it differs (a repeated recolour writes nothing)."""
    for i in range(comp.bRepBodies.count):
        b = comp.bRepBodies.item(i)
        if b.appearance is None or b.appearance.name != ap.name:
            b.appearance = ap


def _paint_zones(design, comp, zones):
    """Face appearance overrides per zone, written only where they differ; never raises. Returns (rows, keys of the
    zone faces). Per zone row: rule, faces selected, finish, read-back colours."""
    out, keep = [], set()
    for z in zones or []:
        row = {"rule": z["rule"], "faces": 0, "finish": None, "hex": [], "error": None}
        if z.get("skip"):
            row["error"] = "skipped: %s" % z["skip"]
            out.append(row)
            continue
        try:
            faces = _zone_faces(comp, z)
            if not faces:
                raise RuntimeError("the rule selected no face")
            ap, fin = _paint_appearance(design, z["color"], z["finish"])
            if ap is None:
                raise RuntimeError("no usable appearance")
            for bi, f in faces:
                if not _is_override(f) or f.appearance.name != ap.name:
                    f.appearance = ap
                keep.add(_face_key(bi, f))
            row.update(faces=len(faces), finish=fin, hex=sorted({_paint_of(f)["hex"] or "?" for _, f in faces}))
        except Exception as e:
            row["error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
        out.append(row)
    return out, keep


def _clear_face_paint(comp, keep):
    """Remove face overrides outside the zone faces `keep` (an earlier palette's zones); returns (cleared, failed)."""
    n, bad = 0, 0
    for bi in range(comp.bRepBodies.count):
        for f in comp.bRepBodies.item(bi).faces:
            if _is_override(f) and _face_key(bi, f) not in keep:
                try:
                    f.appearance = None
                    n += 1
                except Exception:
                    bad += 1
    return n, bad


def _override_count(comp):
    """Faces carrying an appearance override (= the zone faces after a clean recolour)."""
    n = 0
    for i in range(comp.bRepBodies.count):
        for f in comp.bRepBodies.item(i).faces:
            if _is_override(f):
                n += 1
    return n
'''

PRELUDE = r'''import base64, json, math, re, sys, traceback
import adsk.core, adsk.fusion

CFG = json.loads(base64.b64decode("__CFG_B64__").decode("utf-8"))


def mm(v):
    """mm -> Fusion internal cm."""
    return v / 10.0


def pt(x, y, z):
    """Point3D from mm."""
    return adsk.core.Point3D.create(x / 10.0, y / 10.0, z / 10.0)


def val(v_mm):
    """ValueInput for a length in mm."""
    return adsk.core.ValueInput.createByReal(v_mm / 10.0)


def emit(d):
    print(CFG["marker"] + json.dumps(d))


def _depth():
    d, s = 0, sys.stdout
    while hasattr(s, "_original") and d < 100000:
        d += 1
        s = s._original
    return d


def _attr_of(doc):
    d = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
    if d is None:
        return None, None
    a = d.attributes.itemByName(CFG["attr"][0], CFG["attr"][1])
    return d, (a.value if a else None)


def _ensure_doc():
    """The design run's own document (tagged attribute). Activates it; creates it only if allowed."""
    app = adsk.core.Application.get()
    if app.activeDocument is not None:
        d, tag = _attr_of(app.activeDocument)
        if tag == CFG["doc_tag"]:
            return d, False
    for i in range(app.documents.count):
        doc = app.documents.item(i)
        d, tag = _attr_of(doc)
        if tag == CFG["doc_tag"]:
            doc.activate()
            return adsk.fusion.Design.cast(app.activeProduct), False
    if not CFG.get("create_doc"):
        raise RuntimeError("design document '%s' is not open in Fusion" % CFG["doc_tag"])
    app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    d = adsk.fusion.Design.cast(app.activeProduct)
    d.designType = adsk.fusion.DesignTypes.ParametricDesignType
    d.attributes.add(CFG["attr"][0], CFG["attr"][1], CFG["doc_tag"])
    return d, True


def ensure_anchor(root):
    """Fusion ignores transform2 on the ONLY root occurrence: keep an empty identity anchor first."""
    for i in range(root.occurrences.count):
        if root.occurrences.item(i).component.name == CFG["anchor"]:
            return
    root.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component.name = CFG["anchor"]


def _remove_params(design):
    ups = design.userParameters
    names = [ups.item(i).name for i in range(ups.count) if ups.item(i).name.startswith(CFG["prefix"] + "_")]
    for _ in range(3):                                   # dependent parameters may block their references once
        left = []
        for n in names:
            p = ups.itemByName(n)
            if p and not p.deleteMe():
                left.append(n)
        names = left
        if not names:
            return []
    return names


def _remove_previous(design, root):
    for i in range(root.occurrences.count - 1, -1, -1):
        occ = root.occurrences.item(i)
        if occ.component.name.startswith(CFG["key"]):
            occ.deleteMe()
    return _remove_params(design)


class Part:
    """What the body's build(part) receives. Lengths are mm; the component is at IDENTITY (part frame)."""

    def __init__(self, comp):
        self.comp, self.id, self.name = comp, CFG["part_id"], CFG["name"]
        self.p = dict(CFG["params"])                     # key dimensions, mm

    def expr(self, name):
        """User-parameter name for expressions, e.g. part.expr("span") -> "mf1_fwg001_span"."""
        if name not in self.p:
            raise KeyError("no key dimension '%s' (have %s)" % (name, sorted(self.p)))
        return CFG["prefix"] + "_" + name

    def vexpr(self, name):
        return adsk.core.ValueInput.createByString(self.expr(name))

    def plane(self, axis, offset_mm=0.0, name=None):
        """Plane normal to 'x', 'y' or 'z' at offset_mm along that axis (part frame)."""
        base = {"x": self.comp.yZConstructionPlane, "y": self.comp.xZConstructionPlane,
                "z": self.comp.xYConstructionPlane}[axis]
        if abs(offset_mm) < 1e-9:
            return base
        k = "xyz".index(axis)
        cp = None
        for sign in (1.0, -1.0):                         # base plane normals differ: check where it landed
            pi = self.comp.constructionPlanes.createInput()
            pi.setByOffset(base, val(sign * offset_mm))
            cp = self.comp.constructionPlanes.add(pi)
            o = cp.geometry.origin
            if abs((o.x, o.y, o.z)[k] * 10.0 - offset_mm) < 1e-6:
                break
            cp.deleteMe()
        if name:
            cp.name = name
        return cp

    def sketch(self, plane, name):
        sk = self.comp.sketches.add(plane)
        sk.name = name
        return sk

    def polygon(self, sk, pts3_mm):
        """Closed polyline through model points (mm, part frame) lying on the sketch plane."""
        lines = sk.sketchCurves.sketchLines
        sp = [sk.modelToSketchSpace(pt(*p)) for p in pts3_mm]
        first = prev = None
        for i in range(len(sp)):
            a = prev.endSketchPoint if prev else sp[0]
            b = first.startSketchPoint if i == len(sp) - 1 else sp[i + 1]
            ln = lines.addByTwoPoints(a, b)
            first = first or ln
            prev = ln
        return sk

    def profile(self, sk, which="largest"):
        best = None
        for i in range(sk.profiles.count):
            pr = sk.profiles.item(i)
            a = pr.areaProperties().area
            if best is None or (a > best[0] if which == "largest" else a < best[0]):
                best = (a, pr)
        if best is None:
            raise RuntimeError("sketch '%s' has no closed profile" % sk.name)
        return best[1]

    def section(self, axis, offset_mm, pts3_mm, name):
        """Closed section on a plane normal to axis at offset_mm; returns its largest profile (for lofts)."""
        sk = self.sketch(self.plane(axis, offset_mm), name)
        self.polygon(sk, pts3_mm)
        return self.profile(sk)

    def _op(self, op):
        F = adsk.fusion.FeatureOperations
        return {"new": F.NewBodyFeatureOperation, "join": F.JoinFeatureOperation, "cut": F.CutFeatureOperation,
                "intersect": F.IntersectFeatureOperation}[op]

    def extrude(self, profile, distance, name, op="new", symmetric=False, participants=None):
        """distance: mm (float) or a key-dimension name (str, parametric). symmetric: total length centred."""
        v = self.vexpr(distance) if isinstance(distance, str) else val(distance)
        ext = self.comp.features.extrudeFeatures
        ei = ext.createInput(profile, self._op(op))
        if symmetric:
            ei.setSymmetricExtent(v, True)
        else:
            ei.setDistanceExtent(False, v)
        if participants:
            ei.participantBodies = list(participants)
        f = ext.add(ei)
        f.name = name
        return f

    def loft(self, profiles, name, op="new"):
        lf = self.comp.features.loftFeatures
        li = lf.createInput(self._op(op))
        for pr in profiles:
            li.loftSections.add(pr)
        f = lf.add(li)
        f.name = name
        return f

    def body(self, i=0):
        return self.comp.bRepBodies.item(i)


def begin_part(root, design):
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    occ.component.name = CFG["key"] + CFG["name"]
    ups = design.userParameters
    for n, v in CFG["params"].items():
        ups.add(CFG["prefix"] + "_" + n, adsk.core.ValueInput.createByString("%r mm" % float(v)), "mm",
                "%s key dimension" % CFG["part_id"])
    return occ


def finish_part(design, occ, matrix_cm):
    """Place the occurrence; capture the move at once (an uncaptured move is discarded by the next feature)."""
    m = adsk.core.Matrix3D.create()
    m.setWithArray(matrix_cm)
    if not m.isEqualTo(adsk.core.Matrix3D.create()):
        occ.transform2 = m
        if design.snapshots.hasPendingSnapshot:
            design.snapshots.add()
    got = occ.transform2
    return {"applied": bool(got.isEqualTo(m)), "pending": bool(design.snapshots.hasPendingSnapshot)}


# __PAINT_HELPERS__


def _color(design, comp, paint, warnings):
    """Body colour, then face zones; cosmetic: problems are warnings, never errors. Returns the zone rows."""
    try:
        ap, fin = _paint_appearance(design, paint["color"], paint.get("finish", "glossy_paint"))
        if ap is None:
            raise RuntimeError("no usable appearance")
        if fin != paint.get("finish", "glossy_paint"):
            warnings.append("finish %s unavailable: plain colour" % paint.get("finish"))
        _set_body_paint(comp, ap)
    except Exception as e:                               # colouring is cosmetic: fall back silently
        warnings.append("appearance not applied: %s" % str(e)[:120])
        return []
    zones, _ = _paint_zones(design, comp, paint.get("zones"))
    for z in zones:
        if z["error"]:
            warnings.append("zone %s not painted: %s" % (z["rule"], z["error"]))
    return zones


def _health(h):
    S = adsk.fusion.FeatureHealthStates
    return {S.HealthyFeatureHealthState: "HEALTHY", S.WarningFeatureHealthState: "WARNING",
            S.ErrorFeatureHealthState: "ERROR"}.get(h, "UNKNOWN")


def _v(p):
    return [round(p.x * 10.0, 4), round(p.y * 10.0, 4), round(p.z * 10.0, 4)]


def _bbox_local(comp):
    """Part-frame bbox (mm) of the component's native bodies; taken before placement, at identity."""
    lo = hi = None
    for i in range(comp.bRepBodies.count):
        bb = comp.bRepBodies.item(i).boundingBox
        mn, mx = _v(bb.minPoint), _v(bb.maxPoint)
        lo = mn if lo is None else [min(a, c) for a, c in zip(lo, mn)]
        hi = mx if hi is None else [max(a, c) for a, c in zip(hi, mx)]
    return [lo, hi] if lo else None


def _mirror_y(comp):
    """Derived handed part: mirror feature of ALL bodies about the component's XZ construction plane (y -> -y, new
    bodies), then a Remove feature per source body. Works for any body script (it acts on the result, not on how
    it was drawn) and stays parametric: changing a key dimension recomputes build -> mirror -> remove."""
    src = [comp.bRepBodies.item(i) for i in range(comp.bRepBodies.count)]
    coll = adsk.core.ObjectCollection.create()
    for b in src:
        coll.add(b)
    feats = comp.features
    mi = feats.mirrorFeatures.createInput(coll, comp.xZConstructionPlane)
    mi.isCombine = False
    mf = feats.mirrorFeatures.add(mi)
    mf.name = "agent mirror y"
    feature_bodies = mf.bodies.count                     # live (2705.1.30): 2 for one input body
    for i, b in enumerate(src):
        feats.removeFeatures.add(b).name = "agent mirror source %d" % (i + 1)
    if comp.bRepBodies.count != len(src):                # removed source bodies are no longer listed
        raise RuntimeError("mirror left %d bodies, expected %d" % (comp.bRepBodies.count, len(src)))
    return {"source_bodies": len(src), "bodies": comp.bRepBodies.count, "feature_bodies": feature_bodies}


def _measure(design, occ):
    comp = occ.component
    bodies, lo, hi = [], None, None
    for i in range(occ.bRepBodies.count):                # proxies: world coordinates
        b = occ.bRepBodies.item(i)
        bb = b.boundingBox
        bodies.append({"name": b.name, "solid": b.isSolid, "volume_mm3": round(b.volume * 1000.0, 6),
                       "lumps": b.lumps.count})
        mn, mx = _v(bb.minPoint), _v(bb.maxPoint)
        lo = mn if lo is None else [min(a, c) for a, c in zip(lo, mn)]
        hi = mx if hi is None else [max(a, c) for a, c in zip(hi, mx)]
    feats, n = [], 0
    tl = design.timeline
    for i in range(tl.count):
        item = tl.item(i)
        try:
            ent = item.entity
            pc = getattr(ent, "parentComponent", None)
        except Exception:
            continue
        if pc is None or pc.name != comp.name:
            continue
        n += 1
        h = _health(item.healthState)
        if h != "HEALTHY":
            feats.append({"name": item.name, "health": h, "message": (item.errorOrWarningMessage or "")[:160]})
    um, params = design.unitsManager, {}
    for i in range(design.userParameters.count):
        p = design.userParameters.item(i)
        if p.name.startswith(CFG["prefix"] + "_"):
            params[p.name[len(CFG["prefix"]) + 1:]] = round(um.convert(p.value, um.internalUnits, "mm"), 6)
    m = occ.transform2.asArray()
    return {"bodies": bodies, "bbox_world": [lo, hi] if lo else None, "features_total": n, "features_bad": feats,
            "params": params, "transform": [round(v * 10.0, 6) if k in (3, 7, 11) else v for k, v in enumerate(m)]}
'''
PRELUDE = PRELUDE.replace("# __PAINT_HELPERS__\n", PAINT_HELPERS.lstrip("\n"))

RUNNER = r'''

def _body_lines(tb):
    out = []
    for fr in traceback.extract_tb(tb):
        ln = fr.lineno - CFG["body_offset"]
        if ln >= 1:
            out.append(ln)
    return out


def run(_context):
    res = {"ok": False, "stage": "document", "part_id": CFG["part_id"], "depth": _depth()}
    try:
        app = adsk.core.Application.get()
        res["fusion_version"] = app.version
        design, created = _ensure_doc()
        res["created_document"] = created
        root = design.rootComponent
        res["stage"] = "prepare"
        stuck = _remove_previous(design, root)
        if stuck:
            res["error"] = "user parameters still in use elsewhere: %s" % stuck
            emit(res)
            return
        ensure_anchor(root)
        occ = begin_part(root, design)
    except Exception as e:
        res["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        emit(res)
        return
    res["stage"] = "body"
    try:
        build(Part(occ.component))
        if occ.component.bRepBodies.count == 0:
            raise RuntimeError("build(part) created no body")
    except Exception as e:
        tb = sys.exc_info()[2]
        res["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        res["body_lines"] = _body_lines(tb)[-3:]
        try:                                             # leave no partial part behind; end normally
            occ.deleteMe()
            _remove_params(design)
        except Exception:
            pass
        emit(res)
        return
    if CFG.get("mirror"):
        res["stage"] = "mirror"
        try:
            res["mirror"] = _mirror_y(occ.component)
        except Exception as e:
            res["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
            try:
                occ.deleteMe()
                _remove_params(design)
            except Exception:
                pass
            emit(res)
            return
    res["stage"] = "place"
    warnings = []
    try:
        try:                                             # frame check input (identity: before finish_part)
            res["bbox_local"] = _bbox_local(occ.component)
        except Exception as e:                           # reported as NOT_VERIFIED by PART-FRAME, never fatal
            warnings.append("local bbox not measured: %s" % str(e)[:120])
        res["placement"] = finish_part(design, occ, CFG["matrix_cm"])
        res["zones"] = _color(design, occ.component, CFG.get("paint") or {"color": [200, 200, 200]}, warnings)
        res["stage"] = "measure"
        res["measure"] = _measure(design, occ)
        res["ok"] = True
    except Exception as e:
        res["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    res["warnings"] = warnings
    res["document"] = app.activeDocument.name
    emit(res)
'''
