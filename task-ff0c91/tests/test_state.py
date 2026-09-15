
"""
Tests for the regime-aware market-making risk pipeline.

Verifies mathematical invariants and cross-module integration for:
  - Volatility models (conditional variance, forecasting, estimation)
  - Market microstructure signals (order flow, informed trading detection)
  - Volatility regime classifier
  - Optimal quoting engine
  - Portfolio risk measures
  - Pipeline orchestration (SQLite persistence, Makefile, JSON report)
"""

import sys
sys.path.insert(0, '/app')

import csv
import json
import math
import os
import random
import sqlite3
import subprocess

import pytest

from pipeline.garch import (
    GarchParams, GarchState, GarchEstimator,
    GjrGarchParams, GjrGarchState,
)
from pipeline.microstructure import (
    microprice, OrderFlowImbalance, Vpin, KyleLambda,
)
from pipeline.regime import Regime, RegimeDetector
from pipeline.quoting import QuotingConfig, QuotingEngine
from pipeline.risk import Position, VarCalculator


# ═══════════════════════════════════════════════════════════════════
# GARCH(1,1) Tests
# ═══════════════════════════════════════════════════════════════════

class TestGarchParams:
    def test_stationarity_check(self):
        """alpha + beta < 1 is stationary; >= 1 is not."""
        p1 = GarchParams(omega=1e-6, alpha=0.09, beta=0.90)
        assert p1.is_stationary()

        p2 = GarchParams(omega=1e-6, alpha=0.15, beta=0.90)
        assert not p2.is_stationary()

        # Exactly 1.0 is non-stationary (strict inequality)
        p3 = GarchParams(omega=1e-6, alpha=0.10, beta=0.90)
        assert not p3.is_stationary()

    def test_long_run_variance(self):
        """Long-run variance = omega / (1 - alpha - beta)."""
        p = GarchParams(omega=1e-6, alpha=0.09, beta=0.90)
        lr = p.long_run_variance()
        expected = 1e-6 / (1.0 - 0.09 - 0.90)  # 1e-4
        assert abs(lr - expected) < 1e-8

        # Non-stationary returns infinity
        p2 = GarchParams(omega=1e-5, alpha=0.15, beta=0.90)
        assert math.isinf(p2.long_run_variance())

    def test_persistence(self):
        """Persistence = alpha + beta."""
        p = GarchParams(omega=1e-6, alpha=0.09, beta=0.90)
        assert abs(p.persistence() - 0.99) < 1e-10

    def test_shock_half_life(self):
        """Half-life = -ln(2) / ln(persistence)."""
        p = GarchParams(omega=1e-6, alpha=0.09, beta=0.90)
        hl = p.shock_half_life()
        expected = -math.log(2) / math.log(0.99)
        assert abs(hl - expected) < 1e-6
        assert hl > 0 and math.isfinite(hl)


class TestGarchState:
    def test_convergence_to_long_run(self):
        """Variance converges to long-run when fed returns at sqrt(LR)."""
        p = GarchParams(omega=1e-6, alpha=0.09, beta=0.90)
        lr = p.long_run_variance()
        state = GarchState(p, lr * 10.0)  # start far above LR
        r = math.sqrt(lr)
        for _ in range(500):
            state.update(r)
        rel_err = abs(state.conditional_variance - lr) / lr
        assert rel_err < 0.01, (
            f"Variance {state.conditional_variance:.8f} didn't converge to LR {lr:.8f}"
        )

    def test_shock_response(self):
        """5-sigma shock spikes variance, which then decays back."""
        p = GarchParams(omega=1e-6, alpha=0.09, beta=0.90)
        lr = p.long_run_variance()
        state = GarchState(p, lr)

        shock = 5.0 * math.sqrt(lr)
        state.update(shock)
        assert state.conditional_variance > lr * 2.0, "Variance should spike after shock"

        r = math.sqrt(lr)
        for _ in range(200):
            state.update(r)
        rel_err = abs(state.conditional_variance - lr) / lr
        assert rel_err < 0.05, "Variance should decay back toward long-run"

    def test_forecast_mean_reversion(self):
        """h-step forecast converges to long-run for large h."""
        p = GarchParams(omega=1e-5, alpha=0.05, beta=0.85)
        lr = p.long_run_variance()
        state = GarchState(p, lr * 5.0)

        f1 = state.forecast(1)
        assert lr < f1 < state.conditional_variance, (
            f"1-step forecast {f1} should be between LR {lr} and current {state.conditional_variance}"
        )

        f100 = state.forecast(100)
        assert abs(f100 - lr) / lr < 0.01, (
            f"100-step forecast {f100} should be near LR {lr}"
        )

    def test_var_1day(self):
        """VaR_1day = z_score * sigma_daily * position_value."""
        p = GarchParams(omega=1e-6, alpha=0.09, beta=0.90)
        state = GarchState(p, 0.0001)  # sigma_daily = 0.01
        var_95 = state.var_1day(1.645, 100_000.0)
        expected = 1.645 * 0.01 * 100_000.0  # = 1645.0
        assert abs(var_95 - expected) < 1.0

    def test_annualized_vol(self):
        """Annualized vol = sqrt(conditional_variance * 252)."""
        p = GarchParams(omega=1e-6, alpha=0.09, beta=0.90)
        state = GarchState(p, 0.0001)
        vol = state.current_vol_annualized()
        expected = math.sqrt(0.0001 * 252)
        assert abs(vol - expected) < 1e-6


