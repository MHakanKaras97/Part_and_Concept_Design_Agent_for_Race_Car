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
