
import json
import csv
import os
import subprocess
import sqlite3
import pytest


@pytest.fixture(scope="session")
def pipeline_results():
    """Run the pipeline and load results."""
    result = subprocess.run(
        ["python3", "/app/pipeline.py"],
        capture_output=True, text=True, cwd="/app", timeout=120
    )
    assert result.returncode == 0, (
        f"Pipeline exited with code {result.returncode}.\n"
        f"stdout: {result.stdout[:2000]}\nstderr: {result.stderr[:2000]}"
    )
    output_path = "/app/output/results.json"
    assert os.path.exists(output_path), "Output file /app/output/results.json not found"
    with open(output_path) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="session")
def notes_text(pipeline_results):
    """Load note texts including CDA-derived reconstructions."""
    path = "/app/output/note_texts.json"
    assert os.path.exists(path), "note_texts.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def summary_csv(pipeline_results):
    """Load the summary CSV."""
    csv_path = "/app/output/summary.csv"
    assert os.path.exists(csv_path), "Summary CSV /app/output/summary.csv not found"
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = {row["note_id"]: row for row in reader}
    return rows


@pytest.fixture(scope="session")
def fhir_bundle(pipeline_results):
    """Load FHIR Bundle output."""
    path = "/app/output/fhir_conditions.json"
    assert os.path.exists(path), "FHIR output not found at /app/output/fhir_conditions.json"
    with open(path) as f:
        return json.load(f)


def _get_entities(results, note_id):
    for note in results:
        if note["note_id"] == note_id:
            return note["entities"]
    return []


def _find_entity(entities, text):
    text_lower = text.lower()
    for e in entities:
        if e["text"].lower() == text_lower:
            return e
    return None


# ---------- output structure ----------

class TestOutputStructure:
    def test_is_list_of_ten(self, pipeline_results):
        assert isinstance(pipeline_results, list)
        assert len(pipeline_results) == 10

    def test_required_keys(self, pipeline_results):
        required_entity_keys = {
            "text", "start", "end", "type",
            "assertion", "resolved_code", "resolved_term", "similarity",
        }
        for note in pipeline_results:
            assert "note_id" in note
            assert "entities" in note
            for ent in note["entities"]:
                assert required_entity_keys.issubset(ent.keys()), (
                    f"Missing keys in entity: {required_entity_keys - ent.keys()}"
                )

    def test_valid_assertion_values(self, pipeline_results):
        valid = {"affirmed", "negated", "hypothetical", "historical"}
        for note in pipeline_results:
            for ent in note["entities"]:
                assert ent["assertion"] in valid, (
                    f"Invalid assertion '{ent['assertion']}' for '{ent['text']}'"
                )

    def test_valid_entity_types(self, pipeline_results):
        valid = {"CONDITION", "SYMPTOM", "MEDICATION"}
        for note in pipeline_results:
            for ent in note["entities"]:
                assert ent["type"] in valid


# ---------- span validity ----------

class TestSpanValidity:
    def test_spans_recover_text(self, pipeline_results, notes_text):
        for note in pipeline_results:
            text = notes_text[note["note_id"]]
            for ent in note["entities"]:
                recovered = text[ent["start"]:ent["end"]]
                assert recovered.lower() == ent["text"].lower(), (
                    f"Note {note['note_id']}: span [{ent['start']}:{ent['end']}] "
                    f"gives '{recovered}', expected '{ent['text']}'"
                )


# ---------- note_texts.json ----------

class TestNoteTexts:
    def test_note_texts_exists(self, pipeline_results):
        assert os.path.exists("/app/output/note_texts.json")

    def test_note_texts_has_all_notes(self, notes_text):
        expected = {"N001", "N002", "N003", "N004", "N005", "N006", "N007",
                    "N008", "N009", "N010"}
        assert set(notes_text.keys()) == expected

    def test_json_notes_text_matches_source(self, notes_text):
        with open("/app/data/clinical_notes.json") as f:
            source = json.load(f)
        for note in source:
            assert notes_text[note["note_id"]] == note["text"]


# ---------- N001: basic mixed assertions ----------

