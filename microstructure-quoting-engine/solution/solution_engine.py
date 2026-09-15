#!/usr/bin/env python3
"""
Complete solution: creates all engine modules and runs the simulation.
"""

import os


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


# ──────────────────────────────────────────────────────────────
# engine/__init__.py
# ──────────────────────────────────────────────────────────────
write_file('/app/engine/__init__.py', '')

# ──────────────────────────────────────────────────────────────
# engine/garch.py
# ──────────────────────────────────────────────────────────────
write_file('/app/engine/garch.py', r'''
import math


class GarchParams:
    def __init__(self, omega, alpha, beta):
        self.omega = omega
        self.alpha = alpha
        self.beta = beta

    def is_stationary(self):
        return self.alpha + self.beta < 1.0

    def long_run_variance(self):
        denom = 1.0 - self.alpha - self.beta
        if denom <= 0:
            return float('inf')
        return self.omega / denom

    def persistence(self):
        return self.alpha + self.beta

    def shock_half_life(self):
        p = self.persistence()
        if p <= 0 or p >= 1:
            return float('nan')
        return -math.log(2) / math.log(p)


class GarchState:
    def __init__(self, params, initial_variance):
        self.params = params
        self.conditional_variance = initial_variance
        self.last_return = 0.0

    def update(self, return_t):
        if not math.isfinite(return_t):
            return
        p = self.params
        new_var = p.omega + p.alpha * return_t ** 2 + p.beta * self.conditional_variance
        self.conditional_variance = max(new_var, 1e-10)
        self.last_return = return_t

    def forecast(self, h):
        lr = self.params.long_run_variance()
        if not math.isfinite(lr):
            return self.conditional_variance
        p_h = self.params.persistence() ** h
        return lr + p_h * (self.conditional_variance - lr)

    def current_vol_annualized(self):
        return math.sqrt(self.conditional_variance * 252)

    def var_1day(self, z_score, position_value):
        return z_score * math.sqrt(self.conditional_variance) * position_value


class GarchEstimator:
    @staticmethod
    def log_likelihood(returns, params):
        n = len(returns)
        if n == 0:
            return float('-inf')
        sample_var = sum(r * r for r in returns) / n
        sigma2 = sample_var
        ll = 0.0
        for r in returns:
            sigma2 = params.omega + params.alpha * r * r + params.beta * sigma2
            sigma2 = max(sigma2, 1e-12)
            ll += -0.5 * (math.log(sigma2) + r * r / sigma2)
        return ll / n

    @staticmethod
    def fit(returns):
        clean = [r for r in returns if math.isfinite(r)]
        if len(clean) < 50:
            return None

        n = len(clean)
        sample_var = sum(r * r for r in clean) / n

        best_ll = float('-inf')
        best_params = None

        alpha_grid = [0.03, 0.05, 0.08, 0.10, 0.12, 0.15]
        beta_grid = [0.80, 0.85, 0.87, 0.90, 0.92, 0.94]

        for alpha in alpha_grid:
            for beta in beta_grid:
                if alpha + beta >= 0.999:
                    continue
                omega = sample_var * (1 - alpha - beta)
                if omega <= 0:
                    continue
                p = GarchParams(omega, alpha, beta)
                ll = GarchEstimator.log_likelihood(clean, p)
                if ll > best_ll:
                    best_ll = ll
                    best_params = p

        if best_params is None:
            return None

        # Gradient ascent refinement
        cur_omega = best_params.omega
        cur_alpha = best_params.alpha
        cur_beta = best_params.beta
        eps = 1e-6
        lr = 1e-5

        for _ in range(200):
            p = GarchParams(cur_omega, cur_alpha, cur_beta)
            ll = GarchEstimator.log_likelihood(clean, p)

            pa = GarchParams(cur_omega, cur_alpha + eps, cur_beta)
            pb = GarchParams(cur_omega, cur_alpha, cur_beta + eps)
            po = GarchParams(cur_omega + eps, cur_alpha, cur_beta)

            grad_a = (GarchEstimator.log_likelihood(clean, pa) - ll) / eps
            grad_b = (GarchEstimator.log_likelihood(clean, pb) - ll) / eps
            grad_o = (GarchEstimator.log_likelihood(clean, po) - ll) / eps

            cur_alpha = max(1e-6, min(0.5, cur_alpha + lr * grad_a))
            cur_beta = max(1e-6, cur_beta + lr * grad_b)
            cur_omega = max(1e-12, cur_omega + lr * grad_o)

            if cur_alpha + cur_beta >= 0.999:
                s = 0.998 / (cur_alpha + cur_beta)
                cur_alpha *= s
                cur_beta *= s

        final = GarchParams(cur_omega, cur_alpha, cur_beta)
        final_ll = GarchEstimator.log_likelihood(clean, final)
        return (final, final_ll)
''')

