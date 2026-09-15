
"""
Tests for the streaming financial reconciliation pipeline.

Verifies correctness of materialized views, consistency invariants
(total=0, balance=credits-debits), watermark behavior, late-data
rejection, agreement with batch recomputation, DuckDB oracle
correctness, and consistency monitor report structure.
"""

import json
import sys
import os
import subprocess
import pytest

sys.path.insert(0, '/app')


def load_transactions(path):
    txns = []
    with open(path) as f:
        for line in f:
            txns.append(json.loads(line))
    return txns


def simulate_watermark(txns, watermark_delay):
    """Reproduce the same accept/reject logic to determine expected values."""
    max_et = None
    watermark = None
    accepted = []
    for txn in txns:
        et = txn['ts']
        if watermark is not None and et < watermark:
            continue
        accepted.append(txn)
        if max_et is None or et > max_et:
            max_et = et
            new_wm = max_et - watermark_delay
            if watermark is None or new_wm > watermark:
                watermark = new_wm
    return accepted


# ---------------------------------------------------------------------------
# Interface tests
# ---------------------------------------------------------------------------

class TestEngineInterface:
    """Verify the engine exposes the required interface."""

    def test_import(self):
        from engine import IncrementalViewEngine

    def test_constructor(self):
        from engine import IncrementalViewEngine
        engine = IncrementalViewEngine(watermark_delay=5)

    def test_methods_exist(self):
        from engine import IncrementalViewEngine
        engine = IncrementalViewEngine(watermark_delay=5)
        assert callable(getattr(engine, 'ingest', None))
        assert callable(getattr(engine, 'finalize', None))
        assert callable(getattr(engine, 'get_checkpoints', None))
        assert callable(getattr(engine, 'get_rejected_count', None))


# ---------------------------------------------------------------------------
# Basic correctness with hand-crafted examples
# ---------------------------------------------------------------------------

class TestBasicCorrectness:

    def test_single_transaction(self):
        from engine import IncrementalViewEngine
        engine = IncrementalViewEngine(watermark_delay=100)
        engine.ingest(0.0, {
            'id': 0, 'from_account': 0, 'to_account': 1,
            'amount': 10, 'ts': 0,
        })
        engine.finalize()

        cps = engine.get_checkpoints()
        assert len(cps) >= 1
        final = cps[-1]
        assert final['total'] == 0
        assert final['credits'] == {1: 10}
        assert final['debits'] == {0: 10}
        assert final['balance'] == {0: -10, 1: 10}

    def test_three_transactions_no_rejection(self):
        from engine import IncrementalViewEngine
        engine = IncrementalViewEngine(watermark_delay=100)
        txns = [
            {'id': 0, 'from_account': 0, 'to_account': 1, 'amount': 5, 'ts': 0},
            {'id': 1, 'from_account': 1, 'to_account': 2, 'amount': 3, 'ts': 1},
            {'id': 2, 'from_account': 2, 'to_account': 0, 'amount': 8, 'ts': 2},
        ]
        for i, txn in enumerate(txns):
            engine.ingest(float(i), txn)
        engine.finalize()

        assert engine.get_rejected_count() == 0
        final = engine.get_checkpoints()[-1]
        assert final['credits'] == {1: 5, 2: 3, 0: 8}
        assert final['debits'] == {0: 5, 1: 3, 2: 8}
        assert final['balance'] == {0: 3, 1: 2, 2: -5}
        assert final['total'] == 0

    def test_self_transfer(self):
        """Transfer from an account to itself must still maintain total=0."""
        from engine import IncrementalViewEngine
        engine = IncrementalViewEngine(watermark_delay=100)
        engine.ingest(0.0, {
            'id': 0, 'from_account': 3, 'to_account': 3,
            'amount': 100, 'ts': 0,
        })
        engine.finalize()

        final = engine.get_checkpoints()[-1]
        assert final['total'] == 0
        assert final['balance'].get(3, 0) == 0

    def test_varying_amounts(self):
        from engine import IncrementalViewEngine
        engine = IncrementalViewEngine(watermark_delay=100)
        txns = [
            {'id': 0, 'from_account': 0, 'to_account': 1, 'amount': 100, 'ts': 0},
            {'id': 1, 'from_account': 1, 'to_account': 2, 'amount': 50,  'ts': 0},
            {'id': 2, 'from_account': 2, 'to_account': 0, 'amount': 75,  'ts': 0},
            {'id': 3, 'from_account': 0, 'to_account': 2, 'amount': 25,  'ts': 1},
        ]
        for txn in txns:
            engine.ingest(float(txn['ts']), txn)
        engine.finalize()

        for cp in engine.get_checkpoints():
            assert cp['total'] == 0

        final = engine.get_checkpoints()[-1]
        assert final['credits'] == {1: 100, 2: 75, 0: 75}
        assert final['debits'] == {0: 125, 1: 50, 2: 75}
        assert final['balance'] == {0: -50, 1: 50, 2: 0}

    def test_multiple_epochs(self):
        """Events spanning multiple timestamps with small delay should produce
        multiple checkpoints, each internally consistent."""
        from engine import IncrementalViewEngine
        engine = IncrementalViewEngine(watermark_delay=1)
        txns = [
            {'id': 0, 'from_account': 0, 'to_account': 1, 'amount': 10, 'ts': 0},
            {'id': 1, 'from_account': 1, 'to_account': 2, 'amount': 5,  'ts': 3},
            {'id': 2, 'from_account': 2, 'to_account': 0, 'amount': 7,  'ts': 6},
            {'id': 3, 'from_account': 0, 'to_account': 2, 'amount': 3,  'ts': 9},
        ]
        for txn in txns:
            engine.ingest(float(txn['ts']), txn)
        engine.finalize()

        cps = engine.get_checkpoints()
        assert len(cps) >= 2, f"Expected multiple checkpoints, got {len(cps)}"

        for cp in cps:
            assert cp['total'] == 0, \
                f"Checkpoint at wm={cp['watermark']}: total={cp['total']}"
            accts = (set(cp['credits'].keys())
                     | set(cp['debits'].keys())
                     | set(cp['balance'].keys()))
            for acc in accts:
                c = cp['credits'].get(acc, 0)
                d = cp['debits'].get(acc, 0)
                b = cp['balance'].get(acc, 0)
                assert b == c - d, \
                    f"Account {acc}: balance={b} != {c} - {d}"


