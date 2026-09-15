"""
Tests for WSPL evaluation and hierarchical quantile forecast reconciliation.

"""
import json
import csv
import os
import math

import pytest

# ── Constants ──────────────────────────────────────────────────────────
DATA_DIR = "/app/data"
OUTPUT_DIR = "/app/output"
N_FORECAST = 28
QUANTILES = [0.005, 0.025, 0.165, 0.25, 0.5, 0.75, 0.835, 0.975, 0.995]


# ── Helpers ────────────────────────────────────────────────────────────
def load_hierarchy():
    with open(os.path.join(DATA_DIR, "hierarchy.json")) as f:
        return json.load(f)


def load_weights():
    with open(os.path.join(DATA_DIR, "weights.json")) as f:
        return json.load(f)


def load_csv_data(filename):
    """Load a CSV with series_name as key. For actuals/history: {name: [values]}.
    For forecasts: {(name, quantile_str): [values]}."""
    path = os.path.join(DATA_DIR, filename) if "/" not in filename else filename
    data = {}
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        has_quantile = "quantile" in header
        for row in reader:
            if has_quantile:
                key = (row[0], row[1])
                vals = [float(x) for x in row[2:]]
            else:
                key = row[0]
                vals = [float(x) for x in row[1:]]
            data[key] = vals
    return data


def load_forecasts_csv(path):
    """Load forecasts CSV into {(series_name, quantile_str): [h1..h28]}."""
    data = {}
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            key = (row[0], row[1])
            vals = [float(x) for x in row[2:]]
            data[key] = vals
    return data


def load_scores():
    path = os.path.join(OUTPUT_DIR, "scores.json")
    with open(path) as f:
        return json.load(f)


def pinball_loss(q, y, y_hat):
    diff = y - y_hat
    if diff >= 0:
        return q * diff
    else:
        return (1 - q) * (-diff)


def compute_scale_factor(history_vals):
    diffs = [abs(history_vals[t] - history_vals[t - 1]) for t in range(1, len(history_vals))]
    s = sum(diffs) / len(diffs) if diffs else 1.0
    return max(s, 1.0)


def compute_wspl_from_forecasts(forecasts, actuals, history_data, weights, hierarchy):
    """Independently compute WSPL from forecast data."""
    level_order = hierarchy["level_order"]
    levels = hierarchy["levels"]
    n_q = len(QUANTILES)

    level_wspls = {}
    for level_name in level_order:
        level_wspl = 0.0
        for q in QUANTILES:
            q_str = f"{q:.3f}"
            weighted_spl = 0.0
            for series_name in levels[level_name]:
                w = weights[level_name][series_name]
                hist = history_data[series_name]
                s = compute_scale_factor(hist)
                y_vals = actuals[series_name]
                y_hat_vals = forecasts[(series_name, q_str)]
                pl_sum = sum(
                    pinball_loss(q, y_vals[h], y_hat_vals[h])
                    for h in range(N_FORECAST)
                )
                avg_spl = (pl_sum / N_FORECAST) / s
                weighted_spl += w * avg_spl
            level_wspl += weighted_spl
        level_wspl /= n_q
        level_wspls[level_name] = level_wspl

    overall = sum(level_wspls.values()) / len(level_wspls)
    return overall, level_wspls


# ── Tests ──────────────────────────────────────────────────────────────

