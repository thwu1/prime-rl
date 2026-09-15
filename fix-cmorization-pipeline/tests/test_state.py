"""Validate CMOR compliance evaluation and final pipeline output.

"""
import json
import os

import netCDF4 as nc
import numpy as np
import pytest

OUTPUT_DIR = '/app/output'
SPEC_PATH = '/app/cmor_spec.json'
AUDIT_PATH = '/app/audit_report.json'
VARIABLES = ['tas', 'pr', 'rlut']
DIMENSIONS = [
    'spatial_alignment', 'unit_conversion', 'unit_strings',
    'lat_bounds_polar', 'time_bounds', 'missing_values',
    'global_attributes', 'variable_attributes'
]


def load_spec():
    with open(SPEC_PATH) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def spec():
    return load_spec()


@pytest.fixture(scope='module')
def audit():
    assert os.path.exists(AUDIT_PATH), f"audit_report.json not found at {AUDIT_PATH}"
    with open(AUDIT_PATH) as f:
        return json.load(f)


# ===== Ground truth computation for audit verification =====

def check_spatial_alignment(output_dir):
    """Data array should be reordered when lon coordinates are shifted."""
    path = os.path.join(output_dir, 'tas_Amon_OBS_2001.nc')
    if not os.path.exists(path):
        return False
    ds = nc.Dataset(path, 'r')
    data = ds.variables['tas'][0]
    lon = ds.variables['lon'][:]
    lat = ds.variables['lat'][:]
    ds.close()
    eq_mask = (lat >= -15) & (lat <= 15)
    idx_0 = int(np.argmin(np.abs(lon - 2.5)))
    idx_180 = int(np.argmin(np.abs(lon - 182.5)))
    mean_0 = float(np.mean(data[eq_mask, idx_0]))
    mean_180 = float(np.mean(data[eq_mask, idx_180]))
    return mean_0 > mean_180


def check_unit_conversion(output_dir):
    """Precipitation values should be physically reasonable after conversion."""
    path = os.path.join(output_dir, 'pr_Amon_OBS_2001.nc')
    if not os.path.exists(path):
        return False
    ds = nc.Dataset(path, 'r')
    ds.set_auto_mask(False)
    data = ds.variables['pr'][:]
    ds.close()
    valid = data[data < 1.0e19]
    if len(valid) == 0:
        return False
    return float(np.max(valid)) < 0.01


def check_unit_strings(output_dir):
    """Output variable unit strings must match the CMOR spec."""
    s = load_spec()
    for var in VARIABLES:
        path = os.path.join(output_dir, f'{var}_Amon_OBS_2001.nc')
        if not os.path.exists(path):
            return False
        ds = nc.Dataset(path, 'r')
        actual = ds.variables[var].units
        ds.close()
        if actual != s['variables'][var]['units']:
            return False
    return True


def check_lat_bounds_polar(output_dir):
    """Latitude bounds must extend to at least +/-89 for all global grids."""
    for var in VARIABLES:
        path = os.path.join(output_dir, f'{var}_Amon_OBS_2001.nc')
        if not os.path.exists(path):
            return False
        ds = nc.Dataset(path, 'r')
        lb = ds.variables['lat_bnds'][:]
        ds.close()
        if lb[0, 0] > -89.0 or lb[-1, 1] < 89.0:
            return False
    return True


def check_time_bounds(output_dir):
    """Monthly time bounds must be present with correct shape."""
    for var in VARIABLES:
        path = os.path.join(output_dir, f'{var}_Amon_OBS_2001.nc')
        if not os.path.exists(path):
            return False
        ds = nc.Dataset(path, 'r')
        has_tb = 'time_bnds' in ds.variables
        correct_shape = False
        if has_tb:
            tb = ds.variables['time_bnds'][:]
            correct_shape = (tb.shape == (12, 2))
        ds.close()
        if not has_tb or not correct_shape:
            return False
    return True


def check_missing_values(output_dir):
    """Fill values in polar regions must be preserved through processing."""
    path = os.path.join(output_dir, 'pr_Amon_OBS_2001.nc')
    if not os.path.exists(path):
        return False
    ds = nc.Dataset(path, 'r')
    ds.set_auto_mask(False)
    data = ds.variables['pr'][:]
    fill_val = ds.variables['pr']._FillValue
    ds.close()
    n_fill = int(np.sum(np.isclose(data, fill_val, rtol=1e-5)))
    return n_fill / data.size > 0.01


