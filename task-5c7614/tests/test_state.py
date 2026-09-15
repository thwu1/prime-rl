
import json
import os
import csv
import subprocess
import pytest

RESULTS_PATH = "/app/results.json"
TOL = 1e-4


def load_results(path=RESULTS_PATH):
    assert os.path.exists(path), f"Results file not found: {path}"
    with open(path) as f:
        return json.load(f)


def approx(a, b, tol=TOL):
    return abs(a - b) < tol


class TestResultsStructure:
    """Verify the results.json has the correct structure."""

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_results_valid_json(self):
        r = load_results()
        assert "systems" in r
        assert "ranking" in r

    def test_all_systems_present(self):
        r = load_results()
        for s in ["alpha", "beta", "gamma", "delta"]:
            assert s in r["systems"], f"System {s} missing"

    def test_system_has_required_keys(self):
        r = load_results()
        for name, sys in r["systems"].items():
            for task in ["cea", "cta", "cpa"]:
                assert task in sys, f"{name} missing {task}"
                for metric in ["precision", "recall", "f1"]:
                    assert metric in sys[task], f"{name}.{task} missing {metric}"
            assert "cta_hierarchy" in sys, f"{name} missing cta_hierarchy"
            assert "cea_per_table" in sys, f"{name} missing cea_per_table"
            assert "aurc" in sys, f"{name} missing aurc"


class TestCEAMetrics:
    """Verify standard CEA precision/recall/F1 for each system."""

    def test_alpha_cea(self):
        r = load_results()
        cea = r["systems"]["alpha"]["cea"]
        assert approx(cea["precision"], 1.0)
        assert approx(cea["recall"], 0.8)
        assert approx(cea["f1"], 8.0 / 9.0)

    def test_beta_cea(self):
        r = load_results()
        cea = r["systems"]["beta"]["cea"]
        assert approx(cea["precision"], 0.75)
        assert approx(cea["recall"], 0.9)
        assert approx(cea["f1"], 9.0 / 11.0)

    def test_gamma_cea(self):
        r = load_results()
        cea = r["systems"]["gamma"]["cea"]
        assert approx(cea["precision"], 0.85)
        assert approx(cea["recall"], 0.85)
        assert approx(cea["f1"], 0.85)

    def test_delta_cea_with_redirects(self):
        """Delta uses redirected entity IDs. The evaluator must resolve them."""
        r = load_results()
        cea = r["systems"]["delta"]["cea"]
        assert approx(cea["precision"], 1.0), \
            f"Delta CEA precision should be 1.0 (redirect resolution required), got {cea['precision']}"
        assert approx(cea["recall"], 1.0)
        assert approx(cea["f1"], 1.0)


class TestCTAMetrics:
    """Verify standard CTA precision/recall/F1."""

    def test_alpha_cta(self):
        r = load_results()
        cta = r["systems"]["alpha"]["cta"]
        assert approx(cta["precision"], 1.0)
        assert approx(cta["recall"], 0.8)
        assert approx(cta["f1"], 8.0 / 9.0)

    def test_beta_cta(self):
        r = load_results()
        cta = r["systems"]["beta"]["cta"]
        assert approx(cta["precision"], 2.0 / 3.0)
        assert approx(cta["recall"], 0.8)
        assert approx(cta["f1"], 8.0 / 11.0)

    def test_gamma_cta(self):
        r = load_results()
        cta = r["systems"]["gamma"]["cta"]
        assert approx(cta["precision"], 0.8)
        assert approx(cta["recall"], 0.8)
        assert approx(cta["f1"], 0.8)

    def test_delta_cta(self):
        r = load_results()
        cta = r["systems"]["delta"]["cta"]
        assert approx(cta["precision"], 0.6)
        assert approx(cta["recall"], 0.6)
        assert approx(cta["f1"], 0.6)


