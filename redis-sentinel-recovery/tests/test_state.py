
import pytest
import redis
import requests
import json
import time

REDIS_PASSWORD = 'secretpass'
NODE_A_PORT = 6379
NODE_B_PORT = 6380
SENTINEL_PORTS = [26379, 26380, 26381]
APP_URL = 'http://localhost:5000'


class TestNodeARecovery:
    """Verify Node A was recovered from AOF corruption and is operational."""

    def test_node_a_is_running(self):
        """Node A must be reachable and responding to commands."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        assert r.ping() is True

    def test_node_a_aof_enabled(self):
        """Node A should be running with AOF persistence enabled (not disabled as workaround)."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        info = r.info('persistence')
        assert info.get('aof_enabled') == 1, \
            "Node A must have AOF enabled — fix the corruption, don't disable AOF"


class TestDataReconciliation:
    """Verify the split-brain data was correctly reconciled with business rules."""

    def test_master_total_records(self):
        """Master (Node A) should have exactly 130 records after reconciliation."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        keys = r.keys('record:*')
        assert len(keys) == 130, f"Expected 130 records, found {len(keys)}"

    def test_conflict_record_15_b_wins(self):
        """Record 15: B wins (refunded status, financial safety rule)."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        data = json.loads(r.get('record:15'))
        assert data['status'] == 'refunded', \
            f"Record 15 should be 'refunded' (B wins), got '{data['status']}'"
        assert data['updated_at'] == '2024-01-15T14:45:00Z'

    def test_conflict_record_47_b_wins_financial_safety(self):
        """Record 47: B wins by financial safety override despite A having later timestamp.
        A has cancelled@15:10, B has refunded@14:50. Refund overrides timestamp."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        data = json.loads(r.get('record:47'))
        assert data['status'] == 'refunded', \
            f"Record 47 should be 'refunded' (B wins via financial safety), got '{data['status']}'"
        assert data['updated_at'] == '2024-01-15T14:50:00Z', \
            f"Record 47 should have B's timestamp 14:50, got '{data['updated_at']}'"

    def test_a_only_update_record_32(self):
        """Record 32: Only modified on A (amount=500.00), A version should win by timestamp."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        data = json.loads(r.get('record:32'))
        assert data['amount'] == 500.00, \
            f"Record 32 amount should be 500.00, got {data['amount']}"
        assert data['updated_at'] == '2024-01-15T14:45:00Z'

    def test_a_only_update_record_63(self):
        """Record 63: Only modified on A (region=eu-central), A version should win."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        data = json.loads(r.get('record:63'))
        assert data['region'] == 'eu-central', \
            f"Record 63 region should be 'eu-central', got '{data['region']}'"

    def test_a_only_update_record_88(self):
        """Record 88: Only modified on A (status=cancelled), A version should win."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        data = json.loads(r.get('record:88'))
        assert data['status'] == 'cancelled', \
            f"Record 88 should be 'cancelled', got '{data['status']}'"

    def test_b_only_update_record_71(self):
        """Record 71: Only modified on B (status=refunded), B wins (financial safety + timestamp)."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        data = json.loads(r.get('record:71'))
        assert data['status'] == 'refunded', \
            f"Record 71 should be 'refunded', got '{data['status']}'"
        assert data['updated_at'] == '2024-01-15T15:00:00Z'

    def test_b_only_update_record_92(self):
        """Record 92: Only modified on B (amount=750.00), B version should win by timestamp."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        data = json.loads(r.get('record:92'))
        assert data['amount'] == 750.00, \
            f"Record 92 amount should be 750.00, got {data['amount']}"

    def test_overlapping_records_101_110(self):
        """Records 101-110 exist on both nodes with different data; winner by timestamp."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        expected = {
            101: 'node_b', 102: 'node_a',
            103: 'node_b', 104: 'node_a',
            105: 'node_b', 106: 'node_a',
            107: 'node_b', 108: 'node_a',
            109: 'node_b', 110: 'node_a',
        }
        for rec_id, expected_source in expected.items():
            data = json.loads(r.get(f'record:{rec_id}'))
            assert data['source'] == expected_source, \
                f"Record {rec_id} should be from {expected_source}, got '{data.get('source')}'"

    def test_a_unique_records_111_120(self):
        """Records 111-120 exist only on Node A and must be preserved."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        for i in range(111, 121):
            raw = r.get(f'record:{i}')
            assert raw is not None, f"Record {i} (unique to A) should exist"
            data = json.loads(raw)
            assert data['source'] == 'node_a', \
                f"Record {i} should have source 'node_a'"

    def test_b_unique_records_121_130(self):
        """Records 121-130 exist only on Node B and must be merged to A."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        for i in range(121, 131):
            raw = r.get(f'record:{i}')
            assert raw is not None, f"Record {i} (unique to B) should exist on master"
            data = json.loads(raw)
            assert data['source'] == 'node_b', \
                f"Record {i} should have source 'node_b'"

    def test_unmodified_records_intact(self):
        """Records not modified during partition should retain original values."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        for i in [1, 10, 25, 50, 99]:
            data = json.loads(r.get(f'record:{i}'))
            assert data['status'] == 'completed', \
                f"Record {i} status should be 'completed'"
            assert data['updated_at'] == '2024-01-15T10:00:00Z', \
                f"Record {i} should have original timestamp"
            expected_amount = round(100.0 + i * 7.5, 2)
            assert data['amount'] == expected_amount, \
                f"Record {i} amount should be {expected_amount}"


