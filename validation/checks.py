"""Deterministic validation: compare what Fusion measured with what the record says should exist.

Every function returns ValidationResult records; nothing here talks to Fusion or to an AI.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from fusion.inspect import GeometryReport
from vehicle.models import Pose, Severity, Status, ValidationResult
from vehicle.transforms import bbox_to_vcs, pose_to_matrix, transform_point, transform_vector

LENGTH_TOL_MM = 1e-3          # geometric position / size tolerance
VOLUME_REL_TOL = 1e-4         # 0.01 % against the analytic volume
ANGLE_TOL_DEG = 1e-4          # placement rotation tolerance (geodesic angle)


@dataclass
class ExpectedGeometry:
    bbox_local: tuple[tuple[float, float, float], tuple[float, float, float]]
    volume_mm3: float
    holes_local: list[dict]                      # {"id", "center", "axis", "diameter"}
    parameters: dict[str, float]                 # Fusion user parameter name -> value [mm]
    body_count: int = 1
    pose: Pose = field(default_factory=Pose)


def _r(check_id, title, category, scope, claim, passed, method="FUSION_MEASUREMENT", severity=Severity.BLOCKING, **kw):
    return ValidationResult(check_id=check_id, title=title, category=category, scope=scope, claim=claim,
                            severity=severity, method=method,
                            status=Status.VERIFIED if passed else Status.NON_COMPLIANT, **kw)


def cad_build_result(ok: bool, message: str = "") -> ValidationResult:
    return _r("PROC-CAD-BUILD", "Fusion CAD build completed", "PROCESS", "CAD_BUILD",
              "The generated Fusion script ran to completion without error.", ok, message=message)


def geometry_checks(rep: GeometryReport, exp: ExpectedGeometry) -> list[ValidationResult]:
    out: list[ValidationResult] = []
    if not rep.found:
        return [ValidationResult(check_id="GEO-FOUND", title="Component exists in Fusion", category="GEOMETRY",
                                 scope="GEOMETRY", claim="The component exists in the active Fusion design.",
                                 status=Status.NON_COMPLIANT, method="FUSION_MEASUREMENT",
                                 message=f"Component '{rep.component_name}' not found in the active design")]

    solids = [b for b in rep.bodies if b.is_solid]
    out.append(_r("GEO-BODY-COUNT", "Expected number of solid bodies", "GEOMETRY", "GEOMETRY",
                  "Fusion reports the designed number of bodies, all solid.",
                  len(solids) == exp.body_count and len(rep.bodies) == exp.body_count,
                  measured=len(rep.bodies), limit=exp.body_count))

    bad = [f for f in rep.features if f["health"] != "HEALTHY"]
    out.append(_r("GEO-FEATURE-HEALTH", "All timeline features healthy", "GEOMETRY", "GEOMETRY",
                  "Every Fusion timeline feature of the component computed without warning or error.", not bad and bool(rep.features),
                  measured=f"{len(rep.features) - len(bad)}/{len(rep.features)} healthy",
                  message="; ".join(f"{f['name']}: {f['health']} {f['message']}" for f in bad)))

    loose = [s["name"] for s in rep.sketches if not s["fully_constrained"]]
    out.append(_r("GEO-SKETCH-CONSTRAINED", "All sketches fully constrained", "GEOMETRY", "GEOMETRY",
                  "Every sketch is fully constrained (geometry fully driven by dimensions/constraints).", not loose,
                  severity=Severity.ADVISORY, measured=f"{len(rep.sketches) - len(loose)}/{len(rep.sketches)}",
                  message=", ".join(loose)))

    if solids:
        if all(b.bbox_local_min is not None for b in solids):
            # extents in the component's own frame: exact for any placement. (A world axis-aligned box of a rotated,
            # non-box-shaped part is not the rotated design box, so comparing in VCS gives false failures.)
            # Placement itself is verified by GEO-PLACEMENT.
            lo = np.min([b.bbox_local_min for b in solids], axis=0)
            hi = np.max([b.bbox_local_max for b in solids], axis=0)
            elo, ehi = exp.bbox_local
            title, claim = ("Bounding box matches design (component frame)",
                            "Fusion-measured overall extents in the component's own frame equal the designed "
                            "extents (overall size only; independent of placement).")
        else:   # legacy report without local measurements: world box, exact only for an identity pose
            lo = np.min([b.bbox_min for b in solids], axis=0)
            hi = np.max([b.bbox_max for b in solids], axis=0)
            elo, ehi = bbox_to_vcs(exp.pose, *exp.bbox_local)
            title, claim = ("Bounding box matches design (VCS)",
                            "Fusion-measured overall extents equal the designed extents (overall size only).")
        dev = float(max(np.max(np.abs(lo - np.array(elo))), np.max(np.abs(hi - np.array(ehi)))))
        out.append(_r("GEO-BBOX", title, "GEOMETRY", "GEOMETRY", claim,
                      dev <= LENGTH_TOL_MM,
                      measured={"min": [round(v, 4) for v in lo], "max": [round(v, 4) for v in hi]},
                      limit={"min": [round(v, 4) for v in elo], "max": [round(v, 4) for v in ehi],
                             "tol_mm": LENGTH_TOL_MM}, unit="mm", message=f"max deviation {dev:.2e} mm"))

        vol = sum(b.volume_mm3 for b in solids)
        rel = abs(vol - exp.volume_mm3) / exp.volume_mm3
        out.append(_r("GEO-VOLUME", "Volume matches analytic model", "GEOMETRY", "GEOMETRY",
                      "Fusion-measured volume equals the generator's analytic volume (consistency with design intent).",
                      rel <= VOLUME_REL_TOL,
                      measured=round(vol, 3), limit=f"{exp.volume_mm3:.3f} ± {VOLUME_REL_TOL:.0e} rel", unit="mm3",
                      message=f"relative deviation {rel:.2e}"))

    missing, wrong = [], []
    for name, value in exp.parameters.items():
        got = rep.parameters.get(name)
        if got is None:
            missing.append(name)
        elif abs(got["value_mm"] - value) > 1e-6:
            wrong.append(f"{name}: fusion {got['value_mm']} vs record {value}")
    out.append(_r("GEO-PARAM-SYNC", "Fusion user parameters equal the component record", "GEOMETRY", "PARAMETERS",
                  "Fusion holds the parameter values of the record (does not by itself prove the geometry follows them).",
                  not missing and not wrong, measured=f"{len(exp.parameters) - len(missing) - len(wrong)}/{len(exp.parameters)}",
                  message="; ".join([f"missing {m}" for m in missing] + wrong)))

    out.extend(placement_checks(rep, exp))
    out.extend(hole_checks(rep, exp))
    return out


def placement_checks(rep: GeometryReport, exp: ExpectedGeometry) -> list[ValidationResult]:
    """The occurrence sits at the planned pose, and the world geometry is that pose applied to the local geometry.

    Three independent facts: Fusion's occurrence transform equals pose_to_matrix(pose); no uncaptured (pending) move
    that a recompute would discard; every world-space vertex equals the planned pose applied to its local vertex."""
    if rep.occurrence_transform is None:          # legacy report: placement was not measured
        return []
    want = pose_to_matrix(exp.pose)
    got = np.array(rep.occurrence_transform, dtype=float).reshape(4, 4)
    t_dev = float(np.max(np.abs(got[:3, 3] - want[:3, 3])))
    cos = np.clip((np.trace(want[:3, :3].T @ got[:3, :3]) - 1.0) / 2.0, -1.0, 1.0)
    rot_dev = float(np.degrees(np.arccos(cos)))
    v_dev, n_vert, problems = 0.0, 0, []
    for b in rep.bodies:
        if not b.vertices_local or not b.vertices_world or len(b.vertices_local) != len(b.vertices_world):
            problems.append(f"{b.name}: local/world vertices missing or unequal in number")
            continue
        placed = np.array([transform_point(want, tuple(v)) for v in b.vertices_local])
        world = np.array(b.vertices_world, dtype=float)
        d = np.linalg.norm(placed[:, None, :] - world[None, :, :], axis=2)
        v_dev = max(v_dev, float(d.min(axis=1).max()), float(d.min(axis=0).max()))
        n_vert += len(world)
    if t_dev > LENGTH_TOL_MM:
        problems.append(f"translation deviates {t_dev:.2e} mm")
    if rot_dev > ANGLE_TOL_DEG:
        problems.append(f"rotation deviates {rot_dev:.2e} deg")
    if v_dev > LENGTH_TOL_MM:
        problems.append(f"world vertices deviate up to {v_dev:.2e} mm from the planned pose")
    if rep.pending_snapshot:
        problems.append("Fusion has an uncaptured (pending) position change that a recompute would discard")
    return [_r("GEO-PLACEMENT", "Component placed at the planned pose", "GEOMETRY", "PLACEMENT",
               "Fusion's occurrence transform equals the planned pose (position + rotation), nothing is pending, and "
               "every world-space body vertex equals the planned pose applied to its local vertex.",
               not problems,
               measured={"position_mm": [round(float(v), 6) for v in got[:3, 3]], "translation_dev_mm": t_dev,
                         "rotation_dev_deg": rot_dev, "vertices_checked": n_vert, "max_vertex_dev_mm": v_dev,
                         "pending_snapshot": rep.pending_snapshot},
               limit={"position_mm": list(exp.pose.position), "rotation_deg": list(exp.pose.rotation_deg),
                      "tol_mm": LENGTH_TOL_MM, "tol_deg": ANGLE_TOL_DEG},
               message="; ".join(problems) if problems else
               f"placement verified ({n_vert} vertices, max deviation {v_dev:.1e} mm)")]


def _point_line_distance(p, origin, axis) -> float:
    p, o, a = (np.array(x, dtype=float) for x in (p, origin, axis))
    a = a / np.linalg.norm(a)
    d = p - o
    return float(np.linalg.norm(d - np.dot(d, a) * a))


def hole_checks(rep: GeometryReport, exp: ExpectedGeometry) -> list[ValidationResult]:
    """Each expected hole must exist as a concave cylinder with the right diameter, axis and position."""
    if not exp.holes_local:
        return []
    m = pose_to_matrix(exp.pose)
    cyl = [c for b in rep.bodies for c in b.cylinders if c.get("concave")]
    used: set[int] = set()
    found, problems = [], []
    for h in exp.holes_local:
        center = transform_point(m, h["center"])
        axis = transform_vector(m, h["axis"])
        match = None
        for k, c in enumerate(cyl):
            if k in used:
                continue
            if abs(2 * c["radius"] - h["diameter"]) > LENGTH_TOL_MM:
                continue
            if abs(abs(float(np.dot(c["axis"], axis))) - 1.0) > 1e-6:
                continue
            if _point_line_distance(center, c["center"], c["axis"]) > LENGTH_TOL_MM:
                continue
            match = k
            break
        if match is None:
            problems.append(f"{h['id']} (Ø{h['diameter']} at {tuple(round(v, 3) for v in center)})")
        else:
            used.add(match)
            found.append(h["id"])
    return [_r("IFC-HOLE-GEOMETRY", "Own mounting holes: diameter, axis and position as designed", "INTERFACE",
               "HOLE_GEOMETRY",
               "This component's own mounting holes exist in Fusion with the designed diameter, axis and position. "
               "Says nothing about the mating part.",
               not problems, measured=f"{len(found)}/{len(exp.holes_local)} holes matched",
               limit=f"position/diameter tol {LENGTH_TOL_MM} mm", unit="mm",
               message=("missing/misplaced: " + ", ".join(problems)) if problems else "All own mounting holes found in Fusion geometry.")]


def mating_interface_results(interfaces: list[dict]) -> list[ValidationResult]:
    """Explicitly record that fit with mating parts is NOT verified when those parts are not modelled."""
    out = []
    for i in interfaces:
        out.append(ValidationResult(
            check_id=f"IFC-MATING@{i['id']}", title=f"Mating fit of {i['id']} with {i.get('mates_with') or 'unknown part'}",
            category="INTERFACE", scope="MATING_INTERFACE", status=Status.NOT_VERIFIED, severity=Severity.ADVISORY,
            method="NOT_RUN",
            claim="Whether the mating part's holes/faces coincide with this interface. Not checked: the mating part "
                  "is not modelled in the project.",
            message="Mating part geometry not available; fit, hole alignment and clearance are not verified."))
    return out


def structural_adequacy_result() -> ValidationResult:
    return ValidationResult(
        check_id="STR-ADEQUACY", title="Overall structural adequacy", category="STRUCTURAL",
        scope="STRUCTURAL_ADEQUACY", status=Status.NOT_VERIFIED, severity=Severity.ADVISORY, method="NOT_RUN",
        claim="Whether the part is structurally adequate in service. Not established: only one simplified hand "
              "calculation was run.",
        message="Not analysed: bolt loads/prying, base-leg bending, fatigue, stress concentration, FEA.")


def plate_bending_check(force_n: float, lever_arm_mm: float, section_width_mm: float, thickness_mm: float,
                        yield_mpa: float, required_sf: float, inputs_assumed: bool, note: str) -> ValidationResult:
    """Hand calculation: plate under a bending moment M = F·e, section modulus W·t²/6."""
    if force_n <= 0 or lever_arm_mm <= 0:
        # no load case (zero force or lever arm): nothing was checked - never report this as a passed check
        return ValidationResult(check_id="STR-PLATE-BENDING", title="Hand calc: leg bending stress", category="STRUCTURAL",
                                scope="STRUCTURAL_CHECK", status=Status.NOT_VERIFIED, severity=Severity.ADVISORY,
                                method="NOT_RUN",
                                claim="Hand calculation not run: the plan has no load case (zero force or lever arm).",
                                measured={"force_N": force_n, "lever_arm_mm": lever_arm_mm},
                                message="No load case given - plate bending hand calculation not run; the part's "
                                        "strength is not checked.")
    if section_width_mm <= 0 or thickness_mm <= 0:
        return ValidationResult(check_id="STR-PLATE-BENDING", title="Hand calc: leg bending stress", category="STRUCTURAL",
                                scope="STRUCTURAL_CHECK", claim="Hand calculation could not be run.",
                                status=Status.NOT_VERIFIED, method="NOT_RUN", message="invalid section")
    m = force_n * lever_arm_mm
    sigma = 6.0 * m / (section_width_mm * thickness_mm ** 2)
    sf = math.inf if sigma == 0 else yield_mpa / sigma
    passed = sf >= required_sf
    status = Status.NON_COMPLIANT if not passed else (Status.ASSUMPTION if inputs_assumed else Status.VERIFIED)
    return ValidationResult(check_id="STR-PLATE-BENDING", title="Hand calc: leg bending stress vs yield",
                            category="STRUCTURAL", scope="STRUCTURAL_CHECK",
                            claim="One simplified hand calculation (plate bending at the critical section vs yield) "
                                  "meets the required safety factor. Not a structural-adequacy statement.",
                            status=status, severity=Severity.BLOCKING, method="HAND_CALC",
                            measured={"moment_Nmm": round(m, 1), "stress_MPa": round(sigma, 2),
                                      "safety_factor": round(sf, 2)},
                            limit=f"SF >= {required_sf}", unit="MPa",
                            message=note + " Stress concentration at holes/fillet and fatigue NOT included.")
