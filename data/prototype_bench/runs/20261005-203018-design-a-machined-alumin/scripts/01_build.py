
import json
import adsk.core, adsk.fusion

CFG = json.loads(r"""{"component_name": "BRK-001 Sensor box bracket", "body_name": "BRK-001_body", "prefix": "brk001", "params": [["leg_base_length", 64.0, "Base leg length along local X (mm)"], ["leg_upright_height", 50.0, "Upright leg height along local Z (mm)"], ["bracket_width", 60.0, "Bracket width along local Y (mm)"], ["bracket_thickness", 5.0, "Plate thickness of both legs (mm)"], ["bend_inner_radius", 4.0, "Internal bend fillet radius (mm); outer = inner + thickness"], ["base_hole_diameter", 6.6, "Base leg clearance hole diameter (mm)"], ["base_hole_x0", 22.0, "Distance from upright outer face (x=0) to first base hole row (mm)"], ["base_hole_pitch_x", 30.0, "Row pitch of base holes along X (mm); ignored if 1 row"], ["base_hole_pitch_y", 36.0, "Column pitch of base holes along Y (mm); ignored if 1 column"], ["upright_hole_diameter", 5.5, "Upright leg clearance hole diameter (mm)"], ["upright_hole_z0", 35.0, "Height from base bottom face (z=0) to first upright hole row (mm)"], ["upright_hole_pitch_z", 0.0, "Row pitch of upright holes along Z (mm); ignored if 1 row"], ["upright_hole_pitch_y", 40.0, "Column pitch of upright holes along Y (mm); ignored if 1 column"]], "base_holes": {"rows": 2, "cols": 2}, "upright_holes": {"rows": 1, "cols": 2}, "values": {"leg_base_length": 64.0, "leg_upright_height": 50.0, "bracket_width": 60.0, "bracket_thickness": 5.0, "bend_inner_radius": 4.0, "base_hole_diameter": 6.6, "base_hole_x0": 22.0, "base_hole_pitch_x": 30.0, "base_hole_pitch_y": 36.0, "upright_hole_diameter": 5.5, "upright_hole_z0": 35.0, "upright_hole_pitch_z": 0.0, "upright_hole_pitch_y": 40.0, "base_hole_rows": 2, "base_hole_cols": 2, "upright_hole_rows": 1, "upright_hole_cols": 2, "base_fastener": "M6", "upright_fastener": "M5"}, "transform": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0], "fusion_material": "Aluminum 6061", "marker": "@@RESULT@@"}""")
P = CFG["prefix"]
V = CFG["values"]
TOL = 1e-6


def pname(n):
    return P + "_" + n


def pt(x, y, z):
    # local mm -> Fusion cm
    return adsk.core.Point3D.create(x / 10.0, y / 10.0, z / 10.0)


def to_sketch(sk, x, y, z):
    return sk.modelToSketchSpace(pt(x, y, z))


def sketch_orientation(sk, axis):
    """Dimension orientation in sketch space that measures along a local model axis."""
    a = sk.modelToSketchSpace(pt(0, 0, 0))
    b = sk.modelToSketchSpace(pt(*[10.0 * c for c in axis]))
    D = adsk.fusion.DimensionOrientations
    return D.HorizontalDimensionOrientation if abs(b.x - a.x) > abs(b.y - a.y) else D.VerticalDimensionOrientation


def dim(sk, p1, p2, orientation, expr, text_at):
    d = sk.sketchDimensions.addDistanceDimension(p1, p2, orientation, text_at)
    d.parameter.expression = expr
    return d


def remove_previous(design, root):
    for i in range(root.occurrences.count - 1, -1, -1):
        occ = root.occurrences.item(i)
        if occ.component.name == CFG["component_name"]:
            occ.deleteMe()
    remove_params(design)


def remove_params(design):
    ups = design.userParameters
    names = [ups.item(i).name for i in range(ups.count)]
    # derived parameters first (they reference the base ones)
    for n in sorted([n for n in names if n.startswith(P + "_")], key=lambda n: 0 if n.endswith("outer_radius") else 1):
        prm = ups.itemByName(n)
        if prm:
            prm.deleteMe()


def create_params(design):
    ups = design.userParameters
    for n, value, comment in CFG["params"]:
        ups.add(pname(n), adsk.core.ValueInput.createByString("%r mm" % value), "mm", comment)
    ups.add(pname("bend_outer_radius"),
            adsk.core.ValueInput.createByString(pname("bend_inner_radius") + " + " + pname("bracket_thickness")),
            "mm", "Outer bend radius = inner radius + thickness (constant section)")