class TestN001:
    def test_chest_pain_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N001"), "chest pain")
        assert e is not None, "chest pain not extracted in N001"
        assert e["assertion"] == "affirmed"
        assert e["resolved_code"] == "R07.9"

    def test_mi_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N001"), "myocardial infarction")
        assert e is not None, "myocardial infarction not extracted in N001"
        assert e["assertion"] == "negated"
        assert e["resolved_code"] == "I21.9"

    def test_hypertension_historical(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N001"), "hypertension")
        assert e is not None
        assert e["assertion"] == "historical"
        assert e["resolved_code"] == "I10"

    def test_t2dm_historical(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N001"), "type 2 diabetes mellitus")
        assert e is not None
        assert e["assertion"] == "historical"
        assert e["resolved_code"] == "E11.9"

    def test_metformin_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N001"), "metformin")
        assert e is not None
        assert e["assertion"] == "affirmed"
        assert e["resolved_code"] == "RN861004"

    def test_lisinopril_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N001"), "lisinopril")
        assert e is not None
        assert e["assertion"] == "affirmed"
        assert e["resolved_code"] == "RN29046"

    def test_entity_count(self, pipeline_results):
        ents = _get_entities(pipeline_results, "N001")
        assert len(ents) == 6, f"Expected 6 entities in N001, got {len(ents)}"


# ---------- N002: scope termination ----------

class TestN002:
    def test_fever_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N002"), "fever")
        assert e is not None
        assert e["assertion"] == "negated"

    def test_cough_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N002"), "cough")
        assert e is not None
        assert e["assertion"] == "negated"

    def test_dyspnea_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N002"), "dyspnea")
        assert e is not None
        assert e["assertion"] == "negated"

    def test_headache_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N002"), "headache")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_nausea_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N002"), "nausea")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_entity_count(self, pipeline_results):
        ents = _get_entities(pipeline_results, "N002")
        assert len(ents) == 5, f"Expected 5 entities in N002, got {len(ents)}"


# ---------- N003: post-negation and hypothetical ----------

class TestN003:
    def test_pneumonia_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N003"), "pneumonia")
        assert e is not None
        assert e["assertion"] == "negated"
        assert e["resolved_code"] == "J18.9"

    def test_pe_hypothetical(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N003"), "pulmonary embolism")
        assert e is not None
        assert e["assertion"] == "hypothetical"
        assert e["resolved_code"] == "I26.99"

    def test_aspirin_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N003"), "aspirin")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_warfarin_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N003"), "warfarin")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_entity_count(self, pipeline_results):
        ents = _get_entities(pipeline_results, "N003")
        assert len(ents) == 4, f"Expected 4 entities in N003, got {len(ents)}"


# ---------- N004: pseudo-negation ----------

class TestN004:
    def test_copd_affirmed_despite_no(self, pipeline_results):
        e = _find_entity(
            _get_entities(pipeline_results, "N004"),
            "chronic obstructive pulmonary disease",
        )
        assert e is not None, "COPD not extracted in N004"
        assert e["assertion"] == "affirmed", (
            "pseudo-negation phrase must NOT negate COPD"
        )
        assert e["resolved_code"] == "J44.1"

    def test_nausea_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N004"), "nausea")
        assert e is not None
        assert e["assertion"] == "negated"

    def test_vomiting_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N004"), "vomiting")
        assert e is not None
        assert e["assertion"] == "negated"

    def test_asthma_historical(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N004"), "asthma")
        assert e is not None
        assert e["assertion"] == "historical"

    def test_albuterol_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N004"), "albuterol")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_prednisone_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N004"), "prednisone")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_entity_count(self, pipeline_results):
        ents = _get_entities(pipeline_results, "N004")
        assert len(ents) == 6, f"Expected 6 entities in N004, got {len(ents)}"


# ---------- N005: mixed triggers + scope termination ----------

