"""Deterministic checks for free-form parts and their assembly (fast mode), from Fusion measurements only.

Inputs are the prelude's @@RESULT@@ payload (fusion/prelude.py) and the assembly measurement
(fusion/assembly.py); nothing here talks to Fusion or to an AI.
"""
from __future__ import annotations

import numpy as np

from agent import fast_config
from validation.checks import ANGLE_TOL_DEG, LENGTH_TOL_MM
from vehicle.models import Severity, Status, ValidationResult
from vehicle.parts import PartSpec
from vehicle.transforms import pose_to_matrix

PARAM_TOL_MM = 1e-6

# check ids whose failure Claude can fix by rewriting the body (the rest are ours or Fusion's)
REPAIRABLE = {"PART-BUILD", "PART-SOLID", "PART-FEATURES", "PART-BBOX", "PART-PARAMS", "PART-FRAME"}

FRAME_MISMATCH = ("Frame mismatch: script appears to use world coordinates; geometry must be defined in the "
                  "part-local frame and positioned only by pose.")


def _res(check_id, title, scope, claim, ok, category="GEOMETRY", severity=Severity.BLOCKING, status=None, **kw):
    return ValidationResult(check_id=check_id, title=title, category=category, scope=scope, claim=claim,
                            severity=severity, method=kw.pop("method", "FUSION_MEASUREMENT"),
                            status=status or (Status.VERIFIED if ok else Status.NON_COMPLIANT), **kw)


def _fmt_box(lo, hi) -> str:
    return "[" + ",".join("(" + ",".join(f"{v:.0f}" for v in p) + ")" for p in (lo, hi)) + "]"


def _faces_within(m_lo, m_hi, lo, hi, tol) -> int:
    """How many of the 6 faces of box m coincide (|d| <= tol) with the faces of box (lo, hi)."""
    return sum(abs(a - b) <= tol for a, b in zip(list(m_lo) + list(m_hi), list(lo) + list(hi)))


def _contained(m_lo, m_hi, lo, hi, tol) -> bool:
    return all(a >= b - tol for a, b in zip(m_lo, lo)) and all(a <= b + tol for a, b in zip(m_hi, hi))


def _identity_pose(spec: PartSpec) -> bool:
    return (max(abs(v) for v in spec.position_mm) <= LENGTH_TOL_MM
            and max(abs(v) for v in spec.rotation_deg) <= ANGLE_TOL_DEG)


