
"""
Tests for virtual screening pipeline output.
Independently verifies each pipeline stage against the raw input data.
"""

import json
import os
import csv
import pytest
from rdkit import Chem
from rdkit.Chem import Descriptors, Crippen, FilterCatalog, AllChem, DataStructs


REPORT_PATH = "/app/output/report.json"
TRAINING_CSV = "/app/data/training_set.csv"
LIBRARY_CSV = "/app/data/screening_library.csv"


def load_report():
    with open(REPORT_PATH) as f:
        return json.load(f)


def get_valid_unique_mols(csv_path, smiles_col="smiles"):
    """Load CSV, parse SMILES, return (dict canonical->mol, total_rows, valid_count)."""
    mols = {}
    total = 0
    valid = 0
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            smi = row[smiles_col].strip()
            if not smi:
                continue
            mol = Chem.MolFromSmiles(smi)
            if mol is not None:
                valid += 1
                can = Chem.MolToSmiles(mol)
                if can not in mols:
                    mols[can] = mol
    return mols, total, valid


def apply_full_cascade(mols_dict):
    """Apply the full Lipinski->Veber->PAINS->Brenk cascade independently."""
    items = list(mols_dict.values())

    lipinski = [m for m in items if (
        Descriptors.MolWt(m) <= 500 and
        Crippen.MolLogP(m) <= 5 and
        Descriptors.NumHDonors(m) <= 5 and
        Descriptors.NumHAcceptors(m) <= 10
    )]

    veber = [m for m in lipinski if (
        Descriptors.TPSA(m) <= 140 and
        Descriptors.NumRotatableBonds(m) <= 10
    )]

    pains_params = FilterCatalog.FilterCatalogParams()
    pains_params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)
    pains_catalog = FilterCatalog.FilterCatalog(pains_params)
    pains_pass = [m for m in veber if pains_catalog.GetFirstMatch(m) is None]

    brenk_params = FilterCatalog.FilterCatalogParams()
    brenk_params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.BRENK)
    brenk_catalog = FilterCatalog.FilterCatalog(brenk_params)
    brenk_pass = [m for m in pains_pass if brenk_catalog.GetFirstMatch(m) is None]

    return {
        "input": len(items),
        "after_lipinski": len(lipinski),
        "after_veber": len(veber),
        "after_pains": len(pains_pass),
        "after_brenk": len(brenk_pass),
    }


# ============================================================
# Report existence and structure
# ============================================================

class TestReportExists:
    def test_report_file_exists(self):
        assert os.path.isfile(REPORT_PATH), f"{REPORT_PATH} not found"

    def test_report_is_valid_json(self):
        report = load_report()
        assert isinstance(report, dict)


class TestReportStructure:
    def test_top_level_keys(self):
        report = load_report()
        required = {"validation", "cascade_filter", "qsar_model",
                     "applicability_domain", "clustering", "selected_candidates"}
        missing = required - set(report.keys())
        assert not missing, f"Missing top-level keys: {missing}"

    def test_validation_keys(self):
        v = load_report()["validation"]
        for k in ["training_total", "training_valid", "library_total",
                   "library_valid", "library_unique"]:
            assert k in v, f"Missing validation.{k}"

    def test_cascade_filter_keys(self):
        cf = load_report()["cascade_filter"]
        for k in ["input", "after_lipinski", "after_veber", "after_pains", "after_brenk"]:
            assert k in cf, f"Missing cascade_filter.{k}"

    def test_qsar_model_keys(self):
        qm = load_report()["qsar_model"]
        for k in ["n_train", "n_test", "r2_test", "rmse_test"]:
            assert k in qm, f"Missing qsar_model.{k}"

    def test_applicability_domain_keys(self):
        ad = load_report()["applicability_domain"]
        for k in ["ad_threshold", "n_in_ad", "n_out_ad"]:
            assert k in ad, f"Missing applicability_domain.{k}"

    def test_clustering_keys(self):
        cl = load_report()["clustering"]
        for k in ["n_clusters", "cluster_sizes"]:
            assert k in cl, f"Missing clustering.{k}"

    def test_selected_candidates_is_list(self):
        sc = load_report()["selected_candidates"]
        assert isinstance(sc, list)

    def test_candidate_keys(self):
        sc = load_report()["selected_candidates"]
        if len(sc) == 0:
            pytest.skip("No selected candidates")
        cand = sc[0]
        for k in ["smiles", "predicted_pIC50", "qed", "composite_score",
                   "cluster_id", "in_ad"]:
            assert k in cand, f"Missing candidate field: {k}"


