from agent.provenance import describe_numbers, invented_numbers, numbers_in, question_problems, quote_found
from agent.workflow import Engine, create_run
from tests.helpers import ScriptedBackend, analysis_response
from vehicle.store import ProjectStore


def test_numbers_in_digits_tokens_and_words():
    assert numbers_in("four M6 bolts") == {4.0, 6.0}
    assert numbers_in("2×M5, 40 mm apart") == {2.0, 5.0, 40.0}
    assert numbers_in("aluminium 6061-T6") >= {6061.0, 6.0}
    assert numbers_in("no numbers here") == set()


def test_quote_found_is_whitespace_and_case_tolerant_but_verbatim():
    src = "Mount the box with  two M5 bolts,\n40 mm apart."
    assert quote_found("two m5 bolts, 40 mm apart", src)
    assert not quote_found("two M5 bolts 40 mm apart", src)      # comma dropped -> not verbatim


def test_invented_numbers():
    quote = "two M5 bolts 40 mm apart"
    assert invented_numbers("2 x M5 at 40 mm", quote) == set()
    assert invented_numbers("2 x M5 at 40 mm, CoM 35 mm", quote) == {35.0}


def test_question_problems():
    user = ["mount a 2 kg sensor box with four M6 bolts"]
    good = "How is the sensor box attached to the upright leg, and where is its centre of mass relative to the mounting face?"
    assert question_problems(good, user, allow_suggestions=False) == []
    bad = "Should the sensor use 2x M5 bolts 40 mm apart with CoM 40 mm?"
    probs = question_problems(bad, user, allow_suggestions=False)
    assert any("40" in p for p in probs) and any("5" in p for p in probs)
    assert question_problems("Is the 2 kg box mounted on the M6 side?", user, False) == []
    assert any("e.g" in p for p in question_problems("Which fasteners (e.g. bolts)?", user, False))
    assert question_problems(bad, user, allow_suggestions=True) == []


def test_project_identifiers_are_not_engineering_numbers():
    # found while verifying the claude -p backend: a sensible question about BRK-001 was rejected
    assert numbers_in("Is this a new bracket, or a revision of the existing BRK-001 'Sensor box bracket'?") == set()
    assert numbers_in("see R01, M06 and A03") == set()
    assert numbers_in("rules FIA26-C2.3.1 and DFM-MACH-WALL-MIN, material AL6061-T6") == set()
    # but real values next to identifiers are still caught
    assert numbers_in("BRK-001 uses M6 bolts 30 mm apart") == {6.0, 30.0}
    assert question_problems("Is this a revision of BRK-001?", ["four M6 bolts"], False) == []


# ---------------- Turkish user input (found on the first f1_parts run, 2026-10-06) ----------------
def test_english_interpretation_of_turkish_quote_passes():
    # the Part 001 analysis was rejected 4x: "two" (2) in the interpretation, "iki" not recognised in the quote
    assert invented_numbers("The bracket has two main connection regions.", "iki ana bağlantı bölgesi") == set()
    assert invented_numbers("four M6 bolts, three holes", "dört M6 cıvata, üç delik") == set()


def test_turkish_number_words_including_ascii_and_capital_spellings():
    assert numbers_in("iki üç dört beş altı yedi sekiz dokuz") == {2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0}
    assert numbers_in("dort delik, alti civata, uc parca, bes adet") == {3.0, 4.0, 5.0, 6.0}
    assert numbers_in("İKİ DELİK") == {2.0}            # Turkish dotted capital I
    assert invented_numbers("2 holes", "iki delik") == set()


def test_bir_and_on_are_still_not_numbers():
    # "bir" is mostly the indefinite article, "on" also an English word: neither may make 1 / 10 look user-given
    assert numbers_in("bir mounting bracket oluşturmak") == set()
    assert numbers_in("bolted on the plate") == set()
    assert invented_numbers("one bracket, 10 mm thick", "bir bracket on the plate") == {1.0, 10.0}


def test_identifiers_f1_part_numbers_and_record_ids_are_not_values():
    assert numbers_in("F1-inspired demonstrator; F1 Front Wing Mounting Bracket") == set()
    assert numbers_in("PART 001, see R01, R02, A01, M01 and BRK-001") == set()
    assert invented_numbers("F1-inspired demonstrator, no FIA homologation claim (R02)",
                            "Gerçek FIA homologasyon parçası olduğunu iddia etme.") == set()


def test_real_numeric_hallucinations_still_fail():
    assert invented_numbers("two holes 40 mm apart", "iki delik") == {40.0}
    assert invented_numbers("three main connection regions", "iki ana bağlantı bölgesi") == {3.0}
    assert invented_numbers("F1 bracket, 6 mm fillet", "F1 bracket") == {6.0}
    assert invented_numbers("Part 001 with 4 holes", "Part 001") == {4.0}


def test_gate_feedback_names_the_source_token():
    assert describe_numbers({2.0}, "two main connection regions") == ["2 (from 'two')"]
    assert describe_numbers({6.0, 35.0}, "M6 bolts, CoM 35 mm") == ["6 (from 'm6')", "35 (from '35')"]


def _gate(tmp_path, request, requirement):
    store = ProjectStore("bench", root=tmp_path)
    eng = Engine(store, backend_factory=lambda run: ScriptedBackend({}))
    a = analysis_response()
    a["requirements"].append(dict({"id": "R50", "key": "connections", "source": "USER_REQUEST"}, **requirement))
    from agent.reasoning import AnalysisResponse
    return eng.gate_analysis(AnalysisResponse.model_validate(a), create_run(store, request))


def test_gate_accepts_turkish_quote_and_reports_real_inventions(tmp_path):
    from tests.helpers import REQUEST
    tr = REQUEST + " Parça şu özellikleri göstermeli: iki ana bağlantı bölgesi"
    ok = _gate(tmp_path / "a", tr, {"text": "Two main connection regions (F1-inspired, R01).", "quote": "iki ana bağlantı bölgesi"})
    assert ok == []
    bad = _gate(tmp_path / "b", tr, {"text": "Two connection regions, 40 mm apart.", "quote": "iki ana bağlantı bölgesi"})
    assert any("R50: numbers [\"40 (from '40')\"]" in e for e in bad), bad
