# Live-test fixtures

`claude_part_TST-010.body.txt` — the exact `build(part)` body Claude (claude-opus-5-5, `claude -p`, fast-mode part
system prompt = `docs/fusion_script_contract.md`) wrote on 2026-10-10 for the test floor part TST-010 (spec in
`tests/integration/test_fast_live.py::test_claude_written_body_builds`). Stored verbatim so the live suite builds a
real Claude-written script without a paid call. 12 s, 681 output tokens, 3724 cache-creation input tokens.
