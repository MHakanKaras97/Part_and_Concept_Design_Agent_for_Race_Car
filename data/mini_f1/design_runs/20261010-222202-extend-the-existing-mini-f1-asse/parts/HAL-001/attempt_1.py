import math

def build(part):
    t = part.p["bar_thickness"]
    zt = part.p["top_height"]
    xr = -part.p["rear_foot_x_offset"]
    hs = part.p["rear_foot_half_span"]
    pw = part.p["pillar_width"]
    h = t / 2.0
    z0 = zt - h
    z1 = zt + h
    xc = -350.0
    xfront = -80.0
    xback = xr - h
    ax_o = (xfront + h) - xc
    ax_i = (xfront - h) - xc
    ay_o = hs + h
    ay_i = hs - h
    n = 12
    pts = [(xback, ay_o, z0)]
    for i in range(n + 1):
        a = math.radians(90.0 - 180.0 * i / n)
        pts.append((xc + ax_o * math.cos(a), ay_o * math.sin(a), z0))
    pts.append((xback, -ay_o, z0))
    pts.append((xback, -ay_i, z0))
    for i in range(n + 1):
        a = math.radians(-90.0 + 180.0 * i / n)
        pts.append((xc + ax_i * math.cos(a), ay_i * math.sin(a), z0))
    pts.append((xback, ay_i, z0))
    sk = part.sketch(part.plane("z", z0, "PL_hoop"), "SK_hoop")
    part.polygon(sk, pts)
    part.extrude(part.profile(sk), z1 - z0, "EX_hoop")

    for s, nm in ((1, "L"), (-1, "R")):
        skf = part.sketch(part.plane("z", 0, "PL_foot_" + nm), "SK_foot_" + nm)
        yc = s * hs
        part.polygon(skf, [(xr - h, yc - h, 0), (xr + h, yc - h, 0),
                           (xr + h, yc + h, 0), (xr - h, yc + h, 0)])
        part.extrude(part.profile(skf), z1, "EX_foot_" + nm, op="join")

    pp = pw / 2.0
    skp = part.sketch(part.plane("y", 0, "PL_pillar"), "SK_pillar")
    part.polygon(skp, [(-pp, 0, 0), (pp, 0, 0), (xfront + h, 0, z1),
                       (xfront - h, 0, z1), (xfront - h, 0, z0 + 10.0)])
    part.extrude(part.profile(skp), pw, "EX_pillar", op="join", symmetric=True)
