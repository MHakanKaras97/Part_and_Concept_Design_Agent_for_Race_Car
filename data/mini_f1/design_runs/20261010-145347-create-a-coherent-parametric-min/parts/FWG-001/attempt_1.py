def build(part):
    S = part.p["span"]
    T = part.p["endplate_thickness"]
    yi = S / 2 - T
    pl0 = part.plane("y", 0)

    def wing(name, pts, op):
        sk = part.sketch(pl0, "SK_" + name)
        part.polygon(sk, [(x, 0, z) for (x, z) in pts])
        part.extrude(part.profile(sk), "span", "EX_" + name, op=op, symmetric=True)

    main = [(1150, 85), (1130, 98), (1060, 100), (950, 98), (850, 93), (800, 90),
            (800, 84), (900, 75), (1000, 70), (1100, 72), (1140, 78)]
    wing("main_plane", main, "new")

    flap1 = [(860, 115), (840, 130), (780, 138), (720, 140), (680, 142),
             (680, 134), (740, 122), (800, 108), (845, 104)]
    wing("flap1", flap1, "join")

    flap2 = [(740, 160), (720, 175), (660, 183), (600, 185), (560, 187),
             (560, 179), (620, 167), (680, 153), (725, 149)]
    wing("flap2", flap2, "join")

    # Endplates
    ep = [(555, 50), (1150, 50), (1150, 250), (1080, 330), (555, 330)]
    skr = part.sketch(part.plane("y", yi), "SK_endplate_L")
    part.polygon(skr, [(x, yi, z) for (x, z) in ep])
    part.extrude(part.profile(skr), T, "EX_endplate_L", op="join")
    skl = part.sketch(part.plane("y", -yi), "SK_endplate_R")
    part.polygon(skl, [(x, -yi, z) for (x, z) in ep])
    part.extrude(part.profile(skl), -T, "EX_endplate_R", op="join")

    # Central mount / pylon block
    skm = part.sketch(pl0, "SK_mount")
    part.polygon(skm, [(550, 0, 100), (900, 0, 95), (900, 0, 160), (750, 0, 230), (550, 0, 230)])
    part.extrude(part.profile(skm), "mount_width", "EX_mount", op="join", symmetric=True)