# ============================================================
# Validation counts
# ============================================================

class TestValidation:
    def test_training_total(self):
        report = load_report()
        _, total, _ = get_valid_unique_mols(TRAINING_CSV)
        assert report["validation"]["training_total"] == total

    def test_training_valid(self):
        report = load_report()
        _, _, valid = get_valid_unique_mols(TRAINING_CSV)
        assert report["validation"]["training_valid"] == valid

    def test_library_total(self):
        report = load_report()
        _, total, _ = get_valid_unique_mols(LIBRARY_CSV)
        assert report["validation"]["library_total"] == total

    def test_library_valid(self):
        report = load_report()
        _, _, valid = get_valid_unique_mols(LIBRARY_CSV)
        assert report["validation"]["library_valid"] == valid

    def test_library_unique(self):
        report = load_report()
        mols, _, _ = get_valid_unique_mols(LIBRARY_CSV)
        assert report["validation"]["library_unique"] == len(mols)


# ============================================================
# Cascade filter counts
# ============================================================

class TestCascadeFilters:
    def test_cascade_input_equals_unique(self):
        report = load_report()
        assert report["cascade_filter"]["input"] == report["validation"]["library_unique"]

    def test_lipinski_count(self):
        report = load_report()
        mols, _, _ = get_valid_unique_mols(LIBRARY_CSV)
        expected = apply_full_cascade(mols)
        assert report["cascade_filter"]["after_lipinski"] == expected["after_lipinski"]

    def test_veber_count(self):
        report = load_report()
        mols, _, _ = get_valid_unique_mols(LIBRARY_CSV)
        expected = apply_full_cascade(mols)
        assert report["cascade_filter"]["after_veber"] == expected["after_veber"]

    def test_pains_count(self):
        report = load_report()
        mols, _, _ = get_valid_unique_mols(LIBRARY_CSV)
        expected = apply_full_cascade(mols)
        assert report["cascade_filter"]["after_pains"] == expected["after_pains"]

    def test_brenk_count(self):
        report = load_report()
        mols, _, _ = get_valid_unique_mols(LIBRARY_CSV)
        expected = apply_full_cascade(mols)
        assert report["cascade_filter"]["after_brenk"] == expected["after_brenk"]

    def test_cascade_monotonic_decrease(self):
        cf = load_report()["cascade_filter"]
        assert cf["input"] >= cf["after_lipinski"] >= cf["after_veber"] >= \
               cf["after_pains"] >= cf["after_brenk"] >= 0


# ============================================================
# QSAR model
# ============================================================

class TestQSARModel:
    def test_split_sizes_sum(self):
        report = load_report()
        qm = report["qsar_model"]
        assert qm["n_train"] > 0
        assert qm["n_test"] > 0
        assert qm["n_train"] + qm["n_test"] == report["validation"]["training_valid"]

    def test_r2_is_numeric(self):
        qm = load_report()["qsar_model"]
        assert isinstance(qm["r2_test"], (int, float))
        assert qm["r2_test"] == qm["r2_test"]  # not NaN

    def test_r2_reasonable(self):
        qm = load_report()["qsar_model"]
        assert qm["r2_test"] > -5.0, "R² is unreasonably low"

    def test_rmse_positive(self):
        qm = load_report()["qsar_model"]
        assert isinstance(qm["rmse_test"], (int, float))
        assert qm["rmse_test"] > 0
        assert qm["rmse_test"] < 10.0, "RMSE is unreasonably high for pIC50 data"


# ============================================================
# Applicability domain
# ============================================================

