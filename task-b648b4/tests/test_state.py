
import pytest
import sqlite3
import sys
import os
import time
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/app")


@pytest.fixture(autouse=True)
def clean_modules():
    """Remove cached modules to ensure fresh imports with any fixes applied."""
    mods_to_remove = [m for m in sys.modules
                      if m.startswith(("service_control", "gateway", "replicator"))]
    for m in mods_to_remove:
        del sys.modules[m]
    yield
    mods_to_remove = [m for m in sys.modules
                      if m.startswith(("service_control", "gateway", "replicator"))]
    for m in mods_to_remove:
        del sys.modules[m]


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary test database with valid seed data."""
    db_path = str(tmp_path / "test_policies.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE active_policies (
            policy_id TEXT PRIMARY KEY,
            service_name TEXT NOT NULL,
            enforcement_mode TEXT,
            quota_limit INTEGER,
            quota_window TEXT,
            description TEXT,
            updated_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO active_policies VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("p001", "compute.googleapis.com", "ENFORCED", 1000, "1m",
         "Compute API quota", "2025-06-01")
    )
    conn.execute(
        "INSERT INTO active_policies VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("p002", "storage.googleapis.com", "SHADOW", 5000, "1m",
         "Storage API quota", "2025-06-01")
    )
    conn.execute(
        "INSERT INTO active_policies VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("p003", "dns.googleapis.com", "DISABLED", 3000, "1m",
         "DNS API quota", "2025-06-01")
    )
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Test Suite 1: Policy Engine must not crash on corrupt data (fail-open)
# ---------------------------------------------------------------------------


class TestPolicyEngineCrashResilience:
    """Service Control must handle corrupt policy data without crashing."""

    def test_null_enforcement_mode_no_crash(self, test_db):
        """Policy engine must not crash when enforcement_mode is NULL."""
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO active_policies VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("bad1", "iam.googleapis.com", None, 100, "1m", "bad", "2025-06-12")
        )
        conn.commit()
        conn.close()

        from service_control.policy_engine import PolicyEngine
        engine = PolicyEngine(test_db)
        result = engine.evaluate_request("iam.googleapis.com", "iam.roles.list")
        assert isinstance(result, dict)
        assert "allowed" in result
        assert result["allowed"] is True, "Must fail open on NULL enforcement_mode"

    def test_blank_enforcement_mode_no_crash(self, test_db):
        """Policy engine must not crash when enforcement_mode is empty string."""
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO active_policies VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("bad2", "logging.googleapis.com", "", 100, "1m", "bad", "2025-06-12")
        )
        conn.commit()
        conn.close()

        from service_control.policy_engine import PolicyEngine
        engine = PolicyEngine(test_db)
        result = engine.evaluate_request("logging.googleapis.com", "entries.list")
        assert isinstance(result, dict)
        assert result["allowed"] is True, "Must fail open on blank enforcement_mode"

    def test_null_quota_limit_no_crash(self, test_db):
        """Policy engine must not crash when quota_limit is NULL."""
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO active_policies VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("bad3", "dns.googleapis.com", "ENFORCED", None, "1m", "bad", "2025-06-12")
        )
        conn.commit()
        conn.close()

        from service_control.policy_engine import PolicyEngine
        engine = PolicyEngine(test_db)
        result = engine.evaluate_request("dns.googleapis.com", "dns.query")
        assert isinstance(result, dict)
        assert "allowed" in result

    def test_null_quota_window_no_crash(self, test_db):
        """Policy engine must not crash when quota_window is NULL."""
        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO active_policies VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("bad4", "pubsub.googleapis.com", "ENFORCED", 500, None, "bad", "2025-06-12")
        )
        conn.commit()
        conn.close()

        from service_control.policy_engine import PolicyEngine
        engine = PolicyEngine(test_db)
        result = engine.evaluate_request("pubsub.googleapis.com", "publish")
        assert isinstance(result, dict)
        assert "allowed" in result

    def test_valid_policies_still_enforced(self, test_db):
        """Valid policies must still work correctly after the fix."""
        from service_control.policy_engine import PolicyEngine
        engine = PolicyEngine(test_db)
        result = engine.evaluate_request("compute.googleapis.com", "instances.create")
        assert isinstance(result, dict)
        assert "allowed" in result
        assert isinstance(result["allowed"], bool)

    def test_mixed_valid_and_corrupt_data(self, test_db):
        """System must handle database with mix of valid and corrupt records."""
        conn = sqlite3.connect(test_db)
        for i in range(5):
            conn.execute(
                "INSERT INTO active_policies VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"corrupt{i}", f"svc{i}.api", None, None, None, "corrupt", "2025-06-12")
            )
        conn.commit()
        conn.close()

        from service_control.policy_engine import PolicyEngine
        engine = PolicyEngine(test_db)

        # Corrupt entries must fail open
        for i in range(5):
            result = engine.evaluate_request(f"svc{i}.api", "method")
            assert result["allowed"] is True, f"Corrupt policy svc{i} must fail open"

        # Valid entry must still work
        result = engine.evaluate_request("compute.googleapis.com", "instances.create")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Test Suite 2: Thundering herd prevention via exponential backoff with jitter
# ---------------------------------------------------------------------------


class TestThunderingHerdPrevention:
    """Gateway workers must use exponential backoff with jitter for reconnection."""

    def _collect_delays(self, n_samples=15):
        """Run _reconnect against a mock server and capture sleep delays."""
        import requests as req_lib
        import gateway.client

        delays = []

        def capture_sleep(d):
            delays.append(d)
            if len(delays) >= n_samples:
                raise InterruptedError("enough samples")

        mock_session = MagicMock()
        mock_session.get.side_effect = req_lib.ConnectionError("refused")

        with patch.object(gateway.client.time, "sleep", side_effect=capture_sleep):
            client = gateway.client.ServiceControlClient("http://localhost:19999")
            client._session = mock_session
            try:
                client._reconnect()
            except (ConnectionError, InterruptedError, req_lib.ConnectionError):
                pass

        return delays

    def test_delays_increase_over_retries(self):
        """Reconnection delays must increase (exponential backoff)."""
        delays = self._collect_delays(15)

        assert len(delays) >= 5, f"Expected at least 5 retries, got {len(delays)}"

        # Compare early delays to later delays
        early_avg = sum(delays[:3]) / 3
        mid_start = min(len(delays) - 3, 8)
        late_avg = sum(delays[mid_start:mid_start + 3]) / 3
        assert late_avg > early_avg * 2, (
            f"Delays must increase over time (exponential backoff). "
            f"Early average: {early_avg:.4f}s, later average: {late_avg:.4f}s"
        )

    def test_delays_have_jitter(self):
        """Reconnection delays must include randomized jitter."""
        all_delay_sequences = []

        for _ in range(5):
            delays = self._collect_delays(10)
            all_delay_sequences.append(tuple(round(d, 10) for d in delays))

        unique = len(set(all_delay_sequences))
        assert unique > 1, (
            "Reconnection delays must include randomized jitter. "
            "Multiple runs produced identical delay sequences."
        )

    def test_no_fixed_100ms_delay(self):
        """Must not use the original fixed 0.1s delay for all retries."""
        delays = self._collect_delays(10)

        all_point_one = all(abs(d - 0.1) < 0.001 for d in delays)
        assert not all_point_one, (
            "All delays are fixed at 0.1s (the original bug). "
            "Must implement exponential backoff with jitter."
        )


# ---------------------------------------------------------------------------
# Test Suite 3: Gateway session cleanup during reconnection
# ---------------------------------------------------------------------------


class TestSessionCleanup:
    """Gateway client must clean up old sessions during reconnection."""

    def test_old_session_closed_on_reconnect(self):
        """Old requests.Session must be closed when creating a new one."""
        import requests as req_lib
        import gateway.client

        client = gateway.client.ServiceControlClient("http://localhost:19999")

        # Replace session with a trackable mock
        old_session = MagicMock()
        client._session = old_session

        # Stop after first sleep to keep test fast
        with patch.object(gateway.client.time, "sleep",
                          side_effect=InterruptedError("stop")):
            try:
                client._reconnect()
            except (ConnectionError, InterruptedError, req_lib.ConnectionError):
                pass

        # The old session must have been closed before replacement
        old_session.close.assert_called()


# ---------------------------------------------------------------------------
# Test Suite 4: Policy replicator must validate data before insertion
# ---------------------------------------------------------------------------


class TestPolicyValidation:
    """Replicator must validate policy data before inserting into database."""

    def test_rejects_null_enforcement_mode(self, test_db):
        """Must reject policies with NULL enforcement_mode."""
        from replicator.sync import PolicyReplicator
        replicator = PolicyReplicator(test_db)

        result = replicator.replicate_policy({
            "policy_id": "test_bad1",
            "service_name": "test.api",
            "enforcement_mode": None,
            "quota_limit": 100,
            "quota_window": "1m",
        })

        assert not result.get("accepted", True), \
            "Must reject policies with NULL enforcement_mode"

    def test_rejects_blank_enforcement_mode(self, test_db):
        """Must reject policies with blank enforcement_mode."""
        from replicator.sync import PolicyReplicator
        replicator = PolicyReplicator(test_db)

        result = replicator.replicate_policy({
            "policy_id": "test_bad2",
            "service_name": "test.api",
            "enforcement_mode": "",
            "quota_limit": 100,
            "quota_window": "1m",
        })

        assert not result.get("accepted", True), \
            "Must reject policies with blank enforcement_mode"

    def test_rejects_missing_required_fields(self, test_db):
        """Must reject policies with missing required fields."""
        from replicator.sync import PolicyReplicator
        replicator = PolicyReplicator(test_db)

        result = replicator.replicate_policy({
            "policy_id": "test_bad3",
            # Missing service_name, enforcement_mode, quota_limit, quota_window
        })

        assert not result.get("accepted", True), \
            "Must reject policies with missing required fields"

    def test_rejects_null_service_name(self, test_db):
        """Must reject policies with NULL service_name."""
        from replicator.sync import PolicyReplicator
        replicator = PolicyReplicator(test_db)

        result = replicator.replicate_policy({
            "policy_id": "test_bad4",
            "service_name": None,
            "enforcement_mode": "ENFORCED",
            "quota_limit": 100,
            "quota_window": "1m",
        })

        assert not result.get("accepted", True), \
            "Must reject policies with NULL service_name"

    def test_accepts_valid_policy(self, test_db):
        """Must accept valid policy data."""
        from replicator.sync import PolicyReplicator
        replicator = PolicyReplicator(test_db)

        result = replicator.replicate_policy({
            "policy_id": "test_good",
            "service_name": "compute.googleapis.com",
            "enforcement_mode": "ENFORCED",
            "quota_limit": 1000,
            "quota_window": "1m",
            "description": "valid policy",
            "updated_at": "2025-06-12"
        })

        assert result.get("accepted") is True, "Must accept valid policy data"

    def test_rejected_policy_not_persisted(self, test_db):
        """Rejected policies must NOT be written to the database."""
        from replicator.sync import PolicyReplicator
        replicator = PolicyReplicator(test_db)

        replicator.replicate_policy({
            "policy_id": "test_rejected",
            "service_name": "test.api",
            "enforcement_mode": None,
            "quota_limit": 100,
            "quota_window": "1m",
        })

        conn = sqlite3.connect(test_db)
        row = conn.execute(
            "SELECT * FROM active_policies WHERE policy_id = 'test_rejected'"
        ).fetchone()
        conn.close()

        assert row is None, "Rejected policy must NOT be persisted to database"

    def test_valid_policy_persisted(self, test_db):
        """Accepted valid policies must be written to the database."""
        from replicator.sync import PolicyReplicator
        replicator = PolicyReplicator(test_db)

        replicator.replicate_policy({
            "policy_id": "test_persist",
            "service_name": "test.api",
            "enforcement_mode": "ENFORCED",
            "quota_limit": 500,
            "quota_window": "1h",
            "description": "persistence test",
            "updated_at": "2025-06-12"
        })

        conn = sqlite3.connect(test_db)
        row = conn.execute(
            "SELECT * FROM active_policies WHERE policy_id = 'test_persist'"
        ).fetchone()
        conn.close()

        assert row is not None, "Valid policy must be persisted to database"


# ---------------------------------------------------------------------------
# Test Suite 5: Replicator batch operations must also validate
# ---------------------------------------------------------------------------


class TestBatchValidation:
    """Replicator batch operations must validate each entry individually."""

    def test_batch_rejects_invalid_entries(self, test_db):
        """Batch replication must reject entries with invalid required fields."""
        from replicator.sync import PolicyReplicator
        replicator = PolicyReplicator(test_db)

        policies = [
            {
                "policy_id": "batch_good",
                "service_name": "test.api",
                "enforcement_mode": "ENFORCED",
                "quota_limit": 100,
                "quota_window": "1m",
                "description": "valid",
                "updated_at": "2025-06-12"
            },
            {
                "policy_id": "batch_bad",
                "service_name": "test.api",
                "enforcement_mode": None,
                "quota_limit": 100,
                "quota_window": "1m",
            },
        ]

        results = replicator.replicate_batch(policies)
        assert len(results) == 2
        assert results[0].get("accepted") is True, \
            "Valid entry in batch must be accepted"
        assert results[1].get("accepted") is not True, \
            "Invalid entry in batch must be rejected"

    def test_batch_selective_persistence(self, test_db):
        """In a mixed batch, valid entries persist and invalid entries do not."""
        from replicator.sync import PolicyReplicator
        replicator = PolicyReplicator(test_db)

        policies = [
            {
                "policy_id": "batch_persist_good",
                "service_name": "test.api",
                "enforcement_mode": "ENFORCED",
                "quota_limit": 200,
                "quota_window": "1m",
                "description": "valid",
                "updated_at": "2025-06-12"
            },
            {
                "policy_id": "batch_persist_bad",
                "service_name": "test.api",
                "enforcement_mode": "",
                "quota_limit": 100,
                "quota_window": "1m",
            },
        ]

        replicator.replicate_batch(policies)

        conn = sqlite3.connect(test_db)
        good_row = conn.execute(
            "SELECT * FROM active_policies WHERE policy_id = 'batch_persist_good'"
        ).fetchone()
        bad_row = conn.execute(
            "SELECT * FROM active_policies WHERE policy_id = 'batch_persist_bad'"
        ).fetchone()
        conn.close()

        assert good_row is not None, "Valid entry in batch must be persisted"
        assert bad_row is None, "Invalid entry in batch must NOT be persisted"

    def test_batch_all_invalid_none_persisted(self, test_db):
        """Batch with all invalid entries must reject all and persist none."""
        from replicator.sync import PolicyReplicator
        replicator = PolicyReplicator(test_db)

        policies = [
            {
                "policy_id": "batch_allinvalid_1",
                "service_name": "svc1.api",
                "enforcement_mode": None,
                "quota_limit": 100,
                "quota_window": "1m",
            },
            {
                "policy_id": "batch_allinvalid_2",
                "service_name": "svc2.api",
                "enforcement_mode": "",
                "quota_limit": 100,
                "quota_window": "1m",
            },
        ]

        results = replicator.replicate_batch(policies)
        assert all(not r.get("accepted", True) for r in results), \
            "All invalid entries in batch must be rejected"

        conn = sqlite3.connect(test_db)
        rows = conn.execute(
            "SELECT * FROM active_policies WHERE policy_id LIKE 'batch_allinvalid_%'"
        ).fetchall()
        conn.close()

        assert len(rows) == 0, "No invalid entries from batch should be persisted"
