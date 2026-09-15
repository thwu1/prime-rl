
import subprocess
import json
import csv
import os
import math
import tempfile

import numpy as np
import pytest

G = 9.80665


def _type_curve_ref(td_arr, cd):
    """Compute reference type curve values analytically."""
    td_arr = np.asarray(td_arr, dtype=float)
    alpha = cd / 2.0
    if cd < 2.0 - 1e-10:
        omega = math.sqrt(1.0 - alpha ** 2)
        return np.exp(-alpha * td_arr) * (
            np.cos(omega * td_arr) + (alpha / omega) * np.sin(omega * td_arr)
        )
    elif abs(cd - 2.0) < 1e-10:
        return (1.0 + td_arr) * np.exp(-td_arr)
    else:
        beta = math.sqrt(alpha ** 2 - 1.0)
        r1 = -alpha + beta
        r2 = -alpha - beta
        coeff_a = (alpha + beta) / (2.0 * beta)
        coeff_b = (beta - alpha) / (2.0 * beta)
        return coeff_a * np.exp(r1 * td_arr) + coeff_b * np.exp(r2 * td_arr)


def _generate_synthetic(cd, le, t0=0.0, noise_std=0.0, t_max=30.0, dt=0.1, seed=42):
    """Generate synthetic slug test field data."""
    alpha = math.sqrt(G / le)
    time_arr = np.arange(0, t_max + dt / 2, dt)
    td = alpha * (time_arr - t0)
    wd = np.ones_like(time_arr)
    mask = td >= 0
    wd[mask] = _type_curve_ref(td[mask], cd)
    if noise_std > 0:
        rng = np.random.default_rng(seed)
        wd += rng.normal(0, noise_std, len(wd))
    return time_arr, wd


def _write_csv(path, time_arr, nh_arr):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "normalized_head"])
        for t, h in zip(time_arr, nh_arr):
            writer.writerow([f"{t:.6f}", f"{h:.8f}"])


def _run_generate(cd, td_max, dt, output_path):
    result = subprocess.run(
        [
            "python3", "/app/slug_test_analyzer.py", "generate",
            "--cd", str(cd),
            "--td-max", str(td_max),
            "--dt", str(dt),
            "--output", output_path,
        ],
        capture_output=True, text=True, timeout=60,
    )
    return result


def _run_fit(data_path, output_path):
    result = subprocess.run(
        [
            "python3", "/app/slug_test_analyzer.py", "fit",
            "--data", data_path,
            "--output", output_path,
        ],
        capture_output=True, text=True, timeout=120,
    )
    return result


def _read_generated_csv(path):
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((float(row["td"]), float(row["wd"])))
    return rows


# ── Type curve generation tests ──────────────────────────────────────────


