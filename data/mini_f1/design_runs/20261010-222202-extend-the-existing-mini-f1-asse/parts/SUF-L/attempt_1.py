import math
import adsk.core
import adsk.fusion


def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vnorm(a):
    l = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
    return (a[0] / l, a[1] / l, a[2] / l), l


def beam(tb, p0, p1, s, ext0, ext1):
    d, l = vnorm(vsub(p1, p0))
    a = (p0[0] - d[0] * ext0, p0[1] - d[1] * ext0, p0[2] - d[2] * ext0)
    b = (p1[0] + d[0] * ext1, p1[1] + d[1] * ext1, p1[2] + d[2] * ext1)
    c = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)
    L = l + ext0 + ext1
    w, wl = vnorm((d[1], -d[0], 0.0))
    obb = adsk.core.OrientedBoundingBox3D.create(
        adsk.core.Point3D.create(mm(c[0]), mm(c[1]), mm(c[2])),
        adsk.core.Vector3D.create(d[0], d[1], d[2]),
        adsk.core.Vector3D.create(w[0], w[1], w[2]),
        mm(L), mm(s), mm(s))
    return tb.createBox(obb)


def abox(tb, lo, hi):
    c = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2)
    obb = adsk.core.OrientedBoundingBox3D.create(
        adsk.core.Point3D.create(mm(c[0]), mm(c[1]), mm(c[2])),
        adsk.core.Vector3D.create(1, 0, 0),
        adsk.core.Vector3D.create(0, 1, 0),
        mm(hi[0] - lo[0]), mm(hi[1] - lo[1]), mm(hi[2] - lo[2]))
    return tb.createBox(obb)


def build(part):
    p = part.p
    s = p["beam_size"]
    yo = p["outboard_face_y"]
    zlo, zuo = p["lower_outboard_z"], p["upper_outboard_z"]
    zli, zui = p["lower_inboard_z"], p["upper_inboard_z"]
    xf, xr = p["pickup_front_x"], -p["pickup_rear_x_abs"]
    tb = adsk.fusion.TemporaryBRepManager.get()
    union = adsk.fusion.BooleanTypes.UnionBooleanType

    # outboard upright pad on plane Y = outboard_face_y
    body = abox(tb, (-45.0, yo - 20.0, 285.0), (45.0, yo, 435.0))

    links = [
        ((xf, 145.0, zli), (0.0, yo, zlo)),
        ((xr, 210.0, zli), (0.0, yo, zlo)),
        ((xf, 145.0, zui), (0.0, yo, zuo)),
        ((xr, 210.0, zui), (0.0, yo, zuo)),
        ((-200.0, 195.0, 190.0), (40.0, yo, 330.0)),
    ]
    for inb, outb in links:
        tb.booleanOperation(body, beam(tb, inb, outb, s, 15.0, 10.0), union)

    # clip to local envelope (flat outboard face exactly at Y = outboard_face_y)
    env = abox(tb, (-300.0, 140.0, 100.0), (100.0, yo, 440.0))
    tb.booleanOperation(body, env, adsk.fusion.BooleanTypes.IntersectionBooleanType)

    comp = part.comp
    bf = comp.features.baseFeatures.add()
    bf.name = "BF_front_suspension_left"
    bf.startEdit()
    b = comp.bRepBodies.add(body, bf)
    bf.finishEdit()
    part.body(0).name = "SUF_L_links"
