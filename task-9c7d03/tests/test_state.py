"""Tests for virtual screening pipeline output."""

import json
import csv
import pytest
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, Descriptors, Crippen, FilterCatalog, DataStructs


@pytest.fixture
def report():
    with open('/app/report.json') as f:
        return json.load(f)


@pytest.fixture
def training_fps():
    """Compute fingerprints for all valid training molecules."""
    fps = []
    with open('/app/training_data.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            mol = Chem.MolFromSmiles(row['smiles'])
            if mol is not None:
                fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)
                fps.append(fp)
    return fps


class TestReportStructure:
    def test_report_exists_and_valid_json(self, report):
        assert isinstance(report, dict)

    def test_model_performance_keys(self, report):
        mp = report['model_performance']
        for key in ['r_squared', 'rmse', 'n_train', 'n_test']:
            assert key in mp, f"Missing key: {key}"

    def test_pipeline_summary_keys(self, report):
        ps = report['pipeline_summary']
        required = [
            'n_screening', 'n_valid', 'n_active',
            'n_after_lipinski', 'n_after_veber',
            'n_after_pains', 'n_after_brenk',
            'n_in_ad', 'n_clusters', 'n_selected',
        ]
        for key in required:
            assert key in ps, f"Missing key: {key}"

    def test_selected_leads_keys(self, report):
        leads = report['selected_leads']
        assert isinstance(leads, list)
        assert len(leads) > 0, "No leads selected"
        for lead in leads:
            for key in ['smiles', 'predicted_pIC50', 'MW', 'LogP',
                        'TPSA', 'QED', 'cluster_id']:
                assert key in lead, f"Missing key in lead: {key}"


class TestPipelineConsistency:
    def test_monotonic_counts(self, report):
        ps = report['pipeline_summary']
        assert ps['n_valid'] <= ps['n_screening']
        assert ps['n_active'] <= ps['n_valid']
        assert ps['n_after_lipinski'] <= ps['n_active']
        assert ps['n_after_veber'] <= ps['n_after_lipinski']
        assert ps['n_after_pains'] <= ps['n_after_veber']
        assert ps['n_after_brenk'] <= ps['n_after_pains']
        assert ps['n_in_ad'] <= ps['n_after_brenk']
        assert ps['n_selected'] <= ps['n_in_ad']

    def test_n_selected_equals_n_clusters(self, report):
        ps = report['pipeline_summary']
        assert ps['n_selected'] == ps['n_clusters']

    def test_n_screening_matches_input(self, report):
        with open('/app/screening_library.csv') as f:
            reader = csv.DictReader(f)
            n = sum(1 for _ in reader)
        assert report['pipeline_summary']['n_screening'] == n

    def test_n_selected_matches_leads_list(self, report):
        assert report['pipeline_summary']['n_selected'] == len(report['selected_leads'])


class TestModelMetrics:
    def test_r_squared_range(self, report):
        r2 = report['model_performance']['r_squared']
        assert -2.0 <= r2 <= 1.0, f"R² = {r2} outside plausible range"

    def test_rmse_positive(self, report):
        assert report['model_performance']['rmse'] > 0

    def test_split_proportions(self, report):
        mp = report['model_performance']
        total = mp['n_train'] + mp['n_test']
        assert total > 0
        train_frac = mp['n_train'] / total
        assert 0.6 <= train_frac <= 0.95, \
            f"Train fraction {train_frac:.2f} outside expected range [0.6, 0.95]"

    def test_n_test_nonzero(self, report):
        assert report['model_performance']['n_test'] > 0, \
            "Test set is empty — scaffold split likely incorrect"


