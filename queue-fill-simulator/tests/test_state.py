#!/usr/bin/env python3
"""
Tests for the queue position fill simulator.
Includes a complete reference implementation for verification.
"""

import pytest
import subprocess
import json
import numpy as np
import math
import os

# ======== Event Constants ========
DEPTH_EVENT = 1
TRADE_EVENT = 2
DEPTH_CLEAR_EVENT = 3
DEPTH_SNAPSHOT_EVENT = 4
BUY_EVENT = 1 << 29
SELL_EVENT = 1 << 28

EVENT_DTYPE = np.dtype([
    ('ev', '<u8'), ('exch_ts', '<i8'), ('local_ts', '<i8'), ('px', '<f8'),
    ('qty', '<f8'), ('order_id', '<u8'), ('ival', '<i8'), ('fval', '<f8')
], align=True)


def _base_type(ev):
    return int(ev) & 0xF


def _has_flag(ev, flag):
    return (int(ev) & flag) != 0


# ======== Reference Probability Functions ========

def _power_prob(n):
    def prob(front, back):
        fb = back ** n
        ff = front ** n
        d = fb + ff
        return fb / d if d != 0 else 0.0
    return prob


def _log_prob():
    def prob(front, back):
        fb = math.log(1.0 + back)
        ff = math.log(1.0 + front)
        d = fb + ff
        return fb / d if d != 0 else 0.0
    return prob


def _log_prob2():
    def prob(front, back):
        fb = math.log(1.0 + back)
        ft = math.log(1.0 + back + front)
        return fb / ft if ft != 0 else 0.0
    return prob


def _power_prob3(n):
    def prob(front, back):
        d = front + back
        if d == 0:
            return 0.0
        return 1.0 - (front / d) ** n
    return prob


# ======== Reference Queue State ========

class _QState:
    __slots__ = ['fqq', 'ctq', 'ls', 'filled', 'fei', 'fts']

    def __init__(self, fqq, ls):
        self.fqq = fqq
        self.ctq = 0.0
        self.ls = ls
        self.filled = False
        self.fei = None
        self.fts = None

    def chk(self, ei, ts):
        if self.filled:
            return
        if int(round(-self.fqq / self.ls)) > 0:
            self.filled = True
            self.fei = ei
            self.fts = int(ts)
            self.fqq = 0.0

    def ff(self, ei, ts):
        if self.filled:
            return
        self.filled = True
        self.fei = ei
        self.fts = int(ts)
        self.fqq = 0.0


class _RAModel:
    name = "risk_adverse"
    def trade(self, s, q):
        if not s.filled:
            s.fqq -= q
    def depth(self, s, pq, nq):
        if not s.filled:
            s.fqq = min(s.fqq, nq)


class _PQModel:
    def __init__(self, name, pf):
        self.name = name
        self.pf = pf
    def trade(self, s, q):
        if s.filled:
            return
        s.fqq -= q
        s.ctq += q
    def depth(self, s, pq, nq):
        if s.filled:
            return
        chg = pq - nq - s.ctq
        s.ctq = 0.0
        if chg < 0.0:
            s.fqq = min(s.fqq, nq)
            return
        front = s.fqq
        back = pq - front
        p = self.pf(front, back)
        if math.isinf(p):
            p = 1.0
        ef = front - (1.0 - p) * chg + min(back - p * chg, 0.0)
        s.fqq = min(ef, nq)


