#!/usr/bin/env python3
"""Tests for SUMMA-compatible snow column model.

Validates physical consistency, format correctness, parameterization
behavior, and comparison report for the single-layer snow model
with two albedo decay methods.
"""

import json
import os
import numpy as np
import netCDF4 as nc
import pytest

OUTPUT_DIR = '/app/output'
CONFIG_DIR = '/app/config'
CONDECAY_OUTPUT = os.path.join(OUTPUT_DIR, 'conDecay_output.nc')
VARDECAY_OUTPUT = os.path.join(OUTPUT_DIR, 'varDecay_output.nc')
REPORT_PATH = '/app/comparison_report.json'

# Parameters from params.txt
ALBEDO_MAX = 0.84
ALBEDO_MIN = 0.55
TAU_CONST = 86400.0
C_WARM = 5.0e-5
C_COLD = 0.001
RAIN_SNOW_THRESH = 275.15
NEW_SNOW_THRESH = 2.78e-8
DT = 3600.0  # 1 hour timestep

REQUIRED_VARS = [
    'scalarSWE', 'scalarSnowDepth', 'scalarSnowAlbedo',
    'scalarSurfaceTemp', 'scalarSenHeatTotal', 'scalarLatHeatTotal',
    'scalarRainPlusMelt', 'scalarSnowSublimation'
]


@pytest.fixture(scope='module')
def condecay_ds():
    """Open conDecay output dataset."""
    assert os.path.exists(CONDECAY_OUTPUT), \
        f"conDecay output not found: {CONDECAY_OUTPUT}"
    ds = nc.Dataset(CONDECAY_OUTPUT, 'r')
    yield ds
    ds.close()


@pytest.fixture(scope='module')
def vardecay_ds():
    """Open varDecay output dataset."""
    assert os.path.exists(VARDECAY_OUTPUT), \
        f"varDecay output not found: {VARDECAY_OUTPUT}"
    ds = nc.Dataset(VARDECAY_OUTPUT, 'r')
    yield ds
    ds.close()


@pytest.fixture(scope='module')
def forcing_ds():
    """Open forcing dataset."""
    ds = nc.Dataset('/app/data/forcing.nc', 'r')
    yield ds
    ds.close()


@pytest.fixture(scope='module')
def comparison_report():
    """Load comparison report JSON."""
    assert os.path.exists(REPORT_PATH), \
        f"Comparison report not found: {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


# ──────────────────────────────────────────────────────────────────────
# Test Suite 1: Model Execution
# ──────────────────────────────────────────────────────────────────────

class TestModelExecution:
    """Verify both model configurations produced output."""

    def test_condecay_output_exists(self):
        assert os.path.exists(CONDECAY_OUTPUT), "conDecay output file missing"

    def test_vardecay_output_exists(self):
        assert os.path.exists(VARDECAY_OUTPUT), "varDecay output file missing"


# ──────────────────────────────────────────────────────────────────────
# Test Suite 2: Output Format
# ──────────────────────────────────────────────────────────────────────

class TestOutputFormat:
    """Verify NetCDF output structure and dimensions."""

    def test_condecay_has_required_variables(self, condecay_ds):
        for var in REQUIRED_VARS:
            assert var in condecay_ds.variables, f"Missing variable: {var}"

    def test_vardecay_has_required_variables(self, vardecay_ds):
        for var in REQUIRED_VARS:
            assert var in vardecay_ds.variables, f"Missing variable: {var}"

    def test_has_time_dimension(self, condecay_ds):
        assert 'time' in condecay_ds.dimensions, "Missing 'time' dimension"

    def test_has_hru_dimension(self, condecay_ds):
        assert 'hru' in condecay_ds.dimensions, "Missing 'hru' dimension"
        assert condecay_ds.dimensions['hru'].size == 1, "hru dimension should be 1"

    def test_time_length_matches_forcing(self, condecay_ds, forcing_ds):
        n_forcing = len(forcing_ds.dimensions['time'])
        n_output = len(condecay_ds.dimensions['time'])
        assert n_output == n_forcing, \
            f"Output has {n_output} timesteps, forcing has {n_forcing}"

    def test_time_coordinate_exists(self, condecay_ds):
        assert 'time' in condecay_ds.variables, "Missing 'time' coordinate variable"
        assert len(condecay_ds.variables['time'][:]) > 0

    def test_variable_shapes(self, condecay_ds):
        n_time = len(condecay_ds.dimensions['time'])
        for var in REQUIRED_VARS:
            shape = condecay_ds.variables[var].shape
            assert shape == (n_time, 1), \
                f"{var} shape {shape} != expected ({n_time}, 1)"

    def test_no_nan_in_swe(self, condecay_ds):
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        assert not np.any(np.isnan(swe)), "NaN values in scalarSWE"

    def test_no_nan_in_depth(self, condecay_ds):
        depth = condecay_ds.variables['scalarSnowDepth'][:, 0]
        assert not np.any(np.isnan(depth)), "NaN values in scalarSnowDepth"

    def test_no_nan_in_albedo(self, condecay_ds):
        albedo = condecay_ds.variables['scalarSnowAlbedo'][:, 0]
        assert not np.any(np.isnan(albedo)), "NaN values in scalarSnowAlbedo"


