#!/usr/bin/env python3
"""Automated remediation for the Service Control cascading failure.

Applies all six fixes identified through root cause analysis:
1. PolicyChecker.check_quota  — circuit breaker first, null-safe, fail-open
2. DataReplicator.replicate   — validate before propagating
3. ConnectionManager          — exponential backoff with jitter
4. HealthMonitor              — exception handling in check_health
5. Database                   — remove the corrupted policy entry
6. RCA report                 — document all contributing factors
"""


import os
import sqlite3
import textwrap

APP = "/app"
SC = os.path.join(APP, "service_control")

# ──────────────────────────────────────────────────────────────────────
# Fix 1 — core.py
# ──────────────────────────────────────────────────────────────────────

FIXED_CORE = textwrap.dedent('''\
    """Core policy-checking engine for the Service Control system.

    PolicyChecker is the central component that evaluates every incoming API
    request against the project\'s quota and rate-limit policies.  It reads
    policy data from a RegionalDataStore and is protected by a CircuitBreaker
    that should allow emergency bypass of all checks.
    """

    import logging

    from .models import QuotaResult
    from .data_store import RegionalDataStore
    from .circuit_breaker import CircuitBreaker

    logger = logging.getLogger(__name__)


    class PolicyChecker:
        """Evaluates API requests against quota and rate-limit policies."""

        def __init__(self, data_store: RegionalDataStore,
                     circuit_breaker: CircuitBreaker):
            self.data_store = data_store
            self.circuit_breaker = circuit_breaker
            self._consecutive_failures = 0

        def check_quota(self, project_id: str, api_name: str,
                        request_count: int = 1) -> QuotaResult:
            """Check whether a request is within quota and rate limits.

            Design contract
            ---------------
            * If any check **cannot** be performed (data error, store
              unavailable, etc.) the request MUST be **allowed** — this is
              the fail-open principle.
            * When the circuit breaker is open the method MUST return an
              allow-all result **without** touching the data store.
            """
            # ── circuit-breaker bypass — checked FIRST ──────────────
            if self.circuit_breaker.is_open:
                logger.warning("Circuit breaker is open, bypassing checks")
                return QuotaResult(allowed=True,
                                   reason="circuit_breaker_bypass")

            try:
                policies = self.data_store.get_policies(project_id)

                for policy in policies:
                    if policy.api_name == api_name or policy.api_name == "*":
                        # ── validate fields before arithmetic ───────
                        if (policy.max_requests is None
                                or policy.rate_limit is None
                                or policy.rate_limit_window is None):
                            logger.warning(
                                "Policy %s has None fields — skipping",
                                policy.policy_id,
                            )
                            continue
                        if policy.rate_limit_window <= 0:
                            logger.warning(
                                "Policy %s has invalid rate_limit_window — skipping",
                                policy.policy_id,
                            )
                            continue

                        # --- quota check ---
                        remaining = policy.max_requests - policy.current_usage
                        if remaining < request_count:
                            return QuotaResult(
                                allowed=False,
                                reason="quota_exceeded",
                                remaining=max(0, remaining),
                            )

                        # --- rate-limit check ---
                        effective_rate = request_count / policy.rate_limit_window
                        if effective_rate > policy.rate_limit:
                            return QuotaResult(
                                allowed=False,
                                reason="rate_limited",
                                remaining=remaining,
                            )

                self._consecutive_failures = 0
                return QuotaResult(allowed=True, remaining=-1)

            except Exception as e:
                self._consecutive_failures += 1
                self.circuit_breaker.record_failure()
                logger.error("PolicyChecker error: %s", e)
                # Fail open — allow the request when checks cannot be performed
                return QuotaResult(allowed=True, reason="error_fail_open")
''')

# ──────────────────────────────────────────────────────────────────────
# Fix 2 — replicator.py
# ──────────────────────────────────────────────────────────────────────

