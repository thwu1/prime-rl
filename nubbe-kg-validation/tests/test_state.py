
import json
import pytest
import os


@pytest.fixture
def analysis():
    assert os.path.exists("/app/results/analysis.json"), "Output file /app/results/analysis.json not found"
    with open("/app/results/analysis.json", "r") as f:
        return json.load(f)


class TestOrphanSubclassDeclarations:
    def test_count(self, analysis):
        orphans = analysis["orphan_subclass_declarations"]
        assert len(orphans) == 5, f"Expected 5 orphan subclass declarations, got {len(orphans)}"

    def test_aminoacids_and_peptide_orphans(self, analysis):
        """Three classes reference the non-existent 'AminoacidsAndPeptide' parent."""
        orphans = analysis["orphan_subclass_declarations"]
        amp_orphans = [
            o for o in orphans if "AminoacidsAndPeptide" in o["missing_parent"]
        ]
        assert (
            len(amp_orphans) == 3
        ), f"Expected 3 orphans referencing AminoacidsAndPeptide, got {len(amp_orphans)}"

        amp_classes = {o["class"] for o in amp_orphans}
        assert any(
            "Aminoacid" in c and "Peptide" not in c for c in amp_classes
        ), "Missing Aminoacid in orphans"
        assert any(
            "Peptide" in c and "Aminoacid" not in c for c in amp_classes
        ), "Missing Peptide in orphans"
        # The third is Beta-Lactam (with Greek capital beta character)
        assert len(amp_classes) == 3

    def test_tanins_orphan(self, analysis):
        """HydrolysableTannin references non-existent 'Tanins'."""
        orphans = analysis["orphan_subclass_declarations"]
        tanins_orphans = [o for o in orphans if "Tanins" in o["missing_parent"]]
        assert len(tanins_orphans) == 1
        assert "HydrolysableTannin" in tanins_orphans[0]["class"]

    def test_alkaloids_orphan(self, analysis):
        """QuinolizidineAlkaloid references 'Alkaloids' (should be 'Alkaloid')."""
        orphans = analysis["orphan_subclass_declarations"]
        alk_orphans = [
            o
            for o in orphans
            if o["missing_parent"].endswith("Alkaloids")
            or o["missing_parent"].endswith("/Alkaloids")
        ]
        assert len(alk_orphans) == 1
        assert "QuinolizidineAlkaloid" in alk_orphans[0]["class"]

    def test_sorted_by_class_uri(self, analysis):
        orphans = analysis["orphan_subclass_declarations"]
        uris = [o["class"] for o in orphans]
        assert uris == sorted(uris), "Orphan declarations should be sorted by class URI"


class TestMaxHierarchyDepth:
    def test_depth(self, analysis):
        assert (
            analysis["max_hierarchy_depth"] == 4
        ), f"Expected max depth 4, got {analysis['max_hierarchy_depth']}"


class TestLipinskiMismatches:
    def test_count(self, analysis):
        mismatches = analysis["lipinski_mismatches"]
        assert (
            len(mismatches) == 6
        ), f"Expected 6 Lipinski mismatches, got {len(mismatches)}"

    def test_compound_ids(self, analysis):
        mismatches = analysis["lipinski_mismatches"]
        found_ids = {m["compound_id"] for m in mismatches}
        expected_ids = {11, 13, 20, 21, 26, 29}
        assert (
            found_ids == expected_ids
        ), f"Expected compound IDs {expected_ids}, got {found_ids}"

    def test_compound_11(self, analysis):
        """Compound 11: HBD=7>5, HBA=11>10 -> 2 violations, stated=1."""
        m = next(m for m in analysis["lipinski_mismatches"] if m["compound_id"] == 11)
        assert m["stated"] == 1
        assert m["computed"] == 2

    def test_compound_13(self, analysis):
        """Compound 13: all within limits -> 0 violations, stated=1."""
        m = next(m for m in analysis["lipinski_mismatches"] if m["compound_id"] == 13)
        assert m["stated"] == 1
        assert m["computed"] == 0

    def test_compound_20(self, analysis):
        """Compound 20: MW=520.5>500 -> 1 violation, stated=0."""
        m = next(m for m in analysis["lipinski_mismatches"] if m["compound_id"] == 20)
        assert m["stated"] == 0
        assert m["computed"] == 1

    def test_compound_21(self, analysis):
        """Compound 21: MW>500, cLogP>5, HBD>5, HBA>10 -> 4 violations, stated=3."""
        m = next(m for m in analysis["lipinski_mismatches"] if m["compound_id"] == 21)
        assert m["stated"] == 3
        assert m["computed"] == 4

    def test_compound_26(self, analysis):
        """Compound 26: all within limits -> 0 violations, stated=1."""
        m = next(m for m in analysis["lipinski_mismatches"] if m["compound_id"] == 26)
        assert m["stated"] == 1
        assert m["computed"] == 0

    def test_compound_29(self, analysis):
        """Compound 29: HBD=6>5, HBA=11>10 -> 2 violations, stated=1."""
        m = next(m for m in analysis["lipinski_mismatches"] if m["compound_id"] == 29)
        assert m["stated"] == 1
        assert m["computed"] == 2

    def test_sorted_by_compound_id(self, analysis):
        mismatches = analysis["lipinski_mismatches"]
        ids = [m["compound_id"] for m in mismatches]
        assert ids == sorted(ids), "Lipinski mismatches should be sorted by compound_id"


class TestDeepwalkMetrics:
    def test_hits_at_1(self, analysis):
        assert abs(analysis["deepwalk_metrics"]["hits_at_1"] - 0.35) < 0.001

    def test_hits_at_5(self, analysis):
        assert abs(analysis["deepwalk_metrics"]["hits_at_5"] - 0.70) < 0.001

    def test_hits_at_10(self, analysis):
        assert abs(analysis["deepwalk_metrics"]["hits_at_10"] - 0.90) < 0.001

    def test_mrr(self, analysis):
        # MRR = 24853/50400 = 0.49311507936...
        assert abs(analysis["deepwalk_metrics"]["mrr"] - 0.49311508) < 0.001


class TestNode2vecMetrics:
    def test_hits_at_1(self, analysis):
        assert abs(analysis["node2vec_metrics"]["hits_at_1"] - 0.45) < 0.001

    def test_hits_at_5(self, analysis):
        assert abs(analysis["node2vec_metrics"]["hits_at_5"] - 0.80) < 0.001

    def test_hits_at_10(self, analysis):
        assert abs(analysis["node2vec_metrics"]["hits_at_10"] - 0.95) < 0.001

    def test_mrr(self, analysis):
        # MRR = 5051/8400 = 0.60130952380...
        assert abs(analysis["node2vec_metrics"]["mrr"] - 0.60130952) < 0.001
