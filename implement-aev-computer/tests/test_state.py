
"""Tests for the AEV benchmark pipeline.

Verifies HDF5 output structure, SQLite schema/content, AEV numerical
correctness against NeuroChem/TorchANI reference values, and cross-format
consistency between HDF5 data and SQLite statistics.
"""

import pytest
import os
import json
import sqlite3
import numpy as np
import h5py

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────
AEV_LENGTH = 384
RADIAL_LENGTH = 64
ANGULAR_LENGTH = 320
RADIAL_SUBLENGTH = 16
ANGULAR_SUBLENGTH = 32
NUM_SPECIES = 4
NUM_SPECIES_PAIRS = 10
ATOL = 1e-6

# Load input data for reference
with open("/app/conformations.json") as _f:
    _INPUT = json.load(_f)

SPECIES_MAP = _INPUT["species_map"]
MOL_DATA = _INPUT["molecules"]
MOLECULE_NAMES = sorted(MOL_DATA.keys())


# ──────────────────────────────────────────────────────────────────────
# Module-scoped fixtures
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def h5f():
    assert os.path.exists("/app/aev_output.h5"), "HDF5 output file not found"
    f = h5py.File("/app/aev_output.h5", "r")
    yield f
    f.close()


@pytest.fixture(scope="module")
def db():
    assert os.path.exists("/app/benchmark.db"), "SQLite database not found"
    conn = sqlite3.connect("/app/benchmark.db")
    yield conn
    conn.close()


# ──────────────────────────────────────────────────────────────────────
# HDF5 structure tests
# ──────────────────────────────────────────────────────────────────────
class TestHDF5Structure:
    """Verify HDF5 output file structure, datasets, and attributes."""

    def test_top_level_groups(self, h5f):
        assert "molecules" in h5f, "Missing /molecules group"
        assert "params" in h5f, "Missing /params group"
        assert "metadata" in h5f, "Missing /metadata group"

    def test_pipeline_version(self, h5f):
        assert h5f["metadata"].attrs["pipeline_version"] == "1.0"

    def test_params_rcr(self, h5f):
        assert abs(h5f["params"].attrs["Rcr"] - 5.2) < 1e-6

    def test_params_rca(self, h5f):
        assert abs(h5f["params"].attrs["Rca"] - 3.5) < 1e-6

    def test_params_num_species(self, h5f):
        assert h5f["params"].attrs["num_species"] == 4

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_molecule_group_exists(self, h5f, mol_name):
        assert mol_name in h5f["molecules"], f"Missing /molecules/{mol_name}"

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_aev_dataset_shape(self, h5f, mol_name):
        n_atoms = len(MOL_DATA[mol_name]["elements"])
        ds = h5f[f"molecules/{mol_name}/aev"]
        assert ds.shape == (n_atoms, AEV_LENGTH), (
            f"Expected ({n_atoms}, {AEV_LENGTH}), got {ds.shape}"
        )

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_aev_dtype(self, h5f, mol_name):
        ds = h5f[f"molecules/{mol_name}/aev"]
        assert ds.dtype == np.float64

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_aev_compression(self, h5f, mol_name):
        ds = h5f[f"molecules/{mol_name}/aev"]
        assert ds.compression == "gzip", (
            f"AEV dataset must use gzip compression, got {ds.compression}"
        )

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_species_dataset(self, h5f, mol_name):
        n_atoms = len(MOL_DATA[mol_name]["elements"])
        ds = h5f[f"molecules/{mol_name}/species"]
        assert ds.shape == (n_atoms,)
        assert ds.dtype == np.int64

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_coordinates_dataset(self, h5f, mol_name):
        n_atoms = len(MOL_DATA[mol_name]["elements"])
        ds = h5f[f"molecules/{mol_name}/coordinates"]
        assert ds.shape == (n_atoms, 3)
        assert ds.dtype == np.float64

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_group_n_atoms_attr(self, h5f, mol_name):
        n_atoms = len(MOL_DATA[mol_name]["elements"])
        grp = h5f[f"molecules/{mol_name}"]
        assert int(grp.attrs["n_atoms"]) == n_atoms

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_group_aev_length_attr(self, h5f, mol_name):
        grp = h5f[f"molecules/{mol_name}"]
        assert int(grp.attrs["aev_length"]) == AEV_LENGTH

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_species_values(self, h5f, mol_name):
        """Verify species indices match element-to-index mapping."""
        elements = MOL_DATA[mol_name]["elements"]
        expected = [SPECIES_MAP[e] for e in elements]
        actual = list(h5f[f"molecules/{mol_name}/species"][:])
        assert actual == expected

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_coordinates_values(self, h5f, mol_name):
        """Verify coordinates match input data."""
        expected = np.array(MOL_DATA[mol_name]["coordinates"], dtype=np.float64)
        actual = np.array(h5f[f"molecules/{mol_name}/coordinates"])
        np.testing.assert_allclose(actual, expected, atol=1e-12)


