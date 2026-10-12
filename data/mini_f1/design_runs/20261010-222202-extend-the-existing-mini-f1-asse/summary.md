# Design run 20261010-222202-extend-the-existing-mini-f1-asse

Concept level only: no FIA compliance, structural adequacy or race readiness is claimed.

## Brief

Extend the existing Mini F1 assembly with 14 new exterior parts. Reuse MON-001, FWG-001, FLR-001 and RWG-001 exactly as registered (latest versions): do not redesign, move or change them.

GENERAL RULES
- Concept level, project vehicle coordinates (+X front, +Y left, +Z up, mm, origin on the front-axle centreline, Z=0 ground plane). Left parts on +Y, right parts on -Y. Right parts are derived from the left ones: left/right pairs are exact mirror images of each other, except the wheels (the right wheel is the left wheel turned 180 degrees about the vertical axis). Design only the left part of each pair and list the right part as mirror_of the left.
- Each part is ONE connected solid, built in its own local frame and positioned only by its pose. For wheels the local origin is the wheel centre and the axle is the local Y axis.
- All dimensions below are my concept assumptions, not regulation values. Use only the FIA excerpts the system supplies; mark everything else as an assumption. No FIA compliance claims.
- Planned contacts are listed per part. Everything else must keep at least 20 mm clear. Report every planned contact and every unintended overlap.
- Colours: tyres near-black, rims silver, suspension dark grey, sidepods and engine cover the same red as the monocoque, halo dark grey, mirrors black.

REGISTERED PARTS (approximate facts, check against the records)
- MON-001: X -3700..550, |Y|<=450, Z 30..740, flat bottom Z=30. Half-width about 450 at X=-3700, 436 at -2600, 382 at -1400, 247 at -400, 175 at X=0, 75 at the nose tip. Top surface Z about 730 at X=-3700, 690 at -2600, 620 at -1400, 366 at -400. Cockpit opening X -2300..-1500, |Y|<=250; rim ring X -2360..-1440, |Y|<=310, rim top plane Z=740.
- FWG-001: X 550..1150, |Y|<=850, Z 50..330.
- FLR-001: X -4300..-400, top Z=30, bottom Z=0; |Y|<=800 up to X=-2400, tapering to 520 at X=-3030, 520 to the rear end; diffuser ramp over the last 600 mm.
- RWG-001: X -4450..-3700, |Y|<=520, Z 400..1100.

NEW PARTS
A) Wheels WHL-FL, WHL-FR, WHL-RL, WHL-RR: cylinder along Y with rounded tyre shoulders, a recessed rim face on the outboard side and a hub boss (radius 90, length 60) on the inboard side.
 - Front: centre X=0, Z=360, |Y|=800, diameter 720, width 300 (tyre inner face |Y|=650, outer 950); hub boss from |Y|=650 to 590.
 - Rear: centre X=-3400, Z=370, |Y|=760, diameter 740, width 380 (inner face 570, outer 950); hub boss from 570 to 510.
 - A wheel touches nothing except its own suspension.
B) Suspension SUF-L, SUF-R, SUR-L, SUR-R: one connected solid per side and axle: an upper and a lower wishbone as 30 mm square beams forming a triangle in plan view, plus a pushrod to the hub.
 - Outboard ends: flat faces lying exactly in the hub-boss end plane (|Y|=590 front, 510 rear), inside the 90 mm hub radius around the wheel centre: planned contact (touching) with the wheel.
 - Inboard ends: planned shallow embedding, at most 20 mm deep, into the monocoque side wall. Front pickups X -300..+100, Z 100..200. Rear pickups X -3550..-3250, Z 150..500.
