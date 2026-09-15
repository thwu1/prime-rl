
"""
Tests for the Market Microstructure Fill Simulation Engine.

Verifies:
1. Order book reconstruction from L2 event data
2. Queue position models (RiskAdverse, ProbQueue+Power, ProbQueue+Log)
3. Fill determination and P&L computation
4. Integration test on full simulation output
"""

import sys
import os
import json
import math
import numpy as np
import pytest

sys.path.insert(0, '/app')

# ---- Event flags ----
DEPTH_EVENT = 1
TRADE_EVENT = 2
DEPTH_SNAPSHOT_EVENT = 4
EXCH_EVENT = 1 << 31
LOCAL_EVENT = 1 << 30
BUY_EVENT = 1 << 29
SELL_EVENT = 1 << 28

EVENT_DTYPE = np.dtype([
    ('ev', 'u8'), ('exch_ts', 'i8'), ('local_ts', 'i8'), ('px', 'f8'),
    ('qty', 'f8'), ('order_id', 'u8'), ('ival', 'i8'), ('fval', 'f8')
])

T0 = 1_000_000_000_000
S = 1_000_000_000


def _mk(flags, px, qty, ts_offset=0):
    t = T0 + ts_offset
    return np.array([(flags, t, t + 5_000_000, float(px), float(qty), 0, 0, 0.0)],
                    dtype=EVENT_DTYPE)[0]


# =========================================================================
# Test 1: Order book snapshot construction
# =========================================================================
class TestOrderBook:
    def test_snapshot_bbo(self):
        from microstructure import OrderBook
        ob = OrderBook(tick_size=1.0, lot_size=1.0)
        SB = DEPTH_SNAPSHOT_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT
        SS = DEPTH_SNAPSHOT_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT
        ob.process_event(_mk(SB, 99, 50))
        ob.process_event(_mk(SB, 98, 30))
        ob.process_event(_mk(SS, 101, 40))
        ob.process_event(_mk(SS, 102, 20))

        assert ob.best_bid == pytest.approx(99.0)
        assert ob.best_ask == pytest.approx(101.0)
        assert ob.best_bid_qty == pytest.approx(50.0)
        assert ob.best_ask_qty == pytest.approx(40.0)

    def test_depth_update(self):
        from microstructure import OrderBook
        ob = OrderBook(tick_size=1.0, lot_size=1.0)
        SB = DEPTH_SNAPSHOT_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT
        SS = DEPTH_SNAPSHOT_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT
        DB = DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT

        ob.process_event(_mk(SB, 99, 50))
        ob.process_event(_mk(SB, 98, 30))
        ob.process_event(_mk(SS, 101, 40))

        # Clear top bid level
        ob.process_event(_mk(DB, 99, 0))
        assert ob.best_bid == pytest.approx(98.0)
        assert ob.best_bid_qty == pytest.approx(30.0)

    def test_qty_at_price(self):
        from microstructure import OrderBook
        ob = OrderBook(tick_size=1.0, lot_size=1.0)
        SB = DEPTH_SNAPSHOT_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT
        SS = DEPTH_SNAPSHOT_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT

        ob.process_event(_mk(SB, 99, 50))
        ob.process_event(_mk(SS, 101, 40))

        assert ob.bid_qty_at(99.0) == pytest.approx(50.0)
        assert ob.bid_qty_at(100.0) == pytest.approx(0.0)
        assert ob.ask_qty_at(101.0) == pytest.approx(40.0)
        assert ob.ask_qty_at(100.0) == pytest.approx(0.0)

    def test_process_event_returns_prev_new(self):
        from microstructure import OrderBook
        ob = OrderBook(tick_size=1.0, lot_size=1.0)
        SB = DEPTH_SNAPSHOT_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT
        DB = DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT

        prev, new = ob.process_event(_mk(SB, 99, 50))
        assert prev == pytest.approx(0.0)
        assert new == pytest.approx(50.0)

        prev, new = ob.process_event(_mk(DB, 99, 30))
        assert prev == pytest.approx(50.0)
        assert new == pytest.approx(30.0)

    def test_trade_does_not_change_book(self):
        from microstructure import OrderBook
        ob = OrderBook(tick_size=1.0, lot_size=1.0)
        SB = DEPTH_SNAPSHOT_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT
        SS = DEPTH_SNAPSHOT_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT
        TS = TRADE_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT

        ob.process_event(_mk(SB, 99, 50))
        ob.process_event(_mk(SS, 101, 40))
        ob.process_event(_mk(TS, 99, 10))

        assert ob.bid_qty_at(99.0) == pytest.approx(50.0)
        assert ob.best_bid == pytest.approx(99.0)