def check_global_attributes(output_dir):
    """CF-required global attributes must be present."""
    for var in VARIABLES:
        path = os.path.join(output_dir, f'{var}_Amon_OBS_2001.nc')
        if not os.path.exists(path):
            return False
        ds = nc.Dataset(path, 'r')
        has_conv = hasattr(ds, 'Conventions')
        has_hist = hasattr(ds, 'history')
        ds.close()
        if not has_conv or not has_hist:
            return False
    return True


def check_variable_attributes(output_dir):
    """CF-required variable attributes must be present."""
    for var in VARIABLES:
        path = os.path.join(output_dir, f'{var}_Amon_OBS_2001.nc')
        if not os.path.exists(path):
            return False
        ds = nc.Dataset(path, 'r')
        has_cm = hasattr(ds.variables[var], 'cell_methods')
        ds.close()
        if not has_cm:
            return False
    return True


CHECKERS = {
    'spatial_alignment': check_spatial_alignment,
    'unit_conversion': check_unit_conversion,
    'unit_strings': check_unit_strings,
    'lat_bounds_polar': check_lat_bounds_polar,
    'time_bounds': check_time_bounds,
    'missing_values': check_missing_values,
    'global_attributes': check_global_attributes,
    'variable_attributes': check_variable_attributes,
}


# ===== Audit Report Structure Tests =====

class TestAuditReportStructure:
    def test_audit_file_exists(self):
        assert os.path.exists(AUDIT_PATH)

    def test_both_pipelines_present(self, audit):
        assert 'pipeline_alpha' in audit
        assert 'pipeline_beta' in audit

    def test_superior_pipeline_present(self, audit):
        assert 'superior_pipeline' in audit

    def test_all_dimensions_present(self, audit):
        for pipeline in ['pipeline_alpha', 'pipeline_beta']:
            for dim in DIMENSIONS:
                assert dim in audit[pipeline], f"{pipeline} missing {dim}"
            assert 'pass_count' in audit[pipeline]

    def test_dimension_values_are_bool(self, audit):
        for pipeline in ['pipeline_alpha', 'pipeline_beta']:
            for dim in DIMENSIONS:
                assert isinstance(audit[pipeline][dim], bool), \
                    f"{pipeline}.{dim} should be bool"


# ===== Audit Report Accuracy Tests =====

class TestAuditAccuracy:
    """Verify each audit verdict against independently computed ground truth."""

    def test_alpha_verdicts_match_reality(self, audit):
        for dim, checker in CHECKERS.items():
            truth = checker('/app/output_alpha')
            reported = audit['pipeline_alpha'][dim]
            assert reported == truth, \
                f"pipeline_alpha.{dim}: reported {reported} but actual is {truth}"

    def test_beta_verdicts_match_reality(self, audit):
        for dim, checker in CHECKERS.items():
            truth = checker('/app/output_beta')
            reported = audit['pipeline_beta'][dim]
            assert reported == truth, \
                f"pipeline_beta.{dim}: reported {reported} but actual is {truth}"

    def test_pass_counts_correct(self, audit):
        for pipeline in ['pipeline_alpha', 'pipeline_beta']:
            expected = sum(1 for d in DIMENSIONS if audit[pipeline][d])
            assert audit[pipeline]['pass_count'] == expected, \
                f"{pipeline}: pass_count {audit[pipeline]['pass_count']} != {expected}"

    def test_superior_pipeline_correct(self, audit):
        a = audit['pipeline_alpha']['pass_count']
        b = audit['pipeline_beta']['pass_count']
        if a > b:
            expected = 'alpha'
        elif b > a:
            expected = 'beta'
        else:
            expected = 'neither'
        assert audit['superior_pipeline'] == expected, \
            f"superior_pipeline: '{audit['superior_pipeline']}' but alpha={a}, beta={b}"


# ===== Defect Analysis Tests =====

