
import subprocess
import csv
import json
import os
import math
import sqlite3
import pytest

RESULTS_FILE = "/app/output/results.tsv"
RANKINGS_FILE = "/app/output/rankings.tsv"
VALIDATION_FILE = "/app/output/validation.json"
TAXONOMY_DB = "/app/output/taxonomy.db"

MAKE_CMD = [
    "make", "-C", "/app", "all",
    "MANIFEST=/app/data/manifest.json",
    "OUTPUT_DIR=/app/output"
]

RANK_ORDER = ["superkingdom", "phylum", "genus", "species"]
TOL = 1e-4


@pytest.fixture(scope="module", autouse=True)
def run_tool():
    """Run the pipeline via make once before all tests."""
    os.makedirs("/app/output", exist_ok=True)
    result = subprocess.run(MAKE_CMD, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (
        f"make all failed (exit {result.returncode}).\n"
        f"STDOUT: {result.stdout[:2000]}\nSTDERR: {result.stderr[:2000]}"
    )


def load_results():
    with open(RESULTS_FILE) as f:
        return list(csv.DictReader(f, delimiter='\t'))


def load_rankings():
    with open(RANKINGS_FILE) as f:
        return list(csv.DictReader(f, delimiter='\t'))


def load_validation():
    with open(VALIDATION_FILE) as f:
        return json.load(f)


def find_row(data, tool, sample, rank):
    for row in data:
        if row["tool"] == tool and row["sample"] == sample and row["rank"] == rank:
            return row
    return None


# ─── Makefile and pipeline structure ────────────────────────────────────────

class TestMakePipeline:
    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), "/app/Makefile not found"

    def test_taxonomy_db_target_independent(self):
        """taxonomy-db target creates the database in a fresh directory."""
        tmpdir = "/tmp/test_taxonomy_target"
        os.makedirs(tmpdir, exist_ok=True)
        result = subprocess.run(
            ["make", "-C", "/app", "taxonomy-db",
             "MANIFEST=/app/data/manifest.json",
             f"OUTPUT_DIR={tmpdir}"],
            capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, (
            f"make taxonomy-db failed: {result.stderr[:500]}")
        assert os.path.isfile(f"{tmpdir}/taxonomy.db"), (
            "taxonomy.db not created by taxonomy-db target")


# ─── SQLite taxonomy database ──────────────────────────────────────────────

class TestTaxonomyDB:
    def test_taxonomy_db_exists(self):
        assert os.path.isfile(TAXONOMY_DB), "taxonomy.db not found"

    def test_taxonomy_db_schema(self):
        conn = sqlite3.connect(TAXONOMY_DB)
        cursor = conn.execute("PRAGMA table_info(nodes)")
        cols = {row[1]: row[2].upper() for row in cursor.fetchall()}
        assert "tax_id" in cols, "Missing tax_id column"
        assert "parent_id" in cols, "Missing parent_id column"
        assert "rank" in cols, "Missing rank column"
        conn.close()

    def test_taxonomy_db_row_count(self):
        conn = sqlite3.connect(TAXONOMY_DB)
        cursor = conn.execute("SELECT COUNT(*) FROM nodes")
        count = cursor.fetchone()[0]
        assert count == 21, f"Expected 21 nodes, got {count}"
        conn.close()

    def test_taxonomy_parent_escherichia(self):
        """Escherichia (561) parent must be Proteobacteria (1224)."""
        conn = sqlite3.connect(TAXONOMY_DB)
        cursor = conn.execute(
            "SELECT parent_id FROM nodes WHERE tax_id = 561")
        row = cursor.fetchone()
        assert row is not None, "taxid 561 not found"
        assert row[0] == 1224, f"Escherichia parent should be 1224, got {row[0]}"
        conn.close()

    def test_taxonomy_parent_bacillus(self):
        """Bacillus (1386) parent must be Firmicutes (1239)."""
        conn = sqlite3.connect(TAXONOMY_DB)
        cursor = conn.execute(
            "SELECT parent_id FROM nodes WHERE tax_id = 1386")
        row = cursor.fetchone()
        assert row is not None, "taxid 1386 not found"
        assert row[0] == 1239, f"Bacillus parent should be 1239, got {row[0]}"
        conn.close()

    def test_taxonomy_rank_values(self):
        conn = sqlite3.connect(TAXONOMY_DB)
        cursor = conn.execute("SELECT DISTINCT rank FROM nodes")
        ranks = {row[0] for row in cursor.fetchall()}
        assert "superkingdom" in ranks
        assert "phylum" in ranks
        assert "genus" in ranks
        assert "species" in ranks
        conn.close()

    def test_taxonomy_root_self_parent(self):
        """Root node (1) must have itself as parent."""
        conn = sqlite3.connect(TAXONOMY_DB)
        cursor = conn.execute(
            "SELECT parent_id FROM nodes WHERE tax_id = 1")
        row = cursor.fetchone()
        assert row is not None, "Root taxid 1 not found"
        assert row[0] == 1, f"Root parent should be 1, got {row[0]}"
        conn.close()


# ─── File existence and format ───────────────────────────────────────────────

class TestOutputFileFormat:
    def test_results_file_exists(self):
        assert os.path.isfile(RESULTS_FILE), "results.tsv not found"

    def test_rankings_file_exists(self):
        assert os.path.isfile(RANKINGS_FILE), "rankings.tsv not found"

    def test_validation_file_exists(self):
        assert os.path.isfile(VALIDATION_FILE), "validation.json not found"

    def test_results_columns(self):
        data = load_results()
        expected_cols = {"tool", "sample", "rank", "l1_norm", "bray_curtis",
                         "precision", "recall", "f1", "jaccard",
                         "shannon_diversity"}
        actual_cols = set(data[0].keys())
        assert expected_cols.issubset(actual_cols), (
            f"Missing columns: {expected_cols - actual_cols}"
        )

    def test_rankings_columns(self):
        data = load_rankings()
        expected_cols = {"tool", "avg_l1_norm", "avg_bray_curtis",
                         "avg_precision", "avg_recall", "avg_f1",
                         "avg_jaccard", "composite_score"}
        actual_cols = set(data[0].keys())
        assert expected_cols.issubset(actual_cols), (
            f"Missing columns: {expected_cols - actual_cols}"
        )

    def test_results_row_count(self):
        """4 tools x 2 samples x 4 ranks = 32 rows."""
        data = load_results()
        assert len(data) == 32, f"Expected 32 rows, got {len(data)}"

    def test_rankings_row_count(self):
        """4 tools = 4 rows."""
        data = load_rankings()
        assert len(data) == 4, f"Expected 4 rows, got {len(data)}"

    def test_results_all_tools_present(self):
        data = load_results()
        tools = {row["tool"] for row in data}
        assert tools == {"ToolA", "ToolB", "ToolC", "ToolD"}

    def test_results_all_samples_present(self):
        data = load_results()
        samples = {row["sample"] for row in data}
        assert samples == {"S1", "S2"}

    def test_results_all_ranks_present(self):
        data = load_results()
        ranks = {row["rank"] for row in data}
        assert ranks == set(RANK_ORDER)

    def test_validation_structure(self):
        val = load_validation()
        assert "warnings" in val, "validation.json must have 'warnings' key"
        assert isinstance(val["warnings"], list)


# ─── Tool A metrics (high quality, duplicate entry handling) ─────────────────

class TestToolAMetrics:
    def test_tool_a_s1_superkingdom(self):
        data = load_results()
        row = find_row(data, "ToolA", "S1", "superkingdom")
        assert row is not None, "ToolA/S1/superkingdom row missing"
        assert abs(float(row["l1_norm"]) - 0.04) < TOL
        assert abs(float(row["bray_curtis"]) - 0.02) < TOL
        assert abs(float(row["precision"]) - 1.0) < TOL
        assert abs(float(row["recall"]) - 1.0) < TOL
        assert abs(float(row["f1"]) - 1.0) < TOL
        assert abs(float(row["jaccard"]) - 1.0) < TOL

    def test_tool_a_s1_superkingdom_shannon(self):
        data = load_results()
        row = find_row(data, "ToolA", "S1", "superkingdom")
        assert abs(float(row["shannon_diversity"]) - 0.592953) < TOL

    def test_tool_a_s1_phylum(self):
        data = load_results()
        row = find_row(data, "ToolA", "S1", "phylum")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 0.04) < TOL
        assert abs(float(row["bray_curtis"]) - 0.02) < TOL
        assert abs(float(row["precision"]) - 1.0) < TOL

    def test_tool_a_s1_species_duplicate_merge(self):
        """ToolA S1 species has Bacillus subtilis split into two entries
        (17.0 + 10.0 = 27.0). Correct merging should yield same metrics
        as genus level."""
        data = load_results()
        row = find_row(data, "ToolA", "S1", "species")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 0.04) < TOL
        assert abs(float(row["bray_curtis"]) - 0.02) < TOL
        assert abs(float(row["precision"]) - 1.0) < TOL
        assert abs(float(row["recall"]) - 1.0) < TOL
        assert abs(float(row["jaccard"]) - 1.0) < TOL

    def test_tool_a_s2_genus(self):
        data = load_results()
        row = find_row(data, "ToolA", "S2", "genus")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 0.08) < TOL
        assert abs(float(row["bray_curtis"]) - 0.04) < TOL
        assert abs(float(row["precision"]) - 1.0) < TOL
        assert abs(float(row["recall"]) - 1.0) < TOL
        assert abs(float(row["jaccard"]) - 1.0) < TOL