class TestGenerate:
    """Verify type curve generation accuracy."""

    def test_reference_data_match(self, tmp_path):
        """Generated curves must match the provided reference data."""
        with open("/app/reference/type_curves.json") as f:
            ref = json.load(f)

        for cd_str, points in ref["curves"].items():
            cd = float(cd_str)
            td_vals = [p[0] for p in points]
            td_max = max(td_vals)
            out = str(tmp_path / f"curve_{cd_str}.csv")
            result = _run_generate(cd, td_max, 0.5, out)
            assert result.returncode == 0, (
                f"generate failed for CD={cd}: {result.stderr}"
            )
            rows = _read_generated_csv(out)
            gen_dict = {round(r[0], 1): r[1] for r in rows}

            for td_ref, wd_ref in points:
                td_key = round(td_ref, 1)
                if td_key in gen_dict:
                    wd_gen = gen_dict[td_key]
                    assert abs(wd_gen - wd_ref) < 5e-4, (
                        f"CD={cd}, td={td_ref}: got {wd_gen}, ref {wd_ref}"
                    )

    @pytest.mark.parametrize("cd", [0.3, 0.775, 1.333, 2.0, 2.5, 4.0, 7.5, 15.0, 40.0])
    def test_analytical_match(self, cd, tmp_path):
        """Generated curves must match analytical computation for arbitrary CD."""
        out = str(tmp_path / f"curve_{cd}.csv")
        result = _run_generate(cd, 20.0, 0.5, out)
        assert result.returncode == 0, f"generate failed CD={cd}: {result.stderr}"

        rows = _read_generated_csv(out)
        for td_val, wd_gen in rows:
            wd_exp = float(_type_curve_ref(td_val, cd))
            assert abs(wd_gen - wd_exp) < 5e-4, (
                f"CD={cd}, td={td_val}: got {wd_gen}, expected {wd_exp}"
            )

    def test_large_cd_stability(self, tmp_path):
        """Must not overflow or produce NaN for large CD·td products."""
        out = str(tmp_path / "curve_large.csv")
        result = _run_generate(50.0, 100.0, 5.0, out)
        assert result.returncode == 0, f"generate failed: {result.stderr}"
        rows = _read_generated_csv(out)
        for td_val, wd_gen in rows:
            assert math.isfinite(wd_gen), f"Non-finite at td={td_val}"
            wd_exp = float(_type_curve_ref(td_val, 50.0))
            assert abs(wd_gen - wd_exp) < 5e-4, (
                f"CD=50, td={td_val}: got {wd_gen}, expected {wd_exp}"
            )

    def test_initial_condition(self, tmp_path):
        """wd must equal 1.0 at td=0 for any CD."""
        for cd in [0.1, 1.0, 2.0, 5.0, 25.0]:
            out = str(tmp_path / f"ic_{cd}.csv")
            _run_generate(cd, 1.0, 1.0, out)
            rows = _read_generated_csv(out)
            assert abs(rows[0][1] - 1.0) < 1e-6, f"wd(0) != 1 for CD={cd}"

    def test_critically_damped(self, tmp_path):
        """CD=2.0 must be exactly (1+td)*exp(-td)."""
        out = str(tmp_path / "crit.csv")
        _run_generate(2.0, 10.0, 0.1, out)
        rows = _read_generated_csv(out)
        for td_val, wd_gen in rows:
            wd_exp = (1.0 + td_val) * math.exp(-td_val)
            assert abs(wd_gen - wd_exp) < 1e-5, (
                f"Critical damping td={td_val}: got {wd_gen}, expected {wd_exp}"
            )


# ── Fitting tests ────────────────────────────────────────────────────────


