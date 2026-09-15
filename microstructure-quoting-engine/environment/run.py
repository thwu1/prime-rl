#!/usr/bin/env python3
"""Orchestrate the market-making simulation pipeline."""

import csv
import json
import os
import math
import sys

sys.path.insert(0, '/app')

from engine.garch import GarchParams, GarchState, GarchEstimator
from engine.microstructure import OrderFlowImbalance, microprice, Vpin, KyleLambda
from engine.regime import RegimeDetector
from engine.toxicity import ToxicityDetector
from engine.quoting import QuotingEngine


def main():
    os.makedirs('/app/output', exist_ok=True)

    events = []
    with open('/app/data/events.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            events.append({
                'timestamp': int(row['timestamp']),
                'bid_price': float(row['bid_price']),
                'bid_size': float(row['bid_size']),
                'ask_price': float(row['ask_price']),
                'ask_size': float(row['ask_size']),
                'trade_price': float(row['trade_price']),
                'trade_volume': float(row['trade_volume']),
                'trade_side': int(row['trade_side']),
                'log_return': float(row['log_return']),
            })

    returns = [e['log_return'] for e in events]
    fit_result = GarchEstimator.fit(returns)
    if fit_result:
        garch_params, ll = fit_result
    else:
        garch_params = GarchParams(0.000002, 0.08, 0.90)
        ll = 0.0

    lr_var = garch_params.long_run_variance() if garch_params.is_stationary() else None
    with open('/app/output/garch_params.json', 'w') as f:
        json.dump({
            'omega': garch_params.omega,
            'alpha': garch_params.alpha,
            'beta': garch_params.beta,
            'persistence': garch_params.persistence(),
            'long_run_variance': lr_var,
            'log_likelihood': ll,
        }, f, indent=2)

    init_var = lr_var if lr_var and math.isfinite(lr_var) else 0.0001
    garch_state = GarchState(garch_params, init_var)
    ofi = OrderFlowImbalance(window_size=20)
    vpin = Vpin(bucket_volume=5000.0, num_buckets=20)
    kyle = KyleLambda(window_size=50)
    regime_det = RegimeDetector()
    tox_det = ToxicityDetector(adverse_move_threshold=2.0)
    quoting = QuotingEngine()

    quotes = []
    regime_counts = {}
    total_quotes = 0
    active_quotes = 0
    halted_quotes = 0
    n_events = len(events)
    prev_trade_price = events[0]['trade_price'] if events else 100.0

    for evt in events:
        garch_state.update(evt['log_return'])
        sigma = math.sqrt(garch_state.conditional_variance)

        ofi_val = ofi.update(evt['bid_price'], evt['bid_size'],
                             evt['ask_price'], evt['ask_size'])
        fv = microprice(evt['bid_price'], evt['ask_price'],
                        evt['bid_size'], evt['ask_size'])
        vpin_val = vpin.update(evt['trade_price'], prev_trade_price,
                               evt['trade_volume'])
        mid = (evt['bid_price'] + evt['ask_price']) / 2.0
        signed_flow = evt['trade_side'] * evt['trade_volume']
        kyle.update(mid, signed_flow)

        vol_obs = abs(evt['log_return'])
        regime = regime_det.update(vol_obs)
        regime_params = regime_det.params()
        regime_counts[regime] = regime_counts.get(regime, 0) + 1

        if total_quotes > 0 and total_quotes % 5 == 0:
            tox_det.record_fill(evt['trade_price'],
                                evt['trade_side'] > 0,
                                evt['timestamp'])
        tox_det.evaluate(fv, evt['timestamp'])
        tox_val = tox_det.toxicity()

        tau = max(0.001, 1.0 - evt['timestamp'] / max(n_events, 1))
        q = quoting.compute(
            fair_value=fv,
            inventory=0.0,
            sigma=sigma,
            tau=tau,
            ofi=ofi_val,
            vpin=vpin_val,
            regime_gamma=regime_params['gamma'],
            regime_spread_mult=regime_params['spread_mult'],
            regime_size_mult=regime_params['size_mult'],
            toxicity=tox_val,
            base_size=10.0,
        )

        total_quotes += 1
        if q['active']:
            active_quotes += 1
        else:
            halted_quotes += 1

        quotes.append({
            'timestamp': evt['timestamp'],
            'bid': round(q['bid'], 4),
            'ask': round(q['ask'], 4),
            'bid_size': round(q['bid_size'], 2),
            'ask_size': round(q['ask_size'], 2),
            'active': str(q['active']).lower(),
            'regime': regime,
            'vpin': round(vpin_val, 4),
            'toxicity': round(tox_val, 4),
        })

        prev_trade_price = evt['trade_price']

    with open('/app/output/quotes.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=quotes[0].keys())
        writer.writeheader()
        writer.writerows(quotes)

    with open('/app/output/simulation_results.json', 'w') as f:
        json.dump({
            'total_quotes': total_quotes,
            'active_quotes': active_quotes,
            'halted_quotes': halted_quotes,
            'regime_counts': regime_counts,
            'final_vpin': vpin.value(),
            'final_toxicity': tox_det.toxicity(),
        }, f, indent=2)

    print(f"Simulation complete: {total_quotes} quotes "
          f"({active_quotes} active, {halted_quotes} halted)")


if __name__ == '__main__':
    main()