# ─── Tool B metrics (medium quality, zero-entry handling) ──────────────────

class TestToolBMetrics:
    def test_tool_b_s1_superkingdom(self):
        data = load_results()
        row = find_row(data, "ToolB", "S1", "superkingdom")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 0.3) < TOL
        assert abs(float(row["bray_curtis"]) - 0.15) < TOL
        assert abs(float(row["precision"]) - 1.0) < TOL
        assert abs(float(row["recall"]) - 1.0) < TOL

    def test_tool_b_s1_genus(self):
        data = load_results()
        row = find_row(data, "ToolB", "S1", "genus")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 0.4) < TOL
        assert abs(float(row["bray_curtis"]) - 0.2) < TOL
        assert abs(float(row["precision"]) - 1.0) < TOL
        assert abs(float(row["jaccard"]) - 1.0) < TOL

    def test_tool_b_s2_genus_zero_entry(self):
        """ToolB S2 genus has a 0.0% Prevotella entry that must be ignored.
        If counted as present, precision drops below 1.0."""
        data = load_results()
        row = find_row(data, "ToolB", "S2", "genus")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 0.3) < TOL
        assert abs(float(row["bray_curtis"]) - 0.15) < TOL
        assert abs(float(row["precision"]) - 1.0) < TOL
        assert abs(float(row["recall"]) - 1.0) < TOL
        assert abs(float(row["jaccard"]) - 1.0) < TOL

    def test_tool_b_s2_phylum(self):
        data = load_results()
        row = find_row(data, "ToolB", "S2", "phylum")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 0.3) < TOL
        assert abs(float(row["bray_curtis"]) - 0.15) < TOL


