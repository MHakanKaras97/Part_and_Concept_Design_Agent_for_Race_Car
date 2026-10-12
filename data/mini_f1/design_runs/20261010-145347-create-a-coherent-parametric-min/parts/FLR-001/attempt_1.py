def build(part):
    L = part.p["length"]
    W = part.p["width"]
    T = part.p["thickness"]
    DL = part.p["diffuser_length"]
    DH = part.p["diffuser_exit_height"]
    C = part.p["edge_chamfer"]
    xf = -400.0
    xr = xf - L
    hw = W / 2
    # Plate cross-section (YZ) with chamfered top outer edges, extruded rearwards
    prof = part.section("x", xf, [
        (xf, -hw, 0), (xf, hw, 0), (xf, hw, T - C), (xf, hw - C, T),
        (xf, -hw + C, T), (xf, -hw, T - C)], "SK_floor_section")
    part.extrude(prof, -L, "EX_floor_plate")
    # Tapered front corners in plan
    for s, nm in ((1, "L"), (-1, "R")):
        sk = part.sketch(part.plane("z", 0), "SK_front_corner_" + nm)
        part.polygon(sk, [(xf + 10, s * (hw + 10), 0), (xf + 10, s * (hw - 150), 0),
                          (xf - 300, s * (hw + 10), 0)])
        part.extrude(part.profile(sk), T, "CUT_front_corner_" + nm, op="cut")
    # Rear diffuser ramp wedge
    xd = xr + DL
    sk = part.sketch(part.plane("y", 0), "SK_diffuser")
    part.polygon(sk, [(xd, 0, T - 10), (xr, 0, T - 10), (xr, 0, DH), (xd, 0, T)])
    part.extrude(part.profile(sk), "diffuser_width", "EX_diffuser", op="join", symmetric=True)
