"""Tests for metagenome profiling submission audit task.

"""

import csv
import json
import math
import os

import pytest


OPAL_DIR = "/app/audit/opal_output"
ISSUES_JSON = "/app/audit/issues.json"
CORRECTED_TSV = "/app/audit/corrected_metrics.tsv"
RANKING_TXT = "/app/audit/ranking.txt"


# =====================================================================
# OPAL output verification
# =====================================================================

def test_opal_output_dir_exists():
    assert os.path.isdir(OPAL_DIR), f"{OPAL_DIR} directory not found"


def test_opal_output_has_content():
    """OPAL output directory should contain at least one file."""
    assert os.path.isdir(OPAL_DIR), f"{OPAL_DIR} not found"
    files = os.listdir(OPAL_DIR)
    assert len(files) >= 1, "OPAL output directory is empty"


# =====================================================================
# issues.json verification
# =====================================================================

def _load_issues():
    with open(ISSUES_JSON) as f:
        return json.load(f)


def test_issues_file_exists():
    assert os.path.isfile(ISSUES_JSON), f"{ISSUES_JSON} not found"


def test_issues_is_valid_json_array():
    data = _load_issues()
    assert isinstance(data, list), "issues.json must be a JSON array"


def test_issues_minimum_count():
    """At least 4 distinct issues should be identified."""
    data = _load_issues()
    assert len(data) >= 4, f"Expected >= 4 issues, got {len(data)}"


def test_issues_required_keys():
    """Each issue must have tool, sample, issue_type, description."""
    data = _load_issues()
    for v in data:
        assert "tool" in v, f"Missing 'tool' key in issue: {v}"
        assert "sample" in v, f"Missing 'sample' key in issue: {v}"
        assert "issue_type" in v, f"Missing 'issue_type' key in issue: {v}"
        assert "description" in v, f"Missing 'description' key in issue: {v}"


def test_issues_alpha_clean():
    """profiler_alpha should not appear in issues (it's clean)."""
    data = _load_issues()
    alpha_issues = [v for v in data if v["tool"] == "profiler_alpha"]
    assert len(alpha_issues) == 0, \
        f"profiler_alpha should have no issues, but found {len(alpha_issues)}"


def test_issues_multiple_tools_flagged():
    """Issues should span at least 3 distinct tools."""
    data = _load_issues()
    tools = {v["tool"] for v in data}
    assert len(tools) >= 3, \
        f"Expected issues from >= 3 tools, got {len(tools)}: {tools}"


def test_issues_bravo_flagged():
    """profiler_bravo should be flagged (merged/deprecated taxids)."""
    data = _load_issues()
    bravo_issues = [v for v in data if v["tool"] == "profiler_bravo"]
    assert len(bravo_issues) >= 1, "profiler_bravo issues not found"
    # Check that the issue relates to taxids, merged, or deprecated
    combined = " ".join(
        v.get("issue_type", "") + " " + v.get("description", "")
        for v in bravo_issues
    ).lower()
    assert any(kw in combined for kw in [
        "merg", "deprecat", "74313", "29461", "taxid", "unknown", "invalid",
        "obsolet", "old", "remap",
    ]), f"Bravo issues should mention merged/deprecated taxids: {combined[:200]}"


def test_issues_charlie_flagged():
    """profiler_charlie should be flagged (abundance overflow)."""
    data = _load_issues()
    charlie_issues = [v for v in data if v["tool"] == "profiler_charlie"]
    assert len(charlie_issues) >= 1, "profiler_charlie issues not found"
    combined = " ".join(
        v.get("issue_type", "") + " " + v.get("description", "")
        for v in charlie_issues
    ).lower()
    assert any(kw in combined for kw in [
        "overflow", "sum", ">100", "exceed", "110", "normaliz", "100%",
        "abundance",
    ]), f"Charlie issues should mention abundance overflow: {combined[:200]}"