class TestDefectAnalysis:
    """Verify defect analysis contains meaningful root causes for each failure."""

    def test_alpha_defect_analysis_present(self, audit):
        assert 'defect_analysis' in audit['pipeline_alpha'], \
            "pipeline_alpha missing defect_analysis"

    def test_beta_defect_analysis_present(self, audit):
        assert 'defect_analysis' in audit['pipeline_beta'], \
            "pipeline_beta missing defect_analysis"

    def test_alpha_defect_entries_match_failures(self, audit):
        """Each failing dimension in alpha must have a defect_analysis entry."""
        alpha = audit['pipeline_alpha']
        da = alpha['defect_analysis']
        for dim in DIMENSIONS:
            if not alpha[dim]:
                assert dim in da, \
                    f"pipeline_alpha.{dim} is False but missing from defect_analysis"
                entry = da[dim]
                assert 'root_cause' in entry, \
                    f"pipeline_alpha defect_analysis[{dim}] missing root_cause"
                assert 'affected_variables' in entry, \
                    f"pipeline_alpha defect_analysis[{dim}] missing affected_variables"
                assert isinstance(entry['root_cause'], str) and len(entry['root_cause']) >= 15, \
                    f"pipeline_alpha defect_analysis[{dim}] root_cause too short or not a string"
                assert isinstance(entry['affected_variables'], list) and len(entry['affected_variables']) >= 1, \
                    f"pipeline_alpha defect_analysis[{dim}] affected_variables must be non-empty list"

    def test_beta_defect_entries_match_failures(self, audit):
        """Each failing dimension in beta must have a defect_analysis entry."""
        beta = audit['pipeline_beta']
        da = beta['defect_analysis']
        for dim in DIMENSIONS:
            if not beta[dim]:
                assert dim in da, \
                    f"pipeline_beta.{dim} is False but missing from defect_analysis"
                entry = da[dim]
                assert 'root_cause' in entry, \
                    f"pipeline_beta defect_analysis[{dim}] missing root_cause"
                assert 'affected_variables' in entry, \
                    f"pipeline_beta defect_analysis[{dim}] missing affected_variables"
                assert isinstance(entry['root_cause'], str) and len(entry['root_cause']) >= 15, \
                    f"pipeline_beta defect_analysis[{dim}] root_cause too short or not a string"
                assert isinstance(entry['affected_variables'], list) and len(entry['affected_variables']) >= 1, \
                    f"pipeline_beta defect_analysis[{dim}] affected_variables must be non-empty list"

    def test_no_spurious_defect_entries(self, audit):
        """Passing dimensions should NOT appear in defect_analysis."""
        for pipeline_name in ['pipeline_alpha', 'pipeline_beta']:
            pipeline = audit[pipeline_name]
            da = pipeline.get('defect_analysis', {})
            for dim in DIMENSIONS:
                if pipeline[dim]:
                    assert dim not in da, \
                        f"{pipeline_name}.{dim} is True but has defect_analysis entry"

    def test_affected_variables_are_valid(self, audit):
        """All affected_variables entries must reference actual variables."""
        valid_vars = set(VARIABLES)
        for pipeline_name in ['pipeline_alpha', 'pipeline_beta']:
            da = audit[pipeline_name].get('defect_analysis', {})
            for dim, entry in da.items():
                for v in entry.get('affected_variables', []):
                    assert v in valid_vars, \
                        f"{pipeline_name} defect_analysis[{dim}] references invalid variable '{v}'"


# ===== Processing Dependencies Tests =====

class TestProcessingDependencies:
    """Verify processing dependency analysis identifies critical ordering constraints."""

    def test_dependencies_present(self, audit):
        assert 'processing_dependencies' in audit, \
            "audit missing processing_dependencies"
        deps = audit['processing_dependencies']
        assert isinstance(deps, list), "processing_dependencies must be a list"
        assert len(deps) >= 2, \
            f"Expected at least 2 processing dependencies, got {len(deps)}"

    def test_dependency_structure(self, audit):
        """Each dependency must have earlier, later, and rationale fields."""
        for i, dep in enumerate(audit['processing_dependencies']):
            assert 'earlier' in dep, \
                f"processing_dependencies[{i}] missing 'earlier' field"
            assert 'later' in dep, \
                f"processing_dependencies[{i}] missing 'later' field"
            assert 'rationale' in dep, \
                f"processing_dependencies[{i}] missing 'rationale' field"
            assert isinstance(dep['rationale'], str) and len(dep['rationale']) >= 20, \
                f"processing_dependencies[{i}] rationale too short (must be >= 20 chars)"

    def test_fill_conversion_ordering_identified(self, audit):
        """At least one dependency must identify the fill-value / unit-conversion ordering."""
        deps = audit['processing_dependencies']
        fill_kw = {'fill', 'mask', 'missing', 'sentinel', '9999'}
        conv_kw = {'unit', 'conver', 'scale', 'transform'}
        found = False
        for dep in deps:
            combined = (dep['earlier'] + ' ' + dep['later'] + ' ' + dep['rationale']).lower()
            has_fill = any(kw in combined for kw in fill_kw)
            has_conv = any(kw in combined for kw in conv_kw)
            if has_fill and has_conv:
                found = True
                break
        assert found, \
            "No processing dependency identifies the fill-value masking / unit-conversion ordering constraint"


