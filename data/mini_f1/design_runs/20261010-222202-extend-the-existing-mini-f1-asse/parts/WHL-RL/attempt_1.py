import math
import adsk.core
import adsk.fusion


def build(part):
    R = part.p["diameter"] / 2.0
    W = part.p["width"]
    rs = part.p["shoulder_radius"]
    rr = part.p["rim_diameter"] / 2.0
    rd = part.p["rim_recess_depth"]
    hb = part.p["hub_boss_radius"]
    hl = part.p["hub_boss_length"]
    y0, y1 = -W / 2.0, W / 2.0
    yh = y0 - hl
    n = 6
    pts = [(0.0, yh, 0.0), (hb, yh, 0.0), (hb, y0, 0.0)]
    # inboard shoulder: centre (R-rs, y0+rs)
    for i in range(n + 1):
        a = math.radians(90.0 * i / n)
        pts.append((R - rs + rs * math.sin(a), y0 + rs - rs * math.cos(a), 0.0))
    # outboard shoulder: centre (R-rs, y1-rs)
    for i in range(n + 1):
        a = math.radians(90.0 * i / n)
        pts.append((R - rs + rs * math.cos(a), y1 - rs + rs * math.sin(a), 0.0))
    pts += [(rr, y1, 0.0), (rr, y1 - rd, 0.0), (0.0, y1 - rd, 0.0)]
    sk = part.sketch(part.plane("z", 0), "SK_wheel_section")
    part.polygon(sk, pts)
    prof = part.profile(sk)
    revs = part.comp.features.revolveFeatures
    inp = revs.createInput(prof, part.comp.yConstructionAxis,
                           adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setAngleExtent(False, adsk.core.ValueInput.createByString("360 deg"))
    rev = revs.add(inp)
    rev.name = "RV_wheel"
