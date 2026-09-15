"""
Verification tests for the Vitess-style resharding task.

Covers:
  - Shard split (data integrity, routing correctness, no duplicates)
  - VSchema topology update
  - VDiff tool
  - forget_user fix (correctness, query efficiency, rate limiting, circuit breaker)
"""

import hashlib
import inspect
import json
import os
import sqlite3
import subprocess
import sys
import time

import pytest

sys.path.insert(0, "/app")

DATA_DIR = "/app/data"
VSCHEMA_PATH = "/app/vschema.json"

# ── helpers (re-implemented for test independence) ──────────────────────────

def compute_shard_byte(key_value):
    return int(hashlib.md5(str(key_value).encode()).hexdigest()[:2], 16)


def parse_shard_range(shard_name):
    if shard_name.startswith("-"):
        return (0, int(shard_name[1:], 16))
    if shard_name.endswith("-"):
        return (int(shard_name[:-1], 16), 256)
    parts = shard_name.split("-")
    return (int(parts[0], 16), int(parts[1], 16))


def shard_db_path(shard_name):
    if shard_name.startswith("-"):
        return os.path.join(DATA_DIR, f"shard_0_{shard_name[1:]}.db")
    if shard_name.endswith("-"):
        return os.path.join(DATA_DIR, f"shard_{shard_name[:-1]}_ff.db")
    parts = shard_name.split("-")
    return os.path.join(DATA_DIR, f"shard_{parts[0]}_{parts[1]}.db")


def get_all_rows(shard_name, table):
    db_path = shard_db_path(shard_name)
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
    conn.close()
    return rows


PK_COLS = {
    "workspaces": "workspace_id",
    "users": "user_id",
    "channels": "channel_id",
    "messages": "message_id",
    "thread_subscriptions": "sub_id",
}
TABLES = list(PK_COLS.keys())


# ═══════════════════════════════════════════════════════════════════════════
#  1. Resharding
# ═══════════════════════════════════════════════════════════════════════════

