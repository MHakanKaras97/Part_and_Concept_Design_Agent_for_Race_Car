"""Fast mode P2: FIA retrieval, lean Claude calls, prompts and schemas, deterministic plan gate."""
import hashlib
import json

import pytest

from agent.fast_prompts import (MINI_F1_KIT, PLAN_SYSTEM, PartResponse, PlanResponse, gate_plan, part_system,
                                part_user, plan_user, repair_user, schema)
from agent.fast_reasoning import ClaudeFastReasoner, ScriptedReasoner
from agent.reasoning import ReasoningBackendError
from fia_rules.retrieval import (NOT_INSTALLED_NOTE, fia_status, is_verbatim, normalize, retrieve, source_installed,
                                 source_sha256)
from tests.helpers import mini_f1_plan

KIT_IDS = [k["id"] for k in MINI_F1_KIT]


# ---------------------------------------------------------------- FIA retrieval
# "synthetic": the invented stand-in (tests/conftest.py); "real": the installed FIA document, skipped when absent.
SOURCES = ["synthetic", pytest.param("real", marks=pytest.mark.fia_source)]


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("pid", KIT_IDS)
def test_snippets_are_few_short_verbatim_and_hashed(pid, source):
    snips = retrieve(pid)
    assert 2 <= len(snips) <= 6
    assert snips[0].article == "C2.3.1" and snips[0].source == "rules:FIA26-C2.3.1"
    assert len({s.article for s in snips}) == len(snips)
    for s in snips:
        # the structured rules quote the real document (checked in test_rules); the synthetic text cannot hold them
        from_rules = source == "synthetic" and s.source.startswith("rules:")
        assert len(s.text) <= 400 and (from_rules or is_verbatim(s.text)), (s.article, s.text[:80])
        assert s.sha256 == hashlib.sha256(s.text.encode("utf-8")).hexdigest()
        assert s.text.startswith(s.article) or s.source.startswith("rules:")


@pytest.mark.parametrize("source", SOURCES)
def test_retrieval_finds_the_part_articles(source):
    assert "C3.10.1" in {s.article for s in retrieve("FWG-001")}           # Front Wing Profiles
    assert "C3.11.1" in {s.article for s in retrieve("RWG-001")}           # Rear Wing Profiles
    assert {"C12.2.1", "C12.2.2"} <= {s.article for s in retrieve("MON-001")}
    assert any(s.article.startswith("C3.5") for s in retrieve("FLR-001"))  # Floor Bodywork
    assert all(not s.article.startswith("C18.") for p in KIT_IDS for s in retrieve(p))


@pytest.mark.parametrize("source", SOURCES)
def test_page_headers_never_leak_into_snippets(source):
    for p in KIT_IDS:
        for s in retrieve(p):
            assert "©2026" not in s.text and "SECTION C: TECHNICAL REGULATIONS" not in s.text


def test_invented_text_is_not_verbatim():
    assert not is_verbatim("The front wing span must be exactly 1234mm.")
    assert is_verbatim(normalize("the synthetic Survival Cell of the test car encloses a made-up Cockpit opening"))


@pytest.mark.fia_source
def test_regulation_text_is_verbatim_in_the_real_source():
    assert not is_verbatim("The front wing span must be exactly 1234mm.")
    assert is_verbatim(normalize("The X axis is the longitudinal direction of the car and increases rearwards."))


def test_fia_status_only_verified_for_measured_extent_rules():
    assert fia_status("C2.3.1", [[0, -900, 0], [10, 940, 5]])[0] == "VERIFIED"
    assert fia_status("C2.3.1", [[0, -951, 0], [10, 900, 5]])[0] == "NON_COMPLIANT"
    assert fia_status("C2.3.1", None)[0] == "NOT_VERIFIED"
    assert fia_status("C3.10.1", [[0, 0, 0], [1, 1, 1]])[0] == "NOT_VERIFIED"


