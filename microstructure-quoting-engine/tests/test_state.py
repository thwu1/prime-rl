
import pytest
import json
import csv
import os
import sys
import math

sys.path.insert(0, '/app')


# ============================================================
# Section 1: Module existence and importability
# ============================================================

class TestModuleStructure:
    def test_engine_package_exists(self):
        import engine  # noqa: F401

    def test_garch_module(self):
        from engine.garch import GarchParams, GarchState, GarchEstimator  # noqa: F401

    def test_microstructure_module(self):
        from engine.microstructure import OrderFlowImbalance, microprice, Vpin, KyleLambda  # noqa: F401

    def test_regime_module(self):
        from engine.regime import RegimeDetector  # noqa: F401

    def test_toxicity_module(self):
        from engine.toxicity import ToxicityDetector  # noqa: F401

    def test_quoting_module(self):
        from engine.quoting import QuotingEngine  # noqa: F401


# ============================================================
# Section 2: GARCH(1,1) correctness
# ============================================================

class TestGarch:
    def test_stationarity_check_stationary(self):
        from engine.garch import GarchParams
        p = GarchParams(omega=0.000001, alpha=0.09, beta=0.90)
        assert p.is_stationary()

    def test_stationarity_check_nonstationary(self):
        from engine.garch import GarchParams
        p = GarchParams(omega=0.000001, alpha=0.15, beta=0.90)
        assert not p.is_stationary()

    def test_long_run_variance(self):
        from engine.garch import GarchParams
        p = GarchParams(omega=0.000001, alpha=0.09, beta=0.90)
        lr = p.long_run_variance()
        expected = 0.000001 / (1.0 - 0.09 - 0.90)
        assert abs(lr - expected) < 1e-8, f"Expected {expected}, got {lr}"

    def test_nonstationary_lr_infinite(self):
        from engine.garch import GarchParams
        p = GarchParams(omega=0.000001, alpha=0.15, beta=0.90)
        lr = p.long_run_variance()
        assert lr == float('inf') or lr > 1e10

    def test_variance_update_formula(self):
        from engine.garch import GarchParams, GarchState
        p = GarchParams(omega=0.000001, alpha=0.09, beta=0.90)
        s = GarchState(p, 0.0001)
        s.update(0.02)
        expected = 0.000001 + 0.09 * (0.02 ** 2) + 0.90 * 0.0001
        assert abs(s.conditional_variance - expected) < 1e-10, \
            f"Expected {expected}, got {s.conditional_variance}"

    def test_variance_convergence_to_long_run(self):
        from engine.garch import GarchParams, GarchState
        p = GarchParams(omega=0.000001, alpha=0.09, beta=0.90)
        lr = p.long_run_variance()
        r = math.sqrt(lr)
        s = GarchState(p, 0.001)
        for _ in range(500):
            s.update(r)
        rel_err = abs(s.conditional_variance - lr) / lr
        assert rel_err < 0.01, \
            f"Didn't converge: var={s.conditional_variance}, lr={lr}, err={rel_err:.4f}"

    def test_shock_spikes_variance(self):
        from engine.garch import GarchParams, GarchState
        p = GarchParams(omega=0.000001, alpha=0.09, beta=0.90)
        lr = p.long_run_variance()
        s = GarchState(p, lr)
        s.update(5.0 * math.sqrt(lr))
        assert s.conditional_variance > lr * 2, \
            f"Post-shock {s.conditional_variance} should exceed 2*lr={2 * lr}"

    def test_forecast_mean_reverts(self):
        from engine.garch import GarchParams, GarchState
        p = GarchParams(omega=0.000010, alpha=0.10, beta=0.85)
        lr = p.long_run_variance()
        s = GarchState(p, 0.0005)
        f1 = s.forecast(1)
        f100 = s.forecast(100)
        assert f1 < 0.0005 and f1 > lr, \
            f"1-step forecast {f1} should be between current 0.0005 and lr {lr}"
        assert abs(f100 - lr) / lr < 0.02, \
            f"100-step forecast {f100} should approx lr {lr}"

    def test_estimator_recovers_params(self):
        from engine.garch import GarchParams, GarchState, GarchEstimator
        true_p = GarchParams(omega=0.000002, alpha=0.08, beta=0.90)
        lr = true_p.long_run_variance()

        sigma2 = lr
        returns = []
        seed = 42
        for _ in range(1000):
            seed = (seed * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
            u1 = max((seed >> 11) / (1 << 53), 1e-15)
            seed = (seed * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
            u2 = (seed >> 11) / (1 << 53)
            z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
            r = z * math.sqrt(sigma2)
            returns.append(r)
            sigma2 = true_p.omega + true_p.alpha * r ** 2 + true_p.beta * sigma2
            sigma2 = max(sigma2, 1e-12)

        fitted = GarchEstimator.fit(returns)
        assert fitted is not None, "Estimator should converge on 1000 samples"
        fp = fitted[0] if isinstance(fitted, tuple) else fitted
        assert fp.is_stationary(), f"Fitted params should be stationary: a={fp.alpha}, b={fp.beta}"
        assert abs(fp.alpha - 0.08) < 0.08, f"Alpha: expected ~0.08, got {fp.alpha}"
        assert abs(fp.beta - 0.90) < 0.15, f"Beta: expected ~0.90, got {fp.beta}"
        assert fp.alpha + fp.beta < 1.0

    def test_estimator_insufficient_data(self):
        from engine.garch import GarchEstimator
        returns = [math.sin(i * 0.001) * 0.01 for i in range(30)]
        result = GarchEstimator.fit(returns)
        assert result is None


# ============================================================
# Section 3: Microstructure signals
# ============================================================

class TestMicrostructure:
    def test_microprice_balanced(self):
        from engine.microstructure import microprice
        mp = microprice(100.0, 102.0, 500.0, 500.0)
        assert abs(mp - 101.0) < 0.001

    def test_microprice_buy_pressure(self):
        from engine.microstructure import microprice
        mp = microprice(100.0, 101.0, 1000.0, 100.0)
        mid = 100.5
        assert mp > mid, f"Microprice {mp} should be > mid {mid}"

    def test_microprice_sell_pressure(self):
        from engine.microstructure import microprice
        mp = microprice(100.0, 101.0, 100.0, 1000.0)
        mid = 100.5
        assert mp < mid, f"Microprice {mp} should be < mid {mid}"

    def test_ofi_buying_pressure(self):
        from engine.microstructure import OrderFlowImbalance
        ofi = OrderFlowImbalance(window_size=10)
        ofi.update(100.0, 500.0, 101.0, 500.0)
        val = ofi.update(100.0, 800.0, 101.0, 200.0)
        assert val > 0, f"OFI should be positive for buying pressure: {val}"

    def test_ofi_selling_pressure(self):
        from engine.microstructure import OrderFlowImbalance
        ofi = OrderFlowImbalance(window_size=10)
        ofi.update(100.0, 500.0, 101.0, 500.0)
        val = ofi.update(100.0, 200.0, 101.0, 800.0)
        assert val < 0, f"OFI should be negative for selling pressure: {val}"

    def test_vpin_balanced_low(self):
        from engine.microstructure import Vpin
        vpin = Vpin(bucket_volume=1000.0, num_buckets=10)
        for i in range(200):
            price = 100.0 + (0.01 if i % 2 == 0 else -0.01)
            prev = 100.0 - (0.01 if i % 2 == 0 else -0.01)
            vpin.update(price, prev, 100.0)
        assert vpin.value() < 0.5, f"Balanced VPIN should be low: {vpin.value()}"

    def test_vpin_onesided_high(self):
        from engine.microstructure import Vpin
        vpin = Vpin(bucket_volume=500.0, num_buckets=10)
        for _ in range(200):
            vpin.update(100.01, 100.0, 100.0)
        assert vpin.value() > 0.5, f"One-sided VPIN should be high: {vpin.value()}"

    def test_kyle_lambda_nonnegative(self):
        from engine.microstructure import KyleLambda
        kl = KyleLambda(window_size=50)
        for i in range(60):
            mid = 100.0 + i * 0.01
            kl.update(mid, 100.0 + i * 0.5)
        assert kl.lambda_value() >= 0, f"Lambda should be >= 0: {kl.lambda_value()}"


# ============================================================
# Section 4: Regime detection
# ============================================================

class TestRegime:
    def test_normal_regime_stable(self):
        from engine.regime import RegimeDetector
        det = RegimeDetector()
        for _ in range(50):
            det.update(1.0)
        regime = det.regime()
        assert regime == 'Normal', f"Expected 'Normal', got '{regime}'"

    def test_vol_spike_raises_ratio(self):
        from engine.regime import RegimeDetector
        det = RegimeDetector()
        for _ in range(50):
            det.update(1.0)
        for _ in range(10):
            det.update(15.0)
        assert det.vol_ratio() > 1.3, f"Vol ratio should be elevated: {det.vol_ratio()}"

    def test_regime_params_gamma_monotonic(self):
        from engine.regime import RegimeDetector
        det = RegimeDetector()
        params_map = det.get_regime_params_map()
        assert params_map['Crisis']['gamma'] > params_map['Normal']['gamma'], \
            f"Crisis gamma {params_map['Crisis']['gamma']} should > Normal {params_map['Normal']['gamma']}"
        assert params_map['Normal']['gamma'] >= params_map['LowVol']['gamma'], \
            f"Normal gamma {params_map['Normal']['gamma']} should >= LowVol {params_map['LowVol']['gamma']}"

    def test_high_vol_triggers_elevated_regime(self):
        from engine.regime import RegimeDetector
        det = RegimeDetector()
        for _ in range(50):
            det.update(1.0)
        for _ in range(20):
            det.update(25.0)
        assert det.regime() in ('HighVol', 'Crisis'), \
            f"Extreme volatility should trigger elevated regime, got '{det.regime()}'"

    def test_extreme_spike_does_not_reduce_risk(self):
        """After a sudden extreme spike, risk aversion must increase, not decrease."""
        from engine.regime import RegimeDetector
        det = RegimeDetector()
        for _ in range(50):
            det.update(1.0)
        for _ in range(8):
            det.update(50.0)
        regime = det.regime()
        assert regime != 'LowVol' and regime != 'Normal', \
            f"Extreme volatility spike must elevate regime risk, got '{regime}'"


# ============================================================
# Section 5: Toxicity detection
# ============================================================

class TestToxicity:
    def test_clean_flow_stays_low(self):
        from engine.toxicity import ToxicityDetector
        det = ToxicityDetector()
        for i in range(20):
            det.record_fill(100.0, True, i)
            det.evaluate(100.5, i + 3)
        assert det.toxicity() < 0.1, f"Clean toxicity should be low: {det.toxicity()}"

    def test_toxic_flow_elevates(self):
        from engine.toxicity import ToxicityDetector
        det = ToxicityDetector(alpha=0.3)
        for i in range(20):
            det.record_fill(100.0, True, i)
            det.evaluate(99.0, i + 3)
        assert det.toxicity() > 0.3, f"Toxic flow should elevate: {det.toxicity()}"


# ============================================================
# Section 6: Quoting engine
# ============================================================

class TestQuoting:
    def test_quotes_bracket_fair_value(self):
        from engine.quoting import QuotingEngine
        eng = QuotingEngine()
        q = eng.compute(
            fair_value=100.0, inventory=0.0, sigma=0.01, tau=0.5,
            ofi=0.0, vpin=0.0, regime_gamma=0.10, regime_spread_mult=1.0,
            regime_size_mult=1.0, toxicity=0.0, base_size=10.0
        )
        assert q['bid'] < 100.0, f"Bid {q['bid']} should be < FV 100.0"
        assert q['ask'] > 100.0, f"Ask {q['ask']} should be > FV 100.0"
        assert q['ask'] > q['bid'], f"Ask {q['ask']} should > Bid {q['bid']}"
        assert q['active'] is True

    def test_inventory_skews_reservation(self):
        from engine.quoting import QuotingEngine
        eng = QuotingEngine()
        args = dict(sigma=0.01, tau=0.5, ofi=0.0, vpin=0.0,
                    regime_gamma=0.10, regime_spread_mult=1.0,
                    regime_size_mult=1.0, toxicity=0.0, base_size=10.0)
        long_q = eng.compute(fair_value=100.0, inventory=50.0, **args)
        flat_q = eng.compute(fair_value=100.0, inventory=0.0, **args)
        short_q = eng.compute(fair_value=100.0, inventory=-50.0, **args)
        assert long_q['reservation_price'] < flat_q['reservation_price'], \
            f"Long res {long_q['reservation_price']} should < flat {flat_q['reservation_price']}"
        assert short_q['reservation_price'] > flat_q['reservation_price'], \
            f"Short res {short_q['reservation_price']} should > flat {flat_q['reservation_price']}"

    def test_toxicity_halts_quoting(self):
        from engine.quoting import QuotingEngine
        eng = QuotingEngine()
        q = eng.compute(
            fair_value=100.0, inventory=0.0, sigma=0.01, tau=0.5,
            ofi=0.0, vpin=0.0, regime_gamma=0.10, regime_spread_mult=1.0,
            regime_size_mult=1.0, toxicity=0.70, base_size=10.0
        )
        assert q['active'] is False, "Should halt at toxicity > 0.65"

    def test_high_vol_widens_spread(self):
        from engine.quoting import QuotingEngine
        eng = QuotingEngine(min_half_spread=0.0)
        args = dict(inventory=0.0, tau=0.5, ofi=0.0, vpin=0.0,
                    regime_gamma=0.10, regime_spread_mult=1.0,
                    regime_size_mult=1.0, toxicity=0.0, base_size=10.0)
        low = eng.compute(fair_value=100.0, sigma=0.005, **args)
        high = eng.compute(fair_value=100.0, sigma=0.05, **args)
        spread_low = low['ask'] - low['bid']
        spread_high = high['ask'] - high['bid']
        assert spread_high > spread_low, \
            f"High vol spread {spread_high} should > low vol {spread_low}"

    def test_vpin_widens_spread(self):
        from engine.quoting import QuotingEngine
        eng = QuotingEngine()
        args = dict(fair_value=100.0, inventory=0.0, sigma=0.01, tau=0.5,
                    ofi=0.0, regime_gamma=0.10, regime_spread_mult=1.0,
                    regime_size_mult=1.0, toxicity=0.0, base_size=10.0)
        safe = eng.compute(vpin=0.1, **args)
        toxic = eng.compute(vpin=0.7, **args)
        spread_safe = safe['ask'] - safe['bid']
        spread_toxic = toxic['ask'] - toxic['bid']
        assert spread_toxic > spread_safe, \
            f"High VPIN spread {spread_toxic} should > safe {spread_safe}"

    def test_ofi_shifts_quotes_up(self):
        from engine.quoting import QuotingEngine
        eng = QuotingEngine()
        args = dict(fair_value=100.0, inventory=0.0, sigma=0.01, tau=0.5,
                    vpin=0.0, regime_gamma=0.10, regime_spread_mult=1.0,
                    regime_size_mult=1.0, toxicity=0.0, base_size=10.0)
        neutral = eng.compute(ofi=0.0, **args)
        buy_press = eng.compute(ofi=0.8, **args)
        assert buy_press['bid'] > neutral['bid'], \
            f"Positive OFI should raise bid: neutral={neutral['bid']}, ofi={buy_press['bid']}"


# ============================================================
# Section 7: Integration / End-to-end
# ============================================================

class TestIntegration:
    @classmethod
    def setup_class(cls):
        import subprocess
        try:
            result = subprocess.run(
                ['python3', '/app/run.py'],
                capture_output=True, text=True, timeout=120
            )
            cls._sim_ok = result.returncode == 0
            cls._sim_err = result.stderr if result.returncode != 0 else ''
        except Exception as e:
            cls._sim_ok = False
            cls._sim_err = str(e)

    def test_data_file_exists(self):
        assert os.path.exists('/app/data/events.csv'), "events.csv not found"

    def test_data_has_expected_columns(self):
        with open('/app/data/events.csv') as f:
            header = next(csv.reader(f))
        required = {'timestamp', 'bid_price', 'bid_size', 'ask_price', 'ask_size',
                     'trade_price', 'trade_volume', 'trade_side', 'log_return'}
        assert required.issubset(set(header)), f"Missing columns: {required - set(header)}"

    def test_simulation_succeeds(self):
        assert self._sim_ok, f"Simulation failed: {self._sim_err}"

    def test_output_garch_params_valid(self):
        path = '/app/output/garch_params.json'
        assert os.path.exists(path), f"{path} not found"
        with open(path) as f:
            params = json.load(f)
        assert 'alpha' in params and 'beta' in params and 'omega' in params
        assert 0.01 < params['alpha'] < 0.30, f"alpha out of range: {params['alpha']}"
        assert 0.60 < params['beta'] < 0.99, f"beta out of range: {params['beta']}"
        assert params['alpha'] + params['beta'] < 1.0, \
            f"Non-stationary: alpha+beta={params['alpha'] + params['beta']}"

    def test_output_simulation_results(self):
        path = '/app/output/simulation_results.json'
        assert os.path.exists(path), f"{path} not found"
        with open(path) as f:
            results = json.load(f)
        assert 'total_quotes' in results
        assert 'active_quotes' in results
        assert 'halted_quotes' in results
        assert results['total_quotes'] > 0, "Should have produced quotes"
        assert results['active_quotes'] > 0, "Should have some active quotes"

    def test_output_quotes_csv_valid(self):
        path = '/app/output/quotes.csv'
        assert os.path.exists(path), f"{path} not found"
        with open(path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) > 100, f"Expected >100 quotes, got {len(rows)}"
        active_rows = [r for r in rows if r.get('active', 'true').lower() == 'true']
        for row in active_rows[:50]:
            assert float(row['bid']) < float(row['ask']), \
                f"Active quote at t={row.get('timestamp')}: bid={row['bid']} >= ask={row['ask']}"

    def test_regime_detection_finds_elevated(self):
        path = '/app/output/simulation_results.json'
        if not os.path.exists(path):
            pytest.skip("simulation_results.json not found")
        with open(path) as f:
            results = json.load(f)
        if 'regime_counts' in results:
            elevated = results['regime_counts'].get('HighVol', 0) \
                     + results['regime_counts'].get('Crisis', 0)
            assert elevated > 0, \
                f"Should detect elevated regimes in high-vol data: {results['regime_counts']}"