def _ref_sim():
    """Run reference simulation and return results dict."""
    events = np.fromfile('/app/data/events.bin', dtype=EVENT_DTYPE)
    with open('/app/data/orders.json') as f:
        orders = json.load(f)
    with open('/app/data/config.json') as f:
        config = json.load(f)

    ts_ = config['tick_size']
    ls_ = config['lot_size']

    mdls = [
        _RAModel(),
        _PQModel("power_prob_n2", _power_prob(2.0)),
        _PQModel("log_prob", _log_prob()),
        _PQModel("log_prob2", _log_prob2()),
        _PQModel("power_prob3_n3", _power_prob3(3.0)),
    ]

    bb = {}
    ab = {}
    ost = {}
    osp = {o['id']: o for o in orders}
    placed = set()
    tte = 0
    tde = 0

    for ei in range(len(events)):
        ev = int(events[ei]['ev'])
        ets = int(events[ei]['exch_ts'])
        px = float(events[ei]['px'])
        qty = float(events[ei]['qty'])
        bt = _base_type(ev)
        ib = _has_flag(ev, BUY_EVENT)
        ise = _has_flag(ev, SELL_EVENT)
        pt = int(round(px / ts_))

        for o in orders:
            oid = o['id']
            if oid not in placed and ets >= o['place_at_ts']:
                placed.add(oid)
                bq = bb.get(o['price_tick'], 0.0) if o['side'] == 'buy' else ab.get(o['price_tick'], 0.0)
                ost[oid] = {m.name: _QState(bq, ls_) for m in mdls}

        if bt == DEPTH_CLEAR_EVENT:
            if ib:
                bb.clear()
            elif ise:
                ab.clear()
        elif bt == DEPTH_SNAPSHOT_EVENT:
            if ib:
                bb[pt] = qty
            elif ise:
                ab[pt] = qty
        elif bt == DEPTH_EVENT:
            tde += 1
            if ib:
                prev = bb.get(pt, 0.0)
                if qty <= 0:
                    bb.pop(pt, None)
                else:
                    bb[pt] = qty
                for oid in ost:
                    if osp[oid]['side'] == 'buy' and osp[oid]['price_tick'] == pt:
                        for m in mdls:
                            s = ost[oid][m.name]
                            m.depth(s, prev, qty)
                            s.chk(ei, ets)
            elif ise:
                prev = ab.get(pt, 0.0)
                if qty <= 0:
                    ab.pop(pt, None)
                else:
                    ab[pt] = qty
                for oid in ost:
                    if osp[oid]['side'] == 'sell' and osp[oid]['price_tick'] == pt:
                        for m in mdls:
                            s = ost[oid][m.name]
                            m.depth(s, prev, qty)
                            s.chk(ei, ets)
        elif bt == TRADE_EVENT:
            tte += 1
            if ise:
                for oid in ost:
                    sp = osp[oid]
                    if sp['side'] == 'buy':
                        if sp['price_tick'] > pt:
                            for m in mdls:
                                ost[oid][m.name].ff(ei, ets)
                        elif sp['price_tick'] == pt:
                            for m in mdls:
                                s = ost[oid][m.name]
                                m.trade(s, qty)
                                s.chk(ei, ets)
            elif ib:
                for oid in ost:
                    sp = osp[oid]
                    if sp['side'] == 'sell':
                        if sp['price_tick'] < pt:
                            for m in mdls:
                                ost[oid][m.name].ff(ei, ets)
                        elif sp['price_tick'] == pt:
                            for m in mdls:
                                s = ost[oid][m.name]
                                m.trade(s, qty)
                                s.chk(ei, ets)

    bbt = max(bb.keys()) if bb else None
    bat = min(ab.keys()) if ab else None

    results = {
        "orders": [],
        "book_state": {
            "final_best_bid_tick": bbt,
            "final_best_ask_tick": bat,
            "final_best_bid_qty": round(bb.get(bbt, 0.0), 6) if bbt is not None else 0.0,
            "final_best_ask_qty": round(ab.get(bat, 0.0), 6) if bat is not None else 0.0,
            "total_trade_events": tte,
            "total_depth_events": tde,
        }
    }

    for o in orders:
        oid = o['id']
        if oid not in ost:
            continue
        or_ = {
            "order_id": oid,
            "side": o['side'],
            "price_tick": o['price_tick'],
            "qty": o['qty'],
            "models": {}
        }
        for m in mdls:
            s = ost[oid][m.name]
            or_["models"][m.name] = {
                "filled": s.filled,
                "fill_event_idx": s.fei,
                "fill_exch_ts": s.fts,
                "final_front_q_qty": round(s.fqq, 6)
            }
        results["orders"].append(or_)

    return results


