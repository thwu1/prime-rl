"""Tests verifying full remediation of the Service Control cascading failure.

All tests must pass for the system to be considered production-ready.
"""


import os
import sys
import time
import sqlite3
import shutil
import tempfile

sys.path.insert(0, "/app")


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _create_test_db(path, include_corrupted=True):
    """Create a throw-away policy database for testing."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS policies (
            policy_id         TEXT PRIMARY KEY,
            project_id        TEXT NOT NULL,
            api_name          TEXT NOT NULL,
            max_requests      INTEGER,
            current_usage     INTEGER DEFAULT 0,
            rate_limit        REAL,
            rate_limit_window REAL,
            enabled           INTEGER DEFAULT 1
        )
    """)
    conn.execute(
        "INSERT INTO policies VALUES "
        "('pol-valid-001','test-project','compute.googleapis.com',"
        "10000,500,100.0,60.0,1)"
    )
    if include_corrupted:
        conn.execute(
            "INSERT INTO policies VALUES "
            "('pol-corrupt-001','test-project','compute.googleapis.com',"
            "NULL,0,NULL,NULL,1)"
        )
    conn.commit()
    conn.close()


def _flush_service_control_modules():
    """Remove cached service_control modules so re-import picks up changes."""
    for name in list(sys.modules):
        if "service_control" in name:
            del sys.modules[name]


# ──────────────────────────────────────────────────────────────────────
# 1.  NULL policy-field handling
# ──────────────────────────────────────────────────────────────────────

class TestNullPolicyHandling:
    """PolicyChecker.check_quota must not crash on NULL policy fields."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db = os.path.join(self._tmpdir, "policies.db")
        _create_test_db(self._db, include_corrupted=True)

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_no_crash_on_null_fields(self):
        """check_quota must survive None max_requests / rate_limit / rate_limit_window."""
        _flush_service_control_modules()
        from service_control.data_store import RegionalDataStore
        from service_control.circuit_breaker import CircuitBreaker
        from service_control.core import PolicyChecker

        store = RegionalDataStore(self._db, "test-region")
        store.connect()
        checker = PolicyChecker(store, CircuitBreaker())

        # Must NOT raise — fail-open on invalid data
        result = checker.check_quota("test-project", "compute.googleapis.com")
        assert result.allowed is True, (
            f"Expected allowed=True (fail-open), got allowed={result.allowed}"
        )

    def test_valid_policy_still_enforced(self):
        """Fixing null handling must not break enforcement of valid policies."""
        _flush_service_control_modules()
        from service_control.data_store import RegionalDataStore
        from service_control.circuit_breaker import CircuitBreaker
        from service_control.core import PolicyChecker

        valid_db = os.path.join(self._tmpdir, "valid.db")
        _create_test_db(valid_db, include_corrupted=False)

        store = RegionalDataStore(valid_db, "test-region")
        store.connect()
        checker = PolicyChecker(store, CircuitBreaker())

        result = checker.check_quota("test-project", "compute.googleapis.com")
        assert result.allowed is True


# ──────────────────────────────────────────────────────────────────────
# 2.  Circuit-breaker bypass
# ──────────────────────────────────────────────────────────────────────

class TestCircuitBreakerBypass:
    """When the circuit breaker is open, check_quota must bypass all
    data-store access and return an allow-all response immediately."""

    def test_circuit_breaker_prevents_crash_on_failing_store(self):
        _flush_service_control_modules()
        from service_control.circuit_breaker import CircuitBreaker
        from service_control.core import PolicyChecker

        class _FailingStore:
            """Simulates a data store that is unavailable during the outage."""
            def get_policies(self, project_id):
                raise RuntimeError("DB unavailable — simulated outage")

        cb = CircuitBreaker()
        cb.trip()  # red-button override

        checker = PolicyChecker(_FailingStore(), cb)
        result = checker.check_quota("test-project", "compute.googleapis.com")

        assert result.allowed is True, (
            "Circuit breaker should allow all requests when open"
        )
        assert "circuit_breaker" in result.reason.lower(), (
            f"Result reason should reference the circuit breaker, "
            f"got: '{result.reason}'"
        )


# ──────────────────────────────────────────────────────────────────────
# 3.  Data validation in the replicator
# ──────────────────────────────────────────────────────────────────────

class TestDataValidation:
    """DataReplicator.replicate() must validate policy data before
    propagating it to regional stores."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_regional_stores(self, regions):
        _flush_service_control_modules()
        from service_control.data_store import RegionalDataStore
        stores = {}
        for region in regions:
            db = os.path.join(self._tmpdir, f"{region}.db")
            conn = sqlite3.connect(db)
            conn.execute("""
                CREATE TABLE policies (
                    policy_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    api_name TEXT NOT NULL, max_requests INTEGER,
                    current_usage INTEGER DEFAULT 0, rate_limit REAL,
                    rate_limit_window REAL, enabled INTEGER DEFAULT 1
                )
            """)
            conn.commit()
            conn.close()
            s = RegionalDataStore(db, region)
            s.connect()
            stores[region] = s
        return stores

    def test_rejects_null_fields(self):
        """replicate() must refuse policies whose required numeric fields are None."""
        from service_control.replicator import DataReplicator

        stores = self._make_regional_stores(["us-east1", "us-central1"])
        replicator = DataReplicator(stores)

        corrupt = {
            "policy_id": "pol-corrupt-test",
            "project_id": "test-project",
            "api_name": "compute.googleapis.com",
            "max_requests": None,
            "rate_limit": None,
            "rate_limit_window": None,
            "enabled": 1,
        }

        results = replicator.replicate(corrupt)

        for region, success in results.items():
            assert success is False, (
                f"Corrupt policy should NOT have been replicated to {region}"
            )

        # Verify nothing was inserted
        for region, store in stores.items():
            cur = store._conn.execute(
                "SELECT COUNT(*) FROM policies "
                "WHERE policy_id='pol-corrupt-test'"
            )
            assert cur.fetchone()[0] == 0, (
                f"Corrupt policy must not exist in {region} store"
            )

    def test_allows_valid_data(self):
        """replicate() must still propagate valid policy data normally."""
        from service_control.replicator import DataReplicator

        stores = self._make_regional_stores(["us-east1"])
        replicator = DataReplicator(stores)

        valid = {
            "policy_id": "pol-valid-test",
            "project_id": "test-project",
            "api_name": "compute.googleapis.com",
            "max_requests": 10000,
            "rate_limit": 100.0,
            "rate_limit_window": 60.0,
            "enabled": 1,
        }

        results = replicator.replicate(valid)
        for region, success in results.items():
            assert success is True, (
                f"Valid policy should have been replicated to {region}"
            )


