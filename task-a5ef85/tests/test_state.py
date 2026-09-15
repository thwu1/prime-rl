
import json
import os
import glob

import numpy as np
import pytest

import biotite.structure as struc
import biotite.structure.io as strucio

# The NMR ensemble is protein_x42.pdb (1L2Y), despite the misleading lab notes
NMR_PDB_PATH = "/app/data/protein_x42.pdb"
RESULTS_PATH = "/app/results.json"

RMSD_TOL = 0.05       # Angstroms
ANGLE_TOL = 0.05      # radians
FLEX_TOL = 0.05        # circular variance units


# ---------------------------------------------------------------------------
# Reference computation (independent of the agent's implementation)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def reference():
    """Compute ground-truth values using biotite."""
    stack = strucio.load_structure(NMR_PDB_PATH)
    n_models = stack.stack_depth()

    aa_mask = struc.filter_amino_acids(stack[0])
    ca_mask = aa_mask & (stack[0].atom_name == "CA")
    n_residues = int(np.sum(ca_mask))

    # --- RMSD matrix ---
    rmsd_matrix = np.zeros((n_models, n_models))
    for i in range(n_models):
        for j in range(i + 1, n_models):
            fixed = stack[i].coord[ca_mask]
            mobile = stack[j].coord[ca_mask]
            fitted, _ = struc.superimpose(fixed, mobile)
            rmsd = float(np.sqrt(np.mean(np.sum((fixed - fitted) ** 2, axis=-1))))
            rmsd_matrix[i, j] = rmsd
            rmsd_matrix[j, i] = rmsd

    # --- Backbone dihedrals ---
    phi, psi, _ = struc.dihedral_backbone(stack)

    # --- Sequence ---
    three_to_one = {
        "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
        "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
        "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
        "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    }
    res_names_3 = stack[0].res_name[ca_mask]
    sequence = "".join(three_to_one.get(r, "X") for r in res_names_3)

    return {
        "n_models": n_models,
        "n_residues": n_residues,
        "sequence": sequence,
        "rmsd_matrix": rmsd_matrix,
        "phi": phi,
        "psi": psi,
    }


@pytest.fixture(scope="session")
def results():
    """Load the agent's results."""
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "The analysis script must write this file."
    )
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Source file identification tests
# ---------------------------------------------------------------------------

class TestSourceIdentification:
    def test_source_file_present(self, results):
        assert "source_file" in results, "Missing key: source_file"

    def test_correct_nmr_identified(self, results):
        """
        The lab notes at /app/data/notes.txt incorrectly label protein_x42.pdb
        as X-ray and protein_k17.pdb as NMR. The agent must parse the actual
        PDB files to discover that protein_x42.pdb is the true NMR ensemble.
        """
        assert results["source_file"] == "protein_x42.pdb", (
            f"Expected 'protein_x42.pdb' (the actual NMR ensemble), "
            f"got '{results['source_file']}'. The lab notes contain "
            f"incorrect experimental method assignments — the agent must "
            f"verify by parsing the PDB files directly."
        )

    def test_multiple_files_exist(self):
        """Verify the environment has multiple PDB files to investigate."""
        pdb_files = glob.glob("/app/data/*.pdb")
        assert len(pdb_files) >= 2, (
            f"Expected multiple PDB files in /app/data/, found {len(pdb_files)}"
        )

    def test_nmr_file_is_multimodel(self):
        """Verify the identified NMR file actually has multiple models."""
        stack = strucio.load_structure(NMR_PDB_PATH)
        assert isinstance(stack, struc.AtomArrayStack), (
            "protein_x42.pdb should load as AtomArrayStack (multi-model)"
        )
        assert stack.stack_depth() > 1, (
            f"protein_x42.pdb should have multiple models, got {stack.stack_depth()}"
        )

    def test_other_file_is_not_ensemble(self):
        """Verify protein_k17.pdb is NOT a multi-model ensemble."""
        other_path = "/app/data/protein_k17.pdb"
        result = strucio.load_structure(other_path)
        if isinstance(result, struc.AtomArrayStack):
            assert result.stack_depth() <= 1, (
                "protein_k17.pdb should not be a multi-model ensemble"
            )