def l_profile(comp):
    sk = comp.sketches.add(comp.xZConstructionPlane)
    sk.name = "SK_L_profile"
    L, H, t = V["leg_base_length"], V["leg_upright_height"], V["bracket_thickness"]
    pts = [(0, 0), (L, 0), (L, t), (t, t), (t, H), (0, H)]          # (x, z) local
    lines = sk.sketchCurves.sketchLines
    segs = []
    first = to_sketch(sk, 0, 0, 0)
    prev = first
    for i in range(6):
        nx, nz = pts[(i + 1) % 6]
        end = segs[0].startSketchPoint if i == 5 else to_sketch(sk, nx, 0, nz)
        start = segs[-1].endSketchPoint if segs else prev
        segs.append(lines.addByTwoPoints(start, end))
    gc = sk.geometricConstraints
    gc.addCoincident(segs[0].startSketchPoint, sk.originPoint)
    for ln in segs:
        s, e = ln.startSketchPoint.geometry, ln.endSketchPoint.geometry
        if abs(e.x - s.x) > abs(e.y - s.y):
            gc.addHorizontal(ln)
        else:
            gc.addVertical(ln)
    ox = sketch_orientation(sk, (1, 0, 0))
    oz = sketch_orientation(sk, (0, 0, 1))
    tp = lambda x, z: to_sketch(sk, x, 0, z)
    dim(sk, segs[0].startSketchPoint, segs[0].endSketchPoint, ox, pname("leg_base_length"), tp(L / 2, -12))
    dim(sk, segs[1].startSketchPoint, segs[1].endSketchPoint, oz, pname("bracket_thickness"), tp(L + 10, t / 2))
    dim(sk, segs[4].startSketchPoint, segs[4].endSketchPoint, ox, pname("bracket_thickness"), tp(t / 2, H + 10))
    dim(sk, segs[5].startSketchPoint, segs[5].endSketchPoint, oz, pname("leg_upright_height"), tp(-12, H / 2))
    return sk


def find_bend_edge(body, x, z):
    for i in range(body.edges.count):
        e = body.edges.item(i)
        a, b = e.startVertex.geometry, e.endVertex.geometry
        if (abs(a.x - x) < TOL and abs(b.x - x) < TOL and abs(a.z - z) < TOL and abs(b.z - z) < TOL
                and abs(a.y - b.y) > TOL):
            return e
    raise RuntimeError("Bend edge at x=%g z=%g cm not found" % (x, z))


def fillet(comp, body, x_cm, z_cm, expr, name):
    edges = adsk.core.ObjectCollection.create()
    body = comp.bRepBodies.itemByName(CFG["body_name"])
    edges.add(find_bend_edge(body, x_cm, z_cm))
    fi = comp.features.filletFeatures.createInput()
    fi.edgeSetInputs.addConstantRadiusEdgeSet(edges, adsk.core.ValueInput.createByString(expr), True)
    f = comp.features.filletFeatures.add(fi)
    f.name = name
    return f


def same_coord(gc, p1, p2, orientation):
    """Constrain two sketch points to share the coordinate that `orientation` measures."""
    if orientation == adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation:
        gc.addVerticalPoints(p1, p2)        # same sketch x
    else:
        gc.addHorizontalPoints(p1, p2)      # same sketch y


def hole_sketch(comp, plane, name, holes, axis_a, diam_key, a0_key, pitch_a_key, pitch_y_key):
    """holes: (row i, col j, a, y, d) in mm; a is measured along local axis_a from the origin.

    Chained design intent: hole (0,0) is dimensioned from the origin, the others by pitch from
    their neighbour plus alignment constraints (Fusion rejects two parallel dimensions from the
    origin to points that share a coordinate).
    """
    sk = comp.sketches.add(plane)
    sk.name = name
    oa = sketch_orientation(sk, axis_a)
    oy = sketch_orientation(sk, (0, 1, 0))
    gc = sk.geometricConstraints
    ia = axis_a.index(1)
    centers = {}
    for (i, j, a, y, d) in holes:
        c3 = [0.0, y, 0.0]
        c3[ia] = a
        circle = sk.sketchCurves.sketchCircles.addByCenterRadius(to_sketch(sk, *c3), d / 20.0)
        cp = circle.centerSketchPoint
        centers[(i, j)] = cp
        t3 = list(c3); t3[1] = y + d
        sk.sketchDimensions.addDiameterDimension(circle, to_sketch(sk, *t3)).parameter.expression = pname(diam_key)
        ta = list(c3); ta[1] = y - 1.5 * d
        ty = list(c3); ty[ia] = a + 1.5 * d
        # coordinate along the leg (a)
        if i == 0 and j == 0:
            dim(sk, sk.originPoint, cp, oa, pname(a0_key), to_sketch(sk, *ta))
        elif i == 0:
            same_coord(gc, centers[(0, 0)], cp, oa)
        else:
            dim(sk, centers[(0, j)], cp, oa, pname(pitch_a_key), to_sketch(sk, *ta))
        # coordinate across the width (y)
        if i > 0:
            same_coord(gc, centers[(0, j)], cp, oy)
        elif j == 0 and y == 0:
            same_coord(gc, sk.originPoint, cp, oy)
        elif j == 0:
            dim(sk, sk.originPoint, cp, oy, pname(pitch_y_key) + " / 2", to_sketch(sk, *ty))
        else:
            dim(sk, centers[(0, 0)], cp, oy, pname(pitch_y_key), to_sketch(sk, *ty))
    return sk


