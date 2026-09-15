"""

Tests for SAR landscape analysis pipeline.
Independently reads raw project data, applies the cleaning pipeline,
computes all expected results, and verifies agent output.
"""
import json
import os

import numpy as np
import pandas as pd
import pytest
import yaml
from rdkit import Chem
from rdkit.Chem import AllChem, DataStructs
from rdkit.Chem.Scaffolds import MurckoScaffold

PROJECT_DIR = "/app/project"
RESULTS_DIR = "/app/results"


@pytest.fixture(scope="module")
def config():
    """Read pipeline configuration."""
    with open(os.path.join(PROJECT_DIR, "config", "pipeline.yaml")) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def clean_data(config):
    """
    Independently clean raw data following the project configuration.
    This mirrors the cleaning pipeline the agent should implement.
    """
    # Read structures
    structures = pd.read_csv(
        os.path.join(PROJECT_DIR, "data", "structures.csv")
    )

    # Read bioactivity (TSV format)
    bioactivity = pd.read_csv(
        os.path.join(PROJECT_DIR, "data", "bioactivity.tsv"), sep="\t"
    )

    # Read exclusions
    with open(os.path.join(PROJECT_DIR, "data", "exclusions.json")) as f:
        exclusions = json.load(f)
    excluded_ids = set(exclusions["excluded_compounds"])

    # Remove excluded compounds
    structures = structures[~structures["compound_id"].isin(excluded_ids)].copy()
    bioactivity = bioactivity[~bioactivity["compound_id"].isin(excluded_ids)].copy()

    # Validate SMILES — keep only parseable structures
    valid_rows = []
    for _, row in structures.iterrows():
        mol = Chem.MolFromSmiles(row["smiles"])
        if mol is not None:
            valid_rows.append(row)
    structures = pd.DataFrame(valid_rows)

    # Average duplicate bioactivity measurements
    bioactivity_agg = (
        bioactivity.groupby("compound_id")["pIC50"].mean().reset_index()
    )

    # Inner join: require both valid structure and bioactivity
    merged = pd.merge(structures, bioactivity_agg, on="compound_id")
    merged = merged.sort_values("compound_id").reset_index(drop=True)

    return merged


@pytest.fixture(scope="module")
def expected(clean_data, config):
    """Independently compute all expected analysis results from cleaned data."""
    df = clean_data
    n = len(df)

    # Parse SMILES and canonicalize
    mols = []
    canonical_smiles_list = []
    for _, row in df.iterrows():
        mol = Chem.MolFromSmiles(row["smiles"])
        assert mol is not None, f"Failed to parse SMILES: {row['smiles']}"
        mols.append(mol)
        canonical_smiles_list.append(Chem.MolToSmiles(mol))

    # Morgan fingerprints
    fp_cfg = config["molecular_representation"]
    radius = fp_cfg["radius"]
    n_bits = fp_cfg["num_bits"]
    fps = [
        AllChem.GetMorganFingerprintAsBitVect(m, radius, nBits=n_bits)
        for m in mols
    ]

    # Tanimoto similarity matrix
    sim_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            sim_matrix[i][j] = DataStructs.TanimotoSimilarity(fps[i], fps[j])

    # Activity cliffs and SALI
    cliff_cfg = config["pairwise_analysis"]["cliff_detection"]
    min_sim = cliff_cfg["min_similarity"]
    min_delta = cliff_cfg["min_activity_difference"]

    cliffs = []
    cliff_scores = {row["compound_id"]: 0.0 for _, row in df.iterrows()}
    max_sali = 0.0

    for i in range(n):
        for j in range(i + 1, n):
            sim = sim_matrix[i][j]
            delta = abs(df.iloc[i]["pIC50"] - df.iloc[j]["pIC50"])
            if sim >= min_sim and delta >= min_delta:
                if sim < 1.0:
                    sali = delta / (1.0 - sim)
                    cliff_scores[df.iloc[i]["compound_id"]] += sali
                    cliff_scores[df.iloc[j]["compound_id"]] += sali
                    max_sali = max(max_sali, sali)
                else:
                    sali = float("inf")

                cpd1 = df.iloc[i]["compound_id"]
                cpd2 = df.iloc[j]["compound_id"]
                if cpd1 > cpd2:
                    cpd1, cpd2 = cpd2, cpd1

                cliffs.append(
                    {
                        "cpd1": cpd1,
                        "cpd2": cpd2,
                        "similarity": sim,
                        "delta_pIC50": delta,
                        "sali_score": sali,
                    }
                )

    median_cliff_score = float(np.median(list(cliff_scores.values())))
    n_generators = sum(1 for v in cliff_scores.values() if v > median_cliff_score)

    # Murcko scaffolds
    scaffolds = {}
    for i, mol in enumerate(mols):
        scaf_mol = MurckoScaffold.GetScaffoldForMol(mol)
        if scaf_mol.GetNumAtoms() > 0:
            scaf_smiles = Chem.MolToSmiles(scaf_mol)
        else:
            scaf_smiles = ""
        scaffolds[df.iloc[i]["compound_id"]] = scaf_smiles

    # Scaffold groups
    scaffold_groups = {}
    for cpd_id, scaf in scaffolds.items():
        if scaf not in scaffold_groups:
            scaffold_groups[scaf] = []
        scaffold_groups[scaf].append(cpd_id)

    return {
        "n": n,
        "canonical_smiles": canonical_smiles_list,
        "sim_matrix": sim_matrix,
        "cliffs": cliffs,
        "scaffolds": scaffolds,
        "scaffold_groups": scaffold_groups,
        "cliff_scores": cliff_scores,
        "median_cliff_score": median_cliff_score,
        "n_generators": n_generators,
        "n_unique_scaffolds": len(scaffold_groups),
        "max_sali": max_sali,
        "df": df,
    }