# ──────────────────────────────────────────────────────────────────────
# 4.  Exponential backoff with jitter
# ──────────────────────────────────────────────────────────────────────

class TestBackoffJitter:
    """ConnectionManager._retry_connect must use exponential backoff
    with randomised jitter, not a fixed delay."""

    def test_retry_delays_have_jitter(self):
        """Sleep durations must not all be identical (fixed delay = no jitter)."""
        recorded: list = []
        original_sleep = time.sleep
        time.sleep = lambda d: recorded.append(d)

        try:
            _flush_service_control_modules()
            from service_control.connection_manager import ConnectionManager

            cm = ConnectionManager(
                "/nonexistent/dir/impossible/test.db", max_retries=8,
            )
            try:
                cm._retry_connect()
            except Exception:
                pass

            assert len(recorded) >= 5, (
                f"Expected >= 5 retry sleeps, got {len(recorded)}"
            )
            unique = set(round(d, 8) for d in recorded)
            assert len(unique) > 1, (
                f"All retry delays are identical ({recorded[0]:.4f} s) — "
                f"no jitter implemented"
            )
        finally:
            time.sleep = original_sleep

    def test_delays_increase_over_time(self):
        """Average delay in the later retries must exceed the earlier ones
        (exponential backoff)."""
        recorded: list = []
        original_sleep = time.sleep
        time.sleep = lambda d: recorded.append(d)

        try:
            _flush_service_control_modules()
            from service_control.connection_manager import ConnectionManager

            cm = ConnectionManager(
                "/nonexistent/dir/impossible/test.db", max_retries=8,
            )
            try:
                cm._retry_connect()
            except Exception:
                pass

            if len(recorded) >= 6:
                n = len(recorded) // 3
                avg_first = sum(recorded[:n]) / n
                avg_last = sum(recorded[-n:]) / n
                assert avg_last > avg_first, (
                    f"Later delays should be larger: "
                    f"first-third avg={avg_first:.4f}, "
                    f"last-third avg={avg_last:.4f}"
                )
        finally:
            time.sleep = original_sleep


# ──────────────────────────────────────────────────────────────────────
# 5.  Database integrity
# ──────────────────────────────────────────────────────────────────────

class TestDatabaseIntegrity:
    """The corrupted policy entry in /app/data/policies.db must be
    removed or updated with valid values."""

    def test_corrupted_policy_handled(self):
        db_path = "/app/data/policies.db"
        if not os.path.exists(db_path):
            return  # nothing to check

        conn = sqlite3.connect(db_path)
        cur = conn.execute(
            "SELECT max_requests, rate_limit, rate_limit_window "
            "FROM policies WHERE policy_id = 'pol-quota-7f3a9b'"
        )
        row = cur.fetchone()
        conn.close()

        if row is None:
            return  # entry was deleted — acceptable

        max_req, rate_lim, rate_win = row
        assert max_req is not None and max_req > 0, (
            f"max_requests must be a positive integer, got {max_req}"
        )
        assert rate_lim is not None and rate_lim > 0, (
            f"rate_limit must be a positive number, got {rate_lim}"
        )
        assert rate_win is not None and rate_win > 0, (
            f"rate_limit_window must be a positive number, got {rate_win}"
        )