class TestResharding:
    """Verify shard -80 was correctly split into -40 and 40-80."""

    def test_new_shard_databases_exist(self):
        assert os.path.exists(shard_db_path("-40")), "Shard -40 not found"
        assert os.path.exists(shard_db_path("40-80")), "Shard 40-80 not found"

    def test_original_shard_removed(self):
        assert not os.path.exists(shard_db_path("-80")), \
            "Original -80 shard should be removed after reshard"

    def test_shard_80_still_exists(self):
        assert os.path.exists(shard_db_path("80-")), "Shard 80- must still exist"

    @pytest.mark.parametrize("table", TABLES)
    def test_data_integrity(self, table):
        """Every row originally in -80 is in exactly one correct new shard."""
        with open(os.path.join(DATA_DIR, "manifest.json")) as f:
            manifest = json.load(f)
        pk_col = PK_COLS[table]

        # rows that were in -80 (byte < 0x80)
        expected = {}
        for row in manifest["rows"]:
            if row["table"] == table:
                bv = compute_shard_byte(row["shard_key"])
                if bv < 0x80:
                    expected[row["pk"]] = row["shard_key"]

        assert len(expected) > 0, f"No {table} rows in -80 (test is vacuous)"

        found = {}
        for shard in ["-40", "40-80"]:
            for row in get_all_rows(shard, table):
                pk = row[pk_col]
                assert pk not in found, \
                    f"Duplicate {table} pk={pk} in shards {found[pk]} and {shard}"
                found[pk] = shard

                bv = compute_shard_byte(row["workspace_id"])
                start, end = parse_shard_range(shard)
                assert start <= bv < end, (
                    f"{table} pk={pk} byte=0x{bv:02x} "
                    f"routed to wrong shard {shard} [{start:#x},{end:#x})"
                )

        assert set(found.keys()) == set(expected.keys()), (
            f"{table}: missing={set(expected) - set(found)}, "
            f"extra={set(found) - set(expected)}"
        )

    @pytest.mark.parametrize("table", TABLES)
    def test_shard_80_data_unchanged(self, table):
        """Shard 80- must still contain exactly the same rows as originally."""
        with open(os.path.join(DATA_DIR, "manifest.json")) as f:
            manifest = json.load(f)
        pk_col = PK_COLS[table]

        expected_pks = {
            r["pk"] for r in manifest["rows"]
            if r["table"] == table and compute_shard_byte(r["shard_key"]) >= 0x80
        }
        actual_pks = {r[pk_col] for r in get_all_rows("80-", table)}

        assert actual_pks == expected_pks, (
            f"80- {table}: "
            f"missing={expected_pks - actual_pks}, extra={actual_pks - expected_pks}"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  2. VSchema
# ═══════════════════════════════════════════════════════════════════════════

class TestVSchema:
    def test_has_three_shards(self):
        with open(VSCHEMA_PATH) as f:
            v = json.load(f)
        shards = v.get("shards", [])
        assert len(shards) == 3, f"Expected 3 shards, got {len(shards)}: {shards}"

    def test_correct_shard_names(self):
        with open(VSCHEMA_PATH) as f:
            v = json.load(f)
        assert set(v["shards"]) == {"-40", "40-80", "80-"}


# ═══════════════════════════════════════════════════════════════════════════
#  3. VDiff tool
# ═══════════════════════════════════════════════════════════════════════════

class TestVDiff:
    def test_vdiff_exists(self):
        assert os.path.exists("/app/vdiff.py"), "vdiff.py not found"

    def test_vdiff_reports_consistent(self):
        result = subprocess.run(
            [sys.executable, "/app/vdiff.py",
             "--source=-80", "--targets=-40,40-80"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"VDiff reported inconsistency:\n{result.stdout}\n{result.stderr}"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  4. forget_user fix
# ═══════════════════════════════════════════════════════════════════════════

class TestForgetUser:
    """Verify the fixed forget_user job."""

    # ── helper: seed disposable test data ───────────────────────────────

    @staticmethod
    def _create_test_data(offset=0):
        """Insert a small workspace and return (ws_id, user_id, shard, n_channels)."""
        from shard_manager import ShardManager
        mgr = ShardManager()

        for ws_id in range(8000 + offset, 9000 + offset):
            shard = mgr.route_query("users", ws_id)
            if os.path.exists(shard_db_path(shard)):
                break
        else:
            raise RuntimeError("Could not find a routable ws_id")

        conn = mgr.get_connection(shard)
        user_id = 80000 + offset

        for tbl in [
            "thread_subscriptions", "messages", "channels", "users", "workspaces"
        ]:
            conn.execute(f"DELETE FROM {tbl} WHERE workspace_id = ?", (ws_id,))

        conn.execute("INSERT INTO workspaces VALUES (?,?,?,?)",
                     (ws_id, f"test_ws_{offset}", "enterprise", "2020-01-01"))
        conn.execute("INSERT INTO users VALUES (?,?,?,?,?,?)",
                     (user_id, ws_id, f"tuser_{offset}",
                      f"t{offset}@test.com", 1, "2020-01-01"))

        n_channels = 6
        sub_id = 800000 + offset * 1000
        for ch in range(n_channels):
            ch_id = 80100 + offset * 100 + ch
            conn.execute("INSERT INTO channels VALUES (?,?,?,?,?)",
                         (ch_id, ws_id, f"tch_{offset}_{ch}", 1, "2020-01-01"))
            for t in range(3):
                conn.execute(
                    "INSERT INTO thread_subscriptions VALUES (?,?,?,?,?,?,?)",
                    (sub_id, user_id, ch_id, ws_id,
                     f"ts_{ch}_{t}", 1, "2020-01-01"),
                )
                sub_id += 1

        conn.commit()
        mgr.close_all()
        return ws_id, user_id, shard, n_channels

    @staticmethod
    def _fresh_import():
        for mod in list(sys.modules):
            if "forget_user" in mod:
                del sys.modules[mod]
        sys.path.insert(0, "/app/jobs")
        import forget_user as fu          # noqa: F811
        return fu

    # ── tests ───────────────────────────────────────────────────────────

    def test_correctness(self):
        """All subscriptions for the user are deactivated."""
        ws_id, uid, shard, _ = self._create_test_data(offset=0)
        fu = self._fresh_import()
        fu.forget_user(uid, ws_id)

        from shard_manager import ShardManager
        mgr = ShardManager()
        rows = mgr.query_shard(
            shard,
            "SELECT COUNT(*) AS cnt FROM thread_subscriptions "
            "WHERE user_id = ? AND is_active = 1",
            (uid,),
        )
        mgr.close_all()
        assert rows[0]["cnt"] == 0, f"Active subs remain: {rows[0]['cnt']}"

    def test_query_efficiency(self):
        """Fixed version uses strictly fewer queries than the buggy one."""
        ws_id, uid, shard, n_ch = self._create_test_data(offset=100)
        fu = self._fresh_import()
        result = fu.forget_user(uid, ws_id)

        buggy_count = 2 + 3 * n_ch          # initial 2 + 3 per channel
        assert result["queries_executed"] < buggy_count, (
            f"Expected < {buggy_count} queries, got {result['queries_executed']}"
        )

    def test_rate_limiting_parameter(self):
        """forget_user must accept max_ops_per_sec and actually throttle."""
        ws_id, uid, shard, n_ch = self._create_test_data(offset=200)
        fu = self._fresh_import()

        sig = inspect.signature(fu.forget_user)
        assert "max_ops_per_sec" in sig.parameters, (
            f"forget_user must accept max_ops_per_sec. "
            f"Current params: {list(sig.parameters)}"
        )

        start = time.time()
        fu.forget_user(uid, ws_id, max_ops_per_sec=2)
        elapsed = time.time() - start

        # 6 channels at 2 ops/s -> at least ~2.5 s of sleeps
        min_expected = (n_ch - 1) * 0.5 * 0.6     # 60 % tolerance
        assert elapsed >= min_expected, (
            f"Rate limiting too weak: {n_ch} channels in {elapsed:.2f}s "
            f"(expected >= {min_expected:.2f}s at 2 ops/s)"
        )

    def test_circuit_breaker(self):
        """Circuit breaker stops processing when the shard is unhealthy."""
        ws_id, uid, shard, n_ch = self._create_test_data(offset=300)
        fu = self._fresh_import()

        from monitor import monitor
        monitor.inject_error_rate(shard, 0.99)

        try:
            result = fu.forget_user(uid, ws_id)

            assert result.get("circuit_breaker_tripped", False), (
                "circuit_breaker_tripped should be True with 99 % error rate"
            )

            from shard_manager import ShardManager
            mgr = ShardManager()
            rows = mgr.query_shard(
                shard,
                "SELECT COUNT(*) AS cnt FROM thread_subscriptions "
                "WHERE user_id = ? AND is_active = 1",
                (uid,),
            )
            mgr.close_all()
            assert rows[0]["cnt"] > 0, (
                "Circuit breaker tripped yet all subs were deactivated"
            )
        finally:
            monitor.clear_injection(shard)
