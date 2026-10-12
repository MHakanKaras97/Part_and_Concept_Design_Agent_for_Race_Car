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
