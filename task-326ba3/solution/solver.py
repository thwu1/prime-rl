#!/usr/bin/env python3
"""
M6-style financial competition evaluation pipeline.

"""

import json
import os
import numpy as np
import pandas as pd
from scipy import optimize
from scipy.stats import spearmanr


def compute_quintile_indicators(returns, n_assets):
    """
    Compute quintile indicator vectors using M6 tie-handling methodology.

    Ranks assets ascending (lowest return = position 1).
    Uses method='min' for ties.
    For tied groups spanning quintile boundaries, fractional indicators
    are assigned by averaging over the occupied positions.
    """
    ranks = returns.rank(method='min', ascending=True)
    total_ranks = int(ranks.max())

    # Quintile boundaries based on total_ranks (M6 method)
    boundaries = [
        (1, int(0.2 * total_ranks)),
        (int(0.2 * total_ranks) + 1, int(0.4 * total_ranks)),
        (int(0.4 * total_ranks) + 1, int(0.6 * total_ranks)),
        (int(0.6 * total_ranks) + 1, int(0.8 * total_ranks)),
        (int(0.8 * total_ranks) + 1, total_ranks),
    ]

    indicators = {}

    for rank_val in sorted(ranks.unique()):
        group_symbols = ranks[ranks == rank_val].index.tolist()
        n_in_group = len(group_symbols)
        positions = range(int(rank_val), int(rank_val) + n_in_group)

        group_ind = np.zeros(5)
        for pos in positions:
            for q in range(5):
                q_start, q_end = boundaries[q]
                if q_start <= pos <= q_end:
                    group_ind[q] += 1
                    break

        group_ind /= n_in_group

        for sym in group_symbols:
            indicators[sym] = group_ind.copy()

    return indicators


def compute_rps(prices_df, submissions_df, periods_df, symbols, n_assets):
    """Compute per-team average RPS across all periods."""
    teams = sorted(submissions_df['Team'].unique())
    team_rps = {}

    for team in teams:
        period_rps_list = []

        for _, prow in periods_df.iterrows():
            period = prow['period']
            start_date = prow['start_date']
            end_date = prow['end_date']

            # Period returns
            sp = prices_df[prices_df['date'] == start_date].set_index('symbol')['price']
            ep = prices_df[prices_df['date'] == end_date].set_index('symbol')['price']
            returns = ((ep - sp) / sp).reindex(symbols)

            # Quintile indicators with tie handling
            qi = compute_quintile_indicators(returns, n_assets)

            # Team submissions for this period
            tsub = submissions_df[
                (submissions_df['Team'] == team) &
                (submissions_df['Period'] == period)
            ].set_index('Symbol')

            asset_rps = []
            for sym in symbols:
                actual = qi[sym]
                predicted = tsub.loc[sym, ['Rank1', 'Rank2', 'Rank3', 'Rank4', 'Rank5']].values.astype(float)

                cum_a = np.cumsum(actual)
                cum_p = np.cumsum(predicted)
                rps_val = np.mean((cum_a - cum_p) ** 2)
                asset_rps.append(rps_val)

            period_rps_list.append(np.mean(asset_rps))

        team_rps[team] = float(np.mean(period_rps_list))

    return team_rps


def compute_ir(prices_df, submissions_df, periods_df, symbols):
    """Compute per-team Information Ratio across all periods."""
    teams = sorted(submissions_df['Team'].unique())
    team_ir = {}

    for team in teams:
        all_log_returns = []

        for _, prow in periods_df.iterrows():
            period = prow['period']
            start_date = prow['start_date']
            end_date = prow['end_date']

            # Dates in this period
            period_dates = sorted(
                prices_df[
                    (prices_df['date'] >= start_date) &
                    (prices_df['date'] <= end_date)
                ]['date'].unique()
            )

            # Weights for this team-period
            tsub = submissions_df[
                (submissions_df['Team'] == team) &
                (submissions_df['Period'] == period)
            ].set_index('Symbol')
            weights = tsub['Decision'].reindex(symbols).fillna(0)

            # Daily portfolio returns
            for t in range(1, len(period_dates)):
                prev = prices_df[prices_df['date'] == period_dates[t - 1]].set_index('symbol')['price']
                curr = prices_df[prices_df['date'] == period_dates[t]].set_index('symbol')['price']
                daily_ret = ((curr - prev) / prev).reindex(symbols).fillna(0)
                port_ret = float((weights * daily_ret).sum())
                log_ret = np.log(1 + port_ret)
                all_log_returns.append(log_ret)

        log_returns = np.array(all_log_returns)
        if len(log_returns) > 1:
            sd = float(np.std(log_returns, ddof=1))
            if sd > 1e-12:
                team_ir[team] = float(np.sum(log_returns) / sd)
            else:
                team_ir[team] = 0.0
        else:
            team_ir[team] = 0.0

    return team_ir