# ---------------------------------------------------------------------------
# Format and structure tests
# ---------------------------------------------------------------------------

class TestFormat:
    def test_output_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_valid_json(self):
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_required_keys(self, results):
        required = [
            "source_file", "n_models", "n_residues", "sequence", "rmsd_matrix",
            "medoid_model", "mean_pairwise_rmsd", "phi_angles",
            "psi_angles", "per_residue_flexibility", "secondary_structure",
        ]
        for key in required:
            assert key in results, f"Missing key: {key}"

    def test_types(self, results):
        assert isinstance(results["source_file"], str)
        assert isinstance(results["n_models"], int)
        assert isinstance(results["n_residues"], int)
        assert isinstance(results["sequence"], str)
        assert isinstance(results["rmsd_matrix"], list)
        assert isinstance(results["medoid_model"], int)
        assert isinstance(results["mean_pairwise_rmsd"], (int, float))
        assert isinstance(results["phi_angles"], list)
        assert isinstance(results["psi_angles"], list)
        assert isinstance(results["per_residue_flexibility"], list)
        assert isinstance(results["secondary_structure"], list)


# ---------------------------------------------------------------------------
# Dimension tests
# ---------------------------------------------------------------------------

class TestDimensions:
    def test_n_models(self, results, reference):
        assert results["n_models"] == reference["n_models"]

    def test_n_residues(self, results, reference):
        assert results["n_residues"] == reference["n_residues"]

    def test_rmsd_matrix_shape(self, results):
        n = results["n_models"]
        matrix = results["rmsd_matrix"]
        assert len(matrix) == n
        for row in matrix:
            assert len(row) == n

    def test_phi_shape(self, results):
        assert len(results["phi_angles"]) == results["n_models"]
        for row in results["phi_angles"]:
            assert len(row) == results["n_residues"]

    def test_psi_shape(self, results):
        assert len(results["psi_angles"]) == results["n_models"]
        for row in results["psi_angles"]:
            assert len(row) == results["n_residues"]

    def test_flexibility_length(self, results):
        assert len(results["per_residue_flexibility"]) == results["n_residues"]

    def test_ss_length(self, results):
        assert len(results["secondary_structure"]) == results["n_residues"]

    def test_sequence_length(self, results):
        assert len(results["sequence"]) == results["n_residues"]


# ---------------------------------------------------------------------------
# Sequence test
# ---------------------------------------------------------------------------

class TestSequence:
    def test_sequence_correct(self, results, reference):
        assert results["sequence"] == reference["sequence"]


# ---------------------------------------------------------------------------
# RMSD matrix tests
# ---------------------------------------------------------------------------

class TestRMSD:
    def test_diagonal_zero(self, results):
        matrix = np.array(results["rmsd_matrix"])
        assert np.allclose(np.diag(matrix), 0, atol=1e-6), "Diagonal must be zero"

    def test_symmetric(self, results):
        matrix = np.array(results["rmsd_matrix"])
        assert np.allclose(matrix, matrix.T, atol=1e-6), "RMSD matrix must be symmetric"

    def test_positive_off_diagonal(self, results):
        matrix = np.array(results["rmsd_matrix"])
        n = matrix.shape[0]
        for i in range(n):
            for j in range(i + 1, n):
                assert matrix[i, j] > 0, f"RMSD[{i},{j}] must be positive"

    def test_values_match_reference(self, results, reference):
        result_matrix = np.array(results["rmsd_matrix"])
        ref_matrix = reference["rmsd_matrix"]
        max_dev = np.max(np.abs(result_matrix - ref_matrix))
        assert max_dev < RMSD_TOL, (
            f"Max RMSD deviation {max_dev:.4f} exceeds tolerance {RMSD_TOL}"
        )

    def test_mean_pairwise_rmsd(self, results):
        matrix = np.array(results["rmsd_matrix"])
        n = matrix.shape[0]
        upper_vals = matrix[np.triu_indices(n, k=1)]
        expected = float(np.mean(upper_vals))
        assert abs(results["mean_pairwise_rmsd"] - expected) < 0.01, (
            f"mean_pairwise_rmsd {results['mean_pairwise_rmsd']:.4f} != "
            f"expected {expected:.4f}"
        )


