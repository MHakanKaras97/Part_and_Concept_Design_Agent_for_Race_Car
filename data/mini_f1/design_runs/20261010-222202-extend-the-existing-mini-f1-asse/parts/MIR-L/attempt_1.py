import adsk.core
import adsk.fusion

def build(part):
    hl = part.p["housing_length"]
    hw = part.p["housing_width"]
    hh = part.p["housing_height"]
    cy = part.p["housing_center_y"]
    s = part.p["stalk_size"]
    y0 = part.p["stalk_start_y"]
    comp = part.comp

    # Housing box, symmetric about its centre plane y = cy
    skh = part.sketch(part.plane("y", cy, "PL_housing_mid"), "SK_housing")
    part.polygon(skh, [(-hl / 2, cy, -hh / 2), (hl / 2, cy, -hh / 2),
                       (hl / 2, cy, hh / 2), (-hl / 2, cy, hh / 2)])
    part.extrude(part.profile(skh), "housing_width", "EX_housing", symmetric=True)

    # Small edge fillets on housing
    body = part.body(0)
    edges = adsk.core.ObjectCollection.create()
    for e in body.edges:
        edges.add(e)
    fi = comp.features.filletFeatures.createInput()
    fi.edgeSetInputs.addConstantRadiusEdgeSet(edges, val(4.0), True)
    f = comp.features.filletFeatures.add(fi)
    f.name = "FIL_housing"

    # Stalk from y0 into the housing (10 mm overlap for a solid join)
    y1 = cy - hw / 2 + 10.0
    ym = (y0 + y1) / 2
    sks = part.sketch(part.plane("y", ym, "PL_stalk_mid"), "SK_stalk")
    part.polygon(sks, [(-s / 2, ym, -s / 2), (s / 2, ym, -s / 2),
                       (s / 2, ym, s / 2), (-s / 2, ym, s / 2)])
    part.extrude(part.profile(sks), y1 - y0, "EX_stalk", op="join", symmetric=True)