# ──────────────────────────────────────────────────────────────────────
# Test Suite 3: Albedo Physics
# ──────────────────────────────────────────────────────────────────────

class TestAlbedoPhysics:
    """Verify albedo evolution correctness for both methods."""

    def test_albedo_within_bounds_condecay(self, condecay_ds):
        albedo = condecay_ds.variables['scalarSnowAlbedo'][:, 0]
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        snow_mask = swe > 0.01
        if np.any(snow_mask):
            assert np.all(albedo[snow_mask] >= ALBEDO_MIN - 0.01), \
                f"conDecay albedo below minimum: {albedo[snow_mask].min():.4f}"
            assert np.all(albedo[snow_mask] <= ALBEDO_MAX + 0.01), \
                f"conDecay albedo above maximum: {albedo[snow_mask].max():.4f}"

    def test_albedo_within_bounds_vardecay(self, vardecay_ds):
        albedo = vardecay_ds.variables['scalarSnowAlbedo'][:, 0]
        swe = vardecay_ds.variables['scalarSWE'][:, 0]
        snow_mask = swe > 0.01
        if np.any(snow_mask):
            assert np.all(albedo[snow_mask] >= ALBEDO_MIN - 0.01), \
                f"varDecay albedo below minimum: {albedo[snow_mask].min():.4f}"
            assert np.all(albedo[snow_mask] <= ALBEDO_MAX + 0.01), \
                f"varDecay albedo above maximum: {albedo[snow_mask].max():.4f}"

    def test_albedo_resets_on_snowfall(self, condecay_ds, forcing_ds):
        """Albedo should reset near albedo_max after significant snowfall."""
        albedo = condecay_ds.variables['scalarSnowAlbedo'][:, 0]
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        ppt = forcing_ds.variables['pptrate'][:, 0]
        temp = forcing_ds.variables['airtemp'][:, 0]

        snow_events = ((ppt > NEW_SNOW_THRESH * 10) &
                       (temp < RAIN_SNOW_THRESH) &
                       (swe > 0.1))

        if np.any(snow_events):
            event_indices = np.where(snow_events)[0]
            high_count = 0
            total = 0
            for idx in event_indices:
                if idx + 1 < len(albedo) and swe[idx + 1] > 0.01:
                    total += 1
                    if albedo[idx + 1] > ALBEDO_MAX - 0.05:
                        high_count += 1
            if total > 3:
                frac = high_count / total
                assert frac > 0.6, \
                    f"Only {frac:.0%} of snowfall events reset albedo near max"

    def test_condecay_exponential_decay_rate(self, condecay_ds, forcing_ds):
        """Between snow events, conDecay albedo should decay at the rate
        implied by its configured parameters."""
        albedo = condecay_ds.variables['scalarSnowAlbedo'][:, 0]
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        ppt = forcing_ds.variables['pptrate'][:, 0]
        temp = forcing_ds.variables['airtemp'][:, 0]

        no_snow_event = (ppt < NEW_SNOW_THRESH) | (temp >= RAIN_SNOW_THRESH)
        has_snow = swe > 0.5

        ratios = []
        for i in range(1, len(albedo)):
            if (no_snow_event[i] and no_snow_event[i - 1] and
                    has_snow[i] and has_snow[i - 1] and
                    albedo[i - 1] > ALBEDO_MIN + 0.03):
                denom = albedo[i - 1] - ALBEDO_MIN
                if denom > 0.01:
                    ratio = (albedo[i] - ALBEDO_MIN) / denom
                    if 0.5 < ratio < 1.0:
                        ratios.append(ratio)

        assert len(ratios) > 20, \
            f"Too few valid decay ratios to test ({len(ratios)})"

        mean_ratio = np.mean(ratios)
        expected = np.exp(-DT / TAU_CONST)
        assert abs(mean_ratio - expected) < 0.015, \
            f"Mean decay ratio {mean_ratio:.6f} != expected {expected:.6f}"

    def test_vardecay_differs_from_condecay(self, condecay_ds, vardecay_ds):
        """Variable and constant decay must produce different albedo."""
        alb_var = vardecay_ds.variables['scalarSnowAlbedo'][:, 0]
        alb_con = condecay_ds.variables['scalarSnowAlbedo'][:, 0]
        swe_var = vardecay_ds.variables['scalarSWE'][:, 0]

        snow_mask = swe_var > 0.1
        if np.sum(snow_mask) > 10:
            diff = np.abs(alb_var[snow_mask] - alb_con[snow_mask])
            assert np.max(diff) > 0.01, \
                "varDecay and conDecay produced identical albedo time series"


