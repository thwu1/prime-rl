
"""Avellaneda-Stoikov 2008 optimal market-making quoting engine.

Core formulas:
  Reservation price: r = fv - (q/pos_limit) * gamma * sigma^2 * tau
  Optimal half-spread: delta = (gamma * sigma^2 * tau)/2 + (1/gamma) * ln(1 + gamma/kappa)
  Final bid: r - delta * spread_mult * tox_mult + lambda_ofi * OFI
  Final ask: r + delta * spread_mult * tox_mult + lambda_ofi * OFI

Integrates regime-conditioned spread widening, VPIN toxicity widening,
adverse-selection gating, and OFI-based quote skewing.
"""

import math
from dataclasses import dataclass


@dataclass
class QuotingConfig:
    """Configuration for the quoting engine."""
    base_gamma: float = 0.10
    kappa: float = 1.5
    lambda_ofi: float = 0.5
    min_half_spread: float = 1.0
    position_limit: float = 100.0
    session_ticks: int = 1_000_000


@dataclass
class QuotingDecision:
    """Output of the quoting engine."""
    fair_value: float
    reservation_price: float
    bid: float
    ask: float
    raw_half_spread: float
    adjusted_half_spread: float
    bid_size: float
    ask_size: float
    active: bool
    halt_reason: str


class QuotingEngine:
    """2026 Enhanced Avellaneda-Stoikov quoting engine."""

    def __init__(self, config: QuotingConfig):
        self._config = config

    def compute(self, fair_value: float, inventory: float, sigma: float,
                tau: float, ofi: float, vpin: float,
                regime_gamma: float, regime_spread_mult: float,
                regime_size_mult: float, toxicity: float,
                base_size: float) -> QuotingDecision:

        c = self._config

        # Safety halts
        if toxicity > 0.65:
            return self._halt(fair_value, "adverse_selection_halt")
        if vpin > 0.85:
            return self._halt(fair_value, "vpin_extreme")

        gamma = max(regime_gamma, 0.01)
        sigma_sq = max(sigma ** 2, 1e-12)
        tau_safe = max(tau, 0.001)

        # Normalized inventory
        q = inventory / max(c.position_limit, 1.0)

        # Reservation price (A-S 2008)
        reservation = fair_value - q * gamma * sigma_sq * tau_safe

        # Optimal half-spread
        time_component = (gamma * sigma_sq * tau_safe) / 2.0
        arrival_component = (1.0 / gamma) * math.log(1.0 + gamma / max(c.kappa, 0.1))
        raw_half = max(time_component + arrival_component, c.min_half_spread)

        # Spread adjustments
        spread_mult = regime_spread_mult

        # VPIN toxicity widening (Easley et al. 2012)
        if vpin > 0.5:
            spread_mult *= 1.0 + (vpin - 0.5) * 2.0

        # Toxicity widening (Barzykin 2025)
        if toxicity > 0.35:
            spread_mult *= 2.0 + (toxicity - 0.35) * 5.0

        adjusted_half = raw_half * spread_mult

        # OFI skew: positive OFI shifts both quotes upward
        ofi_adj = c.lambda_ofi * ofi

        # Final quotes
        bid = reservation - adjusted_half + ofi_adj
        ask = reservation + adjusted_half + ofi_adj

        # Position sizing (Kelly-based with regime + toxicity)
        toxicity_discount = max(1.0 - toxicity * 2.0, 0.0)
        bid_sz = max(base_size * regime_size_mult * toxicity_discount, 0.0)
        ask_sz = max(base_size * regime_size_mult * toxicity_discount, 0.0)

        # Inventory skew on sizes
        if inventory > 0.0:
            inv_ratio = min(inventory / c.position_limit, 1.0)
            bid_sz *= (1.0 - inv_ratio * 0.5)
            ask_sz *= (1.0 + inv_ratio * 0.3)
        elif inventory < 0.0:
            inv_ratio = min(-inventory / c.position_limit, 1.0)
            bid_sz *= (1.0 + inv_ratio * 0.3)
            ask_sz *= (1.0 - inv_ratio * 0.5)

        return QuotingDecision(
            fair_value=fair_value,
            reservation_price=reservation,
            bid=bid,
            ask=ask,
            raw_half_spread=raw_half,
            adjusted_half_spread=adjusted_half,
            bid_size=bid_sz,
            ask_size=ask_sz,
            active=True,
            halt_reason="",
        )

    def _halt(self, fair_value: float, reason: str) -> QuotingDecision:
        return QuotingDecision(
            fair_value=fair_value,
            reservation_price=fair_value,
            bid=fair_value - 1000.0,
            ask=fair_value + 1000.0,
            raw_half_spread=0.0,
            adjusted_half_spread=0.0,
            bid_size=0.0,
            ask_size=0.0,
            active=False,
            halt_reason=reason,
        )
