"""
Tests for probabilistic load forecasting task.

"""

import os
import numpy as np
import pandas as pd
import pytest

FORECAST_PATH = "/app/output/forecast.csv"
ACTUALS_PATH = "/tests/test_actuals.csv"
PINBALL_THRESHOLD = 45.0
N_HOURS = 744
N_QUANTILES = 99
QUANTILES = np.arange(0.01, 1.0, 0.01)


@pytest.fixture
def forecast():
    """Load the forecast CSV."""
    assert os.path.exists(FORECAST_PATH), (
        f"Forecast file not found at {FORECAST_PATH}"
    )
    df = pd.read_csv(FORECAST_PATH)
    return df


@pytest.fixture
def actuals():
    """Load the test actuals."""
    assert os.path.exists(ACTUALS_PATH), (
        f"Test actuals not found at {ACTUALS_PATH}"
    )
    df = pd.read_csv(ACTUALS_PATH)
    return df


class TestForecastFormat:
    """Tests for output file format compliance."""

    def test_file_exists(self):
        assert os.path.exists(FORECAST_PATH), (
            f"Forecast file not found at {FORECAST_PATH}"
        )

    def test_row_count(self, forecast):
        assert len(forecast) == N_HOURS, (
            f"Expected {N_HOURS} rows, got {len(forecast)}"
        )

    def test_column_count(self, forecast):
        # datetime + 99 quantile columns
        expected_cols = 1 + N_QUANTILES
        assert len(forecast.columns) == expected_cols, (
            f"Expected {expected_cols} columns, got {len(forecast.columns)}"
        )

    def test_datetime_column_exists(self, forecast):
        assert "datetime" in forecast.columns, (
            "Missing 'datetime' column"
        )

    def test_quantile_columns_exist(self, forecast):
        expected_q_cols = [f"q{i:02d}" for i in range(1, 100)]
        for col in expected_q_cols:
            assert col in forecast.columns, (
                f"Missing quantile column '{col}'"
            )

    def test_datetime_format(self, forecast):
        # Check that datetimes are parseable
        try:
            pd.to_datetime(forecast["datetime"])
        except Exception as e:
            pytest.fail(f"Could not parse datetime column: {e}")

    def test_datetime_covers_january_2022(self, forecast):
        dts = pd.to_datetime(forecast["datetime"])
        assert dts.min().month == 1 and dts.min().year == 2022, (
            f"First datetime should be January 2022, got {dts.min()}"
        )
        assert dts.max().month == 1 and dts.max().year == 2022, (
            f"Last datetime should be January 2022, got {dts.max()}"
        )


class TestForecastValues:
    """Tests for forecast value validity."""

    def test_all_values_finite(self, forecast):
        q_cols = [f"q{i:02d}" for i in range(1, 100)]
        values = forecast[q_cols].values
        assert np.all(np.isfinite(values)), (
            f"Found {np.sum(~np.isfinite(values))} non-finite values"
        )

    def test_all_values_nonnegative(self, forecast):
        q_cols = [f"q{i:02d}" for i in range(1, 100)]
        values = forecast[q_cols].values
        min_val = np.min(values)
        assert min_val >= 0, (
            f"Load forecasts must be non-negative, found minimum {min_val:.2f}"
        )

    def test_quantile_monotonicity(self, forecast):
        """No quantile crossing: q_tau1 <= q_tau2 for tau1 < tau2."""
        q_cols = [f"q{i:02d}" for i in range(1, 100)]
        values = forecast[q_cols].values

        violations = 0
        for t in range(len(values)):
            for i in range(1, len(q_cols)):
                if values[t, i] < values[t, i-1] - 1e-6:
                    violations += 1

        assert violations == 0, (
            f"Found {violations} quantile crossing violations "
            f"(quantiles must be non-decreasing for each hour)"
        )

    def test_reasonable_load_range(self, forecast):
        """Forecasts should be within a physically reasonable range."""
        q_cols = [f"q{i:02d}" for i in range(1, 100)]
        values = forecast[q_cols].values
        median_forecast = values[:, 49]  # q50

        assert np.mean(median_forecast) > 500, (
            f"Median forecast mean ({np.mean(median_forecast):.1f}) "
            f"is unreasonably low for MW load"
        )
        assert np.mean(median_forecast) < 5000, (
            f"Median forecast mean ({np.mean(median_forecast):.1f}) "
            f"is unreasonably high for MW load"
        )


class TestForecastAccuracy:
    """Tests for forecast accuracy using pinball loss."""

    def test_pinball_loss_below_threshold(self, forecast, actuals):
        """Mean pinball loss must be below the threshold."""
        q_cols = [f"q{i:02d}" for i in range(1, 100)]
        predicted = forecast[q_cols].values
        actual = actuals["load"].values

        assert len(actual) == len(predicted), (
            f"Mismatch: {len(actual)} actuals vs {len(predicted)} forecasts"
        )

        total_loss = 0.0
        for i, tau in enumerate(QUANTILES):
            errors = actual - predicted[:, i]
            loss = np.where(errors >= 0, tau * errors, (tau - 1) * errors)
            total_loss += np.mean(loss)

        mean_pinball = total_loss / N_QUANTILES

        assert mean_pinball < PINBALL_THRESHOLD, (
            f"Mean pinball loss {mean_pinball:.2f} MW exceeds "
            f"threshold {PINBALL_THRESHOLD} MW"
        )

    def test_forecast_spread_reasonable(self, forecast):
        """The 90% prediction interval should have non-trivial width."""
        q_cols = [f"q{i:02d}" for i in range(1, 100)]
        values = forecast[q_cols].values

        # 90% PI width: q95 - q05
        pi_width = values[:, 94] - values[:, 4]
        mean_width = np.mean(pi_width)

        assert mean_width > 20.0, (
            f"90% PI mean width ({mean_width:.1f} MW) is too narrow — "
            f"suggests the model is not capturing uncertainty"
        )
        assert mean_width < 2000.0, (
            f"90% PI mean width ({mean_width:.1f} MW) is unreasonably wide"
        )