# ──────────────────────────────────────────────────────────────────────
# Test Suite 4: Mass Conservation
# ──────────────────────────────────────────────────────────────────────

class TestMassConservation:
    """Verify mass balance and non-negativity constraints."""

    def test_swe_nonnegative(self, condecay_ds):
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        assert np.all(swe >= -0.01), f"Negative SWE detected: {swe.min():.4f}"

    def test_depth_nonnegative(self, condecay_ds):
        depth = condecay_ds.variables['scalarSnowDepth'][:, 0]
        assert np.all(depth >= -0.001), f"Negative depth: {depth.min():.6f}"

    def test_no_snow_means_no_depth(self, condecay_ds):
        """When SWE is zero, depth must also be zero."""
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        depth = condecay_ds.variables['scalarSnowDepth'][:, 0]
        zero_swe = swe < 0.01
        if np.any(zero_swe):
            max_depth_at_zero = depth[zero_swe].max()
            assert max_depth_at_zero < 0.001, \
                f"Depth {max_depth_at_zero:.6f} m when SWE=0"

    def test_snow_density_reasonable(self, condecay_ds):
        """Implied snow density should be physically reasonable."""
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        depth = condecay_ds.variables['scalarSnowDepth'][:, 0]

        snow_mask = (swe > 1.0) & (depth > 0.001)
        if np.any(snow_mask):
            density = swe[snow_mask] / depth[snow_mask]
            assert np.all(density > 30), \
                f"Snow density impossibly low: {density.min():.1f} kg/m3"
            assert np.all(density < 800), \
                f"Snow density impossibly high: {density.max():.1f} kg/m3"

    def test_approximate_mass_balance(self, condecay_ds, forcing_ds):
        """Mass balance: snowfall ~ final SWE + melt + sublimation."""
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        ppt = forcing_ds.variables['pptrate'][:, 0]
        temp = forcing_ds.variables['airtemp'][:, 0]
        rain_melt = condecay_ds.variables['scalarRainPlusMelt'][:, 0]
        sublim = condecay_ds.variables['scalarSnowSublimation'][:, 0]

        snow_mask = temp < RAIN_SNOW_THRESH
        total_snowfall = np.sum(ppt[snow_mask]) * DT

        rain_rate = np.where(temp >= RAIN_SNOW_THRESH, ppt, 0.0)
        total_rain = np.sum(rain_rate) * DT
        total_rain_melt = np.sum(rain_melt) * DT
        total_melt = max(0, total_rain_melt - total_rain)
        total_sublim = np.sum(np.maximum(sublim, 0)) * DT
        final_swe = swe[-1]

        total_input = total_snowfall
        total_output = final_swe + total_melt + total_sublim

        if total_input > 1.0:
            balance_error = abs(total_input - total_output) / total_input
            assert balance_error < 0.35, \
                f"Mass balance error {balance_error:.1%}: " \
                f"snowfall={total_input:.1f}, final_swe={final_swe:.1f}, " \
                f"melt={total_melt:.1f}, sublim={total_sublim:.1f}"

    def test_sublimation_nonnegative(self, condecay_ds):
        """Sublimation rate (mass loss) should be non-negative."""
        sublim = condecay_ds.variables['scalarSnowSublimation'][:, 0]
        assert np.all(sublim >= -0.001), \
            f"Negative sublimation rate: {sublim.min():.6e}"


# ──────────────────────────────────────────────────────────────────────
# Test Suite 5: Temperature Physics
# ──────────────────────────────────────────────────────────────────────

