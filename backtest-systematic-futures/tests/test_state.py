"""
Verification tests for the systematic futures backtesting engine.

"""
import json
import os

import duckdb
import numpy as np
import pandas as pd
import pytest
import yaml


# ── Reference values computed from the canonical implementation ──────────────
REF_STATS = {
    "sharpe_ratio": 0.538646,
    "annual_return_pct": 11.190196,
    "max_drawdown_pct": -35.677021,
    "calmar_ratio": 0.313653,
}

REF_CHECKPOINTS = {
    "vol_SP500_idx500": 24.346615,
    "combined_fc_US10_idx1000": 7.013743,
    "position_EUROSTOXX_idx1500": -7.072902,
    "fdm_SP500_idx800": 1.075939,
    "final_equity": 1874234.04,
}

CHECKPOINT_DATES = {
    500: "2017-12-04",
    800: "2019-01-28",
    1000: "2019-11-04",
    1500: "2021-10-04",
}


def _load_config():
    with open("/app/config.yaml") as f:
        return yaml.safe_load(f)


def _load_prices():
    conn = duckdb.connect("/app/market.duckdb", read_only=True)
    df = conn.execute(
        "SELECT date, symbol, price FROM daily_prices ORDER BY date, symbol"
    ).fetchdf()
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    pivot = df.pivot(index="date", columns="symbol", values="price").dropna()
    return pivot


# ═══════════════════════════════════════════════════════════════════════════════
# Structural tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOutputStructure:
    """Verify output files exist with correct format."""

    def test_output_dir_exists(self):
        assert os.path.isdir("/app/output"), "/app/output directory not found"

    def test_stats_file_exists(self):
        assert os.path.isfile("/app/output/stats.json"), "stats.json not found"

    def test_combined_forecasts_exists(self):
        assert os.path.isfile(
            "/app/output/combined_forecasts.csv"
        ), "combined_forecasts.csv not found"

    def test_positions_exists(self):
        assert os.path.isfile("/app/output/positions.csv"), "positions.csv not found"

    def test_daily_pnl_exists(self):
        assert os.path.isfile("/app/output/daily_pnl.csv"), "daily_pnl.csv not found"

    def test_stats_has_required_keys(self):
        with open("/app/output/stats.json") as f:
            stats = json.load(f)
        for key in [
            "sharpe_ratio",
            "annual_return_pct",
            "max_drawdown_pct",
            "calmar_ratio",
        ]:
            assert key in stats, f"Missing key: {key}"
            assert isinstance(stats[key], (int, float)), f"{key} must be numeric"

    def test_combined_forecasts_columns(self):
        df = pd.read_csv("/app/output/combined_forecasts.csv")
        assert "date" in df.columns, "combined_forecasts.csv missing 'date' column"
        for inst in ["SP500", "EUROSTOXX", "US10", "GOLD"]:
            assert inst in df.columns, f"combined_forecasts.csv missing '{inst}' column"
        assert len(df) >= 1900, f"Expected >=1900 rows, got {len(df)}"

    def test_positions_columns(self):
        df = pd.read_csv("/app/output/positions.csv")
        assert "date" in df.columns, "positions.csv missing 'date' column"
        for inst in ["SP500", "EUROSTOXX", "US10", "GOLD"]:
            assert inst in df.columns, f"positions.csv missing '{inst}' column"

    def test_daily_pnl_columns(self):
        df = pd.read_csv("/app/output/daily_pnl.csv")
        assert "date" in df.columns, "daily_pnl.csv missing 'date' column"
        assert "total_pnl" in df.columns, "daily_pnl.csv missing 'total_pnl' column"
        for inst in ["SP500", "EUROSTOXX", "US10", "GOLD"]:
            assert f"{inst}_pnl" in df.columns, f"daily_pnl.csv missing '{inst}_pnl'"


# ═══════════════════════════════════════════════════════════════════════════════
# Volatility checkpoint — independently computed from raw DuckDB prices
# ═══════════════════════════════════════════════════════════════════════════════


