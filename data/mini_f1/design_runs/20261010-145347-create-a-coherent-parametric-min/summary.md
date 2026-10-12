# Design run 20261010-145347-create-a-coherent-parametric-min

Concept level only: no FIA compliance, structural adequacy or race readiness is claimed.

## Brief

Create a coherent, parametric Mini F1 concept assembly in Fusion 360 consisting of exactly four main components:

1. **MON-001 — Monocoque:** A tapered central chassis with a raised cockpit rim, an open cockpit, a narrow front nose and a wider rear section.
2. **FWG-001 — Front Wing:** A multi-element front wing with a main plane, two simplified flaps and endplates, mounted ahead of the monocoque.
3. **FLR-001 — Floor:** A broad, thin aerodynamic floor beneath the chassis, with simplified side edges and a tapered rear diffuser ramp.
4. **RWG-001 — Rear Wing:** A raised rear wing with a main plane, one flap, two endplates and simplified supports.

Use millimetres and the project coordinate convention: +X forward, +Y left, +Z upward, with the origin on the front-axle centreline and Z=0 on the reference plane.

Design the four components as separate, editable Fusion components in one design. Place them in a coherent vehicle layout with no unintended solid intersections. Use named features and meaningful user parameters where practical. Keep the shapes manufacturable-looking and geometrically simple enough to regenerate reliably.

Develop a dimensioned concept plan first. Use only the FIA rule excerpts supplied by the system; do not invent rule dimensions or claim FIA compliance. Mark unsupported dimensions as assumptions. Prioritise a successful complete assembly, correct component placement, valid solids, and clear front, top and isometric views over excessive geometric detail.

Connections: parts connect by face contact, never by overlap. The front wing mount touches the nose tip, the monocoque sits on the top face of the floor, and the rear wing supports touch the rear of the monocoque (or the floor). Report the measured gap or overlap of every connected pair.
Keep every part within the overall vehicle width limit given in the supplied rules.
Scale (my own concept assumption, not a regulation value): roughly full-size F1 proportions, overall length about 5.5 m and overall width under 2 m.

Do not add extra main components beyond the four listed. If a critical design decision is missing, ask at most one blocking question; otherwise proceed with explicit assumptions.

At completion, report the component status, measured bounding boxes, placement and interference/gap checks, applicable FIA verification statuses, assumptions, and any failures. Generate isometric, front and top screenshots.

## Parts

| Part | State | Version | World bbox (mm) | Checks | FIA |
|---|---|---|---|---|---|
| MON-001 | DONE | 1 | (-3700, -450, 60) .. (550, 450, 770) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED |
| FWG-001 | DONE | 1 | (550, -900, 50) .. (1150, 900, 330) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED, C3.10.1:NOT_VERIFIED |
| FLR-001 | DONE | 1 | (-4300, -800, 0) .. (-400, 800, 230) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED, C3.5.4:NOT_VERIFIED |
| RWG-001 | DONE | 1 | (-4450, -520, 400) .. (-3700, 520, 1100) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED, C3.11.1:NOT_VERIFIED, C3.11.4:NOT_VERIFIED |

## Assembly

placement-based assembly (each part placed by its pose) + as-built rigid joints for planned mates; contact measured, not constrained

- MATE-FWG-001-MON-001: VERIFIED  {"state": "touching", "gap_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-FLR-001-MON-001: NON_COMPLIANT measured gap (gap 28.46 mm, overlap depth 0.00 mm) {"state": "gap", "gap_mm": 28.46, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-MON-001-RWG-001: VERIFIED  {"state": "touching", "gap_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}

## Assumptions

- A01 ASSUMPTION: Overall length ~5600 mm, from front wing leading edge X=+1150 to rear wing endplate trailing edge X=-4450.
- A02 ASSUMPTION: Max part half-width set to 900 mm (front wing), inside the 950 mm limit of C2.3.1.
- A03 ASSUMPTION: Floor is 30 mm thick with its top face at Z=30; the monocoque has a flat bottom at Z=30.
- A04 ASSUMPTION: Monocoque runs from X=+550 (nose tip) to X=-3700 (rear face); the nose has a flat bottom with no raised-nose geometry.
- A05 ASSUMPTION: Front wing mount is a central pylon block whose rear face touches the 200x200 nose tip face at X=550.
- A06 ASSUMPTION: Rear wing uses two support plates at Y=±100 that touch the monocoque rear face at X=-3700, not a single pylon.
- A07 ASSUMPTION: Diffuser ramp rises from 30 mm to 230 mm over the last 600 mm of the floor and is 1000 mm wide.
- A08 ASSUMPTION: Wing profiles are simplified as constant-thickness cambered or flat plates; no RV/RS reference volumes are modelled.

## Counts

- Claude calls: 5
- Fusion script calls: 8
- MCP stdout wrapper depth: first 2, last 6
