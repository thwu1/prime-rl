"""
Tests for idempotency key processing engine with atomic phases and recovery points.
"""

import pytest
import psycopg2
import psycopg2.extras
import json
import threading
import sys
import time

sys.path.insert(0, '/app')

DB_PARAMS = {'dbname': 'idempotency', 'user': 'postgres', 'host': '127.0.0.1'}

RIDE_PARAMS = {
    'origin_lat': 37.7749,
    'origin_lon': -122.4194,
    'target_lat': 37.3382,
    'target_lon': -121.8863
}


@pytest.fixture(autouse=True)
def clean_tables():
    """Truncate all tables and insert a test user before each test."""
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "TRUNCATE users, idempotency_keys, rides, audit_records, "
        "staged_jobs, charges RESTART IDENTITY CASCADE"
    )
    cur.execute(
        "INSERT INTO users (id, email, stripe_customer_id) "
        "VALUES (1, 'test@example.com', 'cus_test123')"
    )
    cur.close()
    conn.close()
    yield


def _db_query(sql, params=None):
    """Helper to run a query and return all rows."""
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def _db_scalar(sql, params=None):
    """Helper to run a query and return a single scalar value."""
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(sql, params)
    val = cur.fetchone()[0]
    cur.close()
    conn.close()
    return val


def _db_exec(sql, params=None):
    """Helper to execute a statement."""
    conn = psycopg2.connect(**DB_PARAMS)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(sql, params)
    cur.close()
    conn.close()


class TestFullLifecycle:
    """Test the complete happy-path request lifecycle."""

    def test_returns_success(self):
        from idempotency import process_ride_request
        result = process_ride_request(
            user_id=1, idempotency_key='lifecycle-1', request_params=RIDE_PARAMS
        )
        assert result['status_code'] == 201
        assert 'ride_id' in result['body']
        assert 'charge_id' in result['body']

    def test_sets_finished_recovery_point(self):
        from idempotency import process_ride_request
        process_ride_request(
            user_id=1, idempotency_key='lifecycle-2', request_params=RIDE_PARAMS
        )
        rp = _db_scalar(
            "SELECT recovery_point FROM idempotency_keys "
            "WHERE idempotency_key = 'lifecycle-2'"
        )
        assert rp == 'finished'

    def test_creates_ride_and_audit(self):
        from idempotency import process_ride_request
        process_ride_request(
            user_id=1, idempotency_key='lifecycle-3', request_params=RIDE_PARAMS
        )
        assert _db_scalar("SELECT COUNT(*) FROM rides WHERE user_id = 1") == 1
        assert _db_scalar("SELECT COUNT(*) FROM audit_records WHERE user_id = 1") == 1

    def test_creates_charge(self):
        from idempotency import process_ride_request
        process_ride_request(
            user_id=1, idempotency_key='lifecycle-4', request_params=RIDE_PARAMS
        )
        assert _db_scalar("SELECT COUNT(*) FROM charges") == 1
        charge = _db_query("SELECT * FROM charges")[0]
        assert charge['amount'] == 2000
        assert charge['currency'] == 'usd'
        assert charge['id'].startswith('ch_')

    def test_stages_receipt_job(self):
        from idempotency import process_ride_request
        process_ride_request(
            user_id=1, idempotency_key='lifecycle-5', request_params=RIDE_PARAMS
        )
        assert _db_scalar(
            "SELECT COUNT(*) FROM staged_jobs WHERE job_name = 'send_ride_receipt'"
        ) == 1


class TestRetry:
    """Test idempotent retry behavior."""

    def test_retry_returns_cached_response(self):
        from idempotency import process_ride_request
        r1 = process_ride_request(
            user_id=1, idempotency_key='retry-1', request_params=RIDE_PARAMS
        )
        r2 = process_ride_request(
            user_id=1, idempotency_key='retry-1', request_params=RIDE_PARAMS
        )
        assert r1['status_code'] == r2['status_code']
        assert r1['body'] == r2['body']

    def test_retry_does_not_duplicate_data(self):
        from idempotency import process_ride_request
        process_ride_request(
            user_id=1, idempotency_key='retry-2', request_params=RIDE_PARAMS
        )
        process_ride_request(
            user_id=1, idempotency_key='retry-2', request_params=RIDE_PARAMS
        )
        assert _db_scalar("SELECT COUNT(*) FROM rides WHERE user_id = 1") == 1
        assert _db_scalar("SELECT COUNT(*) FROM charges") == 1