# ---------------------------------------------------------------- FIA source not installed (fresh clone)
def test_without_the_fia_source_nothing_is_retrieved_or_verified(no_fia_source):
    assert not source_installed() and source_sha256() is None
    assert all(retrieve(p) == [] for p in KIT_IDS + ["SDP-L", "WHL-FL"])
    assert not is_verbatim("the synthetic Survival Cell of the test car")
    for args in (("C2.3.1", [[0, -900, 0], [10, 940, 5]]), ("C2.3.1", [[0, -951, 0], [10, 900, 5]]),
                 ("C3.10.1", [[0, 0, 0], [1, 1, 1]])):
        assert fia_status(*args) == ("NOT_VERIFIED", NOT_INSTALLED_NOTE)


def test_a_source_with_another_hash_is_not_installed(monkeypatch):
    import fia_rules.retrieval as r
    monkeypatch.setattr(r, "SOURCE_PDF_SHA256", "0" * 64)                  # e.g. another issue of the regulations
    assert not source_installed() and retrieve("FWG-001") == []
    assert fia_status("C2.3.1", [[0, -900, 0], [10, 940, 5]]) == ("NOT_VERIFIED", NOT_INSTALLED_NOTE)


def test_installed_pdf_without_text_gives_only_the_structured_quotes(monkeypatch, tmp_path):
    import fia_rules.retrieval as r
    monkeypatch.setattr(r, "SOURCE_TXT", tmp_path / "missing.txt")
    assert source_installed() and [s.article for s in retrieve("FWG-001")] == ["C2.3.1"]
    assert fia_status("C2.3.1", [[0, -900, 0], [10, 940, 5]])[0] == "VERIFIED"


def test_fetch_script_installs_only_a_matching_pdf(tmp_path):
    import importlib.util
    from tests.conftest import SYNTHETIC_STUB, SYNTHETIC_STUB_SHA256
    from fia_rules.rules import REPO_ROOT
    spec = importlib.util.spec_from_file_location("fetch_fia_source", REPO_ROOT / "scripts" / "fetch_fia_source.py")
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)                                        # no network at import
    fetch.SOURCE_DIR, fetch.REPO_ROOT = tmp_path / "source", tmp_path
    assert fetch.main(["--pdf", str(SYNTHETIC_STUB), "--no-extract"]) == 1  # recorded Issue 20 hash: refused
    assert not (tmp_path / "source" / fetch.PDF_NAME).exists()
    fetch.PDF_SHA256 = SYNTHETIC_STUB_SHA256
    assert fetch.main(["--pdf", str(SYNTHETIC_STUB), "--no-extract"]) == 0
    assert (tmp_path / "source" / fetch.PDF_NAME).read_bytes() == SYNTHETIC_STUB.read_bytes()


def fetch_constants() -> dict:
    import ast
    from fia_rules.rules import REPO_ROOT
    tree = ast.parse((REPO_ROOT / "scripts" / "fetch_fia_source.py").read_text(encoding="utf-8"))
    return {t.id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name) and t.id in ("PDF_SHA256", "PDF_NAME")}


def test_recorded_source_hash_matches_source_md_and_the_rules():
    from fia_rules.rules import REPO_ROOT, RuleSet
    from tests.conftest import REAL_SOURCE_PDF as SOURCE_PDF, REAL_SOURCE_SHA256 as SOURCE_PDF_SHA256
    md = (REPO_ROOT / "fia_rules" / "source" / "SOURCE.md").read_text(encoding="utf-8")
    assert SOURCE_PDF_SHA256 in md and SOURCE_PDF.name in md
    assert (SOURCE_PDF_SHA256, SOURCE_PDF.name) == (fetch_constants()["PDF_SHA256"], fetch_constants()["PDF_NAME"])
    fia = [r for r in RuleSet.load().rules.values() if r.authority == "REGULATION"]
    assert fia and all(r.source.sha256 == SOURCE_PDF_SHA256 and r.source.file.endswith(SOURCE_PDF.name) for r in fia)


# ---------------------------------------------------------------- Claude calls
def _ok_event(structured, usage=None):
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "structured_output": structured,
                       "usage": usage or {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 5000},
                       "modelUsage": {"claude-opus-5-5": {}}, "num_turns": 1})


