import math
import adsk.core
import adsk.fusion


def top_pts(h, zw, yc, zs, bump, cw, zk, tp, n=4, m=6):
    # right shoulder (quarter ellipse, vertical start at zw), crowned deck, left shoulder.
    # crown keeps its original width cw (unchanged centre heights); deck edge yc may differ.
    # points above zk are pinched inwards smoothly (tp = pinch at the top), below zk unchanged.
    def crown(y):
        if abs(y) >= cw:
            return zs
        return zs + bump * math.cos(math.pi / 2.0 * y / cw) ** 2
    ze = crown(yc)
    ry = h - yc
    rz = ze - zw
    ztop = crown(0.0)
    raw = []
    for k in range(n + 1):
        a = k / float(n) * math.pi / 2.0
        raw.append((yc + ry * math.cos(a), zw + rz * math.sin(a)))
    for j in range(1, m):
        y = yc - 2.0 * yc * j / float(m)
        raw.append((y, crown(y)))
    for k in range(n, -1, -1):
        a = k / float(n) * math.pi / 2.0
        raw.append((-(yc + ry * math.cos(a)), zw + rz * math.sin(a)))
    pts = []
    for (y, z) in raw:
        s = 0.0
        if ztop > zk and z > zk:
            s = (z - zk) / (ztop - zk)
        pts.append((y * (1.0 - tp * s * s), z))
    return pts


def sec(part, x, w, zb, zw, yc, zs, bump, cw, cb, zk, tp, name):
    # flat bottom at zb, bottom chamfers cb, straight side walls up to zw,
    # smooth fitted-spline top (rounded shoulders + crown). same topology for all sections.
    h = w / 2.0
    sk = part.sketch(part.plane("x", x), name)
    coll = adsk.core.ObjectCollection.create()
    for (y, z) in top_pts(h, zw, yc, zs, bump, cw, zk, tp):
        coll.add(sk.modelToSketchSpace(pt(x, y, z)))
    sp = sk.sketchCurves.sketchFittedSplines.add(coll)
    lines = sk.sketchCurves.sketchLines
    l1 = lines.addByTwoPoints(sp.startSketchPoint, sk.modelToSketchSpace(pt(x, h, zb + cb)))
    l2 = lines.addByTwoPoints(l1.endSketchPoint, sk.modelToSketchSpace(pt(x, h - cb, zb)))
    l3 = lines.addByTwoPoints(l2.endSketchPoint, sk.modelToSketchSpace(pt(x, -h + cb, zb)))
    l4 = lines.addByTwoPoints(l3.endSketchPoint, sk.modelToSketchSpace(pt(x, -h, zb + cb)))
    lines.addByTwoPoints(l4.endSketchPoint, sp.endSketchPoint)
    return part.profile(sk)


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
    zn = zb + H * 0.48 - 110.0

    profs = [
        # rear: deck narrowed to 220, shoulders roll down to the wall at Z=560, crown unchanged
        sec(part, x_rear, W, zb, 560.0, 220.0, zb + H - 20.0, 20.0, W / 2.0 - 120.0, 80.0, 2000.0, 0.0, "SK_sec_rear"),
        sec(part, -2600, W * 0.97, zb, 560.0, 330.0, 680.0, 20.0, W * 0.97 / 2.0 - 120.0, 75.0, 2000.0, 0.0, "SK_sec_cockpit_rear"),
        # in front of cockpit: shoulder kept below Z=560, rounder dome above
        sec(part, -1400, W * 0.85, zb, 542.0, W * 0.85 / 2.0 - 110.0, 602.0, 35.0, W * 0.85 / 2.0 - 110.0, 65.0, 560.0, 0.12, "SK_sec_cockpit_front"),
        # nose root: kept below Z=300, slimmer top above
        sec(part, -400, W * 0.55, zb, zn, W * 0.55 / 2.0 - 110.0, zn + 110.0, 14.0, W * 0.55 / 2.0 - 110.0, 30.0, 300.0, 0.25, "SK_sec_nose_root"),
        sec(part, 550, nw, zb, zb + nh - 60.0, nw / 2.0 - 60.0, zb + nh, 0.0, nw / 2.0 - 60.0, 15.0, 2000.0, 0.0, "SK_sec_nose_tip"),
    ]
    part.loft(profs, "LF_tub", op="new")

    # cockpit centre
    x0 = -2300.0
    x1 = x0 + cl
    # raised rim block (interior removed by cockpit cut), built separately to round its outer edges
    zr0 = 560.0
    zr_top = 680.0 + rim
    sk = part.sketch(part.plane("z", zr0), "SK_cockpit_rim")
    part.polygon(sk, [
        (x0 - 60, -cw / 2 - 60, zr0), (x1 + 60, -cw / 2 - 60, zr0),
        (x1 + 60, cw / 2 + 60, zr0), (x0 - 60, cw / 2 + 60, zr0),
    ])
    part.extrude(part.profile(sk), zr_top - zr0, "EX_cockpit_rim", op="new")

    feats = part.comp.features
    rimb = part.body(1)
    vert = adsk.core.ObjectCollection.create()
    for e in rimb.edges:
        a = e.startVertex.geometry
        b = e.endVertex.geometry
        if abs(a.x - b.x) < 1e-4 and abs(a.y - b.y) < 1e-4:
            vert.add(e)
    fin = feats.filletFeatures.createInput()
    fin.edgeSetInputs.addConstantRadiusEdgeSet(vert, val(40.0), True)
    feats.filletFeatures.add(fin).name = "FIL_rim_corners"

    rimb = part.body(1)
    topf = None
    for f in rimb.faces:
        if f.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType and abs(f.pointOnFace.z - mm(zr_top)) < 1e-4:
            topf = f
    tedges = adsk.core.ObjectCollection.create()
    for e in topf.edges:
        tedges.add(e)
    fin2 = feats.filletFeatures.createInput()
    fin2.edgeSetInputs.addConstantRadiusEdgeSet(tedges, val(20.0), True)
    feats.filletFeatures.add(fin2).name = "FIL_rim_top_outer"

    tools = adsk.core.ObjectCollection.create()
    tools.add(part.body(1))
    ci = feats.combineFeatures.createInput(part.body(0), tools)
    ci.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
    feats.combineFeatures.add(ci).name = "CMB_rim"

    # cockpit opening cut from above
    zc = 760.0
    skc = part.sketch(part.plane("z", zc), "SK_cockpit_opening")
    part.polygon(skc, [
        (x0, -cw / 2, zc), (x1, -cw / 2, zc),
        (x1, cw / 2, zc), (x0, cw / 2, zc),
    ])
    part.extrude(part.profile(skc), -(zc - 140.0), "CUT_cockpit", op="cut")
