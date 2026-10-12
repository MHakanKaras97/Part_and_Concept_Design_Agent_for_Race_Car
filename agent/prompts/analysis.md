# Task: requirement analysis

The user is the customer. Their words (context.request and the verbatim answers in context.user_answers)
are the only authoritative source of requirements. Everything you write is an *interpretation*.

1. Choose `component_type` from context.generators (or "unsupported" if none fits).
2. Extract `requirements` (R01, R02, ...). Use the generator's `required_info` keys as `key` where the
   requirement covers that topic; other keys are allowed. For every requirement set `source`:
   - USER_REQUEST - interpreted from the request; `quote` = the exact words of the request it rests on.
   - USER_ANSWER  - interpreted from an answer; `answer_id` = the M-id; `quote` = the exact words of that answer.
   - IMAGE        - read by you from a user-supplied image (context.attachments, images attached to the task);
                    `attachment_id` = IMG-nn; `image_evidence` = exactly what you read in the image (e.g. the
                    dimension text "40", the label "2x M5", a feature you see). This is extracted evidence: it is not
                    the user's words and never a user answer. If an image value is unclear, conflicts with the user's
                    text, or is critical and uncertain, ask the user to confirm it; a question may repeat an image
                    value only if it names the image (e.g. "IMG-01 shows a hole spacing of 40 mm - is that correct?").
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