def frame_check(spec: PartSpec, data: dict, frame_mode: str = "part_local") -> ValidationResult:
    """Coordinate-frame contract (docs/fusion_script_contract.md): the part's LOCAL bbox, measured by the prelude in
    the build script at identity (before placement), against the planned world envelope taken back into the part
    frame by the inverse pose (all 8 corners transformed, so rotated poses are handled). Tolerance: BBOX_TOL_MM, the
    same per-side allowance as PART-BBOX.

    part_local: (1) the local bbox lies inside the local envelope (+tol); (2) frame mismatch: a script that encodes
    the world position puts its faces where the WORLD envelope is - when the measured box fits inside the world
    envelope and more of its 6 faces coincide with the world envelope than with the local one, the check fails with
    FRAME_MISMATCH (a bbox that is merely inside the local envelope does not catch this: MON-001 v1 was).
    legacy_world (compatibility exception, MON-001 v2): the script's coordinates are VCS coordinates, valid only at
    an identity pose (then local = world); any other pose would apply the offset twice and fails."""
    tol = fast_config.get("BBOX_TOL_MM")
    exp_lo, exp_hi = spec.local_envelope()
    w_lo, w_hi = tuple(spec.envelope_min), tuple(spec.envelope_max)
    title, claim = "Geometry in the part-local frame", ("The part's local bbox (built at identity) lies in the planned "
                                                       "envelope taken back into the part frame by the inverse pose.")
    m = data.get("bbox_local")
    limit = {"expected_local": [list(exp_lo), list(exp_hi)], "world_envelope": [list(w_lo), list(w_hi)],
             "tol_mm": tol, "frame_mode": frame_mode}
    if not m:
        return _res("PART-FRAME", title, "GEOMETRY", claim, False, severity=Severity.ADVISORY,
                    status=Status.NOT_VERIFIED, method="NOT_RUN", limit=limit,
                    message="local bbox not measured (result without bbox_local)")
    m_lo, m_hi = m
    exp = f"expected local bbox {_fmt_box(exp_lo, exp_hi)}, measured {_fmt_box(m_lo, m_hi)}"
    measured = {"bbox_local": m}
    if frame_mode == "legacy_world":
        if not _identity_pose(spec):
            return _res("PART-FRAME", title, "GEOMETRY", claim, False, limit=limit, measured=measured,
                        message=(f"legacy_world script (VCS coordinates) placed with a non-identity pose "
                                 f"{list(spec.position_mm)} / {list(spec.rotation_deg)} deg would apply the offset "
                                 f"twice; legacy records build only at identity - rewrite it in the part-local frame"))
        ok = _contained(m_lo, m_hi, w_lo, w_hi, tol)
        return _res("PART-FRAME", title, "GEOMETRY", claim, ok, limit=limit, measured=measured,
                    message=("legacy_world compatibility exception (identity pose: local = world)" if ok
                             else f"legacy_world geometry outside the envelope: {exp}"))
    in_local = _contained(m_lo, m_hi, exp_lo, exp_hi, tol)
    if not _identity_pose(spec):
        n_local = _faces_within(m_lo, m_hi, exp_lo, exp_hi, tol)
        n_world = _faces_within(m_lo, m_hi, w_lo, w_hi, tol)
        if _contained(m_lo, m_hi, w_lo, w_hi, tol) and n_world > n_local:
            measured.update(faces_on_world_envelope=n_world, faces_on_local_envelope=n_local)
            return _res("PART-FRAME", title, "GEOMETRY", claim, False, limit=limit, measured=measured,
                        message=f"{FRAME_MISMATCH} {exp}; pose position {[round(v) for v in spec.position_mm]}")
    return _res("PART-FRAME", title, "GEOMETRY", claim, in_local, limit=limit, measured=measured,
                message="" if in_local else f"local geometry outside the local envelope (+{tol:g} mm): {exp}")


