
import pytest
import json
import sys
import math

sys.path.insert(0, '/app')


class TestProbabilityValues:
    """Verify probability function outputs from results.json against analytical formulas."""

    def setup_method(self):
        with open('/app/results.json') as f:
            self.results = json.load(f)
        self.probs = self.results['probabilities']

    def test_power2(self):
        # PowerProbQueueFunc(2): 5^2 / (5^2 + 10^2) = 25/125 = 0.2
        assert abs(self.probs['power2_front10_back5'] - 0.2) < 1e-10

    def test_power3_3(self):
        # PowerProbQueueFunc3(3): 1 - (10/15)^3 = 1 - 8/27 = 19/27
        assert abs(self.probs['power3_3_front10_back5'] - 19.0 / 27.0) < 1e-10

    def test_log(self):
        # LogProbQueueFunc: ln(6) / (ln(6) + ln(11))
        expected = math.log(6) / (math.log(6) + math.log(11))
        assert abs(self.probs['log_front10_back5'] - expected) < 1e-10

    def test_log2(self):
        # LogProbQueueFunc2: ln(6) / ln(16)
        expected = math.log(6) / math.log(16)
        assert abs(self.probs['log2_front10_back5'] - expected) < 1e-10

    def test_power2_2(self):
        # PowerProbQueueFunc2(2): 5^2 / 15^2 = 25/225 = 1/9
        assert abs(self.probs['power2_2_front10_back5'] - 1.0 / 9.0) < 1e-10


class TestProbabilityBoundary:
    """Verify probability functions handle boundary cases correctly."""

    def test_power_at_head(self):
        from simulator import PowerProbQueueFunc
        p = PowerProbQueueFunc(2)
        # At head of queue (front=0): all cancels behind us -> prob=1
        assert abs(p.prob(0, 10) - 1.0) < 1e-10

    def test_power_at_tail(self):
        from simulator import PowerProbQueueFunc
        p = PowerProbQueueFunc(2)
        # At tail (back=0): no cancels behind us -> prob=0
        assert abs(p.prob(10, 0) - 0.0) < 1e-10

    def test_log_at_head(self):
        from simulator import LogProbQueueFunc
        lg = LogProbQueueFunc()
        assert abs(lg.prob(0, 10) - 1.0) < 1e-10

    def test_log_at_tail(self):
        from simulator import LogProbQueueFunc
        lg = LogProbQueueFunc()
        assert abs(lg.prob(10, 0) - 0.0) < 1e-10

    def test_power3_at_head(self):
        from simulator import PowerProbQueueFunc3
        p3 = PowerProbQueueFunc3(3)
        assert abs(p3.prob(0, 10) - 1.0) < 1e-10

    def test_power3_at_tail(self):
        from simulator import PowerProbQueueFunc3
        p3 = PowerProbQueueFunc3(3)
        assert abs(p3.prob(10, 0) - 0.0) < 1e-10

    def test_log2_at_head(self):
        from simulator import LogProbQueueFunc2
        lg2 = LogProbQueueFunc2()
        assert abs(lg2.prob(0, 10) - 1.0) < 1e-10

    def test_power2_at_tail(self):
        from simulator import PowerProbQueueFunc2
        p2 = PowerProbQueueFunc2(2)
        assert abs(p2.prob(10, 0) - 0.0) < 1e-10


