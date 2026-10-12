# Reasoning task 02_analysis (run 20261005-205141-design-a-machined-alumin)

Write your answer as JSON to `02_analysis.response.json` in this folder, then run:

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


# Task: requirement analysis

The user is the customer. Their words (context.request and the verbatim answers in context.user_answers)
are the only authoritative source of requirements. Everything you write is an *interpretation*.

1. Choose `component_type` from context.generators (or "unsupported" if none fits).
2. Extract `requirements` (R01, R02, ...). Use the generator's `required_info` keys as `key` where the
   requirement covers that topic; other keys are allowed. For every requirement set `source`:
   - USER_REQUEST - interpreted from the request; `quote` = the exact words of the request it rests on.
   - USER_ANSWER  - interpreted from an answer; `answer_id` = the M-id; `quote` = the exact words of that answer.
   - DERIVED      - a consequence of other records; list them in `derived_from`.
   Python checks that every quote appears verbatim in the user's text and that every number in your
   interpretation (`text`, `value`) also appears in the quote. Never add numbers the user did not write.
3. For every `required_info` key NOT covered by a requirement, add a `missing_information` item (M01, ...)
   with the same `key`:
   - CRITICAL (the design or interfaces cannot be trusted without it) -> resolution ASK with a `question`.
   - IMPORTANT / MINOR -> resolution ASSUME is allowed; reference an assumption via `assumption_id`.
4. Questions must be neutral and open. Ask what the user knows; do NOT propose values, options or examples
   ("e.g.", "for example", "such as", "2 x M5?"). A question may repeat numbers the user already wrote, but
   must not introduce new ones. Python rejects leading questions.
   Good: "How is the sensor box attached to the upright leg, and where is its centre of mass relative to the
   mounting face?"   Bad: "Should the sensor box use 2 x M5 bolts 40 mm apart?"
5. If an answer in context.user_answers is ambiguous or incomplete for a CRITICAL item, do not fill the gap
   yourself: ask a new clarification question (new M-id, `follows_up` = the answered M-id). Every answered
   question must be either interpreted into requirements (`answer_id`) or followed up.
6. List `assumptions` (A01, ...) with rationale and impact, including scope assumptions (concept-level
   design, nominal geometry, no FEA) so they are visible in the report. Assumptions are for IMPORTANT/MINOR
   gaps only and must be labelled as assumptions - never presented as user requirements.

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
  "existing_components": [
    {
      "id": "BRK-001",
      "name": "Sensor box bracket",
      "type": "l_bracket",
      "revision": 1,
      "lifecycle": "CHECKED"
    }
  ],
  "user_answers": {},
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
  "feedback": {
    "rejected": "analysis",
    "errors": [
      "R01: numbers ['1'] are not in the quoted user words; state them as an assumption or ask"
    ]
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
        "follows_up": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Follows Up"
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
      "description": "An engineering requirement AS INTERPRETED BY THE AI from a user source.\n\nThe user's own words are authoritative; this record is the AI's interpretation of them:\n  source USER_REQUEST - interpreted from the original request; `quote` = verbatim excerpt of it\n  source USER_ANSWER  - interpreted from the user's answer `answer_id`; `quote` = verbatim excerpt\n  source DERIVED      - engineering consequence of other records listed in `derived_from`\n  source LEGACY_V1    - record written before MVP 1.1 (no verbatim quote); read-only, never accepted\n                        from new analyses",
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
          "enum": [
            "USER_REQUEST",
            "USER_ANSWER",
            "DERIVED",
            "LEGACY_V1"
          ],
          "title": "Source",
          "type": "string"
        },
        "quote": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Quote"
        },
        "answer_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Answer Id"
        },
        "derived_from": {
          "items": {
            "type": "string"
          },
          "title": "Derived From",
          "type": "array"
        },
        "interpreted_by": {
          "const": "AI",
          "default": "AI",
          "title": "Interpreted By",
          "type": "string"
        }
      },
      "required": [
        "id",
        "key",
        "text",
        "source"
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