# ─── Tool C metrics (low quality, false positives and negatives) ─────────────

class TestToolCMetrics:
    def test_tool_c_s1_superkingdom(self):
        data = load_results()
        row = find_row(data, "ToolC", "S1", "superkingdom")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 0.5) < TOL
        assert abs(float(row["bray_curtis"]) - 0.25) < TOL
        assert abs(float(row["precision"]) - 1.0) < TOL
        assert abs(float(row["recall"]) - 1.0) < TOL
        assert abs(float(row["jaccard"]) - 1.0) < TOL

    def test_tool_c_s1_phylum(self):
        """GS: 3 phyla. Pred: 3 GS + Bacteroidetes (FP).
        P=3/4=0.75, R=1.0, F1=6/7, J=3/4."""
        data = load_results()
        row = find_row(data, "ToolC", "S1", "phylum")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 0.7) < TOL
        assert abs(float(row["bray_curtis"]) - 0.35) < TOL
        assert abs(float(row["precision"]) - 0.75) < TOL
        assert abs(float(row["recall"]) - 1.0) < TOL
        assert abs(float(row["f1"]) - (6.0 / 7.0)) < TOL
        assert abs(float(row["jaccard"]) - 0.75) < TOL

    def test_tool_c_s1_genus(self):
        """GS: 5 genera. Pred: 4 matching + 2 FP. 1 FN.
        TP=4, FP=2, FN=1. P=4/6, R=4/5, F1=8/11, J=4/7."""
        data = load_results()
        row = find_row(data, "ToolC", "S1", "genus")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 1.0) < TOL
        assert abs(float(row["bray_curtis"]) - 0.5) < TOL
        assert abs(float(row["precision"]) - (4.0 / 6.0)) < TOL
        assert abs(float(row["recall"]) - 0.8) < TOL
        assert abs(float(row["f1"]) - (8.0 / 11.0)) < TOL
        assert abs(float(row["jaccard"]) - (4.0 / 7.0)) < TOL

    def test_tool_c_s1_genus_shannon(self):
        data = load_results()
        row = find_row(data, "ToolC", "S1", "genus")
        assert abs(float(row["shannon_diversity"]) - 1.638506) < TOL

    def test_tool_c_s2_phylum(self):
        data = load_results()
        row = find_row(data, "ToolC", "S2", "phylum")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 0.6) < TOL
        assert abs(float(row["bray_curtis"]) - 0.3) < TOL
        assert abs(float(row["precision"]) - 0.75) < TOL
        assert abs(float(row["recall"]) - 1.0) < TOL
        assert abs(float(row["jaccard"]) - 0.75) < TOL

    def test_tool_c_s2_genus(self):
        """TP=3, FP=2, FN=2. P=3/5, R=3/5, F1=0.6, J=3/7."""
        data = load_results()
        row = find_row(data, "ToolC", "S2", "genus")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 1.0) < TOL
        assert abs(float(row["bray_curtis"]) - 0.5) < TOL
        assert abs(float(row["precision"]) - 0.6) < TOL
        assert abs(float(row["recall"]) - 0.6) < TOL
        assert abs(float(row["f1"]) - 0.6) < TOL
        assert abs(float(row["jaccard"]) - (3.0 / 7.0)) < TOL

    def test_tool_c_s2_genus_shannon(self):
        data = load_results()
        row = find_row(data, "ToolC", "S2", "genus")
        assert abs(float(row["shannon_diversity"]) - 1.544480) < TOL


