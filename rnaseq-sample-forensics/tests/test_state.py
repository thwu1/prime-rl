
import json
import os
import pytest

EXPECTED_MISLABELED = sorted(["Sample_04", "Sample_09", "Sample_17", "Sample_21"])
EXPECTED_OUTLIER_GENES = sorted(["BGENE_0042", "BGENE_0200"])
PERTURBATION_KEYWORDS = ["heat"]
ALL_PIPELINES = ["pipeline_a", "pipeline_b", "pipeline_c", "pipeline_d"]


def _load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def _get_flaw(data, pipeline):
    evals = data["pipeline_evaluations"]
    assert pipeline in evals, f"Missing evaluation for {pipeline}"
    pe = evals[pipeline]
    assert "flaw_description" in pe, \
        f"Missing 'flaw_description' field for {pipeline}. Found keys: {list(pe.keys())}"
    return pe["flaw_description"].lower()


def test_results_file_exists():
    """Check that results.json was created."""
    assert os.path.exists("/app/results.json"), \
        "results.json not found at /app/results.json"


def test_results_is_valid_json():
    """Check results.json structure has all required fields."""
    data = _load_results()
    assert isinstance(data, dict)
    assert "pipeline_evaluations" in data
    assert "mislabeled_samples" in data
    assert "perturbation" in data
    assert "technical_outlier_genes" in data
    assert "confound_summary" in data


def test_pipeline_evaluations_structure():
    """Verify all four pipelines are evaluated with required fields."""
    data = _load_results()
    evals = data["pipeline_evaluations"]
    for p in ALL_PIPELINES:
        assert p in evals, f"Missing evaluation for {p}"
        assert "correct" in evals[p], f"Missing 'correct' field for {p}"
        assert "flaw_description" in evals[p], \
            f"Missing 'flaw_description' field for {p}"


def test_all_pipelines_marked_incorrect():
    """All four pipelines should be identified as methodologically unsound."""
    data = _load_results()
    for p in ALL_PIPELINES:
        assert data["pipeline_evaluations"][p]["correct"] is False, \
            f"{p} should be marked as incorrect (correct: false)"


def test_pipeline_a_flaw_identification():
    """Pipeline A's flaw: batch correction destroys signal due to confounding."""
    data = _load_results()
    flaw = _get_flaw(data, "pipeline_a")
    assert "batch" in flaw, \
        f"Pipeline A flaw description should reference batch effects. Got: '{flaw}'"
    condition_kws = ["confound", "condition", "treatment", "biological",
                     "signal", "remov", "destro", "eliminat", "indistinguish"]
    assert any(kw in flaw for kw in condition_kws), \
        f"Pipeline A flaw should describe how batch correction interacts with " \
        f"the experimental design. Got: '{flaw}'"


def test_pipeline_b_flaw_identification():
    """Pipeline B's flaw: PCA on raw counts without transformation."""
    data = _load_results()
    flaw = _get_flaw(data, "pipeline_b")
    transform_kws = ["log", "transform", "raw count", "scale", "normali",
                     "linear", "untransform", "variance", "magnitude"]
    assert any(kw in flaw for kw in transform_kws), \
        f"Pipeline B flaw description should reference missing data " \
        f"transformation or scaling. Got: '{flaw}'"


def test_pipeline_c_flaw_identification():
    """Pipeline C's flaw: enrichment restricted to downregulated genes."""
    data = _load_results()
    flaw = _get_flaw(data, "pipeline_c")
    direction_kws = ["down", "direction", "one-sid", "unidirectional",
                     "only", "restrict", "bias", "subset", "half",
                     "negative", "suppress"]
    assert any(kw in flaw for kw in direction_kws), \
        f"Pipeline C flaw description should reference directional restriction " \
        f"in the enrichment analysis. Got: '{flaw}'"
    enrich_kws = ["enrich", "gene", "pathway", "de ", "differential",
                  "expression", "regulat"]
    assert any(kw in flaw for kw in enrich_kws), \
        f"Pipeline C flaw should reference the enrichment or gene selection " \
        f"aspect. Got: '{flaw}'"


def test_pipeline_d_flaw_identification():
    """Pipeline D's flaw: variance-based gene selection on raw counts."""
    data = _load_results()
    flaw = _get_flaw(data, "pipeline_d")
    selection_kws = ["select", "filter", "feature", "variable", "variance",
                     "gene", "top", "100", "subset", "chosen"]
    assert any(kw in flaw for kw in selection_kws), \
        f"Pipeline D flaw should reference gene selection or filtering. Got: '{flaw}'"
    bias_kws = ["raw", "count", "mean", "bias", "dominat", "housekeep",
                "outlier", "uninformative", "high-express", "magnitude",
                "mean-variance", "not log", "without log", "untransform",
                "abundance", "inflat"]
    assert any(kw in flaw for kw in bias_kws), \
        f"Pipeline D flaw should reference the bias from raw count " \
        f"variance or mean-variance relationship. Got: '{flaw}'"


def test_mislabeled_samples_correct():
    """Verify exactly the right set of mislabeled samples was identified."""
    data = _load_results()
    found = sorted(data["mislabeled_samples"])
    assert found == EXPECTED_MISLABELED, \
        f"Expected mislabeled samples {EXPECTED_MISLABELED}, got {found}"


def test_perturbation_identified():
    """Verify the biological perturbation was correctly identified."""
    data = _load_results()
    perturbation = data["perturbation"].lower().strip()
    assert any(kw in perturbation for kw in PERTURBATION_KEYWORDS), \
        f"Perturbation '{data['perturbation']}' does not match expected " \
        f"keywords {PERTURBATION_KEYWORDS}."


def test_mislabeled_samples_format():
    """Check that mislabeled_samples is a sorted list of Sample_XX strings."""
    data = _load_results()
    samples = data["mislabeled_samples"]
    assert isinstance(samples, list)
    for s in samples:
        assert isinstance(s, str)
        assert s.startswith("Sample_"), \
            f"Sample ID '{s}' does not match format 'Sample_XX'"
    assert samples == sorted(samples), "mislabeled_samples must be sorted"


def test_technical_outlier_genes():
    """Verify technical outlier genes with extreme count spikes are identified."""
    data = _load_results()
    assert "technical_outlier_genes" in data, \
        "Missing 'technical_outlier_genes' field in results"
    found = sorted(data["technical_outlier_genes"])
    assert found == EXPECTED_OUTLIER_GENES, \
        f"Expected technical outlier genes {EXPECTED_OUTLIER_GENES}, got {found}"


def test_confound_summary_present():
    """Verify confound summary explains batch-condition confounding."""
    data = _load_results()
    assert "confound_summary" in data, \
        "Missing 'confound_summary' field in results"
    summary = data["confound_summary"].lower()
    assert "batch" in summary, \
        f"Confound summary should reference batch. Got: '{summary}'"
    cond_kws = ["condition", "treatment", "control", "experimental"]
    assert any(kw in summary for kw in cond_kws), \
        f"Confound summary should reference condition/treatment/control. " \
        f"Got: '{summary}'"
    confound_kws = ["confound", "correlat", "align", "overlap", "identical",
                    "inseparable", "coincide", "collinear",
                    "indistinguish", "same", "correspond", "map",
                    "entangle", "cannot separate", "cannot distinguish"]
    assert any(kw in summary for kw in confound_kws), \
        f"Confound summary should explain the confounding relationship. " \
        f"Got: '{summary}'"