# ---------------------------------------------------------------------------
# Watermark behaviour
# ---------------------------------------------------------------------------

class TestWatermarkBehavior:

    def test_late_data_rejected(self):
        """Data arriving after watermark has advanced must be rejected."""
        from engine import IncrementalViewEngine
        engine = IncrementalViewEngine(watermark_delay=2)
        # ts=5 -> watermark = 3
        engine.ingest(5.0, {
            'id': 0, 'from_account': 0, 'to_account': 1,
            'amount': 1, 'ts': 5,
        })
        # ts=1 < watermark=3 -> rejected
        engine.ingest(11.0, {
            'id': 1, 'from_account': 1, 'to_account': 0,
            'amount': 1, 'ts': 1,
        })
        engine.finalize()
        assert engine.get_rejected_count() == 1

    def test_watermarks_monotonic(self):
        from engine import IncrementalViewEngine
        txns = load_transactions('/app/data/transactions.jsonl')
        engine = IncrementalViewEngine(watermark_delay=5)
        for txn in txns:
            engine.ingest(txn['arrival_time'], txn)
        engine.finalize()

        cps = engine.get_checkpoints()
        for i in range(1, len(cps)):
            assert cps[i]['watermark'] > cps[i - 1]['watermark'], \
                f"Watermark not monotonic at checkpoint {i}"

    def test_checkpoint_count(self):
        """Engine must emit multiple incremental checkpoints, not just one."""
        from engine import IncrementalViewEngine
        txns = load_transactions('/app/data/transactions.jsonl')
        engine = IncrementalViewEngine(watermark_delay=5)
        for txn in txns:
            engine.ingest(txn['arrival_time'], txn)
        engine.finalize()

        cps = engine.get_checkpoints()
        assert len(cps) >= 10, \
            f"Expected at least 10 checkpoints, got {len(cps)}"

    def test_adversarial_ordering(self):
        """Late-arriving data must be rejected without breaking invariants."""
        from engine import IncrementalViewEngine
        engine = IncrementalViewEngine(watermark_delay=2)

        # ts=5 -> watermark = 3
        engine.ingest(5.0, {
            'id': 0, 'from_account': 0, 'to_account': 1,
            'amount': 1, 'ts': 5,
        })
        # ts=0 < 3 -> rejected
        engine.ingest(10.0, {
            'id': 1, 'from_account': 1, 'to_account': 2,
            'amount': 1, 'ts': 0,
        })
        # ts=3 at watermark boundary -> should be accepted
        engine.ingest(11.0, {
            'id': 2, 'from_account': 2, 'to_account': 0,
            'amount': 1, 'ts': 3,
        })
        # ts=8 -> watermark = 6
        engine.ingest(12.0, {
            'id': 3, 'from_account': 0, 'to_account': 2,
            'amount': 1, 'ts': 8,
        })
        engine.finalize()

        assert engine.get_rejected_count() == 1
        for cp in engine.get_checkpoints():
            assert cp['total'] == 0