# ──────────────────────────────────────────────────────────────────────
# 6.  Health monitor resilience
# ──────────────────────────────────────────────────────────────────────

class TestHealthMonitor:
    """HealthMonitor.check_health must not crash when the underlying
    PolicyChecker raises an exception — it must report degraded status."""

    def test_returns_unhealthy_on_checker_exception(self):
        """When PolicyChecker crashes, check_health must return a dict
        with a non-healthy status instead of propagating the exception."""
        _flush_service_control_modules()
        from service_control.health_monitor import HealthMonitor

        class _CrashingChecker:
            def check_quota(self, project_id, api_name, request_count=1):
                raise TypeError(
                    "unsupported operand type(s) for -: 'NoneType' and 'int'"
                )

        monitor = HealthMonitor(_CrashingChecker())
        result = monitor.check_health()

        assert isinstance(result, dict), (
            f"check_health should return a dict, got {type(result)}"
        )
        assert result.get("status") != "healthy", (
            "check_health should not report 'healthy' when the checker crashes"
        )

    def test_returns_healthy_on_success(self):
        """When PolicyChecker works, check_health must report healthy."""
        _flush_service_control_modules()
        from service_control.health_monitor import HealthMonitor
        from service_control.models import QuotaResult

        class _HealthyChecker:
            def check_quota(self, project_id, api_name, request_count=1):
                return QuotaResult(allowed=True, reason="ok")

        monitor = HealthMonitor(_HealthyChecker())
        result = monitor.check_health()

        assert isinstance(result, dict), (
            f"check_health should return a dict, got {type(result)}"
        )
        assert result.get("status") == "healthy", (
            f"check_health should report 'healthy' when checker succeeds, "
            f"got '{result.get('status')}'"
        )


# ──────────────────────────────────────────────────────────────────────
# 7.  End-to-end integration
# ──────────────────────────────────────────────────────────────────────

class TestIntegration:
    """The system must survive a burst of requests against a data store
    containing corrupt policy entries without any crashes."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db = os.path.join(self._tmpdir, "integration.db")
        _create_test_db(self._db, include_corrupted=True)

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_system_survives_corrupt_data(self):
        _flush_service_control_modules()
        from service_control.data_store import RegionalDataStore
        from service_control.circuit_breaker import CircuitBreaker
        from service_control.core import PolicyChecker

        store = RegionalDataStore(self._db, "integration")
        store.connect()
        checker = PolicyChecker(store, CircuitBreaker())

        crashes = 0
        for _ in range(100):
            try:
                result = checker.check_quota(
                    "test-project", "compute.googleapis.com",
                )
                assert result is not None
            except Exception:
                crashes += 1

        assert crashes == 0, (
            f"System crashed {crashes}/100 requests with corrupt data present"
        )


# ──────────────────────────────────────────────────────────────────────
# 8.  Root cause analysis report
# ──────────────────────────────────────────────────────────────────────

class TestRCAReport:
    """A structured root cause analysis must document all contributing
    factors and explain how they interacted."""

    def test_rca_report_exists(self):
        assert os.path.exists("/app/rca_report.txt"), (
            "Root cause analysis report not found at /app/rca_report.txt"
        )

    def test_rca_report_substance(self):
        with open("/app/rca_report.txt") as f:
            content = f.read()
        assert len(content) >= 500, (
            f"RCA report is too brief ({len(content)} chars) — "
            "expected substantive analysis"
        )

    def test_rca_identifies_root_causes(self):
        """Report must reference at least 4 of the 6 root cause categories."""
        with open("/app/rca_report.txt") as f:
            content = f.read().lower()

        indicators = [
            any(t in content for t in [
                "circuit breaker", "circuit-breaker", "bypass", "red button"
            ]),
            any(t in content for t in [
                "null", "none", "nonetype", "nil field"
            ]),
            any(t in content for t in [
                "backoff", "back-off", "jitter", "thundering herd",
                "thundering-herd", "retry storm"
            ]),
            any(t in content for t in [
                "validat", "replicat", "propagat"
            ]),
            any(t in content for t in [
                "corrupt", "invalid", "malformed"
            ]),
            any(t in content for t in [
                "health", "monitor", "blind spot", "observ"
            ]),
        ]

        found = sum(indicators)
        assert found >= 4, (
            f"RCA report identifies only {found}/6 root cause categories — "
            "expected at least 4"
        )

    def test_rca_discusses_interaction(self):
        """Report must discuss how the failures cascaded or interacted."""
        with open("/app/rca_report.txt") as f:
            content = f.read().lower()

        interaction_terms = [
            "cascad", "interact", "compound", "chain", "amplif",
            "worsen", "escalat", "propagat", "contribut",
        ]
        found = any(term in content for term in interaction_terms)
        assert found, (
            "RCA report should discuss how failures cascaded or interacted"
        )
