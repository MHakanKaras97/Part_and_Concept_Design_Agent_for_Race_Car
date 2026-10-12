def sec(part, x, w, zb, zt, c, name):
    h = w / 2.0
    pts = [
        (x, -h + c, zb), (x, h - c, zb), (x, h, zb + c), (x, h, zt - c),
        (x, h - c, zt), (x, -h + c, zt), (x, -h, zt - c), (x, -h, zb + c),
    ]
    return part.section("x", x, pts, name)


def build(part):
    p = part.p
    W = p["rear_width"]
    H = p["rear_height"]
    nw = p["nose_tip_width"]
    nh = p["nose_tip_height"]
    rim = p["cockpit_rim_height"]
    cl = p["cockpit_opening_length"]
    cw = p["cockpit_opening_width"]
    zb = 30.0
    x_rear = 550.0 - p["length"]

    profs = [
        sec(part, x_rear, W, zb, zb + H, 80, "SK_sec_rear"),
        sec(part, -2600, W * 0.97, zb, zb + H - 40, 75, "SK_sec_cockpit_rear"),
        sec(part, -1400, W * 0.85, zb, zb + H - 110, 65, "SK_sec_cockpit_front"),
        sec(part, -400, W * 0.55, zb, zb + H * 0.56, 50, "SK_sec_nose_root"),
        sec(part, 550, nw, zb, zb + nh, 30, "SK_sec_nose_tip"),
    ]
    part.loft(profs, "LF_tub", op="new")

    # cockpit centre
    x0 = -2300.0
    x1 = x0 + cl
    # raised rim block (interior removed by cockpit cut)
    zr0 = 560.0
    zr_top = 680.0 + rim
    sk = part.sketch(part.plane("z", zr0), "SK_cockpit_rim")
    part.polygon(sk, [
        (x0 - 60, -cw / 2 - 60, zr0), (x1 + 60, -cw / 2 - 60, zr0),
        (x1 + 60, cw / 2 + 60, zr0), (x0 - 60, cw / 2 + 60, zr0),
    ])
    part.extrude(part.profile(sk), zr_top - zr0, "EX_cockpit_rim", op="join")

    # cockpit opening cut from above
    zc = 760.0
    skc = part.sketch(part.plane("z", zc), "SK_cockpit_opening")
    part.polygon(skc, [
        (x0, -cw / 2, zc), (x1, -cw / 2, zc),
        (x1, cw / 2, zc), (x0, cw / 2, zc),
    ])
    part.extrude(part.profile(skc), -(zc - 140.0), "CUT_cockpit", op="cut")