# =========================================================================
# Test 2: RiskAdverse queue model
# =========================================================================
class TestRiskAdverseModel:
    def test_basic_fill(self):
        """Trade consumes past queue position -> fill."""
        from microstructure import RiskAdverseQueueModel
        m = RiskAdverseQueueModel(lot_size=1.0)
        s = m.new_order(50.0)
        m.trade(s, 55.0)
        qty = m.is_filled(s)
        assert qty == pytest.approx(5.0)

    def test_no_fill(self):
        """Trade does not consume full queue -> no fill."""
        from microstructure import RiskAdverseQueueModel
        m = RiskAdverseQueueModel(lot_size=1.0)
        s = m.new_order(50.0)
        m.trade(s, 40.0)
        qty = m.is_filled(s)
        assert qty == pytest.approx(0.0)

    def test_depth_clamp(self):
        """Depth decrease clamps front_q_qty."""
        from microstructure import RiskAdverseQueueModel
        m = RiskAdverseQueueModel(lot_size=1.0)
        s = m.new_order(50.0)
        m.trade(s, 10.0)   # front_q = 40
        m.depth(s, 50.0, 30.0)  # clamp to 30
        m.trade(s, 35.0)   # front_q = -5
        qty = m.is_filled(s)
        assert qty == pytest.approx(5.0)

    def test_partial_reset(self):
        """is_filled resets front_q to 0 when exec > 0 but < order qty."""
        from microstructure import RiskAdverseQueueModel
        m = RiskAdverseQueueModel(lot_size=1.0)
        s = m.new_order(10.0)
        m.trade(s, 12.0)         # front_q = -2, exec = 2
        qty = m.is_filled(s)
        assert qty == pytest.approx(2.0)
        # front_q should be reset to 0
        m.trade(s, 5.0)          # front_q = -5
        qty = m.is_filled(s)
        assert qty == pytest.approx(5.0)


# =========================================================================
# Test 3: ProbQueueModel with PowerProbQueueFunc(n=2)
# =========================================================================
class TestProbQueuePowerModel:
    def test_prob_func_values(self):
        from microstructure import power_prob_func
        pf = power_prob_func(2.0)
        # prob(front=40, back=0) should be 0
        assert pf(40.0, 0.0) == pytest.approx(0.0)
        # prob(front=0, back=40) should be 1
        assert pf(0.0, 40.0) == pytest.approx(1.0)
        # prob(front=30, back=30): f(30)/2f(30) = 0.5
        assert pf(30.0, 30.0) == pytest.approx(0.5)
        # prob(front=10, back=20) = 400/(400+100) = 0.8
        assert pf(10.0, 20.0) == pytest.approx(0.8)

    def test_cancellation_adjustment(self):
        """
        Scenario: front_q=13, back=27, chg=18.
        After depth adjustment, front_q should be ~9.612 (not clamped to 20).
        """
        from microstructure import ProbQueueModel, power_prob_func
        m = ProbQueueModel(lot_size=1.0, prob_func=power_prob_func(2.0))
        s = m.new_order(20.0)  # front_q=20, cum=0

        m.trade(s, 5.0)    # front_q=15, cum=5
        m.depth(s, 20.0, 40.0)  # chg=20-40-5=-25, neg -> clamp min(15,40)=15; cum=0

        m.trade(s, 2.0)    # front_q=13, cum=2
        m.depth(s, 40.0, 20.0)  # chg=40-20-2=18, pos -> prob adjustment
        # front=13, back=27
        # prob = 729/(729+169) = 729/898 ≈ 0.81180
        # est = 13 - 0.1882*18 + min(27-14.612,0) = 13-3.388+0 = 9.612
        # front_q = min(9.612, 20) = 9.612

        # Now trade should fill differently from RiskAdverse
        m.trade(s, 12.0)   # front_q = 9.612-12 = -2.388
        qty = m.is_filled(s)
        assert qty == pytest.approx(2.0)  # round(2.388) = 2

    def test_negative_chg_no_change(self):
        """When depth increases (chg < 0), front_q doesn't decrease."""
        from microstructure import ProbQueueModel, power_prob_func
        m = ProbQueueModel(lot_size=1.0, prob_func=power_prob_func(2.0))
        s = m.new_order(50.0)
        m.depth(s, 50.0, 80.0)  # chg = 50-80-0 = -30, negative
        # front_q should be min(50, 80) = 50
        m.trade(s, 50.0)
        qty = m.is_filled(s)
        assert qty == pytest.approx(0.0)  # front_q was 50, now 0, exec=0


