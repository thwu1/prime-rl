"""Tests for ecological population dynamics inference results."""


import json
import csv
import os
import math
import pytest


# Observed pelt data (thousands), years 1901-1920, for posterior predictive validation
OBSERVED_HARE = [47.2, 70.2, 77.4, 36.3, 20.6, 18.1, 21.4, 22.0, 25.4, 27.1,
                 40.3, 57.0, 76.6, 52.3, 19.5, 11.2, 7.6, 14.6, 16.2, 24.7]
OBSERVED_LYNX = [6.1, 9.8, 35.2, 59.4, 41.7, 19.0, 13.0, 8.3, 9.1, 7.4,
                 8.0, 12.3, 19.5, 45.7, 51.1, 29.7, 15.8, 9.7, 10.1, 8.6]


def pearson_correlation(x, y):
    """Compute Pearson correlation coefficient between two lists."""
    n = len(x)
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / n
    std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x) / n)
    std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y) / n)
    if std_x == 0 or std_y == 0:
        return 0.0
    return cov / (std_x * std_y)


class TestPosteriorSummary:
    """Tests for posterior_summary.json."""

    @pytest.fixture
    def summary(self):
        with open('/app/results/posterior_summary.json') as f:
            return json.load(f)

    def test_file_exists(self):
        assert os.path.exists('/app/results/posterior_summary.json')

    def test_has_parameters_key(self, summary):
        assert 'parameters' in summary

    def test_has_diagnostics_key(self, summary):
        assert 'diagnostics' in summary

    def test_minimum_parameter_count(self, summary):
        """A mechanistic population dynamics model needs at least 6 parameters."""
        assert len(summary['parameters']) >= 6, \
            f"Expected >= 6 model parameters, got {len(summary['parameters'])}"

    def test_parameter_fields(self, summary):
        required_fields = ['mean', 'q5', 'q95', 'rhat', 'ess_bulk']
        for p_name, p_data in summary['parameters'].items():
            for field in required_fields:
                assert field in p_data, f"Missing field '{field}' in {p_name}"

    def test_positive_parameter_means(self, summary):
        """All parameters in an ecological dynamics model should be positive."""
        for p_name, p_data in summary['parameters'].items():
            assert p_data['mean'] > 0, \
                f"{p_name} mean={p_data['mean']}, expected > 0"

    def test_convergence_rhat(self, summary):
        """All R-hat values must be < 1.1."""
        for p_name, p_data in summary['parameters'].items():
            assert p_data['rhat'] < 1.1, f"R-hat for {p_name} = {p_data['rhat']}"

    def test_convergence_ess(self, summary):
        """All bulk ESS values must be > 50."""
        for p_name, p_data in summary['parameters'].items():
            assert p_data['ess_bulk'] > 50, f"ESS for {p_name} = {p_data['ess_bulk']}"

    def test_divergences(self, summary):
        """Total divergent transitions must be < 500."""
        diag = summary['diagnostics']
        assert diag['total_divergent_transitions'] < 500

    def test_diagnostics_max_rhat(self, summary):
        diag = summary['diagnostics']
        assert diag['max_rhat'] < 1.1

    def test_diagnostics_min_ess(self, summary):
        diag = summary['diagnostics']
        assert diag['min_ess_bulk'] > 50

    def test_credible_intervals_contain_mean(self, summary):
        """For each parameter, the mean should lie within [q5, q95]."""
        for p_name, p_data in summary['parameters'].items():
            assert p_data['q5'] <= p_data['mean'] <= p_data['q95'], \
                f"{p_name}: mean {p_data['mean']} not in [{p_data['q5']}, {p_data['q95']}]"