class TestN005:
    def test_chf_historical(self, pipeline_results):
        e = _find_entity(
            _get_entities(pipeline_results, "N005"), "congestive heart failure"
        )
        assert e is not None
        assert e["assertion"] == "historical"
        assert e["resolved_code"] == "I50.9"

    def test_dvt_hypothetical(self, pipeline_results):
        e = _find_entity(
            _get_entities(pipeline_results, "N005"), "deep vein thrombosis"
        )
        assert e is not None
        assert e["assertion"] == "hypothetical"
        assert e["resolved_code"] == "I82.90"

    def test_edema_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N005"), "edema")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_chest_pain_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N005"), "chest pain")
        assert e is not None
        assert e["assertion"] == "negated"

    def test_dyspnea_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N005"), "dyspnea")
        assert e is not None
        assert e["assertion"] == "negated"

    def test_diarrhea_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N005"), "diarrhea")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_atorvastatin_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N005"), "atorvastatin")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_amlodipine_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N005"), "amlodipine")
        assert e is not None
        assert e["assertion"] == "affirmed"


# ---------- N006: fuzzy matching ----------

class TestN006:
    def test_fuzzy_mi(self, pipeline_results):
        e = _find_entity(
            _get_entities(pipeline_results, "N006"), "myocardial infraction"
        )
        assert e is not None, (
            "Fuzzy match for 'myocardial infraction' -> 'myocardial infarction' not found"
        )
        assert e["assertion"] == "affirmed"
        assert e["resolved_code"] == "I21.9"
        assert e["resolved_term"] == "myocardial infarction"
        assert e["similarity"] < 1.0
        assert e["similarity"] >= 0.85

    def test_fuzzy_pneumonia(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N006"), "pneumona")
        assert e is not None, (
            "Fuzzy match for 'pneumona' -> 'pneumonia' not found"
        )
        assert e["assertion"] == "negated"
        assert e["resolved_code"] == "J18.9"
        assert e["resolved_term"] == "pneumonia"
        assert e["similarity"] < 1.0
        assert e["similarity"] >= 0.85

    def test_insulin_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N006"), "insulin")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_omeprazole_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N006"), "omeprazole")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_no_cardiogenic_shock(self, pipeline_results):
        e = _find_entity(
            _get_entities(pipeline_results, "N006"), "cardiogenic shock"
        )
        assert e is None, "cardiogenic shock must NOT be extracted (not in lexicon)"


# ---------- N007: multiple trigger types ----------

class TestN007:
    def test_fever_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N007"), "fever")
        assert e is not None
        assert e["assertion"] == "negated"

    def test_headache_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N007"), "headache")
        assert e is not None
        assert e["assertion"] == "negated"

    def test_nausea_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N007"), "nausea")
        assert e is not None
        assert e["assertion"] == "negated"

    def test_t2dm_historical(self, pipeline_results):
        e = _find_entity(
            _get_entities(pipeline_results, "N007"), "type 2 diabetes mellitus"
        )
        assert e is not None
        assert e["assertion"] == "historical"
        assert e["resolved_code"] == "E11.9"

    def test_pe_hypothetical(self, pipeline_results):
        e = _find_entity(
            _get_entities(pipeline_results, "N007"), "pulmonary embolism"
        )
        assert e is not None
        assert e["assertion"] == "hypothetical"
        assert e["resolved_code"] == "I26.99"

    def test_entity_count(self, pipeline_results):
        ents = _get_entities(pipeline_results, "N007")
        assert len(ents) == 5, f"Expected 5 entities in N007, got {len(ents)}"


# ---------- N008: CDA XML + section-aware PMH defaults ----------

class TestN008:
    def test_afib_affirmed(self, pipeline_results):
        """HPI section entity with no trigger -> affirmed."""
        e = _find_entity(_get_entities(pipeline_results, "N008"), "atrial fibrillation")
        assert e is not None, "atrial fibrillation not extracted in N008"
        assert e["assertion"] == "affirmed"
        assert e["resolved_code"] == "I48.91"

    def test_edema_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N008"), "edema")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_hypertension_historical(self, pipeline_results):
        """PMH section entity -> historical by section default."""
        e = _find_entity(_get_entities(pipeline_results, "N008"), "hypertension")
        assert e is not None
        assert e["assertion"] == "historical", (
            "PMH section must default entities to historical"
        )

    def test_t2dm_historical(self, pipeline_results):
        """PMH section entity -> historical by section default."""
        e = _find_entity(_get_entities(pipeline_results, "N008"), "type 2 diabetes mellitus")
        assert e is not None
        assert e["assertion"] == "historical"

    def test_chf_historical(self, pipeline_results):
        """PMH section entity -> historical by section default."""
        e = _find_entity(_get_entities(pipeline_results, "N008"), "congestive heart failure")
        assert e is not None
        assert e["assertion"] == "historical"
        assert e["resolved_code"] == "I50.9"

    def test_warfarin_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N008"), "warfarin")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_metformin_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N008"), "metformin")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_lisinopril_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N008"), "lisinopril")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_entity_count(self, pipeline_results):
        ents = _get_entities(pipeline_results, "N008")
        assert len(ents) == 8, f"Expected 8 entities in N008, got {len(ents)}"