class TestGarchEstimator:
    def test_recovers_known_params(self):
        """Fit on synthetic GARCH(1,1) data recovers a reasonable stationary model."""
        random.seed(42)
        omega_true, alpha_true, beta_true = 2e-6, 0.08, 0.90
        sigma2 = omega_true / (1.0 - alpha_true - beta_true)
        returns = []
        for _ in range(1000):
            z = random.gauss(0, 1)
            r = z * math.sqrt(sigma2)
            returns.append(r)
            sigma2 = omega_true + alpha_true * r * r + beta_true * sigma2
            sigma2 = max(sigma2, 1e-10)

        result = GarchEstimator.fit(returns)
        assert result is not None, "Estimator should converge on 1000 samples"
        params, ll = result
        assert params.is_stationary(), "Fitted params should be stationary"
        assert 0.02 < params.alpha < 0.35, (
            f"Alpha should be in reasonable range: {params.alpha}"
        )
        assert 0.60 < params.beta < 0.97, (
            f"Beta should be in reasonable range: {params.beta}"
        )
        assert params.persistence() > 0.90, (
            f"Persistence should be high: {params.persistence()}"
        )
        assert params.persistence() < 1.0, "Must be stationary"
        assert ll > 3.5, f"Log-likelihood should be reasonable: {ll}"

    def test_insufficient_data_returns_none(self):
        """< 50 samples should return None."""
        returns = [math.sin(i * 0.1) * 0.01 for i in range(30)]
        assert GarchEstimator.fit(returns) is None


# ═══════════════════════════════════════════════════════════════════
# GJR-GARCH Tests
# ═══════════════════════════════════════════════════════════════════

class TestGjrGarch:
    def test_leverage_effect(self):
        """Negative return produces higher variance than positive of same magnitude."""
        p = GjrGarchParams(omega=5e-6, alpha=0.05, beta=0.90, gamma=0.08)

        state_pos = GjrGarchState(p, 0.0001)
        state_pos.update(0.02)

        state_neg = GjrGarchState(p, 0.0001)
        state_neg.update(-0.02)

        assert state_neg.conditional_variance > state_pos.conditional_variance, (
            f"Negative return should produce higher variance: "
            f"neg={state_neg.conditional_variance:.8f}, pos={state_pos.conditional_variance:.8f}"
        )

        # Exact difference should be gamma * r^2
        expected_diff = p.gamma * 0.02 ** 2
        actual_diff = state_neg.conditional_variance - state_pos.conditional_variance
        assert abs(actual_diff - expected_diff) < 1e-10, (
            f"Leverage diff: expected {expected_diff:.10f}, got {actual_diff:.10f}"
        )

    def test_stationarity(self):
        """Stationarity requires alpha + beta + gamma/2 < 1."""
        p1 = GjrGarchParams(omega=5e-6, alpha=0.05, beta=0.90, gamma=0.08)
        assert p1.is_stationary()  # 0.05 + 0.90 + 0.04 = 0.99

        p2 = GjrGarchParams(omega=5e-6, alpha=0.10, beta=0.90, gamma=0.10)
        assert not p2.is_stationary()  # 0.10 + 0.90 + 0.05 = 1.05

    def test_long_run_variance(self):
        """Long-run = omega / (1 - alpha - beta - gamma/2)."""
        p = GjrGarchParams(omega=5e-6, alpha=0.05, beta=0.90, gamma=0.08)
        lr = p.long_run_variance()
        expected = 5e-6 / (1.0 - 0.05 - 0.90 - 0.04)
        assert abs(lr - expected) < 1e-8
        assert lr > 0 and math.isfinite(lr)