class TestTemperaturePhysics:
    """Verify snow surface temperature constraints."""

    def test_snow_temp_at_or_below_melting(self, condecay_ds):
        """Snow surface temperature must not exceed 273.15 K."""
        temp = condecay_ds.variables['scalarSurfaceTemp'][:, 0]
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        snow_mask = swe > 0.1
        if np.any(snow_mask):
            max_temp = temp[snow_mask].max()
            assert max_temp <= 273.25, \
                f"Snow surface temp exceeds melting point: {max_temp:.2f} K"

    def test_temp_physically_reasonable(self, condecay_ds):
        """Surface temperature should not be unreasonably cold."""
        temp = condecay_ds.variables['scalarSurfaceTemp'][:, 0]
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        snow_mask = swe > 0.1
        if np.any(snow_mask):
            min_temp = temp[snow_mask].min()
            assert min_temp > 200, \
                f"Unreasonably cold snow surface temp: {min_temp:.2f} K"

    def test_melt_only_near_melting_point(self, condecay_ds):
        """Significant melt should only occur when temperature is near 273.15 K."""
        temp = condecay_ds.variables['scalarSurfaceTemp'][:, 0]
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        rain_melt = condecay_ds.variables['scalarRainPlusMelt'][:, 0]

        melt_mask = (rain_melt > 1e-6) & (swe > 0.1)
        if np.sum(melt_mask) > 5:
            melt_temps = temp[melt_mask]
            near_melting = melt_temps > 268
            frac_near_melting = np.mean(near_melting)
            assert frac_near_melting > 0.5, \
                f"Only {frac_near_melting:.0%} of melt near melting point"


# ──────────────────────────────────────────────────────────────────────
# Test Suite 6: Snow Accumulation
# ──────────────────────────────────────────────────────────────────────

class TestSnowAccumulation:
    """Verify snow accumulation during cold precipitation."""

    def test_snow_accumulates_when_cold(self, condecay_ds, forcing_ds):
        """SWE should generally increase during cold precipitation events."""
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        ppt = forcing_ds.variables['pptrate'][:, 0]
        temp = forcing_ds.variables['airtemp'][:, 0]

        cold_precip = (ppt > 5e-5) & (temp < 268)
        events = np.where(cold_precip)[0]

        increases = 0
        total = 0
        for idx in events:
            if idx + 1 < len(swe):
                total += 1
                if swe[idx + 1] >= swe[idx] - 0.5:
                    increases += 1

        if total > 5:
            frac = increases / total
            assert frac > 0.6, \
                f"SWE failed to increase during cold precip: {increases}/{total}"

    def test_peak_swe_in_winter(self, condecay_ds):
        """Peak SWE should occur during winter, not at simulation edges."""
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        n = len(swe)

        if np.max(swe) > 1.0:
            peak_idx = np.argmax(swe)
            assert peak_idx > n * 0.05, \
                f"Peak SWE at index {peak_idx}/{n} -- too early"

    def test_some_snow_accumulates(self, condecay_ds):
        """There should be meaningful snow accumulation during the simulation."""
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        assert np.max(swe) > 1.0, \
            f"Max SWE only {np.max(swe):.2f} kg/m2 -- expected significant accumulation"


# ──────────────────────────────────────────────────────────────────────
# Test Suite 7: Cross-Configuration Comparison
# ──────────────────────────────────────────────────────────────────────

class TestConfigurationDivergence:
    """Verify that different configurations produce meaningfully different results."""

    def test_swe_differs_between_configs(self, condecay_ds, vardecay_ds):
        """Different albedo methods should produce different SWE evolution."""
        swe_con = condecay_ds.variables['scalarSWE'][:, 0]
        swe_var = vardecay_ds.variables['scalarSWE'][:, 0]

        diff = np.abs(swe_con - swe_var)
        assert np.max(diff) > 0.1, \
            f"conDecay/varDecay SWE max diff only {np.max(diff):.4f}"

    def test_melt_differs_between_configs(self, condecay_ds, vardecay_ds):
        """Different albedo methods should produce different melt patterns."""
        melt_con = np.sum(condecay_ds.variables['scalarRainPlusMelt'][:, 0])
        melt_var = np.sum(vardecay_ds.variables['scalarRainPlusMelt'][:, 0])

        assert abs(melt_con - melt_var) > 0, \
            "conDecay and varDecay produced identical total melt"

    def test_vardecay_output_format_also_valid(self, vardecay_ds, forcing_ds):
        """varDecay output should match the same format requirements."""
        n_forcing = len(forcing_ds.dimensions['time'])
        n_output = len(vardecay_ds.dimensions['time'])
        assert n_output == n_forcing

        for var in REQUIRED_VARS:
            assert var in vardecay_ds.variables
            assert vardecay_ds.variables[var].shape == (n_output, 1)

    def test_vardecay_swe_nonnegative(self, vardecay_ds):
        swe = vardecay_ds.variables['scalarSWE'][:, 0]
        assert np.all(swe >= -0.01), f"varDecay negative SWE: {swe.min():.4f}"

    def test_vardecay_temp_ceiling(self, vardecay_ds):
        temp = vardecay_ds.variables['scalarSurfaceTemp'][:, 0]
        swe = vardecay_ds.variables['scalarSWE'][:, 0]
        snow_mask = swe > 0.1
        if np.any(snow_mask):
            assert temp[snow_mask].max() <= 273.25