# ---------------------------------------------------------------------------
# Medoid test
# ---------------------------------------------------------------------------

class TestMedoid:
    def test_medoid_correct(self, results):
        matrix = np.array(results["rmsd_matrix"])
        mean_rmsds = matrix.mean(axis=1)
        expected_medoid = int(np.argmin(mean_rmsds))
        assert results["medoid_model"] == expected_medoid, (
            f"Medoid {results['medoid_model']} != expected {expected_medoid}"
        )


# ---------------------------------------------------------------------------
# Dihedral angle tests
# ---------------------------------------------------------------------------

class TestDihedrals:
    def test_phi_null_first_residue(self, results):
        """First residue should have undefined phi across all models."""
        for m in range(results["n_models"]):
            assert results["phi_angles"][m][0] is None, (
                f"phi[{m}][0] should be null (N-terminal)"
            )

    def test_psi_null_last_residue(self, results):
        """Last residue should have undefined psi across all models."""
        n_res = results["n_residues"]
        for m in range(results["n_models"]):
            assert results["psi_angles"][m][n_res - 1] is None, (
                f"psi[{m}][{n_res - 1}] should be null (C-terminal)"
            )

    def test_phi_values(self, results, reference):
        """Compare phi angles against reference."""
        ref_phi = reference["phi"]
        max_dev = 0.0
        for m in range(results["n_models"]):
            for r in range(results["n_residues"]):
                ref_val = ref_phi[m, r]
                res_val = results["phi_angles"][m][r]
                if np.isnan(ref_val):
                    assert res_val is None, f"phi[{m}][{r}] should be null"
                else:
                    assert res_val is not None, f"phi[{m}][{r}] should not be null"
                    dev = abs(res_val - float(ref_val))
                    max_dev = max(max_dev, dev)
        assert max_dev < ANGLE_TOL, (
            f"Max phi deviation {max_dev:.4f} exceeds tolerance {ANGLE_TOL}"
        )

    def test_psi_values(self, results, reference):
        """Compare psi angles against reference."""
        ref_psi = reference["psi"]
        max_dev = 0.0
        for m in range(results["n_models"]):
            for r in range(results["n_residues"]):
                ref_val = ref_psi[m, r]
                res_val = results["psi_angles"][m][r]
                if np.isnan(ref_val):
                    assert res_val is None, f"psi[{m}][{r}] should be null"
                else:
                    assert res_val is not None, f"psi[{m}][{r}] should not be null"
                    dev = abs(res_val - float(ref_val))
                    max_dev = max(max_dev, dev)
        assert max_dev < ANGLE_TOL, (
            f"Max psi deviation {max_dev:.4f} exceeds tolerance {ANGLE_TOL}"
        )

    def test_angle_range(self, results):
        """All defined angles should be in [-pi, pi]."""
        for m in range(results["n_models"]):
            for r in range(results["n_residues"]):
                phi = results["phi_angles"][m][r]
                psi = results["psi_angles"][m][r]
                if phi is not None:
                    assert -np.pi - 0.01 <= phi <= np.pi + 0.01, (
                        f"phi[{m}][{r}]={phi} out of [-pi, pi]"
                    )
                if psi is not None:
                    assert -np.pi - 0.01 <= psi <= np.pi + 0.01, (
                        f"psi[{m}][{r}]={psi} out of [-pi, pi]"
                    )


# ---------------------------------------------------------------------------
# Flexibility tests
# ---------------------------------------------------------------------------