class TestFit:
    """Verify parameter recovery from synthetic field data."""

    def _run_fit_scenario(self, cd_true, le_true, t0_true, tmp_path,
                          noise_std=0.0, t_max=30.0, dt=0.1, seed=42):
        time_arr, nh = _generate_synthetic(
            cd_true, le_true, t0=t0_true, noise_std=noise_std,
            t_max=t_max, dt=dt, seed=seed,
        )
        data_path = str(tmp_path / "data.csv")
        out_path = str(tmp_path / "result.json")
        _write_csv(data_path, time_arr, nh)

        result = _run_fit(data_path, out_path)
        assert result.returncode == 0, f"fit failed: {result.stderr}"

        with open(out_path) as f:
            fit_result = json.load(f)

        return fit_result

    def _check_cd(self, fit_cd, cd_true, tol=0.02):
        if cd_true > 0.5:
            assert abs(fit_cd - cd_true) / cd_true < tol, (
                f"CD: got {fit_cd:.5f}, expected {cd_true}"
            )
        else:
            assert abs(fit_cd - cd_true) < tol, (
                f"CD: got {fit_cd:.5f}, expected {cd_true}"
            )

    def _check_le(self, fit_le, le_true, tol=0.02):
        assert abs(fit_le - le_true) / le_true < tol, (
            f"Le: got {fit_le:.5f}, expected {le_true}"
        )

    def test_underdamped_clean(self, tmp_path):
        """Fit oscillatory data (CD=0.775, Le=16.99)."""
        cd, le, t0 = 0.775, 16.99, 0.5
        r = self._run_fit_scenario(cd, le, t0, tmp_path)
        self._check_cd(r["cd"], cd)
        self._check_le(r["le"], le)

    def test_overdamped_clean(self, tmp_path):
        """Fit non-oscillatory data (CD=3.5, Le=8.0)."""
        cd, le, t0 = 3.5, 8.0, 0.0
        r = self._run_fit_scenario(cd, le, t0, tmp_path)
        self._check_cd(r["cd"], cd)
        self._check_le(r["le"], le)

    def test_critical_clean(self, tmp_path):
        """Fit critically damped data (CD=2.0, Le=12.0)."""
        cd, le, t0 = 2.0, 12.0, 0.2
        r = self._run_fit_scenario(cd, le, t0, tmp_path)
        self._check_cd(r["cd"], cd)
        self._check_le(r["le"], le)

    def test_high_damping_clean(self, tmp_path):
        """Fit strongly overdamped data (CD=8.0, Le=5.0)."""
        cd, le, t0 = 8.0, 5.0, 0.0
        r = self._run_fit_scenario(cd, le, t0, tmp_path, t_max=40.0)
        self._check_cd(r["cd"], cd)
        self._check_le(r["le"], le)

    def test_underdamped_noisy(self, tmp_path):
        """Fit oscillatory data with noise (sigma=0.005)."""
        cd, le, t0 = 1.2, 14.0, 0.3
        r = self._run_fit_scenario(cd, le, t0, tmp_path, noise_std=0.005)
        self._check_cd(r["cd"], cd, tol=0.05)
        self._check_le(r["le"], le, tol=0.05)

    def test_overdamped_noisy(self, tmp_path):
        """Fit non-oscillatory data with noise (sigma=0.005)."""
        cd, le, t0 = 4.0, 10.0, 0.1
        r = self._run_fit_scenario(cd, le, t0, tmp_path, noise_std=0.005, seed=314)
        self._check_cd(r["cd"], cd, tol=0.05)
        self._check_le(r["le"], le, tol=0.05)

    def test_output_keys(self, tmp_path):
        """Result JSON must have required keys."""
        r = self._run_fit_scenario(2.0, 10.0, 0.0, tmp_path)
        for key in ["cd", "le", "alpha", "t0"]:
            assert key in r, f"Missing key: {key}"
            assert isinstance(r[key], (int, float)), f"{key} not numeric"

    def test_alpha_le_consistency(self, tmp_path):
        """alpha must equal sqrt(g/le)."""
        r = self._run_fit_scenario(3.0, 15.0, 0.0, tmp_path)
        alpha_expected = math.sqrt(G / r["le"])
        assert abs(r["alpha"] - alpha_expected) / alpha_expected < 0.001, (
            f"alpha={r['alpha']} inconsistent with le={r['le']}"
        )


# ── Batch processing tests ───────────────────────────────────────────────


class TestBatch:
    """Verify batch processing subcommand."""

    def test_batch_two_scenarios(self, tmp_path):
        """Batch processes multiple scenarios and writes individual results."""
        scenarios = [
            {"cd": 1.0, "le": 20.0, "t0": 0.0, "name": "scenario_a"},
            {"cd": 5.0, "le": 6.0, "t0": 0.5, "name": "scenario_b"},
        ]

        config_entries = []
        for sc in scenarios:
            time_arr, nh = _generate_synthetic(
                sc["cd"], sc["le"], t0=sc["t0"], t_max=25.0
            )
            data_path = str(tmp_path / f"{sc['name']}_data.csv")
            _write_csv(data_path, time_arr, nh)
            config_entries.append({
                "name": sc["name"],
                "data_file": data_path,
            })

        config_path = str(tmp_path / "batch_config.json")
        with open(config_path, "w") as f:
            json.dump({"scenarios": config_entries}, f)

        output_dir = str(tmp_path / "batch_out")
        os.makedirs(output_dir, exist_ok=True)

        result = subprocess.run(
            [
                "python3", "/app/slug_test_analyzer.py", "batch",
                "--config", config_path,
                "--output-dir", output_dir,
            ],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, f"batch failed: {result.stderr}"

        for sc in scenarios:
            out_file = os.path.join(output_dir, f"{sc['name']}.json")
            assert os.path.exists(out_file), f"Missing: {out_file}"
            with open(out_file) as f:
                r = json.load(f)
            cd_true = sc["cd"]
            le_true = sc["le"]
            if cd_true > 0.5:
                assert abs(r["cd"] - cd_true) / cd_true < 0.02
            else:
                assert abs(r["cd"] - cd_true) < 0.02
            assert abs(r["le"] - le_true) / le_true < 0.02