# ──────────────────────────────────────────────────────────────────────
# Test Suite 8: Variable Decay Specific Behavior
# ──────────────────────────────────────────────────────────────────────

class TestVarDecayBehavior:
    """Verify temperature-dependent behavior of varDecay method."""

    def test_vardecay_temperature_dependent_decay(self, vardecay_ds, forcing_ds):
        """varDecay should show faster albedo decay at warm temperatures
        than at cold temperatures."""
        albedo = vardecay_ds.variables['scalarSnowAlbedo'][:, 0]
        swe = vardecay_ds.variables['scalarSWE'][:, 0]
        temp = vardecay_ds.variables['scalarSurfaceTemp'][:, 0]
        ppt = forcing_ds.variables['pptrate'][:, 0]

        no_snow_event = ppt < NEW_SNOW_THRESH
        has_snow = swe > 0.5

        warm_decays = []
        cold_decays = []

        for i in range(1, len(albedo)):
            if (no_snow_event[i] and has_snow[i] and has_snow[i - 1] and
                    albedo[i - 1] > ALBEDO_MIN + 0.03 and
                    albedo[i] < albedo[i - 1]):
                decay = albedo[i - 1] - albedo[i]
                if temp[i] > 270:
                    warm_decays.append(decay)
                elif temp[i] < 255:
                    cold_decays.append(decay)

        if len(warm_decays) > 3 and len(cold_decays) > 3:
            mean_warm = np.mean(warm_decays)
            mean_cold = np.mean(cold_decays)
            assert mean_warm > mean_cold * 1.2, \
                f"varDecay warm decay {mean_warm:.6f} not faster than cold {mean_cold:.6f}"

    def test_vardecay_mass_conservation(self, vardecay_ds, forcing_ds):
        """Mass conservation should also hold for varDecay configuration."""
        swe = vardecay_ds.variables['scalarSWE'][:, 0]
        ppt = forcing_ds.variables['pptrate'][:, 0]
        temp = forcing_ds.variables['airtemp'][:, 0]
        rain_melt = vardecay_ds.variables['scalarRainPlusMelt'][:, 0]
        sublim = vardecay_ds.variables['scalarSnowSublimation'][:, 0]

        snow_mask = temp < RAIN_SNOW_THRESH
        total_snowfall = np.sum(ppt[snow_mask]) * DT
        rain_rate = np.where(temp >= RAIN_SNOW_THRESH, ppt, 0.0)
        total_rain = np.sum(rain_rate) * DT
        total_rain_melt = np.sum(rain_melt) * DT
        total_melt = max(0, total_rain_melt - total_rain)
        total_sublim = np.sum(np.maximum(sublim, 0)) * DT
        final_swe = swe[-1]

        total_input = total_snowfall
        total_output = final_swe + total_melt + total_sublim

        if total_input > 1.0:
            balance_error = abs(total_input - total_output) / total_input
            assert balance_error < 0.35, \
                f"varDecay mass balance error {balance_error:.1%}"


# ──────────────────────────────────────────────────────────────────────
# Test Suite 9: Heat Flux Physics
# ──────────────────────────────────────────────────────────────────────

