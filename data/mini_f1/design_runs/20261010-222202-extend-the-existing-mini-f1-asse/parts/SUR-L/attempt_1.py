import math

def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

def beam_box(tbm, p0, p1, size, ext):
    d = vsub(p1, p0)
    L = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)
    c = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, (p0[2] + p1[2]) / 2)
    ld = adsk.core.Vector3D.create(d[0], d[1], d[2])
    ld.normalize()
    wd = ld.crossProduct(adsk.core.Vector3D.create(0, 1, 0))
    wd.normalize()
    obb = adsk.core.OrientedBoundingBox3D.create(pt(c[0], c[1], c[2]), ld, wd, mm(L + 2 * ext), mm(size), mm(size))
    return tbm.createBox(obb)

def aa_box(tbm, x0, x1, y0, y1, z0, z1):
    obb = adsk.core.OrientedBoundingBox3D.create(
        pt((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2),
        adsk.core.Vector3D.create(1, 0, 0), adsk.core.Vector3D.create(0, 1, 0),
        mm(x1 - x0), mm(y1 - y0), mm(z1 - z0))
    return tbm.createBox(obb)

def build(part):
    tbm = adsk.fusion.TemporaryBRepManager.get()
    s = part.p["beam_size"]
    yo = part.p["outboard_face_y"]
    yi = part.p["inboard_y"]
    hx = part.p["pickup_half_spread_x"]
    zlo = part.p["lower_outboard_z"]
    zuo = part.p["upper_outboard_z"]
    zli = part.p["lower_inboard_z"]
    zui = part.p["upper_inboard_z"]
    beams = [
        ((hx, yi, zli), (0, yo, zlo)),
        ((-hx, yi, zli), (0, yo, zlo)),
        ((hx, yi, zui), (0, yo, zuo)),
        ((-hx, yi, zui), (0, yo, zuo)),
        ((50, yo, 340), (-100, 435, 460)),
    ]
    union = adsk.fusion.BooleanTypes.UnionBooleanType
    body = None
    for p0, p1 in beams:
        b = beam_box(tbm, p0, p1, s, 12)
        if body is None:
            body = b
        else:
            tbm.booleanOperation(body, b, union)
    # outboard flat pads and upright link pad on Y = yo
    pads = [
        aa_box(tbm, -30, 30, yo - 15, yo, zlo - 25, zlo + 25),
        aa_box(tbm, -30, 30, yo - 15, yo, zuo - 25, zuo + 25),
        aa_box(tbm, -30, 40, yo - 15, yo, zlo - 10, zuo + 10),
    ]
    for pd in pads:
        tbm.booleanOperation(body, pd, union)
    clip = aa_box(tbm, -150, 150, 425, yo, 150, 500)
    tbm.booleanOperation(body, clip, adsk.fusion.BooleanTypes.IntersectionBooleanType)
    bf = part.comp.features.baseFeatures.add()
    bf.name = "BF_rear_left_suspension"
    bf.startEdit()
    added = part.comp.bRepBodies.add(body, bf)
    bf.finishEdit()
    added.name = "SUR_L_links"