def test_issues_delta_flagged():
    """profiler_delta should be flagged (duplicate taxid)."""
    data = _load_issues()
    delta_issues = [v for v in data if v["tool"] == "profiler_delta"]
    assert len(delta_issues) >= 1, "profiler_delta issues not found"
    combined = " ".join(
        v.get("issue_type", "") + " " + v.get("description", "")
        for v in delta_issues
    ).lower()
    assert any(kw in combined for kw in [
        "duplicate", "dupl", "817", "repeated", "twice", "multiple",
    ]), f"Delta issues should mention duplicate taxid: {combined[:200]}"


def test_issues_echo_flagged():
    """profiler_echo should be flagged (malformed/missing header)."""
    data = _load_issues()
    echo_issues = [v for v in data if v["tool"] == "profiler_echo"]
    assert len(echo_issues) >= 1, "profiler_echo issues not found"
    combined = " ".join(
        v.get("issue_type", "") + " " + v.get("description", "")
        for v in echo_issues
    ).lower()
    assert any(kw in combined for kw in [
        "header", "sampleid", "malform", "missing", "sample_id", "parse",
        "format", "broken",
    ]), f"Echo issues should mention malformed header: {combined[:200]}"


# =====================================================================
# corrected_metrics.tsv verification
# =====================================================================

def _load_metrics():
    rows = []
    with open(CORRECTED_TSV) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)
    return rows


def test_metrics_file_exists():
    assert os.path.isfile(CORRECTED_TSV), f"{CORRECTED_TSV} not found"


def test_metrics_correct_columns():
    with open(CORRECTED_TSV) as f:
        reader = csv.DictReader(f, delimiter="\t")
        cols = set(reader.fieldnames)
    expected = {"tool", "sample", "rank", "l1_norm", "precision", "recall"}
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


def test_metrics_row_count():
    """5 tools x 2 samples x 7 ranks = 70 rows."""
    rows = _load_metrics()
    assert len(rows) == 70, f"Expected 70 rows, got {len(rows)}"


def test_metrics_all_tools_present():
    rows = _load_metrics()
    tools = {r["tool"] for r in rows}
    for t in ["profiler_alpha", "profiler_bravo", "profiler_charlie",
              "profiler_delta", "profiler_echo"]:
        assert t in tools, f"Tool {t} missing from corrected_metrics.tsv"


def test_metrics_all_samples_present():
    rows = _load_metrics()
    samples = {r["sample"] for r in rows}
    assert "S1" in samples, "Sample S1 missing"
    assert "S2" in samples, "Sample S2 missing"


def test_metrics_all_ranks_present():
    rows = _load_metrics()
    ranks = {r["rank"] for r in rows}
    expected = {"superkingdom", "phylum", "class", "order", "family",
                "genus", "species"}
    assert expected.issubset(ranks), f"Missing ranks: {expected - ranks}"


def _get_metric(tool, sample, rank):
    rows = _load_metrics()
    for r in rows:
        if r["tool"] == tool and r["sample"] == sample and r["rank"] == rank:
            return r
    pytest.fail(f"Row not found: {tool}/{sample}/{rank}")


# ---- L1 norm spot checks ----

def test_l1_alpha_s1_species():
    """Alpha S1 species: diffs = 1+1+0.5+2+2+0+0.5 = 7.0"""
    row = _get_metric("profiler_alpha", "S1", "species")
    assert math.isclose(float(row["l1_norm"]), 7.0, abs_tol=0.05)


def test_l1_alpha_s1_superkingdom():
    """Alpha S1 superkingdom: |95-97.5|+|2-2.5| = 3.0"""
    row = _get_metric("profiler_alpha", "S1", "superkingdom")
    assert math.isclose(float(row["l1_norm"]), 3.0, abs_tol=0.05)


def test_l1_alpha_s2_superkingdom():
    """Alpha S2 superkingdom: |97-98|+|2.5-2| = 1.5"""
    row = _get_metric("profiler_alpha", "S2", "superkingdom")
    assert math.isclose(float(row["l1_norm"]), 1.5, abs_tol=0.05)


def test_l1_alpha_s1_genus():
    """Alpha S1 genus: 1+1+0.5+0+0+0.5 = 3.0 (Bacteroides cancels)"""
    row = _get_metric("profiler_alpha", "S1", "genus")
    assert math.isclose(float(row["l1_norm"]), 3.0, abs_tol=0.05)