# ──────────────────────────────────────────────────────────────
# engine/microstructure.py
# ──────────────────────────────────────────────────────────────
write_file('/app/engine/microstructure.py', r'''
from collections import deque


def microprice(bid, ask, bid_size, ask_size):
    total = bid_size + ask_size
    if total < 1e-10:
        return (bid + ask) / 2.0
    return ask * (bid_size / total) + bid * (ask_size / total)


class OrderFlowImbalance:
    def __init__(self, window_size=10):
        self.prev_bid_price = 0.0
        self.prev_bid_size = 0.0
        self.prev_ask_price = 0.0
        self.prev_ask_size = 0.0
        self.window = deque(maxlen=window_size)
        self.initialized = False

    def update(self, bid_price, bid_size, ask_price, ask_size):
        if not self.initialized:
            self.prev_bid_price = bid_price
            self.prev_bid_size = bid_size
            self.prev_ask_price = ask_price
            self.prev_ask_size = ask_size
            self.initialized = True
            return 0.0

        # Bid-side flow (Cont et al. 2014)
        if bid_price > self.prev_bid_price:
            delta_bid = bid_size
        elif bid_price == self.prev_bid_price:
            delta_bid = bid_size - self.prev_bid_size
        else:
            delta_bid = -self.prev_bid_size

        # Ask-side flow
        if ask_price < self.prev_ask_price:
            delta_ask = ask_size
        elif ask_price == self.prev_ask_price:
            delta_ask = ask_size - self.prev_ask_size
        else:
            delta_ask = -self.prev_ask_size

        ofi_tick = delta_bid - delta_ask
        self.window.append(ofi_tick)

        self.prev_bid_price = bid_price
        self.prev_bid_size = bid_size
        self.prev_ask_price = ask_price
        self.prev_ask_size = ask_size

        # Normalized OFI
        total = sum(self.window)
        abs_total = sum(abs(x) for x in self.window)
        if abs_total > 0:
            return total / abs_total
        return 0.0

    def raw_ofi(self):
        return sum(self.window)


class Vpin:
    def __init__(self, bucket_volume=1000.0, num_buckets=10):
        self.bucket_volume = bucket_volume
        self.num_buckets = num_buckets
        self.buy_volume = 0.0
        self.sell_volume = 0.0
        self.current_bucket_volume = 0.0
        self.buckets = deque(maxlen=num_buckets)

    def update(self, trade_price, prev_price, volume):
        is_buy = trade_price >= prev_price
        if is_buy:
            self.buy_volume += volume
        else:
            self.sell_volume += volume
        self.current_bucket_volume += volume

        if self.current_bucket_volume >= self.bucket_volume:
            self.buckets.append((self.buy_volume, self.sell_volume))
            self.buy_volume = 0.0
            self.sell_volume = 0.0
            self.current_bucket_volume = 0.0

        return self.value()

    def value(self):
        if not self.buckets:
            return 0.0
        total_imbalance = sum(abs(b - s) for b, s in self.buckets)
        total_volume = sum(b + s for b, s in self.buckets)
        if total_volume < 1e-10:
            return 0.0
        return min(1.0, max(0.0, total_imbalance / total_volume))


class KyleLambda:
    def __init__(self, window_size=50):
        self.price_changes = deque(maxlen=window_size)
        self.signed_flows = deque(maxlen=window_size)
        self.prev_mid = 0.0
        self.initialized = False

    def update(self, mid_price, signed_trade_size):
        if not self.initialized:
            self.prev_mid = mid_price
            self.initialized = True
            return 0.0

        delta_p = mid_price - self.prev_mid
        self.prev_mid = mid_price

        self.price_changes.append(delta_p)
        self.signed_flows.append(signed_trade_size)

        return self._compute()

    def _compute(self):
        n = len(self.price_changes)
        if n < 10:
            return 0.0

        mean_dp = sum(self.price_changes) / n
        mean_sf = sum(self.signed_flows) / n

        cov = sum(
            (self.price_changes[i] - mean_dp) * (self.signed_flows[i] - mean_sf)
            for i in range(n)
        )
        var_sf = sum((self.signed_flows[i] - mean_sf) ** 2 for i in range(n))

        if var_sf < 1e-15:
            return 0.0
        return max(0.0, cov / var_sf)

    def lambda_value(self):
        return self._compute()
''')