def test_claude_call_is_lean_cached_and_audited(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    seen = []

    def runner(cmd, prompt, cwd, timeout):
        seen.append((cmd, prompt))
        return 0, _ok_event({"body": "def build(part):\n    pass\n"}), ""

    r = ClaudeFastReasoner(tmp_path, runner=runner)
    out = r.call("part_MON-001", part_system(), "INPUT", schema(PartResponse))
    assert out["body"].startswith("def build") and r.calls == 1
    cmd, prompt = seen[0]
    assert cmd[:2] == ["claude", "-p"] and "--system-prompt-file" in cmd and "--json-schema" in cmd
    assert cmd[cmd.index("--tools") + 1] == "" and "--model" not in cmd and "--no-session-persistence" in cmd
    assert prompt == "INPUT"                                   # only the per-call input, no history
    sys_file = cmd[cmd.index("--system-prompt-file") + 1]
    assert open(sys_file, encoding="utf-8").read() == part_system()
    meta = json.loads((tmp_path / "reasoning" / "01_part_MON-001.meta.json").read_text(encoding="utf-8"))
    assert meta["cache_read_input_tokens"] == 5000 and meta["models"] == ["claude-opus-5-5"]
    # resumed run: the stored response is reused, Claude is not called again
    r2 = ClaudeFastReasoner(tmp_path, runner=runner)
    assert r2.call("part_MON-001", part_system(), "INPUT", schema(PartResponse)) == out and r2.calls == 0
    assert len(seen) == 1
    # a repair call uses the very same system prompt file (prompt-cache prefix)
    r2.call("repair_MON-001_1", part_system(), "ERR", schema(PartResponse))
    assert seen[1][0][seen[1][0].index("--system-prompt-file") + 1] == sys_file


def test_agent_model_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "claude-sonnet-5-5")
    seen = []

    def runner(cmd, prompt, cwd, timeout):
        seen.append(cmd)
        return 0, _ok_event({"body": "x"}), ""

    ClaudeFastReasoner(tmp_path, runner=runner).call("plan", PLAN_SYSTEM, "{}", schema(PartResponse))
    assert seen[0][seen[0].index("--model") + 1] == "claude-sonnet-5-5"


def test_claude_failures_raise(tmp_path):
    r = ClaudeFastReasoner(tmp_path, runner=lambda c, p, w, t: (1, "", "not logged in"))
    with pytest.raises(ReasoningBackendError):
        r.call("plan", PLAN_SYSTEM, "{}", {})
    r = ClaudeFastReasoner(tmp_path, runner=lambda c, p, w, t: (0, json.dumps({"type": "result",
                                                                              "subtype": "error_max_turns"}), ""))
    with pytest.raises(ReasoningBackendError):
        r.call("plan2", PLAN_SYSTEM, "{}", {})


# ---------------------------------------------------------------- prompts + gate
def _snips():
    return {pid: [s.as_dict() for s in retrieve(pid)] for pid in KIT_IDS}


def test_plan_prompt_is_compact_and_contains_only_snippets():
    u = plan_user("Build a Mini F1.", MINI_F1_KIT, _snips(), [])
    assert len(u) < 16000 and "Build a Mini F1." in u
    d = json.loads(u)
    assert set(d["fia_snippets"]) == set(KIT_IDS) and all(len(v) <= 6 for v in d["fia_snippets"].values())


def test_part_and_repair_inputs_carry_spec_not_brief():
    specs, _, problems, _ = gate_plan(PlanResponse.model_validate(mini_f1_plan()), MINI_F1_KIT, set(), _snips())
    assert not problems
    mon = next(s for s in specs if s.id == "MON-001")
    u = json.loads(part_user(mon, _snips()["MON-001"]))
    assert "brief" not in u and u["part"]["local_envelope_min"] == [0.0, -400.0, 0.0]
    assert [f["article"] for f in u["part"]["fia"]] == ["C2.3.1"]       # only the refs the plan used
    r = json.loads(repair_user(mon, _snips()["MON-001"], {"stage": "body", "error": "x", "failing_lines": ["  3> y"]}, 1))
    assert r["failure"]["failing_lines"] == ["  3> y"] and "body" not in r["part"]


def test_gate_accepts_a_valid_plan_and_corrects_harmless_issues():
    plan = mini_f1_plan()
    plan["parts"][1]["fia_refs_used"] = ["C2.3.1", "C99.9"]
    plan["parts"][2]["reuse"] = True
    plan["mates"].append({"a": "MON-001", "b": "XYZ-001", "expect": "touching", "value_mm": 0})
    specs, mates, problems, notes = gate_plan(PlanResponse.model_validate(plan), MINI_F1_KIT, set(), _snips())
    assert not problems and len(specs) == 4 and len(mates) == 3
    assert next(s for s in specs if s.id == "FWG-001").fia_refs_used == ["C2.3.1"]
    assert not next(s for s in specs if s.id == "FLR-001").reuse
    assert len(notes) == 3