# ---------------------------------------------------------------------------
# File existence tests
# ---------------------------------------------------------------------------
class TestFileExistence:
    @pytest.mark.parametrize(
        "filename",
        [
            "tanimoto_matrix.csv",
            "activity_cliffs.csv",
            "scaffolds.csv",
            "scaffold_stats.csv",
            "summary.json",
        ],
    )
    def test_file_exists(self, filename):
        path = os.path.join(RESULTS_DIR, filename)
        assert os.path.exists(path), f"Missing output file: {filename}"


# ---------------------------------------------------------------------------
# Data cleaning verification
# ---------------------------------------------------------------------------
class TestDataCleaning:
    def test_compound_count(self, expected):
        """Verify the correct number of compounds survived cleaning."""
        assert expected["n"] == 25, (
            f"After cleaning, expected 25 compounds but got {expected['n']}"
        )

    def test_no_excluded_compounds(self, expected):
        """Excluded compounds must not appear in outputs."""
        with open(os.path.join(PROJECT_DIR, "data", "exclusions.json")) as f:
            exclusions = json.load(f)
        excluded_ids = set(exclusions["excluded_compounds"])

        if os.path.exists(os.path.join(RESULTS_DIR, "scaffolds.csv")):
            scaffolds_df = pd.read_csv(
                os.path.join(RESULTS_DIR, "scaffolds.csv"), keep_default_na=False
            )
            found = set(scaffolds_df["compound_id"]) & excluded_ids
            assert len(found) == 0, f"Excluded compounds found in output: {found}"

    def test_no_invalid_smiles_compounds(self, expected):
        """Compounds with unparseable SMILES must not appear in outputs."""
        if os.path.exists(os.path.join(RESULTS_DIR, "scaffolds.csv")):
            scaffolds_df = pd.read_csv(
                os.path.join(RESULTS_DIR, "scaffolds.csv"), keep_default_na=False
            )
            for _, row in scaffolds_df.iterrows():
                mol = Chem.MolFromSmiles(row["canonical_smiles"])
                assert mol is not None, (
                    f"Invalid SMILES in output for {row['compound_id']}: "
                    f"{row['canonical_smiles']}"
                )


# ---------------------------------------------------------------------------
# Tanimoto matrix tests
# ---------------------------------------------------------------------------
class TestTanimotoMatrix:
    def test_dimensions(self, expected):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "tanimoto_matrix.csv"), index_col=0
        )
        n = expected["n"]
        assert df.shape == (n, n), f"Expected {n}x{n} matrix, got {df.shape}"

    def test_symmetry(self):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "tanimoto_matrix.csv"), index_col=0
        )
        matrix = df.values.astype(float)
        np.testing.assert_allclose(
            matrix,
            matrix.T,
            atol=1e-5,
            err_msg="Similarity matrix must be symmetric",
        )

    def test_diagonal_ones(self, expected):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "tanimoto_matrix.csv"), index_col=0
        )
        matrix = df.values.astype(float)
        np.testing.assert_allclose(
            np.diag(matrix),
            np.ones(expected["n"]),
            atol=1e-5,
            err_msg="Diagonal entries must be 1.0",
        )

    def test_values_range(self):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "tanimoto_matrix.csv"), index_col=0
        )
        matrix = df.values.astype(float)
        assert np.all(matrix >= -1e-6), "All values must be >= 0"
        assert np.all(matrix <= 1.0 + 1e-6), "All values must be <= 1"

    def test_values_match_expected(self, expected):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "tanimoto_matrix.csv"), index_col=0
        )
        matrix = df.values.astype(float)
        np.testing.assert_allclose(
            matrix,
            expected["sim_matrix"],
            atol=1e-4,
            err_msg="Tanimoto similarity values don't match expected",
        )