# ===== Final Output Compliance Tests =====

@pytest.fixture(params=VARIABLES)
def var_ds(request):
    var = request.param
    path = os.path.join(OUTPUT_DIR, f'{var}_Amon_OBS_2001.nc')
    assert os.path.exists(path), f"Output file not found: {path}"
    ds = nc.Dataset(path, 'r')
    yield var, ds
    ds.close()


class TestFinalFilesExist:
    def test_all_output_files_exist(self):
        for var in VARIABLES:
            path = os.path.join(OUTPUT_DIR, f'{var}_Amon_OBS_2001.nc')
            assert os.path.exists(path), f"Missing output: {path}"


class TestFinalCoordinates:
    def test_longitude_range(self, var_ds):
        var, ds = var_ds
        lon = ds.variables['lon'][:]
        assert np.all(lon >= 0), f"{var}: lon values below 0"
        assert np.all(lon < 360), f"{var}: lon values >= 360"

    def test_latitude_ascending(self, var_ds):
        var, ds = var_ds
        lat = ds.variables['lat'][:]
        assert np.all(np.diff(lat) > 0), f"{var}: lat not ascending"

    def test_lat_bounds_polar(self, var_ds):
        var, ds = var_ds
        lb = ds.variables['lat_bnds'][:]
        assert lb[0, 0] <= -89.0, \
            f"{var}: southern lat bound {lb[0, 0]:.2f} not extending to pole"
        assert lb[-1, 1] >= 89.0, \
            f"{var}: northern lat bound {lb[-1, 1]:.2f} not extending to pole"

    def test_coordinate_dtypes(self, var_ds):
        var, ds = var_ds
        for coord in ['lat', 'lon', 'time']:
            assert ds.variables[coord].dtype == np.float64, \
                f"{var}: {coord} dtype {ds.variables[coord].dtype} != float64"

    def test_data_dtype(self, var_ds):
        var, ds = var_ds
        assert ds.variables[var].dtype == np.float32, \
            f"{var}: data dtype {ds.variables[var].dtype} != float32"

    def test_bounds_exist(self, var_ds):
        var, ds = var_ds
        assert 'lat_bnds' in ds.variables, f"{var}: missing lat_bnds"
        assert 'lon_bnds' in ds.variables, f"{var}: missing lon_bnds"


class TestFinalTimeBounds:
    def test_time_bounds_exist(self, var_ds):
        var, ds = var_ds
        assert 'time_bnds' in ds.variables, f"{var}: missing time_bnds"

    def test_time_bounds_shape(self, var_ds):
        var, ds = var_ds
        if 'time_bnds' not in ds.variables:
            pytest.skip("time_bnds missing")
        tb = ds.variables['time_bnds'][:]
        assert tb.shape == (12, 2), \
            f"{var}: time_bnds shape {tb.shape} != (12, 2)"

    def test_time_bounds_span(self, var_ds):
        var, ds = var_ds
        if 'time_bnds' not in ds.variables:
            pytest.skip("time_bnds missing")
        tb = ds.variables['time_bnds'][:]
        spans = tb[:, 1] - tb[:, 0]
        assert np.all(spans >= 27) and np.all(spans <= 32), \
            f"{var}: time bound spans out of range [{np.min(spans):.1f}, {np.max(spans):.1f}]"

    def test_time_bounds_contiguous(self, var_ds):
        var, ds = var_ds
        if 'time_bnds' not in ds.variables:
            pytest.skip("time_bnds missing")
        tb = ds.variables['time_bnds'][:]
        for i in range(11):
            assert np.isclose(tb[i, 1], tb[i + 1, 0], atol=0.01), \
                f"{var}: time bounds gap at month {i+1}->{i+2}"

    def test_time_within_bounds(self, var_ds):
        var, ds = var_ds
        if 'time_bnds' not in ds.variables:
            pytest.skip("time_bnds missing")
        t = ds.variables['time'][:]
        tb = ds.variables['time_bnds'][:]
        for i in range(12):
            assert tb[i, 0] <= t[i] <= tb[i, 1], \
                f"{var}: time {t[i]:.1f} not in bounds [{tb[i,0]:.1f}, {tb[i,1]:.1f}]"


