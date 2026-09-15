"""Automated market-making quoting engine with risk-adaptive spread management."""

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

        if toxicity > 0.65:
            return self._halt(fair_value, 'adverse_selection_halt')

        if vpin > 0.85:
            return self._halt(fair_value, 'vpin_extreme')

        gamma = max(regime_gamma, 0.01)
        sigma_sq = max(sigma ** 2, 1e-12)
        tau_safe = max(tau, 0.001)

        q = inventory / max(self.position_limit, 1.0)

        reservation = fair_value + q * gamma * sigma_sq * tau_safe

        spread_time = (gamma * sigma_sq * tau_safe) / 2.0
        spread_arrival = (1.0 / gamma) * math.log(1.0 + gamma / max(self.kappa, 0.1))
        raw_half = max(spread_time + spread_arrival, self.min_half_spread)

        spread_mult = regime_spread_mult

        if vpin > 0.5:
            spread_mult *= 1.0 + (vpin - 0.5) * 2.0

        if toxicity > 0.35:
            spread_mult *= 2.0 + (toxicity - 0.35) * 5.0

        adjusted_half = raw_half * spread_mult

        ofi_adj = self.lambda_ofi * ofi

        bid = reservation - adjusted_half + ofi_adj
        ask = reservation + adjusted_half + ofi_adj

        tox_discount = max(0.0, 1.0 - toxicity * 2.0)
        bid_size = max(0.0, base_size * regime_size_mult * tox_discount)
        ask_size = max(0.0, base_size * regime_size_mult * tox_discount)

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
