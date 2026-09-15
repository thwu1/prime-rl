
import sys
import os
import json
import subprocess
import pytest
import numpy as np

sys.path.insert(0, "/app")


# ===========================================================================
# Fortran module tests
# ===========================================================================
class TestFortranModule:
    """Tests for the compiled Fortran sedtrans module."""

    def test_module_importable(self):
        """The sedtrans shared module must be importable from /app."""
        import sedtrans

    def test_has_fall_velocity(self):
        """Module must expose fall_velocity function."""
        import sedtrans
        assert callable(sedtrans.fall_velocity)

    def test_has_equilibrium_profile(self):
        """Module must expose equilibrium_profile function."""
        import sedtrans
        assert callable(sedtrans.equilibrium_profile)

    def test_fortran_fall_velocity_stokes(self):
        """Fortran fall_velocity for very fine sediment (Stokes regime)."""
        import sedtrans
        ws = sedtrans.fall_velocity(50e-6, 15.0)
        assert 0.0017 < float(ws) < 0.0021, f"ws={ws}"

    def test_fortran_fall_velocity_sand(self):
        """Fortran fall_velocity for D50=200um (transitional regime)."""
        import sedtrans
        ws = sedtrans.fall_velocity(0.0002, 15.0)
        assert 0.020 < float(ws) < 0.025, f"ws={ws}"

    def test_fortran_equilibrium_profile_shape(self):
        """Equilibrium profile must deepen monotonically offshore."""
        import sedtrans
        x = np.array([0.0, 10.0, 50.0, 100.0])
        z = sedtrans.equilibrium_profile(x, 0.1, 0.0)
        assert len(z) == 4
        assert abs(z[0]) < 1e-10, f"z(0)={z[0]} should be 0"
        for i in range(1, len(z)):
            assert z[i] < z[i - 1], f"z[{i}]={z[i]} >= z[{i-1}]={z[i-1]}"

    def test_fortran_equilibrium_profile_landward(self):
        """Landward points (x<0) should equal z_offset."""
        import sedtrans
        x = np.array([-20.0, -10.0, 0.0])
        z = sedtrans.equilibrium_profile(x, 0.1, 2.0)
        assert abs(z[0] - 2.0) < 1e-10, f"z(-20)={z[0]}"
        assert abs(z[1] - 2.0) < 1e-10, f"z(-10)={z[1]}"


# ===========================================================================
# Fall velocity tests
# ===========================================================================
class TestFallVelocity:
    """Verify fall_velocity_vanrijn across all settling regimes."""

    def _ws(self, D50, temperature=15.0):
        from coastal_diag.profiles import fall_velocity_vanrijn
        return fall_velocity_vanrijn(D50, temperature)

    def test_stokes_regime(self):
        """D50 = 50 um sits in the Stokes (viscous) regime."""
        ws = self._ws(50e-6)
        assert 0.0017 < ws < 0.0021, f"Stokes ws={ws}"

    def test_transitional_variable_coefw(self):
        """D50 = 100 um: transitional regime with grain-dependent coefficient."""
        ws = self._ws(100e-6)
        assert 0.0070 < ws < 0.0080, f"Transitional variable coefw ws={ws}"

    def test_transitional_fixed_coefw(self):
        """D50 = 200 um: transitional regime with standard coefficient."""
        ws = self._ws(200e-6)
        assert 0.0215 < ws < 0.0240, f"Transitional fixed coefw ws={ws}"

    def test_impact_regime(self):
        """D50 = 3 mm falls into the impact/inertia regime."""
        ws = self._ws(3e-3)
        assert 0.225 < ws < 0.250, f"Impact ws={ws}"

    def test_monotonicity(self):
        """Fall velocity must increase monotonically with grain size."""
        sizes = [50e-6, 100e-6, 200e-6, 500e-6, 1e-3, 3e-3]
        velocities = [self._ws(d) for d in sizes]
        for i in range(len(velocities) - 1):
            assert velocities[i] < velocities[i + 1], (
                f"ws({sizes[i]})={velocities[i]} >= ws({sizes[i+1]})={velocities[i+1]}"
            )

    def test_temperature_effect(self):
        """Higher temperature -> lower viscosity -> higher fall velocity."""
        ws_cold = self._ws(200e-6, temperature=10.0)
        ws_warm = self._ws(200e-6, temperature=25.0)
        assert ws_cold < ws_warm, f"ws(10C)={ws_cold} >= ws(25C)={ws_warm}"

    def test_positive(self):
        """Fall velocity must always be positive for physical grain sizes."""
        for D50 in [30e-6, 64e-6, 96e-6, 128e-6, 500e-6, 2e-3, 5e-3]:
            ws = self._ws(D50)
            assert ws > 0, f"ws({D50}) = {ws} <= 0"