# ═══════════════════════════════════════════════════════════════════
# Microstructure Signal Tests
# ═══════════════════════════════════════════════════════════════════

class TestMicroprice:
    def test_buying_pressure(self):
        """bid_size >> ask_size pulls microprice toward ask (above midpoint)."""
        mp = microprice(100.0, 101.0, 1000.0, 100.0)
        mid = 100.5
        assert mp > mid, f"Microprice {mp} should be > mid {mid}"

    def test_equal_sizes(self):
        """Equal sizes produce microprice = midpoint."""
        mp = microprice(100.0, 102.0, 500.0, 500.0)
        assert abs(mp - 101.0) < 0.001

    def test_selling_pressure(self):
        """ask_size >> bid_size pulls microprice toward bid (below midpoint)."""
        mp = microprice(100.0, 101.0, 100.0, 1000.0)
        mid = 100.5
        assert mp < mid, f"Microprice {mp} should be < mid {mid}"


class TestOfi:
    def test_buying_pressure(self):
        """Increasing bid size with stable prices produces positive OFI."""
        ofi = OrderFlowImbalance(window_size=10)
        ofi.update(100.0, 500.0, 101.0, 500.0)  # initialize
        val = ofi.update(100.0, 800.0, 101.0, 200.0)  # bid up, ask down
        assert val > 0, f"OFI should be positive for buying pressure: {val}"

    def test_selling_pressure(self):
        """Increasing ask size with stable prices produces negative OFI."""
        ofi = OrderFlowImbalance(window_size=10)
        ofi.update(100.0, 500.0, 101.0, 500.0)
        val = ofi.update(100.0, 200.0, 101.0, 800.0)  # bid down, ask up
        assert val < 0, f"OFI should be negative for selling pressure: {val}"


class TestVpin:
    def test_balanced_flow(self):
        """Balanced buy/sell flow produces low VPIN."""
        vpin = Vpin(bucket_volume=1000.0, num_buckets=10)
        for i in range(100):
            price = 100.0 + (0.01 if i % 2 == 0 else -0.01)
            prev = 100.0 - (0.01 if i % 2 == 0 else -0.01)
            vpin.update(price, prev, 100.0)
        assert vpin.value() < 0.5, f"Balanced flow VPIN should be low: {vpin.value()}"

    def test_one_sided_flow(self):
        """All buy-side trades produce high VPIN."""
        vpin = Vpin(bucket_volume=500.0, num_buckets=10)
        for _ in range(100):
            vpin.update(100.01, 100.0, 100.0)  # all upticks = buys
        assert vpin.value() > 0.5, f"One-sided flow VPIN should be high: {vpin.value()}"


class TestKyleLambda:
    def test_nonnegative(self):
        """Kyle's Lambda (price impact coefficient) should be non-negative."""
        kyle = KyleLambda(window_size=50)
        for i in range(50):
            mid = 100.0 + i * 0.01
            flow = 100.0 + i * 0.5
            kyle.update(mid, flow)
        assert kyle.lambda_() >= 0, f"Lambda should be >= 0: {kyle.lambda_()}"


# ═══════════════════════════════════════════════════════════════════
# Regime Detector Tests
# ═══════════════════════════════════════════════════════════════════