def test_gate_rejects_wrong_parts_and_bad_geometry():
    plan = mini_f1_plan()
    plan["parts"] = plan["parts"][:3]
    assert gate_plan(PlanResponse.model_validate(plan), MINI_F1_KIT, set(), _snips())[2]
    plan = mini_f1_plan()
    plan["parts"][0]["envelope_max"][0] = -5000
    plan["parts"][1]["dims"] = {"Span": 10}
    problems = gate_plan(PlanResponse.model_validate(plan), MINI_F1_KIT, set(), _snips())[2]
    assert any("envelope" in p for p in problems) and any("dims" in p for p in problems)


def test_plan_schema_limits_assumptions():
    with pytest.raises(Exception):
        PlanResponse.model_validate(mini_f1_plan(assumptions=[f"a{i}" for i in range(9)]))


def test_scripted_reasoner_records_calls():
    r = ScriptedReasoner({"plan": [mini_f1_plan()]})
    assert r.call("plan", PLAN_SYSTEM, "{}", {})["parts"] and r.calls == 1
    with pytest.raises(ReasoningBackendError):
        r.call("plan", PLAN_SYSTEM, "{}", {})


# ---------------------------------------------------------------- planned mate consistency (before building)
def _gate(plan):
    return gate_plan(PlanResponse.model_validate(plan), MINI_F1_KIT, set(), _snips())


def test_planned_envelopes_that_touch_pass():
    specs, mates, problems, notes = _gate(mini_f1_plan())
    assert not problems and not any("interpenetrate" in n for n in notes)


def test_touching_mate_with_separated_envelopes_is_rejected():
    plan = mini_f1_plan()
    plan["parts"][0]["envelope_min"][2] = 60                     # tub bottom planned at Z=60, floor top Z=30
    problems = _gate(plan)[2]
    assert problems == ["mate MON-001/FLR-001 (touching): planned envelopes are 30.0 mm apart along Z "
                        "(allowed 0.5 mm); move a part or its envelope so they meet"]


def test_gap_mate_allows_its_value_and_rejects_more():
    plan = mini_f1_plan()
    # RWG-001 envelope 50 mm rearwards of the floor: gap 50 = the planned value
    plan["parts"][3]["envelope_min"][0], plan["parts"][3]["envelope_max"][0] = -3950, -3450
    assert not _gate(plan)[2]
    plan["parts"][3]["envelope_min"][0], plan["parts"][3]["envelope_max"][0] = -4000, -3500
    assert "100.0 mm apart along X (allowed 50.5 mm)" in _gate(plan)[2][0]


def test_tolerance_and_interpenetrating_envelopes_are_noted_not_rejected():
    plan = mini_f1_plan()
    plan["parts"][2]["envelope_max"][2] = 29.6                   # 0.4 mm short: within the 0.5 mm tolerance
    assert not _gate(plan)[2]
    plan = mini_f1_plan()
    plan["parts"][2]["envelope_max"][2] = 230                    # diffuser box reaches up into the tub box
    specs, mates, problems, notes = _gate(plan)
    assert not problems and any("MON-001/FLR-001" in n and "Fusion mate measurement decides" in n for n in notes)


def test_first_real_mini_f1_plan_passes_the_consistency_check():
    from pathlib import Path
    run = Path(__file__).resolve().parents[1] / "data/mini_f1/design_runs/20261010-145347-create-a-coherent-parametric-min"
    plan = json.loads((run / "reasoning/01_plan.response.json").read_text(encoding="utf-8"))
    snippets = json.loads((run / "run.json").read_text(encoding="utf-8"))["snippets"]
    specs, mates, problems, notes = gate_plan(PlanResponse.model_validate(plan), MINI_F1_KIT, set(), snippets)
    assert not problems and len(mates) == 3
    assert [n for n in notes if "interpenetrate" in n] and all("FLR-001" in n for n in notes if "interpenetrate" in n)