class TestFinalUnits:
    def test_units_match_spec(self, var_ds, spec):
        var, ds = var_ds
        expected = spec['variables'][var]['units']
        actual = ds.variables[var].units
        assert actual == expected, \
            f"{var}: units '{actual}' != spec '{expected}'"


class TestFinalAttributes:
    def test_conventions(self, var_ds):
        var, ds = var_ds
        assert hasattr(ds, 'Conventions'), f"{var}: missing Conventions"

    def test_history(self, var_ds):
        var, ds = var_ds
        assert hasattr(ds, 'history'), f"{var}: missing history"

    def test_cell_methods(self, var_ds):
        var, ds = var_ds
        assert hasattr(ds.variables[var], 'cell_methods'), \
            f"{var}: missing cell_methods"

    def test_standard_name(self, var_ds, spec):
        var, ds = var_ds
        expected = spec['variables'][var]['standard_name']
        assert ds.variables[var].standard_name == expected, \
            f"{var}: standard_name mismatch"


class TestFinalTasSpatialConsistency:
    """Verify data is correctly aligned with coordinates after lon shift."""

    def test_temperature_gradient(self):
        path = os.path.join(OUTPUT_DIR, 'tas_Amon_OBS_2001.nc')
        if not os.path.exists(path):
            pytest.skip("tas output missing")
        ds = nc.Dataset(path, 'r')
        data = ds.variables['tas'][0]
        lon = ds.variables['lon'][:]
        lat = ds.variables['lat'][:]
        ds.close()
        eq_mask = (lat >= -15) & (lat <= 15)
        idx_0 = int(np.argmin(np.abs(lon - 2.5)))
        idx_180 = int(np.argmin(np.abs(lon - 182.5)))
        mean_0 = float(np.mean(data[eq_mask, idx_0]))
        mean_180 = float(np.mean(data[eq_mask, idx_180]))
        assert mean_0 > mean_180, \
            f"Equatorial temp at lon~0 ({mean_0:.1f}K) <= lon~180 ({mean_180:.1f}K)"


class TestFinalPrValues:
    """Verify precipitation values are physically reasonable."""

    def test_pr_maximum_reasonable(self):
        path = os.path.join(OUTPUT_DIR, 'pr_Amon_OBS_2001.nc')
        if not os.path.exists(path):
            pytest.skip("pr output missing")
        ds = nc.Dataset(path, 'r')
        ds.set_auto_mask(False)
        data = ds.variables['pr'][:]
        ds.close()
        valid = data[data < 1.0e19]
        assert np.max(valid) < 0.01, \
            f"Max precipitation {np.max(valid):.4f} unreasonably large"

    def test_pr_no_negative(self):
        path = os.path.join(OUTPUT_DIR, 'pr_Amon_OBS_2001.nc')
        if not os.path.exists(path):
            pytest.skip("pr output missing")
        ds = nc.Dataset(path, 'r')
        ds.set_auto_mask(False)
        data = ds.variables['pr'][:]
        ds.close()
        valid = data[data < 1.0e19]
        assert np.all(valid >= 0), \
            f"Negative precipitation found (min={np.min(valid):.6f})"

    def test_pr_has_fill_values(self):
        """Raw polar data contains undeclared fills that must be preserved."""
        path = os.path.join(OUTPUT_DIR, 'pr_Amon_OBS_2001.nc')
        if not os.path.exists(path):
            pytest.skip("pr output missing")
        ds = nc.Dataset(path, 'r')
        ds.set_auto_mask(False)
        data = ds.variables['pr'][:]
        fill_val = ds.variables['pr']._FillValue
        ds.close()
        n_fill = int(np.sum(np.isclose(data, fill_val, rtol=1e-5)))
        fill_frac = n_fill / data.size
        assert fill_frac > 0.01, \
            f"Only {fill_frac*100:.2f}% fill values, expected >1%"
