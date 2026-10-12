"""Generator: machined L-bracket (Prototype 1; v2 adds an optional separate upright thickness).

Deterministic: design inputs -> (feasibility errors, DFM quantities, expected geometry,
interfaces, Fusion script). The Fusion script builds a fully parametric, named model.

Local component frame (documented, mm), t_b = bracket_thickness, t_u = upright_thickness (= t_b if not given):
    origin  = outer corner of the L, on the bracket's mid-width plane
    base leg   : x in [0, leg_base_length], z in [0, t_b]                (bottom face z=0 mounts down)
    upright leg: x in [0, t_u],             z in [0, leg_upright_height] (outer face x=0 mounts the payload)
    width      : y in [-bracket_width/2, +bracket_width/2]
Bend: inner fillet bend_inner_radius at (x=t_u, z=t_b); outer fillet = inner + max(t_b, t_u), so the wall at the
bend is never thinner than min(t_b, t_u) (v1, t_u = t_b: constant section).
Holes: rows x cols grid per leg, columns symmetric about y=0.
"""
from __future__ import annotations

import json
import math
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from fusion.client import RESULT_MARKER

GENERATOR_ID = "l_bracket"
GENERATOR_VERSION = "3"       # 3: empty identity anchor occurrence + placement read-back (geometry unchanged)
ID_PREFIX = "BRK"
PROCESSES = ["machined"]

# Information the analysis stage must cover (as a requirement or as a missing-info item).
REQUIRED_INFO = {
    "function": "What the bracket connects/supports and how it is oriented",
    "material": "Bracket material",
    "manufacturing_process": "How the bracket is made (this generator supports: machined)",
    "base_fastener": "Fastener size and count through the base leg",
    "upright_fastener": "Fastener size and count through the upright leg",
    "load": "Load case: supported mass or force, direction, dynamic/safety factor",
    "envelope": "Available space / size limits for the bracket",
}

# Fusion user parameters (length, mm). Counts are topology inputs, not Fusion parameters.
LENGTH_PARAMS = {
    "leg_base_length": "Base leg length along local X (mm)",
    "leg_upright_height": "Upright leg height along local Z (mm)",
    "bracket_width": "Bracket width along local Y (mm)",
    "bracket_thickness": "Base leg plate thickness along local Z (mm); also the upright thickness unless upright_thickness is given",
    "upright_thickness": "Upright leg plate thickness along local X (mm); OPTIONAL - omit it to use bracket_thickness",
    "bend_inner_radius": "Internal bend fillet radius (mm); outer = inner + thickness",
    "base_hole_diameter": "Base leg clearance hole diameter (mm)",
    "base_hole_x0": "Distance from upright outer face (x=0) to first base hole row (mm)",
    "base_hole_pitch_x": "Row pitch of base holes along X (mm); ignored if 1 row",
    "base_hole_pitch_y": "Column pitch of base holes along Y (mm); ignored if 1 column",
    "upright_hole_diameter": "Upright leg clearance hole diameter (mm)",
    "upright_hole_z0": "Height from base bottom face (z=0) to first upright hole row (mm)",
    "upright_hole_pitch_z": "Row pitch of upright holes along Z (mm); ignored if 1 row",
    "upright_hole_pitch_y": "Column pitch of upright holes along Y (mm); ignored if 1 column",
}
# Length parameters a plan may omit (v1 plans/records have none of them). In Fusion they always exist:
# an omitted one is created as an expression linked to the parameter it defaults to.
OPTIONAL_PARAMS = {"upright_thickness": "bracket_thickness"}
COUNT_PARAMS = {
    "base_hole_rows": "Rows of base holes along X (1 or 2)",
    "base_hole_cols": "Columns of base holes along Y (1 or 2)",
    "upright_hole_rows": "Rows of upright holes along Z (1 or 2)",
    "upright_hole_cols": "Columns of upright holes along Y (1 or 2)",
}


class BracketInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    leg_base_length: float = Field(gt=0)
    leg_upright_height: float = Field(gt=0)
    bracket_width: float = Field(gt=0)
    bracket_thickness: float = Field(gt=0)
    bend_inner_radius: float = Field(ge=0)
    base_hole_diameter: float = Field(gt=0)
    base_hole_x0: float = Field(gt=0)
    base_hole_pitch_x: float = Field(ge=0)
    base_hole_pitch_y: float = Field(ge=0)
    upright_hole_diameter: float = Field(gt=0)
    upright_hole_z0: float = Field(gt=0)
    upright_hole_pitch_z: float = Field(ge=0)
    upright_hole_pitch_y: float = Field(ge=0)
    upright_thickness: Optional[float] = Field(default=None, gt=0)
    base_hole_rows: Literal[1, 2]
    base_hole_cols: Literal[1, 2]
    upright_hole_rows: Literal[1, 2]
    upright_hole_cols: Literal[1, 2]
    base_fastener: str
    upright_fastener: str

    @classmethod
    def from_values(cls, values: dict, fasteners: dict) -> "BracketInputs":
        data = {k: values[k] for k in list(LENGTH_PARAMS) if k in values}
        data.update({k: int(values[k]) for k in COUNT_PARAMS if k in values})
        data["base_fastener"] = fasteners.get("base_fastener", "")
        data["upright_fastener"] = fasteners.get("upright_fastener", "")
        return cls.model_validate(data)

    @property
    def upright_t(self) -> float:
        """Effective upright thickness (v1 behaviour: equal to bracket_thickness)."""
        return self.bracket_thickness if self.upright_thickness is None else self.upright_thickness

    @property
    def outer_radius(self) -> float:
        return self.bend_inner_radius + max(self.bracket_thickness, self.upright_t)

    def length_value(self, name: str) -> float:
        """Value of a LENGTH_PARAMS entry, with optional parameters resolved to their effective value."""
        return self.upright_t if name == "upright_thickness" else float(getattr(self, name))


# --------------------------------------------------------------------------
# Hole layout
# --------------------------------------------------------------------------
def _cols(n: int, pitch: float) -> list[float]:
    return [0.0] if n == 1 else [-pitch / 2.0, pitch / 2.0]


def base_holes(p: BracketInputs) -> list[dict]:
    xs = [p.base_hole_x0 + i * p.base_hole_pitch_x for i in range(p.base_hole_rows)]
    return [{"id": f"HB{i + 1}{j + 1}", "x": x, "y": y, "d": p.base_hole_diameter}
            for i, x in enumerate(xs) for j, y in enumerate(_cols(p.base_hole_cols, p.base_hole_pitch_y))]


def upright_holes(p: BracketInputs) -> list[dict]:
    zs = [p.upright_hole_z0 + i * p.upright_hole_pitch_z for i in range(p.upright_hole_rows)]
    return [{"id": f"HU{i + 1}{j + 1}", "z": z, "y": y, "d": p.upright_hole_diameter}
            for i, z in enumerate(zs) for j, y in enumerate(_cols(p.upright_hole_cols, p.upright_hole_pitch_y))]


# --------------------------------------------------------------------------
# Feasibility (geometric validity - independent of DFM rules)
# --------------------------------------------------------------------------
def feasibility_errors(p: BracketInputs) -> list[str]:
    e: list[str] = []
    tb, tu, ri, w = p.bracket_thickness, p.upright_t, p.bend_inner_radius, p.bracket_width
    base_flat_start = tu + ri                # where the flat part of the base leg begins (along X)
    upright_flat_start = tb + ri             # where the flat part of the upright leg begins (along Z)
    if tb >= min(p.leg_base_length, p.leg_upright_height):
        e.append("bracket_thickness must be smaller than both leg lengths")
    if p.upright_thickness is not None and tu >= min(p.leg_base_length, p.leg_upright_height):
        e.append("upright_thickness must be smaller than both leg lengths")
    if p.outer_radius >= min(p.leg_base_length, p.leg_upright_height):
        e.append("outer bend radius (inner + thickness) must be smaller than both leg lengths")
    for name, rows, cols, pitch_a, pitch_y, d in (
            ("base", p.base_hole_rows, p.base_hole_cols, p.base_hole_pitch_x, p.base_hole_pitch_y, p.base_hole_diameter),
            ("upright", p.upright_hole_rows, p.upright_hole_cols, p.upright_hole_pitch_z, p.upright_hole_pitch_y, p.upright_hole_diameter)):
        if rows == 2 and pitch_a <= d:
            e.append(f"{name} hole row pitch must exceed the hole diameter")
        if cols == 2 and pitch_y <= d:
            e.append(f"{name} hole column pitch must exceed the hole diameter")
    for h in base_holes(p):
        if h["x"] - h["d"] / 2 < base_flat_start:
            e.append(f"base hole {h['id']} cuts into the bend/upright region (x_min {h['x'] - h['d'] / 2:.2f} < {base_flat_start:.2f})")
        if h["x"] + h["d"] / 2 > p.leg_base_length:
            e.append(f"base hole {h['id']} exceeds the base leg end")
        if abs(h["y"]) + h["d"] / 2 > w / 2:
            e.append(f"base hole {h['id']} exceeds the bracket width")
    for h in upright_holes(p):
        if h["z"] - h["d"] / 2 < upright_flat_start:
            e.append(f"upright hole {h['id']} cuts into the bend/base region (z_min {h['z'] - h['d'] / 2:.2f} < {upright_flat_start:.2f})")
        if h["z"] + h["d"] / 2 > p.leg_upright_height:
            e.append(f"upright hole {h['id']} exceeds the upright leg top")
        if abs(h["y"]) + h["d"] / 2 > w / 2:
            e.append(f"upright hole {h['id']} exceeds the bracket width")
    return e


