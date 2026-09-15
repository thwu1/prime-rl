
import pytest
import json
import csv
import os
import math


@pytest.fixture(scope="module")
def reconciled_values():
    """Load reconciled values from agent output."""
    filepath = '/app/results/reconciled_values.csv'
    assert os.path.exists(filepath), f"Output file not found: {filepath}"
    values = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            values[row['variable_name'].strip()] = {
                'measured': float(row['measured_value']),
                'reconciled': float(row['reconciled_value']),
                'measured_hwci': float(row['measured_hwci']),
                'reconciled_hwci': float(row['reconciled_hwci']),
            }
    return values


@pytest.fixture(scope="module")
def gross_errors():
    """Load detected gross errors from agent output."""
    filepath = '/app/results/gross_errors.json'
    assert os.path.exists(filepath), f"Output file not found: {filepath}"
    with open(filepath) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def analysis():
    """Load analysis results from agent output."""
    filepath = '/app/results/analysis.json'
    assert os.path.exists(filepath), f"Output file not found: {filepath}"
    with open(filepath) as f:
        return json.load(f)


class TestOutputFilesExist:
    def test_reconciled_values_exists(self):
        assert os.path.exists('/app/results/reconciled_values.csv'), \
            "reconciled_values.csv not found in /app/results/"

    def test_gross_errors_exists(self):
        assert os.path.exists('/app/results/gross_errors.json'), \
            "gross_errors.json not found in /app/results/"

    def test_analysis_exists(self):
        assert os.path.exists('/app/results/analysis.json'), \
            "analysis.json not found in /app/results/"


class TestOutputFormat:
    def test_all_variables_present(self, reconciled_values):
        expected = {f'm{i}' for i in range(1, 17)}
        actual = set(reconciled_values.keys())
        assert actual == expected, \
            f"Missing variables: {expected - actual}, extra: {actual - expected}"

    def test_reconciled_values_columns(self):
        filepath = '/app/results/reconciled_values.csv'
        with open(filepath) as f:
            reader = csv.DictReader(f)
            fields = set(reader.fieldnames)
        required = {'variable_name', 'measured_value', 'reconciled_value',
                     'measured_hwci', 'reconciled_hwci'}
        assert required.issubset(fields), \
            f"Missing columns: {required - fields}"

    def test_analysis_keys(self, analysis):
        required = {'global_test_statistic', 'chi_square_critical',
                     'global_test_passed', 'num_independent_constraints',
                     'detected_gross_errors'}
        actual = set(analysis.keys())
        assert required.issubset(actual), \
            f"Missing analysis keys: {required - actual}"

    def test_gross_errors_is_list(self, gross_errors):
        assert isinstance(gross_errors, list), \
            f"gross_errors.json should be a list, got {type(gross_errors)}"


class TestConstraintSatisfaction:
    """Reconciled values must satisfy all mass balance constraints."""

    def _get_vals(self, reconciled_values):
        return {k: reconciled_values[k]['reconciled'] for k in reconciled_values}

    def test_constraint_j1(self, reconciled_values):
        v = self._get_vals(reconciled_values)
        residual = v['m1'] + v['m2'] - v['m3']
        assert abs(residual) < 0.01, f"J1: m1+m2-m3 = {residual:.6f}"

    def test_constraint_j2(self, reconciled_values):
        v = self._get_vals(reconciled_values)
        residual = v['m3'] + v['m4'] - v['m5'] - v['m6']
        assert abs(residual) < 0.01, f"J2: m3+m4-m5-m6 = {residual:.6f}"

    def test_constraint_j3(self, reconciled_values):
        v = self._get_vals(reconciled_values)
        residual = v['m5'] - v['m7'] - v['m8']
        assert abs(residual) < 0.01, f"J3: m5-m7-m8 = {residual:.6f}"

    def test_constraint_j4(self, reconciled_values):
        v = self._get_vals(reconciled_values)
        residual = v['m6'] - v['m9'] - v['m10']
        assert abs(residual) < 0.01, f"J4: m6-m9-m10 = {residual:.6f}"

    def test_constraint_j5(self, reconciled_values):
        v = self._get_vals(reconciled_values)
        residual = v['m7'] + v['m9'] - v['m11']
        assert abs(residual) < 0.01, f"J5: m7+m9-m11 = {residual:.6f}"

    def test_constraint_j6(self, reconciled_values):
        v = self._get_vals(reconciled_values)
        residual = v['m8'] + v['m10'] - v['m12']
        assert abs(residual) < 0.01, f"J6: m8+m10-m12 = {residual:.6f}"

    def test_constraint_j7(self, reconciled_values):
        v = self._get_vals(reconciled_values)
        residual = v['m11'] + v['m12'] + v['m13'] - v['m14']
        assert abs(residual) < 0.01, f"J7: m11+m12+m13-m14 = {residual:.6f}"

    def test_constraint_j8(self, reconciled_values):
        v = self._get_vals(reconciled_values)
        residual = v['m14'] - v['m15'] - v['m16']
        assert abs(residual) < 0.01, f"J8: m14-m15-m16 = {residual:.6f}"