class TestRegime:
    def test_normal_stable(self):
        """Constant volatility observations yield Normal regime."""
        det = RegimeDetector()
        for _ in range(50):
            det.update(1.0)
        assert det.regime == Regime.NORMAL
        assert abs(det.vol_ratio - 1.0) < 0.1

    def test_params_gamma_ordered(self):
        """Risk aversion (gamma) increases monotonically across regimes."""
        gammas = [
            Regime.LOW_VOL.params().gamma,
            Regime.NORMAL.params().gamma,
            Regime.HIGH_VOL.params().gamma,
            Regime.CRISIS.params().gamma,
        ]
        for i in range(len(gammas) - 1):
            assert gammas[i] < gammas[i + 1], (
                f"Gamma not monotonic: {gammas[i]} >= {gammas[i+1]}"
            )

    def test_size_mult_decreases_with_risk(self):
        """Position size multiplier decreases as regime severity increases."""
        assert Regime.LOW_VOL.params().size_mult > Regime.CRISIS.params().size_mult
        assert Regime.NORMAL.params().size_mult > Regime.HIGH_VOL.params().size_mult

    def test_spread_mult_increases_with_risk(self):
        """Spread multiplier increases as regime severity increases."""
        assert Regime.LOW_VOL.params().spread_mult < Regime.NORMAL.params().spread_mult
        assert Regime.NORMAL.params().spread_mult < Regime.HIGH_VOL.params().spread_mult
        assert Regime.HIGH_VOL.params().spread_mult < Regime.CRISIS.params().spread_mult


# ═══════════════════════════════════════════════════════════════════
# Avellaneda-Stoikov Quoting Engine Tests
# ═══════════════════════════════════════════════════════════════════

class TestQuotingEngine:
    def test_quotes_bracket_fair_value(self):
        """With zero inventory, bid < fair_value < ask."""
        config = QuotingConfig()
        engine = QuotingEngine(config)
        q = engine.compute(
            fair_value=100.0, inventory=0.0, sigma=0.01, tau=0.5,
            ofi=0.0, vpin=0.0, regime_gamma=0.10,
            regime_spread_mult=1.0, regime_size_mult=1.0,
            toxicity=0.0, base_size=10.0,
        )
        assert q.active
        assert q.bid < 100.0, f"Bid {q.bid} should be < FV 100.0"
        assert q.ask > 100.0, f"Ask {q.ask} should be > FV 100.0"
        assert q.ask > q.bid

    def test_inventory_skews_reservation(self):
        """Long inventory -> reservation below FV; short -> above FV."""
        config = QuotingConfig()
        engine = QuotingEngine(config)

        long_q = engine.compute(100.0, 50.0, 0.01, 0.5, 0.0, 0.0,
                                0.10, 1.0, 1.0, 0.0, 10.0)
        flat_q = engine.compute(100.0, 0.0, 0.01, 0.5, 0.0, 0.0,
                                0.10, 1.0, 1.0, 0.0, 10.0)
        short_q = engine.compute(100.0, -50.0, 0.01, 0.5, 0.0, 0.0,
                                 0.10, 1.0, 1.0, 0.0, 10.0)

        assert long_q.reservation_price < flat_q.reservation_price, (
            f"Long should skew down: {long_q.reservation_price} vs {flat_q.reservation_price}"
        )
        assert short_q.reservation_price > flat_q.reservation_price, (
            f"Short should skew up: {short_q.reservation_price} vs {flat_q.reservation_price}"
        )

    def test_vol_widens_spread(self):
        """Higher volatility produces wider bid-ask spread."""
        config = QuotingConfig(min_half_spread=0.0)
        engine = QuotingEngine(config)

        low = engine.compute(100.0, 0.0, 0.005, 0.5, 0.0, 0.0,
                             0.10, 1.0, 1.0, 0.0, 10.0)
        high = engine.compute(100.0, 0.0, 0.05, 0.5, 0.0, 0.0,
                              0.10, 1.0, 1.0, 0.0, 10.0)

        spread_low = low.ask - low.bid
        spread_high = high.ask - high.bid
        assert spread_high > spread_low, (
            f"High vol should widen: low={spread_low}, high={spread_high}"
        )

    def test_toxicity_halts(self):
        """Toxicity > 0.65 triggers adverse selection halt."""
        config = QuotingConfig()
        engine = QuotingEngine(config)
        q = engine.compute(100.0, 0.0, 0.01, 0.5, 0.0, 0.0,
                           0.10, 1.0, 1.0, 0.70, 10.0)
        assert not q.active, "Should halt at toxicity > 0.65"
        assert q.halt_reason == "adverse_selection_halt"
        assert q.bid_size == 0.0
        assert q.ask_size == 0.0

    def test_vpin_extreme_halts(self):
        """VPIN > 0.85 triggers halt."""
        config = QuotingConfig()
        engine = QuotingEngine(config)
        q = engine.compute(100.0, 0.0, 0.01, 0.5, 0.0, 0.90,
                           0.10, 1.0, 1.0, 0.0, 10.0)
        assert not q.active, "Should halt at VPIN > 0.85"
        assert q.halt_reason == "vpin_extreme"

    def test_ofi_skews_quotes(self):
        """Positive OFI (buy pressure) shifts both quotes upward."""
        config = QuotingConfig()
        engine = QuotingEngine(config)

        neutral = engine.compute(100.0, 0.0, 0.01, 0.5, 0.0, 0.0,
                                 0.10, 1.0, 1.0, 0.0, 10.0)
        buy_pressure = engine.compute(100.0, 0.0, 0.01, 0.5, 0.8, 0.0,
                                      0.10, 1.0, 1.0, 0.0, 10.0)

        assert buy_pressure.bid > neutral.bid, (
            f"Buy pressure should shift bid up: neutral={neutral.bid}, ofi={buy_pressure.bid}"
        )

    def test_crisis_regime_reduces_size(self):
        """Crisis regime (small size_mult) reduces position sizes."""
        config = QuotingConfig()
        engine = QuotingEngine(config)

        normal = engine.compute(100.0, 0.0, 0.01, 0.5, 0.0, 0.0,
                                0.10, 1.0, 1.0, 0.0, 10.0)
        crisis = engine.compute(100.0, 0.0, 0.01, 0.5, 0.0, 0.0,
                                0.40, 4.0, 0.2, 0.0, 10.0)

        assert crisis.bid_size < normal.bid_size, (
            f"Crisis should reduce size: normal={normal.bid_size}, crisis={crisis.bid_size}"
        )


