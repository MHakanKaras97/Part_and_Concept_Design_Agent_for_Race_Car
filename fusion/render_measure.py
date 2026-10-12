"""Measured frame fill of a rendered image or screenshot: the bounding box of the pixels that differ from the
background (mean of the four image corners) by more than `threshold` (sum of |dR|+|dG|+|dB|); 70 leaves out most of
the ground shadow. Used for the render calibration (fusion/render_calibration.json), the re-calibration fallback and
the crop (fusion/render_crop.py)."""
from __future__ import annotations

import io
from typing import Optional


def measure_fill(png: bytes, threshold: int = 70, step: int = 2) -> Optional[dict]:
    import numpy as np
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(png)).convert("RGB")
    except Exception:
        return None
    a = np.asarray(im, dtype=np.int16)
    h, w = a.shape[:2]
    corners = [a[2, 2], a[2, w - 3], a[h - 3, 2], a[h - 3, w - 3]]
    bg = [int(sum(int(c[i]) for c in corners) // 4) for i in range(3)]
    sub = a[::step, ::step]
    mask = np.abs(sub - np.array(bg, dtype=np.int16)).sum(axis=2) > threshold
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    x0, x1, y0, y1 = int(xs.min()) * step, int(xs.max()) * step, int(ys.min()) * step, int(ys.max()) * step
    return {"box": [x0, y0, x1, y1],
            "fill": [round((x1 - x0) / w, 4), round((y1 - y0) / h, 4)],
            "offset": [round(((x0 + x1) / 2 - w / 2) / w, 4), round(((y0 + y1) / 2 - h / 2) / h, 4)],
            "image": [w, h], "background": bg, "threshold": threshold}