C) Sidepods SDP-L, SDP-R: lofted body from X=-700 (front) to X=-2950 (rear), bottom face on the floor top (Z=30): planned contact (touching) with FLR-001. Inner wall follows the monocoque side about 10 mm inside it: |Y| 280 at X=-700, 372 at -1400, 426 at -2600, 431 at -2950 (planned embedding into MON-001, at most 25 mm). Outer wall: |Y| 700 at X=-1200 narrowing to 540 at X=-2950. Top: Z 400 at X=-700, 420 at -1800, 300 at -2950, rounded top edges. A shallow inlet pocket (about 200 x 150 mm, 120 mm deep) in the front face. Relieve the outer lower edge (undercut) only as far as the geometry stays robust.
D) Engine cover ENG-001: airbox and shark-fin spine on the monocoque top. Airbox X -2700..-2450, |Y|<=140, up to Z 1000 with a front intake opening. Spine behind it, |Y|<=40, tapering down to Z 800 at X=-3600. Base plane Z=680 embedded into the monocoque top (planned embedding, at most 60 mm). Stays clear of the rear wing.
E) Halo HAL-001: U-shaped hoop: two side bars (40 mm thick) from rear feet at X about -2330, |Y| 280, rising to a top at Z about 900, and a central front pillar with its foot at X about -1470, Y=0. Foot bottoms lie exactly on the rim top plane Z=740, inside the rim ring: planned contact (touching) with MON-001.
F) Mirrors MIR-L, MIR-R: short stalk plus a rectangular housing (about 40 x 160 x 80 mm). Stalk base embedded at most 15 mm into the monocoque side at X about -1700, Z about 540; housing at |Y| about 560. Must not touch the halo or sidepods.

OUTPUT
Report component status, measured bounding boxes, every planned contact result, unintended overlaps, FIA statuses, assumptions and failures. Generate iso, front and top screenshots.

## Parts

| Part | State | Version | World bbox (mm) | Checks | FIA |
|---|---|---|---|---|---|
| MON-001 | DONE (reused) | 3 | (-3700, -450, 30) .. (550, 450, 740) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED |
| FWG-001 | DONE (reused) | 3 | (550, -900, 50) .. (1150, 900, 330) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED, C3.10.1:NOT_VERIFIED |
| FLR-001 | DONE (reused) | 2 | (-4300, -800, 0) .. (-400, 800, 230) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED, C3.5.4:NOT_VERIFIED |
| RWG-001 | DONE (reused) | 2 | (-4450, -520, 400) .. (-3700, 520, 1100) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED, C3.11.1:NOT_VERIFIED, C3.11.4:NOT_VERIFIED |
| WHL-FL | DONE | 1 | (-360, 590, 0) .. (360, 950, 720) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | - |
| WHL-RL | DONE | 1 | (-3770, 510, 0) .. (-3030, 950, 740) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | - |
| SUF-L | DONE | 1 | (-300, 140, 101) .. (96, 590, 438) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED |
| SUR-L | DONE | 1 | (-3550, 425, 157) .. (-3250, 510, 490) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED |
| SDP-L | DONE | 1 | (-2950, 280, 30) .. (-700, 701, 422) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED |
| ENG-001 | DONE | 1 | (-3600, -140, 680) .. (-2450, 140, 1000) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED |
| HAL-001 | DONE | 1 | (-2350, -300, 740) .. (-1450, 300, 920) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED |
| MIR-L | DONE | 1 | (-1720, 385, 500) .. (-1680, 640, 580) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED | C2.3.1:VERIFIED |
| WHL-FR | DONE (derived from WHL-FL, yaw180) | 1 | (-360, -950, 0) .. (360, -590, 720) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED, PART-DERIVED:VERIFIED | - |
| WHL-RR | DONE (derived from WHL-RL, yaw180) | 1 | (-3770, -950, 0) .. (-3030, -510, 740) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED, PART-DERIVED:VERIFIED | - |
| SUF-R | DONE (derived from SUF-L, mirror) | 1 | (-300, -590, 101) .. (96, -140, 438) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED, PART-DERIVED:VERIFIED | C2.3.1:VERIFIED |
| SUR-R | DONE (derived from SUR-L, mirror) | 1 | (-3550, -510, 157) .. (-3250, -425, 490) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED, PART-DERIVED:VERIFIED | C2.3.1:VERIFIED |
| SDP-R | DONE (derived from SDP-L, mirror) | 1 | (-2950, -701, 30) .. (-700, -280, 422) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED, PART-DERIVED:VERIFIED | C2.3.1:VERIFIED |
| MIR-R | DONE (derived from MIR-L, mirror) | 1 | (-1720, -640, 500) .. (-1680, -385, 580) | PART-BUILD:VERIFIED, PART-SOLID:VERIFIED, PART-FEATURES:VERIFIED, PART-BBOX:VERIFIED, PART-FRAME:VERIFIED, PART-PLACEMENT:VERIFIED, PART-PARAMS:VERIFIED, PART-DERIVED:VERIFIED | C2.3.1:VERIFIED |

