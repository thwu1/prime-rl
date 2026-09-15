
import json
import sqlite3
import numpy as np
import pandas as pd
import pytest
from scipy.optimize import minimize as sp_minimize


WINDOW = 36


@pytest.fixture
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture
def returns():
    """Reconstruct return matrix from the SQLite price database."""
    conn = sqlite3.connect("/app/data/markets.db")
    assets_df = pd.read_sql("SELECT id, ticker FROM assets ORDER BY id", conn)
    tickers = assets_df['ticker'].tolist()
    prices_df = pd.read_sql(
        "SELECT ph.date, a.ticker, ph.price "
        "FROM price_history ph JOIN assets a ON ph.asset_id = a.id "
        "ORDER BY ph.date, a.id", conn)
    conn.close()
    prices_wide = prices_df.pivot(index='date', columns='ticker', values='price')
    prices_wide.index = pd.to_datetime(prices_wide.index)
    prices_wide = prices_wide.sort_index()
    ret = prices_wide.pct_change().iloc[1:]
    return ret[tickers]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _backtest_naive(ret_matrix):
    n_months, n_assets = ret_matrix.shape
    w = np.ones(n_assets) / n_assets
    w_prev = w.copy()
    port_returns, turnovers = [], []
    for t in range(WINDOW, n_months):
        turnovers.append(np.sum(np.abs(w - w_prev)))
        port_returns.append(w @ ret_matrix[t])
        w_after = w * (1 + ret_matrix[t])
        w_prev = w_after / w_after.sum()
    return np.array(port_returns), np.array(turnovers)


def _backtest_mvp(ret_matrix):
    n_months, n_assets = ret_matrix.shape
    w_prev = np.ones(n_assets) / n_assets
    port_returns, turnovers = [], []
    for t in range(WINDOW, n_months):
        hist = ret_matrix[t - WINDOW:t]
        sigma_hat = np.cov(hist, rowvar=False)
        iota = np.ones(n_assets)
        si = np.linalg.inv(sigma_hat)
        w = si @ iota / (iota @ si @ iota)
        turnovers.append(np.sum(np.abs(w - w_prev)))
        port_returns.append(w @ ret_matrix[t])
        w_after = w * (1 + ret_matrix[t])
        w_prev = w_after / w_after.sum()
    return np.array(port_returns), np.array(turnovers)


def _backtest_efficient(ret_matrix, gamma=2):
    n_months, n_assets = ret_matrix.shape
    w_prev = np.ones(n_assets) / n_assets
    port_returns, turnovers = [], []
    for t in range(WINDOW, n_months):
        hist = ret_matrix[t - WINDOW:t]
        mu_hat = hist.mean(axis=0)
        sigma_hat = np.cov(hist, rowvar=False)
        iota = np.ones(n_assets)
        si = np.linalg.inv(sigma_hat)
        wm = si @ iota / (iota @ si @ iota)
        w = wm + (1 / gamma) * (si - np.outer(wm, iota) @ si) @ mu_hat
        turnovers.append(np.sum(np.abs(w - w_prev)))
        port_returns.append(w @ ret_matrix[t])
        w_after = w * (1 + ret_matrix[t])
        w_prev = w_after / w_after.sum()
    return np.array(port_returns), np.array(turnovers)


def _backtest_constrained(ret_matrix, gamma=2):
    n_months, n_assets = ret_matrix.shape
    w_prev = np.ones(n_assets) / n_assets
    port_returns, turnovers = [], []
    for t in range(WINDOW, n_months):
        hist = ret_matrix[t - WINDOW:t]
        mu_hat = hist.mean(axis=0)
        sigma_hat = np.cov(hist, rowvar=False)
        n = n_assets

        def _obj(w, s=sigma_hat, m=mu_hat):
            return gamma / 2 * w @ s @ w - w @ m

        def _grad(w, s=sigma_hat, m=mu_hat):
            return gamma * s @ w - m

        cons = {"type": "eq", "fun": lambda w: np.sum(w) - 1,
                "jac": lambda w: np.ones(n)}
        res = sp_minimize(_obj, np.ones(n) / n, jac=_grad, constraints=cons,
                          bounds=[(0, None)] * n, method="SLSQP",
                          tol=1e-20, options={"maxiter": 10000})
        w = res.x
        turnovers.append(np.sum(np.abs(w - w_prev)))
        port_returns.append(w @ ret_matrix[t])
        w_after = w * (1 + ret_matrix[t])
        w_prev = w_after / w_after.sum()
    return np.array(port_returns), np.array(turnovers)