class TestHeatFluxPhysics:
    """Verify heat flux sign conventions and consistency."""

    def test_sensible_heat_sign_convention(self, condecay_ds, forcing_ds):
        """Sensible heat should correlate with air-surface temperature gradient.
        Positive toward surface means positive when air warmer than snow."""
        sens = condecay_ds.variables['scalarSenHeatTotal'][:, 0]
        t_surf = condecay_ds.variables['scalarSurfaceTemp'][:, 0]
        t_air = forcing_ds.variables['airtemp'][:, 0]
        swe = condecay_ds.variables['scalarSWE'][:, 0]

        snow_mask = swe > 0.5
        if np.sum(snow_mask) > 50:
            t_diff = t_air[snow_mask] - t_surf[snow_mask]
            sens_snow = sens[snow_mask]
            corr = np.corrcoef(t_diff, sens_snow)[0, 1]
            assert corr > 0.3, \
                f"Sensible heat poorly correlated with temperature gradient: {corr:.3f}"

    def test_no_nan_in_heat_fluxes(self, condecay_ds):
        """Heat fluxes should not contain NaN values."""
        for var_name in ['scalarSenHeatTotal', 'scalarLatHeatTotal']:
            vals = condecay_ds.variables[var_name][:, 0]
            assert not np.any(np.isnan(vals)), f"NaN in {var_name}"


# ──────────────────────────────────────────────────────────────────────
# Test Suite 10: Comparison Report
# ──────────────────────────────────────────────────────────────────────

class TestComparisonReport:
    """Verify the comparison report structure and consistency."""

    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH), "comparison_report.json not found"

    def test_report_valid_json(self, comparison_report):
        assert isinstance(comparison_report, dict)

    def test_report_has_config_sections(self, comparison_report):
        assert 'conDecay' in comparison_report, "Missing conDecay section"
        assert 'varDecay' in comparison_report, "Missing varDecay section"
        assert 'divergence' in comparison_report, "Missing divergence section"

    def test_report_config_fields(self, comparison_report):
        required_fields = ['peak_swe_kg_m2', 'peak_swe_timestep',
                           'total_melt_kg_m2', 'mean_snow_albedo',
                           'snow_covered_hours', 'total_sublimation_kg_m2']
        for config in ['conDecay', 'varDecay']:
            for field in required_fields:
                assert field in comparison_report[config], \
                    f"Missing {field} in {config}"

    def test_report_divergence_fields(self, comparison_report):
        required = ['max_swe_difference_kg_m2', 'max_albedo_difference',
                     'melt_onset_difference_hours']
        for field in required:
            assert field in comparison_report['divergence'], \
                f"Missing {field} in divergence"

    def test_peak_swe_consistent_condecay(self, comparison_report, condecay_ds):
        """Reported peak SWE should match raw output."""
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        expected_peak = float(np.max(swe))
        reported = comparison_report['conDecay']['peak_swe_kg_m2']
        assert abs(reported - expected_peak) / max(expected_peak, 0.01) < 0.05, \
            f"Reported peak SWE {reported:.2f} != actual {expected_peak:.2f}"

    def test_peak_timestep_consistent_condecay(self, comparison_report, condecay_ds):
        """Reported peak timestep should match raw output."""
        swe = condecay_ds.variables['scalarSWE'][:, 0]
        expected_idx = int(np.argmax(swe))
        reported = comparison_report['conDecay']['peak_swe_timestep']
        assert abs(reported - expected_idx) <= 2, \
            f"Reported peak timestep {reported} != actual {expected_idx}"

    def test_snow_covered_hours_reasonable(self, comparison_report):
        for config in ['conDecay', 'varDecay']:
            hours = comparison_report[config]['snow_covered_hours']
            assert 100 < hours < 5000, \
                f"{config} snow_covered_hours={hours} out of range"

    def test_divergence_max_swe_positive(self, comparison_report):
        assert comparison_report['divergence']['max_swe_difference_kg_m2'] > 0, \
            "Configurations should show SWE divergence"

    def test_divergence_max_albedo_positive(self, comparison_report):
        assert comparison_report['divergence']['max_albedo_difference'] > 0, \
            "Configurations should show albedo divergence"

    def test_mean_albedo_within_bounds(self, comparison_report):
        for config in ['conDecay', 'varDecay']:
            albedo = comparison_report[config]['mean_snow_albedo']
            assert ALBEDO_MIN - 0.01 <= albedo <= ALBEDO_MAX + 0.01, \
                f"{config} mean albedo {albedo:.4f} out of bounds"

    def test_total_melt_positive(self, comparison_report):
        for config in ['conDecay', 'varDecay']:
            assert comparison_report[config]['total_melt_kg_m2'] > 0, \
                f"{config} total_melt should be positive"

    def test_total_sublimation_nonnegative(self, comparison_report):
        for config in ['conDecay', 'varDecay']:
            assert comparison_report[config]['total_sublimation_kg_m2'] >= 0, \
                f"{config} total_sublimation should be non-negative"
