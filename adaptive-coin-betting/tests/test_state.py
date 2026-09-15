
import math
import sys
import numpy as np
import pytest

sys.path.insert(0, "/app")


class TestKTBettor:

    def test_import(self):
        from pfol import KTBettor
        kb = KTBettor()
        assert kb.wealth() == 1.0

    def test_bet_range(self):
        from pfol import KTBettor
        kb = KTBettor()
        for c in [0.5, -0.3, 0.7, -0.9, 0.1, -0.5, 0.2, 0.8, -0.4, 0.6]:
            b = kb.bet()
            assert -1.0 <= b <= 1.0, f"Bet {b} out of range"
            kb.update(c)

    def test_wealth_positive(self):
        from pfol import KTBettor
        kb = KTBettor()
        np.random.seed(42)
        coins = np.random.uniform(-1, 1, 200)
        for c in coins:
            kb.update(float(c))
            assert kb.wealth() >= 0, f"Wealth went negative: {kb.wealth()}"

    def test_wealth_balanced_lower_bound(self):
        from pfol import KTBettor
        T = 500
        kb = KTBettor()
        for t in range(T):
            coin = 1.0 if t % 2 == 0 else -1.0
            kb.update(coin)
        w = kb.wealth()
        assert w > 0.01 / math.sqrt(T), (
            f"Wealth {w} too low on balanced sequence of length {T}; "
            f"expected >= O(1/sqrt(T)) ~ {0.01 / math.sqrt(T)}"
        )

    def test_wealth_biased_exponential(self):
        from pfol import KTBettor
        T = 200
        kb = KTBettor()
        for _ in range(T):
            kb.update(0.5)
        w = kb.wealth()
        assert w > T, (
            f"Wealth {w} not growing sufficiently on biased coins (T={T})"
        )

    def test_kt_fraction_formula(self):
        from pfol import KTBettor
        kb = KTBettor()
        assert abs(kb.bet()) < 1e-10, "Initial bet should be 0"
        kb.update(1.0)
        b = kb.bet()
        assert b > 0, f"After +1 coin, bet should be positive, got {b}"
        kb.update(-1.0)
        b = kb.bet()
        assert abs(b) < 0.5, f"After balanced coins, bet magnitude should be small, got {b}"


class TestOneDimOLO:

    def test_import(self):
        from pfol import OneDimOLO
        olo = OneDimOLO(lipschitz=1.0)
        assert isinstance(olo.predict(), float)

    def test_regret_vs_zero(self):
        from pfol import OneDimOLO
        T = 1000
        olo = OneDimOLO(lipschitz=1.0)
        for t in range(T):
            g = 1.0 if t % 2 == 0 else -1.0
            olo.update(g)
        reg = olo.cumulative_regret(0.0)
        assert reg < 50, f"Regret vs 0 = {reg}, expected small"

    def test_regret_bound_nonzero_competitor(self):
        from pfol import OneDimOLO
        T = 2000
        u = 5.0
        olo = OneDimOLO(lipschitz=1.0)
        np.random.seed(123)
        for t in range(T):
            g = np.random.choice([-1.0, 1.0])
            olo.update(float(g))
        reg = olo.cumulative_regret(u)
        theoretical = abs(u) * math.sqrt(T * math.log(abs(u) * math.sqrt(T) + math.e))
        assert reg < 8.0 * theoretical, (
            f"Regret {reg} exceeds 8x theoretical bound {theoretical}"
        )

    def test_predictions_adapt(self):
        from pfol import OneDimOLO
        olo = OneDimOLO(lipschitz=1.0)
        preds = []
        for _ in range(100):
            preds.append(olo.predict())
            olo.update(1.0)
        assert preds[-1] < preds[0], "Predictions should decrease with constant positive gradient"