# ---------- N009: Family History exclusion ----------

class TestN009:
    def test_chest_pain_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N009"), "chest pain")
        assert e is not None
        assert e["assertion"] == "affirmed"
        assert e["resolved_code"] == "R07.9"

    def test_dyspnea_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N009"), "dyspnea")
        assert e is not None
        assert e["assertion"] == "negated"

    def test_pe_hypothetical(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N009"), "pulmonary embolism")
        assert e is not None
        assert e["assertion"] == "hypothetical"
        assert e["resolved_code"] == "I26.99"

    def test_no_family_history_mi(self, pipeline_results):
        """Family History entities must be excluded (describe relatives)."""
        ents = _get_entities(pipeline_results, "N009")
        e = _find_entity(ents, "myocardial infarction")
        assert e is None, (
            "myocardial infarction from Family History section must be excluded"
        )

    def test_no_family_history_htn(self, pipeline_results):
        """Family History entities must be excluded."""
        ents = _get_entities(pipeline_results, "N009")
        e = _find_entity(ents, "hypertension")
        assert e is None, (
            "hypertension from Family History section must be excluded"
        )

    def test_pneumonia_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N009"), "pneumonia")
        assert e is not None
        assert e["assertion"] == "negated"
        assert e["resolved_code"] == "J18.9"

    def test_aspirin_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N009"), "aspirin")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_atorvastatin_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N009"), "atorvastatin")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_entity_count(self, pipeline_results):
        ents = _get_entities(pipeline_results, "N009")
        assert len(ents) == 6, f"Expected 6 entities in N009, got {len(ents)}"


# ---------- N010: trigger overrides section default ----------

class TestN010:
    def test_asthma_historical(self, pipeline_results):
        """PMH section, no explicit trigger -> historical default."""
        e = _find_entity(_get_entities(pipeline_results, "N010"), "asthma")
        assert e is not None
        assert e["assertion"] == "historical"
        assert e["resolved_code"] == "J45.909"

    def test_copd_negated_overrides_pmh(self, pipeline_results):
        """PMH section with 'no' trigger -> negated overrides historical."""
        e = _find_entity(
            _get_entities(pipeline_results, "N010"),
            "chronic obstructive pulmonary disease",
        )
        assert e is not None, "COPD not extracted in N010"
        assert e["assertion"] == "negated", (
            "Explicit 'no' trigger must override PMH section historical default"
        )
        assert e["resolved_code"] == "J44.1"

    def test_dvt_hypothetical_overrides_pmh(self, pipeline_results):
        """PMH section with 'possible' trigger -> hypothetical overrides historical."""
        e = _find_entity(_get_entities(pipeline_results, "N010"), "deep vein thrombosis")
        assert e is not None
        assert e["assertion"] == "hypothetical", (
            "Explicit 'possible' trigger must override PMH section historical default"
        )
        assert e["resolved_code"] == "I82.90"

    def test_cough_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N010"), "cough")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_fever_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N010"), "fever")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_nausea_negated(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N010"), "nausea")
        assert e is not None
        assert e["assertion"] == "negated"

    def test_pneumonia_hypothetical(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N010"), "pneumonia")
        assert e is not None
        assert e["assertion"] == "hypothetical"

    def test_albuterol_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N010"), "albuterol")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_prednisone_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N010"), "prednisone")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_omeprazole_affirmed(self, pipeline_results):
        e = _find_entity(_get_entities(pipeline_results, "N010"), "omeprazole")
        assert e is not None
        assert e["assertion"] == "affirmed"

    def test_entity_count(self, pipeline_results):
        ents = _get_entities(pipeline_results, "N010")
        assert len(ents) == 10, f"Expected 10 entities in N010, got {len(ents)}"