class TestReplication:
    """Verify master-replica topology is correctly restored."""

    def test_node_a_is_master(self):
        """Node A should be running as master with at least 1 replica."""
        r = redis.Redis(host='127.0.0.1', port=NODE_A_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        info = r.info('replication')
        assert info['role'] == 'master'
        assert info['connected_slaves'] >= 1

    def test_node_b_is_replica(self):
        """Node B should be a replica of Node A with link status up."""
        r = redis.Redis(host='127.0.0.1', port=NODE_B_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        info = r.info('replication')
        assert info['role'] == 'slave'
        assert info['master_link_status'] == 'up', \
            f"Replica link status is '{info['master_link_status']}', expected 'up'"

    def test_replica_has_all_data(self):
        """Replica should have all 130 records synced from master."""
        r = redis.Redis(host='127.0.0.1', port=NODE_B_PORT,
                        password=REDIS_PASSWORD, decode_responses=True)
        keys = r.keys('record:*')
        assert len(keys) == 130, f"Replica has {len(keys)} records, expected 130"


class TestSentinels:
    """Verify all Sentinel instances agree on the master."""

    def test_all_sentinels_monitor_node_a(self):
        """All 3 sentinels should monitor mymaster at 127.0.0.1:6379."""
        for port in SENTINEL_PORTS:
            r = redis.Redis(host='127.0.0.1', port=port, decode_responses=True)
            found = False
            for _ in range(15):
                try:
                    result = r.execute_command('SENTINEL', 'MASTER', 'mymaster')
                    info = dict(zip(result[::2], result[1::2]))
                    if (info.get('name') == 'mymaster' and
                            info.get('ip') == '127.0.0.1' and
                            str(info.get('port')) == '6379'):
                        found = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            assert found, \
                f"Sentinel on port {port} does not monitor mymaster at 6379"


class TestReconciliationReport:
    """Verify the reconciliation report is correct and complete."""

    def test_report_exists_and_parseable(self):
        """Reconciliation report should exist and be valid JSON."""
        with open('/app/reconciliation_report.json') as f:
            report = json.load(f)
        assert isinstance(report, dict)
        assert 'total_records' in report
        assert 'conflicts' in report
        assert 'unique_records' in report

    def test_report_total_records(self):
        """Report should indicate 130 total records."""
        with open('/app/reconciliation_report.json') as f:
            report = json.load(f)
        assert report['total_records'] == 130, \
            f"Report says {report['total_records']} total, expected 130"

    def test_report_conflict_counts(self):
        """Report should show 17 conflicts: 8 A wins, 9 B wins."""
        with open('/app/reconciliation_report.json') as f:
            report = json.load(f)
        c = report['conflicts']
        assert c['total'] == 17, f"Expected 17 conflicts, got {c['total']}"
        assert c['node_a_wins'] == 8, f"Expected 8 A wins, got {c['node_a_wins']}"
        assert c['node_b_wins'] == 9, f"Expected 9 B wins, got {c['node_b_wins']}"

    def test_report_conflict_details_complete(self):
        """Report conflict details should list all 17 conflicts."""
        with open('/app/reconciliation_report.json') as f:
            report = json.load(f)
        details = report['conflicts']['details']
        assert len(details) == 17, \
            f"Expected 17 conflict details, got {len(details)}"
        ids = sorted(d['record_id'] for d in details)
        expected_ids = [15, 32, 47, 63, 71, 88, 92,
                        101, 102, 103, 104, 105, 106, 107, 108, 109, 110]
        assert ids == expected_ids, f"Conflict IDs mismatch: {ids} vs {expected_ids}"

    def test_report_conflict_winners(self):
        """Each conflict should have the correct winner."""
        with open('/app/reconciliation_report.json') as f:
            report = json.load(f)
        winners = {d['record_id']: d['winner'] for d in report['conflicts']['details']}
        expected_winners = {
            15: 'node_b', 32: 'node_a', 47: 'node_b', 63: 'node_a',
            71: 'node_b', 88: 'node_a', 92: 'node_b',
            101: 'node_b', 102: 'node_a', 103: 'node_b', 104: 'node_a',
            105: 'node_b', 106: 'node_a', 107: 'node_b', 108: 'node_a',
            109: 'node_b', 110: 'node_a',
        }
        for rec_id, expected in expected_winners.items():
            assert winners.get(rec_id) == expected, \
                f"Record {rec_id} winner should be {expected}, got {winners.get(rec_id)}"

    def test_report_resolution_reasons(self):
        """Each conflict should have the correct resolution_reason."""
        with open('/app/reconciliation_report.json') as f:
            report = json.load(f)
        reasons = {d['record_id']: d['resolution_reason']
                   for d in report['conflicts']['details']}
        expected_reasons = {
            15: 'financial_safety', 32: 'timestamp', 47: 'financial_safety',
            63: 'timestamp', 71: 'financial_safety', 88: 'timestamp',
            92: 'timestamp',
            101: 'timestamp', 102: 'timestamp', 103: 'timestamp',
            104: 'timestamp', 105: 'timestamp', 106: 'timestamp',
            107: 'timestamp', 108: 'timestamp', 109: 'timestamp',
            110: 'timestamp',
        }
        for rec_id, expected in expected_reasons.items():
            assert reasons.get(rec_id) == expected, \
                f"Record {rec_id} reason should be {expected}, got {reasons.get(rec_id)}"

    def test_report_financial_safety_count(self):
        """Exactly 3 conflicts should use financial_safety resolution."""
        with open('/app/reconciliation_report.json') as f:
            report = json.load(f)
        fs_count = sum(1 for d in report['conflicts']['details']
                       if d.get('resolution_reason') == 'financial_safety')
        assert fs_count == 3, \
            f"Expected 3 financial_safety resolutions, got {fs_count}"

    def test_report_unique_records(self):
        """Report should show 10 unique records from each node."""
        with open('/app/reconciliation_report.json') as f:
            report = json.load(f)
        u = report['unique_records']
        assert u['from_node_a'] == 10, f"Expected 10 from A, got {u['from_node_a']}"
        assert u['from_node_b'] == 10, f"Expected 10 from B, got {u['from_node_b']}"

    def test_report_details_sorted(self):
        """Conflict details should be sorted by record_id ascending."""
        with open('/app/reconciliation_report.json') as f:
            report = json.load(f)
        details = report['conflicts']['details']
        ids = [d['record_id'] for d in details]
        assert ids == sorted(ids), "Conflict details must be sorted by record_id"

    def test_report_details_have_timestamps(self):
        """Each conflict detail should include both node timestamps."""
        with open('/app/reconciliation_report.json') as f:
            report = json.load(f)
        for d in report['conflicts']['details']:
            assert 'node_a_updated_at' in d, \
                f"Record {d['record_id']} missing node_a_updated_at"
            assert 'node_b_updated_at' in d, \
                f"Record {d['record_id']} missing node_b_updated_at"
            assert d['node_a_updated_at'].startswith('2024-'), \
                f"Record {d['record_id']} has invalid A timestamp"
            assert d['node_b_updated_at'].startswith('2024-'), \
                f"Record {d['record_id']} has invalid B timestamp"


class TestFlaskApp:
    """Verify the Flask application is operational."""

    def test_app_health(self):
        """Flask app /health should return status ok."""
        resp = requests.get(f'{APP_URL}/health', timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'ok'

    def test_app_record_count(self):
        """App should report exactly 130 records."""
        resp = requests.get(f'{APP_URL}/records/count', timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data['count'] == 130, f"App reports {data['count']} records, expected 130"

    def test_app_serves_individual_records(self):
        """App should serve individual records across the full range."""
        for record_id in [1, 15, 47, 101, 115, 125, 130]:
            resp = requests.get(f'{APP_URL}/records/{record_id}', timeout=10)
            assert resp.status_code == 200, \
                f"Record {record_id} returned {resp.status_code}"
            data = resp.json()
            assert data['id'] == record_id