class TestCoordOCO:

    def test_import(self):
        from pfol import CoordOCO
        oco = CoordOCO(dim=3, lipschitz=1.0)
        pred = oco.predict()
        assert len(pred) == 3

    def test_regret_decomposition(self):
        from pfol import CoordOCO, OneDimOLO
        dim = 4
        T = 300
        oco = CoordOCO(dim=dim, lipschitz=1.0)
        indep = [OneDimOLO(lipschitz=1.0) for _ in range(dim)]

        np.random.seed(77)
        for t in range(T):
            grad = list(np.random.uniform(-1, 1, dim))
            oco.update(grad)
            for d_i in range(dim):
                indep[d_i].update(grad[d_i])

        competitor = [1.0, -2.0, 0.5, 3.0]
        reg_oco = oco.cumulative_regret(competitor)
        reg_sum = sum(indep[d_i].cumulative_regret(competitor[d_i]) for d_i in range(dim))
        assert abs(reg_oco - reg_sum) < 1e-6, (
            f"CoordOCO regret {reg_oco} != sum of 1-d regrets {reg_sum}"
        )

    def test_regret_scaling(self):
        from pfol import CoordOCO
        dim = 5
        T = 1000
        oco = CoordOCO(dim=dim, lipschitz=1.0)
        np.random.seed(999)
        for t in range(T):
            grad = list(np.random.choice([-1.0, 1.0], dim))
            oco.update(grad)
        competitor = [2.0] * dim
        reg = oco.cumulative_regret(competitor)
        bound = sum(
            abs(competitor[i]) * math.sqrt(T * math.log(abs(competitor[i]) * math.sqrt(T) + math.e))
            for i in range(dim)
        )
        assert reg < 10.0 * bound, f"Regret {reg} too large vs bound {bound}"