# ---------- similarity scores ----------

class TestSimilarity:
    def test_exact_matches_have_score_1(self, pipeline_results):
        for note in pipeline_results:
            for ent in note["entities"]:
                if ent["text"].lower() == ent["resolved_term"].lower():
                    assert ent["similarity"] == 1.0, (
                        f"Exact match '{ent['text']}' should have similarity 1.0"
                    )

    def test_fuzzy_matches_below_1(self, pipeline_results):
        for note in pipeline_results:
            for ent in note["entities"]:
                if ent["text"].lower() != ent["resolved_term"].lower():
                    assert 0.85 <= ent["similarity"] < 1.0, (
                        f"Fuzzy match '{ent['text']}' -> '{ent['resolved_term']}' "
                        f"has similarity {ent['similarity']}"
                    )


# ---------- summary CSV ----------

class TestSummaryCSV:
    def test_csv_exists(self):
        assert os.path.exists("/app/output/summary.csv"), (
            "Summary CSV not found at /app/output/summary.csv"
        )

    def test_csv_has_all_notes(self, summary_csv):
        expected_notes = {"N001", "N002", "N003", "N004", "N005", "N006", "N007",
                          "N008", "N009", "N010"}
        assert set(summary_csv.keys()) == expected_notes

    def test_csv_header_columns(self):
        with open("/app/output/summary.csv") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == ["note_id", "affirmed", "negated", "hypothetical", "historical"]

    def test_n001_counts(self, summary_csv):
        row = summary_csv["N001"]
        assert int(row["affirmed"]) == 3
        assert int(row["negated"]) == 1
        assert int(row["hypothetical"]) == 0
        assert int(row["historical"]) == 2

    def test_n002_counts(self, summary_csv):
        row = summary_csv["N002"]
        assert int(row["affirmed"]) == 2
        assert int(row["negated"]) == 3
        assert int(row["hypothetical"]) == 0
        assert int(row["historical"]) == 0

    def test_n003_counts(self, summary_csv):
        row = summary_csv["N003"]
        assert int(row["affirmed"]) == 2
        assert int(row["negated"]) == 1
        assert int(row["hypothetical"]) == 1
        assert int(row["historical"]) == 0

    def test_n004_counts(self, summary_csv):
        row = summary_csv["N004"]
        assert int(row["affirmed"]) == 3
        assert int(row["negated"]) == 2
        assert int(row["hypothetical"]) == 0
        assert int(row["historical"]) == 1

    def test_n006_counts(self, summary_csv):
        row = summary_csv["N006"]
        assert int(row["affirmed"]) == 3
        assert int(row["negated"]) == 1
        assert int(row["hypothetical"]) == 0
        assert int(row["historical"]) == 0

    def test_n007_counts(self, summary_csv):
        row = summary_csv["N007"]
        assert int(row["affirmed"]) == 0
        assert int(row["negated"]) == 3
        assert int(row["hypothetical"]) == 1
        assert int(row["historical"]) == 1

    def test_n008_counts(self, summary_csv):
        row = summary_csv["N008"]
        assert int(row["affirmed"]) == 5
        assert int(row["negated"]) == 0
        assert int(row["hypothetical"]) == 0
        assert int(row["historical"]) == 3

    def test_n009_counts(self, summary_csv):
        row = summary_csv["N009"]
        assert int(row["affirmed"]) == 3
        assert int(row["negated"]) == 2
        assert int(row["hypothetical"]) == 1
        assert int(row["historical"]) == 0

    def test_n010_counts(self, summary_csv):
        row = summary_csv["N010"]
        assert int(row["affirmed"]) == 5
        assert int(row["negated"]) == 2
        assert int(row["hypothetical"]) == 2
        assert int(row["historical"]) == 1

    def test_counts_consistent_with_json(self, pipeline_results, summary_csv):
        """Verify CSV counts match the JSON entity assertions."""
        for note in pipeline_results:
            nid = note["note_id"]
            counts = {"affirmed": 0, "negated": 0, "hypothetical": 0, "historical": 0}
            for ent in note["entities"]:
                counts[ent["assertion"]] += 1
            row = summary_csv[nid]
            for status in counts:
                assert int(row[status]) == counts[status], (
                    f"Note {nid}: CSV {status}={row[status]} != JSON count {counts[status]}"
                )


