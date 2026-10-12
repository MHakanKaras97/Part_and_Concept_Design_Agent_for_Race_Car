import math
import adsk.core
import adsk.fusion


def build(part):
    L = part.p["length"]
    W = part.p["width"]
    T = part.p["thickness"]
    DL = part.p["diffuser_length"]
    DH = part.p["diffuser_exit_height"]
    D1 = part.p.get("rear_taper_start", 2000.0)
    D2 = part.p.get("rear_taper_end", 2630.0)
    RHW = part.p.get("rear_half_width", 520.0)
    R = part.p.get("front_corner_radius", 250.0)
    FR = part.p.get("edge_fillet", 8.0)
    xf = -400.0
    xr = xf - L
    hw = W / 2
    # Smooth plan outline: rounded front corners, tangent double-arc S-curve taper
    sk = part.sketch(part.plane("z", 0), "SK_floor_outline")
    lines = sk.sketchCurves.sketchLines
    arcs = sk.sketchCurves.sketchArcs

    def P(x, y):
        return sk.modelToSketchSpace(pt(x, y, 0))

    def arc_pt(cx, cy, r, a):
        return (cx + r * math.cos(a), cy + r * math.sin(a))

    xa = xf - D1
    xb = xf - D2
    dx = (D2 - D1) / 2
    dy = (hw - RHW) / 2
    rs = (dx * dx + dy * dy) / (2 * dy)
    mx, my = xa - dx, hw - dy
    c1 = (xa, hw - rs)
    a1e = math.atan2(my - c1[1], mx - c1[0])
    m1 = arc_pt(c1[0], c1[1], rs, (math.pi / 2 + a1e) / 2)
    c2 = (xb, RHW + rs)
    a2s = math.atan2(my - c2[1], mx - c2[0])
    m2 = arc_pt(c2[0], c2[1], rs, (a2s - math.pi / 2) / 2)
    mc = arc_pt(xf - R, hw - R, R, math.pi / 4)
    for s in (1, -1):
        arcs.addByThreePoints(P(xf, s * (hw - R)), P(mc[0], s * mc[1]), P(xf - R, s * hw))
        lines.addByTwoPoints(P(xf - R, s * hw), P(xa, s * hw))
        arcs.addByThreePoints(P(xa, s * hw), P(m1[0], s * m1[1]), P(mx, s * my))
        arcs.addByThreePoints(P(mx, s * my), P(m2[0], s * m2[1]), P(xb, s * RHW))
        lines.addByTwoPoints(P(xb, s * RHW), P(xr, s * RHW))
    lines.addByTwoPoints(P(xf, -(hw - R)), P(xf, hw - R))
    lines.addByTwoPoints(P(xr, -RHW), P(xr, RHW))
    part.extrude(part.profile(sk), "thickness", "EX_floor_plate")
    # Consistent rounded top edge along the whole outline
    body = part.body(0)
    top = None
    best = 0.0
    for f in body.faces:
        bb = f.boundingBox
        if bb.minPoint.z > mm(T) - 0.001 and f.area > best:
            best = f.area
            top = f
    edges = adsk.core.ObjectCollection.create()
    for e in top.edges:
        edges.add(e)
    fillets = part.comp.features.filletFeatures
    finp = fillets.createInput()
    finp.edgeSetInputs.addConstantRadiusEdgeSet(edges, val(FR), True)
    fil = fillets.add(finp)
    fil.name = "FIL_top_edge"
    # Rear diffuser ramp wedge
    xd = xr + DL
    skd = part.sketch(part.plane("y", 0), "SK_diffuser")
    part.polygon(skd, [(xd, 0, T - 10), (xr, 0, T - 10), (xr, 0, DH), (xd, 0, T)])
    part.extrude(part.profile(skd), "diffuser_width", "EX_diffuser", op="join", symmetric=True)