# ─── Tool D metrics (edge cases: duplicate, zero, missing sample, comments) ──

class TestToolDMetrics:
    def test_tool_d_s1_superkingdom(self):
        """Same values as ToolA S1 (no edge cases at this rank)."""
        data = load_results()
        row = find_row(data, "ToolD", "S1", "superkingdom")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 0.04) < TOL
        assert abs(float(row["bray_curtis"]) - 0.02) < TOL
        assert abs(float(row["precision"]) - 1.0) < TOL
        assert abs(float(row["jaccard"]) - 1.0) < TOL

    def test_tool_d_s1_phylum_sum_not_100(self):
        """Phylum percentages sum to 95, not 100. BC denominator differs."""
        data = load_results()
        row = find_row(data, "ToolD", "S1", "phylum")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 0.09) < TOL
        # BC = 9/(100+95) = 9/195 ≈ 0.046154
        assert abs(float(row["bray_curtis"]) - 0.046154) < TOL
        assert abs(float(row["precision"]) - 1.0) < TOL
        assert abs(float(row["recall"]) - 1.0) < TOL
        assert abs(float(row["jaccard"]) - 1.0) < TOL

    def test_tool_d_s1_genus_duplicate_and_zero(self):
        """Genus has duplicate Bacillus entry (15+12=27) and 0% Prevotella.
        After correct merging/filtering: same effective taxa as ToolA S1."""
        data = load_results()
        row = find_row(data, "ToolD", "S1", "genus")
        assert row is not None
        assert abs(float(row["l1_norm"]) - 0.04) < TOL
        assert abs(float(row["bray_curtis"]) - 0.02) < TOL
        assert abs(float(row["precision"]) - 1.0) < TOL
        assert abs(float(row["recall"]) - 1.0) < TOL
        assert abs(float(row["f1"]) - 1.0) < TOL
        assert abs(float(row["jaccard"]) - 1.0) < TOL

    def test_tool_d_s2_missing_sample(self):
        """ToolD has no S2 predictions. All predictions empty."""
        data = load_results()
        # All 4 ranks at S2 should have values for missing predictions
        for rank in RANK_ORDER:
            row = find_row(data, "ToolD", "S2", rank)
            assert row is not None, f"ToolD/S2/{rank} row missing"
            assert abs(float(row["l1_norm"]) - 1.0) < TOL
            assert abs(float(row["bray_curtis"]) - 1.0) < TOL
            assert abs(float(row["precision"]) - 0.0) < TOL
            assert abs(float(row["recall"]) - 0.0) < TOL
            assert abs(float(row["f1"]) - 0.0) < TOL
            assert abs(float(row["jaccard"]) - 0.0) < TOL
            assert abs(float(row["shannon_diversity"]) - 0.0) < TOL

    def test_tool_d_s1_phylum_shannon(self):
        """Shannon for phylum with non-100 sum (uses raw pct/100, not renormalized)."""
        data = load_results()
        row = find_row(data, "ToolD", "S1", "phylum")
        assert abs(float(row["shannon_diversity"]) - 1.067354) < TOL