def _ref_analysis(results):
    """Compute reference analysis from results."""
    model_names = list(results["orders"][0]["models"].keys())

    fill_counts = {}
    for m in model_names:
        fill_counts[m] = sum(1 for o in results["orders"] if o["models"][m]["filled"])

    ranking = sorted(model_names, key=lambda m: (-fill_counts[m], m))

    sorted_models = sorted(model_names)
    pairwise = {}
    for i in range(len(sorted_models)):
        for j in range(i + 1, len(sorted_models)):
            a, b = sorted_models[i], sorted_models[j]
            key = f"{a}__{b}"
            count = sum(
                1 for o in results["orders"]
                if o["models"][a]["filled"] != o["models"][b]["filled"]
            )
            pairwise[key] = count

    sensitive = sorted([
        o["order_id"] for o in results["orders"]
        if len(set(o["models"][m]["filled"] for m in model_names)) > 1
    ])

    most_conservative = sorted(model_names, key=lambda m: (fill_counts[m], m))[0]
    most_aggressive = sorted(model_names, key=lambda m: (-fill_counts[m], m))[0]

    return {
        "fill_counts": fill_counts,
        "aggressiveness_ranking": ranking,
        "pairwise_disagreements": pairwise,
        "model_sensitive_orders": sensitive,
        "most_conservative_model": most_conservative,
        "most_aggressive_model": most_aggressive,
    }


# ======== Fixtures ========

@pytest.fixture(scope="session")
def student_results():
    """Run student's solution and load results."""
    result = subprocess.run(
        ['python3', '/app/fill_simulator.py'],
        cwd='/app',
        capture_output=True,
        text=True,
        timeout=120
    )
    assert result.returncode == 0, (
        f"fill_simulator.py failed with exit code {result.returncode}.\n"
        f"stderr: {result.stderr[:2000]}\nstdout: {result.stdout[:1000]}"
    )
    assert os.path.exists('/app/results.json'), "results.json was not created"
    with open('/app/results.json') as f:
        return json.load(f)


@pytest.fixture(scope="session")
def student_analysis(student_results):
    """Load student's analysis (depends on student_results to ensure subprocess ran)."""
    assert os.path.exists('/app/analysis.json'), "analysis.json was not created"
    with open('/app/analysis.json') as f:
        return json.load(f)


@pytest.fixture(scope="session")
def reference_results():
    """Compute reference results."""
    return _ref_sim()


@pytest.fixture(scope="session")
def reference_analysis(reference_results):
    """Compute reference analysis."""
    return _ref_analysis(reference_results)


# ======== Tests ========

class TestOutputFormat:
    def test_top_level_keys(self, student_results):
        assert "orders" in student_results, "Missing 'orders' key"
        assert "book_state" in student_results, "Missing 'book_state' key"

    def test_order_count(self, student_results):
        assert len(student_results["orders"]) == 8, \
            f"Expected 8 orders, got {len(student_results['orders'])}"

    def test_model_names(self, student_results):
        expected_models = {"risk_adverse", "power_prob_n2", "log_prob",
                           "log_prob2", "power_prob3_n3"}
        for order in student_results["orders"]:
            assert "models" in order, f"Order {order.get('order_id')} missing 'models'"
            actual_models = set(order["models"].keys())
            assert actual_models == expected_models, \
                f"Order {order.get('order_id')}: expected models {expected_models}, got {actual_models}"

    def test_order_fields(self, student_results):
        for order in student_results["orders"]:
            assert "order_id" in order
            assert "side" in order
            assert "price_tick" in order
            assert "qty" in order
            for mname, mdata in order["models"].items():
                assert "filled" in mdata, f"Missing 'filled' in {mname}"
                assert "fill_event_idx" in mdata, f"Missing 'fill_event_idx' in {mname}"
                assert "fill_exch_ts" in mdata, f"Missing 'fill_exch_ts' in {mname}"
                assert "final_front_q_qty" in mdata, f"Missing 'final_front_q_qty' in {mname}"

    def test_book_state_fields(self, student_results):
        bs = student_results["book_state"]
        for key in ["final_best_bid_tick", "final_best_ask_tick",
                     "final_best_bid_qty", "final_best_ask_qty",
                     "total_trade_events", "total_depth_events"]:
            assert key in bs, f"Missing book_state key: {key}"