class TestCPAMetrics:
    """Verify standard CPA precision/recall/F1."""

    def test_alpha_cpa(self):
        r = load_results()
        cpa = r["systems"]["alpha"]["cpa"]
        assert approx(cpa["precision"], 1.0)
        assert approx(cpa["recall"], 2.0 / 3.0)
        assert approx(cpa["f1"], 0.8)

    def test_beta_cpa(self):
        r = load_results()
        cpa = r["systems"]["beta"]["cpa"]
        assert approx(cpa["precision"], 0.75)
        assert approx(cpa["recall"], 1.0)
        assert approx(cpa["f1"], 6.0 / 7.0)

    def test_gamma_cpa(self):
        r = load_results()
        cpa = r["systems"]["gamma"]["cpa"]
        assert approx(cpa["precision"], 2.0 / 3.0)
        assert approx(cpa["recall"], 2.0 / 3.0)
        assert approx(cpa["f1"], 2.0 / 3.0)

    def test_delta_cpa(self):
        r = load_results()
        cpa = r["systems"]["delta"]["cpa"]
        assert approx(cpa["precision"], 1.0)
        assert approx(cpa["recall"], 1.0)
        assert approx(cpa["f1"], 1.0)


class TestHierarchyCTA:
    """Verify hierarchy-aware CTA scoring."""

    def test_alpha_hierarchy_same_as_standard(self):
        """Alpha predictions are all exact matches, so hierarchy == standard."""
        r = load_results()
        h = r["systems"]["alpha"]["cta_hierarchy"]
        assert approx(h["f1"], 8.0 / 9.0)

    def test_beta_hierarchy(self):
        r = load_results()
        h = r["systems"]["beta"]["cta_hierarchy"]
        assert approx(h["precision"], 0.75)
        assert approx(h["recall"], 0.9)
        assert approx(h["f1"], 9.0 / 11.0)

    def test_gamma_hierarchy(self):
        r = load_results()
        h = r["systems"]["gamma"]["cta_hierarchy"]
        assert approx(h["precision"], 0.9)
        assert approx(h["recall"], 0.9)
        assert approx(h["f1"], 0.9)

    def test_delta_hierarchy(self):
        r = load_results()
        h = r["systems"]["delta"]["cta_hierarchy"]
        assert approx(h["precision"], 0.8)
        assert approx(h["recall"], 0.8)
        assert approx(h["f1"], 0.8)


class TestAURC:
    """Verify AURC computation for selective prediction."""

    def test_gamma_has_aurc(self):
        r = load_results()
        assert r["systems"]["gamma"]["aurc"] is not None

    def test_non_confidence_systems_null_aurc(self):
        r = load_results()
        for s in ["alpha", "beta", "delta"]:
            assert r["systems"][s]["aurc"] is None, \
                f"System {s} should have null AURC"

    def test_gamma_aurc_value(self):
        r = load_results()
        aurc = r["systems"]["gamma"]["aurc"]
        assert abs(aurc - 0.042244) < 1e-3, \
            f"Gamma AURC expected ~0.04224, got {aurc}"


class TestPerTable:
    """Verify per-table CEA metrics."""

    def test_alpha_per_table_t001(self):
        r = load_results()
        t = r["systems"]["alpha"]["cea_per_table"]["T001"]
        assert approx(t["precision"], 1.0)
        assert approx(t["recall"], 1.0)
        assert approx(t["f1"], 1.0)

    def test_alpha_per_table_t003(self):
        r = load_results()
        t = r["systems"]["alpha"]["cea_per_table"]["T003"]
        assert approx(t["precision"], 1.0)
        assert approx(t["recall"], 2.0 / 6.0)
        assert approx(t["f1"], 0.5)

    def test_delta_per_table_all_perfect(self):
        """Delta should have F1=1.0 on all tables after redirect resolution."""
        r = load_results()
        for tbl in ["T001", "T002", "T003"]:
            t = r["systems"]["delta"]["cea_per_table"][tbl]
            assert approx(t["f1"], 1.0), \
                f"Delta {tbl} F1 should be 1.0, got {t['f1']}"


class TestRanking:
    """Verify system ranking by CEA F1."""

    def test_ranking_order(self):
        r = load_results()
        ranking = r["ranking"]
        assert ranking[0] == "delta"
        assert ranking[1] == "alpha"
        assert ranking[2] == "gamma"
        assert ranking[3] == "beta"