# ===========================================================================
# Dean profile tests
# ===========================================================================
class TestDeanProfile:
    """Verify Dean equilibrium profile geometry and physics."""

    def _profile(self, x, **kwargs):
        from coastal_diag.profiles import dean_profile
        return dean_profile(np.asarray(x, dtype=float), **kwargs)

    def test_shoreline_value(self):
        """At x=0, elevation equals z_offset."""
        z = self._profile([0.0], D50=200e-6, z_offset=1.5)
        assert abs(z[0] - 1.5) < 1e-10

    def test_offshore_monotonically_decreasing(self):
        """Profile deepens monotonically moving offshore (x > 0)."""
        x = np.arange(0, 201, 5, dtype=float)
        z = self._profile(x, D50=200e-6)
        for i in range(len(z) - 1):
            assert z[i + 1] <= z[i], f"z[{i+1}]={z[i+1]} > z[{i}]={z[i]}"

    def test_landward_increasing(self):
        """Landward (x<0) profile rises linearly with beta_dry."""
        x = np.array([-50, -40, -30, -20, -10], dtype=float)
        z = self._profile(x, D50=200e-6, beta_dry=0.1)
        expected = 0.1 * np.abs(x)
        np.testing.assert_allclose(z, expected, atol=1e-10)

    def test_beta_dry_slope(self):
        """Different beta_dry values produce correct landward slopes."""
        x = np.array([-20, -10], dtype=float)
        z1 = self._profile(x, D50=200e-6, beta_dry=0.05)
        z2 = self._profile(x, D50=200e-6, beta_dry=0.2)
        assert z1[0] < z2[0]

    def test_z_offset(self):
        """z_offset shifts the entire profile vertically."""
        x = np.array([-10, 0, 10, 50], dtype=float)
        z0 = self._profile(x, D50=200e-6, z_offset=0.0)
        z2 = self._profile(x, D50=200e-6, z_offset=2.0)
        np.testing.assert_allclose(z2 - z0, 2.0, atol=1e-10)

    def test_dean_parameter_A_range(self):
        """For D50=200 um, the scale parameter A should be in physical range."""
        from coastal_diag.profiles import fall_velocity_vanrijn
        ws = fall_velocity_vanrijn(200e-6)
        A = 0.51 * ws ** 0.44
        assert 0.090 < A < 0.105, f"A={A}"

    def test_profile_depth_at_100m(self):
        """Depth at x=100 m for D50=200 um should be physically reasonable."""
        z = self._profile([100.0], D50=200e-6)
        assert -2.5 < z[0] < -1.8, f"z(100)={z[0]}"