class TestQueuePositionTracking:
    """Test ProbQueueModel depth update on a hand-crafted scenario."""

    def test_depth_decrease_power2(self):
        from simulator import ProbQueueModel, PowerProbQueueFunc, OrderBook
        book = OrderBook(0.01, 0.01)
        book.update_bid(9999, 50.0)
        book.update_ask(10001, 50.0)

        model = ProbQueueModel(PowerProbQueueFunc(2))
        qpos = model.new_order('buy', 9999, book)
        assert abs(qpos.front_q_qty - 50.0) < 1e-10

        # Depth increases to 80 (orders added behind us)
        model.depth(qpos, 50.0, 80.0)
        assert abs(qpos.front_q_qty - 50.0) < 1e-10  # No change on increase

        # Depth decreases to 70 (some cancels, chg=10)
        # front=50, back=80-50=30
        # prob = 30^2/(30^2+50^2) = 900/3400 = 9/34
        # est = 50 - (25/34)*10 + min(0, 30 - 90/34)
        #     = 50 - 250/34 + 0 = (1700-250)/34 = 1450/34
        model.depth(qpos, 80.0, 70.0)
        expected = 1450.0 / 34.0
        assert abs(qpos.front_q_qty - expected) < 1e-6

    def test_depth_decrease_logprob(self):
        from simulator import ProbQueueModel, LogProbQueueFunc, OrderBook
        book = OrderBook(0.01, 0.01)
        book.update_bid(9999, 50.0)
        book.update_ask(10001, 50.0)

        model = ProbQueueModel(LogProbQueueFunc())
        qpos = model.new_order('buy', 9999, book)

        model.depth(qpos, 50.0, 80.0)
        model.depth(qpos, 80.0, 70.0)
        # front=50, back=30
        # prob = ln(31) / (ln(31) + ln(51))
        prob_lg = math.log(31) / (math.log(31) + math.log(51))
        expected = 50.0 - (1 - prob_lg) * 10.0
        assert abs(qpos.front_q_qty - expected) < 1e-6

    def test_power2_and_log_differ(self):
        """PowerProb(2) and LogProb should give different front_q_qty values."""
        from simulator import ProbQueueModel, PowerProbQueueFunc, LogProbQueueFunc, OrderBook

        book1 = OrderBook(0.01, 0.01)
        book1.update_bid(9999, 50.0)
        book1.update_ask(10001, 50.0)
        m1 = ProbQueueModel(PowerProbQueueFunc(2))
        q1 = m1.new_order('buy', 9999, book1)
        m1.depth(q1, 50.0, 80.0)
        m1.depth(q1, 80.0, 70.0)

        book2 = OrderBook(0.01, 0.01)
        book2.update_bid(9999, 50.0)
        book2.update_ask(10001, 50.0)
        m2 = ProbQueueModel(LogProbQueueFunc())
        q2 = m2.new_order('buy', 9999, book2)
        m2.depth(q2, 50.0, 80.0)
        m2.depth(q2, 80.0, 70.0)

        assert abs(q1.front_q_qty - q2.front_q_qty) > 0.1


class TestOverflowCorrection:
    """Test the min(0, back - prob*chg) overflow correction term."""

    def test_overflow_triggers(self):
        from simulator import ProbQueueModel, PowerProbQueueFunc, QueuePos

        model = ProbQueueModel(PowerProbQueueFunc(2))

        # front=1, back=4, prev_qty=5, new_qty=0.5 -> chg=4.5
        # prob = 16/17, (1-prob)*chg = 4.5/17
        # prob*chg = 72/17, back - prob*chg = 4 - 72/17 = -4/17
        # est = 1 - 4.5/17 + (-4/17) = 1 - 8.5/17 = 0.5
        qpos = QueuePos()
        qpos.front_q_qty = 1.0
        qpos.cum_trade_qty = 0.0

        model.depth(qpos, 5.0, 0.5)
        assert abs(qpos.front_q_qty - 0.5) < 1e-10

    def test_no_overflow(self):
        from simulator import ProbQueueModel, PowerProbQueueFunc, QueuePos

        model = ProbQueueModel(PowerProbQueueFunc(2))

        # front=3, back=2, prev_qty=5, new_qty=3 -> chg=2
        # prob = 4/13, (1-prob)*chg = 18/13
        # back - prob*chg = 2 - 8/13 = 18/13 > 0 (no overflow)
        # est = 3 - 18/13 + 0 = 21/13
        qpos = QueuePos()
        qpos.front_q_qty = 3.0
        qpos.cum_trade_qty = 0.0

        model.depth(qpos, 5.0, 3.0)
        assert abs(qpos.front_q_qty - 21.0 / 13.0) < 1e-10


class TestTradeDepthInteraction:
    """Test cum_trade_qty deduction in depth updates."""

    def test_trade_then_depth(self):
        from simulator import ProbQueueModel, PowerProbQueueFunc, QueuePos

        model = ProbQueueModel(PowerProbQueueFunc(2))

        qpos = QueuePos()
        qpos.front_q_qty = 6.0
        qpos.cum_trade_qty = 0.0

        # Trade of 3
        model.trade(qpos, 3.0)
        assert abs(qpos.front_q_qty - 3.0) < 1e-10
        assert abs(qpos.cum_trade_qty - 3.0) < 1e-10

        # Depth: prev=15, new=10 -> chg=5, chg-=3=2
        # front=3, back=15-3=12
        # prob = 144/(144+9) = 144/153 = 16/17
        # est = 3 - (1/17)*2 + min(0, 12-32/17)
        #     = 3 - 2/17 + min(0, (204-32)/17)
        #     = 3 - 2/17 + 0 = 49/17
        model.depth(qpos, 15.0, 10.0)
        assert abs(qpos.cum_trade_qty - 0.0) < 1e-10
        assert abs(qpos.front_q_qty - 49.0 / 17.0) < 1e-6

    def test_cum_reset(self):
        from simulator import ProbQueueModel, PowerProbQueueFunc, QueuePos

        model = ProbQueueModel(PowerProbQueueFunc(2))
        qpos = QueuePos()
        qpos.front_q_qty = 10.0
        qpos.cum_trade_qty = 0.0

        model.trade(qpos, 5.0)
        assert abs(qpos.cum_trade_qty - 5.0) < 1e-10

        # After depth update, cum should reset
        model.depth(qpos, 20.0, 14.0)
        assert abs(qpos.cum_trade_qty - 0.0) < 1e-10