# ---------------------------------------------------------------------------
# Internal consistency invariants
# ---------------------------------------------------------------------------

class TestInternalConsistency:

    def test_total_always_zero_random(self):
        from engine import IncrementalViewEngine
        txns = load_transactions('/app/data/transactions.jsonl')
        engine = IncrementalViewEngine(watermark_delay=5)
        for txn in txns:
            engine.ingest(txn['arrival_time'], txn)
        engine.finalize()

        for i, cp in enumerate(engine.get_checkpoints()):
            assert cp['total'] == 0, \
                f"Checkpoint {i} (wm={cp['watermark']}): total={cp['total']}"

    def test_balance_consistency(self):
        """balance[i] must equal credits[i] - debits[i] at every checkpoint."""
        from engine import IncrementalViewEngine
        txns = load_transactions('/app/data/transactions.jsonl')
        engine = IncrementalViewEngine(watermark_delay=5)
        for txn in txns:
            engine.ingest(txn['arrival_time'], txn)
        engine.finalize()

        for cp in engine.get_checkpoints():
            accts = (set(cp['credits'].keys())
                     | set(cp['debits'].keys())
                     | set(cp['balance'].keys()))
            for acc in accts:
                c = cp['credits'].get(acc, 0)
                d = cp['debits'].get(acc, 0)
                b = cp['balance'].get(acc, 0)
                assert b == c - d, \
                    f"Account {acc}: balance={b} != {c} - {d}"

    def test_credits_debits_sum_equal(self):
        """Sum of credits must equal sum of debits at every checkpoint."""
        from engine import IncrementalViewEngine
        txns = load_transactions('/app/data/transactions.jsonl')
        engine = IncrementalViewEngine(watermark_delay=5)
        for txn in txns:
            engine.ingest(txn['arrival_time'], txn)
        engine.finalize()

        for cp in engine.get_checkpoints():
            tc = sum(cp['credits'].values())
            td = sum(cp['debits'].values())
            assert tc == td, f"sum(credits)={tc} != sum(debits)={td}"

    def test_monotonic_credits_debits(self):
        """Credit and debit totals must never decrease between checkpoints."""
        from engine import IncrementalViewEngine
        txns = load_transactions('/app/data/transactions.jsonl')
        engine = IncrementalViewEngine(watermark_delay=5)
        for txn in txns:
            engine.ingest(txn['arrival_time'], txn)
        engine.finalize()

        cps = engine.get_checkpoints()
        for i in range(1, len(cps)):
            prev, curr = cps[i - 1], cps[i]
            for acc in prev['credits']:
                assert curr['credits'].get(acc, 0) >= prev['credits'][acc], \
                    f"Credits decreased for account {acc}"
            for acc in prev['debits']:
                assert curr['debits'].get(acc, 0) >= prev['debits'][acc], \
                    f"Debits decreased for account {acc}"

    def test_total_zero_multiple_delays(self):
        """Internal consistency must hold for any watermark delay."""
        from engine import IncrementalViewEngine
        txns = load_transactions('/app/data/transactions.jsonl')
        for delay in [0, 1, 3, 5, 10, 20, 50]:
            engine = IncrementalViewEngine(watermark_delay=delay)
            for txn in txns:
                engine.ingest(txn['arrival_time'], txn)
            engine.finalize()

            for cp in engine.get_checkpoints():
                assert cp['total'] == 0, \
                    f"delay={delay}, wm={cp['watermark']}: total={cp['total']}"


# ---------------------------------------------------------------------------
# Simplified cyclic dataset
# ---------------------------------------------------------------------------

class TestSimplifiedData:

    def test_balance_range(self):
        """With cyclic transfers (i->i+1 mod 10), balance must be in {-1, 0, 1}."""
        from engine import IncrementalViewEngine
        txns = load_transactions('/app/data/simplified.jsonl')
        engine = IncrementalViewEngine(watermark_delay=0)
        for txn in txns:
            engine.ingest(txn['arrival_time'], txn)
        engine.finalize()

        for cp in engine.get_checkpoints():
            assert cp['total'] == 0
            for acc, bal in cp['balance'].items():
                assert bal in (-1, 0, 1), \
                    f"Account {acc} at wm={cp['watermark']}: balance={bal}"

    def test_final_all_zero(self):
        """100K txns in cycle of 10 = 10K full cycles -> all final balances 0."""
        from engine import IncrementalViewEngine
        txns = load_transactions('/app/data/simplified.jsonl')
        engine = IncrementalViewEngine(watermark_delay=0)
        for txn in txns:
            engine.ingest(txn['arrival_time'], txn)
        engine.finalize()

        final = engine.get_checkpoints()[-1]
        for acc in range(10):
            assert final['balance'].get(acc, 0) == 0, \
                f"Account {acc}: expected 0, got {final['balance'].get(acc, 0)}"


