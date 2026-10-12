# Reasoning task 04_review (run 20261010-105534-part-001-f1-front-wing-m)

Write your answer as JSON to `04_review.response.json` in this folder, then run:

    python -m agent step 20261010-105534-part-001-f1-front-wing-m

---

# Role

You are the reasoning component of an AI Engineering Agent. You do not draw CAD and you do not
compute checks yourself: Python performs calculations, rule checks and registration, and Fusion 360
builds and measures geometry. Your job is engineering judgement: interpret, identify gaps, state
assumptions, plan, and decide on revisions.

Rules that always apply:
- Answer with ONE JSON object that validates against the response schema. No prose outside it.
- Never invent requirements, regulations or rule values. Only rules listed in the context exist.
- Never claim FIA compliance, structural safety, race-readiness or production readiness.
- Do not silently invent critical information. Anything not stated by the user is either a
  missing-information item (ASK) or an explicit assumption (A-id) - never a hidden default.
- Every numeric design value must trace to requirement ids (R..), assumption ids (A..),
  user answers (M..) or rule ids. Units: mm, deg, N, kg.
- Keep the layers distinct: the user's words (authoritative) -> your interpretation (requirements,
  labelled as AI interpretation) -> your engineering decisions (assumptions, parameters, traced).
  Never present an interpretation or an assumption as something the user said.
- Be concise and specific; write for an engineer reviewing your reasoning later.


# Task: design review after CAD + validation

context.validation lists every check result (status, severity, measured, limit, message).
context.blocking_failures lists the results that prevent acceptance.

Decide:
- ACCEPT  - only if there are no blocking failures (Python enforces this) and the result meets the
            requirements. Advisory findings may remain; mention them in the rationale.
- REVISE  - give `parameter_changes` (only changed parameters, full PlannedParam entries) that fix
            the findings. Python re-checks and rebuilds. Revision loops are limited (context.loops).
- STOP    - the request cannot be met with this generator/inputs; explain why.

Do not accept a design to "finish the task". An honest STOP is better than an unjustified ACCEPT.


---

## Context