class TestFlexibility:
    def test_range(self, results):
        """Circular variance is in [0, 1]."""
        for i, val in enumerate(results["per_residue_flexibility"]):
            if val is not None:
                assert 0 <= val <= 1 + 1e-6, (
                    f"flexibility[{i}]={val} out of [0, 1]"
                )

    def test_values(self, results, reference):
        """Verify flexibility scores match circular-variance computation."""
        phi = reference["phi"]  # (n_models, n_residues)
        psi = reference["psi"]
        n_residues = reference["n_residues"]

        def circ_var(angles):
            valid = angles[~np.isnan(angles)]
            if len(valid) == 0:
                return None
            cos_m = float(np.mean(np.cos(valid)))
            sin_m = float(np.mean(np.sin(valid)))
            return 1.0 - np.sqrt(cos_m ** 2 + sin_m ** 2)

        for r in range(n_residues):
            cv_phi = circ_var(phi[:, r])
            cv_psi = circ_var(psi[:, r])
            if cv_phi is not None and cv_psi is not None:
                expected = (cv_phi + cv_psi) / 2.0
            elif cv_phi is not None:
                expected = cv_phi
            elif cv_psi is not None:
                expected = cv_psi
            else:
                expected = None

            res_val = results["per_residue_flexibility"][r]
            if expected is None:
                assert res_val is None, f"flexibility[{r}] should be null"
            else:
                assert res_val is not None, f"flexibility[{r}] should not be null"
                assert abs(res_val - expected) < FLEX_TOL, (
                    f"flexibility[{r}]: {res_val:.4f} != expected {expected:.4f}"
                )

    def test_not_linear_variance(self, results, reference):
        """
        Sanity check: circular variance should differ from linear variance
        for at least some residues, confirming circular statistics were used.
        """
        phi = reference["phi"]
        n_residues = reference["n_residues"]
        differences_found = 0
        for r in range(1, n_residues):  # skip first (phi undefined)
            valid_phi = phi[:, r][~np.isnan(phi[:, r])]
            if len(valid_phi) < 2:
                continue
            linear_var = float(np.var(valid_phi))
            cos_m = float(np.mean(np.cos(valid_phi)))
            sin_m = float(np.mean(np.sin(valid_phi)))
            circ_var = 1.0 - np.sqrt(cos_m ** 2 + sin_m ** 2)
            if abs(linear_var - circ_var) > 0.001:
                differences_found += 1
        assert differences_found > 0, (
            "Circular variance should differ from linear variance "
            "for at least some residues"
        )


# ---------------------------------------------------------------------------
# Secondary structure tests
# ---------------------------------------------------------------------------

def _classify_ss(phi_val, psi_val):
    """Reference Ramachandran classification."""
    if phi_val is None or psi_val is None:
        return "coil"
    phi_deg = np.degrees(phi_val)
    psi_deg = np.degrees(psi_val)
    if -160 <= phi_deg <= -20 and -120 <= psi_deg <= 50:
        return "alpha"
    if -180 <= phi_deg <= -20 and (psi_deg > 50 or psi_deg < -120):
        return "beta"
    return "coil"


class TestSecondaryStructure:
    def test_valid_labels(self, results):
        valid = {"alpha", "beta", "coil"}
        for i, label in enumerate(results["secondary_structure"]):
            assert label in valid, (
                f"secondary_structure[{i}]='{label}' not in {valid}"
            )

    def test_consistency_with_angles(self, results):
        """SS classification must be consistent with the reported angles."""
        medoid = results["medoid_model"]
        n_residues = results["n_residues"]
        for r in range(n_residues):
            phi = results["phi_angles"][medoid][r]
            psi = results["psi_angles"][medoid][r]
            expected = _classify_ss(phi, psi)
            assert results["secondary_structure"][r] == expected, (
                f"secondary_structure[{r}]='{results['secondary_structure'][r]}' "
                f"inconsistent with phi={phi}, psi={psi} (expected '{expected}')"
            )

    def test_terminal_residues_coil(self, results):
        """Terminal residues with undefined angles should be 'coil'."""
        assert results["secondary_structure"][0] == "coil", (
            "N-terminal residue with undefined phi should be 'coil'"
        )
        n = results["n_residues"]
        assert results["secondary_structure"][n - 1] == "coil", (
            "C-terminal residue with undefined psi should be 'coil'"
        )

    def test_known_alpha_region(self, results, reference):
        """
        Trp-cage (1L2Y) has a known alpha-helical region roughly
        residues 2-8 (0-indexed). Verify at least some of these are
        classified as alpha in the medoid.
        """
        medoid = results["medoid_model"]
        alpha_count = sum(
            1
            for r in range(2, 9)
            if results["secondary_structure"][r] == "alpha"
        )
        assert alpha_count >= 4, (
            f"Expected >=4 alpha residues in positions 2-8 of Trp-cage, "
            f"got {alpha_count}"
        )