def part_checks(spec: PartSpec, data: dict, frame_mode: str = "part_local") -> list[ValidationResult]:
    """data: the prelude result for one part build."""
    if not data.get("ok"):
        return [_res("PART-BUILD", "Part script ran", "CAD_BUILD", "The part script built a body without error.",
                     False, category="PROCESS", message=f"[{data.get('stage')}] {data.get('error', 'failed')}")]
    m = data["measure"]
    out = [_res("PART-BUILD", "Part script ran", "CAD_BUILD", "The part script built a body without error.", True,
                category="PROCESS")]
    solids = [b for b in m["bodies"] if b["solid"] and b["volume_mm3"] > 0]
    out.append(_res("PART-SOLID", "Solid body exists", "GEOMETRY", "The part has at least one closed solid body.",
                    bool(solids), measured={"bodies": len(m["bodies"]), "solids": len(solids),
                                            "volume_mm3": round(sum(b["volume_mm3"] for b in solids), 1)},
                    message="" if solids else "no solid body with positive volume"))
    errors = [f for f in m["features_bad"] if f["health"] == "ERROR"]
    warns = [f for f in m["features_bad"] if f["health"] != "ERROR"]
    out.append(_res("PART-FEATURES", "Features healthy", "GEOMETRY", "No feature of the part is in an error state.",
                    not errors, measured={"features": m["features_total"], "errors": len(errors), "warnings": len(warns)},
                    message="; ".join(f"{f['name']}: {f['health']} {f['message']}" for f in errors + warns)[:400]))
    tol = fast_config.get("BBOX_TOL_MM")
    bb = m.get("bbox_world")
    if bb:
        lo, hi = np.array(bb[0]), np.array(bb[1])
        elo, ehi = np.array(spec.envelope_min), np.array(spec.envelope_max)
        over = np.maximum(elo - lo, 0) + 0.0
        under = np.maximum(hi - ehi, 0) + 0.0
        worst = float(max(over.max(), under.max()))
        ok = worst <= tol
        msg = "" if ok else "outside the planned envelope: " + ", ".join(
            f"{ax}{s} by {v:.1f} mm" for ax, a, b in zip("XYZ", over, under)
            for s, v in (("-", a), ("+", b)) if v > tol)
    else:
        ok, worst, msg = False, None, "no bounding box measured"
    out.append(_res("PART-BBOX", "World bounding box within the planned envelope", "GEOMETRY",
                    f"The measured world bbox lies inside the planned envelope (+{tol:g} mm per side).", ok,
                    measured=bb, limit={"min": list(spec.envelope_min), "max": list(spec.envelope_max), "tol_mm": tol},
                    message=msg))
    out.append(frame_check(spec, data, frame_mode))
    want = pose_to_matrix(spec.pose)
    got = np.array(m["transform"], dtype=float).reshape(4, 4)
    t_dev = float(np.max(np.abs(got[:3, 3] - want[:3, 3])))
    cos = np.clip((np.trace(want[:3, :3].T @ got[:3, :3]) - 1.0) / 2.0, -1.0, 1.0)
    r_dev = float(np.degrees(np.arccos(cos)))
    pl = data.get("placement") or {}
    problems = []
    if t_dev > LENGTH_TOL_MM:
        problems.append(f"translation deviates {t_dev:.2e} mm")
    if r_dev > ANGLE_TOL_DEG:
        problems.append(f"rotation deviates {r_dev:.2e} deg")
    if pl.get("pending"):
        problems.append("uncaptured (pending) move")
    out.append(_res("PART-PLACEMENT", "Placed at the planned pose (read-back)", "PLACEMENT",
                    "Fusion's occurrence transform read back equals the planned pose; nothing is pending.",
                    not problems, measured={"position_mm": [round(float(v), 6) for v in got[:3, 3]],
                                            "translation_dev_mm": t_dev, "rotation_dev_deg": r_dev},
                    limit={"tol_mm": LENGTH_TOL_MM, "tol_deg": ANGLE_TOL_DEG}, message="; ".join(problems)))
    params = m.get("params") or {}
    wrong = [f"{k}: {params.get(k)} != {v}" for k, v in spec.dims.items()
             if k not in params or abs(params[k] - v) > PARAM_TOL_MM]
    out.append(_res("PART-PARAMS", "Key parameters equal the plan", "PARAMETERS",
                    "Every key dimension exists as a Fusion user parameter with the planned value.", not wrong,
                    method="PARAMETER_CHECK", measured=params, limit=spec.dims, message="; ".join(wrong)))
    return out


def failed(results: list[ValidationResult]) -> list[ValidationResult]:
    return [r for r in results if r.blocking_failure]


def repairable(results: list[ValidationResult]) -> bool:
    """True if the blocking failures are all ones a rewritten body can fix."""
    bad = failed(results)
    return bool(bad) and all(r.check_id in REPAIRABLE for r in bad)


def box_separation(a_min, a_max, b_min, b_max) -> list[float]:
    """Per axis (X, Y, Z): distance between two axis-aligned boxes (> 0 = apart, < 0 = interpenetration depth)."""
    return [max(a_min[i] - b_max[i], b_min[i] - a_max[i]) for i in range(3)]