# =========================================================================
# Test 4: ProbQueueModel with LogProbQueueFunc
# =========================================================================
class TestProbQueueLogModel:
    def test_log_prob_func_values(self):
        from microstructure import log_prob_func
        lf = log_prob_func()
        assert lf(0.0, 0.0) == pytest.approx(0.0)
        assert lf(0.0, 10.0) == pytest.approx(1.0)
        assert lf(10.0, 0.0) == pytest.approx(0.0)
        # prob(10, 10) = ln(11)/(ln(11)+ln(11)) = 0.5
        assert lf(10.0, 10.0) == pytest.approx(0.5)

    def test_more_aggressive_than_power(self):
        """
        With front=13, back=27, log model estimates higher prob (more behind)
        than power(2), leading to lower front_q.
        """
        from microstructure import ProbQueueModel, power_prob_func, log_prob_func

        # Power model
        mp = ProbQueueModel(lot_size=1.0, prob_func=power_prob_func(2.0))
        sp = mp.new_order(20.0)
        mp.trade(sp, 5.0)
        mp.depth(sp, 20.0, 40.0)
        mp.trade(sp, 2.0)
        mp.depth(sp, 40.0, 20.0)

        # Log model
        ml = ProbQueueModel(lot_size=1.0, prob_func=log_prob_func())
        sl = ml.new_order(20.0)
        ml.trade(sl, 5.0)
        ml.depth(sl, 20.0, 40.0)
        ml.trade(sl, 2.0)
        ml.depth(sl, 40.0, 20.0)

        # Both had front=13, back=27 before the second depth
        # Power: front_q ≈ 9.612
        # Log: prob=ln(28)/(ln(28)+ln(14))≈0.558
        #   est = 13 - 0.442*18 + 0 = 5.045
        #   front_q = min(5.045, 20) = 5.045

        # After trade of 12:
        mp.trade(sp, 12.0)
        ml.trade(sl, 12.0)
        pq = mp.is_filled(sp)
        lq = ml.is_filled(sl)

        # Power: front_q=-2.388, exec=round(2.388)=2
        assert pq == pytest.approx(2.0)
        # Log: front_q=-6.955, exec=round(6.955)=7
        assert lq == pytest.approx(7.0)