# ──────────────────────────────────────────────────────────────────────
# SQLite structure tests
# ──────────────────────────────────────────────────────────────────────
class TestSQLiteStructure:
    """Verify SQLite database schema and content."""

    def test_molecules_table_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='molecules'"
        )
        assert cur.fetchone() is not None, "Missing 'molecules' table"

    def test_atom_details_table_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='atom_details'"
        )
        assert cur.fetchone() is not None, "Missing 'atom_details' table"

    def test_molecules_columns(self, db):
        cur = db.execute("PRAGMA table_info(molecules)")
        cols = {row[1] for row in cur.fetchall()}
        expected = {
            "name", "n_atoms", "formula", "radial_norm_mean", "radial_norm_std",
            "angular_norm_mean", "angular_norm_std", "sparsity", "max_element",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_atom_details_columns(self, db):
        cur = db.execute("PRAGMA table_info(atom_details)")
        cols = {row[1] for row in cur.fetchall()}
        expected = {
            "molecule_name", "atom_index", "species",
            "radial_l2_norm", "angular_l2_norm",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_molecules_row_count(self, db):
        cur = db.execute("SELECT COUNT(*) FROM molecules")
        assert cur.fetchone()[0] == len(MOLECULE_NAMES)

    def test_atom_details_total_count(self, db):
        total = sum(len(MOL_DATA[m]["elements"]) for m in MOLECULE_NAMES)
        cur = db.execute("SELECT COUNT(*) FROM atom_details")
        assert cur.fetchone()[0] == total

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_molecule_exists_in_db(self, db, mol_name):
        cur = db.execute("SELECT * FROM molecules WHERE name=?", (mol_name,))
        assert cur.fetchone() is not None, f"Molecule '{mol_name}' not in database"

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_n_atoms_value(self, db, mol_name):
        cur = db.execute("SELECT n_atoms FROM molecules WHERE name=?", (mol_name,))
        n = cur.fetchone()[0]
        expected = len(MOL_DATA[mol_name]["elements"])
        assert n == expected

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_atom_details_count_per_molecule(self, db, mol_name):
        cur = db.execute(
            "SELECT COUNT(*) FROM atom_details WHERE molecule_name=?", (mol_name,)
        )
        n = cur.fetchone()[0]
        expected = len(MOL_DATA[mol_name]["elements"])
        assert n == expected


# ──────────────────────────────────────────────────────────────────────
# Hill-order formula tests
# ──────────────────────────────────────────────────────────────────────
class TestFormulas:
    """Verify molecular formulas follow Hill order convention."""

    EXPECTED_FORMULAS = {
        "water": "H2O",
        "methane": "CH4",
        "formaldehyde": "CH2O",
        "glycine": "C2H5NO2",
        "urea": "CH4N2O",
    }

    @pytest.mark.parametrize(
        "mol_name,expected",
        list(EXPECTED_FORMULAS.items()),
    )
    def test_formula(self, db, mol_name, expected):
        cur = db.execute("SELECT formula FROM molecules WHERE name=?", (mol_name,))
        row = cur.fetchone()
        assert row is not None
        assert row[0] == expected, f"Expected '{expected}', got '{row[0]}'"


# ──────────────────────────────────────────────────────────────────────
# AEV numerical correctness tests
# ──────────────────────────────────────────────────────────────────────

# Precomputed per-atom sums (radial_sum, angular_sum) for known molecules.
# Reference values computed with float64 precision using NeuroChem/TorchANI.
REFERENCE_SUMS = {
    "water": [
        (0.6719979294365, 2.246914369673),
        (0.6677980231311, 1.366578329218),
        (0.6677980231311, 1.366578329218),
    ],
    "methane": [
        (1.444648679441, 10.86727646082),
        (1.274979536995, 5.718716510998),
        (1.274979536995, 5.718716510998),
        (1.274979536995, 5.718716510998),
        (1.274979536995, 5.718716510998),
    ],
    "formaldehyde": [
        (1.082517299543, 4.953487010944),
        (0.9130839203514, 2.296232423831),
        (0.9329655743630, 2.626105495362),
        (0.9329655743630, 2.626105495362),
    ],
}

# Spot-check specific AEV element values: (atom_idx, aev_idx, expected_value)
REFERENCE_ELEMENTS = {
    "water": [
        (0, 0, 0.43582326690093975),
        (0, 1, 0.22463779979389722),
        (0, 2, 0.01147868506347617),
        (0, 68, 1.3102725644261366),
        (0, 69, 0.5006514263553087),
        (0, 70, 0.014758346652489669),
        (1, 0, 0.00048318098197154465),
        (1, 2, 0.18326551599354166),
        (1, 3, 0.11140932243875802),
        (1, 160, 0.043809500948075196),
        (1, 161, 0.3533793595980334),
        (1, 162, 0.23528002697596126),
    ],
    "methane": [
        (0, 0, 0.5119468456690063),
        (0, 1, 0.8052055201252885),
        (0, 2, 0.12555253745061953),
        (0, 67, 0.6269152795464963),
        (0, 68, 4.864882820896107),
        (0, 69, 3.119126298991204),
        (1, 16, 0.12798671141725157),
        (1, 66, 0.0029156057227036963),
    ],
    "formaldehyde": [
        (0, 0, 0.23071212488164267),
        (0, 1, 0.4167879393419413),
        (0, 68, 0.5674456803369295),
        (0, 69, 0.6941512304882791),
        (0, 164, 0.5580162390613951),
        (0, 165, 1.3275121462014654),
        (0, 166, 0.262987112109979),
        (2, 96, 0.009359471149263922),
        (2, 97, 0.04378180010449467),
    ],
}


class TestAEVNumericalCorrectness:
    """Verify AEV values against precomputed references."""

    @pytest.mark.parametrize("mol_name", ["water", "methane", "formaldehyde"])
    def test_radial_sums(self, h5f, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        for i, (rad_ref, _) in enumerate(REFERENCE_SUMS[mol_name]):
            rad_sum = float(aev[i, :RADIAL_LENGTH].sum())
            np.testing.assert_allclose(
                rad_sum, rad_ref, atol=ATOL,
                err_msg=f"{mol_name} atom {i} radial sum mismatch",
            )

    @pytest.mark.parametrize("mol_name", ["water", "methane", "formaldehyde"])
    def test_angular_sums(self, h5f, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        for i, (_, ang_ref) in enumerate(REFERENCE_SUMS[mol_name]):
            ang_sum = float(aev[i, RADIAL_LENGTH:].sum())
            np.testing.assert_allclose(
                ang_sum, ang_ref, atol=ATOL,
                err_msg=f"{mol_name} atom {i} angular sum mismatch",
            )

    @pytest.mark.parametrize("mol_name", ["water", "methane", "formaldehyde"])
    def test_spot_checks(self, h5f, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        for atom_idx, aev_idx, expected in REFERENCE_ELEMENTS[mol_name]:
            actual = float(aev[atom_idx, aev_idx])
            np.testing.assert_allclose(
                actual, expected, atol=ATOL,
                err_msg=(
                    f"{mol_name} atom {atom_idx} AEV[{aev_idx}]: "
                    f"expected {expected:.10e}, got {actual:.10e}"
                ),
            )

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_aev_shape_correct(self, h5f, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        n_atoms = len(MOL_DATA[mol_name]["elements"])
        assert aev.shape == (n_atoms, AEV_LENGTH)

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_no_nan_values(self, h5f, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        assert not np.isnan(aev).any(), f"{mol_name} AEV contains NaN"

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_no_negative_aev(self, h5f, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        assert (aev >= -1e-15).all(), f"{mol_name} AEV contains negative values"


# ──────────────────────────────────────────────────────────────────────
# Symmetry tests
# ──────────────────────────────────────────────────────────────────────
class TestSymmetry:
    """Verify equivalent atoms produce identical AEVs."""

    def test_water_h_symmetry(self, h5f):
        aev = np.array(h5f["molecules/water/aev"])
        np.testing.assert_allclose(
            aev[1], aev[2], atol=1e-12,
            err_msg="Water H atoms should have equal AEVs",
        )

    def test_methane_h_symmetry(self, h5f):
        aev = np.array(h5f["molecules/methane/aev"])
        for i in range(2, 5):
            np.testing.assert_allclose(
                aev[1], aev[i], atol=1e-12,
                err_msg=f"Methane H atoms 1 and {i} should have equal AEVs",
            )

    def test_formaldehyde_h_symmetry(self, h5f):
        aev = np.array(h5f["molecules/formaldehyde/aev"])
        np.testing.assert_allclose(
            aev[2], aev[3], atol=1e-12,
            err_msg="Formaldehyde H atoms should have equal AEVs",
        )

    def test_urea_n_symmetry(self, h5f):
        """Urea's two N atoms are related by C2 symmetry."""
        aev = np.array(h5f["molecules/urea/aev"])
        np.testing.assert_allclose(
            aev[2], aev[3], atol=1e-12,
            err_msg="Urea N atoms should have equal AEVs",
        )

    def test_urea_h_pair1_symmetry(self, h5f):
        """Urea H4 and H6 are C2-related."""
        aev = np.array(h5f["molecules/urea/aev"])
        np.testing.assert_allclose(
            aev[4], aev[6], atol=1e-12,
            err_msg="Urea H atoms 4 and 6 should have equal AEVs",
        )

    def test_urea_h_pair2_symmetry(self, h5f):
        """Urea H5 and H7 are C2-related."""
        aev = np.array(h5f["molecules/urea/aev"])
        np.testing.assert_allclose(
            aev[5], aev[7], atol=1e-12,
            err_msg="Urea H atoms 5 and 7 should have equal AEVs",
        )


# ──────────────────────────────────────────────────────────────────────
# Angular block assignment tests
# ──────────────────────────────────────────────────────────────────────
class TestAngularBlocks:
    """Verify angular contributions land in correct species-pair blocks."""

    def test_water_o_only_hh_angular(self, h5f):
        """O in water: only H-H angular pair should be nonzero."""
        aev = np.array(h5f["molecules/water/aev"])
        o_angular = aev[0, RADIAL_LENGTH:]
        hh_block = o_angular[:ANGULAR_SUBLENGTH]
        assert np.abs(hh_block).max() > 0.01, "O angular H-H block should be nonzero"
        for pair_idx in range(1, NUM_SPECIES_PAIRS):
            start = pair_idx * ANGULAR_SUBLENGTH
            end = start + ANGULAR_SUBLENGTH
            np.testing.assert_allclose(
                o_angular[start:end], 0.0, atol=1e-15,
                err_msg=f"O angular pair block {pair_idx} should be zero in water",
            )

    def test_formaldehyde_c_angular_blocks(self, h5f):
        """C in formaldehyde has H-H and H-O angular neighbors."""
        aev = np.array(h5f["molecules/formaldehyde/aev"])
        c_angular = aev[0, RADIAL_LENGTH:]
        hh_block = c_angular[:ANGULAR_SUBLENGTH]
        ho_block = c_angular[3 * ANGULAR_SUBLENGTH : 4 * ANGULAR_SUBLENGTH]
        assert np.abs(hh_block).max() > 0.01
        assert np.abs(ho_block).max() > 0.01
        for pair_idx in [1, 2, 4, 5, 6, 7, 8, 9]:
            start = pair_idx * ANGULAR_SUBLENGTH
            end = start + ANGULAR_SUBLENGTH
            np.testing.assert_allclose(
                c_angular[start:end], 0.0, atol=1e-15,
                err_msg=f"C angular pair block {pair_idx} should be zero in formaldehyde",
            )

    def test_glycine_has_all_four_species_radial(self, h5f):
        """Glycine has all four species; the N atom should have H, C, O radial blocks."""
        aev = np.array(h5f["molecules/glycine/aev"])
        n_radial = aev[0, :RADIAL_LENGTH]  # N atom (index 0)
        # N has C and H neighbors within Rcr; check at least H and C blocks are nonzero
        h_block = n_radial[:RADIAL_SUBLENGTH]
        c_block = n_radial[RADIAL_SUBLENGTH : 2 * RADIAL_SUBLENGTH]
        assert np.abs(h_block).max() > 0.001, "N should have nonzero H radial block"
        assert np.abs(c_block).max() > 0.001, "N should have nonzero C radial block"


# ──────────────────────────────────────────────────────────────────────
# Cross-format consistency tests
# ──────────────────────────────────────────────────────────────────────
class TestCrossFormatConsistency:
    """Verify HDF5 data and SQLite statistics are mutually consistent."""

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_n_atoms_consistent(self, h5f, db, mol_name):
        h5_n = int(h5f[f"molecules/{mol_name}"].attrs["n_atoms"])
        cur = db.execute("SELECT n_atoms FROM molecules WHERE name=?", (mol_name,))
        db_n = cur.fetchone()[0]
        assert h5_n == db_n

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_radial_norm_mean(self, h5f, db, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        radial_norms = np.linalg.norm(aev[:, :RADIAL_LENGTH], axis=1)
        expected = float(radial_norms.mean())
        cur = db.execute(
            "SELECT radial_norm_mean FROM molecules WHERE name=?", (mol_name,)
        )
        db_val = cur.fetchone()[0]
        np.testing.assert_allclose(db_val, expected, rtol=1e-6)

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_radial_norm_std(self, h5f, db, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        radial_norms = np.linalg.norm(aev[:, :RADIAL_LENGTH], axis=1)
        expected = float(radial_norms.std())
        cur = db.execute(
            "SELECT radial_norm_std FROM molecules WHERE name=?", (mol_name,)
        )
        db_val = cur.fetchone()[0]
        np.testing.assert_allclose(db_val, expected, rtol=1e-6)

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_angular_norm_mean(self, h5f, db, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        angular_norms = np.linalg.norm(aev[:, RADIAL_LENGTH:], axis=1)
        expected = float(angular_norms.mean())
        cur = db.execute(
            "SELECT angular_norm_mean FROM molecules WHERE name=?", (mol_name,)
        )
        db_val = cur.fetchone()[0]
        np.testing.assert_allclose(db_val, expected, rtol=1e-6)

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_angular_norm_std(self, h5f, db, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        angular_norms = np.linalg.norm(aev[:, RADIAL_LENGTH:], axis=1)
        expected = float(angular_norms.std())
        cur = db.execute(
            "SELECT angular_norm_std FROM molecules WHERE name=?", (mol_name,)
        )
        db_val = cur.fetchone()[0]
        np.testing.assert_allclose(db_val, expected, rtol=1e-6)

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_sparsity(self, h5f, db, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        expected = float((aev == 0.0).sum()) / aev.size
        cur = db.execute("SELECT sparsity FROM molecules WHERE name=?", (mol_name,))
        db_val = cur.fetchone()[0]
        np.testing.assert_allclose(db_val, expected, rtol=1e-6)

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_max_element(self, h5f, db, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        expected = float(aev.max())
        cur = db.execute("SELECT max_element FROM molecules WHERE name=?", (mol_name,))
        db_val = cur.fetchone()[0]
        np.testing.assert_allclose(db_val, expected, rtol=1e-6)

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_atom_details_radial_norms(self, h5f, db, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        n_atoms = aev.shape[0]
        for i in range(n_atoms):
            cur = db.execute(
                "SELECT radial_l2_norm FROM atom_details "
                "WHERE molecule_name=? AND atom_index=?",
                (mol_name, i),
            )
            row = cur.fetchone()
            assert row is not None, f"Missing atom_details for {mol_name} atom {i}"
            expected = float(np.linalg.norm(aev[i, :RADIAL_LENGTH]))
            np.testing.assert_allclose(row[0], expected, rtol=1e-6)

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_atom_details_angular_norms(self, h5f, db, mol_name):
        aev = np.array(h5f[f"molecules/{mol_name}/aev"])
        n_atoms = aev.shape[0]
        for i in range(n_atoms):
            cur = db.execute(
                "SELECT angular_l2_norm FROM atom_details "
                "WHERE molecule_name=? AND atom_index=?",
                (mol_name, i),
            )
            row = cur.fetchone()
            assert row is not None
            expected = float(np.linalg.norm(aev[i, RADIAL_LENGTH:]))
            np.testing.assert_allclose(row[0], expected, rtol=1e-6)

    @pytest.mark.parametrize("mol_name", MOLECULE_NAMES)
    def test_atom_details_species(self, h5f, db, mol_name):
        h5_species = list(h5f[f"molecules/{mol_name}/species"][:])
        n_atoms = len(h5_species)
        for i in range(n_atoms):
            cur = db.execute(
                "SELECT species FROM atom_details "
                "WHERE molecule_name=? AND atom_index=?",
                (mol_name, i),
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == int(h5_species[i])


# ──────────────────────────────────────────────────────────────────────
# Analytic radial cross-validation
# ──────────────────────────────────────────────────────────────────────
class TestAnalyticRadial:
    """Verify a simple radial case against independent analytic computation."""

    def test_water_o_first_radial_element(self, h5f):
        """Verify O atom's first radial element in water analytically.

        O has two H neighbors at identical distance d. The first radial
        element is: 2 * 0.25 * exp(-EtaR * (d - ShfR[0])^2) * fc(d, Rcr).
        """
        import math

        coords = np.array(MOL_DATA["water"]["coordinates"])
        d = float(np.linalg.norm(coords[1] - coords[0]))  # O-H distance
        Rcr = 5.2
        EtaR = 16.0
        ShfR0 = 0.9
        fc = 0.5 * math.cos(d * math.pi / Rcr) + 0.5
        # Two H neighbors contribute to the H-species radial block
        expected = 2 * 0.25 * math.exp(-EtaR * (d - ShfR0) ** 2) * fc

        aev = np.array(h5f["molecules/water/aev"])
        actual = float(aev[0, 0])  # O atom, first radial element (H block)
        np.testing.assert_allclose(actual, expected, atol=1e-10)