```json
{
  "request": "PART 001 — F1 Front Wing Mounting Bracket\n\nAmaç:\nÖn kanadın araç üzerindeki yapısal bağlantısını temsil eden, parametrik ve üretilebilir bir mounting bracket oluşturmak.\n\nBu ilk parça bir F1-inspired engineering demonstrator olacak.\nGerçek FIA homologasyon parçası olduğunu iddia etme.\nBoyutları ve geometrik kuralları proje kapsamında tanımlanmış mühendislik varsayımları olarak kabul et.\n\nParça şu özellikleri göstermeli:\n- rigid mounting bracket\n- iki ana bağlantı bölgesi\n- bolt holes\n- yeterli malzeme kalınlığı\n- fillet'ler\n- açıkça tanımlanmış parametrik ölçüler\n- simetrik olmayan / yönü belli bir geometri\n- Fusion assembly içerisinde anlamlı bir coordinate frame\n- daha sonra başka F1 parçalarıyla assembly oluşturulabilecek şekilde tasarlanmış olması\n\nInitial Part Parameters:\nOverall length: 120 mm\nOverall width: 70 mm\nBase thickness: 12 mm\nVertical support thickness: 10 mm\nSupport height: 65 mm\n\nMounting holes:\n- 2 × Ø10 mm base mounting holes\n- 2 × Ø8 mm front-wing mounting holes\n\nMinimum fillet:\nR5 mm\n\nCoordinate System:\nX: part longitudinal direction\nY: part lateral direction\nZ: vertical direction\nOrigin için şimdilik mevcut generator origin'ini koru.\n\nPlacement:\nPosition:\nX = 500 mm\nY = -250 mm\nZ = 150 mm\n\nRotation:\nRoll = 15°\nPitch = 35°\nYaw = 60°",
  "plan": {
    "generator": "l_bracket",
    "component_name": "PART 001 - F1 front wing mounting bracket",
    "steps": [
      "Map the user envelope (R05-R09) to the l_bracket parameters: base leg 120 mm along X, upright 65 mm along Z, width 70 mm along Y, base 12 mm, upright 10 mm thick.",
      "Set the inner bend fillet to the user minimum of R5 (R12). Check it against DFM-MACH-INNER-RADIUS-MIN (>= 3 mm) and DFM-DFMEA-FATIGUE-FILLET (5/12 = 0.42 >= 0.2).",
      "Place the 2 x Ø10 base holes (vehicle side, A07) as 1 row x 2 columns, and the 2 x Ø8 upright holes (front-wing side) as 1 row x 2 columns. Check GL-HOLE-EDGE-DISTANCE (>= 1.5 d) and clearance to the bend fillet.",
      "Assign fastener designations to the user hole diameters (A10). The user diameters are kept. The STD-ISO273-MEDIUM mismatch is reported as advisory, not hidden.",
      "Check feasibility and DFM in Python: minimum wall 10 mm >= 2 mm (DFM-MACH-WALL-MIN), hole edge distances and fillet ratios.",
      "Build the parametric model in Fusion with the generator origin kept (R17). Apply the user pose (R18-R23) with R = Rz(60)*Ry(35)*Rx(15) (A09), then read the placement back.",
      "Measure the geometry in Fusion: bounding box, thicknesses, hole diameters and positions, fillet radius, and mass with AL7075-T6.",
      "Report the structural check as NOT_RUN, because no load case was given (A04)."
    ],
    "parameters": {
      "leg_base_length": {
        "value": 120.0,
        "unit": "mm",
        "source": "USER",
        "trace": [
          "R05",
          "R14"
        ],
        "rationale": "The user's overall length of 120 mm along local X. The base leg runs x = 0..120."
      },
      "leg_upright_height": {
        "value": 65.0,
        "unit": "mm",
        "source": "USER",
        "trace": [
          "R09",
          "R16"
        ],
        "rationale": "The user's support height of 65 mm along local Z, measured from the base bottom face z = 0."
      },
      "bracket_width": {
        "value": 70.0,
        "unit": "mm",
        "source": "USER",
        "trace": [
          "R06",
          "R15"
        ],
        "rationale": "The user's overall width of 70 mm along local Y, symmetric about y = 0."
      },
      "bracket_thickness": {
        "value": 12.0,
        "unit": "mm",
        "source": "USER",
        "trace": [
          "R07"
        ],
        "rationale": "The user's base thickness of 12 mm. This is well above the 2 mm minimum wall in DFM-MACH-WALL-MIN."
      },
      "upright_thickness": {
        "value": 10.0,
        "unit": "mm",
        "source": "USER",
        "trace": [
          "R08"
        ],
        "rationale": "The user's vertical support thickness of 10 mm. It is given explicitly because it differs from the 12 mm base thickness."
      },
      "bend_inner_radius": {
        "value": 5.0,
        "unit": "mm",
        "source": "USER",
        "trace": [
          "R12",
          "A03",
          "DFM-MACH-INNER-RADIUS-MIN",
          "DFM-DFMEA-FATIGUE-FILLET"
        ],
        "rationale": "The user minimum of R5. It meets the >= 3 mm end-mill rule and the fatigue ratio 5/12 = 0.42 >= 0.2. The generator sets the outer fillet to 5 + 12 = 17 mm."
      },
      "base_hole_diameter": {
        "value": 10.0,
        "unit": "mm",
        "source": "USER",
        "trace": [
          "R10",
          "A05",
          "A10"
        ],
        "rationale": "The user's Ø10 finished hole. It is kept as given, although it is the ISO 273 coarse clearance for M8, not the medium value of 9.0 (advisory STD-ISO273-MEDIUM)."
      },
      "base_hole_rows": {
        "value": 1.0,
        "unit": "count",
        "source": "ASSUMPTION",
        "trace": [
          "R10",
          "A06"
        ],
        "rationale": "The two base holes are set as one row across the width (1 x 2 = 2 holes, R10)."
      },
      "base_hole_cols": {
        "value": 2.0,
        "unit": "count",
        "source": "ASSUMPTION",
        "trace": [
          "R10",
          "A06"
        ],
        "rationale": "Two columns symmetric about y = 0 give the 2 holes of R10 and a lateral bolt spread against roll moments."
      },
      "base_hole_x0": {
        "value": 75.0,
        "unit": "mm",
        "source": "ASSUMPTION",
        "trace": [
          "A06",
          "GL-HOLE-EDGE-DISTANCE",
          "R05"
        ],
        "rationale": "The row sits on the free part of the base, well clear of the bend fillet end at x = 15 (gap of 55 mm to the hole edge leaves room for the bolt head and tool). The distance to the free end x = 120 is 45 mm >= 15 mm (1.5 d)."
      },
      "base_hole_pitch_x": {
        "value": 30.0,
        "unit": "mm",
        "source": "ASSUMPTION",
        "trace": [
          "A06"
        ],
        "rationale": "Ignored by the generator because there is only 1 row. Placeholder value only."
      },
      "base_hole_pitch_y": {
        "value": 36.0,
        "unit": "mm",
        "source": "ASSUMPTION",
        "trace": [
          "A06",
          "GL-HOLE-EDGE-DISTANCE",
          "R06"
        ],
        "rationale": "Holes at y = +/-18. Side edge distance is 35 - 18 = 17 mm >= 15 mm (1.5 x 10)."
      },
      "upright_hole_diameter": {
        "value": 8.0,
        "unit": "mm",
        "source": "USER",
        "trace": [
          "R11",
          "A05",
          "A10"
        ],
        "rationale": "The user's Ø8 finished hole. It is kept as given, although it is a large clearance for M6 and not an ISO 273 medium value (advisory STD-ISO273-MEDIUM)."
      },
      "upright_hole_rows": {
        "value": 1.0,
        "unit": "count",
        "source": "ASSUMPTION",
        "trace": [
          "R11",
          "A06"
        ],
        "rationale": "One row across the width gives 1 x 2 = 2 holes (R11)."
      },
      "upright_hole_cols": {
        "value": 2.0,
        "unit": "count",
        "source": "ASSUMPTION",
        "trace": [
          "R11",
          "A06"
        ],
        "rationale": "Two columns symmetric about y = 0 for the front-wing interface."
      },
      "upright_hole_z0": {
        "value": 45.0,
        "unit": "mm",
        "source": "ASSUMPTION",
        "trace": [
          "A06",
          "GL-HOLE-EDGE-DISTANCE",
          "R09"
        ],
        "rationale": "The distance to the top edge z = 65 is 20 mm >= 12 mm (1.5 x 8). The hole is 28 mm above the inner fillet end at z = 17, which leaves bolt-head and tool access."
      },
      "upright_hole_pitch_z": {
        "value": 20.0,
        "unit": "mm",
        "source": "ASSUMPTION",
        "trace": [
          "A06"
        ],
        "rationale": "Ignored by the generator because there is only 1 row. Placeholder value only."
      },
      "upright_hole_pitch_y": {
        "value": 36.0,
        "unit": "mm",
        "source": "ASSUMPTION",
        "trace": [
          "A06",
          "GL-HOLE-EDGE-DISTANCE",
          "R06"
        ],
        "rationale": "Holes at y = +/-18, matching the base pattern. Side edge distance is 17 mm >= 12 mm (1.5 x 8)."
      }
    },
    "design_inputs": {
      "base_fastener": "M8",
      "upright_fastener": "M6",
      "base_mates_with": "vehicle-side mounting structure (chassis/nose), base bottom face z=0 (A07)",
      "upright_mates_with": "front wing mounting pylon/interface, upright outer face x=0 (A07)"
    },
    "manufacturing": {
      "process": "machined",
      "material": "AL7075-T6"
    },
    "load_case": {
      "description": "No load case was given by the user (M03/A04). Force and lever arm are set to 0 as a 'no load' marker, so STR-PLATE-BENDING is reported as NOT_RUN, not passed. The safety factor of 1.0 is a placeholder only and is not evaluated.",
      "force_n": 0.0,
      "lever_arm_mm": 0.0,
      "required_safety_factor": 1.0,
      "trace": [
        "M03",
        "A04",
        "A11"
      ]
    },
    "new_assumptions": [
      {
        "id": "A10",
        "text": "Fastener designations: M8 for the Ø10 base holes and M6 for the Ø8 upright holes. The user's hole diameters are kept as the finished diameters.",
        "rationale": "The generator requires a fastener string (the previous plan failed with base_fastener/upright_fastener = None). Ø10 is the ISO 273 coarse clearance for M8. Ø8 is the nearest usable clearance for M6. The user specified holes, not bolts (A05).",
        "impact": "STD-ISO273-MEDIUM will flag an advisory mismatch. The bolt size and fit must be confirmed by the user before mating with real parts.",
        "affects": [
          "R10",
          "R11",
          "A05"
        ]
      },
      {
        "id": "A11",
        "text": "The load case is entered as force 0 N and lever arm 0 mm with a placeholder safety factor of 1.0. This only signals 'no load defined'.",
        "rationale": "The schema requires a load case, but no load was given and loads must not be invented (A04).",
        "impact": "The structural check is NOT_RUN. Strength is unverified until the user supplies a load.",
        "affects": [
          "M03",
          "A04"
        ]
      }
    ],
    "verification_plan": [
      "Fusion measurement: bounding box in the local frame is 120 x 70 x 65 mm (R05, R06, R09). Base thickness is 12 mm and upright thickness is 10 mm (R07, R08).",
      "Fusion measurement: 2 x Ø10 base holes at x = 75, y = +/-18 and 2 x Ø8 upright holes at z = 45, y = +/-18. Count and diameters match R10 and R11.",
      "Fusion measurement: inner bend fillet R5 is present (R12).",
      "Rule check: DFM-MACH-WALL-MIN (10 mm >= 2 mm), DFM-MACH-INNER-RADIUS-MIN (5 >= 3), DFM-DFMEA-FATIGUE-FILLET (0.42 >= 0.2), GL-HOLE-EDGE-DISTANCE (min ratio 17/10 = 1.7 >= 1.5).",
      "Rule check: STD-ISO273-MEDIUM is expected to give an ADVISORY mismatch for M8/Ø10 and M6/Ø8. The user diameters are retained (A10).",
      "Placement read-back: the occurrence transform equals position (500, -250, 150) mm and R = Rz(60)*Ry(35)*Rx(15) (R18-R23, A09).",
      "Mass from Fusion volume x 2810 kg/m3 (AL7075-T6, A02). Indicative only.",
      "Hand calculation: STR-PLATE-BENDING is NOT_RUN because there is no load case (A04). No structural-safety claim is made (A01)."
    ],
    "placement": {
      "position_mm": [
        500.0,
        -250.0,
        150.0
      ],
      "rotation_deg": [
        15.0,
        35.0,
        60.0
      ],
      "source": "USER",
      "trace": [
        "R17",
        "R18",
        "R19",
        "R20",
        "R21",
        "R22",
        "R23",
        "A09"
      ],
      "rationale": "The user-stated pose of the generator origin, applied as R = Rz(yaw)*Ry(pitch)*Rx(roll) per the project convention."
    }
  },
  "assumptions": [
    {
      "id": "A01",
      "text": "Scope: concept-level demonstrator with nominal geometry only. No FEA, no tolerancing, no FIA compliance, structural-safety or race-readiness claim.",
      "rationale": "Stated by the user (R02, R03) and by project policy.",
      "impact": "All results are indicative, for demonstration and assembly-framework purposes.",
      "affects": [
        "R01",
        "R02",
        "R03"
      ]
    },
    {
      "id": "A02",
      "text": "Material is assumed to be a machinable high-strength aluminium alloy (7075-T6 class) until the user specifies otherwise.",
      "rationale": "A common choice for machined motorsport brackets. The user did not specify a material.",
      "impact": "Affects only mass properties and any later strength check, not the geometry.",
      "affects": [
        "M01"
      ]
    },
    {
      "id": "A03",
      "text": "The part is assumed to be machined from billet (the only process the l_bracket generator supports).",
      "rationale": "The user asked for a manufacturable part without naming a process.",
      "impact": "Internal corners use fillets of at least the R12 minimum. No draft or casting features.",
      "affects": [
        "M02",
        "R12"
      ]
    },
    {
      "id": "A04",
      "text": "No load case is defined. Load-dependent structural checks are reported as NOT_RUN, not as passed.",
      "rationale": "The user gave no load, and loads must not be invented.",
      "impact": "Strength and stiffness of the bracket are unverified until the user supplies a load case.",
      "affects": [
        "M03"
      ]
    },
    {
      "id": "A05",
      "text": "The Ø10 and Ø8 values are treated as finished hole diameters. Bolt thread, grade and clearance class are not specified.",
      "rationale": "The user specified holes, not fasteners (R10, R11).",
      "impact": "Fastener selection and hole fit must be confirmed before interfacing with real parts.",
      "affects": [
        "R10",
        "R11"
      ]
    },
    {
      "id": "A06",
      "text": "Hole positions, spacing and edge distances follow the l_bracket generator's parametric defaults. Each pair is placed in its own leg, and the values are exposed as named parameters.",
      "rationale": "Not given by the user. R03 allows project-defined geometric assumptions.",
      "impact": "Mating F1 parts must later adopt or re-parameterise these interface positions.",
      "affects": [
        "R10",
        "R11",
        "R24"
      ]
    },
    {
      "id": "A07",
      "text": "Base holes (R10) form the vehicle/chassis-side connection zone. Upright holes (R11) form the front-wing connection zone. Together they satisfy the two connection zones of R04.",
      "rationale": "Follows from the hole labels in the request.",
      "impact": "Defines which leg faces which mating part in later assemblies.",
      "affects": [
        "R04",
        "R10",
        "R11"
      ]
    },
    {
      "id": "A08",
      "text": "The L-profile (a base leg with an upright at one end) provides the required directional asymmetry along local X.",
      "rationale": "R13 asks for an orientation-defined geometry. The l_bracket form is inherently asymmetric along its longitudinal axis.",
      "impact": "No additional asymmetric features are added unless requested.",
      "affects": [
        "R13"
      ]
    },
    {
      "id": "A09",
      "text": "Roll, pitch and yaw are applied about X, Y and Z respectively, using the project's standard pose convention (VCS: +X front, +Y left, +Z up). The position is the placement of the generator origin.",
      "rationale": "The user did not state a rotation order. The project convention is used for consistency with other parts.",
      "impact": "A different rotation order would yield a different final orientation.",
      "affects": [
        "R18",
        "R19",
        "R20",
        "R21",
        "R22",
        "R23",
        "R17"
      ]
    },
    {
      "id": "A10",
      "text": "Fastener designations: M8 for the Ø10 base holes and M6 for the Ø8 upright holes. The user's hole diameters are kept as the finished diameters.",
      "rationale": "The generator requires a fastener string (the previous plan failed with base_fastener/upright_fastener = None). Ø10 is the ISO 273 coarse clearance for M8. Ø8 is the nearest usable clearance for M6. The user specified holes, not bolts (A05).",
      "impact": "STD-ISO273-MEDIUM will flag an advisory mismatch. The bolt size and fit must be confirmed by the user before mating with real parts.",
      "affects": [
        "R10",
        "R11",
        "A05"
      ]
    },
    {
      "id": "A11",
      "text": "The load case is entered as force 0 N and lever arm 0 mm with a placeholder safety factor of 1.0. This only signals 'no load defined'.",
      "rationale": "The schema requires a load case, but no load was given and loads must not be invented (A04).",
      "impact": "The structural check is NOT_RUN. Strength is unverified until the user supplies a load.",
      "affects": [
        "M03",
        "A04"
      ]
    }
  ],
  "cad": {
    "ok": true,
    "result": {
      "component_name": "f1parts BRK-001 PART 001 - F1 front wing mounting bracket",
      "body_name": "BRK-001_body",
      "document": "Untitled",
      "created_document": true,
      "fusion_version": "2705.1.30",
      "material": null,
      "warnings": []
    },
    "script": "scripts/01_build.py"
  },
  "cad_error_output": null,
  "validation": [
    {
      "check_id": "PROC-CAD-BUILD",
      "title": "Fusion CAD build completed",
      "category": "PROCESS",
      "scope": "CAD_BUILD",
      "claim": "The generated Fusion script ran to completion without error.",
      "status": "VERIFIED",
      "severity": "BLOCKING",
      "method": "FUSION_MEASUREMENT",
      "measured": null,
      "limit": null,
      "unit": null,
      "rule_id": null,
      "message": ""
    },
    {
      "check_id": "GEO-BODY-COUNT",
      "title": "Expected number of solid bodies",
      "category": "GEOMETRY",
      "scope": "GEOMETRY",
      "claim": "Fusion reports the designed number of bodies, all solid.",
      "status": "VERIFIED",
      "severity": "BLOCKING",
      "method": "FUSION_MEASUREMENT",
      "measured": 1,
      "limit": 1,
      "unit": null,
      "rule_id": null,
      "message": ""
    },
    {
      "check_id": "GEO-FEATURE-HEALTH",
      "title": "All timeline features healthy",
      "category": "GEOMETRY",
      "scope": "GEOMETRY",
      "claim": "Every Fusion timeline feature of the component computed without warning or error.",
      "status": "VERIFIED",
      "severity": "BLOCKING",
      "method": "FUSION_MEASUREMENT",
      "measured": "8/8 healthy",
      "limit": null,
      "unit": null,
      "rule_id": null,
      "message": ""
    },
    {
      "check_id": "GEO-SKETCH-CONSTRAINED",
      "title": "All sketches fully constrained",
      "category": "GEOMETRY",
      "scope": "GEOMETRY",
      "claim": "Every sketch is fully constrained (geometry fully driven by dimensions/constraints).",
      "status": "VERIFIED",
      "severity": "ADVISORY",
      "method": "FUSION_MEASUREMENT",
      "measured": "3/3",
      "limit": null,
      "unit": null,
      "rule_id": null,
      "message": ""
    },
    {
      "check_id": "GEO-BBOX",
      "title": "Bounding box matches design (component frame)",
      "category": "GEOMETRY",
      "scope": "GEOMETRY",
      "claim": "Fusion-measured overall extents in the component's own frame equal the designed extents (overall size only; independent of placement).",
      "status": "VERIFIED",
      "severity": "BLOCKING",
      "method": "FUSION_MEASUREMENT",
      "measured": {
        "min": [
          0.0,
          -35.0,
          0.0
        ],
        "max": [
          120.0,
          35.0,
          65.0
        ]
      },
      "limit": {
        "min": [
          0.0,
          -35.0,
          0.0
        ],
        "max": [
          120.0,
          35.0,
          65.0
        ],
        "tol_mm": 0.001
      },
      "unit": "mm",
      "rule_id": null,
      "message": "max deviation 0.00e+00 mm"
    },
    {
      "check_id": "GEO-VOLUME",
      "title": "Volume matches analytic model",
      "category": "GEOMETRY",
      "scope": "GEOMETRY",
      "claim": "Fusion-measured volume equals the generator's analytic volume (consistency with design intent).",
      "status": "VERIFIED",
      "severity": "BLOCKING",
      "method": "FUSION_MEASUREMENT",
      "measured": 131043.893,
      "limit": "131043.893 ± 1e-04 rel",
      "unit": "mm3",
      "rule_id": null,
      "message": "relative deviation 8.88e-16"
    },
    {
      "check_id": "GEO-PARAM-SYNC",
      "title": "Fusion user parameters equal the component record",
      "category": "GEOMETRY",
      "scope": "PARAMETERS",
      "claim": "Fusion holds the parameter values of the record (does not by itself prove the geometry follows them).",
      "status": "VERIFIED",
      "severity": "BLOCKING",
      "method": "FUSION_MEASUREMENT",
      "measured": "15/15",
      "limit": null,
      "unit": null,
      "rule_id": null,
      "message": ""
    },
    {
      "check_id": "GEO-PLACEMENT",
      "title": "Component placed at the planned pose",
      "category": "GEOMETRY",
      "scope": "PLACEMENT",
      "claim": "Fusion's occurrence transform equals the planned pose (position + rotation), nothing is pending, and every world-space body vertex equals the planned pose applied to its local vertex.",
      "status": "VERIFIED",
      "severity": "BLOCKING",
      "method": "FUSION_MEASUREMENT",
      "measured": {
        "position_mm": [
          500.0,
          -250.0,
          150.0
        ],
        "translation_dev_mm": 0.0,
        "rotation_dev_deg": 0.0,
        "vertices_checked": 24,
        "max_vertex_dev_mm": 6.503961262668462e-07,
        "pending_snapshot": false
      },
      "limit": {
        "position_mm": [
          500.0,
          -250.0,
          150.0
        ],
        "rotation_deg": [
          15.0,
          35.0,
          60.0
        ],
        "tol_mm": 0.001,
        "tol_deg": 0.0001
      },
      "unit": null,
      "rule_id": null,
      "message": "placement verified (24 vertices, max deviation 6.5e-07 mm)"
    },
    {
      "check_id": "IFC-HOLE-GEOMETRY",
      "title": "Own mounting holes: diameter, axis and position as designed",
      "category": "INTERFACE",
      "scope": "HOLE_GEOMETRY",
      "claim": "This component's own mounting holes exist in Fusion with the designed diameter, axis and position. Says nothing about the mating part.",
      "status": "VERIFIED",
      "severity": "BLOCKING",
      "method": "FUSION_MEASUREMENT",
      "measured": "4/4 holes matched",
      "limit": "position/diameter tol 0.001 mm",
      "unit": "mm",
      "rule_id": null,
      "message": "All own mounting holes found in Fusion geometry."
    },
    {
      "check_id": "IFC-MATING@IF-BASE",
      "title": "Mating fit of IF-BASE with vehicle-side mounting structure (chassis/nose), base bottom face z=0 (A07)",
      "category": "INTERFACE",
      "scope": "MATING_INTERFACE",
      "claim": "Whether the mating part's holes/faces coincide with this interface. Not checked: the mating part is not modelled in the project.",
      "status": "NOT_VERIFIED",
      "severity": "ADVISORY",
      "method": "NOT_RUN",
      "measured": null,
      "limit": null,
      "unit": null,
      "rule_id": null,
      "message": "Mating part geometry not available; fit, hole alignment and clearance are not verified."
    },
    {
      "check_id": "IFC-MATING@IF-UPRIGHT",
      "title": "Mating fit of IF-UPRIGHT with front wing mounting pylon/interface, upright outer face x=0 (A07)",
      "category": "INTERFACE",
      "scope": "MATING_INTERFACE",
      "claim": "Whether the mating part's holes/faces coincide with this interface. Not checked: the mating part is not modelled in the project.",
      "status": "NOT_VERIFIED",
      "severity": "ADVISORY",
      "method": "NOT_RUN",
      "measured": null,
      "limit": null,
      "unit": null,
      "rule_id": null,
      "message": "Mating part geometry not available; fit, hole alignment and clearance are not verified."
    },
    {
      "check_id": "DFM-MACH-WALL-MIN",
      "title": "Minimum machinable wall thickness",
      "category": "MANUFACTURING",
      "scope": "MANUFACTURING_RULE",
      "claim": "Design value of 'wall_thickness' satisfies rule DFM-MACH-WALL-MIN as transcribed (transcription NOT_VERIFIED).",
      "status": "ASSUMPTION",
      "severity": "BLOCKING",
      "method": "PARAMETER_CHECK",
      "measured": 10.0,
      "limit": ">= 2.0",
      "unit": "mm",
      "rule_id": "DFM-MACH-WALL-MIN",
      "message": "Passes; rule transcription not yet human-verified."
    },
    {
      "check_id": "DFM-MACH-INNER-RADIUS-MIN",
      "title": "Minimum internal corner radius (end-mill access)",
      "category": "MANUFACTURING",
      "scope": "MANUFACTURING_RULE",
      "claim": "Design value of 'internal_corner_radius' satisfies rule DFM-MACH-INNER-RADIUS-MIN as transcribed (transcription NOT_VERIFIED).",
      "status": "ASSUMPTION",
      "severity": "BLOCKING",
      "method": "PARAMETER_CHECK",
      "measured": 5.0,
      "limit": ">= 3.0",
      "unit": "mm",
      "rule_id": "DFM-MACH-INNER-RADIUS-MIN",
      "message": "Passes; rule transcription not yet human-verified."
    },
    {
      "check_id": "DFM-DFMEA-FATIGUE-FILLET",
      "title": "Fatigue - internal fillet radius relative to wall thickness",
      "category": "MANUFACTURING",
      "scope": "MANUFACTURING_RULE",
      "claim": "Design value of 'fillet_to_thickness_ratio' satisfies rule DFM-DFMEA-FATIGUE-FILLET as transcribed (transcription NOT_VERIFIED).",
      "status": "ASSUMPTION",
      "severity": "ADVISORY",
      "method": "PARAMETER_CHECK",
      "measured": 0.4167,
      "limit": ">= 0.2",
      "unit": null,
      "rule_id": "DFM-DFMEA-FATIGUE-FILLET",
      "message": "Passes; rule transcription not yet human-verified."
    },
    {
      "check_id": "STD-ISO273-MEDIUM",
      "title": "Clearance hole diameter for metric bolts (ISO 273, medium series)",
      "category": "MANUFACTURING",
      "scope": "MANUFACTURING_RULE",
      "claim": "Design value of 'clearance_holes' satisfies rule STD-ISO273-MEDIUM as transcribed (transcription NOT_VERIFIED).",
      "status": "NON_COMPLIANT",
      "severity": "ADVISORY",
      "method": "PARAMETER_CHECK",
      "measured": [
        {
          "item": "M8",
          "value": 10.0
        },
        {
          "item": "M6",
          "value": 8.0
        }
      ],
      "limit": {
        "M3": 3.4,
        "M4": 4.5,
        "M5": 5.5,
        "M6": 6.6,
        "M8": 9.0,
        "M10": 11.0,
        "M12": 13.5
      },
      "unit": "mm",
      "rule_id": "STD-ISO273-MEDIUM",
      "message": "M8: 10.0 (table 9.0); M6: 8.0 (table 6.6)"
    },
    {
      "check_id": "GL-HOLE-EDGE-DISTANCE",
      "title": "Bolt hole centre to free edge distance",
      "category": "MANUFACTURING",
      "scope": "MANUFACTURING_RULE",
      "claim": "Design value of 'hole_edge_distance_ratio' satisfies rule GL-HOLE-EDGE-DISTANCE as transcribed (transcription NOT_VERIFIED).",
      "status": "ASSUMPTION",
      "severity": "BLOCKING",
      "method": "PARAMETER_CHECK",
      "measured": 1.7,
      "limit": ">= 1.5",
      "unit": null,
      "rule_id": "GL-HOLE-EDGE-DISTANCE",
      "message": "Passes; rule transcription not yet human-verified."
    },
    {
      "check_id": "STR-PLATE-BENDING",
      "title": "Hand calc: leg bending stress",
      "category": "STRUCTURAL",
      "scope": "STRUCTURAL_CHECK",
      "claim": "Hand calculation not run: the plan has no load case (zero force or lever arm).",
      "status": "NOT_VERIFIED",
      "severity": "ADVISORY",
      "method": "NOT_RUN",
      "measured": {
        "force_N": 0.0,
        "lever_arm_mm": 0.0
      },
      "limit": null,
      "unit": null,
      "rule_id": null,
      "message": "No load case given - plate bending hand calculation not run; the part's strength is not checked."
    },
    {
      "check_id": "STR-ADEQUACY",
      "title": "Overall structural adequacy",
      "category": "STRUCTURAL",
      "scope": "STRUCTURAL_ADEQUACY",
      "claim": "Whether the part is structurally adequate in service. Not established: only one simplified hand calculation was run.",
      "status": "NOT_VERIFIED",
      "severity": "ADVISORY",
      "method": "NOT_RUN",
      "measured": null,
      "limit": null,
      "unit": null,
      "rule_id": null,
      "message": "Not analysed: bolt loads/prying, base-leg bending, fatigue, stress concentration, FEA."
    },
    {
      "check_id": "FIA-APPLICABILITY",
      "title": "FIA rules for this component",
      "category": "FIA",
      "scope": "FIA",
      "claim": "None of the structured FIA rules in the project targets this component type. No FIA compliance statement of any kind.",
      "status": "NOT_APPLICABLE",
      "severity": "ADVISORY",
      "method": "NOT_RUN",
      "measured": "6 structured FIA rules loaded; 0 apply to 'l_bracket'",
      "limit": null,
      "unit": null,
      "rule_id": null,
      "message": "No structured FIA rule applies to this component type; no FIA claim is made."
    }
  ],
  "blocking_failures": [],
  "loops": {
    "used": 1,
    "max": 3
  }
}
```

