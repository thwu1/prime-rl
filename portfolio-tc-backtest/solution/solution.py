"""
Portfolio backtest with illiquidity-adjusted transaction costs.
Reads data from SQLite, config from TOML, outputs JSON + Parquet.

"""
import numpy as np
import json
import os
import sqlite3
import tomllib
import pyarrow as pa
import pyarrow.parquet as pq


def load_data():
    conn = sqlite3.connect('/app/data/market.db')

    # Get industry list in alphabetical order for consistency
    cur = conn.execute(
        'SELECT DISTINCT industry FROM industry_info ORDER BY industry')
    industries = [row[0] for row in cur.fetchall()]
    N = len(industries)

    # Pivot long-format returns into T x N matrix
    T = conn.execute(
        'SELECT MAX(period) + 1 FROM monthly_returns').fetchone()[0]
    returns = np.zeros((T, N))
    for row in conn.execute(
            'SELECT period, industry, return_value FROM monthly_returns'):
        period, ind, val = row
        returns[period, industries.index(ind)] = val

    # Load illiquidity in same industry order
    illiquidity = np.zeros(N)
    for row in conn.execute('SELECT industry, illiquidity FROM industry_info'):
        ind, illiq = row
        illiquidity[industries.index(ind)] = illiq

    conn.close()

    # Parse TOML config
    with open('/app/config.toml', 'rb') as f:
        config = tomllib.load(f)

    return returns, illiquidity, industries, config


def compute_efficient_weight(sigma, mu, gamma, beta, w_prev, B_mat):
    """Closed-form MV efficient portfolio with quadratic TC adjustment."""
    n = sigma.shape[0]
    iota = np.ones(n)
    sigma_star = sigma + (beta / gamma) * B_mat
    mu_star = mu + beta * (B_mat @ w_prev)
    sigma_star_inv = np.linalg.inv(sigma_star)
    w_mvp = sigma_star_inv @ iota / (iota @ sigma_star_inv @ iota)
    w_opt = w_mvp + (1.0 / gamma) * (
        sigma_star_inv - np.outer(w_mvp, iota) @ sigma_star_inv
    ) @ mu_star
    return w_opt


def adjust_weights(w, ret):
    w_drifted = w * (1.0 + ret)
    return w_drifted / np.sum(w_drifted)


def run_backtest(returns, illiquidity, config, strategy,
                 beta_construct, beta_eval):
    N = returns.shape[1]
    T = returns.shape[0]
    gamma = config['backtest']['gamma']
    wl = int(config['backtest']['window_length'])
    tc_scale = config['backtest']['tc_scale']
    periods = T - wl
    iota = np.ones(N)
    I_N = np.eye(N)
    B = np.diag(illiquidity)

    w_prev_plus = np.ones(N) / N
    net_rets = np.zeros(periods)
    turnovers = np.zeros(periods)
    weights_record = {}

    for p in range(periods):
        rw = returns[p:p + wl]
        nr = returns[p + wl]
        sigma_hat = np.cov(rw.T)
        mu_hat = rw.mean(axis=0)

        if strategy == 'naive':
            w_new = np.ones(N) / N
        elif strategy == 'mvp':
            si = np.linalg.inv(sigma_hat)
            w_new = si @ iota / (iota @ si @ iota)
        elif strategy == 'mv_tc_iso':
            w_new = compute_efficient_weight(
                sigma_hat, mu_hat, gamma, beta_construct, w_prev_plus, I_N)
        elif strategy == 'mv_tc_illiq':
            w_new = compute_efficient_weight(
                sigma_hat, mu_hat, gamma, beta_construct, w_prev_plus, B)
        else:
            raise ValueError(strategy)

        weights_record[p] = w_new.copy()
        raw_ret = w_new @ nr
        to = np.sum(np.abs(w_new - w_prev_plus) * illiquidity)
        net_rets[p] = raw_ret - (beta_eval / tc_scale) * to
        turnovers[p] = to
        w_prev_plus = adjust_weights(w_new, nr)

    sharpe = np.mean(net_rets) / np.std(net_rets, ddof=1) * np.sqrt(12)
    return {
        'sharpe_ratio': float(sharpe),
        'mean_return_ann_pct': float(np.mean(net_rets) * 12 * 100),
        'volatility_ann_pct': float(
            np.std(net_rets, ddof=1) * np.sqrt(12) * 100),
        'avg_turnover': float(np.mean(turnovers)),
        'weights_record': weights_record,
    }


def main():
    returns, illiquidity, industries, config = load_data()
    bd = int(config['backtest']['beta_default'])

    strategies = ['naive', 'mvp', 'mv_tc_iso', 'mv_tc_illiq']
    performance = {}
    weights_250 = {}
    all_weight_rows = []

    for strat in strategies:
        beta_c = bd if strat in ('mv_tc_iso', 'mv_tc_illiq') else 0
        res = run_backtest(returns, illiquidity, config, strat, beta_c, bd)
        performance[strat] = {
            'sharpe_ratio': res['sharpe_ratio'],
            'mean_return_ann_pct': res['mean_return_ann_pct'],
            'volatility_ann_pct': res['volatility_ann_pct'],
            'avg_turnover': res['avg_turnover'],
        }
        # Period 250 weights as dict {industry: weight}
        w250 = res['weights_record'][250]
        weights_250[strat] = {
            ind: float(w250[i]) for i, ind in enumerate(industries)}

        # Collect all weights for Parquet output
        for p, w in res['weights_record'].items():
            row = {'period': int(p), 'strategy': strat}
            for i, ind in enumerate(industries):
                row[ind] = float(w[i])
            all_weight_rows.append(row)

    # Grid search for optimal beta_construct
    gs = config['grid_search']
    beta_grid = list(range(
        int(gs['beta_start']), int(gs['beta_end']) + 1,
        int(gs['beta_step'])))
    best_sharpe = -np.inf
    best_beta = 0
    for bc in beta_grid:
        r = run_backtest(returns, illiquidity, config, 'mv_tc_illiq', bc, bd)
        if r['sharpe_ratio'] > best_sharpe:
            best_sharpe = r['sharpe_ratio']
            best_beta = bc

    # Write JSON results
    os.makedirs('/app/results', exist_ok=True)

    with open('/app/results/performance.json', 'w') as f:
        json.dump(performance, f, indent=2)

    with open('/app/results/optimal_beta.json', 'w') as f:
        json.dump({
            'optimal_beta': int(best_beta),
            'sharpe_at_optimal': float(best_sharpe),
        }, f, indent=2)

    ranking = sorted(
        performance.keys(),
        key=lambda x: performance[x]['sharpe_ratio'],
        reverse=True)
    with open('/app/results/strategy_ranking.json', 'w') as f:
        json.dump(ranking, f, indent=2)

    with open('/app/results/weights_period_250.json', 'w') as f:
        json.dump(weights_250, f, indent=2)

    # Write Parquet weight history
    all_weight_rows.sort(key=lambda r: (r['period'], r['strategy']))
    columns = ['period', 'strategy'] + industries
    arrays = {col: [row[col] for row in all_weight_rows] for col in columns}
    table = pa.table(arrays)
    pq.write_table(table, '/app/results/weight_history.parquet')

    print("Results saved to /app/results/")
    for s in strategies:
        print(f"  {s}: Sharpe={performance[s]['sharpe_ratio']:.4f}")
    print(f"  Optimal beta: {best_beta} (Sharpe={best_sharpe:.4f})")
    print(f"  Ranking: {ranking}")


if __name__ == '__main__':
    main()