# ──────────────────────────────────────────────────────────────
# engine/regime.py
# ──────────────────────────────────────────────────────────────
write_file('/app/engine/regime.py', r'''
CRISIS_THRESH = 2.5
HIGH_VOL_THRESH = 1.4
LOW_VOL_THRESH = 0.7

REGIME_PARAMS = {
    'LowVol': {'gamma': 0.05, 'spread_mult': 0.6, 'size_mult': 1.2, 'urgency_mult': 0.8},
    'Normal': {'gamma': 0.10, 'spread_mult': 1.0, 'size_mult': 1.0, 'urgency_mult': 1.0},
    'HighVol': {'gamma': 0.20, 'spread_mult': 2.0, 'size_mult': 0.6, 'urgency_mult': 1.3},
    'Crisis': {'gamma': 0.40, 'spread_mult': 4.0, 'size_mult': 0.2, 'urgency_mult': 0.3},
}


class RegimeDetector:
    def __init__(self, fast_alpha=0.15, slow_alpha=0.03, min_regime_ticks=5):
        self.fast_alpha = fast_alpha
        self.slow_alpha = slow_alpha
        self.min_regime_ticks = min_regime_ticks
        self.vol_fast_ema = 1.0
        self.vol_slow_ema = 1.0
        self._regime = 'Normal'
        self.ticks_in_regime = 0
        self._vol_ratio = 1.0

    def update(self, vol_observation):
        self.vol_fast_ema = (self.fast_alpha * vol_observation
                             + (1 - self.fast_alpha) * self.vol_fast_ema)
        self.vol_slow_ema = (self.slow_alpha * vol_observation
                             + (1 - self.slow_alpha) * self.vol_slow_ema)

        self._vol_ratio = self.vol_fast_ema / max(self.vol_slow_ema, 1e-10)

        if self._vol_ratio > CRISIS_THRESH:
            proposed = 'Crisis'
        elif self._vol_ratio > HIGH_VOL_THRESH:
            proposed = 'HighVol'
        elif self._vol_ratio < LOW_VOL_THRESH:
            proposed = 'LowVol'
        else:
            proposed = 'Normal'

        self.ticks_in_regime += 1
        if proposed != self._regime and self.ticks_in_regime >= self.min_regime_ticks:
            self._regime = proposed
            self.ticks_in_regime = 0

        return self._regime

    def regime(self):
        return self._regime

    def vol_ratio(self):
        return self._vol_ratio

    def params(self):
        return dict(REGIME_PARAMS.get(self._regime, REGIME_PARAMS['Normal']))

    def get_regime_params_map(self):
        return dict(REGIME_PARAMS)
''')

# ──────────────────────────────────────────────────────────────
# engine/toxicity.py
# ──────────────────────────────────────────────────────────────
write_file('/app/engine/toxicity.py', r'''
from collections import deque


class ToxicityDetector:
    def __init__(self, alpha=0.15, warn_threshold=0.35, halt_threshold=0.65,
                 adverse_move_threshold=0.5, max_history=200):
        self.alpha = alpha
        self.warn_threshold = warn_threshold
        self.halt_threshold = halt_threshold
        self.adverse_move_threshold = adverse_move_threshold
        self.fills = deque(maxlen=max_history)
        self._toxicity = 0.0
        self.consecutive_toxic = 0
        self.total_evaluated = 0
        self.total_toxic = 0

    def record_fill(self, price, is_bid, timestamp):
        self.fills.append({
            'price': price,
            'is_bid': is_bid,
            'timestamp': timestamp,
            'evaluated': False,
        })

    def evaluate(self, fair_value, timestamp):
        for fill in self.fills:
            if fill['evaluated']:
                continue

            if fill['is_bid']:
                post_move = fair_value - fill['price']
            else:
                post_move = fill['price'] - fair_value

            fill['evaluated'] = True
            is_toxic = post_move < -self.adverse_move_threshold

            self.total_evaluated += 1
            if is_toxic:
                self.total_toxic += 1
                self.consecutive_toxic += 1
            else:
                self.consecutive_toxic = 0

            toxic_signal = 1.0 if is_toxic else 0.0
            self._toxicity = (self.alpha * toxic_signal
                              + (1 - self.alpha) * self._toxicity)

        return self._recommend()

    def _recommend(self):
        if self._toxicity > self.halt_threshold or self.consecutive_toxic >= 5:
            return 'HaltPassive'
        elif self._toxicity > self.warn_threshold:
            return 'Widen'
        return 'Normal'

    def toxicity(self):
        return self._toxicity

    def is_safe(self):
        return self._toxicity < self.warn_threshold
''')