# ===========================================================================
# JONSWAP spectrum tests
# ===========================================================================
class TestJONSWAP:
    """Verify JONSWAP spectral density computation."""

    def test_hm0_integral(self):
        """Spectral integral must recover the input Hm0."""
        from coastal_diag.spectra import jonswap_spectrum
        f = np.linspace(0.01, 1.0, 10000)
        S = jonswap_spectrum(f, Hm0=3.0, Tp=8.0, gamma=3.3)
        m0 = np.trapz(S, f)
        Hm0_check = 4.0 * np.sqrt(m0)
        assert abs(Hm0_check - 3.0) < 0.06, f"Hm0_check={Hm0_check}"

    def test_peak_frequency(self):
        """Spectral peak must occur near f_p = 1/Tp."""
        from coastal_diag.spectra import jonswap_spectrum
        f = np.linspace(0.01, 1.0, 10000)
        S = jonswap_spectrum(f, Hm0=3.0, Tp=8.0, gamma=3.3)
        f_peak = f[np.argmax(S)]
        assert abs(f_peak - 1.0 / 8.0) < 0.01, f"f_peak={f_peak}"

    def test_positive_values(self):
        """Spectral density must be non-negative everywhere."""
        from coastal_diag.spectra import jonswap_spectrum
        f = np.linspace(0.01, 1.0, 5000)
        S = jonswap_spectrum(f, Hm0=3.0, Tp=8.0)
        assert np.all(S >= 0), "Negative spectral density found"

    def test_gamma_effect(self):
        """Higher gamma -> more peaked spectrum (higher peak value)."""
        from coastal_diag.spectra import jonswap_spectrum
        f = np.linspace(0.01, 1.0, 5000)
        S_low = jonswap_spectrum(f, Hm0=3.0, Tp=8.0, gamma=1.0)
        S_high = jonswap_spectrum(f, Hm0=3.0, Tp=8.0, gamma=7.0)
        assert np.max(S_high) > np.max(S_low), "Higher gamma should produce sharper peak"

    def test_different_hm0(self):
        """Doubling Hm0 should quadruple the spectral energy."""
        from coastal_diag.spectra import jonswap_spectrum
        f = np.linspace(0.01, 1.0, 10000)
        S1 = jonswap_spectrum(f, Hm0=2.0, Tp=8.0)
        S2 = jonswap_spectrum(f, Hm0=4.0, Tp=8.0)
        m0_1 = np.trapz(S1, f)
        m0_2 = np.trapz(S2, f)
        ratio = m0_2 / m0_1
        assert abs(ratio - 4.0) < 0.2, f"Energy ratio={ratio}, expected 4.0"


# ===========================================================================
# Directional spreading tests
# ===========================================================================
class TestDirectionalSpreading:
    """Verify cosine-power directional spreading function."""

    def test_normalization(self):
        """D(theta) must integrate to 1 over full circle."""
        from coastal_diag.spectra import directional_spreading
        theta = np.linspace(-np.pi, np.pi, 3600)
        D = directional_spreading(theta, 0.0, s=10)
        integral = np.trapz(D, theta)
        assert abs(integral - 1.0) < 0.02, f"Integral={integral}"

    def test_symmetry(self):
        """D(theta) should be symmetric around theta_mean."""
        from coastal_diag.spectra import directional_spreading
        theta = np.linspace(-np.pi, np.pi, 1001)
        D = directional_spreading(theta, 0.0, s=10)
        np.testing.assert_allclose(D, D[::-1], atol=1e-6)

    def test_peak_at_mean(self):
        """Maximum D(theta) should be at theta_mean."""
        from coastal_diag.spectra import directional_spreading
        theta = np.linspace(-np.pi, np.pi, 1001)
        theta_mean = 0.5
        D = directional_spreading(theta, theta_mean, s=20)
        peak_theta = theta[np.argmax(D)]
        assert abs(peak_theta - theta_mean) < 0.01, f"peak at {peak_theta}"

    def test_narrower_with_higher_s(self):
        """Higher s should produce narrower (more peaked) distribution."""
        from coastal_diag.spectra import directional_spreading
        theta = np.linspace(-np.pi, np.pi, 1001)
        D_wide = directional_spreading(theta, 0.0, s=2)
        D_narrow = directional_spreading(theta, 0.0, s=50)
        assert np.max(D_narrow) > np.max(D_wide)


