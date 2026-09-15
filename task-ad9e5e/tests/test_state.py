
import os
import re
import pytest
import psycopg2


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(dbname="postgres", user="postgres")
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def cur(db):
    cursor = db.cursor()
    yield cursor
    cursor.close()


class TestPreparedTransactions:
    """The orphaned prepared transaction must be resolved to unblock the xmin horizon."""

    def test_no_orphaned_prepared_transactions(self, cur):
        cur.execute("SELECT COUNT(*) FROM pg_prepared_xacts;")
        count = cur.fetchone()[0]
        assert count == 0, (
            f"Found {count} orphaned prepared transaction(s) — "
            "these block the global xmin horizon and prevent VACUUM from cleaning dead tuples"
        )


class TestAutovacuumTableSettings:
    """Per-table autovacuum settings must be correctly configured."""

    def test_audit_log_autovacuum_enabled(self, cur):
        """audit_log must not have autovacuum explicitly disabled."""
        cur.execute(
            "SELECT reloptions FROM pg_class WHERE relname = 'audit_log';"
        )
        row = cur.fetchone()
        reloptions = row[0] if row else None
        if reloptions:
            for opt in reloptions:
                if "autovacuum_enabled" in opt.lower():
                    assert "false" not in opt.lower(), (
                        f"audit_log has autovacuum_enabled=false in reloptions: {opt}"
                    )

    def _check_scale_factor(self, cur, table_name, threshold=0.05):
        cur.execute(
            "SELECT option_value "
            "FROM pg_options_to_table("
            "  (SELECT reloptions FROM pg_class WHERE relname = %s)"
            ") "
            "WHERE option_name = 'autovacuum_vacuum_scale_factor';",
            (table_name,),
        )
        row = cur.fetchone()
        assert row is not None, (
            f"{table_name} should have per-table autovacuum_vacuum_scale_factor set "
            f"(default 0.2 is too high for tables with >100K rows)"
        )
        val = float(row[0])
        assert val < threshold, (
            f"{table_name} autovacuum_vacuum_scale_factor = {val}, "
            f"should be < {threshold} for a table of this size"
        )

    def test_orders_scale_factor(self, cur):
        self._check_scale_factor(cur, "orders")

    def test_order_items_scale_factor(self, cur):
        self._check_scale_factor(cur, "order_items")

    def test_audit_log_scale_factor(self, cur):
        self._check_scale_factor(cur, "audit_log")


class TestGlobalVacuumSettings:
    """Global vacuum configuration parameters must be tuned for this workload."""

    def test_vacuum_cost_delay(self, cur):
        """autovacuum_vacuum_cost_delay should be <= 5ms for modern hardware."""
        cur.execute("SHOW autovacuum_vacuum_cost_delay;")
        raw = cur.fetchone()[0]
        delay_ms = float(re.sub(r"[^0-9.]", "", raw))
        assert delay_ms <= 5, (
            f"autovacuum_vacuum_cost_delay = {raw}, should be <= 5ms"
        )

    def test_vacuum_cost_limit(self, cur):
        """autovacuum_vacuum_cost_limit should be >= 200."""
        cur.execute("SHOW autovacuum_vacuum_cost_limit;")
        limit = int(cur.fetchone()[0])
        assert limit >= 200, (
            f"autovacuum_vacuum_cost_limit = {limit}, should be >= 200"
        )

    def test_maintenance_work_mem(self, cur):
        """maintenance_work_mem should be >= 256MB to reduce index vacuum cycles."""
        cur.execute("SHOW maintenance_work_mem;")
        raw = cur.fetchone()[0]
        if "GB" in raw:
            mem_mb = float(re.sub(r"[^0-9.]", "", raw)) * 1024
        elif "MB" in raw:
            mem_mb = float(re.sub(r"[^0-9.]", "", raw))
        elif "kB" in raw:
            mem_mb = float(re.sub(r"[^0-9.]", "", raw)) / 1024
        else:
            mem_mb = float(raw) / (1024 * 1024)
        assert mem_mb >= 256, (
            f"maintenance_work_mem = {raw}, should be >= 256MB"
        )

    def test_idle_in_transaction_timeout(self, cur):
        """idle_in_transaction_session_timeout must be set to prevent future vacuum blocking."""
        cur.execute("SHOW idle_in_transaction_session_timeout;")
        timeout = cur.fetchone()[0]
        assert timeout != "0", (
            "idle_in_transaction_session_timeout = 0 (disabled) — "
            "this allows idle transactions to block vacuum indefinitely"
        )