# ──────────────────────────────────────────────────────────────
# engine/quoting.py
# ──────────────────────────────────────────────────────────────
write_file('/app/engine/quoting.py', r'''
import math


class QuotingEngine:
    def __init__(self, base_gamma=0.10, kappa=1.5, lambda_ofi=0.5,
                 min_half_spread=1.0, position_limit=100.0, session_ticks=1000000):
        self.base_gamma = base_gamma
        self.kappa = kappa
        self.lambda_ofi = lambda_ofi
        self.min_half_spread = min_half_spread
        self.position_limit = position_limit
        self.session_ticks = session_ticks

    def compute(self, fair_value, inventory, sigma, tau, ofi, vpin,
                regime_gamma, regime_spread_mult, regime_size_mult,
                toxicity, base_size):

        # Halt on extreme toxicity (Barzykin 2025)
        if toxicity > 0.65:
            return self._halt(fair_value, 'adverse_selection_halt')

        # Halt on extreme VPIN (Easley et al. 2012)
        if vpin > 0.85:
            return self._halt(fair_value, 'vpin_extreme')

        gamma = max(regime_gamma, 0.01)
        sigma_sq = max(sigma ** 2, 1e-12)
        tau_safe = max(tau, 0.001)

        q = inventory / max(self.position_limit, 1.0)

        # Reservation price (Avellaneda-Stoikov 2008)
        reservation = fair_value - q * gamma * sigma_sq * tau_safe

        # Optimal half-spread
        spread_time = (gamma * sigma_sq * tau_safe) / 2.0
        spread_arrival = (1.0 / gamma) * math.log(1.0 + gamma / max(self.kappa, 0.1))
        raw_half = max(spread_time + spread_arrival, self.min_half_spread)

        # Regime spread multiplier
        spread_mult = regime_spread_mult

        # VPIN toxicity widening (Easley et al. 2012)
        if vpin > 0.5:
            spread_mult *= 1.0 + (vpin - 0.5) * 2.0

        # Toxicity widening (Barzykin 2025)
        if toxicity > 0.35:
            spread_mult *= 2.0 + (toxicity - 0.35) * 5.0

        adjusted_half = raw_half * spread_mult

        # OFI skew (Cont et al. 2014)
        ofi_adj = self.lambda_ofi * ofi

        bid = reservation - adjusted_half + ofi_adj
        ask = reservation + adjusted_half + ofi_adj

        # Position sizing with toxicity discount
        tox_discount = max(0.0, 1.0 - toxicity * 2.0)
        bid_size = max(0.0, base_size * regime_size_mult * tox_discount)
        ask_size = max(0.0, base_size * regime_size_mult * tox_discount)

        # Inventory skew on sizes
        if inventory > 0:
            inv_ratio = min(inventory / self.position_limit, 1.0)
            bid_size *= (1 - inv_ratio * 0.5)
            ask_size *= (1 + inv_ratio * 0.3)
        elif inventory < 0:
            inv_ratio = min(-inventory / self.position_limit, 1.0)
            bid_size *= (1 + inv_ratio * 0.3)
            ask_size *= (1 - inv_ratio * 0.5)

        return {
            'fair_value': fair_value,
            'reservation_price': reservation,
            'bid': bid,
            'ask': ask,
            'raw_half_spread': raw_half,
            'adjusted_half_spread': adjusted_half,
            'bid_size': bid_size,
            'ask_size': ask_size,
            'active': True,
            'halt_reason': '',
        }

    def _halt(self, fair_value, reason):
        return {
            'fair_value': fair_value,
            'reservation_price': fair_value,
            'bid': fair_value - 1000.0,
            'ask': fair_value + 1000.0,
            'raw_half_spread': 0.0,
            'adjusted_half_spread': 0.0,
            'bid_size': 0.0,
            'ask_size': 0.0,
            'active': False,
            'halt_reason': reason,
        }
''')

# ──────────────────────────────────────────────────────────────
# run.py — main simulation
# ──────────────────────────────────────────────────────────────
write_file('/app/run.py', r'''
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

    # Load data
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

    # Fit GARCH on log returns
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

    # Initialize components
    init_var = lr_var if lr_var and math.isfinite(lr_var) else 0.0001
    garch_state = GarchState(garch_params, init_var)
    ofi = OrderFlowImbalance(window_size=20)
    vpin = Vpin(bucket_volume=5000.0, num_buckets=20)
    kyle = KyleLambda(window_size=50)
    regime_det = RegimeDetector()
    tox_det = ToxicityDetector(adverse_move_threshold=2.0)
    quoting = QuotingEngine()

    # Run simulation
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

        # Simulate occasional fills for toxicity tracking
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

    # Write quotes CSV
    with open('/app/output/quotes.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=quotes[0].keys())
        writer.writeheader()
        writer.writerows(quotes)

    # Write summary results
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
''')


# ──────────────────────────────────────────────────────────────
# Execute the simulation
# ──────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import subprocess
    result = subprocess.run(['python3', '/app/run.py'], capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    exit(result.returncode)
