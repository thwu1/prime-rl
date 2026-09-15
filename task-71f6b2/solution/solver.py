"""
Portfolio optimization backtesting with transaction cost adjustment.

Reads project configuration from /app/config.toml, extracts price data from
the SQLite database, computes returns, implements five portfolio strategies,
runs rolling-window backtesting, and searches for the optimal friction parameter.
"""

import json
import sqlite3
import tomllib
import numpy as np
import pandas as pd
from scipy.optimize import minimize


def load_config():
    with open("/app/config.toml", "rb") as f:
        return tomllib.load(f)


def load_returns(db_path):
    """Load price data from SQLite and compute simple returns."""
    conn = sqlite3.connect(db_path)
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

    returns = prices_wide.pct_change().iloc[1:]
    return returns[tickers]


def mvp_weights(sigma_hat):
    """Minimum variance portfolio weights (analytical)."""
    n = sigma_hat.shape[0]
    iota = np.ones(n)
    si = np.linalg.inv(sigma_hat)
    w = si @ iota / (iota @ si @ iota)
    return w


def efficient_weights(sigma_hat, mu_hat, gamma):
    """Unconstrained mean-variance efficient portfolio weights (analytical)."""
    n = sigma_hat.shape[0]
    iota = np.ones(n)
    si = np.linalg.inv(sigma_hat)
    w_mvp = si @ iota / (iota @ si @ iota)
    w = w_mvp + (1 / gamma) * (si - np.outer(w_mvp, iota) @ si) @ mu_hat
    return w


def constrained_weights(sigma_hat, mu_hat, gamma):
    """Mean-variance efficient with no-short-selling constraint (numerical)."""
    n = sigma_hat.shape[0]

    def objective(w):
        return gamma / 2 * w @ sigma_hat @ w - w @ mu_hat

    def gradient(w):
        return gamma * sigma_hat @ w - mu_hat

    constraints = {
        "type": "eq",
        "fun": lambda w: np.sum(w) - 1,
        "jac": lambda w: np.ones(n),
    }
    bounds = [(0, None)] * n
    w0 = np.ones(n) / n

    result = minimize(
        objective, w0, jac=gradient, constraints=constraints,
        bounds=bounds, method="SLSQP", tol=1e-20,
        options={"maxiter": 10000},
    )
    return result.x


def tc_adjusted_weights(sigma_hat, mu_hat, gamma, beta, w_prev):
    """TC-adjusted efficient weights via moment augmentation."""
    n = sigma_hat.shape[0]
    iota = np.ones(n)
    sigma_star = sigma_hat + (beta / gamma) * np.eye(n)
    mu_star = mu_hat + beta * w_prev
    si = np.linalg.inv(sigma_star)
    w_mvp = si @ iota / (iota @ si @ iota)
    w = w_mvp + (1 / gamma) * (si - np.outer(w_mvp, iota) @ si) @ mu_star
    return w


def update_weights(w, r):
    """Update portfolio weights after observing returns (passive drift)."""
    w_after = w * (1 + r)
    return w_after / w_after.sum()


def run_backtest(ret_matrix, strategy, window, gamma, beta=0.005):
    """Run rolling-window backtest for a given strategy."""
    n_months, n_assets = ret_matrix.shape
    w_prev = np.ones(n_assets) / n_assets
    port_returns = []
    turnovers = []

    for t in range(window, n_months):
        hist = ret_matrix[t - window:t]
        mu_hat = hist.mean(axis=0)
        sigma_hat = np.cov(hist, rowvar=False)

        if strategy == "naive":
            w = np.ones(n_assets) / n_assets
        elif strategy == "mvp":
            w = mvp_weights(sigma_hat)
        elif strategy == "efficient":
            w = efficient_weights(sigma_hat, mu_hat, gamma)
        elif strategy == "constrained":
            w = constrained_weights(sigma_hat, mu_hat, gamma)
        elif strategy == "tc_adjusted":
            w = tc_adjusted_weights(sigma_hat, mu_hat, gamma, beta, w_prev)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        turnovers.append(np.sum(np.abs(w - w_prev)))
        port_returns.append(w @ ret_matrix[t])
        w_prev = update_weights(w, ret_matrix[t])

    return np.array(port_returns), np.array(turnovers)


def compute_metrics(port_returns, turnovers):
    """Compute annualized performance metrics."""
    mean_ret = np.mean(port_returns)
    ann_ret = (1 + mean_ret) ** 12 - 1
    ann_vol = np.std(port_returns, ddof=1) * np.sqrt(12)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0

    cumulative = np.cumprod(1 + port_returns)
    peak = np.maximum.accumulate(cumulative)
    drawdown = (peak - cumulative) / peak
    max_dd = float(np.max(drawdown))

    return {
        "annualized_return": float(ann_ret),
        "annualized_volatility": float(ann_vol),
        "sharpe_ratio": float(sharpe),
        "max_drawdown": max_dd,
        "avg_monthly_turnover": float(np.mean(turnovers)),
    }


def net_of_costs_returns(ret_matrix, beta, window, gamma):
    """Compute net-of-quadratic-costs returns for TC-adjusted strategy."""
    n_months, n_assets = ret_matrix.shape
    w_prev = np.ones(n_assets) / n_assets
    net_returns = []

    for t in range(window, n_months):
        hist = ret_matrix[t - window:t]
        mu_hat = hist.mean(axis=0)
        sigma_hat = np.cov(hist, rowvar=False)

        w = tc_adjusted_weights(sigma_hat, mu_hat, gamma, beta, w_prev)
        tc_cost = (beta / 2) * np.sum((w - w_prev) ** 2)
        net_returns.append(w @ ret_matrix[t] - tc_cost)
        w_prev = update_weights(w, ret_matrix[t])

    return np.array(net_returns)


def net_sharpe(net_returns):
    """Annualized Sharpe ratio from net return series."""
    ann_ret = (1 + np.mean(net_returns)) ** 12 - 1
    ann_vol = np.std(net_returns, ddof=1) * np.sqrt(12)
    return ann_ret / ann_vol if ann_vol > 0 else 0.0


def main():
    config = load_config()

    db_path = f"/app/{config['data']['database']}"
    window = config['estimation']['window_months']
    gamma = config['risk']['gamma']
    default_beta = config['strategies']['tc_adjusted']['friction_parameter']

    returns = load_returns(db_path)
    ret_matrix = returns.values

    strategies = ["naive", "mvp", "efficient", "constrained", "tc_adjusted"]
    strategy_results = {}
    for s in strategies:
        beta = default_beta if s == "tc_adjusted" else 0.005
        rets, turns = run_backtest(ret_matrix, s, window, gamma, beta)
        strategy_results[s] = compute_metrics(rets, turns)

    betas = np.arange(0.0001, 0.0501, 0.0001)
    sharpes = np.array([
        net_sharpe(net_of_costs_returns(ret_matrix, b, window, gamma))
        for b in betas
    ])
    best_idx = int(np.argmax(sharpes))
    optimal_beta = round(float(betas[best_idx]), 4)
    optimal_sharpe = float(
        net_sharpe(net_of_costs_returns(ret_matrix, optimal_beta, window, gamma))
    )

    output = {
        "strategies": strategy_results,
        "optimal_beta": optimal_beta,
        "optimal_beta_sharpe": optimal_sharpe,
    }

    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Results written to /app/results.json")
    print(f"Optimal beta: {optimal_beta}")
    print(f"Optimal beta Sharpe: {optimal_sharpe:.6f}")


if __name__ == "__main__":
    main()
