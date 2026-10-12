def build(part):
    # stations: (x, inner y, outer y, top z)
    st = [
        (0.0, 280.0, 620.0, 370.0),
        (-500.0, 345.7, 700.0, 379.0),
        (-1100.0, 390.0, 645.0, 390.0),
        (-1900.0, 426.0, 572.0, 306.5),
        (-2250.0, 431.0, 540.0, 270.0),
    ]
    profs = []
    for i, (x, yi, yo, zt) in enumerate(st):
        pts = [
            (x, yi, 0.0),
            (x, yo - 60.0, 0.0),
            (x, yo, 100.0),
            (x, yo, zt - 60.0),
            (x, yo - 60.0, zt),
            (x, yi + 40.0, zt),
            (x, yi, zt - 40.0),
        ]
        profs.append(part.section("x", x, pts, "SK_sec%d" % i))
    part.loft(profs, "LF_sidepod")

    # radiator inlet pocket on the front face (symmetric cut -> 120 mm into the body)
    d = part.p["inlet_depth"]
    sk = part.sketch(part.plane("x", 0.0), "SK_inlet")
    part.polygon(sk, [(0.0, 360.0, 145.0), (0.0, 560.0, 145.0),
                      (0.0, 560.0, 295.0), (0.0, 360.0, 295.0)])
    part.extrude(part.profile(sk), 2.0 * d, "CUT_inlet", op="cut", symmetric=True)
