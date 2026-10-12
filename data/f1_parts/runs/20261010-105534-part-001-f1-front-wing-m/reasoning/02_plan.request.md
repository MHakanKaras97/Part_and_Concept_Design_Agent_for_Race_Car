# Reasoning task 02_plan (run 20261010-105534-part-001-f1-front-wing-m)

Write your answer as JSON to `02_plan.response.json` in this folder, then run:

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


# Task: engineering design plan

Using context.analysis (requirements, assumptions, answers), context.generator (parameters, local
frame, feasibility rules), context.rules (applicable manufacturing rules) and context.materials:

1. `steps`: a short ordered engineering plan (what is done and checked, in order).
2. `parameters`: a value for EVERY generator parameter (length params in mm, count params with
   unit "count"); parameters listed in context.generator.optional_params may be omitted (their documented
   default applies) - give them only when the requirements call for them. Each with source, trace and a one-line rationale. Source USER / REQUIREMENT only for values
   from the user's own words; IMAGE_EVIDENCE for values read from an attached image (trace the IMAGE requirement). Choose values that satisfy the
   listed rules and the generator feasibility constraints - Python will check them.
3. `design_inputs`: fasteners (e.g. "M6") and what each interface mates with.
4. `manufacturing`: process + material id from context.materials.
5. `load_case`: the load the bracket must carry for the hand calculation (force incl. any dynamic
   factor, lever arm, required safety factor), with trace. If it rests on assumptions, add them to
   `new_assumptions` (continue the A-numbering from the analysis).
6. `verification_plan`: what will be verified and how (Fusion measurement, rule check, hand calc).
7. `placement`: ONLY if the user stated where the component's local frame is placed in the project/vehicle
   coordinate system: position_mm and rotation_deg = (roll, pitch, yaw) about X, Y, Z, applied as
   R = Rz(yaw)·Ry(pitch)·Rx(roll), with source and trace like a parameter. Otherwise omit it (identity pose).

If context.feedback is present, a previous plan was rejected or failed checks: fix exactly those
issues and explain the change in the affected parameter rationales.


---

## Context