class TestBloatRemediation:
    """Dead tuples must be cleared via VACUUM after resolving blockers."""

    @pytest.fixture(autouse=True, scope="class")
    def ensure_pgstattuple(self, cur):
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgstattuple;")

    def _check_bloat(self, cur, table_name, max_pct=5.0):
        cur.execute(
            "SELECT dead_tuple_percent FROM pgstattuple(%s);",
            (table_name,),
        )
        pct = cur.fetchone()[0]
        assert pct < max_pct, (
            f"{table_name} dead_tuple_percent = {pct:.1f}%, "
            f"should be < {max_pct}% after VACUUM"
        )

    def test_orders_bloat(self, cur):
        self._check_bloat(cur, "orders")

    def test_order_items_bloat(self, cur):
        self._check_bloat(cur, "order_items")

    def test_audit_log_bloat(self, cur):
        self._check_bloat(cur, "audit_log")


class TestConfigFile:
    """The global vacuum configuration file must exist with required parameters."""

    CONF_PATH = "/app/postgresql_tuning.conf"
    REQUIRED_PARAMS = [
        "autovacuum_vacuum_cost_delay",
        "autovacuum_vacuum_cost_limit",
        "maintenance_work_mem",
        "idle_in_transaction_session_timeout",
    ]

    def test_config_file_exists(self):
        assert os.path.isfile(self.CONF_PATH), (
            f"{self.CONF_PATH} does not exist"
        )

    def test_config_file_contains_required_params(self):
        with open(self.CONF_PATH, "r") as f:
            content = f.read()
        for param in self.REQUIRED_PARAMS:
            assert param in content, (
                f"{self.CONF_PATH} is missing required parameter: {param}"
            )


class TestVacuumHealthFunction:
    """The vacuum_health_report() function must exist and correctly assess system health."""

    def test_function_callable(self, cur):
        """Function must exist and return rows."""
        cur.execute("SELECT * FROM vacuum_health_report();")
        rows = cur.fetchall()
        assert len(rows) > 0, "vacuum_health_report() returned no rows"

    def test_column_structure(self, cur):
        """Function must return the four specified columns."""
        cur.execute("SELECT * FROM vacuum_health_report() LIMIT 1;")
        colnames = [desc[0] for desc in cur.description]
        assert colnames == [
            "check_name", "status", "current_value", "recommended_action"
        ], (
            f"Expected columns [check_name, status, current_value, "
            f"recommended_action], got {colnames}"
        )

    def test_minimum_distinct_checks(self, cur):
        """Function must perform at least 8 distinct checks."""
        cur.execute("SELECT DISTINCT check_name FROM vacuum_health_report();")
        check_names = [row[0] for row in cur.fetchall()]
        assert len(check_names) >= 8, (
            f"Function returns only {len(check_names)} distinct checks, "
            f"need at least 8: {check_names}"
        )

    def test_valid_status_values(self, cur):
        """All status values must be OK, WARNING, or CRITICAL."""
        cur.execute("SELECT DISTINCT status FROM vacuum_health_report();")
        statuses = {row[0] for row in cur.fetchall()}
        valid = {"OK", "WARNING", "CRITICAL"}
        invalid = statuses - valid
        assert not invalid, (
            f"Invalid status values: {invalid}. Must be one of {valid}"
        )

    def test_no_critical_after_remediation(self, cur):
        """After remediation, no checks should report CRITICAL status."""
        cur.execute(
            "SELECT check_name, current_value "
            "FROM vacuum_health_report() WHERE status = 'CRITICAL';"
        )
        critical = cur.fetchall()
        assert len(critical) == 0, (
            f"Found {len(critical)} CRITICAL check(s) after remediation: "
            + ", ".join(f"{r[0]}={r[1]}" for r in critical)
        )
