import math
import adsk.core
import adsk.fusion


def teardrop(hl, hh, y, k):
    # XZ teardrop: rounded front (+X), slightly tapered flat rear (-X, glass side)
    a = hl / 2 * k
    b = hh / 2 * k
    pts = []
    n = 10
    for i in range(n + 1):
        t = math.radians(-90.0 + 180.0 * i / n)
        pts.append((round(a * math.cos(t), 4), y, round(b * math.sin(t), 4)))
    pts.append((-a, y, 0.7 * b))
    pts.append((-a, y, -0.7 * b))
    return pts


def build(part):
    hl = part.p["housing_length"]
    hw = part.p["housing_width"]
    hh = part.p["housing_height"]
    cy = part.p["housing_center_y"]
    s = part.p["stalk_size"]
    y0 = part.p["stalk_start_y"]

    # Housing: lofted rounded teardrop, slightly tapered towards both ends
    y_in = cy - hw / 2
    y_out = cy + hw / 2
    p_in = part.section("y", y_in, teardrop(hl, hh, y_in, 0.85), "SK_housing_in")
    p_mid = part.section("y", cy, teardrop(hl, hh, cy, 1.0), "SK_housing_mid")
    p_out = part.section("y", y_out, teardrop(hl, hh, y_out, 0.78), "SK_housing_out")
    part.loft([p_in, p_mid, p_out], "LF_housing")

    # Slim flattened stalk with rounded (elliptic) section, 10 mm into the housing
    y1 = y_in + 10.0
    ym = (y0 + y1) / 2
    a = s / 2
    b = s * 0.25
    spts = []
    m = 16
    for i in range(m):
        t = 2 * math.pi * i / m
        spts.append((round(a * math.cos(t), 4), ym, round(b * math.sin(t), 4)))
    sks = part.sketch(part.plane("y", ym, "PL_stalk_mid"), "SK_stalk")
    part.polygon(sks, spts)
    part.extrude(part.profile(sks), y1 - y0, "EX_stalk", op="join", symmetric=True)
