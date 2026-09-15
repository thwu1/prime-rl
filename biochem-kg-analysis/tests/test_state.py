"""
"""
import json
import os
import math
import pytest


@pytest.fixture
def report():
    report_path = "/app/report.json"
    assert os.path.exists(report_path), "report.json does not exist at /app/report.json"
    with open(report_path) as f:
        data = json.load(f)
    return data


class TestOntologyAnalysis:
    def test_report_has_ontology_section(self, report):
        assert "ontology" in report, "Report missing 'ontology' section"

    def test_num_classes(self, report):
        assert report["ontology"]["num_classes"] == 55, (
            f"Expected 55 OWL classes, got {report['ontology']['num_classes']}"
        )

    def test_num_datatype_properties(self, report):
        assert report["ontology"]["num_datatype_properties"] == 16, (
            f"Expected 16 datatype properties, got {report['ontology']['num_datatype_properties']}"
        )

    def test_max_hierarchy_depth(self, report):
        assert report["ontology"]["max_hierarchy_depth"] == 3, (
            f"Expected max hierarchy depth 3, got {report['ontology']['max_hierarchy_depth']}"
        )

    def test_broken_references_count(self, report):
        refs = report["ontology"]["broken_references"]
        assert len(refs) == 5, (
            f"Expected 5 broken references, got {len(refs)}"
        )

    def test_broken_references_content(self, report):
        refs = report["ontology"]["broken_references"]
        ref_pairs = {(r["class"], r["target"]) for r in refs}

        expected_pairs = {
            ("Aminoacid", "AminoacidsAndPeptide"),
            ("HydrolysableTannin", "Tanins"),
            ("Peptide", "AminoacidsAndPeptide"),
            ("QuinolizidineAlkaloid", "Alkaloids"),
        }
        # The fifth is Β-Lactam (Greek Beta) -> AminoacidsAndPeptide
        found_beta_lactam = False
        for cls_name, ref_name in ref_pairs:
            if "Lactam" in cls_name and ref_name == "AminoacidsAndPeptide":
                found_beta_lactam = True
                break

        ascii_pairs = {(c, r) for c, r in ref_pairs if "Lactam" not in c}
        assert expected_pairs == ascii_pairs, (
            f"Expected pairs {expected_pairs}, got {ascii_pairs}"
        )
        assert found_beta_lactam, (
            "Missing Β-Lactam -> AminoacidsAndPeptide reference"
        )

    def test_broken_refs_sorted(self, report):
        refs = report["ontology"]["broken_references"]
        class_names = [r["class"] for r in refs]
        assert class_names == sorted(class_names), (
            f"broken_references should be sorted by class name, got {class_names}"
        )

    def test_broken_ref_distinct_targets(self, report):
        refs = report["ontology"]["broken_references"]
        targets = {r["target"] for r in refs}
        assert len(targets) == 3, (
            f"Expected 3 distinct broken target names, got {len(targets)}: {targets}"
        )


class TestConformance:
    def test_report_has_conformance_section(self, report):
        assert "conformance" in report, "Report missing 'conformance' section"

    def test_property_name_mismatches_count(self, report):
        mismatches = report["conformance"]["property_name_mismatches"]
        assert len(mismatches) == 1, (
            f"Expected 1 property name mismatch, got {len(mismatches)}"
        )

    def test_property_name_mismatch_clogp(self, report):
        mismatches = report["conformance"]["property_name_mismatches"]
        found = False
        for m in mismatches:
            if m["ontology_name"] == "clogP" and m["kb_name"] == "cLogP":
                found = True
                break
        assert found, (
            f"Expected mismatch ontology='clogP' vs kb='cLogP', got {mismatches}"
        )


class TestKBAnalysis:
    def test_report_has_kb_section(self, report):
        assert "kb" in report, "Report missing 'kb' section"

    def test_num_compounds(self, report):
        assert report["kb"]["num_compounds"] == 20, (
            f"Expected 20 compounds, got {report['kb']['num_compounds']}"
        )

    def test_num_triples(self, report):
        assert report["kb"]["num_triples"] == 200, (
            f"Expected 200 triples, got {report['kb']['num_triples']}"
        )

    def test_lipinski_violators(self, report):
        violators = sorted(report["kb"]["lipinski_violators"])
        expected = [4, 5, 8, 9, 11, 20]
        assert violators == expected, (
            f"Expected Lipinski violators {expected}, got {violators}"
        )


