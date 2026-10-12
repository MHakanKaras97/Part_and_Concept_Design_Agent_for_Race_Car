import math

def build(part):
    AL = part.p["airbox_length"]
    AW = part.p["airbox_half_width"]
    AH = part.p["airbox_height"]
    SL = part.p["spine_length"]
    SW = part.p["spine_half_width"]
    SE = part.p["spine_end_height"]

    # Airbox: rounded-top cross-section on the X=0 face, extruded rearwards
    zs = AH - 120.0
    pts = [(0.0, -AW, 0.0), (0.0, AW, 0.0), (0.0, AW, zs)]
    n = 10
    for i in range(1, n):
        a = math.pi * i / n
        pts.append((0.0, AW * math.cos(a), zs + 120.0 * math.sin(a)))
    pts.append((0.0, -AW, zs))
    sk = part.sketch(part.plane("x", 0.0), "SK_airbox")
    part.polygon(sk, pts)
    part.extrude(part.profile(sk), -AL, "EX_airbox")

    # Shark-fin spine: side profile in XZ, overlapping the airbox by 50 mm
    x_end = -AL - SL
    sk2 = part.sketch(part.plane("y", 0.0), "SK_spine")
    part.polygon(sk2, [
        (x_end, 0.0, 0.0),
        (-AL + 50.0, 0.0, 0.0),
        (-AL + 50.0, 0.0, 300.0),
        (-AL, 0.0, 300.0),
        (x_end, 0.0, SE),
    ])
    part.extrude(part.profile(sk2), 2.0 * SW, "EX_spine", op="join", symmetric=True)

    # Front intake opening: ~160 wide x 120 high, 150 deep pocket
    sk3 = part.sketch(part.plane("x", 0.0), "SK_intake")
    part.polygon(sk3, [
        (0.0, -80.0, 160.0), (0.0, 80.0, 160.0),
        (0.0, 80.0, 280.0), (0.0, -80.0, 280.0),
    ])
    part.extrude(part.profile(sk3), -150.0, "CUT_intake", op="cut")