## Response JSON schema

```json
{
  "$defs": {
    "Assumption": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "pattern": "^A\\d{2,3}$",
          "title": "Id",
          "type": "string"
        },
        "text": {
          "title": "Text",
          "type": "string"
        },
        "rationale": {
          "title": "Rationale",
          "type": "string"
        },
        "impact": {
          "default": "",
          "title": "Impact",
          "type": "string"
        },
        "affects": {
          "items": {
            "type": "string"
          },
          "title": "Affects",
          "type": "array"
        }
      },
      "required": [
        "id",
        "text",
        "rationale"
      ],
      "title": "Assumption",
      "type": "object"
    },
    "ParamSource": {
      "enum": [
        "REQUIREMENT",
        "ASSUMPTION",
        "RULE",
        "DERIVED",
        "USER",
        "IMAGE_EVIDENCE"
      ],
      "title": "ParamSource",
      "type": "string"
    },
    "PlannedParam": {
      "additionalProperties": false,
      "properties": {
        "value": {
          "title": "Value",
          "type": "number"
        },
        "unit": {
          "enum": [
            "mm",
            "deg",
            "N",
            "kg",
            "count",
            ""
          ],
          "title": "Unit",
          "type": "string"
        },
        "source": {
          "$ref": "#/$defs/ParamSource"
        },
        "trace": {
          "items": {
            "type": "string"
          },
          "title": "Trace",
          "type": "array"
        },
        "rationale": {
          "title": "Rationale",
          "type": "string"
        }
      },
      "required": [
        "value",
        "unit",
        "source",
        "rationale"
      ],
      "title": "PlannedParam",
      "type": "object"
    }
  },
  "additionalProperties": false,
  "properties": {
    "decision": {
      "enum": [
        "ACCEPT",
        "REVISE",
        "STOP"
      ],
      "title": "Decision",
      "type": "string"
    },
    "rationale": {
      "title": "Rationale",
      "type": "string"
    },
    "parameter_changes": {
      "additionalProperties": {
        "$ref": "#/$defs/PlannedParam"
      },
      "title": "Parameter Changes",
      "type": "object"
    },
    "new_assumptions": {
      "items": {
        "$ref": "#/$defs/Assumption"
      },
      "title": "New Assumptions",
      "type": "array"
    }
  },
  "required": [
    "decision",
    "rationale"
  ],
  "title": "ReviewResponse",
  "type": "object"
}
```