class TestBookState:
    def test_best_bid_tick(self, student_results, reference_results):
        assert student_results["book_state"]["final_best_bid_tick"] == \
               reference_results["book_state"]["final_best_bid_tick"]

    def test_best_ask_tick(self, student_results, reference_results):
        assert student_results["book_state"]["final_best_ask_tick"] == \
               reference_results["book_state"]["final_best_ask_tick"]

    def test_best_bid_qty(self, student_results, reference_results):
        s = student_results["book_state"]["final_best_bid_qty"]
        r = reference_results["book_state"]["final_best_bid_qty"]
        assert abs(s - r) < 1e-3, f"Best bid qty: {s} vs reference {r}"

    def test_best_ask_qty(self, student_results, reference_results):
        s = student_results["book_state"]["final_best_ask_qty"]
        r = reference_results["book_state"]["final_best_ask_qty"]
        assert abs(s - r) < 1e-3, f"Best ask qty: {s} vs reference {r}"

    def test_trade_event_count(self, student_results, reference_results):
        assert student_results["book_state"]["total_trade_events"] == \
               reference_results["book_state"]["total_trade_events"]

    def test_depth_event_count(self, student_results, reference_results):
        assert student_results["book_state"]["total_depth_events"] == \
               reference_results["book_state"]["total_depth_events"]


class TestFillDeterminations:
    """Verify fill/no-fill for every order under every model."""

    def test_risk_adverse_fills(self, student_results, reference_results):
        for so, ro in zip(student_results["orders"], reference_results["orders"]):
            sm = so["models"]["risk_adverse"]
            rm = ro["models"]["risk_adverse"]
            assert sm["filled"] == rm["filled"], \
                f"Order {so['order_id']} risk_adverse: filled={sm['filled']} expected={rm['filled']}"

    def test_power_prob_n2_fills(self, student_results, reference_results):
        for so, ro in zip(student_results["orders"], reference_results["orders"]):
            sm = so["models"]["power_prob_n2"]
            rm = ro["models"]["power_prob_n2"]
            assert sm["filled"] == rm["filled"], \
                f"Order {so['order_id']} power_prob_n2: filled={sm['filled']} expected={rm['filled']}"

    def test_log_prob_fills(self, student_results, reference_results):
        for so, ro in zip(student_results["orders"], reference_results["orders"]):
            sm = so["models"]["log_prob"]
            rm = ro["models"]["log_prob"]
            assert sm["filled"] == rm["filled"], \
                f"Order {so['order_id']} log_prob: filled={sm['filled']} expected={rm['filled']}"

    def test_log_prob2_fills(self, student_results, reference_results):
        for so, ro in zip(student_results["orders"], reference_results["orders"]):
            sm = so["models"]["log_prob2"]
            rm = ro["models"]["log_prob2"]
            assert sm["filled"] == rm["filled"], \
                f"Order {so['order_id']} log_prob2: filled={sm['filled']} expected={rm['filled']}"

    def test_power_prob3_n3_fills(self, student_results, reference_results):
        for so, ro in zip(student_results["orders"], reference_results["orders"]):
            sm = so["models"]["power_prob3_n3"]
            rm = ro["models"]["power_prob3_n3"]
            assert sm["filled"] == rm["filled"], \
                f"Order {so['order_id']} power_prob3_n3: filled={sm['filled']} expected={rm['filled']}"