def compute_or(team_rps, team_ir):
    """Compute Overall Rank: average of RPS rank and IR rank."""
    teams = sorted(team_rps.keys())

    rps_vals = pd.Series({t: team_rps[t] for t in teams})
    ir_vals = pd.Series({t: team_ir[t] for t in teams})

    # RPS rank: lower is better -> ascending rank
    rps_rank = rps_vals.rank(method='average', ascending=True)
    # IR rank: higher is better -> descending rank (negate then ascending)
    ir_rank = (-ir_vals).rank(method='average', ascending=True)

    or_score = (rps_rank + ir_rank) / 2
    return or_score.sort_values().index.tolist()


def compute_crowd_rps(prices_df, submissions_df, periods_df, symbols, n_assets):
    """Compute RPS of the crowd-averaged forecast."""
    prob_cols = ['Rank1', 'Rank2', 'Rank3', 'Rank4', 'Rank5']

    # Average all team forecasts per period-asset
    crowd = submissions_df.groupby(['Period', 'Symbol'])[prob_cols].mean().reset_index()

    # Renormalize probabilities
    for idx in crowd.index:
        psum = crowd.loc[idx, prob_cols].sum()
        if psum > 0:
            crowd.loc[idx, prob_cols] /= psum

    crowd['Team'] = 'CROWD'
    crowd['Decision'] = 0.0

    rps = compute_rps(prices_df, crowd, periods_df, symbols, n_assets)
    return rps['CROWD']


def ledoit_wolf_shrinkage(X):
    """
    Ledoit-Wolf linear shrinkage covariance estimator.
    X: (n_samples, n_features) centered data matrix.
    Shrinkage target: scaled identity (same trace as sample cov).
    """
    n, p = X.shape

    # Sample covariance (1/n, not 1/(n-1) — standard LW uses 1/n)
    S = (X.T @ X) / n

    # Shrinkage target: scaled identity
    mu_val = np.trace(S) / p
    F = mu_val * np.eye(p)

    # Compute optimal shrinkage intensity using LW formula
    # delta = S - F
    delta = S - F

    # Squared Frobenius norm of delta
    delta_sq_sum = np.sum(delta ** 2)

    # Estimate sum of element-wise variances of S
    # Var(S_ij) = (1/n) * (E[x_i^2 x_j^2] - S_ij^2)
    X2 = X ** 2
    phi_mat = (X2.T @ X2) / n - S ** 2
    phi = np.sum(phi_mat) / n

    # Shrinkage intensity
    if delta_sq_sum > 0:
        alpha = max(0.0, min(1.0, phi / delta_sq_sum))
    else:
        alpha = 1.0

    return alpha * F + (1 - alpha) * S


def optimize_portfolio(expected_returns, cov_matrix, max_gross=1.0, min_gross=0.25, max_single=0.1):
    """Mean-variance portfolio optimization maximizing Sharpe ratio."""
    n = len(expected_returns)

    def neg_sharpe(w):
        port_ret = w @ expected_returns
        port_var = w @ cov_matrix @ w
        if port_var < 1e-16:
            return 0.0
        return -port_ret / np.sqrt(port_var)

    constraints = [
        {'type': 'ineq', 'fun': lambda w: max_gross - np.sum(np.abs(w))},
        {'type': 'ineq', 'fun': lambda w: np.sum(np.abs(w)) - min_gross},
    ]

    bounds = [(-max_single, max_single)] * n
    x0 = expected_returns / (np.abs(expected_returns).sum() + 1e-10) * 0.5

    result = optimize.minimize(
        neg_sharpe,
        x0=x0,
        method='SLSQP',
        bounds=bounds,
        constraints=constraints,
        options={'maxiter': 2000, 'ftol': 1e-12}
    )

    return result.x