# ─── Rankings ────────────────────────────────────────────────────────────────

class TestRankings:
    def test_ranking_order(self):
        """ToolA > ToolB > ToolC > ToolD by composite score."""
        data = load_rankings()
        tools_ordered = [row["tool"] for row in data]
        assert tools_ordered == ["ToolA", "ToolB", "ToolC", "ToolD"], (
            f"Expected ranking ToolA > ToolB > ToolC > ToolD, got {tools_ordered}"
        )

    def test_tool_a_composite(self):
        data = load_rankings()
        row = [r for r in data if r["tool"] == "ToolA"][0]
        assert abs(float(row["composite_score"]) - 0.991667) < 0.001

    def test_tool_b_composite(self):
        data = load_rankings()
        row = [r for r in data if r["tool"] == "ToolB"][0]
        assert abs(float(row["composite_score"]) - 0.945833) < 0.001

    def test_tool_c_composite(self):
        data = load_rankings()
        row = [r for r in data if r["tool"] == "ToolC"][0]
        assert abs(float(row["composite_score"]) - 0.716712) < 0.001

    def test_tool_d_composite(self):
        data = load_rankings()
        row = [r for r in data if r["tool"] == "ToolD"][0]
        assert abs(float(row["composite_score"]) - 0.537268) < 0.001

    def test_tool_a_avg_metrics(self):
        data = load_rankings()
        row = [r for r in data if r["tool"] == "ToolA"][0]
        assert abs(float(row["avg_l1_norm"]) - 0.05) < TOL
        assert abs(float(row["avg_bray_curtis"]) - 0.025) < TOL
        assert abs(float(row["avg_precision"]) - 1.0) < TOL
        assert abs(float(row["avg_recall"]) - 1.0) < TOL
        assert abs(float(row["avg_jaccard"]) - 1.0) < TOL

    def test_tool_c_avg_metrics(self):
        data = load_rankings()
        row = [r for r in data if r["tool"] == "ToolC"][0]
        assert abs(float(row["avg_l1_norm"]) - 0.7875) < TOL
        assert abs(float(row["avg_bray_curtis"]) - 0.39375) < TOL
        assert abs(float(row["avg_precision"]) - 0.754167) < TOL
        assert abs(float(row["avg_recall"]) - 0.85) < TOL
        assert abs(float(row["avg_jaccard"]) - 0.6875) < TOL

    def test_tool_d_avg_metrics(self):
        data = load_rankings()
        row = [r for r in data if r["tool"] == "ToolD"][0]
        assert abs(float(row["avg_precision"]) - 0.5) < TOL
        assert abs(float(row["avg_recall"]) - 0.5) < TOL
        assert abs(float(row["avg_jaccard"]) - 0.5) < TOL


# ─── Validation ──────────────────────────────────────────────────────────────

