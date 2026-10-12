"""Left/right derived parts (pure, deterministic): derived specs, derived mates, staleness.

A derived part costs zero Claude calls: it is built from its SOURCE part's stored script.
- mirror (handed parts: suspension, sidepods, mirrors): the script builds the source geometry in the derived part's
  own component, the prelude mirrors it about the component-local XZ plane (y -> -y) and the part is placed with the
  mirrored pose. With S = diag(1, -1, 1): world = S·P·local = (S·P·S)·(S·local), so the derived pose is S·P·S:
  position (x, -y, z), rotation S·R·S = Rz(-yaw)·Ry(pitch)·Rx(-roll), i.e. (-roll, pitch, -yaw).
- yaw180 (wheels only): the script is NOT mirrored. A wheel is rotationally symmetric about its axle (part-local Y
  through the local origin), so it is also symmetric under x -> -x (Sx), and S·P·G = S·P·Sx·G. The rigid pose
  S·P·Sx has rotation (S·R·S)·Rz(180): position (x, -y, z), and for a pose with zero roll and pitch the rotation is
  just yaw -> 180 - yaw (yaw += 180 when the toe angle is 0). The hub boss, built on the source's inboard side,
  stays inboard; a mirrored pose of unmirrored geometry would not be a rigid placement.
Both modes: the derived world envelope is the source envelope with its Y range flipped.
"""
from __future__ import annotations

import numpy as np

from vehicle.parts import PartRecord, PartSpec
from vehicle.transforms import rotation_matrix, rotation_to_euler

S = np.diag([1.0, -1.0, 1.0])
MODES = ("mirror", "yaw180")


def mirror_box(lo, hi) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Axis-aligned box mirrored about Y = 0."""
    return (float(lo[0]), -float(hi[1]) + 0.0, float(lo[2])), (float(hi[0]), -float(lo[1]) + 0.0, float(hi[2]))


def derived_rotation(rotation_deg, mode: str) -> tuple[float, float, float]:
    if mode not in MODES:
        raise ValueError(f"unknown mirror_mode {mode!r}")
    roll, pitch, yaw = (float(v) for v in rotation_deg)
    if mode == "mirror":                                 # S·R·S, exact
        return (-roll + 0.0, pitch + 0.0, -yaw + 0.0)
    return rotation_to_euler(S @ rotation_matrix(roll, pitch, yaw) @ S @ rotation_matrix(0.0, 0.0, 180.0))


def derive_spec(src: PartSpec, new_id: str, mode: str, name: str | None = None, role: str | None = None) -> PartSpec:
    """The derived part's spec from its source's spec (dims, notes and FIA refs kept; pose and envelope mirrored)."""
    if src.mirror_of:
        raise ValueError(f"{src.id} is itself derived from {src.mirror_of}; derive from a source part")
    if new_id == src.id:
        raise ValueError(f"{new_id} cannot be derived from itself")
    x, y, z = src.position_mm
    lo, hi = mirror_box(src.envelope_min, src.envelope_max)
    return src.model_copy(update={"id": new_id, "name": name or src.name, "role": role or src.role,
                                  "position_mm": (float(x), -float(y) + 0.0, float(z)),
                                  "rotation_deg": derived_rotation(src.rotation_deg, mode),
                                  "envelope_min": lo, "envelope_max": hi, "reuse": False,
                                  "mirror_of": src.id, "mirror_mode": mode})


def derive_mates(mates: list[dict], derived: dict[str, str]) -> tuple[list[dict], list[str]]:
    """derived {derived_id: source_id}. A derived part's mates are its source's mates with ids mapped (a source that
    has a derived counterpart maps to it, any other part stays). The mate kinds carry no direction, so nothing else
    changes: the flipped envelopes put the derived contact on the mirrored side. Planned mates that involve a derived
    part are replaced, except a mate between a derived part and its own source (it has no source equivalent).
    Returns (mates, notes)."""
    counterpart = {src: dst for dst, src in derived.items()}
    out, notes, seen = [], [], set()

    def add(m):
        key = tuple(sorted((m["a"], m["b"])))
        if m["a"] != m["b"] and key not in seen:
            seen.add(key)
            out.append(m)
    for m in mates:
        a_d, b_d = m["a"] in derived, m["b"] in derived
        own_pair = (a_d and derived[m["a"]] == m["b"]) or (b_d and derived[m["b"]] == m["a"])
        if (a_d or b_d) and not own_pair:
            notes.append(f"mate {m['a']}/{m['b']} replaced: a derived part's mates come from its source's mates")
            continue
        add(dict(m))
    for m in list(out):
        if m["a"] in derived or m["b"] in derived:
            continue
        if m["a"] in counterpart or m["b"] in counterpart:
            add(dict(m, a=counterpart.get(m["a"], m["a"]), b=counterpart.get(m["b"], m["b"])))
    return out, notes


def derived_note(source_id: str, source_version: int, mode: str) -> str:
    return f"derived from {source_id} v{source_version} ({mode})"


def staleness(records: list[PartRecord]) -> dict[str, dict]:
    """Per derived part: {source_id, source_version, latest_source_version, stale}. Stale = the source has a newer
    version than the one the part was derived from. Computed on read, never stored (a stored flag would go stale)."""
    latest = {r.id: r.version for r in records}
    out = {}
    for r in records:
        if not r.derived:
            continue
        src, v = r.derived.get("source_id"), r.derived.get("source_version")
        out[r.id] = {"source_id": src, "source_version": v, "latest_source_version": latest.get(src),
                     "mode": r.derived.get("mode"), "stale": latest.get(src) != v}
    return out
