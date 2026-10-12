def build(part):
    span = part.p["span"]
    ept = part.p["endplate_thickness"]
    st = part.p["support_thickness"]
    sy = part.p["support_spacing"] / 2.0

    # Main plane (leading edge at front, +X)
    sk = part.sketch(part.plane("y", 0), "SK_mainplane")
    mp = [(-4050, 885), (-4080, 898), (-4200, 905), (-4400, 900), (-4400, 894),
          (-4250, 872), (-4120, 870), (-4070, 875)]
    part.polygon(sk, [(x, 0, z) for x, z in mp])
    part.extrude(part.profile(sk), "span", "EX_mainplane", symmetric=True)

    # Flap above/behind with slot gap
    skf = part.sketch(part.plane("y", 0), "SK_flap")
    fp = [(-4250, 932), (-4265, 950), (-4350, 975), (-4450, 1000), (-4450, 985),
          (-4350, 948), (-4280, 930)]
    part.polygon(skf, [(x, 0, z) for x, z in fp])
    part.extrude(part.profile(skf), "span", "EX_flap", op="join", symmetric=True)

    # Endplates
    yin = span / 2.0 - ept
    ep = [(-4450, 700), (-3950, 700), (-3950, 1100), (-4450, 1100)]
    skl = part.sketch(part.plane("y", yin), "SK_endplate_L")
    part.polygon(skl, [(x, yin, z) for x, z in ep])
    part.extrude(part.profile(skl), ept, "EX_endplate_L", op="join")
    skr = part.sketch(part.plane("y", -yin), "SK_endplate_R")
    part.polygon(skr, [(x, -yin, z) for x, z in ep])
    part.extrude(part.profile(skr), -ept, "EX_endplate_R", op="join")

    # Support plates sweeping from monocoque rear face up to main plane underside
    sp = [(-3700, 400), (-3700, 500), (-4100, 888), (-4300, 888), (-4300, 830), (-3800, 400)]
    for nm, yc in (("L", sy), ("R", -sy)):
        sks = part.sketch(part.plane("y", yc), "SK_support_" + nm)
        part.polygon(sks, [(x, yc, z) for x, z in sp])
        part.extrude(part.profile(sks), st, "EX_support_" + nm, op="join", symmetric=True)