# ===========================================================================
# Brier Skill Score tests
# ===========================================================================
class TestBSS:
    """Verify Brier Skill Score computation."""

    def test_perfect_prediction(self):
        """BSS = 1 when predicted == observed."""
        from coastal_diag.metrics import brier_skill_score
        obs = np.array([1.0, 2.0, 3.0, 4.0])
        baseline = np.array([0.0, 0.0, 0.0, 0.0])
        bss = brier_skill_score(obs, obs, baseline)
        assert abs(bss - 1.0) < 1e-10, f"BSS={bss}"

    def test_baseline_prediction(self):
        """BSS = 0 when predicted == baseline."""
        from coastal_diag.metrics import brier_skill_score
        obs = np.array([1.0, 2.0, 3.0, 4.0])
        baseline = np.array([0.0, 0.0, 0.0, 0.0])
        bss = brier_skill_score(baseline, obs, baseline)
        assert abs(bss) < 1e-10, f"BSS={bss}"

    def test_worse_than_baseline(self):
        """BSS < 0 when prediction is worse than baseline."""
        from coastal_diag.metrics import brier_skill_score
        obs = np.array([1.0, 2.0, 3.0])
        baseline = np.array([0.9, 1.9, 2.9])
        pred = np.array([10.0, 20.0, 30.0])
        bss = brier_skill_score(pred, obs, baseline)
        assert bss < 0, f"BSS={bss} should be negative"

    def test_numerical_values(self):
        """Verify BSS against hand-computed values."""
        from coastal_diag.metrics import brier_skill_score
        pred = np.array([2.0, 3.0, 4.0, 5.0])
        obs = np.array([2.1, 3.2, 3.8, 5.1])
        baseline = np.array([1.0, 1.0, 1.0, 1.0])
        bss = brier_skill_score(pred, obs, baseline)
        assert abs(bss - 0.99674) < 0.001, f"BSS={bss}"


# ===========================================================================
# RMSE tests
# ===========================================================================
class TestRMSE:
    """Verify root-mean-square error computation."""

    def test_zero_error(self):
        from coastal_diag.metrics import rmse
        a = np.array([1.0, 2.0, 3.0])
        assert rmse(a, a) < 1e-15

    def test_constant_error(self):
        from coastal_diag.metrics import rmse
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([1.0, 1.0, 1.0])
        assert abs(rmse(a, b) - 1.0) < 1e-10

    def test_known_values(self):
        from coastal_diag.metrics import rmse
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([2.0, 4.0, 6.0])
        r = rmse(a, b)
        assert abs(r - np.sqrt(14.0 / 3.0)) < 1e-10, f"RMSE={r}"


# ===========================================================================
# Volume change tests
# ===========================================================================
class TestVolumeChange:
    """Verify net volume change computation."""

    def test_no_change(self):
        from coastal_diag.metrics import volume_change
        z = np.array([1.0, 2.0, 3.0])
        assert abs(volume_change(z, z, dx=2.0)) < 1e-10

    def test_known_change_1d(self):
        from coastal_diag.metrics import volume_change
        z0 = np.array([1.0, 2.0, 3.0])
        zf = np.array([1.5, 2.5, 3.5])
        vol = volume_change(z0, zf, dx=2.0)
        assert abs(vol - 3.0) < 1e-10, f"vol={vol}"

    def test_2d_volume(self):
        from coastal_diag.metrics import volume_change
        z0 = np.array([0.0, 0.0, 0.0])
        zf = np.array([1.0, 1.0, 1.0])
        vol = volume_change(z0, zf, dx=2.0, dy=5.0)
        assert abs(vol - 30.0) < 1e-10, f"vol={vol}"