class TestAntiCheat:
    """Run the evaluator on a fresh synthetic dataset to ensure it is not hardcoded."""

    @pytest.fixture(autouse=True)
    def setup_holdout(self, tmp_path):
        """Create a small holdout dataset with RDF ontology files."""
        self.data_dir = str(tmp_path / "holdout")
        self.output_path = str(tmp_path / "holdout_results.json")

        WD = "http://www.wikidata.org/entity/"

        for d in ["gold", "predictions/test_sys", "ontology"]:
            os.makedirs(os.path.join(self.data_dir, d), exist_ok=True)

        # Gold CEA: 4 annotations
        self._write_csv(os.path.join(self.data_dir, "gold", "cea.csv"), [
            ["TX", "1", "0", f"{WD}QA"],
            ["TX", "1", "1", f"{WD}QB"],
            ["TX", "2", "0", f"{WD}QC"],
            ["TX", "2", "1", f"{WD}QD"],
        ])
        # Gold CTA: 2
        self._write_csv(os.path.join(self.data_dir, "gold", "cta.csv"), [
            ["TX", "0", f"{WD}QT1"],
            ["TX", "1", f"{WD}QT2"],
        ])
        # Gold CPA: 1
        self._write_csv(os.path.join(self.data_dir, "gold", "cpa.csv"), [
            ["TX", "0", "1", f"{WD}PP1"],
        ])

        # Prediction: 3 submitted for CEA, 2 correct
        self._write_csv(os.path.join(self.data_dir, "predictions", "test_sys", "cea.csv"), [
            ["TX", "1", "0", f"{WD}QA"],
            ["TX", "1", "1", f"{WD}QWRONG"],
            ["TX", "2", "0", f"{WD}QC"],
        ])
        # CTA: 2 submitted, 2 correct
        self._write_csv(os.path.join(self.data_dir, "predictions", "test_sys", "cta.csv"), [
            ["TX", "0", f"{WD}QT1"],
            ["TX", "1", f"{WD}QT2"],
        ])
        # CPA: 1 submitted, 0 correct
        self._write_csv(os.path.join(self.data_dir, "predictions", "test_sys", "cpa.csv"), [
            ["TX", "0", "1", f"{WD}PWRONG"],
        ])

        # Type hierarchy in Turtle format (two unrelated root types)
        with open(os.path.join(self.data_dir, "ontology", "type_hierarchy.ttl"), "w") as f:
            f.write("@prefix wd: <http://www.wikidata.org/entity/> .\n")
            f.write("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n")
            f.write('wd:QT1 rdfs:label "Type1" .\n')
            f.write('wd:QT2 rdfs:label "Type2" .\n')

        # Entity redirects in N-Triples format (empty)
        with open(os.path.join(self.data_dir, "ontology", "entity_redirects.nt"), "w") as f:
            f.write("# No redirects in holdout data\n")

        # Config
        self._write_json(os.path.join(self.data_dir, "config.json"), {
            "systems": ["test_sys"],
            "systems_with_confidence": [],
        })

    def _write_csv(self, path, rows):
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            for row in rows:
                w.writerow(row)

    def _write_json(self, path, obj):
        with open(path, "w") as f:
            json.dump(obj, f)

    def test_evaluator_on_holdout(self):
        """Run the evaluator on holdout data and verify metrics."""
        result = subprocess.run(
            ["python3", "/app/evaluate.py",
             "--data-dir", self.data_dir,
             "--output", self.output_path],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, \
            f"Evaluator failed on holdout data: {result.stderr}"

        with open(self.output_path) as f:
            r = json.load(f)

        sys_r = r["systems"]["test_sys"]

        # CEA: 2 correct / 3 submitted / 4 gold
        assert approx(sys_r["cea"]["precision"], 2.0 / 3.0)
        assert approx(sys_r["cea"]["recall"], 0.5)
        assert approx(sys_r["cea"]["f1"], 4.0 / 7.0)

        # CTA: 2 correct / 2 submitted / 2 gold => P=R=F1=1.0
        assert approx(sys_r["cta"]["f1"], 1.0)

        # CPA: 0 correct / 1 submitted / 1 gold
        assert approx(sys_r["cpa"]["precision"], 0.0)
        assert approx(sys_r["cpa"]["recall"], 0.0)
        assert approx(sys_r["cpa"]["f1"], 0.0)