class TestOutputStructure:
    """Verify output files exist and have correct structure."""

    def test_scores_json_exists(self):
        path = os.path.join(OUTPUT_DIR, "scores.json")
        assert os.path.isfile(path), "scores.json not found in /app/output/"

    def test_scores_json_keys(self):
        scores = load_scores()
        assert "base_wspl" in scores, "scores.json missing 'base_wspl'"
        assert "reconciled_wspl" in scores, "scores.json missing 'reconciled_wspl'"
        assert "level_wspls" in scores, "scores.json missing 'level_wspls'"

    def test_scores_json_level_wspls_keys(self):
        scores = load_scores()
        hierarchy = load_hierarchy()
        expected_levels = set(hierarchy["level_order"])
        actual_levels = set(scores["level_wspls"].keys())
        assert expected_levels == actual_levels, (
            f"level_wspls keys mismatch: expected {expected_levels}, got {actual_levels}"
        )

    def test_reconciled_csv_exists(self):
        path = os.path.join(OUTPUT_DIR, "reconciled_forecasts.csv")
        assert os.path.isfile(path), "reconciled_forecasts.csv not found in /app/output/"

    def test_reconciled_csv_row_count(self):
        """Should have 40 series x 9 quantiles = 360 data rows."""
        path = os.path.join(OUTPUT_DIR, "reconciled_forecasts.csv")
        with open(path) as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            rows = list(reader)
        assert len(rows) == 360, f"Expected 360 rows, got {len(rows)}"

    def test_reconciled_csv_columns(self):
        """Each row should have series_name + quantile + 28 horizon values = 30 columns."""
        path = os.path.join(OUTPUT_DIR, "reconciled_forecasts.csv")
        with open(path) as f:
            reader = csv.reader(f)
            header = next(reader)
        assert len(header) == 30, f"Expected 30 columns, got {len(header)}"

    def test_reconciled_csv_all_series_present(self):
        """All 40 series names should appear in the reconciled CSV."""
        hierarchy = load_hierarchy()
        all_series = set()
        for level_name in hierarchy["level_order"]:
            for sn in hierarchy["levels"][level_name]:
                all_series.add(sn)

        path = os.path.join(OUTPUT_DIR, "reconciled_forecasts.csv")
        found_series = set()
        with open(path) as f:
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                found_series.add(row[0])

        missing = all_series - found_series
        assert not missing, f"Missing series in reconciled CSV: {missing}"


class TestWSPLComputation:
    """Verify the agent correctly computed WSPL for the base forecasts."""

    def test_base_wspl_matches_independent(self):
        """Independently compute base WSPL from base_forecasts.csv and compare."""
        base_forecasts = load_csv_data("base_forecasts.csv")
        actuals = load_csv_data("actuals.csv")
        history = load_csv_data("history.csv")
        weights = load_weights()
        hierarchy = load_hierarchy()

        computed_base_wspl, _ = compute_wspl_from_forecasts(
            base_forecasts, actuals, history, weights, hierarchy
        )

        scores = load_scores()
        reported_base_wspl = scores["base_wspl"]

        assert abs(computed_base_wspl - reported_base_wspl) < 0.005, (
            f"Independently computed base WSPL ({computed_base_wspl:.6f}) differs from "
            f"reported ({reported_base_wspl:.6f}) by "
            f"{abs(computed_base_wspl - reported_base_wspl):.6f}"
        )

    def test_base_wspl_in_range(self):
        """Base WSPL should be in a reasonable range for this data."""
        scores = load_scores()
        base_wspl = scores["base_wspl"]
        assert 0.01 < base_wspl < 5.0, (
            f"Base WSPL {base_wspl} outside reasonable range (0.01, 5.0)"
        )

    def test_base_wspl_positive(self):
        scores = load_scores()
        assert scores["base_wspl"] > 0, "Base WSPL should be positive"

    def test_reconciled_wspl_positive(self):
        scores = load_scores()
        assert scores["reconciled_wspl"] > 0, "Reconciled WSPL should be positive"


