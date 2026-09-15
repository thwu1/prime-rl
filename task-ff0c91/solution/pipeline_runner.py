#!/usr/bin/env python3
"""Pipeline runner: processes market data and populates SQLite database."""

import csv
import json
import math
import sqlite3
import sys

sys.path.insert(0, '/app')

from pipeline.garch import GarchEstimator, GarchState
from pipeline.microstructure import microprice, OrderFlowImbalance, Vpin
from pipeline.regime import RegimeDetector
from pipeline.quoting import QuotingConfig, QuotingEngine
from pipeline.risk import Position, VarCalculator


def run():
    with open('/app/config.json') as f:
        config = json.load(f)

    db_path = config['output']['database']
    conn = sqlite3.connect(db_path)

    with open('/app/schema.sql') as f:
        conn.executescript(f.read())

    # Load data
    returns = []
    with open(config['data']['returns_path']) as f:
        for row in csv.DictReader(f):
            returns.append(float(row['log_return']))

    ticks = []
    with open(config['data']['orderbook_path']) as f:
        for row in csv.DictReader(f):
            ticks.append(row)

    # --- Volatility Forecasting ---
    fit_result = GarchEstimator.fit(returns)
    if fit_result is None:
        raise RuntimeError("Volatility model fitting failed")
    params, _ = fit_result

    state = GarchState(params, params.long_run_variance())
    for i, r in enumerate(returns):
        state.update(r)
        conn.execute(
            "INSERT OR REPLACE INTO volatility_forecast VALUES (?, ?, ?)",
            (i, state.conditional_variance, state.current_vol_annualized())
        )

    # --- Regime Detection, Microstructure Signals, Quoting ---
    det = RegimeDetector()
    ofi = OrderFlowImbalance(window_size=20)
    vpin_calc = Vpin(bucket_volume=1000.0, num_buckets=10)
    engine = QuotingEngine(QuotingConfig())

    sigma_daily = math.sqrt(state.conditional_variance)
    prev_trade = None

    for tick in ticks:
        i = int(tick['tick'])
        bp = float(tick['bid_price'])
        bs = float(tick['bid_size'])
        ap = float(tick['ask_price'])
        as_ = float(tick['ask_size'])
        tp = float(tick['trade_price'])
        tv = float(tick['trade_volume'])

        mid = (bp + ap) / 2.0
        vol_obs = abs(tp - mid) if prev_trade is not None else 1.0
        det.update(vol_obs)

        conn.execute(
            "INSERT OR REPLACE INTO regime_state VALUES (?, ?, ?)",
            (i, det.regime.value, det.vol_ratio)
        )

        ofi_val = ofi.update(bp, bs, ap, as_)
        vpin_val = vpin_calc.update(tp, prev_trade, tv) if prev_trade is not None else 0.0

        mp = microprice(bp, ap, bs, as_)
        rp = det.regime.params()
        q = engine.compute(
            fair_value=mp, inventory=0.0, sigma=sigma_daily,
            tau=config['quoting']['tau'], ofi=ofi_val, vpin=vpin_val,
            regime_gamma=rp.gamma, regime_spread_mult=rp.spread_mult,
            regime_size_mult=rp.size_mult, toxicity=0.0,
            base_size=config['quoting']['base_size'],
        )

        conn.execute(
            "INSERT OR REPLACE INTO quoting_decision VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (i, q.bid, q.ask, q.reservation_price, q.bid_size, q.ask_size,
             1 if q.active else 0, q.halt_reason)
        )

        prev_trade = tp

    # --- Risk Metrics ---
    rc = config['risk']
    calc = VarCalculator(min_history_days=rc['min_history_days'])
    for r in returns:
        calc.update_returns(rc['position_symbol'], r * 100.0)

    positions = [Position(rc['position_symbol'], rc['position_quantity'],
                          rc['position_price'])]

    for method_name, method_fn in [('historical', calc.historical_var),
                                    ('parametric', calc.parametric_var)]:
        result = method_fn(positions)
        if result:
            conn.execute(
                "INSERT OR REPLACE INTO risk_metrics VALUES (?, ?, ?, ?, ?, ?)",
                (method_name, result.var_95_1d_usd, result.var_99_1d_usd,
                 result.var_99_10d_usd, result.cvar_95_usd,
                 result.portfolio_notional)
            )

    conn.commit()
    conn.close()
    print(f"Pipeline complete. Database: {db_path}")


if __name__ == '__main__':
    run()