class TestValidation:
    def test_validation_warning_count(self):
        """Exactly 2 warnings: phylum sum and TAXPATH mismatch in ToolD."""
        val = load_validation()
        assert len(val["warnings"]) == 2, (
            f"Expected 2 validation warnings, got {len(val['warnings'])}: "
            f"{val['warnings']}"
        )

    def test_validation_phylum_sum_warning(self):
        """ToolD S1 phylum sums to 95, not 100."""
        val = load_validation()
        phylum_warnings = [w for w in val["warnings"]
                           if w["file"] == "tool_d.profile"
                           and w["sample"] == "S1"
                           and w["rank"] == "phylum"
                           and "sum" in w["issue"].lower()]
        assert len(phylum_warnings) >= 1, (
            "Missing validation warning for ToolD S1 phylum percentage sum"
        )

    def test_validation_taxpath_warning(self):
        """ToolD S1 genus taxid 561 has wrong parent in TAXPATH."""
        val = load_validation()
        taxpath_warnings = [w for w in val["warnings"]
                            if w["file"] == "tool_d.profile"
                            and w["sample"] == "S1"
                            and "561" in w["issue"]
                            and ("parent" in w["issue"].lower()
                                 or "taxpath" in w["issue"].lower()
                                 or "1239" in w["issue"])]
        assert len(taxpath_warnings) >= 1, (
            "Missing validation warning for ToolD S1 genus taxid 561 "
            "TAXPATH parent mismatch"
        )

    def test_no_false_positive_warnings(self):
        """No warnings for ToolA, ToolB, ToolC, or gold standard."""
        val = load_validation()
        non_toold = [w for w in val["warnings"]
                     if w["file"] != "tool_d.profile"]
        assert len(non_toold) == 0, (
            f"Unexpected warnings for non-ToolD profiles: {non_toold}"
        )

    def test_validation_warning_fields(self):
        """Each warning has required fields."""
        val = load_validation()
        for w in val["warnings"]:
            assert "file" in w, f"Missing 'file' in warning: {w}"
            assert "sample" in w, f"Missing 'sample' in warning: {w}"
            assert "rank" in w, f"Missing 'rank' in warning: {w}"
            assert "issue" in w, f"Missing 'issue' in warning: {w}"


# ─── Valid ranges ────────────────────────────────────────────────────────────

class TestValidRanges:
    def test_l1_norm_range(self):
        data = load_results()
        for row in data:
            val = float(row["l1_norm"])
            assert 0.0 <= val <= 2.0, f"L1 norm {val} out of range for {row}"

    def test_bray_curtis_range(self):
        data = load_results()
        for row in data:
            val = float(row["bray_curtis"])
            assert 0.0 <= val <= 1.0, f"Bray-Curtis {val} out of range for {row}"

    def test_precision_range(self):
        data = load_results()
        for row in data:
            val = float(row["precision"])
            assert 0.0 <= val <= 1.0, f"Precision {val} out of range for {row}"

    def test_recall_range(self):
        data = load_results()
        for row in data:
            val = float(row["recall"])
            assert 0.0 <= val <= 1.0, f"Recall {val} out of range for {row}"

    def test_f1_range(self):
        data = load_results()
        for row in data:
            val = float(row["f1"])
            assert 0.0 <= val <= 1.0, f"F1 {val} out of range for {row}"

    def test_jaccard_range(self):
        data = load_results()
        for row in data:
            val = float(row["jaccard"])
            assert 0.0 <= val <= 1.0, f"Jaccard {val} out of range for {row}"

    def test_shannon_non_negative(self):
        data = load_results()
        for row in data:
            val = float(row["shannon_diversity"])
            assert val >= 0.0, f"Shannon diversity {val} negative for {row}"

    def test_composite_range(self):
        data = load_rankings()
        for row in data:
            val = float(row["composite_score"])
            assert 0.0 <= val <= 1.0, f"Composite score {val} out of range for {row}"


# ─── Sorting checks ─────────────────────────────────────────────────────────

class TestSorting:
    def test_results_sorted_by_tool_sample_rank(self):
        """Verify results are sorted by tool, then sample, then rank order."""
        data = load_results()
        rank_idx = {r: i for i, r in enumerate(RANK_ORDER)}
        sort_keys = [(row["tool"], row["sample"], rank_idx.get(row["rank"], 99))
                     for row in data]
        assert sort_keys == sorted(sort_keys), "results.tsv is not properly sorted"

    def test_rankings_sorted_by_composite_desc(self):
        """Verify rankings are sorted by composite_score descending."""
        data = load_rankings()
        scores = [float(row["composite_score"]) for row in data]
        assert scores == sorted(scores, reverse=True), (
            "rankings.tsv not sorted by composite_score descending"
        )