def planned_mate_problem(mate: dict, a_box, b_box, tol: float) -> tuple[str | None, str | None]:
    """Plan consistency for one mate from the planned envelopes. Returns (problem, note): a problem rejects the plan
    (the envelopes contradict the mate); a note records a contact that envelopes cannot confirm.

    touching / overlap: the boxes must not be apart by more than tol on any axis, and the mate axis is the axis whose
    faces meet (|separation| <= tol). gap <= value: not apart by more than value + tol. If the boxes interpenetrate
    on all three axes (one envelope reaches into the other, e.g. a floor with a raised diffuser under a tub) there is
    no contact plane to check: noted, left to the Fusion mate measurement.
    clear >= value (keep-clear): never a problem (envelopes are loose boxes); noted when the envelopes are not at
    least value apart on some axis - the Fusion minimum distance decides."""
    sep = box_separation(*a_box, *b_box)
    if mate["expect"] == "clear":
        if max(sep) >= (mate.get("value_mm") or 0.0):
            return None, None
        return None, (f"mate {mate['a']}/{mate['b']} (clear >= {mate.get('value_mm') or 0.0:g} mm): envelopes are "
                      f"{max(sep):.1f} mm apart at most; the Fusion minimum distance decides")
    allowed = tol if mate["expect"] in ("touching", "overlap") else (mate.get("value_mm") or 0.0) + tol
    worst = max(range(3), key=lambda i: sep[i])
    name = f"{mate['a']}/{mate['b']} ({mate['expect']}" + (f" <= {mate['value_mm']:g} mm)" if mate.get("value_mm") else ")")
    if sep[worst] > allowed:
        return (f"mate {name}: planned envelopes are {sep[worst]:.1f} mm apart along {'XYZ'[worst]} "
                f"(allowed {allowed:g} mm); move a part or its envelope so they meet"), None
    if mate["expect"] == "touching" and not any(abs(s) <= tol for s in sep):
        return None, (f"mate {name}: envelopes interpenetrate on X/Y/Z ({', '.join(f'{s:.0f}' for s in sep)} mm); "
                      f"no contact plane to check before building - the Fusion mate measurement decides")
    return None, None


def planned_contact_axis(mate: dict, spec_a, spec_b) -> int | None:
    """The one axis on which the two planned envelopes meet for this mate (separation within the mate's window)
    while they overlap on the other two; None when there is no unique contact face (mate_face_checks uses the same
    rule)."""
    tol = fast_config.get("TOUCH_TOL_MM")
    sep = box_separation(spec_a.envelope_min, spec_a.envelope_max, spec_b.envelope_min, spec_b.envelope_max)
    v = mate.get("value_mm") or 0.0
    lo_s, hi_s = {"touching": (-tol, tol), "gap": (-tol, v + tol), "overlap": (-v - tol, tol)}.get(
        mate["expect"], (None, None))
    if lo_s is None:
        return None
    contact = [i for i in range(3) if lo_s <= sep[i] <= hi_s]
    if len(contact) != 1 or not all(sep[j] < 0 for j in range(3) if j != contact[0]):
        return None
    return contact[0]


def mate_title(mt: dict) -> str:
    v = mt.get("value_mm")
    return f"{mt['a']} / {mt['b']} {mt['expect']}" + (f" {'>=' if mt['expect'] == 'clear' else '<='} {v:g} mm" if v else "")