class TestFillTimestamps:
    """Verify fill timestamps match for filled orders."""

    def test_fill_timestamps_match(self, student_results, reference_results):
        for so, ro in zip(student_results["orders"], reference_results["orders"]):
            for mname in ro["models"]:
                rm = ro["models"][mname]
                sm = so["models"][mname]
                if rm["filled"]:
                    assert sm["fill_exch_ts"] == rm["fill_exch_ts"], \
                        f"Order {so['order_id']} {mname}: " \
                        f"fill_ts={sm['fill_exch_ts']} expected={rm['fill_exch_ts']}"

    def test_fill_event_indices_match(self, student_results, reference_results):
        for so, ro in zip(student_results["orders"], reference_results["orders"]):
            for mname in ro["models"]:
                rm = ro["models"][mname]
                sm = so["models"][mname]
                if rm["filled"]:
                    assert sm["fill_event_idx"] == rm["fill_event_idx"], \
                        f"Order {so['order_id']} {mname}: " \
                        f"fill_idx={sm['fill_event_idx']} expected={rm['fill_event_idx']}"


class TestQueuePositions:
    """Verify final queue positions for unfilled orders."""

    def test_unfilled_queue_positions(self, student_results, reference_results):
        for so, ro in zip(student_results["orders"], reference_results["orders"]):
            for mname in ro["models"]:
                rm = ro["models"][mname]
                sm = so["models"][mname]
                if not rm["filled"]:
                    diff = abs(sm["final_front_q_qty"] - rm["final_front_q_qty"])
                    assert diff < 1e-3, \
                        f"Order {so['order_id']} {mname}: " \
                        f"front_q_qty={sm['final_front_q_qty']:.6f} " \
                        f"expected={rm['final_front_q_qty']:.6f} diff={diff:.6f}"

    def test_filled_orders_have_zero_front(self, student_results):
        for order in student_results["orders"]:
            for mname, mdata in order["models"].items():
                if mdata["filled"]:
                    assert mdata["final_front_q_qty"] == 0.0, \
                        f"Order {order['order_id']} {mname}: filled but front_q_qty != 0"


class TestModelConsistency:
    """Verify inter-model consistency properties."""

    def test_risk_adverse_most_conservative(self, student_results):
        """If risk_adverse fills, all ProbQueue models must also fill."""
        prob_models = ["power_prob_n2", "log_prob", "log_prob2", "power_prob3_n3"]
        for order in student_results["orders"]:
            ra = order["models"]["risk_adverse"]
            if ra["filled"]:
                for pm in prob_models:
                    assert order["models"][pm]["filled"], \
                        f"Order {order['order_id']}: risk_adverse filled but {pm} did not"

    def test_filled_null_consistency(self, student_results):
        """If filled, fill_event_idx and fill_exch_ts must be non-null. If not filled, must be null."""
        for order in student_results["orders"]:
            for mname, mdata in order["models"].items():
                if mdata["filled"]:
                    assert mdata["fill_event_idx"] is not None, \
                        f"Order {order['order_id']} {mname}: filled but fill_event_idx is null"
                    assert mdata["fill_exch_ts"] is not None, \
                        f"Order {order['order_id']} {mname}: filled but fill_exch_ts is null"
                else:
                    assert mdata["fill_event_idx"] is None, \
                        f"Order {order['order_id']} {mname}: not filled but fill_event_idx is not null"
                    assert mdata["fill_exch_ts"] is None, \
                        f"Order {order['order_id']} {mname}: not filled but fill_exch_ts is not null"

    def test_fill_timestamps_positive(self, student_results):
        """Fill timestamps must be positive integers."""
        for order in student_results["orders"]:
            for mname, mdata in order["models"].items():
                if mdata["filled"]:
                    assert isinstance(mdata["fill_exch_ts"], int), \
                        f"Order {order['order_id']} {mname}: fill_exch_ts is not int"
                    assert mdata["fill_exch_ts"] > 0
                    assert isinstance(mdata["fill_event_idx"], int), \
                        f"Order {order['order_id']} {mname}: fill_event_idx is not int"
                    assert mdata["fill_event_idx"] >= 0