class TestGrossErrorDetection:
    def test_correct_gross_errors_identified(self, gross_errors):
        detected_set = set(gross_errors)
        expected_set = {'m4', 'm8', 'm15'}
        assert detected_set == expected_set, \
            f"Expected gross errors {{m4, m8, m15}}, got {detected_set}"

    def test_three_gross_errors(self, gross_errors):
        assert len(gross_errors) == 3, \
            f"Expected exactly 3 gross errors, found {len(gross_errors)}"

    def test_gross_errors_match_analysis(self, gross_errors, analysis):
        assert set(gross_errors) == set(analysis['detected_gross_errors']), \
            "gross_errors.json and analysis.json disagree on detected errors"


class TestStatisticalTests:
    def test_global_test_passes(self, analysis):
        assert analysis['global_test_passed'] is True, \
            "Global test should pass after gross error elimination"

    def test_j_star_below_critical(self, analysis):
        assert analysis['global_test_statistic'] < analysis['chi_square_critical'], \
            f"J*={analysis['global_test_statistic']:.4f} >= chi2={analysis['chi_square_critical']:.4f}"

    def test_num_independent_constraints(self, analysis):
        assert analysis['num_independent_constraints'] == 8, \
            f"Expected 8 independent constraints, got {analysis['num_independent_constraints']}"

    def test_chi_square_critical_value(self, analysis):
        """Chi-square critical value for df=8 at 95% should be ~15.507."""
        # scipy.stats.chi2.ppf(0.95, 8) = 15.50731305586545
        expected = 15.5073
        assert abs(analysis['chi_square_critical'] - expected) < 0.1, \
            f"Chi-square critical for df=8 should be ~{expected:.3f}, got {analysis['chi_square_critical']:.3f}"

    def test_j_star_positive(self, analysis):
        assert analysis['global_test_statistic'] > 0, \
            "J* should be positive"


class TestReconciledValues:
    """Reconciled values should be close to the true underlying values."""

    TRUE_VALUES = {
        'm1': 100.0, 'm2': 80.0, 'm3': 180.0, 'm4': 60.0,
        'm5': 140.0, 'm6': 100.0, 'm7': 80.0, 'm8': 60.0,
        'm9': 55.0, 'm10': 45.0, 'm11': 135.0, 'm12': 105.0,
        'm13': 20.0, 'm14': 260.0, 'm15': 160.0, 'm16': 100.0
    }

    def test_non_gross_error_values_reasonable(self, reconciled_values):
        """Non-faulty sensors should reconcile close to true values."""
        non_faulty = [v for v in self.TRUE_VALUES if v not in {'m4', 'm8', 'm15'}]
        for var in non_faulty:
            rec = reconciled_values[var]['reconciled']
            true = self.TRUE_VALUES[var]
            tol = max(8.0, 0.15 * abs(true))
            assert abs(rec - true) < tol, \
                f"{var}: reconciled={rec:.2f}, true={true:.2f}, tol={tol:.1f}"

    def test_gross_error_values_corrected(self, reconciled_values):
        """Gross-error sensors should be corrected toward true values."""
        for var in ['m4', 'm8', 'm15']:
            rec = reconciled_values[var]['reconciled']
            meas = reconciled_values[var]['measured']
            true = self.TRUE_VALUES[var]
            assert abs(rec - true) < abs(meas - true), \
                f"{var}: reconciled={rec:.2f} not closer to true={true:.2f} than measured={meas:.2f}"

    def test_overall_mass_balance(self, reconciled_values):
        """System inputs must equal system outputs."""
        v = {k: reconciled_values[k]['reconciled'] for k in reconciled_values}
        inputs = v['m1'] + v['m2'] + v['m4'] + v['m13']
        outputs = v['m15'] + v['m16']
        assert abs(inputs - outputs) < 0.05, \
            f"Overall balance violated: inputs={inputs:.4f}, outputs={outputs:.4f}"


class TestUncertaintyReduction:
    def test_reconciled_hwci_nonnegative(self, reconciled_values):
        for var, data in reconciled_values.items():
            assert data['reconciled_hwci'] >= 0, \
                f"{var}: negative reconciled HWCI = {data['reconciled_hwci']}"

    def test_most_uncertainties_reduced(self, reconciled_values):
        """Most non-gross-error variables should have reduced HWCI after reconciliation."""
        non_faulty = {v for v in reconciled_values if v not in {'m4', 'm8', 'm15'}}
        reduced = sum(
            1 for v in non_faulty
            if reconciled_values[v]['reconciled_hwci'] <= reconciled_values[v]['measured_hwci'] * 1.01
        )
        assert reduced >= 10, \
            f"Only {reduced}/{len(non_faulty)} non-faulty variables had reduced uncertainty"