class TestParameterMismatch:
    """Test that different params with same key raises ParameterMismatch."""

    def test_raises_on_mismatch(self):
        from idempotency import process_ride_request, ParameterMismatch
        params2 = dict(RIDE_PARAMS, origin_lat=40.7128, origin_lon=-74.0060)
        process_ride_request(
            user_id=1, idempotency_key='mismatch-1', request_params=RIDE_PARAMS
        )
        with pytest.raises(ParameterMismatch):
            process_ride_request(
                user_id=1, idempotency_key='mismatch-1', request_params=params2
            )


class TestCrashRecovery:
    """Test crash recovery via recovery points."""

    def test_crash_at_ride_created_persists_recovery_point(self):
        from idempotency import process_ride_request, CrashSimulation
        with pytest.raises(CrashSimulation):
            process_ride_request(
                user_id=1, idempotency_key='crash-ride-1',
                request_params=RIDE_PARAMS, simulate_crash_at='ride_created'
            )
        rp = _db_scalar(
            "SELECT recovery_point FROM idempotency_keys "
            "WHERE idempotency_key = 'crash-ride-1'"
        )
        assert rp == 'ride_created'

    def test_crash_at_ride_created_has_ride_but_no_charge(self):
        from idempotency import process_ride_request, CrashSimulation
        with pytest.raises(CrashSimulation):
            process_ride_request(
                user_id=1, idempotency_key='crash-ride-2',
                request_params=RIDE_PARAMS, simulate_crash_at='ride_created'
            )
        assert _db_scalar("SELECT COUNT(*) FROM rides WHERE user_id = 1") == 1
        assert _db_scalar("SELECT COUNT(*) FROM charges") == 0

    def test_retry_after_crash_at_ride_created_succeeds(self):
        from idempotency import process_ride_request, CrashSimulation
        with pytest.raises(CrashSimulation):
            process_ride_request(
                user_id=1, idempotency_key='crash-ride-3',
                request_params=RIDE_PARAMS, simulate_crash_at='ride_created'
            )
        result = process_ride_request(
            user_id=1, idempotency_key='crash-ride-3', request_params=RIDE_PARAMS
        )
        assert result['status_code'] == 201
        assert _db_scalar("SELECT COUNT(*) FROM rides WHERE user_id = 1") == 1
        assert _db_scalar("SELECT COUNT(*) FROM charges") == 1

    def test_crash_at_charge_created_persists_state(self):
        from idempotency import process_ride_request, CrashSimulation
        with pytest.raises(CrashSimulation):
            process_ride_request(
                user_id=1, idempotency_key='crash-charge-1',
                request_params=RIDE_PARAMS, simulate_crash_at='charge_created'
            )
        rp = _db_scalar(
            "SELECT recovery_point FROM idempotency_keys "
            "WHERE idempotency_key = 'crash-charge-1'"
        )
        assert rp == 'charge_created'
        assert _db_scalar("SELECT COUNT(*) FROM rides") == 1
        assert _db_scalar("SELECT COUNT(*) FROM charges") == 1
        assert _db_scalar("SELECT COUNT(*) FROM staged_jobs") == 0

    def test_retry_after_crash_at_charge_created_succeeds(self):
        from idempotency import process_ride_request, CrashSimulation
        with pytest.raises(CrashSimulation):
            process_ride_request(
                user_id=1, idempotency_key='crash-charge-2',
                request_params=RIDE_PARAMS, simulate_crash_at='charge_created'
            )
        result = process_ride_request(
            user_id=1, idempotency_key='crash-charge-2', request_params=RIDE_PARAMS
        )
        assert result['status_code'] == 201
        assert _db_scalar(
            "SELECT COUNT(*) FROM staged_jobs WHERE job_name = 'send_ride_receipt'"
        ) == 1