# --------------------------------------------------------------------------
# Deterministic engineering quantities
# --------------------------------------------------------------------------
def dfm_quantities(p: BracketInputs) -> dict:
    ratios = []
    for h in base_holes(p):     # free edges: base end (x=L) and the two sides
        ratios.append(min(p.leg_base_length - h["x"], p.bracket_width / 2 - abs(h["y"])) / h["d"])
    for h in upright_holes(p):  # free edges: upright top (z=H) and the two sides
        ratios.append(min(p.leg_upright_height - h["z"], p.bracket_width / 2 - abs(h["y"])) / h["d"])
    return {
        "wall_thickness": min(p.bracket_thickness, p.upright_t),
        "internal_corner_radius": p.bend_inner_radius,
        "fillet_to_thickness_ratio": p.bend_inner_radius / max(p.bracket_thickness, p.upright_t),
        "clearance_holes": [{"item": p.base_fastener, "value": p.base_hole_diameter},
                            {"item": p.upright_fastener, "value": p.upright_hole_diameter}],
        "hole_edge_distance_ratio": min(ratios) if ratios else None,
    }


def expected_volume_mm3(p: BracketInputs) -> float:
    tb, tu, ri, ro = p.bracket_thickness, p.upright_t, p.bend_inner_radius, p.outer_radius
    k = 1.0 - math.pi / 4.0           # area between a square corner and its quarter-circle fillet
    area = p.leg_base_length * tb + (p.leg_upright_height - tb) * tu + (ri * ri - ro * ro) * k
    hole_area_vol = (sum(math.pi * h["d"] ** 2 / 4.0 * tb for h in base_holes(p))
                     + sum(math.pi * h["d"] ** 2 / 4.0 * tu for h in upright_holes(p)))
    return area * p.bracket_width - hole_area_vol


def expected_bbox_local(p: BracketInputs) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    w2 = p.bracket_width / 2.0
    return (0.0, -w2, 0.0), (p.leg_base_length, w2, p.leg_upright_height)


def expected_holes_local(p: BracketInputs) -> list[dict]:
    """Expected cylindrical hole features: centre on the leg mid-plane, axis, diameter (local frame)."""
    tb, tu = p.bracket_thickness, p.upright_t
    holes = [{"id": h["id"], "center": (h["x"], h["y"], tb / 2), "axis": (0.0, 0.0, 1.0), "diameter": h["d"]}
             for h in base_holes(p)]
    holes += [{"id": h["id"], "center": (tu / 2, h["y"], h["z"]), "axis": (1.0, 0.0, 0.0), "diameter": h["d"]}
              for h in upright_holes(p)]
    return holes


def interfaces(p: BracketInputs, base_mates: str | None, upright_mates: str | None) -> list[dict]:
    return [
        {"id": "IF-BASE", "name": "Base mounting face", "type": "BOLTED", "mates_with": base_mates,
         "origin": (p.leg_base_length / 2, 0.0, 0.0), "normal": (0.0, 0.0, -1.0),
         "mounting_points": [{"id": h["id"], "position": (h["x"], h["y"], 0.0), "axis": (0.0, 0.0, 1.0),
                              "hole_diameter": h["d"], "fastener": p.base_fastener} for h in base_holes(p)]},
        {"id": "IF-UPRIGHT", "name": "Upright mounting face", "type": "BOLTED", "mates_with": upright_mates,
         "origin": (0.0, 0.0, p.leg_upright_height / 2), "normal": (-1.0, 0.0, 0.0),
         "mounting_points": [{"id": h["id"], "position": (0.0, h["y"], h["z"]), "axis": (1.0, 0.0, 0.0),
                              "hole_diameter": h["d"], "fastener": p.upright_fastener} for h in upright_holes(p)]},
    ]