def mate_results(mates: list[dict], measured: dict) -> list[ValidationResult]:
    """mates: [{"a", "b", "expect": touching|overlap|gap|clear, "value_mm"}]; measured: fusion.assembly result.

    touching: gap <= tol, or an interference no deeper than tol. overlap <= value (planned shallow embedding):
    touching, or interference depth <= value (depth = smallest extent of the interference body). gap <= value: not
    interfering and gap <= value. clear >= value (keep-clear): no interference and gap >= value (and > tol).
    Pairs the measurement skipped (bounding boxes far apart, no planned mate) cannot interfere: not reported.

    Overlap depth: measurement version 2 (fusion/assembly.py) ray-measures planned-overlap pairs per interference
    piece (depth_method "ray": that depth is used). If the rays could not determine it ("bbox_fallback") the result
    is ADVISORY / NOT_VERIFIED with the old bbox depth and a note - never a silent pass. Version 1 measurements (old
    runs, no depth_method) keep the old bbox depth unchanged."""
    tol, noise = fast_config.get("TOUCH_TOL_MM"), fast_config.get("OVERLAP_IGNORE_MM3")
    pairs = {tuple(sorted((p["a"], p["b"]))): p for p in measured.get("pairs", [])}
    out = []
    for mt in mates:
        key = tuple(sorted((mt["a"], mt["b"])))
        p = pairs.get(key)
        cid = f"MATE-{key[0]}-{key[1]}"
        title = mate_title(mt)
        if p is None or p.get("error") or p.get("skipped"):
            out.append(_res(cid, title, "MATING_INTERFACE", "Measured contact state of the two parts.", False,
                            category="INTERFACE", status=Status.NOT_VERIFIED, method="NOT_RUN",
                            message=(p or {}).get("error") or "pair not measured"))
            continue
        gap, vol, depth = p["min_distance_mm"], p["overlap_mm3"], p["overlap_depth_mm"]
        state = "overlap" if vol > noise else ("touching" if gap <= tol else "gap")
        limit = mt.get("value_mm") or 0.0
        method = p.get("depth_method") if mt["expect"] == "overlap" and state == "overlap" else None
        extra = {}
        if method:
            extra = {"depth_method": method, "overlap_depth_bbox_mm": round(p["overlap_depth_mm"], 3),
                     "measure_version": measured.get("measure_version"),
                     "pieces": [{"axis": r["axis"], "depth_mm": r["depth_mm"], "rays": r["rays"]}
                                for r in p.get("depth_pieces", [])]}
            if method == "ray":
                depth = p["overlap_depth_ray_mm"]
        if mt["expect"] == "touching":
            ok = state == "touching" or (state == "overlap" and depth <= tol)
        elif mt["expect"] == "gap":
            ok = state in ("touching", "gap") and gap <= max(limit, tol)
        elif mt["expect"] == "clear":
            ok = state == "gap" and gap >= limit
        else:                                            # overlap <= value
            ok = state in ("touching", "overlap") and (depth <= max(limit, tol))
        meas = {"state": state, "gap_mm": round(gap, 3), "overlap_mm3": round(vol, 1),
                "overlap_depth_mm": round(depth, 3), **extra}
        lim = {"expect": mt["expect"], "value_mm": limit, "tol_mm": tol}
        if method == "bbox_fallback":
            out.append(_res(cid, title, "MATING_INTERFACE",
                            "Measured in Fusion: minimum distance and interference of the two placed parts.", False,
                            category="INTERFACE", severity=Severity.ADVISORY, status=Status.NOT_VERIFIED,
                            measured=meas, limit=lim,
                            message=(f"overlap depth not determined by rays ({p.get('depth_note') or 'no reason'}); "
                                     f"bbox depth {depth:.2f} mm (smallest side of the interference body, may "
                                     f"overstate) {'within' if ok else 'above'} {limit:g} mm - check manually")))
            continue
        out.append(_res(cid, title, "MATING_INTERFACE",
                        "Measured in Fusion: minimum distance and interference of the two placed parts.", ok,
                        category="INTERFACE", measured=meas, limit=lim,
                        message="" if ok else f"measured {state} (gap {gap:.2f} mm, overlap depth {depth:.2f} mm)"))
    mated = {tuple(sorted((m["a"], m["b"]))) for m in mates}
    for key, p in sorted(pairs.items()):
        if key in mated or p.get("error") or p.get("skipped") or p["overlap_mm3"] <= noise:
            continue
        out.append(_res(f"OVERLAP-{key[0]}-{key[1]}", f"Unintended overlap {key[0]} / {key[1]}", "GEOMETRY",
                        "Parts without a planned mate do not interfere.", False, category="GEOMETRY",
                        severity=Severity.ADVISORY, measured={"overlap_mm3": round(p["overlap_mm3"], 1),
                                                              "overlap_depth_mm": round(p["overlap_depth_mm"], 3)},
                        message="unintended overlap"))
    return out