class TestCBCE:

    def test_import(self):
        from pfol import CBCE
        cb = CBCE(dim=2, lipschitz=1.0)
        pred = cb.predict()
        assert len(pred) == 2

    def test_active_learners_logarithmic(self):
        from pfol import CBCE
        cb = CBCE(dim=2, lipschitz=1.0)
        np.random.seed(55)
        for t in range(1, 2001):
            cb.update(list(np.random.choice([-1.0, 1.0], 2)))
            n_active = cb.num_active_learners()
            max_allowed = 5 * (math.log2(t + 1) + 1) + 5
            assert n_active <= max_allowed, (
                f"At round {t}, {n_active} active learners exceeds "
                f"O(log t) bound of {max_allowed}"
            )

    def test_strongly_adaptive_regret(self):
        from pfol import CBCE
        dim = 2
        T = 4000
        cb = CBCE(dim=dim, lipschitz=1.0)

        np.random.seed(2024)
        grads = []
        for phase in range(T // 500):
            direction = np.random.choice([-1.0, 1.0], dim)
            for _ in range(500):
                noise = np.random.uniform(-0.1, 0.1, dim)
                grads.append(list(direction + noise))

        for g in grads:
            g_clipped = [max(-1.0, min(1.0, x)) for x in g]
            cb.update(g_clipped)

        test_intervals = [
            (0, 500),
            (500, 1000),
            (1000, 2000),
            (2000, 4000),
            (1500, 2500),
        ]
        competitor = [0.0] * dim

        for (s, e) in test_intervals:
            n = e - s
            reg = cb.interval_regret(s, e, competitor)
            bound = 50.0 * math.sqrt(n) * (math.log(T + 1) ** 2)
            assert reg < bound, (
                f"Interval [{s},{e}): regret {reg:.2f} exceeds strongly-adaptive "
                f"bound {bound:.2f} (n={n}, T={T})"
            )

    def test_interval_regret_nonzero_competitor(self):
        from pfol import CBCE
        dim = 3
        T = 2000
        cb = CBCE(dim=dim, lipschitz=1.0)

        np.random.seed(888)
        for t in range(T):
            g = list(np.random.uniform(-1, 1, dim))
            cb.update(g)

        s, e = 500, 700
        n = e - s
        competitor = [1.0, -1.0, 0.5]
        reg = cb.interval_regret(s, e, competitor)
        u_norm = math.sqrt(sum(c ** 2 for c in competitor))
        bound = 100.0 * u_norm * math.sqrt(n) * (math.log(T + 1) ** 2)
        assert reg < bound, (
            f"Interval [{s},{e}): regret {reg:.2f} exceeds bound {bound:.2f}"
        )

    def test_full_horizon_regret(self):
        from pfol import CBCE
        dim = 2
        T = 1000
        cb = CBCE(dim=dim, lipschitz=1.0)

        np.random.seed(321)
        for t in range(T):
            g = list(np.random.choice([-1.0, 1.0], dim))
            cb.update(g)

        competitor = [0.0, 0.0]
        reg = cb.interval_regret(0, T, competitor)
        bound = 100.0 * math.sqrt(T) * (math.log(T + 1) ** 2)
        assert reg < bound, (
            f"Full-horizon regret {reg:.2f} exceeds bound {bound:.2f}"
        )

    def test_predictions_are_finite(self):
        from pfol import CBCE
        cb = CBCE(dim=3, lipschitz=1.0)
        np.random.seed(111)
        for t in range(500):
            pred = cb.predict()
            for p in pred:
                assert math.isfinite(p), f"Non-finite prediction at round {t}: {pred}"
            cb.update(list(np.random.uniform(-1, 1, 3)))


class TestBoundsChecker:

    def test_import_and_load(self):
        from pfol import BoundsChecker
        bc = BoundsChecker()

    def test_generate_deterministic(self):
        from pfol import BoundsChecker
        bc = BoundsChecker()
        s1 = bc.generate_sequence(42, 100, 2)
        s2 = bc.generate_sequence(42, 100, 2)
        assert len(s1) == 100
        assert len(s1[0]) == 2
        for t in range(100):
            for d in range(2):
                assert s1[t][d] == s2[t][d], f"Mismatch at t={t}, d={d}"

    def test_sequence_bounds(self):
        from pfol import BoundsChecker
        bc = BoundsChecker()
        seq = bc.generate_sequence(99, 500, 3)
        for t in range(500):
            for d in range(3):
                assert -1.0 <= seq[t][d] <= 1.0, (
                    f"Value {seq[t][d]} out of [-1,1] at t={t}, d={d}"
                )

    def test_olo_bound_matches_c(self):
        from pfol import BoundsChecker
        bc = BoundsChecker()
        b = bc.olo_bound(5.0, 1000, 1.0)
        expected = 5.0 * math.sqrt(1000 * math.log(5 * math.sqrt(1000) + math.e))
        assert abs(b - expected) < 1e-4, f"olo_bound {b} != expected {expected}"

    def test_adaptive_bound_matches_c(self):
        from pfol import BoundsChecker
        bc = BoundsChecker()
        b = bc.adaptive_bound(500, 4000)
        expected = 50.0 * math.sqrt(500) * (math.log(4001)) ** 2
        assert abs(b - expected) < 1e-4, f"adaptive_bound {b} != expected {expected}"

    def test_wealth_bound_matches_c(self):
        from pfol import BoundsChecker
        bc = BoundsChecker()
        b = bc.wealth_bound(500)
        expected = 0.01 / math.sqrt(500)
        assert abs(b - expected) < 1e-8, f"wealth_bound {b} != expected {expected}"

    def test_olo_with_adversarial_sequence(self):
        from pfol import BoundsChecker, OneDimOLO
        bc = BoundsChecker()
        seq = bc.generate_sequence(99, 1000, 1)
        olo = OneDimOLO(lipschitz=1.0)
        for t in range(1000):
            olo.update(seq[t][0])
        competitor = 3.0
        reg = olo.cumulative_regret(competitor)
        bound = bc.olo_bound(competitor, 1000, 1.0)
        assert reg < 8.0 * bound, f"regret {reg} > 8*bound {8 * bound}"

    def test_cbce_with_adversarial_sequence(self):
        from pfol import BoundsChecker, CBCE
        bc = BoundsChecker()
        dim = 2
        T = 2000
        seq = bc.generate_sequence(77, T, dim)
        cb = CBCE(dim=dim, lipschitz=1.0)
        for t in range(T):
            cb.update(seq[t])
        competitor = [0.0] * dim
        for s, e in [(0, 500), (500, 1000), (1000, 2000)]:
            n = e - s
            reg = cb.interval_regret(s, e, competitor)
            bound = bc.adaptive_bound(n, T)
            assert reg < bound, f"[{s},{e}): regret {reg} > bound {bound}"