def cut_holes(comp, sk, body, name):
    profs = adsk.core.ObjectCollection.create()
    for i in range(sk.profiles.count):
        profs.add(sk.profiles.item(i))
    ext = comp.features.extrudeFeatures
    ei = ext.createInput(profs, adsk.fusion.FeatureOperations.CutFeatureOperation)
    ei.setTwoSidesExtent(adsk.fusion.ThroughAllExtentDefinition.create(),
                         adsk.fusion.ThroughAllExtentDefinition.create())
    ei.participantBodies = [comp.bRepBodies.itemByName(CFG["body_name"])]
    f = ext.add(ei)
    f.name = name
    return f


def grid(rows, cols, a0, pa, py, d):
    ys = [0.0] if cols == 1 else [-py / 2.0, py / 2.0]
    return [(i, j, a0 + i * pa, y, d) for i in range(rows) for j, y in enumerate(ys)]


def apply_material(design, body, warnings):
    want = CFG["fusion_material"]
    if not want:
        return None
    app = adsk.core.Application.get()
    for li in range(app.materialLibraries.count):
        lib = app.materialLibraries.item(li)
        m = lib.materials.itemByName(want)
        if m:
            body.material = m
            return m.name
    warnings.append("Fusion material '%s' not found; body keeps default material" % want)
    return None


def build(design, comp):
    warnings = []
    sk = l_profile(comp)
    if sk.profiles.count != 1:
        raise RuntimeError("L profile sketch has %d profiles, expected 1" % sk.profiles.count)
    ext = comp.features.extrudeFeatures
    ei = ext.createInput(sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ei.setSymmetricExtent(adsk.core.ValueInput.createByString(pname("bracket_width")), True)
    ex = ext.add(ei)
    ex.name = "EX_L_profile"
    body = ex.bodies.item(0)
    body.name = CFG["body_name"]
    t = V["bracket_thickness"] / 10.0
    if V["bend_inner_radius"] > 0:
        fillet(comp, body, t, t, pname("bend_inner_radius"), "FL_bend_inner")
        fillet(comp, body, 0.0, 0.0, pname("bend_outer_radius"), "FL_bend_outer")
    bh = CFG["base_holes"]
    sk_b = hole_sketch(comp, comp.xYConstructionPlane, "SK_base_holes",
                       grid(bh["rows"], bh["cols"], V["base_hole_x0"], V["base_hole_pitch_x"], V["base_hole_pitch_y"], V["base_hole_diameter"]),
                       (1, 0, 0), "base_hole_diameter", "base_hole_x0", "base_hole_pitch_x", "base_hole_pitch_y")
    cut_holes(comp, sk_b, body, "CUT_base_holes")
    uh = CFG["upright_holes"]
    sk_u = hole_sketch(comp, comp.yZConstructionPlane, "SK_upright_holes",
                       grid(uh["rows"], uh["cols"], V["upright_hole_z0"], V["upright_hole_pitch_z"], V["upright_hole_pitch_y"], V["upright_hole_diameter"]),
                       (0, 0, 1), "upright_hole_diameter", "upright_hole_z0", "upright_hole_pitch_z", "upright_hole_pitch_y")
    cut_holes(comp, sk_u, body, "CUT_upright_holes")
    body = comp.bRepBodies.itemByName(CFG["body_name"])
    material = apply_material(design, body, warnings)
    return body, material, warnings


def run(_context: str):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    created_doc = False
    if design is None:
        app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        created_doc = True
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    root = design.rootComponent
    remove_previous(design, root)
    create_params(design)
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = CFG["component_name"]
    try:
        body, material, warnings = build(design, comp)
        m = adsk.core.Matrix3D.create()
        m.setWithArray(CFG["transform"])
        if not m.isEqualTo(adsk.core.Matrix3D.create()):
            occ.transform2 = m
            design.snapshots.add()
    except Exception:
        # leave no partial component behind; re-raise so the caller sees the real error
        occ.deleteMe()
        remove_params(design)
        raise
    print(CFG["marker"] + json.dumps({
        "component_name": comp.name,
        "body_name": body.name,
        "document": app.activeDocument.name,
        "created_document": created_doc,
        "fusion_version": app.version,
        "material": material,
        "warnings": warnings,
    }))