def compute_connection_scores(submissions_df):
    """Compute forecast-investment Spearman correlation per team."""
    teams = sorted(submissions_df['Team'].unique())
    periods = sorted(submissions_df['Period'].unique())

    connection = {}

    for team in teams:
        correlations = []

        for period in periods:
            tsub = submissions_df[
                (submissions_df['Team'] == team) &
                (submissions_df['Period'] == period)
            ]

            if len(tsub) < 3:
                continue

            expected_q = (
                tsub['Rank1'].values * 1 +
                tsub['Rank2'].values * 2 +
                tsub['Rank3'].values * 3 +
                tsub['Rank4'].values * 4 +
                tsub['Rank5'].values * 5
            )

            decision = tsub['Decision'].values

            corr, _ = spearmanr(expected_q, decision)
            if not np.isnan(corr):
                correlations.append(corr)

        connection[team] = float(np.mean(correlations)) if correlations else 0.0

    return connection


def main():
    # Load data
    prices_df = pd.read_csv('/app/data/prices.csv')
    submissions_df = pd.read_csv('/app/data/submissions.csv')
    periods_df = pd.read_csv('/app/data/periods.csv')
    universe_df = pd.read_csv('/app/data/universe.csv')

    n_assets = len(universe_df)
    symbols = sorted(universe_df['symbol'].tolist())

    # 1. RPS
    team_rps = compute_rps(prices_df, submissions_df, periods_df, symbols, n_assets)

    # 2. IR
    team_ir = compute_ir(prices_df, submissions_df, periods_df, symbols)

    # 3. OR
    or_ranking = compute_or(team_rps, team_ir)

    # 4. Crowd RPS
    crowd_rps = compute_crowd_rps(prices_df, submissions_df, periods_df, symbols, n_assets)

    # 5. Optimal weights from crowd forecast
    # Build daily returns matrix
    all_dates = sorted(prices_df['date'].unique())
    returns_rows = []
    for t in range(1, len(all_dates)):
        prev = prices_df[prices_df['date'] == all_dates[t - 1]].set_index('symbol')['price']
        curr = prices_df[prices_df['date'] == all_dates[t]].set_index('symbol')['price']
        dr = ((curr - prev) / prev).reindex(symbols).fillna(0)
        returns_rows.append(dr.values)
    returns_matrix = np.array(returns_rows)

    # Center
    X = returns_matrix - returns_matrix.mean(axis=0)

    # Ledoit-Wolf covariance
    cov_matrix = ledoit_wolf_shrinkage(X)

    # Crowd expected returns from last period forecast
    prob_cols = ['Rank1', 'Rank2', 'Rank3', 'Rank4', 'Rank5']
    crowd = submissions_df.groupby(['Period', 'Symbol'])[prob_cols].mean().reset_index()
    for idx in crowd.index:
        psum = crowd.loc[idx, prob_cols].sum()
        if psum > 0:
            crowd.loc[idx, prob_cols] /= psum

    last_period = periods_df['period'].iloc[-1]
    last_crowd = crowd[crowd['Period'] == last_period].set_index('Symbol')

    expected_q = (
        last_crowd['Rank1'] * 1 +
        last_crowd['Rank2'] * 2 +
        last_crowd['Rank3'] * 3 +
        last_crowd['Rank4'] * 4 +
        last_crowd['Rank5'] * 5
    ).reindex(symbols)

    cross_vol = np.sqrt(np.diag(cov_matrix)).mean()
    expected_returns = (expected_q.values - 3) * cross_vol * 0.3

    # Optimize
    opt_w = optimize_portfolio(expected_returns, cov_matrix)
    optimal_weights = {sym: round(float(w), 6) for sym, w in zip(symbols, opt_w)}

    # 6. Connection scores
    connection_scores = compute_connection_scores(submissions_df)

    # Write output
    os.makedirs('/app/output', exist_ok=True)
    output = {
        'team_rps': {k: round(v, 6) for k, v in team_rps.items()},
        'team_ir': {k: round(v, 6) for k, v in team_ir.items()},
        'or_ranking': or_ranking,
        'crowd_rps': round(crowd_rps, 6),
        'optimal_weights': optimal_weights,
        'connection_scores': {k: round(v, 6) for k, v in connection_scores.items()},
    }

    with open('/app/output/evaluation.json', 'w') as f:
        json.dump(output, f, indent=2)

    print("Evaluation complete. Output written to /app/output/evaluation.json")


if __name__ == '__main__':
    main()