class TestApplicabilityDomain:
    def test_ad_threshold_positive(self):
        ad = load_report()["applicability_domain"]
        assert ad["ad_threshold"] > 0
        assert ad["ad_threshold"] < 1.0, "AD threshold should be a Tanimoto distance < 1"

    def test_ad_counts_sum_to_filtered(self):
        report = load_report()
        ad = report["applicability_domain"]
        cf = report["cascade_filter"]
        assert ad["n_in_ad"] + ad["n_out_ad"] == cf["after_brenk"]

    def test_ad_counts_nonnegative(self):
        ad = load_report()["applicability_domain"]
        assert ad["n_in_ad"] >= 0
        assert ad["n_out_ad"] >= 0


# ============================================================
# Clustering
# ============================================================

class TestClustering:
    def test_cluster_sizes_sum_to_in_ad(self):
        report = load_report()
        cl = report["clustering"]
        ad = report["applicability_domain"]
        assert sum(cl["cluster_sizes"]) == ad["n_in_ad"]

    def test_n_clusters_matches_sizes_length(self):
        cl = load_report()["clustering"]
        assert cl["n_clusters"] == len(cl["cluster_sizes"])

    def test_cluster_sizes_positive(self):
        cl = load_report()["clustering"]
        for size in cl["cluster_sizes"]:
            assert size > 0


# ============================================================
# Selected candidates
# ============================================================

class TestSelectedCandidates:
    def test_one_per_cluster(self):
        report = load_report()
        sc = report["selected_candidates"]
        cl = report["clustering"]
        assert len(sc) == cl["n_clusters"]

    def test_all_smiles_valid(self):
        sc = load_report()["selected_candidates"]
        for cand in sc:
            mol = Chem.MolFromSmiles(cand["smiles"])
            assert mol is not None, f"Invalid SMILES in output: {cand['smiles']}"

    def test_qed_values_correct(self):
        """Independently verify QED for each selected molecule."""
        sc = load_report()["selected_candidates"]
        for cand in sc:
            mol = Chem.MolFromSmiles(cand["smiles"])
            expected_qed = round(Descriptors.qed(mol), 4)
            assert abs(cand["qed"] - expected_qed) < 0.02, \
                f"QED mismatch for {cand['smiles']}: got {cand['qed']}, expected {expected_qed}"

    def test_all_in_ad(self):
        sc = load_report()["selected_candidates"]
        for cand in sc:
            assert cand["in_ad"] is True, \
                f"Selected candidate {cand['smiles']} should be in-AD"

    def test_composite_score_range(self):
        sc = load_report()["selected_candidates"]
        for cand in sc:
            assert 0.0 <= cand["composite_score"] <= 1.0, \
                f"Composite score out of [0,1] range: {cand['composite_score']}"

    def test_composite_score_formula(self):
        """Verify composite score = 0.6 * norm_pIC50 + 0.4 * QED."""
        sc = load_report()["selected_candidates"]
        if len(sc) < 2:
            pytest.skip("Need at least 2 candidates to verify normalization")
        preds = [c["predicted_pIC50"] for c in sc]
        min_p, max_p = min(preds), max(preds)
        for cand in sc:
            if max_p > min_p:
                norm_p = (cand["predicted_pIC50"] - min_p) / (max_p - min_p)
            else:
                norm_p = 1.0
            expected = round(0.6 * norm_p + 0.4 * cand["qed"], 4)
            assert abs(cand["composite_score"] - expected) < 0.02, \
                f"Composite score mismatch: got {cand['composite_score']}, expected {expected}"

    def test_unique_cluster_ids(self):
        """Each selected candidate should come from a different cluster."""
        sc = load_report()["selected_candidates"]
        cluster_ids = [c["cluster_id"] for c in sc]
        assert len(set(cluster_ids)) == len(cluster_ids), \
            "Duplicate cluster_ids in selected candidates"

    def test_predicted_pIC50_reasonable(self):
        """Predicted pIC50 values should be in a reasonable range."""
        sc = load_report()["selected_candidates"]
        for cand in sc:
            assert 0.0 < cand["predicted_pIC50"] < 15.0, \
                f"Unreasonable pIC50 prediction: {cand['predicted_pIC50']}"