# ===========================================================================
# Mass balance check tests
# ===========================================================================
class TestMassBalance:
    """Verify mass balance check logic."""

    def test_no_change(self):
        from coastal_diag.metrics import mass_balance_check
        z = np.array([1.0, 2.0, 3.0])
        passed, error = mass_balance_check(z, z, dx=1.0, threshold=0.1)
        assert passed is True
        assert abs(error) < 1e-10

    def test_within_threshold(self):
        from coastal_diag.metrics import mass_balance_check
        z0 = np.array([0.0, 0.0])
        zf = np.array([0.5, 0.5])
        passed, error = mass_balance_check(z0, zf, dx=1.0, threshold=5.0)
        assert passed is True
        assert abs(error - 1.0) < 1e-10

    def test_exceeds_threshold(self):
        from coastal_diag.metrics import mass_balance_check
        z0 = np.array([0.0, 0.0])
        zf = np.array([10.0, 10.0])
        passed, error = mass_balance_check(z0, zf, dx=1.0, threshold=5.0)
        assert passed is False
        assert abs(error - 20.0) < 1e-10


# ===========================================================================
# Slope check tests
# ===========================================================================
class TestSlopeCheck:
    """Verify finite-difference slope verification."""

    def test_uniform_slope(self):
        from coastal_diag.verification import slope_check
        z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        result = slope_check(z, dx=1.0, locations=[0, 2, -1],
                             expected_slopes=[1.0, 1.0, 1.0], tolerance=0.1)
        assert result["passed"] is True

    def test_pass_with_tolerance(self):
        from coastal_diag.verification import slope_check
        z = np.array([0.0, 1.05, 2.1])
        result = slope_check(z, dx=1.0, locations=[0, 1],
                             expected_slopes=[1.0, 1.0], tolerance=0.1)
        assert result["passed"] is True

    def test_fail_out_of_tolerance(self):
        from coastal_diag.verification import slope_check
        z = np.array([0.0, 2.0, 3.0])
        result = slope_check(z, dx=1.0, locations=[0],
                             expected_slopes=[1.0], tolerance=0.1)
        assert result["passed"] is False

    def test_details_structure(self):
        from coastal_diag.verification import slope_check
        z = np.array([0.0, 1.0, 2.0])
        result = slope_check(z, dx=1.0, locations=[0],
                             expected_slopes=[1.0], tolerance=0.1)
        assert "details" in result
        assert len(result["details"]) == 1
        d = result["details"][0]
        assert "location" in d
        assert "expected" in d
        assert "actual" in d
        assert "passed" in d


# ===========================================================================
# Bed level change check tests
# ===========================================================================
class TestBedLevelChange:
    """Verify bed level change detection."""

    def test_change_detected(self):
        from coastal_diag.verification import bed_level_change_check
        z0 = np.array([1.0, 2.0, 3.0])
        zf = np.array([1.1, 2.2, 3.3])
        result = bed_level_change_check(z0, zf)
        assert result["passed"] is True
        assert result["mean_abs_change"] > 0

    def test_no_change(self):
        from coastal_diag.verification import bed_level_change_check
        z = np.array([1.0, 2.0, 3.0])
        result = bed_level_change_check(z, z)
        assert result["passed"] is False
        assert result["mean_abs_change"] == 0.0