class TestResultsStructure:
    """Test results.json has correct structure and valid values."""

    def setup_method(self):
        with open('/app/results.json') as f:
            self.results = json.load(f)

    def test_top_level_keys(self):
        assert 'probabilities' in self.results
        assert 'fills' in self.results
        assert 'book_snapshots' in self.results

    def test_probability_keys(self):
        required = [
            'power2_front10_back5', 'power3_3_front10_back5',
            'log_front10_back5', 'log2_front10_back5',
            'power2_2_front10_back5'
        ]
        for k in required:
            assert k in self.results['probabilities'], f"Missing key: {k}"
            assert isinstance(self.results['probabilities'][k], float)

    def test_fill_model_keys(self):
        for model_key in ['power_n2', 'power_n3', 'log']:
            assert model_key in self.results['fills'], f"Missing model: {model_key}"
            fills = self.results['fills'][model_key]
            for k in ['filled_order_ids', 'total_fills', 'pnl', 'total_fees', 'final_position']:
                assert k in fills, f"Missing key {k} in {model_key}"

    def test_fill_consistency(self):
        for model_key in ['power_n2', 'power_n3', 'log']:
            fills = self.results['fills'][model_key]
            assert isinstance(fills['filled_order_ids'], list)
            assert isinstance(fills['total_fills'], int)
            assert fills['total_fills'] == len(fills['filled_order_ids'])
            assert fills['total_fees'] >= 0


class TestBookSnapshots:
    """Test book snapshot values are physically valid."""

    def setup_method(self):
        with open('/app/results.json') as f:
            self.results = json.load(f)

    def test_snapshot_keys(self):
        for key in ['event_500', 'event_1000', 'event_1500']:
            assert key in self.results['book_snapshots']

    def test_bid_below_ask(self):
        for key in ['event_500', 'event_1000', 'event_1500']:
            snap = self.results['book_snapshots'][key]
            bb = snap['best_bid']
            ba = snap['best_ask']
            assert bb > 0, f"best_bid must be positive at {key}"
            assert ba > 0, f"best_ask must be positive at {key}"
            assert bb < ba, f"best_bid ({bb}) >= best_ask ({ba}) at {key}"

    def test_prices_near_initial(self):
        # Mid should stay roughly near 100.00 (drift is small)
        for key in ['event_500', 'event_1000', 'event_1500']:
            snap = self.results['book_snapshots'][key]
            mid = (snap['best_bid'] + snap['best_ask']) / 2
            assert 99.0 < mid < 101.0, f"Mid price {mid} too far from 100.0 at {key}"


class TestPnLConsistency:
    """Cross-reference P&L with orders.json to verify consistency."""

    def setup_method(self):
        with open('/app/results.json') as f:
            self.results = json.load(f)
        with open('/app/orders.json') as f:
            self.orders = json.load(f)
        with open('/app/config.json') as f:
            self.config = json.load(f)

    def test_fees_match(self):
        maker_fee = self.config['maker_fee']
        for model_key in ['power_n2', 'power_n3', 'log']:
            fills = self.results['fills'][model_key]
            filled_ids = set(fills['filled_order_ids'])

            expected_fees = 0.0
            for order in self.orders:
                if order['order_id'] in filled_ids:
                    expected_fees += abs(order['price'] * order['qty'] * maker_fee)

            assert abs(fills['total_fees'] - expected_fees) < 0.01, \
                f"Fee mismatch for {model_key}: got {fills['total_fees']}, expected {expected_fees}"

    def test_position_match(self):
        for model_key in ['power_n2', 'power_n3', 'log']:
            fills = self.results['fills'][model_key]
            filled_ids = set(fills['filled_order_ids'])

            expected_pos = 0.0
            for order in self.orders:
                if order['order_id'] in filled_ids:
                    if order['side'] == 'buy':
                        expected_pos += order['qty']
                    else:
                        expected_pos -= order['qty']

            assert abs(fills['final_position'] - expected_pos) < 0.001, \
                f"Position mismatch for {model_key}: got {fills['final_position']}, expected {expected_pos}"

    def test_filled_ids_valid(self):
        valid_ids = {o['order_id'] for o in self.orders}
        for model_key in ['power_n2', 'power_n3', 'log']:
            for oid in self.results['fills'][model_key]['filled_order_ids']:
                assert oid in valid_ids, f"Invalid order_id {oid} in {model_key}"