# ---------------------------------------------------------------------------
# Final values vs batch recomputation
# ---------------------------------------------------------------------------

class TestFinalValues:

    def test_final_matches_batch(self):
        """Final checkpoint must match batch computation of accepted txns."""
        from engine import IncrementalViewEngine
        txns = load_transactions('/app/data/transactions.jsonl')
        accepted = simulate_watermark(txns, 5)

        exp_credits, exp_debits = {}, {}
        for t in accepted:
            exp_credits[t['to_account']] = exp_credits.get(t['to_account'], 0) + t['amount']
            exp_debits[t['from_account']] = exp_debits.get(t['from_account'], 0) + t['amount']

        engine = IncrementalViewEngine(watermark_delay=5)
        for txn in txns:
            engine.ingest(txn['arrival_time'], txn)
        engine.finalize()

        final = engine.get_checkpoints()[-1]
        assert final['credits'] == exp_credits, "Credits mismatch vs batch"
        assert final['debits'] == exp_debits, "Debits mismatch vs batch"
        assert engine.get_rejected_count() == len(txns) - len(accepted), \
            f"Rejected: {engine.get_rejected_count()} vs expected {len(txns) - len(accepted)}"

    def test_simplified_final_matches_batch(self):
        """Simplified data with large delay: no rejections, exact values."""
        from engine import IncrementalViewEngine
        txns = load_transactions('/app/data/simplified.jsonl')
        engine = IncrementalViewEngine(watermark_delay=100)
        for txn in txns:
            engine.ingest(txn['arrival_time'], txn)
        engine.finalize()

        assert engine.get_rejected_count() == 0

        exp_credits, exp_debits = {}, {}
        for t in txns:
            exp_credits[t['to_account']] = exp_credits.get(t['to_account'], 0) + t['amount']
            exp_debits[t['from_account']] = exp_debits.get(t['from_account'], 0) + t['amount']

        final = engine.get_checkpoints()[-1]
        assert final['credits'] == exp_credits
        assert final['debits'] == exp_debits


# ---------------------------------------------------------------------------
# DuckDB Oracle
# ---------------------------------------------------------------------------

class TestDuckDBOracle:

    def test_oracle_script_exists(self):
        """Oracle compute script must exist and be executable."""
        assert os.path.isfile('/app/oracle/compute.sh'), \
            "Oracle script missing at /app/oracle/compute.sh"
        assert os.access('/app/oracle/compute.sh', os.X_OK), \
            "Oracle script must be executable"

    def test_oracle_uses_duckdb(self):
        """Oracle implementation must reference DuckDB."""
        found = False
        oracle_dir = '/app/oracle'
        if os.path.isdir(oracle_dir):
            for fname in os.listdir(oracle_dir):
                fpath = os.path.join(oracle_dir, fname)
                if os.path.isfile(fpath):
                    with open(fpath) as fh:
                        if 'duckdb' in fh.read().lower():
                            found = True
                            break
        assert found, "Oracle must use DuckDB for batch computation"

    def test_oracle_results_delay_5(self):
        """Oracle with delay=5 must match independently computed ground truth."""
        subprocess.run(
            ['bash', '/app/oracle/compute.sh', '5'],
            check=True, capture_output=True, text=True,
            cwd='/app', timeout=120
        )
        assert os.path.isfile('/app/oracle/batch_results.json')

        with open('/app/oracle/batch_results.json') as f:
            oracle = json.load(f)

        for field in ['watermark_delay', 'accepted_count', 'rejected_count',
                      'credits', 'debits', 'balance', 'total']:
            assert field in oracle, f"Missing field: {field}"

        txns = load_transactions('/app/data/transactions.jsonl')
        accepted = simulate_watermark(txns, 5)

        exp_credits, exp_debits = {}, {}
        for t in accepted:
            exp_credits[t['to_account']] = exp_credits.get(t['to_account'], 0) + t['amount']
            exp_debits[t['from_account']] = exp_debits.get(t['from_account'], 0) + t['amount']

        oracle_credits = {int(k): v for k, v in oracle['credits'].items()}
        oracle_debits = {int(k): v for k, v in oracle['debits'].items()}

        assert oracle_credits == exp_credits, "Oracle credits mismatch"
        assert oracle_debits == exp_debits, "Oracle debits mismatch"
        assert oracle['total'] == 0
        assert oracle['accepted_count'] == len(accepted)
        assert oracle['rejected_count'] == len(txns) - len(accepted)

    def test_oracle_results_delay_0(self):
        """Oracle with delay=0 must produce total=0."""
        subprocess.run(
            ['bash', '/app/oracle/compute.sh', '0'],
            check=True, capture_output=True, text=True,
            cwd='/app', timeout=120
        )
        with open('/app/oracle/batch_results.json') as f:
            oracle = json.load(f)
        assert oracle['total'] == 0
        assert oracle['watermark_delay'] == 0

    def test_oracle_results_delay_20(self):
        """Oracle with delay=20 must agree on accepted count."""
        subprocess.run(
            ['bash', '/app/oracle/compute.sh', '20'],
            check=True, capture_output=True, text=True,
            cwd='/app', timeout=120
        )
        with open('/app/oracle/batch_results.json') as f:
            oracle = json.load(f)

        txns = load_transactions('/app/data/transactions.jsonl')
        accepted = simulate_watermark(txns, 20)

        assert oracle['total'] == 0
        assert oracle['accepted_count'] == len(accepted)
        assert oracle['rejected_count'] == len(txns) - len(accepted)