FIXED_REPLICATOR = textwrap.dedent('''\
    """Policy data replicator.

    Replicates policy updates across all regional data stores so that quota
    enforcement is consistent globally.  Data integrity is paramount —
    corrupt or incomplete policy records propagating to every region can
    cause Service Control to malfunction worldwide.
    """

    import logging
    from typing import Dict, List, Optional, Tuple

    from .data_store import RegionalDataStore

    logger = logging.getLogger(__name__)

    REQUIRED_POLICY_FIELDS = [
        \'policy_id\', \'project_id\', \'api_name\',
        \'max_requests\', \'rate_limit\', \'rate_limit_window\',
    ]


    class DataReplicator:
        """Replicates policy data to regional stores."""

        def __init__(self, regional_stores: Dict[str, RegionalDataStore]):
            self.regional_stores = regional_stores
            self._replication_log: list = []

        def replicate(self, policy_data: dict,
                      target_regions: Optional[List[str]] = None) -> Dict[str, bool]:
            """Replicate *policy_data* to every target region.

            Returns a dict mapping region name -> success boolean.
            Data is validated before propagation; invalid data is rejected
            for ALL regions.
            """
            if target_regions is None:
                target_regions = list(self.regional_stores.keys())

            # ── validate BEFORE propagating ─────────────────────────
            is_valid, error_msg = self.validate_policy_data(policy_data)
            if not is_valid:
                logger.error(
                    "Rejecting replication of invalid policy data: %s",
                    error_msg,
                )
                return {region: False for region in target_regions}

            results: Dict[str, bool] = {}

            for region in target_regions:
                if region not in self.regional_stores:
                    logger.warning("Unknown region: %s", region)
                    results[region] = False
                    continue

                try:
                    store = self.regional_stores[region]
                    store.insert_policy(policy_data)
                    results[region] = True
                    self._replication_log.append({
                        \'region\': region,
                        \'policy_id\': policy_data.get(\'policy_id\'),
                        \'status\': \'success\',
                    })
                    logger.info("Replicated policy %s to %s",
                                policy_data.get(\'policy_id\'), region)
                except Exception as e:
                    results[region] = False
                    self._replication_log.append({
                        \'region\': region,
                        \'policy_id\': policy_data.get(\'policy_id\'),
                        \'status\': \'failed\',
                        \'error\': str(e),
                    })
                    logger.error("Failed to replicate to %s: %s", region, e)

            return results

        def validate_policy_data(self, policy_data: dict) -> Tuple[bool, str]:
            """Validate that *policy_data* is safe to replicate.

            Returns ``(is_valid, error_message)``.
            """
            errors: List[str] = []

            for field in REQUIRED_POLICY_FIELDS:
                if field not in policy_data:
                    errors.append(f"Missing required field: {field}")
                elif policy_data[field] is None:
                    errors.append(f"Field \'{field}\' cannot be None")

            for field in (\'max_requests\', \'rate_limit\', \'rate_limit_window\'):
                val = policy_data.get(field)
                if val is not None:
                    try:
                        if float(val) <= 0:
                            errors.append(
                                f"Field \'{field}\' must be positive, got {val}")
                    except (ValueError, TypeError):
                        errors.append(
                            f"Field \'{field}\' must be numeric, got {val}")

            if errors:
                return False, "; ".join(errors)
            return True, ""
''')

# ──────────────────────────────────────────────────────────────────────
# Fix 3 — connection_manager.py
# ──────────────────────────────────────────────────────────────────────