def test_l1_bravo_s1_species_corrected():
    """Bravo S1 species (after merging 74313->562, 29461->817): 1+2+1+1+1+0+0 = 6.0"""
    row = _get_metric("profiler_bravo", "S1", "species")
    assert math.isclose(float(row["l1_norm"]), 6.0, abs_tol=0.05)


def test_l1_bravo_s1_superkingdom_corrected():
    """Bravo S1 superkingdom corrected: |97.5-97.5|+|2.5-2.5| = 0.0"""
    row = _get_metric("profiler_bravo", "S1", "superkingdom")
    assert math.isclose(float(row["l1_norm"]), 0.0, abs_tol=0.05)


def test_l1_bravo_s2_species_corrected():
    """Bravo S2 species corrected: 1+1+1+1+0+0+0 = 4.0"""
    row = _get_metric("profiler_bravo", "S2", "species")
    assert math.isclose(float(row["l1_norm"]), 4.0, abs_tol=0.05)


def test_l1_charlie_s1_species_corrected():
    """Charlie S1 species after normalization (sum=110 -> /1.1): 0+0+0+0+0+0.5+0.5 = 1.0"""
    row = _get_metric("profiler_charlie", "S1", "species")
    assert math.isclose(float(row["l1_norm"]), 1.0, abs_tol=0.05)


def test_l1_charlie_s1_genus_corrected():
    """Charlie S1 genus after normalization: 0+0+0+0+0.5+0.5 = 1.0"""
    row = _get_metric("profiler_charlie", "S1", "genus")
    assert math.isclose(float(row["l1_norm"]), 1.0, abs_tol=0.05)


def test_l1_charlie_s1_superkingdom_corrected():
    """Charlie S1 superkingdom normalized: |97-97.5|+|3-2.5| = 1.0"""
    row = _get_metric("profiler_charlie", "S1", "superkingdom")
    assert math.isclose(float(row["l1_norm"]), 1.0, abs_tol=0.05)


def test_l1_charlie_s2_species():
    """Charlie S2 species (clean): 1+1+1+1+1+1+0 = 6.0"""
    row = _get_metric("profiler_charlie", "S2", "species")
    assert math.isclose(float(row["l1_norm"]), 6.0, abs_tol=0.05)


def test_l1_delta_s1_species():
    """Delta S1 species (clean): 1+1+0+1+1+0+0 = 4.0"""
    row = _get_metric("profiler_delta", "S1", "species")
    assert math.isclose(float(row["l1_norm"]), 4.0, abs_tol=0.05)


def test_l1_delta_s2_species_corrected():
    """Delta S2 species after dedup (15+7=22 for fragilis): 1+1+1+2+1+0+0 = 6.0"""
    row = _get_metric("profiler_delta", "S2", "species")
    assert math.isclose(float(row["l1_norm"]), 6.0, abs_tol=0.05)


def test_l1_delta_s1_superkingdom():
    """Delta S1 superkingdom: |97.5-97.5|+|2.5-2.5| = 0.0"""
    row = _get_metric("profiler_delta", "S1", "superkingdom")
    assert math.isclose(float(row["l1_norm"]), 0.0, abs_tol=0.05)


def test_l1_echo_s1_species():
    """Echo S1 species: 2+1+0.5+1+1+0.5+0 = 6.0"""
    row = _get_metric("profiler_echo", "S1", "species")
    assert math.isclose(float(row["l1_norm"]), 6.0, abs_tol=0.05)


def test_l1_echo_s2_species_corrected():
    """Echo S2 species (after fixing header): 1+1+1+1+1+1+0 = 6.0"""
    row = _get_metric("profiler_echo", "S2", "species")
    assert math.isclose(float(row["l1_norm"]), 6.0, abs_tol=0.05)


def test_l1_echo_s2_genus_corrected():
    """Echo S2 genus (after fixing header): 1+1+1+0+1+0 = 4.0"""
    row = _get_metric("profiler_echo", "S2", "genus")
    assert math.isclose(float(row["l1_norm"]), 4.0, abs_tol=0.05)