# ═══════════════════════════════════════════════════════════════════
# Value-at-Risk Tests
# ═══════════════════════════════════════════════════════════════════

def _make_var_calculator(sigma_pct=1.5, n_days=252, seed=99):
    """Helper: create VarCalculator with deterministic pseudo-normal returns."""
    calc = VarCalculator(min_history_days=20)
    random.seed(seed)
    for _ in range(n_days):
        ret = random.gauss(0, sigma_pct)
        calc.update_returns("TEST", ret)
    return calc


class TestVarCalculator:
    def test_var_99_exceeds_95(self):
        """VaR at 99% confidence >= VaR at 95%."""
        calc = _make_var_calculator()
        positions = [Position("TEST", 100.0, 100.0)]
        result = calc.historical_var(positions)
        assert result is not None
        assert result.var_99_1d_usd >= result.var_95_1d_usd, (
            f"VaR99 ({result.var_99_1d_usd:.2f}) should >= VaR95 ({result.var_95_1d_usd:.2f})"
        )

    def test_cvar_exceeds_var(self):
        """CVaR (Expected Shortfall) >= VaR at same confidence."""
        calc = _make_var_calculator()
        positions = [Position("TEST", 100.0, 100.0)]
        result = calc.historical_var(positions)
        assert result is not None
        assert result.cvar_95_usd >= result.var_95_1d_usd, (
            f"CVaR ({result.cvar_95_usd:.2f}) should >= VaR95 ({result.var_95_1d_usd:.2f})"
        )

    def test_scales_with_position_size(self):
        """Doubling position size approximately doubles parametric VaR."""
        calc = _make_var_calculator()
        small = [Position("TEST", 50.0, 100.0)]
        large = [Position("TEST", 100.0, 100.0)]

        var_small = calc.parametric_var(small)
        var_large = calc.parametric_var(large)
        assert var_small is not None and var_large is not None

        ratio = var_large.var_95_1d_usd / max(var_small.var_95_1d_usd, 1e-10)
        assert abs(ratio - 2.0) < 0.01, (
            f"VaR should scale linearly: ratio={ratio:.4f}, expected 2.0"
        )

    def test_10d_sqrt_scaling(self):
        """10-day VaR = 1-day VaR * sqrt(10) (Basel scaling)."""
        calc = _make_var_calculator()
        positions = [Position("TEST", 100.0, 100.0)]
        result = calc.historical_var(positions)
        assert result is not None
        expected = result.var_99_1d_usd * math.sqrt(10)
        rel_err = abs(result.var_99_10d_usd - expected) / max(expected, 1e-10)
        assert rel_err < 0.001, (
            f"10d VaR ({result.var_99_10d_usd:.4f}) should = 1d * sqrt(10) ({expected:.4f})"
        )

    def test_empty_portfolio_returns_none(self):
        """Empty portfolio returns None for both methods."""
        calc = VarCalculator(min_history_days=20)
        assert calc.historical_var([]) is None
        assert calc.parametric_var([]) is None

    def test_insufficient_history_returns_none(self):
        """Returns None when history is below minimum threshold."""
        calc = VarCalculator(min_history_days=50)
        for i in range(20):
            calc.update_returns("TEST", float(i) * 0.01)
        positions = [Position("TEST", 100.0, 100.0)]
        assert calc.historical_var(positions) is None

    def test_parametric_var_positive(self):
        """Parametric VaR values should be positive for non-trivial portfolios."""
        calc = _make_var_calculator()
        positions = [Position("TEST", 100.0, 100.0)]
        result = calc.parametric_var(positions)
        assert result is not None
        assert result.var_95_1d_usd > 0
        assert result.var_99_1d_usd > 0
        assert result.var_99_1d_usd >= result.var_95_1d_usd


