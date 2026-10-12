"""Engineering report (Markdown) for one run: what was created, verified, assumed, and not verified."""
from __future__ import annotations

from collections import Counter

from fia_rules.rules import RuleSet

STATUS_ORDER = ["NON_COMPLIANT", "NOT_VERIFIED", "ASSUMPTION", "VERIFIED", "NOT_APPLICABLE"]
STATUS_LABEL = {
    "VERIFIED": "Verified (deterministic check passed; measured in Fusion or computed, rule human-verified or no rule needed)",
    "ASSUMPTION": "Passed under assumptions (assumed inputs or rule transcription not yet human-verified)",
    "NON_COMPLIANT": "Non-compliant (check ran and failed)",
    "NOT_VERIFIED": "Not verified (not checked / could not be checked)",
    "NOT_APPLICABLE": "Not applicable",
}


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, dict):
        return ", ".join(f"{k}={_fmt(x)}" for k, x in v.items())
    if isinstance(v, (list, tuple)):
        return "; ".join(_fmt(x) for x in v)
    return str(v).replace("|", "/").replace("\n", " ")


def _table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(_fmt(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render_report(run: dict, rules: RuleSet) -> str:
    L: list[str] = []
    reg = run.get("registered")
    a = run.get("analysis") or {}
    plan = run.get("plan") or {}
    val = run.get("validation") or []
    counts = Counter(v["status"] for v in val)

    L.append(f"# Engineering report — run `{run['run_id']}`\n")
    L.append(f"**Request:** {run['request']}\n")
    for att in run.get("attachments") or []:
        L.append(f"**Source image {att['id']}:** `{att['file']}` ('{att['original_name']}', {att['media_type']}, "
                 f"{att['bytes']} bytes, sha256 `{att['sha256']}`) — user-supplied evidence; values read from it are "
                 f"marked IMAGE, not user words.  \n![{att['id']}]({att['file']})\n")
    if reg:
        outcome = (f"Component **{reg['id']} rev {reg['revision']}** registered as `CHECKED` "
                   f"(all blocking checks passed; concept-level design, see limitations).")
    else:
        outcome = f"**No component registered.** {run.get('stop_reason', '')}"
    L.append(f"**Outcome:** {outcome}\n")
    if val:
        L.append("**Check summary:** " + ", ".join(f"{s}: {counts[s]}" for s in STATUS_ORDER if counts.get(s)) + "\n")
        labels = Counter(f"{v.get('scope', '?')}_{v['status']}" for v in val)
        L.append("**Evidence labels:** " + ", ".join(f"`{k}`" + (f" x{n}" if n > 1 else "")
                                                   for k, n in sorted(labels.items())) + "\n")

    # 1 requirements
    if a:
        L.append("## 1. Requirements\n")
        L.append(f"{a.get('summary', '')}\n")
        L.append("Each requirement is the **AI's interpretation**; the authoritative source is the user's own words "
                 "(request or verbatim answer) quoted next to it, or — for origin IMAGE — what the AI read in a "
                 "user-supplied image (extracted evidence, not the user's words).\n")

        def evidence(r):
            if r["source"] == "IMAGE":
                return f"image {r.get('attachment_id')}: \"{r.get('image_evidence')}\" (AI reading)"
            return f"\"{r['quote']}\"" if r.get("quote") else ""
        L.append(_table(["ID", "Key", "Origin", "Source evidence", "AI interpretation", "Value", "Unit"],
                        [[r["id"], r["key"],
                          r["source"] + (f" ({r['answer_id']})" if r.get("answer_id") else "")
                          + (f" ({r['attachment_id']})" if r.get("attachment_id") else "")
                          + (f" from {', '.join(r.get('derived_from') or [])}" if r["source"] == "DERIVED" else ""),
                          evidence(r), r["text"], r.get("value"), r.get("unit")]
                         for r in a["requirements"]]))
        answers = run.get("user_answers") or {}
        if answers:
            L.append("\n### Customer answers (verbatim, authoritative)\n")
            for mid, ans in answers.items():
                if isinstance(ans, dict):
                    L.append(f"- **{mid}** Q: \"{ans['question']}\"  \n  A (user, {ans['received']}, via "
                             f"{ans['entered_via']}): \"{ans['answer']}\"")
                else:
                    L.append(f"- **{mid}** A (legacy record): \"{ans}\"")
        L.append("\n## 2. Missing information and how it was resolved\n")
        rows = []
        for m in a["missing_information"]:
            ans = answers.get(m["id"])
            ans_text = (ans["answer"] if isinstance(ans, dict) else ans) if ans else "(pending)"
            how = (f"Asked: \"{m['question']}\" → user answer: \"{ans_text}\"" if m["resolution"] == "ASK"
                   else f"Assumed ({m['assumption_id']})")
            if m.get("follows_up"):
                how += f" (clarifies {m['follows_up']})"
            rows.append([m["id"], m["topic"], m["criticality"], how])
        L.append(_table(["ID", "Topic", "Criticality", "Resolution"], rows) if rows else "None.")

    # 3 assumptions
    if run.get("assumptions"):
        L.append("\n## 3. Engineering assumptions\n")
        L.append(_table(["ID", "Assumption", "Rationale", "Impact"],
                        [[x["id"], x["text"], x["rationale"], x.get("impact", "")] for x in run["assumptions"]]))

    # 4 plan
    if plan:
        L.append("\n## 4. Engineering plan\n")
        L += [f"{i}. {s}" for i, s in enumerate(plan["steps"], 1)]
        L.append(f"\n**Manufacturing:** {plan['manufacturing']['process']}, material `{plan['manufacturing']['material']}`  ")
        L.append(f"**Design inputs:** {_fmt(plan['design_inputs'])}  ")
        lc = plan["load_case"]
        L.append(f"**Load case:** {lc['description']} — F = {lc['force_n']:g} N, lever arm {lc['lever_arm_mm']:g} mm, "
                 f"required SF {lc['required_safety_factor']:g} (trace {', '.join(lc['trace'])})\n")
        L.append("### Parameters (traceability)\n")
        L.append(_table(["Parameter", "Value", "Unit", "Source", "Trace", "Rationale"],
                        [[k, v["value"], v["unit"], v["source"], ", ".join(v["trace"]), v["rationale"]]
                         for k, v in plan["parameters"].items()]))

    # 5 CAD
    cad = run.get("cad")
    geo = run.get("geometry")
    if cad:
        L.append("\n## 5. CAD (Autodesk Fusion via MCP)\n")
        if cad.get("ok"):
            r = cad.get("result") or {}
            L.append(f"- Fusion component: `{r.get('component_name')}` in document `{r.get('document')}` "
                     f"(Fusion {r.get('fusion_version')}), body `{r.get('body_name')}`, material `{r.get('material')}`")
            for w in r.get("warnings", []):
                L.append(f"- Warning: {w}")
        else:
            L.append(f"- Build FAILED: {cad.get('error')}")
        L.append(f"- Build script: `{cad.get('script')}` (re-runnable; regenerates the model from the record)")
    if geo and geo.get("found"):
        L.append("\n### Fusion measurements (read-only inspection)\n")
        built, inspected = geo.get("build_fusion_version"), geo.get("fusion_version")
        L.append(f"- Fusion build: inspected with {inspected or 'unknown'}, built with {built or 'unknown'}"
                 + (" - **WARNING: different Fusion builds; re-run the build**" if built and inspected and built != inspected
                    else ""))
        for b in geo["bodies"]:
            L.append(f"- Body `{b['name']}`: solid={b['is_solid']}, volume {b['volume_mm3']:.3f} mm³, "
                     f"area {b['area_mm2']:.1f} mm², bbox min {b['bbox_min']} max {b['bbox_max']} mm, material {b['material']}")
        L.append("- Features: " + ", ".join(f"{f['name']} ({f['health']})" for f in geo["features"]))
        L.append("- Sketches: " + ", ".join(f"{s['name']} (fully constrained: {s['fully_constrained']})" for s in geo["sketches"]))
        L.append(f"- User parameters in Fusion: {len(geo['parameters'])} (editable; all dimensions are driven by them)")
        L.append("\n![Fusion screenshot](screenshot.png)\n")

    # 6 validation
    if val:
        L.append("\n## 6. Validation results\n")
        for s in STATUS_ORDER:
            group = [v for v in val if v["status"] == s]
            if not group:
                continue
            L.append(f"\n### {STATUS_LABEL[s]}\n")
            L.append(_table(["Evidence label", "Check", "Claim (exactly what this result establishes)", "Severity",
                             "Method", "Measured", "Limit", "Note"],
                            [[f"{v.get('scope', '?')}_{v['status']}", v["check_id"], v.get("claim", ""), v["severity"],
                              v["method"], v.get("measured"), v.get("limit"), v.get("message")] for v in group]))
        used = sorted({v["rule_id"] for v in val if v.get("rule_id")})
        if used:
            L.append("\n### Rules used\n")
            rows = []
            for rid in used:
                r = rules.rules.get(rid)
                if r:
                    src = r.source
                    rows.append([rid, r.authority, f"{src.document} {src.article or ''}".strip(), r.verification_status])
            L.append(_table(["Rule", "Authority", "Source", "Transcription status"], rows))

    # 7 FIA
    L.append("\n## 7. Regulatory (FIA) status\n")
    fia = [v for v in val if v["category"] == "FIA"]
    if fia:
        for v in fia:
            L.append(f"- {v['status']}: {v['message']} ({_fmt(v.get('measured'))})")
    L.append("- No statement of FIA compliance is made by this report.")

    # 8 iterations
    if run.get("iterations"):
        L.append("\n## 8. Revisions within this run\n")
        for it in run["iterations"]:
            detail = it.get("changes") or it.get("findings")
            L.append(f"- Loop {it['loop']} ({it['reason']}): {_fmt(detail)}")

    # 9 limitations
    L.append("\n## 9. What remains unverified / limitations\n")
    L.append("- Concept-level design. Not structurally validated beyond the stated hand calculation "
             "(no FEA, no fatigue, no stress concentration, no bolt/joint analysis).")
    L.append("- Material properties are typical handbook values (NOT_VERIFIED against a supplier datasheet).")
    L.append("- Manufacturing checks are parameter-level rules only (no tool-path or fixture analysis).")
    L.append("- Rule transcriptions marked NOT_VERIFIED must be reviewed by a human "
             "(`python -m agent rules-verify <id> --by <name>`).")
    if run.get("assumptions"):
        L.append(f"- Results depend on assumptions {', '.join(x['id'] for x in run['assumptions'])}.")
    L.append("- Not FIA homologated, not race-ready, not production-ready, not human-verified.")

    if run.get("reviews"):
        L.append("\n## 10. Reviewer decisions\n")
        for rv in run["reviews"]:
            L.append(f"- **{rv['decision']}** — {rv['rationale']}")
    return "\n".join(L) + "\n"
