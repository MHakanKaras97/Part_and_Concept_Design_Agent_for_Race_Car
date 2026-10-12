# Reasoning task 02_analysis (run 20261005-203018-design-a-machined-alumin)

Write your answer as JSON to `02_analysis.response.json` in this folder, then run:

    python -m agent step 20261005-203018-design-a-machined-alumin

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
- Be concise and specific; write for an engineer reviewing your reasoning later.


# Task: requirement analysis

From the user's request (and any answers the user has already given, see context.user_answers):

1. Choose `component_type` from context.generators (or "unsupported" if none fits).
2. Extract `requirements` (R01, R02, ...). Use the generator's `required_info` keys as `key` where
   the requirement covers that topic; other keys are allowed. `source`: USER for stated facts,
   USER_ANSWER for facts from user answers, DERIVED for direct consequences (explain in text).
3. For every `required_info` key NOT covered by a requirement, add a `missing_information` item
   (M01, ...) with the same `key`:
   - criticality CRITICAL  -> the design or interfaces cannot be trusted without it -> resolution ASK
     (the project policy forbids assuming CRITICAL items) and give a precise `question`.
   - IMPORTANT / MINOR     -> resolution ASSUME is allowed; reference an assumption via `assumption_id`.
   Also flag any other gap you consider important.
4. List `assumptions` (A01, ...) with rationale and impact. Include scope assumptions (e.g.
   concept-level design, nominal geometry, no FEA) so they are visible in the report.

Prefer asking over assuming when an answer would materially change the geometry or interfaces.


---

## Context

```json
{
  "request": "Design a machined aluminium L-bracket to mount a 2 kg sensor box to a flat plate with four M6 bolts.",
  "project": {
    "schema_version": 1,
    "id": "prototype_bench",
    "name": "Prototype bench",
    "kind": "bench",
    "description": "Stand-alone components used to develop and prove the agent workflow (Prototype 1+).",
    "coordinate_system": "VCS: +X front, +Y left, +Z up, mm (see docs/architecture.md)",
    "regulation": null,
    "policy": {
      "critical_missing_info_must_be_asked": true,
      "max_revision_loops": 3
    },
    "created": "2026-10-05T17:30:18+00:00"
  },
  "existing_components": [],
  "user_answers": {
    "M01": "Two M5 bolts side by side, 40 mm apart horizontally (one row). Sensor box centre of mass is 40 mm from its mounting face."
  },
  "generators": {
    "l_bracket": {
      "description": "Generator: machined L-bracket (Prototype 1).",
      "processes": [
        "machined"
      ],
      "required_info": {
        "function": "What the bracket connects/supports and how it is oriented",
        "material": "Bracket material",
        "manufacturing_process": "How the bracket is made (this generator supports: machined)",
        "base_fastener": "Fastener size and count through the base leg",
        "upright_fastener": "Fastener size and count through the upright leg",
        "load": "Load case: supported mass or force, direction, dynamic/safety factor",
        "envelope": "Available space / size limits for the bracket"
      }
    }
  },
  "feedback": null
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
    "MissingInfo": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "pattern": "^M\\d{2,3}$",
          "title": "Id",
          "type": "string"
        },
        "key": {
          "title": "Key",
          "type": "string"
        },
        "topic": {
          "title": "Topic",
          "type": "string"
        },
        "why_it_matters": {
          "title": "Why It Matters",
          "type": "string"
        },
        "criticality": {
          "enum": [
            "CRITICAL",
            "IMPORTANT",
            "MINOR"
          ],
          "title": "Criticality",
          "type": "string"
        },
        "resolution": {
          "enum": [
            "ASK",
            "ASSUME"
          ],
          "title": "Resolution",
          "type": "string"
        },
        "question": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Question"
        },
        "assumption_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Assumption Id"
        },
        "answer": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Answer"
        }
      },
      "required": [
        "id",
        "key",
        "topic",
        "why_it_matters",
        "criticality",
        "resolution"
      ],
      "title": "MissingInfo",
      "type": "object"
    },
    "Requirement": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "pattern": "^R\\d{2,3}$",
          "title": "Id",
          "type": "string"
        },
        "key": {
          "title": "Key",
          "type": "string"
        },
        "text": {
          "title": "Text",
          "type": "string"
        },
        "value": {
          "default": null,
          "title": "Value"
        },
        "unit": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Unit"
        },
        "source": {
          "default": "USER",
          "enum": [
            "USER",
            "DERIVED",
            "USER_ANSWER"
          ],
          "title": "Source",
          "type": "string"
        }
      },
      "required": [
        "id",
        "key",
        "text"
      ],
      "title": "Requirement",
      "type": "object"
    }
  },
  "additionalProperties": false,
  "properties": {
    "component_type": {
      "description": "Generator id that fits the request, e.g. 'l_bracket', or 'unsupported'",
      "title": "Component Type",
      "type": "string"
    },
    "summary": {
      "title": "Summary",
      "type": "string"
    },
    "requirements": {
      "items": {
        "$ref": "#/$defs/Requirement"
      },
      "title": "Requirements",
      "type": "array"
    },
    "missing_information": {
      "items": {
        "$ref": "#/$defs/MissingInfo"
      },
      "title": "Missing Information",
      "type": "array"
    },
    "assumptions": {
      "items": {
        "$ref": "#/$defs/Assumption"
      },
      "title": "Assumptions",
      "type": "array"
    }
  },
  "required": [
    "component_type",
    "summary",
    "requirements",
    "missing_information",
    "assumptions"
  ],
  "title": "AnalysisResponse",
  "type": "object"
}
```