# ═══════════════════════════════════════════════════════════════════
# Integration Test — Full Pipeline on Provided Data
# ═══════════════════════════════════════════════════════════════════

class TestPipelineIntegration:
    def test_full_pipeline(self):
        """Run all modules on provided data and verify pipeline invariants."""
        # 1. Load returns data
        returns = []
        with open('/app/data/returns.csv') as f:
            reader = csv.DictReader(f)
            for row in reader:
                returns.append(float(row['log_return']))
        assert len(returns) == 500

        # 2. Fit GARCH on returns
        result = GarchEstimator.fit(returns)
        assert result is not None, "GARCH should fit on 500 returns"
        params, ll = result
        assert params.is_stationary(), "Fitted GARCH should be stationary"

        # 3. Run GARCH state through returns
        state = GarchState(params, params.long_run_variance())
        for r in returns:
            state.update(r)
        vol = state.current_vol_annualized()
        assert 0.05 < vol < 1.0, f"Annualized vol should be sensible: {vol}"

        # 4. Feed returns into regime detector
        det = RegimeDetector()
        for r in returns:
            det.update(abs(r))
        assert det.regime in (Regime.LOW_VOL, Regime.NORMAL,
                              Regime.HIGH_VOL, Regime.CRISIS)

        # 5. Compute A-S quotes using GARCH vol and regime params
        config = QuotingConfig()
        engine = QuotingEngine(config)
        rp = det.regime.params()
        sigma_daily = math.sqrt(state.conditional_variance)
        q = engine.compute(
            fair_value=100.0, inventory=0.0, sigma=sigma_daily,
            tau=0.5, ofi=0.0, vpin=0.0,
            regime_gamma=rp.gamma, regime_spread_mult=rp.spread_mult,
            regime_size_mult=rp.size_mult, toxicity=0.0, base_size=10.0,
        )
        assert q.active
        assert q.bid < 100.0 < q.ask

        # 6. Load orderbook and run microstructure signals
        ticks = []
        with open('/app/data/orderbook.csv') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticks.append(row)
        assert len(ticks) == 3000

        ofi = OrderFlowImbalance(window_size=20)
        for tick in ticks[:100]:
            val = ofi.update(
                float(tick['bid_price']), float(tick['bid_size']),
                float(tick['ask_price']), float(tick['ask_size']),
            )
        assert -1.0 <= val <= 1.0, f"OFI should be in [-1, 1]: {val}"

        # 7. VaR from returns
        calc = VarCalculator(min_history_days=20)
        for r in returns:
            calc.update_returns("SYN", r * 100.0)  # convert to pct
        positions = [Position("SYN", 1000.0, 100.0)]
        var_result = calc.historical_var(positions)
        assert var_result is not None
        assert var_result.var_99_1d_usd >= var_result.var_95_1d_usd
        assert var_result.cvar_95_usd >= var_result.var_95_1d_usd


# ═══════════════════════════════════════════════════════════════════
# Pipeline Orchestration Tests — SQLite, Makefile, Report
# ═══════════════════════════════════════════════════════════════════