def mate_face_checks(mates: list[dict], specs: dict, bboxes: dict) -> list[dict]:
    """ADVISORY, per planned mate: does each part's measured solid reach its planned mating face?

    The intended contact face comes from the planned envelopes: exactly one axis on which the two envelopes meet
    (separation within [-tol, tol] touching, [-tol, value + tol] gap, [-value - tol, tol] overlap) while they overlap
    on the other two.
    Then per part: expected = its envelope face on that side, measured = its bbox face, deviation = measured -
    expected. PASS: |deviation| <= TOUCH_TOL_MM; WARNING: beyond it. NOT_CHECKABLE: no unique contact face (e.g. one
    envelope reaches into the other on every axis) or no measured bbox - then a geometric / Fusion-level check is
    needed. A bbox reaching the face does not prove face contact (a tapered solid touches it at one point only);
    the Fusion mate measurement (MATE-*) decides. specs: {id: PartSpec}; bboxes: {id: [[min], [max]] world}."""
    tol = fast_config.get("TOUCH_TOL_MM")
    out = []
    for m in mates:
        a, b = m["a"], m["b"]
        name = f"{a}/{b}"
        if a not in specs or b not in specs or m["expect"] == "clear":       # keep-clear: no contact face
            continue
        ea, eb = (specs[a].envelope_min, specs[a].envelope_max), (specs[b].envelope_min, specs[b].envelope_max)
        sep = box_separation(*ea, *eb)
        v = m.get("value_mm") or 0.0                     # contact-axis window for the envelope separation
        lo_s, hi_s = {"touching": (-tol, tol), "gap": (-tol, v + tol), "overlap": (-v - tol, tol)}[m["expect"]]
        contact = [i for i in range(3) if lo_s <= sep[i] <= hi_s]
        others_overlap = all(sep[j] < 0 for j in range(3) if j not in contact)
        if len(contact) != 1 or not others_overlap:
            out.append({"mate": name, "a": a, "b": b, "part": None, "face": name, "axis": None, "expected_mm": None,
                        "measured_mm": None, "deviation_mm": None, "status": "NOT_CHECKABLE",
                        "note": (f"no unique planned contact face (envelope separation X/Y/Z "
                                 f"{', '.join(f'{s:.0f}' for s in sep)} mm); a geometric / Fusion-level check is "
                                 f"needed - the MATE measurement decides")})
            continue
        i = contact[0]
        a_low = abs(ea[1][i] - eb[0][i]) <= abs(eb[1][i] - ea[0][i])      # a's +axis face meets b's -axis face
        for pid, env, side in ((a, ea, 1 if a_low else 0), (b, eb, 0 if a_low else 1)):
            face = f"{pid} {'+' if side else '-'}{'XYZ'[i]}"
            expected = float(env[side][i])
            bb = bboxes.get(pid)
            if not bb:
                out.append({"mate": name, "a": a, "b": b, "part": pid, "face": face, "axis": "XYZ"[i],
                            "expected_mm": expected, "measured_mm": None, "deviation_mm": None,
                            "status": "NOT_CHECKABLE", "note": "part not measured"})
                continue
            measured = float(bb[side][i])
            dev = round(measured - expected, 3) + 0.0
            ok = abs(dev) <= tol
            out.append({"mate": name, "a": a, "b": b, "part": pid, "face": face, "axis": "XYZ"[i],
                        "expected_mm": expected, "measured_mm": measured, "deviation_mm": dev,
                        "status": "PASS" if ok else "WARNING",
                        "note": (f"bbox reaches the planned face (expected {expected:g}, measured {measured:g} mm); "
                                 f"actual contact is decided by the Fusion mate measurement" if ok else
                                 f"solid {'stops short of' if (dev < 0) == bool(side) else 'passes'} the planned face by "
                                 f"{abs(dev):.2f} mm (expected {expected:g}, measured {measured:g} mm)")})
    return out


