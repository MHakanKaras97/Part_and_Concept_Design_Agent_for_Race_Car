"""Crop a finished render around the car (PIL, zero Fusion calls).

The render camera (long-lens: true focal-length distance, narrowed angle that Fusion compensates by moving the eye
back) leaves the car at ~1/3 of the frame; the crop makes it fill `fill` of the output with an even margin:

    car box   measured in the image (fusion/render_measure.py: pixels that differ from the corner background)
    window    aspect `aspect` (width / height), centred on the car box, the larger relative side = fill
    padding   a window that reaches past the image edge is padded with the measured background colour (solid
              render background), so the margin stays even instead of shifting the car off-centre
    output    resized DOWN to `target` (Lanczos) when the window is larger; a smaller window is kept at its native
              size and reported (never upscaled silently)
The crop works only from the car's measured position in the image: it does not depend on the Fusion viewport.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

MIN_CAR_FRACTION = 0.02      # a car box smaller than this (either side) is treated as "nearly empty": no crop


def crop_plan(car_box, image_size, fill: float = 0.8, aspect: float = 1.5, target=None) -> dict:
    """car_box: (x0, y0, x1, y1) pixels, inclusive of the car; image_size: (w, h); target: (w, h) output or None.
    Returns the window (may reach past the image: padding), the native and output sizes and the scale factor."""
    w, h = image_size
    x0, y0, x1, y1 = car_box
    cw, ch = x1 - x0 + 1, y1 - y0 + 1
    if cw < MIN_CAR_FRACTION * w or ch < MIN_CAR_FRACTION * h:
        return {"skipped": f"car box {cw}x{ch} px is under {MIN_CAR_FRACTION:.0%} of the {w}x{h} image"}
    win_w = max(cw / fill, ch / fill * aspect)
    win_h = win_w / aspect
    nw, nh = int(math.ceil(win_w)), int(math.ceil(win_h))
    nh = max(nh, int(round(nw / aspect)))                # integer sizes at the aspect ratio (+/- 1 px)
    nw = int(round(nh * aspect))
    cx, cy = (x0 + x1 + 1) / 2.0, (y0 + y1 + 1) / 2.0
    left, top = int(round(cx - nw / 2.0)), int(round(cy - nh / 2.0))
    box = [left, top, left + nw, top + nh]
    pad = [max(0, -box[0]), max(0, -box[1]), max(0, box[2] - w), max(0, box[3] - h)]
    edge = x0 <= 0 or y0 <= 0 or x1 >= w - 1 or y1 >= h - 1
    out = {"box": box, "native_size": [nw, nh], "padded": pad, "car_box": [x0, y0, x1, y1],
           "car_fill_full": [round(cw / w, 4), round(ch / h, 4)],
           "car_fill_planned": [round(cw / nw, 4), round(ch / nh, 4)],
           "car_touches_edge": edge, "target_size": list(target) if target else None, "fill": fill, "aspect": aspect}
    if target and (nw > target[0] or nh > target[1]):
        s = min(target[0] / nw, target[1] / nh)
        out.update(output_size=[int(round(nw * s)), int(round(nh * s))], factor=round(s, 4), resized="down")
    else:
        out.update(output_size=[nw, nh], factor=1.0, resized="none",
                   note=(f"native crop {nw}x{nh} is smaller than the target {target[0]}x{target[1]}: kept at native "
                         f"size, NOT upscaled") if target else None)
    return out


def apply_crop(src: Path, dst: Path, plan: dict, background) -> dict:
    """Write the cropped (padded, resized down) image; returns the measured car fill of the result."""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    x0, y0, x1, y1 = plan["box"]
    canvas = Image.new("RGB", (x1 - x0, y1 - y0), tuple(background))
    canvas.paste(im, (-x0, -y0))                          # padding = background where the window leaves the image
    if plan["resized"] == "down":
        canvas = canvas.resize(tuple(plan["output_size"]), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst, "PNG")
    return {"size": list(canvas.size)}


def crop_render(src: Path, dst: Path, fill: float = 0.8, aspect: float = 1.5, target=None,
                threshold: int = 70) -> Optional[dict]:
    """Measure the car in `src`, crop it to `dst`; returns the crop record (or {"skipped": why})."""
    from PIL import Image
    from fusion.render_measure import measure_fill
    try:
        Image.open(src).verify()
    except Exception as e:
        return {"skipped": f"the render could not be read as an image ({type(e).__name__})"}
    m = measure_fill(Path(src).read_bytes(), threshold=threshold, step=1)
    if not m:
        return {"skipped": "no car found in the image (nearly empty)"}
    plan = crop_plan(m["box"], m["image"], fill, aspect, target)
    if plan.get("skipped"):
        return plan
    got = apply_crop(src, dst, plan, m["background"])
    after = measure_fill(Path(dst).read_bytes(), threshold=threshold, step=1)
    plan.update(output_size=got["size"], background=m["background"], threshold=threshold,
                car_fill_cropped=after["fill"] if after else None,
                car_offset_cropped=after["offset"] if after else None)
    return plan