class TestConcurrency:
    """Test concurrent request handling."""

    def test_concurrent_same_key_creates_exactly_one_ride(self):
        from idempotency import process_ride_request

        results = []
        errors = []
        barrier = threading.Barrier(2, timeout=15)

        def make_request():
            try:
                barrier.wait()
                r = process_ride_request(
                    user_id=1, idempotency_key='concurrent-1',
                    request_params=RIDE_PARAMS
                )
                results.append(r)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=make_request)
        t2 = threading.Thread(target=make_request)
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        ride_count = _db_scalar("SELECT COUNT(*) FROM rides WHERE user_id = 1")
        charge_count = _db_scalar("SELECT COUNT(*) FROM charges")
        assert ride_count == 1, f"Expected 1 ride, got {ride_count}"
        assert charge_count == 1, f"Expected 1 charge, got {charge_count}"


class TestStagedJobVisibility:
    """Test that staged jobs follow transactional staging semantics."""

    def test_no_staged_jobs_before_finish_phase(self):
        from idempotency import process_ride_request, CrashSimulation
        with pytest.raises(CrashSimulation):
            process_ride_request(
                user_id=1, idempotency_key='staged-1',
                request_params=RIDE_PARAMS, simulate_crash_at='charge_created'
            )
        assert _db_scalar("SELECT COUNT(*) FROM staged_jobs") == 0


class TestCompleter:
    """Test the completer process for stale requests."""

    def test_completer_finishes_stale_request(self):
        from idempotency import process_ride_request, CrashSimulation, complete_stale_requests
        with pytest.raises(CrashSimulation):
            process_ride_request(
                user_id=1, idempotency_key='stale-1',
                request_params=RIDE_PARAMS, simulate_crash_at='ride_created'
            )
        # Backdate to make it look stale
        _db_exec(
            "UPDATE idempotency_keys "
            "SET locked_at = now() - interval '10 minutes', "
            "    last_run_at = now() - interval '10 minutes' "
            "WHERE idempotency_key = 'stale-1'"
        )
        completed = complete_stale_requests(staleness_threshold_seconds=60)
        assert completed >= 1
        rp = _db_scalar(
            "SELECT recovery_point FROM idempotency_keys "
            "WHERE idempotency_key = 'stale-1'"
        )
        assert rp == 'finished'
        resp_code = _db_scalar(
            "SELECT response_code FROM idempotency_keys "
            "WHERE idempotency_key = 'stale-1'"
        )
        assert resp_code == 201


class TestReaper:
    """Test the reaper process for old finished keys."""

    def test_reaper_removes_old_finished_keys(self):
        from idempotency import process_ride_request, reap_old_keys
        process_ride_request(
            user_id=1, idempotency_key='old-1', request_params=RIDE_PARAMS
        )
        # Backdate to make it old
        _db_exec(
            "UPDATE idempotency_keys "
            "SET created_at = now() - interval '4 days' "
            "WHERE idempotency_key = 'old-1'"
        )
        reaped = reap_old_keys(age_threshold_hours=72)
        assert reaped >= 1
        assert _db_scalar(
            "SELECT COUNT(*) FROM idempotency_keys WHERE idempotency_key = 'old-1'"
        ) == 0

    def test_reaper_preserves_ride_with_null_fk(self):
        from idempotency import process_ride_request, reap_old_keys
        process_ride_request(
            user_id=1, idempotency_key='old-2', request_params=RIDE_PARAMS
        )
        _db_exec(
            "UPDATE idempotency_keys "
            "SET created_at = now() - interval '4 days' "
            "WHERE idempotency_key = 'old-2'"
        )
        reap_old_keys(age_threshold_hours=72)
        ride_count = _db_scalar("SELECT COUNT(*) FROM rides WHERE user_id = 1")
        assert ride_count == 1
        fk = _db_scalar(
            "SELECT idempotency_key_id FROM rides WHERE user_id = 1"
        )
        assert fk is None