def _backtest_tc(ret_matrix, gamma=2, beta=0.005):
    n_months, n_assets = ret_matrix.shape
    w_prev = np.ones(n_assets) / n_assets
    port_returns, turnovers = [], []
    for t in range(WINDOW, n_months):
        hist = ret_matrix[t - WINDOW:t]
        mu_hat = hist.mean(axis=0)
        sigma_hat = np.cov(hist, rowvar=False)
        iota = np.ones(n_assets)
        ss = sigma_hat + (beta / gamma) * np.eye(n_assets)
        ms = mu_hat + beta * w_prev
        si = np.linalg.inv(ss)
        wm = si @ iota / (iota @ si @ iota)
        w = wm + (1 / gamma) * (si - np.outer(wm, iota) @ si) @ ms
        turnovers.append(np.sum(np.abs(w - w_prev)))
        port_returns.append(w @ ret_matrix[t])
        w_after = w * (1 + ret_matrix[t])
        w_prev = w_after / w_after.sum()
    return np.array(port_returns), np.array(turnovers)


def _backtest_tc_net(ret_matrix, gamma=2, beta=0.005):
    """TC-adjusted backtest returning net-of-costs returns."""
    n_months, n_assets = ret_matrix.shape
    w_prev = np.ones(n_assets) / n_assets
    net_returns = []
    for t in range(WINDOW, n_months):
        hist = ret_matrix[t - WINDOW:t]
        mu_hat = hist.mean(axis=0)
        sigma_hat = np.cov(hist, rowvar=False)
        iota = np.ones(n_assets)
        ss = sigma_hat + (beta / gamma) * np.eye(n_assets)
        ms = mu_hat + beta * w_prev
        si = np.linalg.inv(ss)
        wm = si @ iota / (iota @ si @ iota)
        w = wm + (1 / gamma) * (si - np.outer(wm, iota) @ si) @ ms
        tc_cost = (beta / 2) * np.sum((w - w_prev) ** 2)
        net_returns.append(w @ ret_matrix[t] - tc_cost)
        w_after = w * (1 + ret_matrix[t])
        w_prev = w_after / w_after.sum()
    return np.array(net_returns)


def _metrics(port_returns, turnovers):
    ann_ret = (1 + np.mean(port_returns)) ** 12 - 1
    ann_vol = np.std(port_returns, ddof=1) * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    cum = np.cumprod(1 + port_returns)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum) / peak
    max_dd = np.max(dd)
    avg_to = np.mean(turnovers)
    return {
        "annualized_return": ann_ret,
        "annualized_volatility": ann_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "avg_monthly_turnover": avg_to,
    }


def _net_sharpe(port_returns):
    ann_ret = (1 + np.mean(port_returns)) ** 12 - 1
    ann_vol = np.std(port_returns, ddof=1) * np.sqrt(12)
    return ann_ret / ann_vol if ann_vol > 0 else 0.0


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_json_exists(self, results):
        assert results is not None

    def test_all_strategies_present(self, results):
        expected = {"naive", "mvp", "efficient", "constrained", "tc_adjusted"}
        assert set(results["strategies"].keys()) == expected

    def test_all_metrics_present(self, results):
        keys = {"annualized_return", "annualized_volatility",
                "sharpe_ratio", "max_drawdown", "avg_monthly_turnover"}
        for name, m in results["strategies"].items():
            assert set(m.keys()) == keys, f"Missing metrics for {name}"

    def test_optimal_beta_present(self, results):
        assert "optimal_beta" in results
        assert "optimal_beta_sharpe" in results

    def test_optimal_beta_in_range(self, results):
        assert 0 < results["optimal_beta"] <= 0.05


# ---------------------------------------------------------------------------
# Naive strategy reference
# ---------------------------------------------------------------------------

class TestNaive:
    def test_naive_metrics(self, results, returns):
        ret_matrix = returns.values
        rets, turns = _backtest_naive(ret_matrix)
        ref = _metrics(rets, turns)
        agent = results["strategies"]["naive"]
        for k in ref:
            assert abs(agent[k] - ref[k]) < 1e-4, \
                f"naive.{k}: agent={agent[k]}, ref={ref[k]}"


# ---------------------------------------------------------------------------
# MVP strategy reference
# ---------------------------------------------------------------------------

class TestMVP:
    def test_mvp_metrics(self, results, returns):
        ret_matrix = returns.values
        rets, turns = _backtest_mvp(ret_matrix)
        ref = _metrics(rets, turns)
        agent = results["strategies"]["mvp"]
        for k in ref:
            assert abs(agent[k] - ref[k]) < 1e-4, \
                f"mvp.{k}: agent={agent[k]}, ref={ref[k]}"


