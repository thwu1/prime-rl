
import json
import math
import os

import h5py
import numpy as np
import pytest

RESULTS_PATH = "/app/validation_report.json"


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"Output file {RESULTS_PATH} not found"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


def approx_rel(expected, rel_tol):
    return pytest.approx(expected, rel=rel_tol)


def approx_abs(expected, abs_tol):
    return pytest.approx(expected, abs=abs_tol)


def read_statepoint(benchmark_id):
    """Read HDF5 statepoint and independently compute reference values."""
    filepath = f"/app/statepoints/{benchmark_id}_statepoint.h5"
    with h5py.File(filepath, "r") as f:
        keff_all = f["results/k_effective"][:]
        n_inactive = int(f["settings/n_inactive"][()])
        entropy_all = f["diagnostics/entropy"][:]

    active_keff = keff_all[n_inactive:]
    n_active = len(active_keff)
    keff_mean = float(np.mean(active_keff))
    keff_stderr = float(np.std(active_keff, ddof=1) / np.sqrt(n_active))

    last_half = entropy_all[len(entropy_all) // 2 :]
    entropy_cv = float(np.std(last_half) / np.mean(last_half))
    entropy_converged = entropy_cv < 0.02

    return {
        "keff_mean": keff_mean,
        "keff_stderr": keff_stderr,
        "n_active": n_active,
        "entropy_converged": entropy_converged,
    }


# ===== HMF001 (Godiva) Tests =====


class TestHMF001:
    def test_exists(self, results):
        assert "hmf001" in results

    def test_total_fissile_mass(self, results):
        mass = results["hmf001"]["total_fissile_mass_kg"]
        assert mass == approx_rel(52.37, 0.01)

    def test_avg_enrichment(self, results):
        enrich = results["hmf001"]["avg_enrichment_wt_pct"]
        assert enrich == approx_abs(93.87, 0.5)

    def test_shell_densities_count(self, results):
        densities = results["hmf001"]["shell_densities_gcc"]
        assert len(densities) == 6

    def test_shell_densities_range(self, results):
        for i, d in enumerate(results["hmf001"]["shell_densities_gcc"]):
            assert 18.5 < d < 19.1, f"Shell {i+1} density {d:.3f} outside range"

    def test_shell1_density(self, results):
        d = results["hmf001"]["shell_densities_gcc"][0]
        assert d == approx_rel(18.806, 0.01)

    def test_shell6_density(self, results):
        d = results["hmf001"]["shell_densities_gcc"][5]
        assert d == approx_rel(18.660, 0.01)

    def test_simulated_keff(self, results):
        ref = read_statepoint("hmf001")
        assert results["hmf001"]["simulated_keff"] == approx_abs(
            ref["keff_mean"], 0.0005
        )

    def test_simulated_keff_stderr(self, results):
        ref = read_statepoint("hmf001")
        assert results["hmf001"]["simulated_keff_stderr"] == approx_rel(
            ref["keff_stderr"], 0.1
        )

    def test_n_active_batches(self, results):
        ref = read_statepoint("hmf001")
        assert results["hmf001"]["n_active_batches"] == ref["n_active"]

    def test_entropy_converged(self, results):
        assert results["hmf001"]["entropy_converged"] is True

    def test_experimental_keff(self, results):
        assert results["hmf001"]["experimental_keff"] == approx_abs(1.0, 0.001)

    def test_experimental_uncertainty(self, results):
        assert results["hmf001"]["experimental_uncertainty"] == approx_abs(
            0.001, 0.0005
        )

    def test_c_over_e(self, results):
        ref = read_statepoint("hmf001")
        expected_ce = ref["keff_mean"] / 1.0
        assert results["hmf001"]["c_over_e"] == approx_rel(expected_ce, 0.001)

    def test_c_over_e_unc(self, results):
        ref = read_statepoint("hmf001")
        ce = ref["keff_mean"] / 1.0
        ce_unc = ce * math.sqrt(
            (ref["keff_stderr"] / ref["keff_mean"]) ** 2 + (0.001 / 1.0) ** 2
        )
        assert results["hmf001"]["c_over_e_unc"] == approx_rel(ce_unc, 0.15)

    def test_validation_pass(self, results):
        ref = read_statepoint("hmf001")
        ce = ref["keff_mean"] / 1.0
        ce_unc = ce * math.sqrt(
            (ref["keff_stderr"] / ref["keff_mean"]) ** 2 + (0.001 / 1.0) ** 2
        )
        expected_pass = abs(ce - 1.0) < 2.0 * ce_unc
        assert results["hmf001"]["validation_pass"] == expected_pass


# ===== HMF003 (Topsy) Tests =====


class TestHMF003:
    def test_exists(self, results):
        assert "hmf003" in results

    def test_core_mass(self, results):
        assert results["hmf003"]["core_mass_kg"] == approx_rel(24.50, 0.01)

    def test_core_enrichment(self, results):
        assert results["hmf003"]["core_enrichment_wt_pct"] == approx_abs(93.50, 0.5)

    def test_core_density(self, results):
        assert results["hmf003"]["core_density_gcc"] == approx_rel(18.75, 0.01)

    def test_reflector_mass(self, results):
        assert results["hmf003"]["reflector_mass_kg"] == approx_rel(107.44, 0.01)

    def test_reflector_enrichment(self, results):
        assert results["hmf003"]["reflector_enrichment_wt_pct"] == approx_abs(
            0.711, 0.1
        )

    def test_reflector_density(self, results):
        assert results["hmf003"]["reflector_density_gcc"] == approx_rel(18.90, 0.01)

    def test_simulated_keff(self, results):
        ref = read_statepoint("hmf003")
        assert results["hmf003"]["simulated_keff"] == approx_abs(
            ref["keff_mean"], 0.0005
        )

    def test_simulated_keff_stderr(self, results):
        ref = read_statepoint("hmf003")
        assert results["hmf003"]["simulated_keff_stderr"] == approx_rel(
            ref["keff_stderr"], 0.1
        )

    def test_n_active_batches(self, results):
        ref = read_statepoint("hmf003")
        assert results["hmf003"]["n_active_batches"] == ref["n_active"]

    def test_entropy_converged(self, results):
        assert results["hmf003"]["entropy_converged"] is True

    def test_experimental_keff(self, results):
        assert results["hmf003"]["experimental_keff"] == approx_abs(1.0, 0.001)

    def test_experimental_uncertainty(self, results):
        assert results["hmf003"]["experimental_uncertainty"] == approx_abs(
            0.005, 0.001
        )

    def test_c_over_e(self, results):
        ref = read_statepoint("hmf003")
        expected_ce = ref["keff_mean"] / 1.0
        assert results["hmf003"]["c_over_e"] == approx_rel(expected_ce, 0.001)

    def test_c_over_e_unc(self, results):
        ref = read_statepoint("hmf003")
        ce = ref["keff_mean"] / 1.0
        ce_unc = ce * math.sqrt(
            (ref["keff_stderr"] / ref["keff_mean"]) ** 2 + (0.005 / 1.0) ** 2
        )
        assert results["hmf003"]["c_over_e_unc"] == approx_rel(ce_unc, 0.15)

    def test_validation_pass(self, results):
        ref = read_statepoint("hmf003")
        ce = ref["keff_mean"] / 1.0
        ce_unc = ce * math.sqrt(
            (ref["keff_stderr"] / ref["keff_mean"]) ** 2 + (0.005 / 1.0) ** 2
        )
        expected_pass = abs(ce - 1.0) < 2.0 * ce_unc
        assert results["hmf003"]["validation_pass"] == expected_pass


# ===== HST001 (Uranyl Nitrate Solution) Tests =====


class TestHST001:
    def test_exists(self, results):
        assert "hst001" in results

    def test_solution_density(self, results):
        assert results["hst001"]["solution_density_gcc"] == approx_rel(1.2036, 0.01)

    def test_enrichment(self, results):
        assert results["hst001"]["enrichment_wt_pct"] == approx_abs(93.17, 0.5)

    def test_hx_ratio(self, results):
        assert results["hst001"]["hx_ratio"] == approx_rel(181.79, 0.02)

    def test_solution_volume(self, results):
        assert results["hst001"]["solution_volume_cm3"] == approx_rel(19101.84, 0.01)

    def test_u235_mass(self, results):
        assert results["hst001"]["u235_mass_g"] == approx_rel(2592.78, 0.01)

    def test_simulated_keff(self, results):
        ref = read_statepoint("hst001")
        assert results["hst001"]["simulated_keff"] == approx_abs(
            ref["keff_mean"], 0.0005
        )

    def test_simulated_keff_stderr(self, results):
        ref = read_statepoint("hst001")
        assert results["hst001"]["simulated_keff_stderr"] == approx_rel(
            ref["keff_stderr"], 0.1
        )

    def test_n_active_batches(self, results):
        ref = read_statepoint("hst001")
        assert results["hst001"]["n_active_batches"] == ref["n_active"]

    def test_entropy_converged(self, results):
        assert results["hst001"]["entropy_converged"] is True

    def test_experimental_keff(self, results):
        assert results["hst001"]["experimental_keff"] == approx_abs(1.0004, 0.001)

    def test_experimental_uncertainty(self, results):
        assert results["hst001"]["experimental_uncertainty"] == approx_abs(
            0.006, 0.001
        )

    def test_c_over_e(self, results):
        ref = read_statepoint("hst001")
        expected_ce = ref["keff_mean"] / 1.0004
        assert results["hst001"]["c_over_e"] == approx_rel(expected_ce, 0.001)

    def test_c_over_e_unc(self, results):
        ref = read_statepoint("hst001")
        ce = ref["keff_mean"] / 1.0004
        ce_unc = ce * math.sqrt(
            (ref["keff_stderr"] / ref["keff_mean"]) ** 2 + (0.006 / 1.0004) ** 2
        )
        assert results["hst001"]["c_over_e_unc"] == approx_rel(ce_unc, 0.15)

    def test_validation_pass(self, results):
        ref = read_statepoint("hst001")
        ce = ref["keff_mean"] / 1.0004
        ce_unc = ce * math.sqrt(
            (ref["keff_stderr"] / ref["keff_mean"]) ** 2 + (0.006 / 1.0004) ** 2
        )
        expected_pass = abs(ce - 1.0) < 2.0 * ce_unc
        assert results["hst001"]["validation_pass"] == expected_pass


# ===== Cross-benchmark structural tests =====


class TestStructure:
    def test_all_benchmarks_present(self, results):
        for key in ["hmf001", "hmf003", "hst001"]:
            assert key in results, f"Missing benchmark: {key}"

    def test_json_valid(self):
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_hmf001_has_required_keys(self, results):
        required = [
            "total_fissile_mass_kg",
            "avg_enrichment_wt_pct",
            "shell_densities_gcc",
            "simulated_keff",
            "simulated_keff_stderr",
            "n_active_batches",
            "entropy_converged",
            "experimental_keff",
            "experimental_uncertainty",
            "c_over_e",
            "c_over_e_unc",
            "validation_pass",
        ]
        for key in required:
            assert key in results["hmf001"], f"hmf001 missing key: {key}"

    def test_hmf003_has_required_keys(self, results):
        required = [
            "core_mass_kg",
            "core_enrichment_wt_pct",
            "reflector_mass_kg",
            "reflector_enrichment_wt_pct",
            "core_density_gcc",
            "reflector_density_gcc",
            "simulated_keff",
            "simulated_keff_stderr",
            "n_active_batches",
            "entropy_converged",
            "experimental_keff",
            "experimental_uncertainty",
            "c_over_e",
            "c_over_e_unc",
            "validation_pass",
        ]
        for key in required:
            assert key in results["hmf003"], f"hmf003 missing key: {key}"

    def test_hst001_has_required_keys(self, results):
        required = [
            "solution_density_gcc",
            "enrichment_wt_pct",
            "hx_ratio",
            "solution_volume_cm3",
            "u235_mass_g",
            "simulated_keff",
            "simulated_keff_stderr",
            "n_active_batches",
            "entropy_converged",
            "experimental_keff",
            "experimental_uncertainty",
            "c_over_e",
            "c_over_e_unc",
            "validation_pass",
        ]
        for key in required:
            assert key in results["hst001"], f"hst001 missing key: {key}"

    def test_physical_sanity_mass_positive(self, results):
        assert results["hmf001"]["total_fissile_mass_kg"] > 0
        assert results["hmf003"]["core_mass_kg"] > 0
        assert results["hmf003"]["reflector_mass_kg"] > 0
        assert results["hst001"]["u235_mass_g"] > 0

    def test_physical_sanity_enrichment_range(self, results):
        for enrich in [
            results["hmf001"]["avg_enrichment_wt_pct"],
            results["hmf003"]["core_enrichment_wt_pct"],
            results["hmf003"]["reflector_enrichment_wt_pct"],
            results["hst001"]["enrichment_wt_pct"],
        ]:
            assert 0 < enrich < 100

    def test_physical_sanity_heu_vs_reflector(self, results):
        core = results["hmf003"]["core_enrichment_wt_pct"]
        refl = results["hmf003"]["reflector_enrichment_wt_pct"]
        assert core > 50 * refl

    def test_c_over_e_near_unity(self, results):
        for bm in ["hmf001", "hmf003", "hst001"]:
            ce = results[bm]["c_over_e"]
            assert 0.95 < ce < 1.05, f"{bm} C/E = {ce} far from unity"

    def test_keff_stderr_positive(self, results):
        for bm in ["hmf001", "hmf003", "hst001"]:
            assert results[bm]["simulated_keff_stderr"] > 0

    def test_keff_stderr_reasonable(self, results):
        for bm in ["hmf001", "hmf003", "hst001"]:
            stderr = results[bm]["simulated_keff_stderr"]
            keff = results[bm]["simulated_keff"]
            assert stderr / keff < 0.01