class TestSelectedLeads:
    def test_smiles_valid(self, report):
        for lead in report['selected_leads']:
            mol = Chem.MolFromSmiles(lead['smiles'])
            assert mol is not None, f"Invalid SMILES: {lead['smiles']}"

    def test_predicted_activity_threshold(self, report):
        for lead in report['selected_leads']:
            assert lead['predicted_pIC50'] >= 5.0 - 1e-4, \
                f"predicted_pIC50 {lead['predicted_pIC50']} below threshold for {lead['smiles']}"

    def test_cluster_ids_unique(self, report):
        cluster_ids = [lead['cluster_id'] for lead in report['selected_leads']]
        assert len(cluster_ids) == len(set(cluster_ids)), \
            "Duplicate cluster IDs in selected leads"

    def test_descriptor_accuracy_mw(self, report):
        for lead in report['selected_leads']:
            mol = Chem.MolFromSmiles(lead['smiles'])
            assert mol is not None
            mw = Descriptors.MolWt(mol)
            assert abs(lead['MW'] - mw) < 0.5, \
                f"MW mismatch for {lead['smiles']}: reported {lead['MW']}, computed {mw:.2f}"

    def test_descriptor_accuracy_logp(self, report):
        for lead in report['selected_leads']:
            mol = Chem.MolFromSmiles(lead['smiles'])
            assert mol is not None
            logp = Crippen.MolLogP(mol)
            assert abs(lead['LogP'] - logp) < 0.05, \
                f"LogP mismatch for {lead['smiles']}: reported {lead['LogP']}, computed {logp:.4f}"

    def test_descriptor_accuracy_tpsa(self, report):
        for lead in report['selected_leads']:
            mol = Chem.MolFromSmiles(lead['smiles'])
            assert mol is not None
            tpsa = Descriptors.TPSA(mol)
            assert abs(lead['TPSA'] - tpsa) < 0.5, \
                f"TPSA mismatch for {lead['smiles']}: reported {lead['TPSA']}, computed {tpsa:.2f}"

    def test_descriptor_accuracy_qed(self, report):
        for lead in report['selected_leads']:
            mol = Chem.MolFromSmiles(lead['smiles'])
            assert mol is not None
            qed = Descriptors.qed(mol)
            assert abs(lead['QED'] - qed) < 0.01, \
                f"QED mismatch for {lead['smiles']}: reported {lead['QED']}, computed {qed:.4f}"


class TestADMETCompliance:
    def test_lipinski(self, report):
        for lead in report['selected_leads']:
            mol = Chem.MolFromSmiles(lead['smiles'])
            assert mol is not None
            assert Descriptors.MolWt(mol) <= 500, \
                f"Lipinski MW fail: {lead['smiles']}"
            assert Crippen.MolLogP(mol) <= 5, \
                f"Lipinski LogP fail: {lead['smiles']}"
            assert Descriptors.NumHDonors(mol) <= 5, \
                f"Lipinski HBD fail: {lead['smiles']}"
            assert Descriptors.NumHAcceptors(mol) <= 10, \
                f"Lipinski HBA fail: {lead['smiles']}"

    def test_veber(self, report):
        for lead in report['selected_leads']:
            mol = Chem.MolFromSmiles(lead['smiles'])
            assert mol is not None
            assert Descriptors.TPSA(mol) <= 140, \
                f"Veber TPSA fail: {lead['smiles']}"
            assert Descriptors.NumRotatableBonds(mol) <= 10, \
                f"Veber RotBonds fail: {lead['smiles']}"

    def test_pains(self, report):
        pains_params = FilterCatalog.FilterCatalogParams()
        pains_params.AddCatalog(
            FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)
        pains_catalog = FilterCatalog.FilterCatalog(pains_params)

        for lead in report['selected_leads']:
            mol = Chem.MolFromSmiles(lead['smiles'])
            assert mol is not None
            assert pains_catalog.GetFirstMatch(mol) is None, \
                f"PAINS alert for: {lead['smiles']}"

    def test_brenk(self, report):
        brenk_params = FilterCatalog.FilterCatalogParams()
        brenk_params.AddCatalog(
            FilterCatalog.FilterCatalogParams.FilterCatalogs.BRENK)
        brenk_catalog = FilterCatalog.FilterCatalog(brenk_params)

        for lead in report['selected_leads']:
            mol = Chem.MolFromSmiles(lead['smiles'])
            assert mol is not None
            assert brenk_catalog.GetFirstMatch(mol) is None, \
                f"Brenk alert for: {lead['smiles']}"


class TestApplicabilityDomain:
    def test_leads_within_ad(self, report, training_fps):
        # Compute training nearest-neighbor distances
        nn_dists = []
        for i, fp in enumerate(training_fps):
            min_dist = min(
                1.0 - DataStructs.TanimotoSimilarity(fp, training_fps[j])
                for j in range(len(training_fps)) if j != i
            )
            nn_dists.append(min_dist)

        threshold = float(np.percentile(nn_dists, 95))

        for lead in report['selected_leads']:
            mol = Chem.MolFromSmiles(lead['smiles'])
            assert mol is not None
            fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)
            min_dist = min(
                1.0 - DataStructs.TanimotoSimilarity(fp, tfp)
                for tfp in training_fps
            )
            assert min_dist <= threshold + 1e-6, \
                f"Outside AD: {lead['smiles']}, dist={min_dist:.4f}, threshold={threshold:.4f}"