# ---------- FTS5 database ----------

class TestFTS5Database:
    def test_fts5_table_exists(self):
        conn = sqlite3.connect("/app/data/lexicon.db")
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='terms_fts'")
        result = c.fetchone()
        conn.close()
        assert result is not None, "FTS5 virtual table 'terms_fts' not found in lexicon.db"

    def test_fts5_match_query(self):
        conn = sqlite3.connect("/app/data/lexicon.db")
        c = conn.cursor()
        c.execute(
            "SELECT canonical FROM terms_fts WHERE terms_fts MATCH 'chest' LIMIT 5"
        )
        results = [row[0] for row in c]
        conn.close()
        assert any("chest" in r.lower() for r in results), (
            "FTS5 MATCH query for 'chest' should return chest-related terms"
        )


# ---------- FHIR output ----------

class TestFHIROutput:
    def test_bundle_structure(self, fhir_bundle):
        assert fhir_bundle["resourceType"] == "Bundle"
        assert fhir_bundle["type"] == "collection"
        assert "entry" in fhir_bundle

    def test_all_entries_are_conditions(self, fhir_bundle):
        for entry in fhir_bundle["entry"]:
            assert entry["resource"]["resourceType"] == "Condition"

    def test_no_medication_entries(self, fhir_bundle):
        """MEDICATION entities must not appear as FHIR Condition resources."""
        medication_codes = {"RN861004", "RN29046", "RN1191", "RN11289", "RN435",
                            "RN83367", "RN17767", "RN7646", "RN5856", "RN8640"}
        for entry in fhir_bundle["entry"]:
            code = entry["resource"]["code"]["coding"][0]["code"]
            assert code not in medication_codes, (
                f"Medication code {code} should not be in FHIR Conditions"
            )

    def test_clinical_status_values(self, fhir_bundle):
        valid = {"active", "resolved"}
        for entry in fhir_bundle["entry"]:
            status = entry["resource"]["clinicalStatus"]["coding"][0]["code"]
            assert status in valid, f"Invalid clinicalStatus: {status}"

    def test_verification_status_values(self, fhir_bundle):
        valid = {"confirmed", "refuted", "provisional"}
        for entry in fhir_bundle["entry"]:
            status = entry["resource"]["verificationStatus"]["coding"][0]["code"]
            assert status in valid, f"Invalid verificationStatus: {status}"

    def test_historical_maps_to_resolved(self, fhir_bundle):
        """Historical entities should have clinicalStatus=resolved."""
        for entry in fhir_bundle["entry"]:
            r = entry["resource"]
            ver = r["verificationStatus"]["coding"][0]["code"]
            clin = r["clinicalStatus"]["coding"][0]["code"]
            if clin == "resolved":
                assert ver == "confirmed", (
                    "Resolved (historical) conditions should have verification=confirmed"
                )

    def test_negated_maps_to_refuted(self, fhir_bundle):
        """Check at least one refuted entry exists."""
        refuted = [
            e for e in fhir_bundle["entry"]
            if e["resource"]["verificationStatus"]["coding"][0]["code"] == "refuted"
        ]
        assert len(refuted) > 0, "No refuted entries found in FHIR bundle"

    def test_icd10_system_uri(self, fhir_bundle):
        for entry in fhir_bundle["entry"]:
            system = entry["resource"]["code"]["coding"][0]["system"]
            assert system == "http://hl7.org/fhir/sid/icd-10-cm", (
                f"Expected ICD-10 system URI, got {system}"
            )

    def test_entry_count(self, fhir_bundle):
        """Total CONDITION+SYMPTOM entities across all 10 notes."""
        entries = fhir_bundle["entry"]
        assert len(entries) == 44, f"Expected 44 FHIR entries, got {len(entries)}"

    def test_subject_reference(self, fhir_bundle):
        for entry in fhir_bundle["entry"]:
            assert entry["resource"]["subject"]["reference"] == "Patient/unknown"