## Assembly

placement-based assembly (each part placed by its pose) + as-built rigid joints for planned mates; contact measured, not constrained

- MATE-FLR-001-MON-001: VERIFIED  {"state": "touching", "gap_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-FWG-001-MON-001: VERIFIED  {"state": "touching", "gap_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-MON-001-RWG-001: VERIFIED  {"state": "touching", "gap_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-SUF-L-WHL-FL: VERIFIED  {"state": "touching", "gap_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-SUR-L-WHL-RL: VERIFIED  {"state": "touching", "gap_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-MON-001-SUF-L: NON_COMPLIANT measured overlap (gap 0.00 mm, overlap depth 88.85 mm) {"state": "overlap", "gap_mm": 0.0, "overlap_mm3": 148441.0, "overlap_depth_mm": 88.855}
- MATE-MON-001-SUR-L: NON_COMPLIANT measured overlap (gap 0.00 mm, overlap depth 25.17 mm) {"state": "overlap", "gap_mm": 0.0, "overlap_mm3": 197412.3, "overlap_depth_mm": 25.168}
- MATE-FLR-001-SDP-L: VERIFIED  {"state": "touching", "gap_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-MON-001-SDP-L: NON_COMPLIANT measured overlap (gap 0.00 mm, overlap depth 164.52 mm) {"state": "overlap", "gap_mm": 0.0, "overlap_mm3": 9407472.6, "overlap_depth_mm": 164.524}
- MATE-ENG-001-MON-001: VERIFIED  {"state": "overlap", "gap_mm": 0.0, "overlap_mm3": 2956923.6, "overlap_depth_mm": 47.316}
- MATE-HAL-001-MON-001: VERIFIED  {"state": "touching", "gap_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-MIR-L-MON-001: NON_COMPLIANT measured overlap (gap 0.00 mm, overlap depth 21.29 mm) {"state": "overlap", "gap_mm": 0.0, "overlap_mm3": 18259.5, "overlap_depth_mm": 21.292}
- MATE-HAL-001-MIR-L: VERIFIED  {"state": "gap", "gap_mm": 339.984, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-MIR-L-SDP-L: VERIFIED  {"state": "gap", "gap_mm": 78.173, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-ENG-001-RWG-001: VERIFIED  {"state": "gap", "gap_mm": 199.34, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-ENG-001-HAL-001: VERIFIED  {"state": "gap", "gap_mm": 156.205, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-FLR-001-WHL-FL: VERIFIED  {"state": "gap", "gap_mm": 161.782, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-FWG-001-WHL-FL: VERIFIED  {"state": "gap", "gap_mm": 195.81, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-FLR-001-WHL-RL: VERIFIED  {"state": "gap", "gap_mm": 50.877, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-RWG-001-WHL-RL: VERIFIED  {"state": "gap", "gap_mm": 284.158, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-SDP-L-WHL-RL: VERIFIED  {"state": "gap", "gap_mm": 115.179, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-WHL-FL-WHL-FR: VERIFIED  {"state": "gap", "gap_mm": 1180.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-WHL-RL-WHL-RR: VERIFIED  {"state": "gap", "gap_mm": 1020.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-SUF-L-SUF-R: VERIFIED  {"state": "gap", "gap_mm": 280.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-SUR-L-SUR-R: VERIFIED  {"state": "gap", "gap_mm": 850.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-SDP-L-SDP-R: VERIFIED  {"state": "gap", "gap_mm": 560.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-MIR-L-MIR-R: VERIFIED  {"state": "gap", "gap_mm": 770.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-SUF-R-WHL-FR: VERIFIED  {"state": "touching", "gap_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-SUR-R-WHL-RR: VERIFIED  {"state": "touching", "gap_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-MON-001-SUF-R: NON_COMPLIANT measured overlap (gap 0.00 mm, overlap depth 88.85 mm) {"state": "overlap", "gap_mm": 0.0, "overlap_mm3": 148441.0, "overlap_depth_mm": 88.855}
- MATE-MON-001-SUR-R: NON_COMPLIANT measured overlap (gap 0.00 mm, overlap depth 25.17 mm) {"state": "overlap", "gap_mm": 0.0, "overlap_mm3": 197412.3, "overlap_depth_mm": 25.168}
- MATE-FLR-001-SDP-R: VERIFIED  {"state": "touching", "gap_mm": 0.0, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-MON-001-SDP-R: NON_COMPLIANT measured overlap (gap 0.00 mm, overlap depth 164.52 mm) {"state": "overlap", "gap_mm": 0.0, "overlap_mm3": 9407304.3, "overlap_depth_mm": 164.524}
- MATE-MIR-R-MON-001: NON_COMPLIANT measured overlap (gap 0.00 mm, overlap depth 21.29 mm) {"state": "overlap", "gap_mm": 0.0, "overlap_mm3": 18259.5, "overlap_depth_mm": 21.292}
- MATE-HAL-001-MIR-R: VERIFIED  {"state": "gap", "gap_mm": 339.984, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-MIR-R-SDP-R: VERIFIED  {"state": "gap", "gap_mm": 78.173, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-FLR-001-WHL-FR: VERIFIED  {"state": "gap", "gap_mm": 161.782, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-FWG-001-WHL-FR: VERIFIED  {"state": "gap", "gap_mm": 195.81, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-FLR-001-WHL-RR: VERIFIED  {"state": "gap", "gap_mm": 50.877, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-RWG-001-WHL-RR: VERIFIED  {"state": "gap", "gap_mm": 284.158, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- MATE-SDP-R-WHL-RR: VERIFIED  {"state": "gap", "gap_mm": 115.179, "overlap_mm3": 0.0, "overlap_depth_mm": 0.0}
- mate face (advisory) FLR-001/MON-001: NOT_CHECKABLE - no unique planned contact face (envelope separation X/Y/Z -3300, -1250, -200 mm); a geometric / Fusion-level check is needed - the MATE measurement decides
- mate face (advisory) FWG-001 -X: PASS - bbox reaches the planned face (expected 550, measured 550 mm); actual contact is decided by the Fusion mate measurement
- mate face (advisory) MON-001 +X: PASS - bbox reaches the planned face (expected 550, measured 550 mm); actual contact is decided by the Fusion mate measurement
- mate face (advisory) RWG-001 +X: PASS - bbox reaches the planned face (expected -3700, measured -3700 mm); actual contact is decided by the Fusion mate measurement
- mate face (advisory) MON-001 -X: PASS - bbox reaches the planned face (expected -3700, measured -3700 mm); actual contact is decided by the Fusion mate measurement
- mate face (advisory) WHL-FL -Y: PASS - bbox reaches the planned face (expected 590, measured 590 mm); actual contact is decided by the Fusion mate measurement
- mate face (advisory) SUF-L +Y: PASS - bbox reaches the planned face (expected 590, measured 590 mm); actual contact is decided by the Fusion mate measurement
- mate face (advisory) WHL-RL -Y: PASS - bbox reaches the planned face (expected 510, measured 510 mm); actual contact is decided by the Fusion mate measurement
- mate face (advisory) SUR-L +Y: PASS - bbox reaches the planned face (expected 510, measured 510 mm); actual contact is decided by the Fusion mate measurement
- mate face (advisory) SUF-L/MON-001: NOT_CHECKABLE - no unique planned contact face (envelope separation X/Y/Z -850, -310, -410 mm); a geometric / Fusion-level check is needed - the MATE measurement decides
- mate face (advisory) SUR-L/MON-001: NOT_CHECKABLE - no unique planned contact face (envelope separation X/Y/Z -450, -25, -470 mm); a geometric / Fusion-level check is needed - the MATE measurement decides
- mate face (advisory) SDP-L/FLR-001: NOT_CHECKABLE - no unique planned contact face (envelope separation X/Y/Z -2550, -530, -200 mm); a geometric / Fusion-level check is needed - the MATE measurement decides
- mate face (advisory) SDP-L/MON-001: NOT_CHECKABLE - no unique planned contact face (envelope separation X/Y/Z -3000, -180, -390 mm); a geometric / Fusion-level check is needed - the MATE measurement decides
- mate face (advisory) ENG-001/MON-001: NOT_CHECKABLE - no unique planned contact face (envelope separation X/Y/Z -1250, -590, -110 mm); a geometric / Fusion-level check is needed - the MATE measurement decides
- mate face (advisory) HAL-001/MON-001: NOT_CHECKABLE - no unique planned contact face (envelope separation X/Y/Z -2250, -750, -50 mm); a geometric / Fusion-level check is needed - the MATE measurement decides
- mate face (advisory) MIR-L/MON-001: NOT_CHECKABLE - no unique planned contact face (envelope separation X/Y/Z -2020, -70, -290 mm); a geometric / Fusion-level check is needed - the MATE measurement decides
- mate face (advisory) WHL-FR +Y: PASS - bbox reaches the planned face (expected -590, measured -590 mm); actual contact is decided by the Fusion mate measurement
- mate face (advisory) SUF-R -Y: PASS - bbox reaches the planned face (expected -590, measured -590 mm); actual contact is decided by the Fusion mate measurement
- mate face (advisory) WHL-RR +Y: PASS - bbox reaches the planned face (expected -510, measured -510 mm); actual contact is decided by the Fusion mate measurement
- mate face (advisory) SUR-R -Y: PASS - bbox reaches the planned face (expected -510, measured -510 mm); actual contact is decided by the Fusion mate measurement
- mate face (advisory) SUF-R/MON-001: NOT_CHECKABLE - no unique planned contact face (envelope separation X/Y/Z -850, -310, -410 mm); a geometric / Fusion-level check is needed - the MATE measurement decides
- mate face (advisory) SUR-R/MON-001: NOT_CHECKABLE - no unique planned contact face (envelope separation X/Y/Z -450, -25, -470 mm); a geometric / Fusion-level check is needed - the MATE measurement decides
- mate face (advisory) SDP-R/FLR-001: NOT_CHECKABLE - no unique planned contact face (envelope separation X/Y/Z -2550, -530, -200 mm); a geometric / Fusion-level check is needed - the MATE measurement decides
- mate face (advisory) SDP-R/MON-001: NOT_CHECKABLE - no unique planned contact face (envelope separation X/Y/Z -3000, -180, -390 mm); a geometric / Fusion-level check is needed - the MATE measurement decides
- mate face (advisory) MIR-R/MON-001: NOT_CHECKABLE - no unique planned contact face (envelope separation X/Y/Z -2020, -70, -290 mm); a geometric / Fusion-level check is needed - the MATE measurement decides

## Assumptions

- A01 ASSUMPTION: Reused parts keep their registered pose at the VCS origin and registered envelopes (MON-001 Z max 790 per registry).
- A02 ASSUMPTION: Monocoque side-wall half-width is linearly interpolated between the brief's stations to set inboard embed depths.
- A03 ASSUMPTION: Wheel rim face diameters 460 (front) / 480 (rear), 30 mm recess, 40 mm tyre shoulder radius.
- A04 ASSUMPTION: Front pickups: lower Z 120, upper Z 185 at X +80 and -280; outboard nodes at Z 300/420.
- A05 ASSUMPTION: Rear pickups: lower Z 180, upper Z 470 at X -3270/-3530; outboard nodes at Z 310/430.
- A06 ASSUMPTION: Sidepod outer half-width about 620 at the front face, inlet pocket centred Y~460, Z~250 in VCS, undercut ~60 mm.
- A07 ASSUMPTION: Halo top bar centreline at Z 900 (outer surface 920); front pillar 40 mm wide.
- A08 ASSUMPTION: Mirror stalk 30x30 mm, housing centre Y 560, Z 540; engine intake opening about 160x120 mm.

## Counts

- Claude calls: 10
- Fusion script calls: 37
- MCP stdout wrapper depth: first 2, last 37
