"""Read-only geometry inspection of one component in Fusion (authoritative CAD measurements).

Runs with readOnly=True (enforced by Fusion: the script cannot modify the design).
All values are converted to mm / mm² / mm³ inside the script; coordinates are world (= VCS).
"""
from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel

from fusion.client import RESULT_MARKER, FusionMCPClient, FusionOutputLost


class BodyReport(BaseModel):
    name: str
    is_solid: bool
    volume_mm3: float
    area_mm2: float
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    material: Optional[str] = None
    cylinders: list[dict]            # {"center": [x,y,z], "axis": [..], "radius": r, "concave": bool}
    # component-local measurements of the native body (None in reports written before they were added)
    bbox_local_min: Optional[tuple[float, float, float]] = None
    bbox_local_max: Optional[tuple[float, float, float]] = None
    vertices_local: Optional[list[list[float]]] = None
    vertices_world: Optional[list[list[float]]] = None


class GeometryReport(BaseModel):
    found: bool
    component_name: str
    document: Optional[str] = None
    fusion_version: Optional[str] = None            # Fusion build that ran this inspection
    build_fusion_version: Optional[str] = None      # Fusion build that ran the CAD build (from its result; set by the workflow)
    bodies: list[BodyReport] = []
    features: list[dict] = []        # {"name", "type", "health", "message"}
    sketches: list[dict] = []        # {"name", "fully_constrained", "profiles"}
    parameters: dict[str, dict] = {}  # name -> {"value_mm", "expression", "unit"}
    occurrence_transform: Optional[list[float]] = None   # row-major 4x4 local -> world, translation in mm
    pending_snapshot: Optional[bool] = None               # an uncaptured move would be lost on recompute

    @property
    def total_volume_mm3(self) -> float:
        return sum(b.volume_mm3 for b in self.bodies)


def build_inspect_script(component_name: str, param_prefix: str) -> str:
    cfg = json.dumps({"component_name": component_name, "prefix": param_prefix + "_", "marker": RESULT_MARKER})
    return _INSPECT_TEMPLATE.replace("__CFG__", cfg)


def inspect_component(client: FusionMCPClient, component_name: str, param_prefix: str) -> GeometryReport:
    result = client.run_script(build_inspect_script(component_name, param_prefix), read_only=True)
    if result.data is None:
        raise FusionOutputLost(f"Inspection script returned no result: {result.output[:300]}")
    return GeometryReport.model_validate(result.data)


_INSPECT_TEMPLATE = r'''
import json
import adsk.core, adsk.fusion

CFG = json.loads(r"""__CFG__""")


def v3(p, k=10.0):
    return [round(p.x * k, 6), round(p.y * k, 6), round(p.z * k, 6)]


def health_name(h):
    S = adsk.fusion.FeatureHealthStates
    return {S.HealthyFeatureHealthState: "HEALTHY", S.WarningFeatureHealthState: "WARNING",
            S.ErrorFeatureHealthState: "ERROR"}.get(h, "UNKNOWN")


def cylinders(body):
    out = []
    for i in range(body.faces.count):
        f = body.faces.item(i)
        g = f.geometry
        if g.surfaceType != adsk.core.SurfaceTypes.CylinderSurfaceType:
            continue
        # concave (hole or internal fillet): the face normal points toward the axis
        ok, n = f.evaluator.getNormalAtPoint(f.pointOnFace)
        p = f.pointOnFace
        to_axis = adsk.core.Vector3D.create(g.origin.x - p.x, g.origin.y - p.y, g.origin.z - p.z)
        ax = g.axis.copy(); ax.normalize()
        along = to_axis.dotProduct(ax)
        radial = adsk.core.Vector3D.create(to_axis.x - ax.x * along, to_axis.y - ax.y * along, to_axis.z - ax.z * along)
        concave = bool(ok and radial.dotProduct(n) > 0)
        out.append({"center": v3(g.origin), "axis": [round(ax.x, 9), round(ax.y, 9), round(ax.z, 9)],
                    "radius": round(g.radius * 10.0, 6), "concave": concave})
    return out


def run(_context: str):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    rep = {"found": False, "component_name": CFG["component_name"], "fusion_version": app.version,
           "document": app.activeDocument.name if app.activeDocument else None}
    occ = None
    if design:
        for i in range(design.rootComponent.occurrences.count):
            o = design.rootComponent.occurrences.item(i)
            if o.component.name == CFG["component_name"]:
                occ = o
                break
    if occ is None:
        print(CFG["marker"] + json.dumps(rep))
        return
    rep["found"] = True
    comp = occ.component
    acc = adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy
    bodies = []
    for i in range(occ.bRepBodies.count):        # proxies -> world coordinates
        b = occ.bRepBodies.item(i)
        nb = b.nativeObject                      # same body in the component's own frame
        pp = b.getPhysicalProperties(acc)
        bb, lb = b.boundingBox, nb.boundingBox
        bodies.append({"name": b.name, "is_solid": b.isSolid, "volume_mm3": pp.volume * 1000.0,
                       "area_mm2": pp.area * 100.0, "bbox_min": v3(bb.minPoint), "bbox_max": v3(bb.maxPoint),
                       "material": b.material.name if b.material else None, "cylinders": cylinders(b),
                       "bbox_local_min": v3(lb.minPoint), "bbox_local_max": v3(lb.maxPoint),
                       "vertices_local": [v3(v.geometry) for v in nb.vertices],
                       "vertices_world": [v3(v.geometry) for v in b.vertices]})
    rep["bodies"] = bodies
    m = occ.transform2.asArray()                 # root-level occurrence: relative to the root = world
    rep["occurrence_transform"] = [round(v * 10.0, 6) if k in (3, 7, 11) else v for k, v in enumerate(m)]
    if design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        rep["pending_snapshot"] = design.snapshots.hasPendingSnapshot
    feats = []
    tl = design.timeline if design.designType == adsk.fusion.DesignTypes.ParametricDesignType else None
    if tl:
        for i in range(tl.count):
            item = tl.item(i)
            ent = item.entity
            pc = getattr(ent, "parentComponent", None)
            if pc is None or pc.name != comp.name:
                continue
            feats.append({"name": item.name, "type": ent.objectType.split("::")[-1],
                          "health": health_name(item.healthState), "message": item.errorOrWarningMessage or ""})
    rep["features"] = feats
    rep["sketches"] = [{"name": s.name, "fully_constrained": s.isFullyConstrained, "profiles": s.profiles.count}
                       for s in [comp.sketches.item(i) for i in range(comp.sketches.count)]]
    um = design.unitsManager
    params = {}
    for i in range(design.userParameters.count):
        p = design.userParameters.item(i)
        if p.name.startswith(CFG["prefix"]):
            params[p.name] = {"value_mm": round(um.convert(p.value, um.internalUnits, "mm"), 6),
                              "expression": p.expression, "unit": p.unit}
    rep["parameters"] = params
    print(CFG["marker"] + json.dumps(rep))
'''
