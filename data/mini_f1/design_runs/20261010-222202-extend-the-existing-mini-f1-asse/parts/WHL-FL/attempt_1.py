import math
import adsk.core
import adsk.fusion


def build(part):
    R = part.p["diameter"] / 2.0
    W = part.p["width"]
    s = part.p["shoulder_radius"]
    rr = part.p["rim_diameter"] / 2.0
    rd = part.p["rim_recess_depth"]
    hb = part.p["hub_boss_radius"]
    hl = part.p["hub_boss_length"]
    y0, y1 = -W / 2.0, W / 2.0
    yh = y0 - hl

    pts = [(0.0, yh), (hb, yh), (hb, y0), (R - s, y0)]
    n = 6
    # inboard shoulder: centre (R-s, y0+s), from angle -90 to 0 (in r,y as x,y)
    for i in range(1, n):
        a = -math.pi / 2 + (math.pi / 2) * i / n
        pts.append((R - s + s * math.cos(a), y0 + s + s * math.sin(a)))
    pts.append((R, y0 + s))
    pts.append((R, y1 - s))
    for i in range(1, n):
        a = (math.pi / 2) * i / n
        pts.append((R - s + s * math.cos(a), y1 - s + s * math.sin(a)))
    pts.append((R - s, y1))
    pts.append((rr, y1))
    pts.append((rr, y1 - rd))
    pts.append((0.0, y1 - rd))

    sk = part.sketch(part.plane("z", 0), "SK_wheel_section")
    part.polygon(sk, [(r, y, 0.0) for (r, y) in pts])
    prof = part.profile(sk)

    comp = part.comp
    revs = comp.features.revolveFeatures
    inp = revs.createInput(prof, comp.yConstructionAxis,
                           adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.setAngleExtent(False, adsk.core.ValueInput.createByString("360 deg"))
    rev = revs.add(inp)
    rev.name = "RV_wheel"