def structural_section(p: BracketInputs) -> dict:
    """Critical section for the payload-on-upright load case (plate bending, constant moment M = F*e):
    net section of the upright through its hole row(s)."""
    return {"width": p.bracket_width - p.upright_hole_cols * p.upright_hole_diameter,
            "thickness": p.upright_t,
            "note": ("Upright leg as a plate under constant moment M = F*e (payload weight F at CG offset e from "
                     "the upright face); critical net section through the upright hole row "
                     f"(W - {p.upright_hole_cols} x hole).")}


def fusion_parameters(component_id: str, p: BracketInputs, namespace: str = "") -> dict[str, float]:
    """Fusion user parameters (mm) this generator creates, with their expected values."""
    pre = param_prefix(component_id, namespace)
    out = {f"{pre}_{k}": p.length_value(k) for k in LENGTH_PARAMS}
    out[f"{pre}_bend_outer_radius"] = p.outer_radius
    return out


# --------------------------------------------------------------------------
# Fusion script
# --------------------------------------------------------------------------
# Fusion names live in ONE namespace per Fusion document, while component ids are unique per project.
# Projects therefore carry a `fusion_namespace` (empty for the original prototype_bench, so BRK-001/002 keep
# their names) that prefixes every Fusion component and parameter name.
def param_prefix(component_id: str, namespace: str = "") -> str:
    base = component_id.lower().replace("-", "")          # BRK-001 -> brk001
    return f"{namespace}_{base}" if namespace else base


def component_key(component_id: str, namespace: str = "") -> str:
    """Leading part of the Fusion component name that identifies this component regardless of its title."""
    return f"{namespace} {component_id} " if namespace else f"{component_id} "


def fusion_component_name(component_id: str, name: str, namespace: str = "") -> str:
    return f"{component_key(component_id, namespace)}{name}"


# Empty identity occurrence kept as the FIRST root occurrence of every design the agent builds in. Verified live
# (Fusion 2705.1.11 and 2705.1.30): occurrence.transform2 on the ONLY root occurrence is silently ignored (the part
# stays at identity, no error); with another root occurrence present it is applied exactly. Shared by all projects
# in a document; never matches a component key ("<namespace> <ID> "), so remove_previous never deletes it.
ANCHOR_NAME = "VCS origin"


def build_script(component_id: str, name: str, p: BracketInputs, transform: list[float],
                 fusion_material: str | None = None, namespace: str = "", anchor: bool = True) -> str:
    """anchor=False only for live tests of the Fusion behaviour (canary / fail-loud path)."""
    cfg = {
        "component_name": fusion_component_name(component_id, name, namespace),
        "component_key": component_key(component_id, namespace),
        "body_name": f"{component_id}_body",
        "prefix": param_prefix(component_id, namespace),
        "params": [[k, p.length_value(k), LENGTH_PARAMS[k]] for k in LENGTH_PARAMS],
        # omitted optional parameters are created in Fusion as expressions linked to their default parameter
        "linked": {k: dflt for k, dflt in OPTIONAL_PARAMS.items() if getattr(p, k) is None},
        "optional": list(OPTIONAL_PARAMS),
        "upright_t": p.upright_t,
        "base_holes": {"rows": p.base_hole_rows, "cols": p.base_hole_cols},
        "upright_holes": {"rows": p.upright_hole_rows, "cols": p.upright_hole_cols},
        "values": p.model_dump(),
        "transform": transform,
        "anchor_name": ANCHOR_NAME if anchor else None,
        "fusion_material": fusion_material,
        "marker": RESULT_MARKER,
    }
    return _SCRIPT_TEMPLATE.replace("__CFG__", json.dumps(cfg))