class TestPipelineOrchestration:
    """Verify Makefile orchestration, SQLite persistence, and JSON report."""

    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Makefile must exist at /app/Makefile"

    def test_makefile_uses_required_tools(self):
        """Makefile must reference both jq and sqlite3."""
        with open("/app/Makefile") as f:
            content = f.read()
        assert "jq" in content, "Makefile must use jq for config validation and report assembly"
        assert "sqlite3" in content, "Makefile must use sqlite3 for database operations"

    def test_make_pipeline_succeeds(self):
        """make pipeline must complete without error."""
        result = subprocess.run(
            ["make", "-C", "/app", "pipeline"],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, f"make pipeline failed:\n{result.stderr}\n{result.stdout}"

    def test_database_exists(self):
        assert os.path.exists("/app/results.db"), "results.db must exist after pipeline"

    def test_database_has_required_tables(self):
        conn = sqlite3.connect("/app/results.db")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor}
        conn.close()
        for table in ["volatility_forecast", "regime_state",
                       "quoting_decision", "risk_metrics"]:
            assert table in tables, f"Missing table: {table}"

    def test_volatility_forecasts_count(self):
        conn = sqlite3.connect("/app/results.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM volatility_forecast"
        ).fetchone()[0]
        conn.close()
        assert count == 500, f"Expected 500 volatility rows, got {count}"

    def test_volatility_values_positive(self):
        conn = sqlite3.connect("/app/results.db")
        row = conn.execute(
            "SELECT MIN(conditional_variance), MIN(annualized_vol) FROM volatility_forecast"
        ).fetchone()
        conn.close()
        assert row[0] > 0, "All conditional variances must be positive"
        assert row[1] > 0, "All annualized vols must be positive"

    def test_regime_states_count(self):
        conn = sqlite3.connect("/app/results.db")
        count = conn.execute("SELECT COUNT(*) FROM regime_state").fetchone()[0]
        conn.close()
        assert count == 3000, f"Expected 3000 regime rows, got {count}"

    def test_regime_values_valid(self):
        conn = sqlite3.connect("/app/results.db")
        regimes = conn.execute(
            "SELECT DISTINCT regime FROM regime_state"
        ).fetchall()
        valid = {"low_vol", "normal", "high_vol", "crisis"}
        conn.close()
        for (r,) in regimes:
            assert r in valid, f"Invalid regime value: {r}"

    def test_quoting_decisions_count(self):
        conn = sqlite3.connect("/app/results.db")
        count = conn.execute(
            "SELECT COUNT(*) FROM quoting_decision"
        ).fetchone()[0]
        conn.close()
        assert count == 3000, f"Expected 3000 quoting rows, got {count}"

    def test_quoting_bid_ask_ordering(self):
        """Active quotes must have bid < ask."""
        conn = sqlite3.connect("/app/results.db")
        bad = conn.execute(
            "SELECT COUNT(*) FROM quoting_decision WHERE active=1 AND bid >= ask"
        ).fetchone()[0]
        conn.close()
        assert bad == 0, f"Found {bad} active quotes with bid >= ask"

    def test_risk_metrics_populated(self):
        conn = sqlite3.connect("/app/results.db")
        count = conn.execute("SELECT COUNT(*) FROM risk_metrics").fetchone()[0]
        conn.close()
        assert count >= 2, f"Expected >= 2 risk metric rows, got {count}"

    def test_risk_var_ordering_in_db(self):
        """VaR99 >= VaR95 for all methods in the database."""
        conn = sqlite3.connect("/app/results.db")
        rows = conn.execute(
            "SELECT method, var_95_1d, var_99_1d FROM risk_metrics"
        ).fetchall()
        conn.close()
        for method, v95, v99 in rows:
            assert v99 >= v95, f"VaR99 >= VaR95 violated for {method}"

    def test_report_json_exists(self):
        assert os.path.exists("/app/report.json"), "report.json must exist"

    def test_report_json_structure(self):
        with open("/app/report.json") as f:
            report = json.load(f)
        for key in ["volatility_forecast_count", "regime_distribution",
                     "active_quotes_count", "halted_quotes_count",
                     "var_99_1d", "cvar_95"]:
            assert key in report, f"Missing key '{key}' in report.json"
        assert isinstance(report["regime_distribution"], dict), (
            "regime_distribution must be an object"
        )
        assert report["volatility_forecast_count"] == 500

    def test_report_var_positive(self):
        with open("/app/report.json") as f:
            report = json.load(f)
        assert report["var_99_1d"] > 0, "VaR must be positive"
        assert report["cvar_95"] > 0, "CVaR must be positive"