# ---------------------------------------------------------------------------
# Activity cliff tests
# ---------------------------------------------------------------------------
class TestActivityCliffs:
    def test_columns(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "activity_cliffs.csv"))
        required = {"cpd1", "cpd2", "similarity", "delta_pIC50", "sali_score"}
        assert required.issubset(
            set(df.columns)
        ), f"Missing columns: {required - set(df.columns)}"

    def test_count(self, expected):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "activity_cliffs.csv"))
        assert len(df) == len(
            expected["cliffs"]
        ), f"Expected {len(expected['cliffs'])} cliffs, got {len(df)}"

    def test_criteria_met(self, config):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "activity_cliffs.csv"))
        cliff_cfg = config["pairwise_analysis"]["cliff_detection"]
        min_sim = cliff_cfg["min_similarity"]
        min_delta = cliff_cfg["min_activity_difference"]
        for _, row in df.iterrows():
            assert row["similarity"] >= min_sim - 1e-6, (
                f"Cliff {row['cpd1']}-{row['cpd2']}: "
                f"similarity {row['similarity']} < {min_sim}"
            )
            assert row["delta_pIC50"] >= min_delta - 1e-6, (
                f"Cliff {row['cpd1']}-{row['cpd2']}: "
                f"delta_pIC50 {row['delta_pIC50']} < {min_delta}"
            )

    def test_sali_consistency(self):
        """Verify SALI = delta_pIC50 / (1 - similarity)."""
        df = pd.read_csv(os.path.join(RESULTS_DIR, "activity_cliffs.csv"))
        for _, row in df.iterrows():
            reconstructed = row["sali_score"] * (1.0 - row["similarity"])
            np.testing.assert_allclose(
                reconstructed,
                row["delta_pIC50"],
                atol=1e-3,
                err_msg=f"SALI inconsistency for {row['cpd1']}-{row['cpd2']}",
            )

    def test_ordering(self):
        df = pd.read_csv(os.path.join(RESULTS_DIR, "activity_cliffs.csv"))
        for _, row in df.iterrows():
            assert str(row["cpd1"]) < str(row["cpd2"]), (
                f"Pairs must be ordered: {row['cpd1']} should be < {row['cpd2']}"
            )


# ---------------------------------------------------------------------------
# Scaffold tests
# ---------------------------------------------------------------------------
class TestScaffolds:
    def test_all_compounds_present(self, expected):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "scaffolds.csv"), keep_default_na=False
        )
        assert len(df) == expected["n"]
        expected_ids = set(expected["df"]["compound_id"])
        actual_ids = set(df["compound_id"])
        assert expected_ids == actual_ids, (
            f"Missing compounds: {expected_ids - actual_ids}"
        )

    def test_columns(self):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "scaffolds.csv"), keep_default_na=False
        )
        required = {"compound_id", "canonical_smiles", "murcko_scaffold"}
        assert required.issubset(set(df.columns)), (
            f"Missing columns: {required - set(df.columns)}"
        )

    def test_canonical_smiles_valid(self):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "scaffolds.csv"), keep_default_na=False
        )
        for _, row in df.iterrows():
            mol = Chem.MolFromSmiles(row["canonical_smiles"])
            assert mol is not None, (
                f"Invalid canonical SMILES for {row['compound_id']}: "
                f"{row['canonical_smiles']}"
            )

    def test_canonical_smiles_match(self, expected):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "scaffolds.csv"), keep_default_na=False
        )
        for _, row in df.iterrows():
            cpd_id = row["compound_id"]
            idx = list(expected["df"]["compound_id"]).index(cpd_id)
            exp_canonical = expected["canonical_smiles"][idx]
            assert row["canonical_smiles"] == exp_canonical, (
                f"Canonical SMILES mismatch for {cpd_id}: "
                f"got '{row['canonical_smiles']}', expected '{exp_canonical}'"
            )

    def test_scaffolds_match(self, expected):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "scaffolds.csv"), keep_default_na=False
        )
        for _, row in df.iterrows():
            cpd_id = row["compound_id"]
            exp_scaffold = expected["scaffolds"][cpd_id]
            actual_scaffold = row["murcko_scaffold"]
            assert actual_scaffold == exp_scaffold, (
                f"Scaffold mismatch for {cpd_id}: "
                f"got '{actual_scaffold}', expected '{exp_scaffold}'"
            )