class TestPosteriorPredictive:
    """Tests for posterior_predictive.csv."""

    @pytest.fixture
    def pp_rows(self):
        with open('/app/results/posterior_predictive.csv') as f:
            return list(csv.DictReader(f))

    def test_file_exists(self):
        assert os.path.exists('/app/results/posterior_predictive.csv')

    def test_row_count(self, pp_rows):
        assert len(pp_rows) == 20, f"Expected 20 rows, got {len(pp_rows)}"

    def test_columns_present(self, pp_rows):
        required = ['year', 'hare_mean', 'hare_q5', 'hare_q95',
                     'lynx_mean', 'lynx_q5', 'lynx_q95']
        for col in required:
            assert col in pp_rows[0], f"Missing column '{col}'"

    def test_year_sequence(self, pp_rows):
        years = [int(float(r['year'])) for r in pp_rows]
        assert years == list(range(1901, 1921))

    def test_positive_values(self, pp_rows):
        for row in pp_rows:
            for col in ['hare_mean', 'hare_q5', 'lynx_mean', 'lynx_q5']:
                val = float(row[col])
                assert val > 0, f"{col} at year {row['year']} = {val}, expected > 0"

    def test_quantile_ordering(self, pp_rows):
        for row in pp_rows:
            assert float(row['hare_q5']) < float(row['hare_q95']), \
                f"hare q5 >= q95 at year {row['year']}"
            assert float(row['lynx_q5']) < float(row['lynx_q95']), \
                f"lynx q5 >= q95 at year {row['year']}"

    def test_hare_peak_captured(self, pp_rows):
        """Posterior predictive should capture the hare population peak."""
        hare_means = [float(r['hare_mean']) for r in pp_rows]
        assert max(hare_means) > 30, \
            f"Peak hare mean = {max(hare_means)}, expected > 30"

    def test_lynx_peak_captured(self, pp_rows):
        """Posterior predictive should capture the lynx population peak."""
        lynx_means = [float(r['lynx_mean']) for r in pp_rows]
        assert max(lynx_means) > 20, \
            f"Peak lynx mean = {max(lynx_means)}, expected > 20"

    def test_reasonable_magnitudes(self, pp_rows):
        """Values should not be astronomically large."""
        for row in pp_rows:
            assert float(row['hare_q95']) < 500, \
                f"hare q95 = {row['hare_q95']} at year {row['year']}, expected < 500"
            assert float(row['lynx_q95']) < 500, \
                f"lynx q95 = {row['lynx_q95']} at year {row['year']}, expected < 500"

    def test_hare_dynamics_correlation(self, pp_rows):
        """Posterior predictive hare means must track the observed oscillatory pattern."""
        predicted = [float(r['hare_mean']) for r in pp_rows]
        corr = pearson_correlation(OBSERVED_HARE, predicted)
        assert corr > 0.5, \
            f"Hare posterior predictive vs. observed correlation = {corr:.3f}, expected > 0.5"

    def test_lynx_dynamics_correlation(self, pp_rows):
        """Posterior predictive lynx means must track the observed oscillatory pattern."""
        predicted = [float(r['lynx_mean']) for r in pp_rows]
        corr = pearson_correlation(OBSERVED_LYNX, predicted)
        assert corr > 0.5, \
            f"Lynx posterior predictive vs. observed correlation = {corr:.3f}, expected > 0.5"


class TestPredictions:
    """Tests for predictions.csv (forward predictions 1921-1930)."""

    @pytest.fixture
    def pred_rows(self):
        with open('/app/results/predictions.csv') as f:
            return list(csv.DictReader(f))

    def test_file_exists(self):
        assert os.path.exists('/app/results/predictions.csv')

    def test_row_count(self, pred_rows):
        assert len(pred_rows) == 10, f"Expected 10 rows, got {len(pred_rows)}"

    def test_columns_present(self, pred_rows):
        required = ['year', 'hare_mean', 'hare_q5', 'hare_q95',
                     'lynx_mean', 'lynx_q5', 'lynx_q95']
        for col in required:
            assert col in pred_rows[0], f"Missing column '{col}'"

    def test_year_sequence(self, pred_rows):
        years = [int(float(r['year'])) for r in pred_rows]
        assert years == list(range(1921, 1931))

    def test_positive_values(self, pred_rows):
        for row in pred_rows:
            for col in ['hare_mean', 'hare_q5', 'lynx_mean', 'lynx_q5']:
                val = float(row[col])
                assert val > 0, f"{col} at year {row['year']} = {val}, expected > 0"

    def test_reasonable_magnitudes(self, pred_rows):
        """Predicted populations should stay within a plausible ecological range."""
        for row in pred_rows:
            assert float(row['hare_q95']) < 500, \
                f"hare q95 = {row['hare_q95']} at year {row['year']}, expected < 500"
            assert float(row['lynx_q95']) < 500, \
                f"lynx q95 = {row['lynx_q95']} at year {row['year']}, expected < 500"

    def test_quantile_ordering(self, pred_rows):
        for row in pred_rows:
            assert float(row['hare_q5']) < float(row['hare_q95']), \
                f"hare q5 >= q95 at year {row['year']}"
            assert float(row['lynx_q5']) < float(row['lynx_q95']), \
                f"lynx q5 >= q95 at year {row['year']}"


class TestModelSource:
    """Tests for the Stan model source file."""

    def test_file_exists(self):
        assert os.path.exists('/app/models/dynamics.stan')

    def test_has_required_blocks(self):
        with open('/app/models/dynamics.stan') as f:
            content = f.read()
        for block in ['functions', 'data', 'parameters',
                      'transformed parameters', 'model', 'generated quantities']:
            assert block in content, f"Stan model missing '{block}' block"

    def test_has_ode_solver(self):
        with open('/app/models/dynamics.stan') as f:
            content = f.read()
        ode_keywords = ['integrate_ode', 'ode_rk45', 'ode_bdf',
                        'ode_adams', 'ode_ckrk', 'ode_rk45_tol', 'ode_bdf_tol']
        has_ode = any(kw in content for kw in ode_keywords)
        assert has_ode, "Stan model must use an ODE solver"

    def test_has_population_dynamics(self):
        with open('/app/models/dynamics.stan') as f:
            content = f.read()
        assert 'real' in content, "Model should declare real variables"
        assert 'return' in content, "ODE function should return derivatives"
