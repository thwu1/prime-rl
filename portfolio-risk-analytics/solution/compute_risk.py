#!/usr/bin/env python3
"""Compute portfolio risk analytics from the warehouse database."""

import os
import duckdb
import numpy as np
import pandas as pd
from scipy.stats import norm, skew, kurtosis


def main():
    con = duckdb.connect('/app/warehouse.duckdb', read_only=True)

    # Load all required data
    securities = con.execute(
        "SELECT security_id, currency FROM securities"
    ).fetchall()
    sec_currency = {r[0]: r[1] for r in securities}

    prices_raw = con.execute(
        "SELECT security_id, trade_date, close_price FROM daily_prices "
        "ORDER BY security_id, trade_date"
    ).fetchall()

    portfolios = con.execute(
        "SELECT portfolio_id, benchmark_id FROM portfolios ORDER BY portfolio_id"
    ).fetchall()

    holdings_raw = con.execute(
        "SELECT portfolio_id, security_id, quantity FROM holdings"
    ).fetchall()

    fx_raw = con.execute(
        "SELECT currency, rate_date, rate_to_usd FROM fx_rates "
        "ORDER BY currency, rate_date"
    ).fetchall()

    bm_raw = con.execute(
        "SELECT benchmark_id, trade_date, daily_return FROM benchmark_returns "
        "ORDER BY benchmark_id, trade_date"
    ).fetchall()

    rf_raw = con.execute(
        "SELECT trade_date, daily_rate FROM risk_free_rates ORDER BY trade_date"
    ).fetchall()

    actions_raw = con.execute(
        "SELECT security_id, action_date, action_type, factor "
        "FROM corporate_actions"
    ).fetchall()

    div_raw = con.execute(
        "SELECT security_id, ex_date, amount FROM dividends "
        "ORDER BY security_id, ex_date"
    ).fetchall()

    con.close()

    # Build lookup structures
    prices = {}
    dates_set = set()
    for sec_id, td, cp in prices_raw:
        prices[(sec_id, td)] = cp
        dates_set.add(td)
    trading_dates = sorted(dates_set)
    n_days = len(trading_dates)

    # FX rates with forward-fill for missing dates
    fx_dict = {}
    for cur, rd, rate in fx_raw:
        fx_dict[(cur, rd)] = rate

    fx = {}
    for cur in ['EUR', 'GBP']:
        last = None
        for d in trading_dates:
            k = (cur, d)
            if k in fx_dict:
                last = fx_dict[k]
            if last is not None:
                fx[k] = last
    for d in trading_dates:
        fx[('USD', d)] = 1.0

    # Corporate actions (splits only)
    splits = {}
    for sid, ad, at, fac in actions_raw:
        if at == 'SPLIT':
            splits.setdefault(sid, []).append((ad, fac))

    # Dividends: {sec_id: {date: amount}}
    div_lookup = {}
    for sid, ed, amt in div_raw:
        div_lookup.setdefault(sid, {})[ed] = amt

    # Holdings by portfolio
    holdings = {}
    for pid, sid, qty in holdings_raw:
        holdings.setdefault(pid, []).append((sid, qty))

    # Benchmark returns
    bm_ret = {}
    for bmid, td, ret in bm_raw:
        bm_ret[(bmid, td)] = ret

    # Risk-free
    rf = {td: rate for td, rate in rf_raw}

    results = []

    for pf_id, bm_id in portfolios:
        pf_h = holdings.get(pf_id, [])

        # Compute daily portfolio value and dividend income
        daily_values = np.zeros(n_days)
        daily_div_income = np.zeros(n_days)

        for d_idx, d in enumerate(trading_dates):
            total_val = 0.0
            div_inc = 0.0
            for sec_id, qty in pf_h:
                q = qty
                cur = sec_currency[sec_id]

                # Reverse corporate actions for pre-action dates
                if sec_id in splits:
                    for split_date, factor in splits[sec_id]:
                        if d < split_date:
                            q = q / factor

                price = prices.get((sec_id, d))
                if price is None:
                    continue

                fx_rate = fx.get((cur, d), 1.0)
                total_val += q * price * fx_rate

                # Add dividend income on ex-date
                if sec_id in div_lookup and d in div_lookup[sec_id]:
                    div_inc += q * div_lookup[sec_id][d] * fx_rate

            daily_values[d_idx] = total_val
            daily_div_income[d_idx] = div_inc

        # Daily total returns (price change + dividends)
        daily_returns = (daily_values[1:] + daily_div_income[1:]) / daily_values[:-1] - 1

        # Align benchmark and risk-free returns
        bm_aligned = np.array([
            bm_ret[(bm_id, trading_dates[i + 1])]
            for i in range(len(daily_returns))
        ])
        rf_aligned = np.array([
            rf[trading_dates[i + 1]]
            for i in range(len(daily_returns))
        ])

        # 1. Total return (compounded)
        total_return = np.prod(1 + daily_returns) - 1

        # 2. EWMA volatility (half-life=60, RiskMetrics zero-mean)
        halflife = 60
        lam = 2.0 ** (-1.0 / halflife)
        ewma_var = daily_returns[0] ** 2
        for t in range(1, len(daily_returns)):
            ewma_var = lam * ewma_var + (1 - lam) * daily_returns[t] ** 2
        ewma_vol = np.sqrt(ewma_var) * np.sqrt(252)

        # 3. Cornish-Fisher VaR at 99%
        z_alpha = norm.ppf(0.01)
        mu = np.mean(daily_returns)
        sigma = np.std(daily_returns, ddof=1)
        S = skew(daily_returns, bias=False)
        K = kurtosis(daily_returns, fisher=True, bias=False)

        z_cf = (z_alpha
                + (z_alpha ** 2 - 1) * S / 6
                + (z_alpha ** 3 - 3 * z_alpha) * K / 24
                - (2 * z_alpha ** 3 - 5 * z_alpha) * S ** 2 / 36)
        cf_var_99 = mu + z_cf * sigma

        # 4. Expected Shortfall at 95%
        threshold = np.percentile(daily_returns, 5)
        es_95 = np.mean(daily_returns[daily_returns <= threshold])

        # 5. Max drawdown
        cum_wealth = np.cumprod(1 + daily_returns)
        running_max = np.maximum.accumulate(cum_wealth)
        max_dd = np.min(cum_wealth / running_max - 1)

        # 6. Sortino ratio (target=0%)
        downside = np.minimum(daily_returns, 0)
        dd_daily = np.sqrt(np.mean(downside ** 2))
        sortino = mu / dd_daily * np.sqrt(252)

        # 7. Beta (CAPM, excess returns)
        excess_port = daily_returns - rf_aligned
        excess_bm = bm_aligned - rf_aligned
        cov_mat = np.cov(excess_port, excess_bm)
        beta = cov_mat[0, 1] / cov_mat[1, 1]

        # 8. Tracking error
        active = daily_returns - bm_aligned
        te = np.std(active, ddof=1) * np.sqrt(252)

        results.append({
            'portfolio_id': int(pf_id),
            'total_return': round(total_return, 6),
            'ewma_volatility': round(ewma_vol, 6),
            'cf_var_99': round(cf_var_99, 6),
            'expected_shortfall_95': round(es_95, 6),
            'max_drawdown': round(max_dd, 6),
            'sortino_ratio': round(sortino, 6),
            'beta': round(beta, 6),
            'tracking_error': round(te, 6),
        })

    # Write output
    os.makedirs('/app/output', exist_ok=True)
    result_df = pd.DataFrame(results).sort_values('portfolio_id')
    result_df.to_csv('/app/output/risk_report.csv', index=False)
    print("Risk report written to /app/output/risk_report.csv")
    print(result_df.to_string(index=False))


if __name__ == '__main__':
    main()