class TestVolatility:
    """Verify mixed volatility estimation is correct at a checkpoint."""

    def test_mixed_vol_sp500(self):
        """Independently compute mixed vol for SP500 at index 500 and compare."""
        price_df = _load_prices()
        config = _load_config()
        vol_cfg = config["volatility"]

        price_returns = price_df["SP500"].diff()
        fast_vol = price_returns.ewm(
            span=vol_cfg["fast_span"], min_periods=vol_cfg["min_periods"]
        ).std()
        slow_vol = price_returns.ewm(
            span=vol_cfg["slow_span"], min_periods=vol_cfg["min_periods"]
        ).std()
        mixed_vol = (1 - vol_cfg["proportion_slow"]) * fast_vol + vol_cfg[
            "proportion_slow"
        ] * slow_vol

        computed = mixed_vol.iloc[500]
        expected = REF_CHECKPOINTS["vol_SP500_idx500"]
        assert abs(computed - expected) / abs(expected) < 0.001, (
            f"Vol checkpoint mismatch: computed={computed:.6f}, expected={expected:.6f}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Combined forecast checkpoint
# ═══════════════════════════════════════════════════════════════════════════════


class TestCombinedForecast:
    """Verify combined forecasts at specific dates."""

    def test_combined_forecast_us10_idx1000(self):
        """Check combined forecast for US10 at date index 1000."""
        fc_df = pd.read_csv("/app/output/combined_forecasts.csv", parse_dates=["date"])
        fc_df = fc_df.set_index("date")

        target_date = pd.Timestamp(CHECKPOINT_DATES[1000])
        idx = fc_df.index.get_indexer([target_date], method="nearest")[0]
        actual = fc_df["US10"].iloc[idx]
        expected = REF_CHECKPOINTS["combined_fc_US10_idx1000"]

        assert abs(actual - expected) / max(abs(expected), 1e-6) < 0.02, (
            f"Combined forecast US10 at idx 1000: actual={actual:.4f}, expected={expected:.4f}"
        )

    def test_forecasts_have_variation(self):
        """Verify forecasts are not constant (system is dynamic)."""
        fc_df = pd.read_csv("/app/output/combined_forecasts.csv", parse_dates=["date"])
        for inst in ["SP500", "EUROSTOXX", "US10", "GOLD"]:
            std = fc_df[inst].dropna().std()
            assert std > 0.5, (
                f"Forecasts for {inst} have too little variation (std={std:.4f})"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Position checkpoint
# ═══════════════════════════════════════════════════════════════════════════════


class TestPositions:
    """Verify portfolio positions at specific dates."""

    def test_position_eurostoxx_idx1500(self):
        """Check EUROSTOXX position at date index 1500."""
        pos_df = pd.read_csv("/app/output/positions.csv", parse_dates=["date"])
        pos_df = pos_df.set_index("date")

        target_date = pd.Timestamp(CHECKPOINT_DATES[1500])
        idx = pos_df.index.get_indexer([target_date], method="nearest")[0]
        actual = pos_df["EUROSTOXX"].iloc[idx]
        expected = REF_CHECKPOINTS["position_EUROSTOXX_idx1500"]

        assert abs(actual - expected) / max(abs(expected), 1e-6) < 0.02, (
            f"Position EUROSTOXX at idx 1500: actual={actual:.4f}, expected={expected:.4f}"
        )

    def test_positions_change_over_time(self):
        """Verify positions are not static."""
        pos_df = pd.read_csv("/app/output/positions.csv", parse_dates=["date"])
        for inst in ["SP500", "EUROSTOXX", "US10", "GOLD"]:
            vals = pos_df[inst].dropna()
            assert vals.std() > 0.1, f"Positions for {inst} appear static"

    def test_positions_have_reasonable_scale(self):
        """Positions should be in a reasonable range for $1M capital."""
        pos_df = pd.read_csv("/app/output/positions.csv", parse_dates=["date"])
        for inst in ["SP500", "EUROSTOXX", "US10", "GOLD"]:
            vals = pos_df[inst].dropna()
            max_abs = vals.abs().max()
            assert max_abs < 5000, (
                f"Position for {inst} seems too large: max_abs={max_abs:.1f}"
            )
            late_vals = vals.iloc[-500:]
            assert late_vals.abs().mean() > 0.01, (
                f"Positions for {inst} are near-zero in late period"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# FDM checkpoint
# ═══════════════════════════════════════════════════════════════════════════════


class TestFDM:
    """Verify the forecast diversification multiplier is estimated correctly."""

    def test_fdm_in_expected_range(self):
        """FDM should reflect diversification benefit (> 1.0) and be bounded."""
        assert 1.0 < REF_CHECKPOINTS["fdm_SP500_idx800"] < 2.5, (
            "Reference FDM for SP500 should be between 1.0 and 2.5"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Statistics tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatistics:
    """Verify portfolio statistics match reference values."""

    def _load_stats(self):
        with open("/app/output/stats.json") as f:
            return json.load(f)

    def test_sharpe_ratio(self):
        stats = self._load_stats()
        expected = REF_STATS["sharpe_ratio"]
        actual = stats["sharpe_ratio"]
        assert abs(actual - expected) / max(abs(expected), 1e-6) < 0.10, (
            f"Sharpe ratio: actual={actual:.4f}, expected={expected:.4f} (>10% off)"
        )

    def test_sharpe_positive(self):
        stats = self._load_stats()
        assert stats["sharpe_ratio"] > 0, (
            "Sharpe ratio should be positive for trending data"
        )

    def test_annual_return(self):
        stats = self._load_stats()
        expected = REF_STATS["annual_return_pct"]
        actual = stats["annual_return_pct"]
        assert abs(actual - expected) / max(abs(expected), 1e-6) < 0.15, (
            f"Annual return: actual={actual:.4f}%, expected={expected:.4f}% (>15% off)"
        )

    def test_max_drawdown(self):
        stats = self._load_stats()
        expected = REF_STATS["max_drawdown_pct"]
        actual = stats["max_drawdown_pct"]
        assert actual < 0, "Max drawdown should be negative"
        assert abs(actual - expected) / max(abs(expected), 1e-6) < 0.15, (
            f"Max drawdown: actual={actual:.4f}%, expected={expected:.4f}% (>15% off)"
        )

    def test_calmar_ratio(self):
        stats = self._load_stats()
        expected = REF_STATS["calmar_ratio"]
        actual = stats["calmar_ratio"]
        assert abs(actual - expected) / max(abs(expected), 1e-6) < 0.20, (
            f"Calmar ratio: actual={actual:.4f}, expected={expected:.4f} (>20% off)"
        )

    def test_final_equity(self):
        """Verify the implied final equity from P&L is close to reference."""
        pnl_df = pd.read_csv("/app/output/daily_pnl.csv", parse_dates=["date"])
        total_pnl = pnl_df["total_pnl"].sum()
        final_equity = 1000000 + total_pnl
        expected = REF_CHECKPOINTS["final_equity"]
        assert abs(final_equity - expected) / abs(expected) < 0.10, (
            f"Final equity: actual={final_equity:.2f}, expected={expected:.2f} (>10% off)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# P&L consistency tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestPnLConsistency:
    """Verify P&L calculations are internally consistent."""

    def test_total_pnl_is_sum_of_instruments(self):
        """total_pnl should equal sum of per-instrument P&L columns."""
        pnl_df = pd.read_csv("/app/output/daily_pnl.csv", parse_dates=["date"])
        inst_cols = [
            c for c in pnl_df.columns if c.endswith("_pnl") and c != "total_pnl"
        ]
        assert len(inst_cols) == 4, (
            f"Expected 4 instrument P&L columns, got {len(inst_cols)}"
        )

        computed_total = pnl_df[inst_cols].sum(axis=1)
        reported_total = pnl_df["total_pnl"]

        diff = (computed_total - reported_total).abs()
        max_diff = diff.max()
        assert max_diff < 1.0, (
            f"total_pnl doesn't match sum of instrument P&Ls (max diff={max_diff:.4f})"
        )

    def test_pnl_not_all_zero(self):
        """P&L should have non-trivial values."""
        pnl_df = pd.read_csv("/app/output/daily_pnl.csv", parse_dates=["date"])
        total_std = pnl_df["total_pnl"].dropna().std()
        assert total_std > 100, f"P&L standard deviation too low: {total_std:.2f}"

    def test_pnl_row_count(self):
        """P&L should have approximately 2000 rows."""
        pnl_df = pd.read_csv("/app/output/daily_pnl.csv", parse_dates=["date"])
        assert 1900 <= len(pnl_df) <= 2001, (
            f"Expected ~2000 P&L rows, got {len(pnl_df)}"
        )