class TestEvaluationMetrics:
    def test_report_has_evaluation_section(self, report):
        assert "evaluation" in report, "Report missing 'evaluation' section"

    def test_metrics_present(self, report):
        metrics = report["evaluation"]["metrics"]
        assert len(metrics) == 4, (
            f"Expected 4 metric entries (2 algorithms x 2 stages), got {len(metrics)}"
        )

    def test_best_hits1_algorithm(self, report):
        best = report["evaluation"]["best_hits1_algorithm"]
        assert best == "regularization", (
            f"Expected best hits@1 algorithm 'regularization', got '{best}'"
        )

    def _find_metric(self, metrics, algorithm, stage):
        for m in metrics:
            if m["algorithm"] == algorithm and m["stage"] == stage:
                return m
        return None

    def test_deep_walk_1st_hits1(self, report):
        m = self._find_metric(report["evaluation"]["metrics"], "deep_walk", "1st")
        assert m is not None, "Missing metric for deep_walk/1st"
        assert math.isclose(m["hits_at_1"], 0.2, abs_tol=1e-6), (
            f"deep_walk 1st hits@1: expected 0.2, got {m['hits_at_1']}"
        )

    def test_deep_walk_1st_hits3(self, report):
        m = self._find_metric(report["evaluation"]["metrics"], "deep_walk", "1st")
        assert m is not None, "Missing metric for deep_walk/1st"
        assert math.isclose(m["hits_at_3"], 1.0, abs_tol=1e-6), (
            f"deep_walk 1st hits@3: expected 1.0, got {m['hits_at_3']}"
        )

    def test_deep_walk_1st_mrr(self, report):
        m = self._find_metric(report["evaluation"]["metrics"], "deep_walk", "1st")
        assert m is not None, "Missing metric for deep_walk/1st"
        assert math.isclose(m["mrr"], 0.5, abs_tol=1e-4), (
            f"deep_walk 1st MRR: expected 0.5, got {m['mrr']}"
        )

    def test_deep_walk_2nd_hits1(self, report):
        m = self._find_metric(report["evaluation"]["metrics"], "deep_walk", "2nd")
        assert m is not None, "Missing metric for deep_walk/2nd"
        assert math.isclose(m["hits_at_1"], 1.0 / 3.0, abs_tol=1e-4), (
            f"deep_walk 2nd hits@1: expected {1/3}, got {m['hits_at_1']}"
        )

    def test_deep_walk_2nd_hits3(self, report):
        m = self._find_metric(report["evaluation"]["metrics"], "deep_walk", "2nd")
        assert m is not None, "Missing metric for deep_walk/2nd"
        assert math.isclose(m["hits_at_3"], 2.0 / 3.0, abs_tol=1e-4), (
            f"deep_walk 2nd hits@3: expected {2/3}, got {m['hits_at_3']}"
        )

    def test_deep_walk_2nd_mrr(self, report):
        m = self._find_metric(report["evaluation"]["metrics"], "deep_walk", "2nd")
        assert m is not None, "Missing metric for deep_walk/2nd"
        # doi_6: rank=3 -> 1/3, doi_7: rank=1 -> 1/1, doi_8: NOT FOUND (excluded)
        # MRR = (1/3 + 1) / 2 = 0.6667
        assert math.isclose(m["mrr"], (1.0 / 3.0 + 1.0) / 2.0, abs_tol=1e-4), (
            f"deep_walk 2nd MRR: expected {(1/3 + 1) / 2}, got {m['mrr']}"
        )

    def test_regularization_1st_hits1(self, report):
        m = self._find_metric(
            report["evaluation"]["metrics"], "regularization", "1st"
        )
        assert m is not None, "Missing metric for regularization/1st"
        assert math.isclose(m["hits_at_1"], 0.8, abs_tol=1e-6), (
            f"regularization 1st hits@1: expected 0.8, got {m['hits_at_1']}"
        )

    def test_regularization_2nd_hits1(self, report):
        m = self._find_metric(
            report["evaluation"]["metrics"], "regularization", "2nd"
        )
        assert m is not None, "Missing metric for regularization/2nd"
        assert math.isclose(m["hits_at_1"], 1.0, abs_tol=1e-6), (
            f"regularization 2nd hits@1: expected 1.0, got {m['hits_at_1']}"
        )

    def test_regularization_1st_mrr(self, report):
        m = self._find_metric(
            report["evaluation"]["metrics"], "regularization", "1st"
        )
        assert m is not None, "Missing metric for regularization/1st"
        assert math.isclose(m["mrr"], 0.9, abs_tol=1e-4), (
            f"regularization 1st MRR: expected 0.9, got {m['mrr']}"
        )

    def test_regularization_2nd_mrr(self, report):
        m = self._find_metric(
            report["evaluation"]["metrics"], "regularization", "2nd"
        )
        assert m is not None, "Missing metric for regularization/2nd"
        assert math.isclose(m["mrr"], 1.0, abs_tol=1e-4), (
            f"regularization 2nd MRR: expected 1.0, got {m['mrr']}"
        )