_SCRIPT_TEMPLATE = r'''
import json
import adsk.core, adsk.fusion

CFG = json.loads(r"""__CFG__""")
P = CFG["prefix"]
V = CFG["values"]
OPTIONAL = CFG["optional"]
TOL = 1e-6


def pname(n):
    return P + "_" + n


def pt(x, y, z):
    # local mm -> Fusion cm
    return adsk.core.Point3D.create(x / 10.0, y / 10.0, z / 10.0)


def to_sketch(sk, x, y, z):
    return sk.modelToSketchSpace(pt(x, y, z))


def sketch_orientation(sk, axis):
    """Dimension orientation in sketch space that measures along a local model axis."""
    a = sk.modelToSketchSpace(pt(0, 0, 0))
    b = sk.modelToSketchSpace(pt(*[10.0 * c for c in axis]))
    D = adsk.fusion.DimensionOrientations
    return D.HorizontalDimensionOrientation if abs(b.x - a.x) > abs(b.y - a.y) else D.VerticalDimensionOrientation


def dim(sk, p1, p2, orientation, expr, text_at):
    d = sk.sketchDimensions.addDistanceDimension(p1, p2, orientation, text_at)
    d.parameter.expression = expr
    return d


def ensure_anchor(root):
    # Fusion ignores transform2 on the only root occurrence; keep an empty identity anchor occurrence first
    if not CFG["anchor_name"]:
        return
    for i in range(root.occurrences.count):
        if root.occurrences.item(i).component.name == CFG["anchor_name"]:
            return
    root.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component.name = CFG["anchor_name"]


def remove_previous(design, root):
    # an earlier build of THIS component (same project namespace + id), whatever its title was
    for i in range(root.occurrences.count - 1, -1, -1):
        occ = root.occurrences.item(i)
        if occ.component.name.startswith(CFG["component_key"]):
            occ.deleteMe()
    remove_params(design)


def remove_params(design):
    ups = design.userParameters
    names = [ups.item(i).name for i in range(ups.count)]
    # dependent parameters first: the derived outer radius, then linked optional ones, then the base ones
    linked = tuple("_" + k for k in OPTIONAL)
    for n in sorted([n for n in names if n.startswith(P + "_")],
                    key=lambda n: 0 if n.endswith("outer_radius") else 1 if n.endswith(linked) else 2):
        prm = ups.itemByName(n)
        if prm and not prm.deleteMe():
            raise RuntimeError("user parameter %s is still used by other geometry in this document; "
                               "refusing to overwrite it (Fusion name collision)" % n)


def create_params(design):
    ups = design.userParameters
    for n, value, comment in CFG["params"]:      # linked parameters come after the ones they reference
        expr = pname(CFG["linked"][n]) if n in CFG["linked"] else "%r mm" % value
        ups.add(pname(n), adsk.core.ValueInput.createByString(expr), "mm", comment)
    ups.add(pname("bend_outer_radius"),
            adsk.core.ValueInput.createByString(pname("bend_inner_radius") + " + max(" + pname("bracket_thickness")
                                                + "; " + pname("upright_thickness") + ")"),
            "mm", "Outer bend radius = inner radius + max(base, upright thickness): wall at the bend >= the thinner leg")


def l_profile(comp):
    sk = comp.sketches.add(comp.xZConstructionPlane)
    sk.name = "SK_L_profile"
    L, H, t, tu = V["leg_base_length"], V["leg_upright_height"], V["bracket_thickness"], CFG["upright_t"]
    pts = [(0, 0), (L, 0), (L, t), (tu, t), (tu, H), (0, H)]          # (x, z) local; t = base, tu = upright
    lines = sk.sketchCurves.sketchLines
    segs = []
    first = to_sketch(sk, 0, 0, 0)
    prev = first
    for i in range(6):
        nx, nz = pts[(i + 1) % 6]
        end = segs[0].startSketchPoint if i == 5 else to_sketch(sk, nx, 0, nz)
        start = segs[-1].endSketchPoint if segs else prev
        segs.append(lines.addByTwoPoints(start, end))
    gc = sk.geometricConstraints
    gc.addCoincident(segs[0].startSketchPoint, sk.originPoint)
    for ln in segs:
        s, e = ln.startSketchPoint.geometry, ln.endSketchPoint.geometry
        if abs(e.x - s.x) > abs(e.y - s.y):
            gc.addHorizontal(ln)
        else:
            gc.addVertical(ln)
    ox = sketch_orientation(sk, (1, 0, 0))
    oz = sketch_orientation(sk, (0, 0, 1))
    tp = lambda x, z: to_sketch(sk, x, 0, z)
    dim(sk, segs[0].startSketchPoint, segs[0].endSketchPoint, ox, pname("leg_base_length"), tp(L / 2, -12))
    dim(sk, segs[1].startSketchPoint, segs[1].endSketchPoint, oz, pname("bracket_thickness"), tp(L + 10, t / 2))
    dim(sk, segs[4].startSketchPoint, segs[4].endSketchPoint, ox, pname("upright_thickness"), tp(tu / 2, H + 10))
    dim(sk, segs[5].startSketchPoint, segs[5].endSketchPoint, oz, pname("leg_upright_height"), tp(-12, H / 2))
    return sk


def find_bend_edge(body, x, z):
    for i in range(body.edges.count):
        e = body.edges.item(i)
        a, b = e.startVertex.geometry, e.endVertex.geometry
        if (abs(a.x - x) < TOL and abs(b.x - x) < TOL and abs(a.z - z) < TOL and abs(b.z - z) < TOL
                and abs(a.y - b.y) > TOL):
            return e
    raise RuntimeError("Bend edge at x=%g z=%g cm not found" % (x, z))


def fillet(comp, body, x_cm, z_cm, expr, name):
    edges = adsk.core.ObjectCollection.create()
    body = comp.bRepBodies.itemByName(CFG["body_name"])
    edges.add(find_bend_edge(body, x_cm, z_cm))
    fi = comp.features.filletFeatures.createInput()
    fi.edgeSetInputs.addConstantRadiusEdgeSet(edges, adsk.core.ValueInput.createByString(expr), True)
    f = comp.features.filletFeatures.add(fi)
    f.name = name
    return f


def same_coord(gc, p1, p2, orientation):
    """Constrain two sketch points to share the coordinate that `orientation` measures."""
    if orientation == adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation:
        gc.addVerticalPoints(p1, p2)        # same sketch x
    else:
        gc.addHorizontalPoints(p1, p2)      # same sketch y


def hole_sketch(comp, plane, name, holes, axis_a, diam_key, a0_key, pitch_a_key, pitch_y_key):
    """holes: (row i, col j, a, y, d) in mm; a is measured along local axis_a from the origin.

    Chained design intent: hole (0,0) is dimensioned from the origin, the others by pitch from
    their neighbour plus alignment constraints (Fusion rejects two parallel dimensions from the
    origin to points that share a coordinate).
    """
    sk = comp.sketches.add(plane)
    sk.name = name
    oa = sketch_orientation(sk, axis_a)
    oy = sketch_orientation(sk, (0, 1, 0))
    gc = sk.geometricConstraints
    ia = axis_a.index(1)
    centers = {}
    for (i, j, a, y, d) in holes:
        c3 = [0.0, y, 0.0]
        c3[ia] = a
        circle = sk.sketchCurves.sketchCircles.addByCenterRadius(to_sketch(sk, *c3), d / 20.0)
        cp = circle.centerSketchPoint
        centers[(i, j)] = cp
        t3 = list(c3); t3[1] = y + d
        sk.sketchDimensions.addDiameterDimension(circle, to_sketch(sk, *t3)).parameter.expression = pname(diam_key)
        ta = list(c3); ta[1] = y - 1.5 * d
        ty = list(c3); ty[ia] = a + 1.5 * d
        # coordinate along the leg (a)
        if i == 0 and j == 0:
            dim(sk, sk.originPoint, cp, oa, pname(a0_key), to_sketch(sk, *ta))
        elif i == 0:
            same_coord(gc, centers[(0, 0)], cp, oa)
        else:
            dim(sk, centers[(0, j)], cp, oa, pname(pitch_a_key), to_sketch(sk, *ta))
        # coordinate across the width (y)
        if i > 0:
            same_coord(gc, centers[(0, j)], cp, oy)
        elif j == 0 and y == 0:
            same_coord(gc, sk.originPoint, cp, oy)
        elif j == 0:
            dim(sk, sk.originPoint, cp, oy, pname(pitch_y_key) + " / 2", to_sketch(sk, *ty))
        else:
            dim(sk, centers[(0, 0)], cp, oy, pname(pitch_y_key), to_sketch(sk, *ty))
    return sk


def cut_holes(comp, sk, body, name):
    profs = adsk.core.ObjectCollection.create()
    for i in range(sk.profiles.count):
        profs.add(sk.profiles.item(i))
    ext = comp.features.extrudeFeatures
    ei = ext.createInput(profs, adsk.fusion.FeatureOperations.CutFeatureOperation)
    ei.setTwoSidesExtent(adsk.fusion.ThroughAllExtentDefinition.create(),
                         adsk.fusion.ThroughAllExtentDefinition.create())
    ei.participantBodies = [comp.bRepBodies.itemByName(CFG["body_name"])]
    f = ext.add(ei)
    f.name = name
    return f


def grid(rows, cols, a0, pa, py, d):
    ys = [0.0] if cols == 1 else [-py / 2.0, py / 2.0]
    return [(i, j, a0 + i * pa, y, d) for i in range(rows) for j, y in enumerate(ys)]


def apply_material(design, body, warnings):
    want = CFG["fusion_material"]
    if not want:
        return None
    app = adsk.core.Application.get()
    for li in range(app.materialLibraries.count):
        lib = app.materialLibraries.item(li)
        m = lib.materials.itemByName(want)
        if m:
            body.material = m
            return m.name
    warnings.append("Fusion material '%s' not found; body keeps default material" % want)
    return None


def build(design, comp):
    warnings = []
    sk = l_profile(comp)
    if sk.profiles.count != 1:
        raise RuntimeError("L profile sketch has %d profiles, expected 1" % sk.profiles.count)
    ext = comp.features.extrudeFeatures
    ei = ext.createInput(sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ei.setSymmetricExtent(adsk.core.ValueInput.createByString(pname("bracket_width")), True)
    ex = ext.add(ei)
    ex.name = "EX_L_profile"
    body = ex.bodies.item(0)
    body.name = CFG["body_name"]
    t, tu = V["bracket_thickness"] / 10.0, CFG["upright_t"] / 10.0
    if V["bend_inner_radius"] > 0:
        fillet(comp, body, tu, t, pname("bend_inner_radius"), "FL_bend_inner")   # inner corner at (x=tu, z=t)
        fillet(comp, body, 0.0, 0.0, pname("bend_outer_radius"), "FL_bend_outer")
    bh = CFG["base_holes"]
    sk_b = hole_sketch(comp, comp.xYConstructionPlane, "SK_base_holes",
                       grid(bh["rows"], bh["cols"], V["base_hole_x0"], V["base_hole_pitch_x"], V["base_hole_pitch_y"], V["base_hole_diameter"]),
                       (1, 0, 0), "base_hole_diameter", "base_hole_x0", "base_hole_pitch_x", "base_hole_pitch_y")
    cut_holes(comp, sk_b, body, "CUT_base_holes")
    uh = CFG["upright_holes"]
    sk_u = hole_sketch(comp, comp.yZConstructionPlane, "SK_upright_holes",
                       grid(uh["rows"], uh["cols"], V["upright_hole_z0"], V["upright_hole_pitch_z"], V["upright_hole_pitch_y"], V["upright_hole_diameter"]),
                       (0, 0, 1), "upright_hole_diameter", "upright_hole_z0", "upright_hole_pitch_z", "upright_hole_pitch_y")
    cut_holes(comp, sk_u, body, "CUT_upright_holes")
    body = comp.bRepBodies.itemByName(CFG["body_name"])
    material = apply_material(design, body, warnings)
    return body, material, warnings


def run(_context: str):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    created_doc = False
    if design is None:
        app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        created_doc = True
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    root = design.rootComponent
    remove_previous(design, root)
    ensure_anchor(root)
    create_params(design)
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = CFG["component_name"]
    try:
        body, material, warnings = build(design, comp)
        m = adsk.core.Matrix3D.create()
        m.setWithArray(CFG["transform"])
        if not m.isEqualTo(adsk.core.Matrix3D.create()):
            occ.transform2 = m
            design.snapshots.add()
            if not occ.transform2.isEqualTo(m):     # fail loud: Fusion can ignore transform2 without an error
                raise RuntimeError("Fusion did not apply the placement (transform2 read-back differs)")
    except Exception:
        # leave no partial component behind; re-raise so the caller sees the real error
        occ.deleteMe()
        remove_params(design)
        raise
    print(CFG["marker"] + json.dumps({
        "component_name": comp.name,
        "body_name": body.name,
        "document": app.activeDocument.name,
        "created_document": created_doc,
        "fusion_version": app.version,
        "material": material,
        "warnings": warnings,
    }))
'''
