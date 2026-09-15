
import json
import math
import numpy as np
from scipy.linalg import expm
import pytest


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def hydro():
    with open("/app/hydro_data.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def config():
    with open("/app/config.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def sea_state_ids(config):
    return [ss["id"] for ss in config["sea_states"]]


# ──────────────────────────────────────────────
# Schema / completeness tests
# ──────────────────────────────────────────────
class TestSchema:
    def test_top_level_keys(self, results):
        for key in ["irf", "state_space", "sea_states", "pto_optimization"]:
            assert key in results, f"Missing top-level key: {key}"

    def test_irf_keys(self, results):
        irf = results["irf"]
        for key in ["time", "K_r", "K_r_at_zero"]:
            assert key in irf, f"Missing irf key: {key}"
        assert len(irf["time"]) == len(irf["K_r"])
        assert len(irf["time"]) > 100

    def test_state_space_keys(self, results):
        ss = results["state_space"]
        for key in ["order", "R2", "A", "B", "C", "eigenvalues_real"]:
            assert key in ss, f"Missing state_space key: {key}"
        n = ss["order"]
        assert len(ss["A"]) == n
        assert all(len(row) == n for row in ss["A"])
        assert len(ss["B"]) == n
        assert len(ss["eigenvalues_real"]) == n

    def test_all_sea_states_present(self, results, sea_state_ids):
        for ss_id in sea_state_ids:
            assert ss_id in results["sea_states"], \
                f"Missing sea state: {ss_id}"

    def test_per_sea_state_keys(self, results, sea_state_ids):
        for ss_id in sea_state_ids:
            ss = results["sea_states"][ss_id]
            for key in ["wave", "simulation", "power_curve"]:
                assert key in ss, f"Missing key '{key}' in sea_state '{ss_id}'"
            for key in ["m0", "m2", "Hm0", "Tm02"]:
                assert key in ss["wave"], \
                    f"Missing wave key '{key}' in '{ss_id}'"
            for key in ["heave_max", "heave_std", "heave_mean"]:
                assert key in ss["simulation"], \
                    f"Missing simulation key '{key}' in '{ss_id}'"

    def test_pto_optimization_keys(self, results):
        pto = results["pto_optimization"]
        for section in ["unconstrained", "constrained"]:
            assert section in pto, f"Missing pto_optimization.{section}"
        for key in ["optimal_damping", "weighted_avg_power"]:
            assert key in pto["unconstrained"], \
                f"Missing unconstrained.{key}"
            assert key in pto["constrained"], \
                f"Missing constrained.{key}"
        assert "binding_sea_states" in pto["constrained"], \
            "Missing constrained.binding_sea_states"


# ──────────────────────────────────────────────
# IRF tests
# ──────────────────────────────────────────────
class TestIRF:
    def _compute_K_r_at_zero(self, hydro):
        """Independently compute K_r(0) = (2/pi) * integral(B(omega), 0, inf)."""
        omegas = hydro["omega"]
        B33 = hydro["B33"]
        integral = 0.5 * B33[0] * omegas[0]
        for i in range(len(omegas) - 1):
            integral += 0.5 * (B33[i] + B33[i + 1]) * (omegas[i + 1] - omegas[i])
        return (2.0 / math.pi) * integral

    def test_K_r_at_zero(self, results, hydro):
        expected = self._compute_K_r_at_zero(hydro)
        actual = results["irf"]["K_r_at_zero"]
        rel_err = abs(actual - expected) / abs(expected)
        assert rel_err < 0.02, \
            f"K_r(0) error {rel_err:.4f} exceeds 2%: got {actual}, expected {expected}"

    def test_irf_positive_at_zero(self, results):
        assert results["irf"]["K_r_at_zero"] > 0

    def test_irf_decays(self, results):
        K_r = np.array(results["irf"]["K_r"])
        peak = np.max(np.abs(K_r))
        n = len(K_r)
        tail = K_r[int(0.9 * n):]
        assert np.all(np.abs(tail) < 0.01 * peak), \
            f"IRF tail max {np.max(np.abs(tail)):.2f} exceeds 1% of peak {peak:.2f}"

    def test_irf_length_matches_config(self, results, config):
        time = np.array(results["irf"]["time"])
        expected_dur = config["state_space"]["irf_duration"]
        assert abs(time[-1] - expected_dur) < 1.0, \
            f"IRF duration {time[-1]} doesn't match config {expected_dur}"


# ──────────────────────────────────────────────
# State-space tests
# ──────────────────────────────────────────────
class TestStateSpace:
    def test_order_range(self, results, config):
        n = results["state_space"]["order"]
        assert 2 <= n <= config["state_space"]["max_order"], \
            f"SS order {n} outside [2, {config['state_space']['max_order']}]"

    def test_r2_threshold(self, results, config):
        assert results["state_space"]["R2"] >= config["state_space"]["r2_threshold"], \
            f"SS R2 {results['state_space']['R2']} < threshold"

    def test_stability(self, results):
        eigs = results["state_space"]["eigenvalues_real"]
        for i, e in enumerate(eigs):
            assert e < 0, f"Eigenvalue {i} has non-negative real part: {e}"

    def test_ss_reproduces_irf(self, results):
        A = np.array(results["state_space"]["A"])
        B_mat = np.array(results["state_space"]["B"])
        C_mat = np.array(results["state_space"]["C"])
        K_r_ref = np.array(results["irf"]["K_r"])
        time = np.array(results["irf"]["time"])

        if B_mat.ndim == 1:
            B_mat = B_mat.reshape(-1, 1)
        if C_mat.ndim == 1:
            C_mat = C_mat.reshape(1, -1)

        step = max(1, len(time) // 120)
        idx = np.arange(0, len(time), step)
        time_sub = time[idx]
        K_r_sub = K_r_ref[idx]

        K_r_ss = np.zeros(len(time_sub))
        for i, t in enumerate(time_sub):
            val = C_mat @ expm(A * t) @ B_mat
            K_r_ss[i] = float(np.squeeze(val))

        ss_res = np.sum((K_r_sub - K_r_ss) ** 2)
        ss_tot = np.sum((K_r_sub - np.mean(K_r_sub)) ** 2)
        R2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        assert R2 >= 0.95, f"SS reproduction R2 = {R2:.4f} < 0.95"


# ──────────────────────────────────────────────
# Per-sea-state wave spectrum tests
# ──────────────────────────────────────────────
class TestWave:
    def test_m0_matches_Hs(self, results, config):
        for ss_cfg in config["sea_states"]:
            ss_id = ss_cfg["id"]
            Hs = ss_cfg["Hs"]
            expected_m0 = (Hs / 4.0) ** 2
            actual_m0 = results["sea_states"][ss_id]["wave"]["m0"]
            rel_err = abs(actual_m0 - expected_m0) / expected_m0
            assert rel_err < 0.05, \
                f"[{ss_id}] m0 error {rel_err:.4f}: got {actual_m0}, expected {expected_m0}"

    def test_Hm0_matches_Hs(self, results, config):
        for ss_cfg in config["sea_states"]:
            ss_id = ss_cfg["id"]
            Hs = ss_cfg["Hs"]
            Hm0 = results["sea_states"][ss_id]["wave"]["Hm0"]
            rel_err = abs(Hm0 - Hs) / Hs
            assert rel_err < 0.05, \
                f"[{ss_id}] Hm0 error {rel_err:.4f}: got {Hm0}, expected {Hs}"

    def test_m2_positive(self, results, config):
        for ss_cfg in config["sea_states"]:
            ss_id = ss_cfg["id"]
            assert results["sea_states"][ss_id]["wave"]["m2"] > 0, \
                f"[{ss_id}] m2 not positive"

    def test_Tm02_reasonable(self, results, config):
        for ss_cfg in config["sea_states"]:
            ss_id = ss_cfg["id"]
            Tp = ss_cfg["Tp"]
            Tm02 = results["sea_states"][ss_id]["wave"]["Tm02"]
            assert 0.5 * Tp < Tm02 < 1.1 * Tp, \
                f"[{ss_id}] Tm02 = {Tm02} outside expected range for Tp = {Tp}"


# ──────────────────────────────────────────────
# Per-sea-state simulation sanity tests
# ──────────────────────────────────────────────
class TestSimulation:
    def test_heave_bounded(self, results, config):
        for ss_cfg in config["sea_states"]:
            ss_id = ss_cfg["id"]
            Hs = ss_cfg["Hs"]
            heave_max = results["sea_states"][ss_id]["simulation"]["heave_max"]
            assert heave_max < 5.0 * Hs, \
                f"[{ss_id}] heave_max {heave_max} exceeds 5*Hs={5*Hs}"

    def test_heave_mean_near_zero(self, results, config):
        for ss_cfg in config["sea_states"]:
            ss_id = ss_cfg["id"]
            heave_mean = results["sea_states"][ss_id]["simulation"]["heave_mean"]
            assert abs(heave_mean) < 1.0, \
                f"[{ss_id}] heave_mean {heave_mean} not near zero"

    def test_heave_std_positive(self, results, config):
        for ss_cfg in config["sea_states"]:
            ss_id = ss_cfg["id"]
            assert results["sea_states"][ss_id]["simulation"]["heave_std"] > 0, \
                f"[{ss_id}] heave_std not positive"

    def test_heave_std_scales_with_Hs(self, results, config):
        """Heave std should generally increase with significant wave height."""
        sea_states_sorted = sorted(config["sea_states"], key=lambda s: s["Hs"])
        stds = [results["sea_states"][ss["id"]]["simulation"]["heave_std"]
                for ss in sea_states_sorted]
        assert stds[-1] > stds[0], \
            "Heave std does not increase from mildest to most energetic sea state"


# ──────────────────────────────────────────────
# Power curve tests
# ──────────────────────────────────────────────
class TestPowerCurve:
    def test_power_curve_length(self, results, config):
        n = config["pto"]["damping_sweep"]["n_points"]
        for ss_id, ss_res in results["sea_states"].items():
            assert len(ss_res["power_curve"]) == n, \
                f"[{ss_id}] power_curve length {len(ss_res['power_curve'])} != {n}"

    def test_power_all_non_negative(self, results):
        for ss_id, ss_res in results["sea_states"].items():
            for damping, power in ss_res["power_curve"]:
                assert damping > 0, \
                    f"[{ss_id}] Non-positive damping: {damping}"
                assert power >= 0, \
                    f"[{ss_id}] Negative power at damping {damping}: {power}"

    def test_power_curve_has_peak(self, results):
        """At least one sea state's power curve should have an interior peak."""
        has_interior_peak = False
        for ss_id, ss_res in results["sea_states"].items():
            powers = [p for _, p in ss_res["power_curve"]]
            max_idx = np.argmax(powers)
            if 0 < max_idx < len(powers) - 1:
                has_interior_peak = True
                break
        assert has_interior_peak, \
            "No sea state has an interior power peak — sweep range may be wrong"

    def test_power_increases_with_sea_state(self, results, config):
        """More energetic sea states should produce more power at their peaks."""
        sea_states_sorted = sorted(config["sea_states"], key=lambda s: s["Hs"])
        max_powers = []
        for ss in sea_states_sorted:
            curve = results["sea_states"][ss["id"]]["power_curve"]
            max_powers.append(max(p for _, p in curve))
        assert max_powers[-1] > max_powers[0], \
            "Peak power does not increase from mildest to most energetic sea state"


# ──────────────────────────────────────────────
# Unconstrained optimization tests
# ──────────────────────────────────────────────
class TestUnconstrainedOptimization:
    def test_damping_in_range(self, results, config):
        d_min = config["pto"]["damping_sweep"]["min"]
        d_max = config["pto"]["damping_sweep"]["max"]
        d_opt = results["pto_optimization"]["unconstrained"]["optimal_damping"]
        assert d_min <= d_opt <= d_max, \
            f"Unconstrained optimal damping {d_opt} outside [{d_min}, {d_max}]"

    def test_power_positive(self, results):
        assert results["pto_optimization"]["unconstrained"]["weighted_avg_power"] > 0

    def test_is_weighted_maximum(self, results, config):
        """Verify the claimed optimum matches the weighted power curve maximum."""
        probabilities = {ss["id"]: ss["probability"]
                         for ss in config["sea_states"]}
        n_pts = config["pto"]["damping_sweep"]["n_points"]

        weighted_powers = np.zeros(n_pts)
        for ss_id, prob in probabilities.items():
            curve = results["sea_states"][ss_id]["power_curve"]
            for i, (_, power) in enumerate(curve):
                weighted_powers[i] += prob * power

        max_weighted = float(np.max(weighted_powers))
        claimed = results["pto_optimization"]["unconstrained"]["weighted_avg_power"]
        rel_err = abs(max_weighted - claimed) / max(claimed, 1e-10)
        assert rel_err < 0.01, \
            f"Claimed weighted power {claimed} != curve max {max_weighted}"

    def test_optimal_damping_matches_curve(self, results, config):
        """The optimal damping must correspond to a sweep grid point."""
        probabilities = {ss["id"]: ss["probability"]
                         for ss in config["sea_states"]}
        n_pts = config["pto"]["damping_sweep"]["n_points"]
        d_opt = results["pto_optimization"]["unconstrained"]["optimal_damping"]

        best_damping = None
        best_power = -1
        for i in range(n_pts):
            wp = 0
            d = None
            for ss_id, prob in probabilities.items():
                curve = results["sea_states"][ss_id]["power_curve"]
                d_i, p_i = curve[i]
                wp += prob * p_i
                d = d_i
            if wp > best_power:
                best_power = wp
                best_damping = d

        rel_err = abs(d_opt - best_damping) / max(abs(best_damping), 1e-10)
        assert rel_err < 0.01, \
            f"Optimal damping {d_opt} != grid maximum {best_damping}"


# ──────────────────────────────────────────────
# Constrained optimization tests
# ──────────────────────────────────────────────
class TestConstrainedOptimization:
    def test_damping_in_range(self, results, config):
        d_min = config["pto"]["damping_sweep"]["min"]
        d_max = config["pto"]["damping_sweep"]["max"]
        d_opt = results["pto_optimization"]["constrained"]["optimal_damping"]
        assert d_min <= d_opt <= d_max, \
            f"Constrained optimal damping {d_opt} outside [{d_min}, {d_max}]"

    def test_power_bounded_by_unconstrained(self, results):
        """Constrained power cannot exceed unconstrained."""
        con = results["pto_optimization"]["constrained"]["weighted_avg_power"]
        unc = results["pto_optimization"]["unconstrained"]["weighted_avg_power"]
        assert con <= unc * 1.001, \
            f"Constrained power {con} exceeds unconstrained {unc}"

    def test_binding_sea_states_subset(self, results, sea_state_ids):
        binding = results["pto_optimization"]["constrained"]["binding_sea_states"]
        assert isinstance(binding, list)
        for ss_id in binding:
            assert ss_id in sea_state_ids, \
                f"Binding sea state '{ss_id}' not in config"

    def test_constraint_consistency(self, results, config):
        """If constrained != unconstrained, the constraint must be active:
        at least one sea state should have heave_max near or above the limit
        at the unconstrained optimal damping."""
        unc_d = results["pto_optimization"]["unconstrained"]["optimal_damping"]
        con_d = results["pto_optimization"]["constrained"]["optimal_damping"]
        limit = config["constraints"]["max_heave_amplitude"]

        if abs(unc_d - con_d) / max(abs(unc_d), 1.0) > 0.01:
            max_heaves = [ss_res["simulation"]["heave_max"]
                          for ss_res in results["sea_states"].values()]
            assert max(max_heaves) >= limit * 0.90, \
                f"Constraint active but no sea state has heave near limit " \
                f"{limit}: max heave = {max(max_heaves)}"

    def test_constrained_differs_from_unconstrained(self, results, config):
        """With max_heave_amplitude=1.5 and energetic Hs=4.0,
        the constraint should be active."""
        unc_d = results["pto_optimization"]["unconstrained"]["optimal_damping"]
        con_d = results["pto_optimization"]["constrained"]["optimal_damping"]
        con_p = results["pto_optimization"]["constrained"]["weighted_avg_power"]
        unc_p = results["pto_optimization"]["unconstrained"]["weighted_avg_power"]
        if abs(unc_d - con_d) / max(abs(unc_d), 1.0) > 0.01:
            assert con_p < unc_p, \
                "Constrained and unconstrained differ in damping but not power"
            binding = results["pto_optimization"]["constrained"]["binding_sea_states"]
            assert len(binding) > 0, \
                "Constraint active but no binding sea states reported"


# ──────────────────────────────────────────────
# Frequency-domain cross-check
# ──────────────────────────────────────────────
class TestFrequencyDomainCrossCheck:
    def _jonswap_spectrum(self, f, Hs, Tp, gamma):
        fp = 1.0 / Tp
        if f <= 0:
            return 0.0
        sigma = 0.07 if f <= fp else 0.09
        alpha_exp = math.exp(-((f / fp - 1.0) ** 2) / (2.0 * sigma ** 2))
        C_gamma = 1.0 - 0.287 * math.log(gamma)
        S_pm = (5.0 / 16.0) * Hs ** 2 * fp ** 4 * f ** (-5) * \
               math.exp(-1.25 * (fp / f) ** 4)
        return C_gamma * S_pm * gamma ** alpha_exp

    def test_heave_std_frequency_domain(self, results, hydro, config):
        """Frequency-domain heave std should approximately match time-domain
        for at least the mildest sea state (most linear behavior)."""
        mildest = min(config["sea_states"], key=lambda s: s["Hs"])
        ss_id = mildest["id"]
        Hs = mildest["Hs"]
        Tp = mildest["Tp"]
        gamma = mildest["gamma"]

        C_pto = results["pto_optimization"]["unconstrained"]["optimal_damping"]
        K_hs = hydro["body"]["hydrostatic_stiffness"]
        mass = hydro["body"]["mass"]

        omegas = np.array(hydro["omega"])
        A33 = np.array(hydro["A33"])
        B33 = np.array(hydro["B33"])
        Fexc_re = np.array(hydro["Fexc_re"])
        Fexc_im = np.array(hydro["Fexc_im"])

        m0_z = 0.0
        for i in range(len(omegas)):
            omega = omegas[i]
            f = omega / (2.0 * math.pi)
            S_f = self._jonswap_spectrum(f, Hs, Tp, gamma)
            S_omega = S_f / (2.0 * math.pi)

            F_exc = complex(Fexc_re[i], Fexc_im[i])
            Z = complex(K_hs - omega ** 2 * (mass + A33[i]),
                        omega * (B33[i] + C_pto))
            RAO = F_exc / Z
            S_z = abs(RAO) ** 2 * S_omega

            if i < len(omegas) - 1:
                d_omega = omegas[i + 1] - omegas[i]
            else:
                d_omega = omegas[i] - omegas[i - 1]
            m0_z += S_z * d_omega

        sigma_z_fd = math.sqrt(m0_z)
        sigma_z_td = results["sea_states"][ss_id]["simulation"]["heave_std"]

        rel_err = abs(sigma_z_td - sigma_z_fd) / sigma_z_fd
        assert rel_err < 0.30, \
            f"[{ss_id}] Heave std mismatch: TD={sigma_z_td:.4f}, " \
            f"FD={sigma_z_fd:.4f}, error={rel_err:.2%}"

    def test_relative_heave_std_across_sea_states(self, results, config):
        """FD analysis predicts heave_std scales roughly with Hs.
        Check that the ratio of heave_stds roughly follows ratio of Hs."""
        sea_states_sorted = sorted(config["sea_states"], key=lambda s: s["Hs"])
        stds = [results["sea_states"][ss["id"]]["simulation"]["heave_std"]
                for ss in sea_states_sorted]
        hs_vals = [ss["Hs"] for ss in sea_states_sorted]

        ratio_hs = hs_vals[-1] / hs_vals[0]
        ratio_std = stds[-1] / stds[0]
        assert ratio_std > 0.3 * ratio_hs, \
            f"Heave std ratio {ratio_std:.2f} too small compared to " \
            f"Hs ratio {ratio_hs:.2f}"