FIXED_CONN_MGR = textwrap.dedent('''\
    """Database connection management with retry logic.

    Manages a pool of SQLite connections and retries failed connection
    attempts.  Uses exponential backoff with random jitter to prevent
    thundering-herd effects during recovery.
    """

    import time
    import random
    import sqlite3
    import logging
    import threading
    from typing import Optional, List

    logger = logging.getLogger(__name__)


    class ConnectionManager:

        def __init__(self, db_path: str, max_connections: int = 10,
                     max_retries: int = 10):
            self.db_path = db_path
            self.max_connections = max_connections
            self.max_retries = max_retries
            self._pool: List[sqlite3.Connection] = []
            self._active = 0
            self._lock = threading.Lock()
            self._retry_history: List[float] = []

        def get_connection(self) -> sqlite3.Connection:
            with self._lock:
                if self._pool:
                    conn = self._pool.pop()
                    self._active += 1
                    return conn
            return self._retry_connect()

        def release_connection(self, conn: sqlite3.Connection):
            with self._lock:
                self._active -= 1
                if len(self._pool) < self.max_connections:
                    self._pool.append(conn)
                else:
                    conn.close()

        def close_all(self):
            with self._lock:
                for conn in self._pool:
                    conn.close()
                self._pool.clear()

        def _retry_connect(self) -> sqlite3.Connection:
            """Connect with exponential backoff and random jitter."""
            base_delay = 0.1
            for attempt in range(self.max_retries):
                try:
                    conn = sqlite3.connect(self.db_path, timeout=5)
                    conn.row_factory = sqlite3.Row
                    with self._lock:
                        self._active += 1
                        self._retry_history.append(time.time())
                    return conn
                except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
                    logger.warning(
                        "Connection attempt %d/%d failed: %s",
                        attempt + 1, self.max_retries, e,
                    )
                    self._retry_history.append(time.time())
                    # Exponential backoff with jitter
                    delay = min(base_delay * (2 ** attempt), 30.0)
                    jitter = random.uniform(0, delay * 0.5)
                    time.sleep(delay + jitter)

            raise ConnectionError(
                f"Failed to connect to {self.db_path} after "
                f"{self.max_retries} attempts"
            )

        def get_retry_delays(self) -> List[float]:
            if len(self._retry_history) < 2:
                return []
            return [
                self._retry_history[i + 1] - self._retry_history[i]
                for i in range(len(self._retry_history) - 1)
            ]
''')

# ──────────────────────────────────────────────────────────────────────
# Fix 4 — health_monitor.py
# ──────────────────────────────────────────────────────────────────────

FIXED_HEALTH_MONITOR = textwrap.dedent('''\
    """Health monitoring for the Service Control system.

    Performs periodic health checks by executing a test quota check against
    the live data store.  Results are exposed to the API Gateway for
    upstream health-check probes.
    """

    import json
    import os
    import logging
    import time

    logger = logging.getLogger(__name__)

    HEALTH_STATUS_PATH = "/app/data/health_status.json"


    class HealthMonitor:
        """Monitors Service Control health via test quota checks."""

        def __init__(self, policy_checker):
            self.policy_checker = policy_checker
            self._last_check_time = 0
            self._consecutive_failures = 0

        def check_health(self) -> dict:
            """Run a health check and return status.

            Must never crash — a crashing health check creates a monitoring
            blind spot during incidents when visibility is most critical.
            """
            try:
                result = self.policy_checker.check_quota(
                    "health-check-project", "health.googleapis.com"
                )
                self._last_check_time = time.time()
                self._consecutive_failures = 0
                return {
                    "status": "healthy",
                    "last_check": self._last_check_time,
                    "details": "quota check passed",
                }
            except Exception as e:
                self._last_check_time = time.time()
                self._consecutive_failures += 1
                logger.error("Health check failed: %s", e)
                return {
                    "status": "unhealthy",
                    "last_check": self._last_check_time,
                    "error": str(e),
                    "consecutive_failures": self._consecutive_failures,
                    "details": "quota check failed",
                }

        def write_status(self, status: dict):
            """Write health status to disk for the API Gateway."""
            os.makedirs(os.path.dirname(HEALTH_STATUS_PATH), exist_ok=True)
            with open(HEALTH_STATUS_PATH, \'w\') as f:
                json.dump(status, f)
''')

# ──────────────────────────────────────────────────────────────────────
# Fix 5 — RCA report
# ──────────────────────────────────────────────────────────────────────