# ---------------------------------------------------------------------------
# Scaffold stats tests
# ---------------------------------------------------------------------------
class TestScaffoldStats:
    def test_columns(self):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "scaffold_stats.csv"), keep_default_na=False
        )
        required = {"scaffold", "n_compounds", "mean_pIC50", "std_pIC50"}
        assert required.issubset(set(df.columns))

    def test_total_compounds_consistent(self, expected):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "scaffold_stats.csv"), keep_default_na=False
        )
        assert df["n_compounds"].sum() == expected["n"], (
            "Sum of n_compounds across scaffolds must equal total compounds"
        )

    def test_scaffold_count(self, expected):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "scaffold_stats.csv"), keep_default_na=False
        )
        assert len(df) == expected["n_unique_scaffolds"], (
            f"Expected {expected['n_unique_scaffolds']} scaffolds, got {len(df)}"
        )

    def test_stats_values(self, expected):
        df = pd.read_csv(
            os.path.join(RESULTS_DIR, "scaffold_stats.csv"), keep_default_na=False
        )
        compounds_df = expected["df"]
        for _, row in df.iterrows():
            scaf = row["scaffold"]
            if scaf in expected["scaffold_groups"]:
                cpd_ids = expected["scaffold_groups"][scaf]
                pIC50s = [
                    compounds_df[compounds_df["compound_id"] == cid][
                        "pIC50"
                    ].values[0]
                    for cid in cpd_ids
                ]
                assert row["n_compounds"] == len(cpd_ids), (
                    f"Scaffold '{scaf}': expected {len(cpd_ids)} compounds, "
                    f"got {row['n_compounds']}"
                )
                np.testing.assert_allclose(
                    row["mean_pIC50"], np.mean(pIC50s), atol=1e-3
                )
                if len(pIC50s) > 1:
                    np.testing.assert_allclose(
                        row["std_pIC50"], np.std(pIC50s, ddof=1), atol=1e-3
                    )
                else:
                    np.testing.assert_allclose(row["std_pIC50"], 0.0, atol=1e-6)


# ---------------------------------------------------------------------------
# Summary tests
# ---------------------------------------------------------------------------
class TestSummary:
    def test_keys_present(self):
        with open(os.path.join(RESULTS_DIR, "summary.json")) as f:
            summary = json.load(f)
        required_keys = {
            "n_compounds",
            "n_unique_scaffolds",
            "n_activity_cliffs",
            "n_cliff_generators",
            "max_sali",
            "median_cliff_score",
        }
        assert required_keys.issubset(set(summary.keys())), (
            f"Missing keys: {required_keys - set(summary.keys())}"
        )

    def test_n_compounds(self, expected):
        with open(os.path.join(RESULTS_DIR, "summary.json")) as f:
            summary = json.load(f)
        assert summary["n_compounds"] == expected["n"]

    def test_n_unique_scaffolds(self, expected):
        with open(os.path.join(RESULTS_DIR, "summary.json")) as f:
            summary = json.load(f)
        assert summary["n_unique_scaffolds"] == expected["n_unique_scaffolds"]

    def test_n_activity_cliffs(self, expected):
        with open(os.path.join(RESULTS_DIR, "summary.json")) as f:
            summary = json.load(f)
        assert summary["n_activity_cliffs"] == len(expected["cliffs"])

    def test_n_cliff_generators(self, expected):
        with open(os.path.join(RESULTS_DIR, "summary.json")) as f:
            summary = json.load(f)
        assert summary["n_cliff_generators"] == expected["n_generators"]

    def test_max_sali(self, expected):
        with open(os.path.join(RESULTS_DIR, "summary.json")) as f:
            summary = json.load(f)
        np.testing.assert_allclose(
            summary["max_sali"],
            round(expected["max_sali"], 4),
            atol=0.05,
        )

    def test_median_cliff_score(self, expected):
        with open(os.path.join(RESULTS_DIR, "summary.json")) as f:
            summary = json.load(f)
        np.testing.assert_allclose(
            summary["median_cliff_score"],
            round(expected["median_cliff_score"], 4),
            atol=0.05,
        )