def test_l1_echo_s2_superkingdom_corrected():
    """Echo S2 superkingdom corrected: |98-98|+|2-2| = 0.0"""
    row = _get_metric("profiler_echo", "S2", "superkingdom")
    assert math.isclose(float(row["l1_norm"]), 0.0, abs_tol=0.05)


# ---- Precision/recall spot checks ----

def test_precision_recall_alpha_all_one():
    """Alpha predicts all taxa present in GS -> precision=recall=1.0 at every rank."""
    rows = _load_metrics()
    for r in rows:
        if r["tool"] == "profiler_alpha":
            assert math.isclose(float(r["precision"]), 1.0, abs_tol=0.001), \
                f"Alpha {r['sample']}/{r['rank']} precision={r['precision']}"
            assert math.isclose(float(r["recall"]), 1.0, abs_tol=0.001), \
                f"Alpha {r['sample']}/{r['rank']} recall={r['recall']}"


def test_precision_recall_bravo_corrected_all_one():
    """After resolving merged taxids, bravo predicts all GS taxa."""
    rows = _load_metrics()
    for r in rows:
        if r["tool"] == "profiler_bravo":
            assert math.isclose(float(r["precision"]), 1.0, abs_tol=0.001), \
                f"Bravo {r['sample']}/{r['rank']} precision={r['precision']}"
            assert math.isclose(float(r["recall"]), 1.0, abs_tol=0.001), \
                f"Bravo {r['sample']}/{r['rank']} recall={r['recall']}"


def test_precision_recall_charlie_corrected():
    """Charlie (after normalization) predicts all GS taxa."""
    rows = _load_metrics()
    for r in rows:
        if r["tool"] == "profiler_charlie":
            assert math.isclose(float(r["precision"]), 1.0, abs_tol=0.001), \
                f"Charlie {r['sample']}/{r['rank']} precision={r['precision']}"
            assert math.isclose(float(r["recall"]), 1.0, abs_tol=0.001), \
                f"Charlie {r['sample']}/{r['rank']} recall={r['recall']}"


# =====================================================================
# ranking.txt verification
# =====================================================================

def test_ranking_file_exists():
    assert os.path.isfile(RANKING_TXT), f"{RANKING_TXT} not found"


def test_ranking_has_five_entries():
    with open(RANKING_TXT) as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 5, f"Expected 5 tools in ranking, got {len(lines)}"


def test_ranking_correct_order():
    """Ranking by mean corrected L1 (lowest first):
    charlie (2.071) < delta (2.286) < bravo (3.0) < echo (3.429) < alpha (3.679)
    """
    with open(RANKING_TXT) as f:
        lines = [line.strip() for line in f if line.strip()]
    assert lines[0] == "profiler_charlie", f"Expected profiler_charlie 1st, got {lines[0]}"
    assert lines[1] == "profiler_delta", f"Expected profiler_delta 2nd, got {lines[1]}"
    assert lines[2] == "profiler_bravo", f"Expected profiler_bravo 3rd, got {lines[2]}"
    assert lines[3] == "profiler_echo", f"Expected profiler_echo 4th, got {lines[3]}"
    assert lines[4] == "profiler_alpha", f"Expected profiler_alpha 5th, got {lines[4]}"


def test_ranking_mean_l1_ordering():
    """Verify mean L1 values from corrected_metrics.tsv match ranking order."""
    rows = _load_metrics()
    tool_l1 = {}
    for r in rows:
        tool = r["tool"]
        l1 = float(r["l1_norm"])
        tool_l1.setdefault(tool, []).append(l1)
    means = {t: sum(vs) / len(vs) for t, vs in tool_l1.items()}
    ranked = sorted(means.keys(), key=lambda t: means[t])
    with open(RANKING_TXT) as f:
        file_ranking = [line.strip() for line in f if line.strip()]
    assert ranked == file_ranking, \
        f"Ranking from metrics doesn't match ranking.txt: {ranked} vs {file_ranking}"