RCA_REPORT = """\
ROOT CAUSE ANALYSIS — Service Control Cascading Failure
========================================================

Date: 2025-06-12
Duration: ~1h 30min (17:45 UTC — 19:15 UTC)
Severity: Sev-1 global outage
Affected: All API-serving paths (60+ products)

EXECUTIVE SUMMARY
------------------
A corrupted policy entry with NULL/None numeric fields was replicated to all
regional data stores without validation. The policy triggered an unhandled
TypeError in PolicyChecker.check_quota(), causing a global crash loop. The
circuit breaker emergency override failed to mitigate because its check was
evaluated after the crash point. Recovery was prolonged by thundering-herd
database contention from fixed-interval connection retries. The health
monitoring subsystem crashed alongside the main service, creating a monitoring
blind spot that delayed detection and complicated triage.

CONTRIBUTING FACTORS
---------------------

1. Missing data validation in the replication pipeline
   - DataReplicator.replicate() propagated policy data to all 6 regions
     without calling the existing validate_policy_data() method
   - Policy pol-quota-7f3a9b contained NULL values for max_requests,
     rate_limit, and rate_limit_window
   - The corrupt data reached all regions within 3 seconds

2. Unhandled None/NULL fields in PolicyChecker
   - check_quota() performed arithmetic (policy.max_requests - policy.current_usage)
     without null-checking, causing a TypeError
   - The exception handler re-raised instead of failing open per the design contract
   - Every request matching the corrupt policy crashed the process

3. Circuit breaker bypass evaluated too late
   - The circuit_breaker.is_open check was placed AFTER the data store access
     and arithmetic that caused the crash
   - When the red button was activated, the crash occurred before the bypass
     check could execute, rendering the emergency override useless

4. Fixed-interval retry causing thundering herd
   - ConnectionManager._retry_connect() used a fixed 0.5s delay with no
     randomization or exponential backoff
   - Hundreds of restarting instances all hit the database on the same cadence
   - This created sustained overload that prevented manual remediation

5. Health monitor crash propagation
   - HealthMonitor.check_health() called PolicyChecker.check_quota() without
     exception handling
   - When the checker crashed, the health monitor also crashed instead of
     reporting degraded status
   - This eliminated visibility into system status during the outage, creating
     a monitoring blind spot

6. Corrupted database entry
   - Policy pol-quota-7f3a9b remained in /app/data/policies.db with NULL fields
   - Even after code fixes, the entry would continue triggering issues until
     removed or corrected

CASCADING INTERACTION
----------------------
These factors compounded into a cascading failure: the missing replication
validation (1) allowed corrupt data to propagate globally, which triggered
the null-handling crash (2) in all regions simultaneously. The misplaced
circuit breaker (3) prevented the standard emergency response from working.
During recovery, the thundering herd (4) overwhelmed databases and blocked
manual intervention. Throughout the entire incident, the health monitor
crash (5) created a blind spot that delayed initial detection and complicated
ongoing triage. The corrupted database entry (6) ensured the crash would
recur on every restart until manually removed.

CHANGES MADE
-------------
- Moved circuit breaker check to the top of check_quota() (before data access)
- Added null-field guards and fail-open behavior in check_quota()
- Integrated validate_policy_data() call at the start of replicate()
- Replaced fixed 0.5s retry with exponential backoff + random jitter
- Added exception handling in HealthMonitor.check_health()
- Removed corrupted policy pol-quota-7f3a9b from the production database
"""


# ──────────────────────────────────────────────────────────────────────
# Apply
# ──────────────────────────────────────────────────────────────────────

def write(path, content):
    with open(path, "w") as f:
        f.write(content)
    print(f"  [fixed] {path}")


def fix_database():
    db = os.path.join(APP, "data", "policies.db")
    if not os.path.exists(db):
        print("  [skip]  database not found")
        return
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM policies WHERE policy_id = 'pol-quota-7f3a9b'")
    conn.commit()
    conn.close()
    print(f"  [fixed] removed corrupted policy from {db}")


def main():
    print("Applying cascading-failure remediation…")
    write(os.path.join(SC, "core.py"), FIXED_CORE)
    write(os.path.join(SC, "replicator.py"), FIXED_REPLICATOR)
    write(os.path.join(SC, "connection_manager.py"), FIXED_CONN_MGR)
    write(os.path.join(SC, "health_monitor.py"), FIXED_HEALTH_MONITOR)
    fix_database()
    # Write RCA report
    write(os.path.join(APP, "rca_report.txt"), RCA_REPORT)
    print("Done.")


if __name__ == "__main__":
    main()