def geometry_of(data: dict) -> dict:
    """Exact measurement kept for derived-part verification (prelude result of one build)."""
    m = data.get("measure") or {}
    solids = [b for b in m.get("bodies", []) if b.get("solid") and b.get("volume_mm3", 0) > 0]
    if not solids:
        return {}
    return {"volume_mm3": sum(b["volume_mm3"] for b in solids), "solids": len(solids),
            "lumps": sum(b.get("lumps", 1) for b in solids), "bbox_local": data.get("bbox_local"),
            "bbox_world": m.get("bbox_world")}


def _box_dev(a, b) -> float:
    return max(abs(float(x) - float(y)) for p, q in zip(a, b) for x, y in zip(p, q))


def derived_check(mode: str, source_id: str, source: dict, data: dict) -> ValidationResult:
    """PART-DERIVED: a derived part (vehicle/mirror.py) against its source's exact measurement.
    - volume equal within DERIVED_VOLUME_REL (1e-6 relative); same number of solid bodies and lumps;
    - local bbox (before placement): mirror = the source's with Y flipped; yaw180 = equal;
    - world bbox: the source's with Y flipped (both modes; for yaw180 this is what proves the wheel symmetric about
      its axle with the hub boss inboard), within DERIVED_WORLD_TOL_MM (Fusion's world boxes of rotated curved
      bodies are not tight). Local tolerance DERIVED_BBOX_TOL_MM."""
    from vehicle.mirror import mirror_box
    title = f"Derived from {source_id} ({mode})"
    claim = ("Same volume and body structure as the source; local bbox mirrored (mirror) or equal (yaw180); world "
             "bbox = the source's mirrored about Y = 0.")
    got = geometry_of(data)
    if not source or not got:
        return _res("PART-DERIVED", title, "GEOMETRY", claim, False, status=Status.NOT_VERIFIED, method="NOT_RUN",
                    message="source measurement missing" if not source else "no solid measured")
    vol_rel, loc_tol, world_tol = (fast_config.get(k) for k in ("DERIVED_VOLUME_REL", "DERIVED_BBOX_TOL_MM",
                                                                  "DERIVED_WORLD_TOL_MM"))
    problems = []
    rel = abs(got["volume_mm3"] - source["volume_mm3"]) / max(source["volume_mm3"], 1e-12)
    if rel > vol_rel:
        problems.append(f"volume {got['volume_mm3']:.6f} vs source {source['volume_mm3']:.6f} mm3 (rel {rel:.2e})")
    if (got["solids"], got["lumps"]) != (source["solids"], source.get("lumps", got["lumps"])):
        problems.append(f"{got['solids']} solid(s) / {got['lumps']} lump(s) vs source {source['solids']} / "
                        f"{source.get('lumps')}")
    measured = {"volume_mm3": got["volume_mm3"], "volume_rel_dev": rel, "solids": got["solids"], "lumps": got["lumps"]}
    if source.get("bbox_local") and got.get("bbox_local"):
        lo, hi = source["bbox_local"]
        want = [list(v) for v in (mirror_box(lo, hi) if mode == "mirror" else (lo, hi))]
        dev = _box_dev(got["bbox_local"], want)
        measured["bbox_local_dev_mm"] = round(dev, 6)
        if dev > loc_tol:
            problems.append(f"local bbox {got['bbox_local']} != expected {want} (dev {dev:.4f} mm)")
    else:
        problems.append("local bbox not measured")
    if source.get("bbox_world") and got.get("bbox_world"):
        want = [list(v) for v in mirror_box(*source["bbox_world"])]
        dev = _box_dev(got["bbox_world"], want)
        measured["bbox_world_dev_mm"] = round(dev, 6)
        if dev > world_tol:
            problems.append(f"world bbox {got['bbox_world']} != source mirrored {want} (dev {dev:.3f} mm)")
    return _res("PART-DERIVED", title, "GEOMETRY", claim, not problems, measured=measured,
                limit={"volume_rel": vol_rel, "bbox_local_tol_mm": loc_tol, "bbox_world_tol_mm": world_tol,
                       "source": {k: source.get(k) for k in ("volume_mm3", "solids", "lumps", "bbox_local",
                                                            "bbox_world")}},
                message="; ".join(problems))
