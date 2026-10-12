"""Coordinate systems and transforms (pure, deterministic, unit-tested).

VCS (project vehicle coordinate system, original brief §8, docs/dev-log/original_brief.md):  +X front, +Y left, +Z up, mm.
FIA Car Coordinate System (2026 Section C, Art. C2.1.1): X increases rearwards,
Y increases to the driver's right, Z upwards, mm.
=> FIA axes = VCS axes rotated 180° about Z.  x_fia = -x_vcs + x0, y_fia = -y_vcs, z_fia = z_vcs.
The X origin offset x0 is a vehicle-level datum, unknown until the vehicle layout exists.

Fusion API lengths are in cm; all project data is in mm. Convert only through mm_to_cm / cm_to_mm.
"""
from __future__ import annotations

import numpy as np

from vehicle.models import Pose, Vec3

MM_PER_CM = 10.0


def mm_to_cm(v: float) -> float:
    return v / MM_PER_CM


def cm_to_mm(v: float) -> float:
    return v * MM_PER_CM


def rotation_matrix(roll_deg: float, pitch_deg: float, yaw_deg: float) -> np.ndarray:
    """R = Rz(yaw) @ Ry(pitch) @ Rx(roll), angles in degrees, right-handed."""
    r, p, y = np.radians([roll_deg, pitch_deg, yaw_deg])
    rx = np.array([[1, 0, 0], [0, np.cos(r), -np.sin(r)], [0, np.sin(r), np.cos(r)]])
    ry = np.array([[np.cos(p), 0, np.sin(p)], [0, 1, 0], [-np.sin(p), 0, np.cos(p)]])
    rz = np.array([[np.cos(y), -np.sin(y), 0], [np.sin(y), np.cos(y), 0], [0, 0, 1]])
    return rz @ ry @ rx


def rotation_to_euler(r: np.ndarray) -> tuple[float, float, float]:
    """(roll, pitch, yaw) deg with R = Rz(yaw) @ Ry(pitch) @ Rx(roll); pitch in [-90, 90], yaw/roll in (-180, 180].
    Entries are rounded to 1e-12 first so exact quarter/half turns come out exact (no -180 from -0.0 noise)."""
    r = np.round(np.asarray(r, dtype=float), 12) + 0.0
    pitch = np.degrees(np.arcsin(np.clip(-r[2, 0], -1.0, 1.0)))
    if abs(r[2, 0]) < 1.0 - 1e-12:
        roll = np.degrees(np.arctan2(r[2, 1], r[2, 2]))
        yaw = np.degrees(np.arctan2(r[1, 0], r[0, 0]))
    else:                                                # gimbal lock: put the whole turn into yaw
        roll, yaw = 0.0, np.degrees(np.arctan2(-r[0, 1], r[1, 1]))

    def norm(a: float) -> float:
        a = round(float(a), 9) + 0.0
        return 180.0 if a == -180.0 else a
    return norm(roll), norm(pitch), norm(yaw)


def pose_to_matrix(pose: Pose) -> np.ndarray:
    """4x4 homogeneous matrix mapping local component coordinates -> VCS."""
    m = np.eye(4)
    m[:3, :3] = rotation_matrix(*pose.rotation_deg)
    m[:3, 3] = pose.position
    return m


def invert(m: np.ndarray) -> np.ndarray:
    r, t = m[:3, :3], m[:3, 3]
    inv = np.eye(4)
    inv[:3, :3] = r.T
    inv[:3, 3] = -r.T @ t
    return inv


def transform_point(m: np.ndarray, p: Vec3) -> Vec3:
    v = m @ np.array([p[0], p[1], p[2], 1.0])
    return (float(v[0]), float(v[1]), float(v[2]))


def transform_vector(m: np.ndarray, v: Vec3) -> Vec3:
    w = m[:3, :3] @ np.array(v, dtype=float)
    return (float(w[0]), float(w[1]), float(w[2]))


def local_to_vcs(pose: Pose, p: Vec3) -> Vec3:
    return transform_point(pose_to_matrix(pose), p)


def vcs_to_local(pose: Pose, p: Vec3) -> Vec3:
    return transform_point(invert(pose_to_matrix(pose)), p)


def bbox_to_vcs(pose: Pose, bmin: Vec3, bmax: Vec3) -> tuple[Vec3, Vec3]:
    """Axis-aligned VCS box enclosing a local axis-aligned box (all 8 corners transformed)."""
    m = pose_to_matrix(pose)
    corners = np.array([transform_point(m, (x, y, z))
                        for x in (bmin[0], bmax[0]) for y in (bmin[1], bmax[1]) for z in (bmin[2], bmax[2])])
    lo, hi = corners.min(axis=0), corners.max(axis=0)
    return (tuple(map(float, lo)), tuple(map(float, hi)))  # type: ignore[return-value]


def vcs_to_fia(p: Vec3, x_offset_mm: float = 0.0) -> Vec3:
    """VCS point -> FIA Car Coordinate System (C2.1.1). x_offset_mm = FIA X of the VCS origin."""
    return (-p[0] + x_offset_mm, -p[1], p[2])


def fia_to_vcs(p: Vec3, x_offset_mm: float = 0.0) -> Vec3:
    return (-(p[0] - x_offset_mm), -p[1], p[2])


def matrix_to_fusion_cm(m: np.ndarray) -> list[float]:
    """Row-major 16 floats for adsk.core.Matrix3D.setWithArray, translation converted to cm."""
    f = m.copy()
    f[:3, 3] = f[:3, 3] / MM_PER_CM
    return [float(x) for x in f.reshape(-1)]
