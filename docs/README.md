# Documentation index

Start with the top-level [README](../README.md), then [LEARNING_GUIDE.md](LEARNING_GUIDE.md) if you want to read or
change the code.

## Design and status

| Document | What it covers |
|---|---|
| [architecture.md](architecture.md) | How the pipeline is built: layers, gates, Fusion facts that shaped the design, fast mode (§14), status of every part |
| [development_plan.md](development_plan.md) | Milestones, what is done and what is open, risks |
| [coordinate_system.md](coordinate_system.md) | Vehicle coordinate system (+X front, +Y left, +Z up) and its relation to the FIA Car Coordinate System |
| [fusion_script_contract.md](fusion_script_contract.md) | The contract an AI-written part script must follow (also the system prompt for part calls) |
| [fast_mode_plan.md](fast_mode_plan.md) | The Phase 0 plan and audit before fast mode was built |

## Development log (AI-assisted)

The project was built with Claude (Claude Code, Claude Opus). These logs record what was tried, measured and decided,
including mistakes and corrections. They are historical: their wording and labels are those of the day.

| Document | What it covers |
|---|---|
| [dev-log/original_brief.md](dev-log/original_brief.md) | The original project brief |
| [dev-log/fast_mode_progress.md](dev-log/fast_mode_progress.md) | Fast mode phase by phase, the first real Mini F1 run, 18 parts, derived left/right parts, overlap depth, palette, rendering |
| [dev-log/revise_progress.md](dev-log/revise_progress.md) | Part revision and revert, the frame contract, the advisory mate-face check, a live test |

## Sources

| Document | What it covers |
|---|---|
| [../fia_rules/source/README.md](../fia_rules/source/README.md) | How to install the FIA regulation (not included) and what changes when it is present |
| [../fia_rules/source/SOURCE.md](../fia_rules/source/SOURCE.md) | Which FIA document the rule records cite (issue, date, URL, SHA-256) |
| [../manufacturing/source/DFM_rules_summary.md](../manufacturing/source/DFM_rules_summary.md) | Design-for-manufacturing rules used by the strict path, summarised in our own words |