class TestAnalysisFormat:
    """Verify analysis.json structure."""

    def test_analysis_exists(self, student_analysis):
        assert student_analysis is not None, "analysis.json could not be loaded"

    def test_analysis_top_level_keys(self, student_analysis):
        required = {"fill_counts", "aggressiveness_ranking", "pairwise_disagreements",
                     "model_sensitive_orders", "most_conservative_model", "most_aggressive_model"}
        actual = set(student_analysis.keys())
        missing = required - actual
        assert not missing, f"Missing analysis keys: {missing}"

    def test_fill_counts_has_all_models(self, student_analysis):
        expected = {"risk_adverse", "power_prob_n2", "log_prob", "log_prob2", "power_prob3_n3"}
        actual = set(student_analysis["fill_counts"].keys())
        assert actual == expected, f"fill_counts models: {actual} != {expected}"

    def test_ranking_length(self, student_analysis):
        assert len(student_analysis["aggressiveness_ranking"]) == 5, \
            f"Expected 5 models in ranking, got {len(student_analysis['aggressiveness_ranking'])}"

    def test_pairwise_key_count(self, student_analysis):
        assert len(student_analysis["pairwise_disagreements"]) == 10, \
            f"Expected 10 pairwise entries (C(5,2)), got {len(student_analysis['pairwise_disagreements'])}"


class TestAnalysisValues:
    """Verify analysis.json computed values."""

    def test_fill_counts(self, student_analysis, reference_analysis):
        for model, count in reference_analysis["fill_counts"].items():
            assert student_analysis["fill_counts"].get(model) == count, \
                f"fill_counts[{model}]: {student_analysis['fill_counts'].get(model)} expected {count}"

    def test_aggressiveness_ranking(self, student_analysis, reference_analysis):
        assert student_analysis["aggressiveness_ranking"] == reference_analysis["aggressiveness_ranking"], \
            f"Ranking: {student_analysis['aggressiveness_ranking']} expected {reference_analysis['aggressiveness_ranking']}"

    def test_pairwise_disagreements(self, student_analysis, reference_analysis):
        for key, count in reference_analysis["pairwise_disagreements"].items():
            assert student_analysis["pairwise_disagreements"].get(key) == count, \
                f"pairwise[{key}]: {student_analysis['pairwise_disagreements'].get(key)} expected {count}"

    def test_model_sensitive_orders(self, student_analysis, reference_analysis):
        assert sorted(student_analysis["model_sensitive_orders"]) == \
               sorted(reference_analysis["model_sensitive_orders"]), \
            f"Sensitive orders: {student_analysis['model_sensitive_orders']} " \
            f"expected {reference_analysis['model_sensitive_orders']}"

    def test_most_conservative(self, student_analysis, reference_analysis):
        assert student_analysis["most_conservative_model"] == reference_analysis["most_conservative_model"], \
            f"Most conservative: {student_analysis['most_conservative_model']} " \
            f"expected {reference_analysis['most_conservative_model']}"

    def test_most_aggressive(self, student_analysis, reference_analysis):
        assert student_analysis["most_aggressive_model"] == reference_analysis["most_aggressive_model"], \
            f"Most aggressive: {student_analysis['most_aggressive_model']} " \
            f"expected {reference_analysis['most_aggressive_model']}"

    def test_ranking_consistent_with_fill_counts(self, student_analysis):
        """Verify ranking is consistent with fill counts."""
        ranking = student_analysis["aggressiveness_ranking"]
        counts = student_analysis["fill_counts"]
        for i in range(len(ranking) - 1):
            c_curr = counts[ranking[i]]
            c_next = counts[ranking[i + 1]]
            assert c_curr >= c_next, \
                f"Ranking inconsistent: {ranking[i]}({c_curr}) before {ranking[i+1]}({c_next})"
            if c_curr == c_next:
                assert ranking[i] < ranking[i + 1], \
                    f"Tied models not alphabetically ordered: {ranking[i]} vs {ranking[i+1]}"
