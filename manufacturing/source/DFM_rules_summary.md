# DFM rules summary (machined metal parts)

**Generic design guidance, not a standard, not verified.** This page is the source that
`manufacturing/rules/machined.yaml` cites for its project rules. It lists only the rules the DFM checks
(`manufacturing/dfm.py`) evaluate. The values are common rules of thumb for small CNC-machined aluminium or steel
parts. They have not been checked against a standard or a supplier's capabilities, so every rule stays
`NOT_VERIFIED` until a person reviews it (`python -m agent rules-verify <rule_id> --by "<name>"`).

## 1. Machined metal

| Rule id | Guidance | Value |
|---|---|---|
| `DFM-MACH-WALL-MIN` | Thin walls deflect and chatter under the cutter. Keep every machined wall at least this thick. | wall thickness ≥ 2.0 mm |
| `DFM-MACH-INNER-RADIUS-MIN` | A rotating end mill cannot cut a sharp inside corner. Give internal corners a radius the tool can reach. | internal corner radius ≥ 3.0 mm |

## 2. Holes

| Rule id | Guidance | Value |
|---|---|---|
| `STD-ISO273-MEDIUM` | Size bolt holes to standard drill and clearance sizes rather than arbitrary diameters. This project uses the ISO 273 medium-series clearance table. The table values come from general engineering knowledge, not from the standard itself. | M3 3.4 · M4 4.5 · M5 5.5 · M6 6.6 · M8 9.0 · M10 11.0 · M12 13.5 mm |
| `GL-HOLE-EDGE-DISTANCE` | A bolt hole too close to a free edge can tear out. Keep the hole centre a margin away from the edge. Project guideline, not from a standard. | edge distance ≥ 1.5 × hole diameter |

## 3. Failure modes (DFMEA-style check)

| Rule id | Guidance | Value |
|---|---|---|
| `DFM-DFMEA-FATIGUE-FILLET` | Sharp internal corners concentrate stress and are where fatigue cracks usually start. Size the internal fillet relative to the wall it joins. Advisory only. | fillet radius ≥ 0.2 × wall thickness |

## Scope

These checks run on parameters, before CAD. They do not replace a stress analysis, a tolerance study or a review
by a manufacturing engineer.
