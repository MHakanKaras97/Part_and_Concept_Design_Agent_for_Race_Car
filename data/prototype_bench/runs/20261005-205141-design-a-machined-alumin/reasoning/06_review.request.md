# Reasoning task 06_review (run 20261005-205141-design-a-machined-alumin)

Write your answer as JSON to `06_review.response.json` in this folder, then run:

    python -m agent step 20261005-205141-design-a-machined-alumin

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
  "request": "Design a machined aluminium L-bracket to mount a 2 kg sensor box to a flat plate with four M6 bolts.",
  "plan": {
    "generator": "l_bracket",
    "component_name": "Sensor box bracket",
    "steps": [
      "Fix the interfaces from the user's words: base leg 4 x M6 to the plate (R03); carrying leg 2 x M5, 40 mm apart horizontally (R06), hole centres 35 mm above the plate (R08).",
      "Size clearance holes per STD-ISO273-MEDIUM: M6 -> 6.6 mm, M5 -> 5.5 mm.",
      "Choose width, leg lengths and base-hole layout so every hole centre is >= 1.5 d from free edges (GL-HOLE-EDGE-DISTANCE) and clear of the bend.",
      "Choose thickness from the bending hand calculation with the user's lever arm (R07) and the assumed design load (A03, A02); respect min wall (DFM-MACH-WALL-MIN).",
      "Internal bend radius per DFM-MACH-INNER-RADIUS-MIN and DFM-DFMEA-FATIGUE-FILLET.",
      "Build the parametric model in Fusion; inspect read-only; validate; review."
    ],
    "parameters": {
      "bracket_thickness": {
        "value": 5.0,
        "unit": "mm",
        "source": "ASSUMPTION",
        "trace": [
          "A01",
          "A03",
          "DFM-MACH-WALL-MIN"
        ],
        "rationale": "Engineering decision: hand calc with the assumed load gives a large margin already at 4 mm; 5 mm chosen for bolt-clamping stiffness."
      },
      "bend_inner_radius": {
        "value": 4.0,
        "unit": "mm",
        "source": "RULE",
        "trace": [
          "DFM-MACH-INNER-RADIUS-MIN",
          "DFM-DFMEA-FATIGUE-FILLET"
        ],
        "rationale": ">= 3 mm end-mill rule and >= 0.2 t fatigue rule."
      },
      "bracket_width": {
        "value": 60.0,
        "unit": "mm",
        "source": "DERIVED",
        "trace": [
          "R06",
          "GL-HOLE-EDGE-DISTANCE",
          "A04"
        ],
        "rationale": "User M5 spacing 40 mm (R06) + 2 x 1.5 x 5.5 mm edge distance = 56.5 mm minimum -> 60 mm."
      },
      "leg_base_length": {
        "value": 64.0,
        "unit": "mm",
        "source": "DERIVED",
        "trace": [
          "GL-HOLE-EDGE-DISTANCE",
          "A04",
          "A05"
        ],
        "rationale": "Last base hole row at 52 mm + 1.5 x 6.6 mm = 61.9 mm minimum -> 64 mm."
      },
      "leg_upright_height": {
        "value": 50.0,
        "unit": "mm",
        "source": "DERIVED",
        "trace": [
          "R08",
          "GL-HOLE-EDGE-DISTANCE",
          "A04"
        ],
        "rationale": "User hole height 35 mm (R08) + 1.5 x 5.5 mm = 43.25 mm minimum -> 50 mm."
      },
      "base_hole_diameter": {
        "value": 6.6,
        "unit": "mm",
        "source": "RULE",
        "trace": [
          "STD-ISO273-MEDIUM",
          "R03"
        ],
        "rationale": "ISO 273 medium clearance for the user's M6 bolts."
      },
      "base_hole_x0": {
        "value": 22.0,
        "unit": "mm",
        "source": "ASSUMPTION",
        "trace": [
          "A06"
        ],
        "rationale": "Engineering decision: socket access next to the carrying leg (A06)."
      },
      "base_hole_pitch_x": {
        "value": 30.0,
        "unit": "mm",
        "source": "ASSUMPTION",
        "trace": [
          "A05"
        ],
        "rationale": "Engineering decision: spread the four M6 bolts along the base to resist the overturning moment; plate drilled to suit (A05)."
      },
      "base_hole_pitch_y": {
        "value": 36.0,
        "unit": "mm",
        "source": "DERIVED",
        "trace": [
          "GL-HOLE-EDGE-DISTANCE",
          "A05"
        ],
        "rationale": "Side edge distance (30 - 18) = 12 mm = 1.82 d >= 1.5 d."
      },
      "base_hole_rows": {
        "value": 2.0,
        "unit": "count",
        "source": "REQUIREMENT",
        "trace": [
          "R03",
          "A05"
        ],
        "rationale": "Four M6 bolts (R03) arranged 2 x 2 (A05)."
      },
      "base_hole_cols": {
        "value": 2.0,
        "unit": "count",
        "source": "REQUIREMENT",
        "trace": [
          "R03",
          "A05"
        ],
        "rationale": "Four M6 bolts (R03) arranged 2 x 2 (A05)."
      },
      "upright_hole_diameter": {
        "value": 5.5,
        "unit": "mm",
        "source": "RULE",
        "trace": [
          "STD-ISO273-MEDIUM",
          "R06"
        ],
        "rationale": "ISO 273 medium clearance for the user's M5 bolts."
      },
      "upright_hole_z0": {
        "value": 35.0,
        "unit": "mm",
        "source": "USER",
        "trace": [
          "M06",
          "R08"
        ],
        "rationale": "User: hole centres 35 mm above the flat plate (R08 interpretation of M06)."
      },
      "upright_hole_pitch_z": {
        "value": 0.0,
        "unit": "mm",
        "source": "DERIVED",
        "trace": [],
        "rationale": "Single row of holes (R06) - not used."
      },
      "upright_hole_pitch_y": {
        "value": 40.0,
        "unit": "mm",
        "source": "USER",
        "trace": [
          "M01",
          "R06"
        ],
        "rationale": "User: M5 bolts 40 mm apart horizontally."
      },
      "upright_hole_rows": {
        "value": 1.0,
        "unit": "count",
        "source": "USER",
        "trace": [
          "M01",
          "R06"
        ],
        "rationale": "Two bolts side by side horizontally (R06 interpretation)."
      },
      "upright_hole_cols": {
        "value": 2.0,
        "unit": "count",
        "source": "USER",
        "trace": [
          "M01",
          "R06"
        ],
        "rationale": "Two M5 bolts (user)."
      }
    },
    "design_inputs": {
      "base_fastener": "M6",
      "upright_fastener": "M5",
      "base_mates_with": "flat_plate (external, not modelled)",
      "upright_mates_with": "sensor_box (external, not modelled)"
    },
    "manufacturing": {
      "process": "machined",
      "material": "AL6061-T6"
    },
    "load_case": {
      "description": "Box weight 2 kg (R02) x assumed factor 5 (A03) = 98.1 N acting at the user's centre-of-mass offset of 40 mm (R07) from the carrying-leg face: constant bending moment on that leg.",
      "force_n": 98.1,
      "lever_arm_mm": 40.0,
      "required_safety_factor": 2.0,
      "trace": [
        "R02",
        "R07",
        "A03"
      ]
    },
    "new_assumptions": [
      {
        "id": "A06",
        "text": "ENGINEERING ASSUMPTION (not stated by the user): M6 hex-head bolts with washers installed from above with a socket; >= 15 mm from hole centre to the inner face of the carrying leg.",
        "rationale": "Tool access for the base bolts next to the carrying leg.",
        "impact": "Sets base_hole_x0.",
        "affects": [
          "base_hole_x0"
        ]
      }
    ],
    "verification_plan": [
      "Pre-CAD (Python): manufacturing rules and the bending hand calculation.",
      "Fusion (read-only): body count, feature health, sketches constrained, bbox, volume vs analytic model, parameters vs record.",
      "Own hole geometry: all 4 M6 and 2 M5 holes at designed position, axis and diameter. Mating fit with plate and sensor box will remain NOT_VERIFIED (parts not modelled)."
    ]
  },
  "assumptions": [
    {
      "id": "A01",
      "text": "Concept-level design: nominal geometry, no tolerancing, no FEA or fatigue analysis; sizing by one hand calculation only.",
      "rationale": "MVP scope.",
      "impact": "Results are not a structural sign-off.",
      "affects": [
        "all"
      ]
    },
    {
      "id": "A02",
      "text": "ENGINEERING ASSUMPTION (not stated by the user): aluminium 6061-T6 (material id AL6061-T6).",
      "rationale": "Common general-purpose machining alloy; the request says only 'aluminium'.",
      "impact": "Handbook yield strength (NOT_VERIFIED) used in the bending check.",
      "affects": [
        "material",
        "load_case"
      ]
    },
    {
      "id": "A03",
      "text": "ENGINEERING ASSUMPTION (not stated by the user): design load = 5 x the static weight of the 2 kg box, required safety factor on yield 2.0.",
      "rationale": "No environment given; covers handling, shock and vibration at concept level.",
      "impact": "Drives plate thickness; must be confirmed for the real environment.",
      "affects": [
        "load_case",
        "bracket_thickness"
      ]
    },
    {
      "id": "A04",
      "text": "ENGINEERING ASSUMPTION (not stated by the user): no hard envelope limit; keep the bracket compact.",
      "rationale": "Envelope not stated.",
      "impact": "Leg lengths and width follow from hole layout and edge-distance rules.",
      "affects": [
        "leg_base_length",
        "leg_upright_height",
        "bracket_width"
      ]
    },
    {
      "id": "A05",
      "text": "ENGINEERING ASSUMPTION (not stated by the user): the flat plate will be drilled to match the bracket's M6 hole pattern.",
      "rationale": "No plate pattern given.",
      "impact": "The bracket defines the plate drilling pattern.",
      "affects": [
        "base_hole_x0",
        "base_hole_pitch_x",
        "base_hole_pitch_y"
      ]
    },
    {
      "id": "A06",
      "text": "ENGINEERING ASSUMPTION (not stated by the user): M6 hex-head bolts with washers installed from above with a socket; >= 15 mm from hole centre to the inner face of the carrying leg.",
      "rationale": "Tool access for the base bolts next to the carrying leg.",
      "impact": "Sets base_hole_x0.",
      "affects": [
        "base_hole_x0"
      ]
    }
  ],
  "cad": {
    "ok": true,
    "result": {
      "component_name": "BRK-002 Sensor box bracket",
      "body_name": "BRK-002_body",
      "document": "Untitled",
      "created_document": false,
      "fusion_version": "2705.1.11",
      "material": "Aluminum 6061",
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
      "title": "Bounding box matches design (VCS)",
      "category": "GEOMETRY",
      "scope": "GEOMETRY",
      "claim": "Fusion-measured overall extents equal the designed extents (overall size only).",
      "status": "VERIFIED",
      "severity": "BLOCKING",
      "method": "FUSION_MEASUREMENT",
      "measured": {
        "min": [
          0.0,
          -30.0,
          0.0
        ],
        "max": [
          64.0,
          30.0,
          50.0
        ]
      },
      "limit": {
        "min": [
          0.0,
          -30.0,
          0.0
        ],
        "max": [
          64.0,
          30.0,
          50.0
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
      "measured": 30941.231,
      "limit": "30941.231 ± 1e-04 rel",
      "unit": "mm3",
      "rule_id": null,
      "message": "relative deviation 1.18e-15"
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
      "measured": "14/14",
      "limit": null,
      "unit": null,
      "rule_id": null,
      "message": ""
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
      "measured": "6/6 holes matched",
      "limit": "position/diameter tol 0.001 mm",
      "unit": "mm",
      "rule_id": null,
      "message": "All own mounting holes found in Fusion geometry."
    },
    {
      "check_id": "IFC-MATING@IF-BASE",
      "title": "Mating fit of IF-BASE with flat_plate (external, not modelled)",
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
      "title": "Mating fit of IF-UPRIGHT with sensor_box (external, not modelled)",
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
      "measured": 5.0,
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
      "measured": 4.0,
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
      "measured": 0.8,
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
      "status": "ASSUMPTION",
      "severity": "ADVISORY",
      "method": "PARAMETER_CHECK",
      "measured": [
        {
          "item": "M6",
          "value": 6.6
        },
        {
          "item": "M5",
          "value": 5.5
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
      "message": "All items match the table."
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
      "measured": 1.8182,
      "limit": ">= 1.5",
      "unit": null,
      "rule_id": "GL-HOLE-EDGE-DISTANCE",
      "message": "Passes; rule transcription not yet human-verified."
    },
    {
      "check_id": "STR-PLATE-BENDING",
      "title": "Hand calc: leg bending stress vs yield",
      "category": "STRUCTURAL",
      "scope": "STRUCTURAL_CHECK",
      "claim": "One simplified hand calculation (plate bending at the critical section vs yield) meets the required safety factor. Not a structural-adequacy statement.",
      "status": "ASSUMPTION",
      "severity": "BLOCKING",
      "method": "HAND_CALC",
      "measured": {
        "moment_Nmm": 3924.0,
        "stress_MPa": 19.22,
        "safety_factor": 14.36
      },
      "limit": "SF >= 2.0",
      "unit": "MPa",
      "rule_id": null,
      "message": "Upright leg as a plate under constant moment M = F*e (payload weight F at CG offset e from the upright face); critical net section through the upright hole row (W - 2 x hole). Material AL6061-T6 yield 276.0 MPa (NOT_VERIFIED). Stress concentration at holes/fillet and fatigue NOT included."
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
    "used": 0,
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
        "USER"
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