# =========================================================================
# Test 5: Full simulation results.json
# =========================================================================
class TestResultsIntegration:
    @pytest.fixture(scope="class")
    def results(self):
        path = '/app/results.json'
        assert os.path.exists(path), "results.json not found at /app/results.json"
        with open(path) as f:
            return json.load(f)

    def _find_order(self, fills, oid):
        for f in fills:
            if f["order_id"] == oid:
                return f
        pytest.fail(f"Order {oid} not found in fills")

    # ---- RiskAdverse model ----
    def test_risk_adverse_order1(self, results):
        """Buy@99 qty=3: filled at T0+7s via queue."""
        o = self._find_order(results["risk_adverse"]["fills"], 1)
        assert o["filled"] is True
        assert o["fill_time_ns"] == T0 + 7 * S
        assert o["fill_price"] == pytest.approx(99.0)

    def test_risk_adverse_order2(self, results):
        """Sell@101 qty=5: NOT filled (exec=4 < 5, then no more trades)."""
        o = self._find_order(results["risk_adverse"]["fills"], 2)
        assert o["filled"] is False

    def test_risk_adverse_order3(self, results):
        """Buy@98 qty=10: filled at T0+21s via price improvement."""
        o = self._find_order(results["risk_adverse"]["fills"], 3)
        assert o["filled"] is True
        assert o["fill_time_ns"] == T0 + 21 * S
        assert o["fill_price"] == pytest.approx(98.0)

    def test_risk_adverse_order4(self, results):
        """Buy@97 qty=1: NOT filled."""
        o = self._find_order(results["risk_adverse"]["fills"], 4)
        assert o["filled"] is False

    def test_risk_adverse_order5(self, results):
        """Sell@101 qty=3: filled at T0+14s."""
        o = self._find_order(results["risk_adverse"]["fills"], 5)
        assert o["filled"] is True
        assert o["fill_time_ns"] == T0 + 14 * S

    def test_risk_adverse_position(self, results):
        """Position = 3 + 10 - 3 = 10"""
        assert results["risk_adverse"]["position"] == pytest.approx(10.0)

    def test_risk_adverse_balance(self, results):
        """
        Fills: buy 99*3, buy 98*10, sell 101*3.
        Fees: 297*(-0.0001) + 980*(-0.0001) + 303*(-0.0001) = -0.158
        Balance: -297 - 980 + 303 + 0.158 = -973.842
        """
        assert results["risk_adverse"]["balance"] == pytest.approx(-973.842, abs=0.01)

    def test_risk_adverse_fees(self, results):
        assert results["risk_adverse"]["total_fees"] == pytest.approx(-0.158, abs=0.001)

    # ---- ProbQueue Power(2) model ----
    def test_prob_power_order1(self, results):
        """Buy@99 qty=3: filled at T0+6s (earlier than RiskAdverse)."""
        o = self._find_order(results["prob_power_2"]["fills"], 1)
        assert o["filled"] is True
        assert o["fill_time_ns"] == T0 + 6 * S

    def test_prob_power_order2(self, results):
        """Sell@101 qty=5: FILLED at T0+14s (vs NOT filled in RiskAdverse)."""
        o = self._find_order(results["prob_power_2"]["fills"], 2)
        assert o["filled"] is True
        assert o["fill_time_ns"] == T0 + 14 * S

    def test_prob_power_order5(self, results):
        """Sell@101 qty=3: filled at T0+14s."""
        o = self._find_order(results["prob_power_2"]["fills"], 5)
        assert o["filled"] is True
        assert o["fill_time_ns"] == T0 + 14 * S

    def test_prob_power_position(self, results):
        """Position = 3 + 10 - 5 - 3 = 5"""
        assert results["prob_power_2"]["position"] == pytest.approx(5.0)

    def test_prob_power_balance(self, results):
        """
        Fills: buy 99*3, sell 101*5, buy 98*10, sell 101*3.
        Fees: -(0.0297 + 0.0505 + 0.098 + 0.0303) = -0.2085
        Balance: -297 + 505 - 980 + 303 + 0.2085 = -468.7915
        """
        assert results["prob_power_2"]["balance"] == pytest.approx(-468.7915, abs=0.01)

    # ---- ProbQueue Log model ----
    def test_prob_log_order1(self, results):
        """Buy@99 qty=3: filled at T0+5s (earliest of all three models)."""
        o = self._find_order(results["prob_log"]["fills"], 1)
        assert o["filled"] is True
        assert o["fill_time_ns"] == T0 + 5 * S

    def test_prob_log_order2(self, results):
        """Sell@101 qty=5: FILLED at T0+14s."""
        o = self._find_order(results["prob_log"]["fills"], 2)
        assert o["filled"] is True
        assert o["fill_time_ns"] == T0 + 14 * S

    def test_prob_log_order5(self, results):
        """Sell@101 qty=3: filled at T0+13s (earlier than Power and RiskAdverse)."""
        o = self._find_order(results["prob_log"]["fills"], 5)
        assert o["filled"] is True
        assert o["fill_time_ns"] == T0 + 13 * S

    def test_prob_log_position(self, results):
        """Same fills as Power model: position = 5"""
        assert results["prob_log"]["position"] == pytest.approx(5.0)

    # ---- Cross-model differentiation ----
    def test_models_differ_on_fill_timing(self, results):
        """
        Order 1 (buy@99 qty=3) fills at different times:
          LogProb < PowerProb < RiskAdverse
        """
        ra = self._find_order(results["risk_adverse"]["fills"], 1)
        pp = self._find_order(results["prob_power_2"]["fills"], 1)
        pl = self._find_order(results["prob_log"]["fills"], 1)
        assert pl["fill_time_ns"] < pp["fill_time_ns"] < ra["fill_time_ns"]

    def test_models_differ_on_fill_count(self, results):
        """
        RiskAdverse fills 3 orders; ProbQueue models fill 4 orders.
        """
        ra_filled = sum(1 for f in results["risk_adverse"]["fills"] if f["filled"])
        pp_filled = sum(1 for f in results["prob_power_2"]["fills"] if f["filled"])
        pl_filled = sum(1 for f in results["prob_log"]["fills"] if f["filled"])
        assert ra_filled == 3
        assert pp_filled == 4
        assert pl_filled == 4