```json
{
  "request": "PART 001 — F1 Front Wing Mounting Bracket\n\nAmaç:\nÖn kanadın araç üzerindeki yapısal bağlantısını temsil eden, parametrik ve üretilebilir bir mounting bracket oluşturmak.\n\nBu ilk parça bir F1-inspired engineering demonstrator olacak.\nGerçek FIA homologasyon parçası olduğunu iddia etme.\nBoyutları ve geometrik kuralları proje kapsamında tanımlanmış mühendislik varsayımları olarak kabul et.\n\nParça şu özellikleri göstermeli:\n- rigid mounting bracket\n- iki ana bağlantı bölgesi\n- bolt holes\n- yeterli malzeme kalınlığı\n- fillet'ler\n- açıkça tanımlanmış parametrik ölçüler\n- simetrik olmayan / yönü belli bir geometri\n- Fusion assembly içerisinde anlamlı bir coordinate frame\n- daha sonra başka F1 parçalarıyla assembly oluşturulabilecek şekilde tasarlanmış olması\n\nInitial Part Parameters:\nOverall length: 120 mm\nOverall width: 70 mm\nBase thickness: 12 mm\nVertical support thickness: 10 mm\nSupport height: 65 mm\n\nMounting holes:\n- 2 × Ø10 mm base mounting holes\n- 2 × Ø8 mm front-wing mounting holes\n\nMinimum fillet:\nR5 mm\n\nCoordinate System:\nX: part longitudinal direction\nY: part lateral direction\nZ: vertical direction\nOrigin için şimdilik mevcut generator origin'ini koru.\n\nPlacement:\nPosition:\nX = 500 mm\nY = -250 mm\nZ = 150 mm\n\nRotation:\nRoll = 15°\nPitch = 35°\nYaw = 60°",
  "project": {
    "schema_version": 2,
    "id": "f1_parts",
    "name": "F1 parts",
    "kind": "bench",
    "description": "F1-inspired engineering components (concept-level demonstrators, not FIA-homologated parts), each designed with its own local frame and placed by pose. prototype_bench stays for test/diagnostic/regression work.",
    "coordinate_system": "VCS: +X front, +Y left, +Z up, mm (see docs/architecture.md)",
    "regulation": null,
    "fusion_namespace": "f1parts",
    "policy": {
      "critical_missing_info_must_be_asked": true,
      "allow_suggested_values_in_questions": false,
      "max_revision_loops": 3
    },
    "created": "2026-10-06T20:20:09+00:00"
  },
  "existing_components": [],
  "user_answers": {},
  "attachments": [],
  "analysis": {
    "component_type": "l_bracket",
    "summary": "PART 001 is an F1-inspired front-wing mounting bracket for a concept-level demonstrator. It does not claim FIA homologation. It maps to the l_bracket generator: a base leg holds 2 x Ø10 holes for the vehicle-side mount and an upright support holds 2 x Ø8 holes for the front-wing mount. The user gave the main dimensions (120 x 70 mm envelope, 12 mm base, 10 mm upright, 65 mm support height), a minimum R5 fillet, the local frame axes, the instruction to keep the generator origin, and the placement pose (500, -250, 150 mm; roll 15, pitch 35, yaw 60 deg). The user also said to treat dimensions and geometric rules as project engineering assumptions. For that reason the gaps that do not change the given geometry are assumed and labelled, not asked: material, manufacturing process, hole positions and edge distances, how the holes map to fasteners, and the rotation convention. No load case was given. Structural checks will therefore be NOT_RUN, not passed, until the user supplies a load.",
    "requirements": [
      {
        "id": "R01",
        "key": "function",
        "text": "The part is a rigid mounting bracket representing the structural connection of the front wing to the vehicle. It must be parametric and manufacturable.",
        "value": null,
        "unit": null,
        "source": "USER_REQUEST",
        "quote": "Ön kanadın araç üzerindeki yapısal bağlantısını temsil eden, parametrik ve üretilebilir bir mounting bracket oluşturmak.",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R02",
        "key": "scope_no_homologation_claim",
        "text": "The part is an F1-inspired engineering demonstrator. It must not be presented as a real FIA-homologated part.",
        "value": null,
        "unit": null,
        "source": "USER_REQUEST",
        "quote": "Gerçek FIA homologasyon parçası olduğunu iddia etme.",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R03",
        "key": "scope_dimensions_as_assumptions",
        "text": "Dimensions and geometric rules are to be treated as engineering assumptions defined within the project scope.",
        "value": null,
        "unit": null,
        "source": "USER_REQUEST",
        "quote": "Boyutları ve geometrik kuralları proje kapsamında tanımlanmış mühendislik varsayımları olarak kabul et.",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R04",
        "key": "function_two_mounting_zones",
        "text": "The bracket must have two main connection zones.",
        "value": null,
        "unit": null,
        "source": "USER_REQUEST",
        "quote": "iki ana bağlantı bölgesi",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R05",
        "key": "envelope",
        "text": "Overall bracket length (local X, longitudinal) is 120 mm.",
        "value": 120,
        "unit": "mm",
        "source": "USER_REQUEST",
        "quote": "Overall length: 120 mm",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R06",
        "key": "envelope",
        "text": "Overall bracket width (local Y, lateral) is 70 mm.",
        "value": 70,
        "unit": "mm",
        "source": "USER_REQUEST",
        "quote": "Overall width: 70 mm",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R07",
        "key": "base_thickness",
        "text": "Base leg thickness is 12 mm.",
        "value": 12,
        "unit": "mm",
        "source": "USER_REQUEST",
        "quote": "Base thickness: 12 mm",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R08",
        "key": "upright_thickness",
        "text": "Vertical support (upright) thickness is 10 mm.",
        "value": 10,
        "unit": "mm",
        "source": "USER_REQUEST",
        "quote": "Vertical support thickness: 10 mm",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R09",
        "key": "envelope",
        "text": "Support height (local Z) is 65 mm.",
        "value": 65,
        "unit": "mm",
        "source": "USER_REQUEST",
        "quote": "Support height: 65 mm",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R10",
        "key": "base_fastener",
        "text": "The base leg has 2 mounting holes of diameter 10 mm (vehicle-side connection).",
        "value": {
          "count": 2,
          "diameter": 10
        },
        "unit": "mm",
        "source": "USER_REQUEST",
        "quote": "2 × Ø10 mm base mounting holes",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R11",
        "key": "upright_fastener",
        "text": "The upright has 2 front-wing mounting holes of diameter 8 mm.",
        "value": {
          "count": 2,
          "diameter": 8
        },
        "unit": "mm",
        "source": "USER_REQUEST",
        "quote": "2 × Ø8 mm front-wing mounting holes",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R12",
        "key": "min_fillet",
        "text": "The minimum fillet radius is 5 mm.",
        "value": 5,
        "unit": "mm",
        "source": "USER_REQUEST",
        "quote": "R5 mm",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R13",
        "key": "orientation_asymmetric",
        "text": "The geometry must be non-symmetric, with a clearly identifiable orientation.",
        "value": null,
        "unit": null,
        "source": "USER_REQUEST",
        "quote": "simetrik olmayan / yönü belli bir geometri",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R14",
        "key": "local_frame_x",
        "text": "Local X is the part's longitudinal direction.",
        "value": null,
        "unit": null,
        "source": "USER_REQUEST",
        "quote": "X: part longitudinal direction",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R15",
        "key": "local_frame_y",
        "text": "Local Y is the part's lateral direction.",
        "value": null,
        "unit": null,
        "source": "USER_REQUEST",
        "quote": "Y: part lateral direction",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R16",
        "key": "local_frame_z",
        "text": "Local Z is the vertical direction.",
        "value": null,
        "unit": null,
        "source": "USER_REQUEST",
        "quote": "Z: vertical direction",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R17",
        "key": "local_origin",
        "text": "Keep the existing generator origin as the part origin for now.",
        "value": null,
        "unit": null,
        "source": "USER_REQUEST",
        "quote": "Origin için şimdilik mevcut generator origin'ini koru.",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R18",
        "key": "placement_x",
        "text": "Placement position X is 500 mm.",
        "value": 500,
        "unit": "mm",
        "source": "USER_REQUEST",
        "quote": "X = 500 mm",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R19",
        "key": "placement_y",
        "text": "Placement position Y is -250 mm.",
        "value": -250,
        "unit": "mm",
        "source": "USER_REQUEST",
        "quote": "Y = -250 mm",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R20",
        "key": "placement_z",
        "text": "Placement position Z is 150 mm.",
        "value": 150,
        "unit": "mm",
        "source": "USER_REQUEST",
        "quote": "Z = 150 mm",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R21",
        "key": "placement_roll",
        "text": "Placement roll is 15 deg.",
        "value": 15,
        "unit": "deg",
        "source": "USER_REQUEST",
        "quote": "Roll = 15°",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R22",
        "key": "placement_pitch",
        "text": "Placement pitch is 35 deg.",
        "value": 35,
        "unit": "deg",
        "source": "USER_REQUEST",
        "quote": "Pitch = 35°",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R23",
        "key": "placement_yaw",
        "text": "Placement yaw is 60 deg.",
        "value": 60,
        "unit": "deg",
        "source": "USER_REQUEST",
        "quote": "Yaw = 60°",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      },
      {
        "id": "R24",
        "key": "assembly_ready",
        "text": "The part must be designed so it can later be assembled with other F1 parts, with a meaningful coordinate frame inside the Fusion assembly.",
        "value": null,
        "unit": null,
        "source": "USER_REQUEST",
        "quote": "daha sonra başka F1 parçalarıyla assembly oluşturulabilecek şekilde tasarlanmış olması",
        "answer_id": null,
        "derived_from": [],
        "attachment_id": null,
        "image_evidence": null,
        "interpreted_by": "AI"
      }
    ],
    "missing_information": [
      {
        "id": "M01",
        "key": "material",
        "topic": "Bracket material",
        "why_it_matters": "Material drives mass, machinability and any later structural check. The user-given geometry does not depend on it.",
        "criticality": "IMPORTANT",
        "resolution": "ASSUME",
        "question": null,
        "assumption_id": "A02",
        "follows_up": null
      },
      {
        "id": "M02",
        "key": "manufacturing_process",
        "topic": "Manufacturing process",
        "why_it_matters": "The request asks for a manufacturable part but names no process. The process sets the allowed features and fillet rules; the generator supports only machined.",
        "criticality": "IMPORTANT",
        "resolution": "ASSUME",
        "question": null,
        "assumption_id": "A03",
        "follows_up": null
      },
      {
        "id": "M03",
        "key": "load",
        "topic": "Load case (force/mass, direction, dynamic or safety factor)",
        "why_it_matters": "Without a load case no structural check can be evaluated. Checks will be NOT_RUN rather than passed. The given dimensions are not changed by this gap.",
        "criticality": "IMPORTANT",
        "resolution": "ASSUME",
        "question": null,
        "assumption_id": "A04",
        "follows_up": null
      }
    ],
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
      }
    ]
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
    }
  ],
  "generator": {
    "id": "l_bracket",
    "version": "3",
    "description": "Generator: machined L-bracket (Prototype 1; v2 adds an optional separate upright thickness).\n\nDeterministic: design inputs -> (feasibility errors, DFM quantities, expected geometry,\ninterfaces, Fusion script). The Fusion script builds a fully parametric, named model.\n\nLocal component frame (documented, mm), t_b = bracket_thickness, t_u = upright_thickness (= t_b if not given):\n    origin  = outer corner of the L, on the bracket's mid-width plane\n    base leg   : x in [0, leg_base_length], z in [0, t_b]                (bottom face z=0 mounts down)\n    upright leg: x in [0, t_u],             z in [0, leg_upright_height] (outer face x=0 mounts the payload)\n    width      : y in [-bracket_width/2, +bracket_width/2]\nBend: inner fillet bend_inner_radius at (x=t_u, z=t_b); outer fillet = inner + max(t_b, t_u), so the wall at the\nbend is never thinner than min(t_b, t_u) (v1, t_u = t_b: constant section).\nHoles: rows x cols grid per leg, columns symmetric about y=0.\n",
    "length_params_mm": {
      "leg_base_length": "Base leg length along local X (mm)",
      "leg_upright_height": "Upright leg height along local Z (mm)",
      "bracket_width": "Bracket width along local Y (mm)",
      "bracket_thickness": "Base leg plate thickness along local Z (mm); also the upright thickness unless upright_thickness is given",
      "upright_thickness": "Upright leg plate thickness along local X (mm); OPTIONAL - omit it to use bracket_thickness",
      "bend_inner_radius": "Internal bend fillet radius (mm); outer = inner + thickness",
      "base_hole_diameter": "Base leg clearance hole diameter (mm)",
      "base_hole_x0": "Distance from upright outer face (x=0) to first base hole row (mm)",
      "base_hole_pitch_x": "Row pitch of base holes along X (mm); ignored if 1 row",
      "base_hole_pitch_y": "Column pitch of base holes along Y (mm); ignored if 1 column",
      "upright_hole_diameter": "Upright leg clearance hole diameter (mm)",
      "upright_hole_z0": "Height from base bottom face (z=0) to first upright hole row (mm)",
      "upright_hole_pitch_z": "Row pitch of upright holes along Z (mm); ignored if 1 row",
      "upright_hole_pitch_y": "Column pitch of upright holes along Y (mm); ignored if 1 column"
    },
    "optional_params": [
      "upright_thickness"
    ],
    "count_params": {
      "base_hole_rows": "Rows of base holes along X (1 or 2)",
      "base_hole_cols": "Columns of base holes along Y (1 or 2)",
      "upright_hole_rows": "Rows of upright holes along Z (1 or 2)",
      "upright_hole_cols": "Columns of upright holes along Y (1 or 2)"
    },
    "processes": [
      "machined"
    ],
    "design_inputs": [
      "base_fastener",
      "upright_fastener",
      "base_mates_with",
      "upright_mates_with"
    ]
  },
  "rules": [
    {
      "id": "DFM-MACH-WALL-MIN",
      "title": "Minimum machinable wall thickness",
      "authority": "PROJECT_RULE",
      "requirement_text": "Duvar Kalınlığı: Minimum işlenebilir duvar kalınlığı 2.0 mm tutulmalıdır.",
      "process": "machined",
      "constraint": {
        "type": "min",
        "quantity": "wall_thickness",
        "value": 2.0,
        "unit": "mm"
      },
      "severity": "BLOCKING",
      "verification_status": "NOT_VERIFIED"
    },
    {
      "id": "DFM-MACH-INNER-RADIUS-MIN",
      "title": "Minimum internal corner radius (end-mill access)",
      "authority": "PROJECT_RULE",
      "requirement_text": "Radyuslar (Internal Fillets): İç keskin köşelerden kaçınılmalı; parmak freze uç çaplarına uygun minimum R >= 3.0 mm radüs verilmelidir.",
      "process": "machined",
      "constraint": {
        "type": "min",
        "quantity": "internal_corner_radius",
        "value": 3.0,
        "unit": "mm"
      },
      "severity": "BLOCKING",
      "verification_status": "NOT_VERIFIED"
    },
    {
      "id": "DFM-DFMEA-FATIGUE-FILLET",
      "title": "Fatigue - internal fillet radius relative to wall thickness",
      "authority": "PROJECT_RULE",
      "requirement_text": "Yorulma Çatlağı (Fatigue) / Keskin iç köşelerdeki stres yoğunlaşması: fillet_radius >= 0.2 * wall_thickness şartı koy.",
      "process": null,
      "constraint": {
        "type": "min",
        "quantity": "fillet_to_thickness_ratio",
        "value": 0.2
      },
      "severity": "ADVISORY",
      "verification_status": "NOT_VERIFIED"
    },
    {
      "id": "STD-ISO273-MEDIUM",
      "title": "Clearance hole diameter for metric bolts (ISO 273, medium series)",
      "authority": "STANDARD",
      "requirement_text": "Standart Delik Ölçüleri: Delik çapları standart matkap ucu ve kılavuz (Tap/Thread) ölçülerine göre belirlenmelidir. (CAD_Design_Rules.md §2.A) -> implemented with ISO 273 medium-series clearance holes.",
      "process": null,
      "constraint": {
        "type": "table_match",
        "quantity": "clearance_holes",
        "unit": "mm",
        "table": {
          "M3": 3.4,
          "M4": 4.5,
          "M5": 5.5,
          "M6": 6.6,
          "M8": 9.0,
          "M10": 11.0,
          "M12": 13.5
        },
        "tolerance": 0.01
      },
      "severity": "ADVISORY",
      "verification_status": "NOT_VERIFIED"
    },
    {
      "id": "GL-HOLE-EDGE-DISTANCE",
      "title": "Bolt hole centre to free edge distance",
      "authority": "GUIDELINE",
      "requirement_text": "Hole centre to nearest free edge >= 1.5 x hole diameter (project guideline, common bolted-joint practice).",
      "process": null,
      "constraint": {
        "type": "min",
        "quantity": "hole_edge_distance_ratio",
        "value": 1.5
      },
      "severity": "BLOCKING",
      "verification_status": "NOT_VERIFIED"
    }
  ],
  "materials": {
    "AL6061-T6": {
      "id": "AL6061-T6",
      "name": "Aluminium 6061-T6",
      "density_kg_m3": 2700.0,
      "yield_strength_mpa": 276.0,
      "processes": [
        "machined"
      ],
      "fusion_material": "Aluminum 6061",
      "source": "Typical handbook value (e.g. ASM Handbook), not verified",
      "verification_status": "NOT_VERIFIED"
    },
    "AL7075-T6": {
      "id": "AL7075-T6",
      "name": "Aluminium 7075-T6",
      "density_kg_m3": 2810.0,
      "yield_strength_mpa": 503.0,
      "processes": [
        "machined"
      ],
      "fusion_material": null,
      "source": "Typical handbook value (e.g. ASM Handbook), not verified",
      "verification_status": "NOT_VERIFIED"
    },
    "S235": {
      "id": "S235",
      "name": "Structural steel S235",
      "density_kg_m3": 7850.0,
      "yield_strength_mpa": 235.0,
      "processes": [
        "machined"
      ],
      "fusion_material": null,
      "source": "EN 10025-2 nominal minimum (t <= 16 mm), not verified",
      "verification_status": "NOT_VERIFIED"
    },
    "TI6AL4V": {
      "id": "TI6AL4V",
      "name": "Titanium Ti-6Al-4V (annealed)",
      "density_kg_m3": 4430.0,
      "yield_strength_mpa": 880.0,
      "processes": [
        "machined"
      ],
      "fusion_material": null,
      "source": "Typical handbook value, not verified",
      "verification_status": "NOT_VERIFIED"
    }
  },
  "feedback": null,
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
    "LoadCase": {
      "additionalProperties": false,
      "properties": {
        "description": {
          "title": "Description",
          "type": "string"
        },
        "force_n": {
          "minimum": 0,
          "title": "Force N",
          "type": "number"
        },
        "lever_arm_mm": {
          "minimum": 0,
          "title": "Lever Arm Mm",
          "type": "number"
        },
        "required_safety_factor": {
          "exclusiveMinimum": 0,
          "title": "Required Safety Factor",
          "type": "number"
        },
        "trace": {
          "items": {
            "type": "string"
          },
          "title": "Trace",
          "type": "array"
        }
      },
      "required": [
        "description",
        "force_n",
        "lever_arm_mm",
        "required_safety_factor",
        "trace"
      ],
      "title": "LoadCase",
      "type": "object"
    },
    "Manufacturing": {
      "additionalProperties": false,
      "properties": {
        "process": {
          "title": "Process",
          "type": "string"
        },
        "material": {
          "title": "Material",
          "type": "string"
        }
      },
      "required": [
        "process",
        "material"
      ],
      "title": "Manufacturing",
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
    },
    "PlannedPlacement": {
      "additionalProperties": false,
      "description": "Pose of the component's local frame in the project coordinate system (vehicle.models.Pose convention).",
      "properties": {
        "position_mm": {
          "description": "Origin of the local frame (x, y, z) in mm",
          "items": {
            "type": "number"
          },
          "maxItems": 3,
          "minItems": 3,
          "title": "Position Mm",
          "type": "array"
        },
        "rotation_deg": {
          "description": "(roll, pitch, yaw) in degrees about X, Y, Z; R = Rz(yaw)\u00b7Ry(pitch)\u00b7Rx(roll)",
          "items": {
            "type": "number"
          },
          "maxItems": 3,
          "minItems": 3,
          "title": "Rotation Deg",
          "type": "array"
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
        "position_mm",
        "rotation_deg",
        "source",
        "rationale"
      ],
      "title": "PlannedPlacement",
      "type": "object"
    }
  },
  "additionalProperties": false,
  "properties": {
    "generator": {
      "title": "Generator",
      "type": "string"
    },
    "component_name": {
      "title": "Component Name",
      "type": "string"
    },
    "steps": {
      "items": {
        "type": "string"
      },
      "title": "Steps",
      "type": "array"
    },
    "parameters": {
      "additionalProperties": {
        "$ref": "#/$defs/PlannedParam"
      },
      "title": "Parameters",
      "type": "object"
    },
    "design_inputs": {
      "additionalProperties": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "description": "Non-numeric generator inputs, e.g. base_fastener, upright_fastener, base_mates_with, upright_mates_with",
      "title": "Design Inputs",
      "type": "object"
    },
    "manufacturing": {
      "$ref": "#/$defs/Manufacturing"
    },
    "load_case": {
      "$ref": "#/$defs/LoadCase"
    },
    "new_assumptions": {
      "items": {
        "$ref": "#/$defs/Assumption"
      },
      "title": "New Assumptions",
      "type": "array"
    },
    "verification_plan": {
      "items": {
        "type": "string"
      },
      "title": "Verification Plan",
      "type": "array"
    },
    "placement": {
      "anyOf": [
        {
          "$ref": "#/$defs/PlannedPlacement"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "description": "Only if the user specified where the component is placed; omitted = identity pose"
    }
  },
  "required": [
    "generator",
    "component_name",
    "steps",
    "parameters",
    "design_inputs",
    "manufacturing",
    "load_case",
    "verification_plan"
  ],
  "title": "PlanResponse",
  "type": "object"
}
```