class TestReconciliation:
    """Verify properties of the reconciled forecasts."""

    def test_wspl_improvement(self):
        """Reconciled WSPL must be strictly less than base WSPL."""
        scores = load_scores()
        assert scores["reconciled_wspl"] < scores["base_wspl"], (
            f"Reconciled WSPL ({scores['reconciled_wspl']}) should be less than "
            f"base WSPL ({scores['base_wspl']})"
        )

    def test_quantile_monotonicity(self):
        """For each series and horizon, quantile forecasts must be non-decreasing."""
        path = os.path.join(OUTPUT_DIR, "reconciled_forecasts.csv")
        forecasts = load_forecasts_csv(path)

        hierarchy = load_hierarchy()
        all_series = []
        for level_name in hierarchy["level_order"]:
            for sn in hierarchy["levels"][level_name]:
                all_series.append(sn)

        violations = 0
        for sn in all_series:
            for h in range(N_FORECAST):
                prev_val = -1e30
                for q in QUANTILES:
                    q_str = f"{q:.3f}"
                    key = (sn, q_str)
                    if key not in forecasts:
                        continue
                    val = forecasts[key][h]
                    if val < prev_val - 0.01:
                        violations += 1
                    prev_val = val

        assert violations == 0, (
            f"Found {violations} quantile monotonicity violations in reconciled forecasts"
        )

    def test_hierarchical_coherence(self):
        """Upper-level quantile forecasts must equal sum of bottom-level constituents."""
        path = os.path.join(OUTPUT_DIR, "reconciled_forecasts.csv")
        forecasts = load_forecasts_csv(path)
        hierarchy = load_hierarchy()
        bottom_series = hierarchy["bottom_series"]

        max_err = 0.0
        violations = []

        for level_name in ['Total', 'Region', 'Store', 'Category', 'Region_Category']:
            for series_name, indices in hierarchy["levels"][level_name].items():
                for q in QUANTILES:
                    q_str = f"{q:.3f}"
                    upper_key = (series_name, q_str)
                    if upper_key not in forecasts:
                        violations.append(f"Missing {upper_key} in reconciled forecasts")
                        continue

                    for h in range(N_FORECAST):
                        upper_val = forecasts[upper_key][h]
                        bottom_sum = sum(
                            forecasts[(bottom_series[bi], q_str)][h]
                            for bi in indices
                            if (bottom_series[bi], q_str) in forecasts
                        )
                        err = abs(upper_val - bottom_sum)
                        if err > max_err:
                            max_err = err
                        if err > 0.01:
                            violations.append(
                                f"{series_name} q={q_str} h={h+1}: "
                                f"upper={upper_val:.4f} sum={bottom_sum:.4f} err={err:.4f}"
                            )

        assert len(violations) == 0, (
            f"Coherence violations (max_err={max_err:.6f}):\n"
            + "\n".join(violations[:20])
        )


class TestIndependentWSPLVerification:
    """Independently recompute WSPL from reconciled CSV and verify consistency."""

    def test_reconciled_wspl_matches_reported(self):
        """Recompute WSPL from reconciled_forecasts.csv and compare to scores.json."""
        path = os.path.join(OUTPUT_DIR, "reconciled_forecasts.csv")
        forecasts = load_forecasts_csv(path)

        actuals = load_csv_data("actuals.csv")
        history = load_csv_data("history.csv")
        weights = load_weights()
        hierarchy = load_hierarchy()

        computed_wspl, computed_levels = compute_wspl_from_forecasts(
            forecasts, actuals, history, weights, hierarchy
        )

        scores = load_scores()
        reported_wspl = scores["reconciled_wspl"]

        assert abs(computed_wspl - reported_wspl) < 0.005, (
            f"Independently computed WSPL ({computed_wspl:.6f}) differs from "
            f"reported ({reported_wspl:.6f}) by {abs(computed_wspl - reported_wspl):.6f}"
        )

    def test_per_level_wspls_match(self):
        """Verify per-level WSPLs are approximately correct."""
        path = os.path.join(OUTPUT_DIR, "reconciled_forecasts.csv")
        forecasts = load_forecasts_csv(path)

        actuals = load_csv_data("actuals.csv")
        history = load_csv_data("history.csv")
        weights = load_weights()
        hierarchy = load_hierarchy()

        _, computed_levels = compute_wspl_from_forecasts(
            forecasts, actuals, history, weights, hierarchy
        )

        scores = load_scores()
        reported_levels = scores["level_wspls"]

        for level_name in hierarchy["level_order"]:
            computed_val = computed_levels[level_name]
            reported_val = reported_levels[level_name]
            assert abs(computed_val - reported_val) < 0.005, (
                f"Level {level_name}: computed={computed_val:.6f} "
                f"vs reported={reported_val:.6f}"
            )

    def test_nonnegative_forecasts(self):
        """All quantile forecast values should be non-negative (sales can't be negative)."""
        path = os.path.join(OUTPUT_DIR, "reconciled_forecasts.csv")
        forecasts = load_forecasts_csv(path)
        neg_count = 0
        for key, vals in forecasts.items():
            for v in vals:
                if v < -0.01:
                    neg_count += 1
        assert neg_count == 0, f"Found {neg_count} negative forecast values"