# ---------------------------------------------------------------------------
# Efficient strategy reference
# ---------------------------------------------------------------------------

class TestEfficient:
    def test_efficient_metrics(self, results, returns):
        ret_matrix = returns.values
        rets, turns = _backtest_efficient(ret_matrix)
        ref = _metrics(rets, turns)
        agent = results["strategies"]["efficient"]
        for k in ref:
            assert abs(agent[k] - ref[k]) < 1e-4, \
                f"efficient.{k}: agent={agent[k]}, ref={ref[k]}"


# ---------------------------------------------------------------------------
# Constrained strategy reference
# ---------------------------------------------------------------------------

class TestConstrained:
    def test_constrained_metrics(self, results, returns):
        ret_matrix = returns.values
        rets, turns = _backtest_constrained(ret_matrix)
        ref = _metrics(rets, turns)
        agent = results["strategies"]["constrained"]
        for k in ref:
            assert abs(agent[k] - ref[k]) < 1e-3, \
                f"constrained.{k}: agent={agent[k]}, ref={ref[k]}"

    def test_constrained_differs_from_efficient(self, results):
        c = results["strategies"]["constrained"]
        e = results["strategies"]["efficient"]
        assert abs(c["sharpe_ratio"] - e["sharpe_ratio"]) > 1e-6


# ---------------------------------------------------------------------------
# TC-adjusted strategy reference
# ---------------------------------------------------------------------------

class TestTCAdjusted:
    def test_tc_adjusted_metrics(self, results, returns):
        ret_matrix = returns.values
        rets, turns = _backtest_tc(ret_matrix)
        ref = _metrics(rets, turns)
        agent = results["strategies"]["tc_adjusted"]
        for k in ref:
            assert abs(agent[k] - ref[k]) < 1e-4, \
                f"tc_adjusted.{k}: agent={agent[k]}, ref={ref[k]}"

    def test_tc_lower_turnover_than_efficient(self, results):
        tc = results["strategies"]["tc_adjusted"]["avg_monthly_turnover"]
        ef = results["strategies"]["efficient"]["avg_monthly_turnover"]
        assert tc < ef, f"TC turnover {tc} >= efficient turnover {ef}"


# ---------------------------------------------------------------------------
# Optimal beta
# ---------------------------------------------------------------------------

class TestOptimalBeta:
    def test_optimal_beta_self_consistent(self, results, returns):
        """Recompute Sharpe at the reported optimal beta and compare."""
        ret_matrix = returns.values
        beta = results["optimal_beta"]
        net_rets = _backtest_tc_net(ret_matrix, beta=beta)
        ref_sharpe = _net_sharpe(net_rets)
        assert abs(results["optimal_beta_sharpe"] - ref_sharpe) < 1e-3, \
            f"Reported Sharpe {results['optimal_beta_sharpe']} != recomputed {ref_sharpe}"

    def test_optimal_beta_is_local_max(self, results, returns):
        """Nearby beta values should yield lower or equal net Sharpe."""
        ret_matrix = returns.values
        opt_beta = results["optimal_beta"]
        opt_sharpe = _net_sharpe(
            _backtest_tc_net(ret_matrix, beta=opt_beta)
        )
        for delta in [0.001, 0.002, 0.005]:
            for sign in [-1, 1]:
                nb = opt_beta + sign * delta
                if 0.0001 <= nb <= 0.05:
                    ns = _net_sharpe(
                        _backtest_tc_net(ret_matrix, beta=nb)
                    )
                    assert opt_sharpe >= ns - 1e-3, \
                        f"beta={nb:.4f} Sharpe={ns:.6f} > optimal Sharpe={opt_sharpe:.6f}"


# ---------------------------------------------------------------------------
# Metric range sanity
# ---------------------------------------------------------------------------

class TestRanges:
    def test_returns_reasonable(self, results):
        for name, m in results["strategies"].items():
            assert -1.0 < m["annualized_return"] < 2.0, \
                f"{name} return {m['annualized_return']} out of range"

    def test_volatility_positive(self, results):
        for name, m in results["strategies"].items():
            assert m["annualized_volatility"] > 0

    def test_drawdown_range(self, results):
        for name, m in results["strategies"].items():
            assert 0 <= m["max_drawdown"] <= 1.0, \
                f"{name} drawdown {m['max_drawdown']} out of range"

    def test_turnover_nonnegative(self, results):
        for name, m in results["strategies"].items():
            assert m["avg_monthly_turnover"] >= 0

    def test_sharpe_finite(self, results):
        for name, m in results["strategies"].items():
            assert np.isfinite(m["sharpe_ratio"])