# ---------------------------------------------------------------------------
# Consistency Monitor
# ---------------------------------------------------------------------------

class TestMonitorReport:

    def test_report_exists(self):
        """Monitor report must exist."""
        assert os.path.isfile('/app/monitor/report.json'), \
            "Monitor report missing at /app/monitor/report.json"

    def test_report_schema(self):
        """Report must have correct schema with all required fields."""
        with open('/app/monitor/report.json') as f:
            report = json.load(f)

        assert 'systems' in report
        assert 'overall_consistent' in report
        assert isinstance(report['systems'], list)
        assert len(report['systems']) == 5, \
            f"Must cover 5 delays, got {len(report['systems'])}"

        expected_delays = {0, 1, 5, 10, 20}
        actual_delays = {e['watermark_delay'] for e in report['systems']}
        assert actual_delays == expected_delays

        valid_modes = {'stream_desync', 'watermark_boundary',
                       'missing_accounts', 'finalization_error'}
        for entry in report['systems']:
            assert isinstance(entry['consistent'], bool)
            assert isinstance(entry['total_anomalies'], int)
            assert isinstance(entry['failure_modes'], list)
            for mode in entry['failure_modes']:
                assert mode in valid_modes, f"Invalid failure mode: {mode}"

    def test_report_overall_consistent(self):
        """Pipeline must be consistent after fixes."""
        with open('/app/monitor/report.json') as f:
            report = json.load(f)
        assert report['overall_consistent'] is True

    def test_report_all_delays_zero_anomalies(self):
        """Every watermark delay must show zero anomalies after fixes."""
        with open('/app/monitor/report.json') as f:
            report = json.load(f)

        for entry in report['systems']:
            assert entry['consistent'] is True, \
                f"Delay {entry['watermark_delay']}: not consistent"
            assert entry['total_anomalies'] == 0, \
                f"Delay {entry['watermark_delay']}: {entry['total_anomalies']} anomalies"
            assert entry['failure_modes'] == [], \
                f"Delay {entry['watermark_delay']}: modes={entry['failure_modes']}"

    def test_monitor_uses_jq(self):
        """Monitor must use jq for structured JSON comparison."""
        found = False
        monitor_dir = '/app/monitor'
        if os.path.isdir(monitor_dir):
            for fname in os.listdir(monitor_dir):
                fpath = os.path.join(monitor_dir, fname)
                if os.path.isfile(fpath):
                    with open(fpath) as fh:
                        if 'jq' in fh.read():
                            found = True
                            break
        assert found, "Monitor must use jq"

    def test_monitor_references_oracle(self):
        """Monitor must reference the DuckDB oracle."""
        found = False
        monitor_dir = '/app/monitor'
        if os.path.isdir(monitor_dir):
            for fname in os.listdir(monitor_dir):
                fpath = os.path.join(monitor_dir, fname)
                if os.path.isfile(fpath):
                    with open(fpath) as fh:
                        content = fh.read()
                        if 'oracle' in content or 'duckdb' in content.lower():
                            found = True
                            break
        assert found, "Monitor must reference DuckDB oracle"