# ===========================================================================
# run_diagnostics integration test
# ===========================================================================
class TestRunDiagnostics:
    """Verify the combined diagnostic runner."""

    def test_basic_pass(self):
        from coastal_diag.verification import run_diagnostics
        config = {
            "z_pre": [0.0, 1.0, 2.0, 3.0, 4.0],
            "z_sim": [0.1, 1.1, 2.1, 3.1, 4.1],
            "z_obs": [0.1, 1.1, 2.1, 3.1, 4.1],
            "dx": 1.0,
            "dy": 1.0,
            "mass_balance_threshold": 10.0,
        }
        result = run_diagnostics(config)
        assert "overall" in result
        assert result["brier_skill_score"] == pytest.approx(1.0, abs=1e-10)
        assert result["overall"] == "PASS"

    def test_basic_fail(self):
        from coastal_diag.verification import run_diagnostics
        config = {
            "z_pre": [0.0, 0.0, 0.0],
            "z_sim": [100.0, 100.0, 100.0],
            "z_obs": [0.1, 0.1, 0.1],
            "dx": 1.0,
            "dy": 1.0,
            "mass_balance_threshold": 5.0,
        }
        result = run_diagnostics(config)
        assert result["overall"] == "FAIL"

    def test_contains_all_keys(self):
        from coastal_diag.verification import run_diagnostics
        config = {
            "z_pre": [0.0, 1.0, 2.0],
            "z_sim": [0.1, 1.1, 2.1],
            "z_obs": [0.1, 1.1, 2.1],
            "dx": 1.0,
            "dy": 1.0,
            "mass_balance_threshold": 10.0,
            "slope_locations": [0],
            "expected_slopes": [1.0],
            "slope_tolerance": 0.1,
        }
        result = run_diagnostics(config)
        assert "brier_skill_score" in result
        assert "rmse" in result
        assert "volume_change" in result
        assert "mass_balance" in result
        assert "bed_level_change" in result
        assert "slope_check" in result
        assert "overall" in result


# ===========================================================================
# CLI integration test
# ===========================================================================
class TestCLI:
    """Verify the CLI produces a valid JSON report."""

    @pytest.fixture(autouse=True)
    def run_cli(self, tmp_path):
        """Run the CLI once and store the report for all test methods."""
        self.output_path = str(tmp_path / "report.json")
        result = subprocess.run(
            [
                "python3", "/app/coastal_diag/cli.py",
                "--config", "/app/data/config.json",
                "--output", self.output_path,
            ],
            capture_output=True, text=True, cwd="/app",
            env={**os.environ, "PYTHONPATH": "/app"},
        )
        self.returncode = result.returncode
        self.stderr = result.stderr
        if os.path.exists(self.output_path):
            with open(self.output_path) as f:
                self.report = json.load(f)
        else:
            self.report = None

    def test_exit_code(self):
        assert self.returncode == 0, f"CLI failed: {self.stderr}"

    def test_output_exists(self):
        assert self.report is not None, "No report JSON produced"

    def test_report_structure(self):
        assert "fall_velocity" in self.report
        assert "dean_parameter_A" in self.report
        assert "spectrum" in self.report
        assert "peak_frequency" in self.report["spectrum"]
        assert "Hm0_check" in self.report["spectrum"]
        assert "brier_skill_score" in self.report
        assert "rmse" in self.report
        assert "volume_change" in self.report
        assert "diagnostics" in self.report
        diag = self.report["diagnostics"]
        assert "mass_balance" in diag
        assert "bed_level_change" in diag
        assert "overall" in diag

    def test_fall_velocity_range(self):
        ws = self.report["fall_velocity"]
        assert 0.020 < ws < 0.025, f"fall_velocity={ws}"

    def test_dean_parameter_range(self):
        A = self.report["dean_parameter_A"]
        assert 0.090 < A < 0.105, f"dean_parameter_A={A}"

    def test_spectrum_hm0(self):
        hm0 = self.report["spectrum"]["Hm0_check"]
        assert 2.85 < hm0 < 3.15, f"Hm0_check={hm0}"

    def test_spectrum_peak_freq(self):
        fp = self.report["spectrum"]["peak_frequency"]
        assert abs(fp - 0.125) < 0.01, f"peak_frequency={fp}"

    def test_bss_range(self):
        bss = self.report["brier_skill_score"]
        assert 0.93 < bss < 1.0, f"BSS={bss}"

    def test_rmse_range(self):
        r = self.report["rmse"]
        assert 0.02 < r < 0.08, f"RMSE={r}"

    def test_volume_change_range(self):
        vc = self.report["volume_change"]
        assert -25.0 < vc < -10.0, f"volume_change={vc}"

    def test_diagnostics_overall(self):
        assert self.report["diagnostics"]["overall"] == "PASS"
