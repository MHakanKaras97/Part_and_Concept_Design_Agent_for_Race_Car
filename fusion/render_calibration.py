"""Measured render framing calibration (fusion/render_calibration.json).

Live (2705.1.30): a local render shows a wider field than the camera passed to startLocalRender implies - the car
came out at ~34 % x 35 % of a 3:2 frame where 78 % x 80 % was planned (the viewport screenshot of the same camera:
~51 % x 53 %). The cause is not documented by the API, so the correction is MEASURED, per camera type and image
aspect ratio: field_scale per axis = mean(planned fill / measured fill) over the renders listed in the entry. The
render camera keeps the eye distance of a true focal-length view and narrows its perspective angle so the car still
fills the planned fraction (fusion/render_frame.py narrow_factor; orthographic: extents divided by field_scale).
Entries are keyed by camera type, aspect ratio and the viewport size; another viewport size gets a note and a
screenshot-measured re-scale (agent/render_run.py RenderRunner._recalibrate), never a silent reuse.
A camera type / aspect ratio without an entry is not corrected and the render record says so (never a reused
factor from another aspect ratio).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

CALIBRATION_PATH = Path(__file__).with_name("render_calibration.json")
ASPECT_TOL = 0.01


def load(path: Path = CALIBRATION_PATH) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["entries"]


def derive(entry: dict) -> tuple[float, float]:
    """(scale_x, scale_y) = mean planned / measured fill per axis over the entry's renders."""
    rows = entry["derived_from"]
    if not rows:
        raise ValueError(f"calibration {entry['id']} lists no measurements")
    sx = sum(r["planned_fill"][0] / r["measured_fill"][0] for r in rows) / len(rows)
    sy = sum(r["planned_fill"][1] / r["measured_fill"][1] for r in rows) / len(rows)
    return round(sx, 4), round(sy, 4)


def field_scale(camera: str, width: int, height: int, viewport=None, entries: Optional[list] = None) -> Optional[dict]:
    """The calibration for this camera type and image aspect ratio, or None (uncalibrated). An entry for another
    viewport size is still returned, with viewport_match False: the caller must not use it silently."""
    aspect = width / float(height)
    found = [e for e in (load() if entries is None else entries)
             if e["camera"] == camera and abs(e["aspect"] - aspect) <= ASPECT_TOL]
    if not found:
        return None
    vp = list(viewport) if viewport is not None else None
    e = next((x for x in found if vp is not None and x.get("viewport") == vp), found[0])
    sx, sy = derive(e)
    return {"id": e["id"], "scale": [sx, sy], "aspect": e["aspect"], "renders": len(e["derived_from"]),
            "views_measured": e.get("views_measured"), "focal_mm": e.get("focal_mm"),
            "viewport": e.get("viewport"), "viewport_now": vp,
            "viewport_match": vp is not None and e.get("viewport") == vp,
            "screenshot_scale": e.get("screenshot_scale")}


def rescale(cal: dict, screenshot_scale_now) -> list:
    """Render factor re-scaled by the screenshot factor measured now vs at calibration (per axis)."""
    s0 = cal["screenshot_scale"]
    return [round(cal["scale"][i] * screenshot_scale_now[i] / s0[i], 4) for i in range(2)]
