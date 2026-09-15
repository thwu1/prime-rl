
import json
import os
import sqlite3
import struct
import sys

import pytest
from Crypto.Cipher import DES

APP_DIR = "/app"
OUTPUT_DIR = os.path.join(APP_DIR, "output")

# ---------------------------------------------------------------------------
# Reference implementation of Vitess hash vindex (independent of solution)
# ---------------------------------------------------------------------------
_DES_CIPHER = DES.new(b"\x00" * 8, DES.MODE_ECB)


def vitess_vhash(shard_key: int) -> bytes:
    """Compute the Vitess hash vindex keyspace ID for a given integer key."""
    shard_key = shard_key & 0xFFFFFFFFFFFFFFFF
    key_bytes = struct.pack(">Q", shard_key)
    return _DES_CIPHER.encrypt(key_bytes)


def keyspace_id_to_shard(ksid: bytes) -> int:
    """Map a keyspace ID to a shard number (0-7) by first-byte range."""
    first_byte = ksid[0]
    boundaries = [0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0]
    for i, boundary in enumerate(boundaries):
        if first_byte < boundary:
            return i
    return 7


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def shard_config():
    with open(os.path.join(APP_DIR, "shard_config.json")) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def table_config():
    with open(os.path.join(APP_DIR, "table_config.json")) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def legacy_db():
    conn = sqlite3.connect(os.path.join(APP_DIR, "legacy_mappings.db"))
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def router():
    if OUTPUT_DIR not in sys.path:
        sys.path.insert(0, OUTPUT_DIR)
    import hybrid_router  # noqa: E402

    return hybrid_router


# ===================================================================
# Test: Output file existence
# ===================================================================
class TestOutputFiles:
    def test_hybrid_router_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "hybrid_router.py")), (
            "hybrid_router.py must exist in /app/output/"
        )

    def test_migration_plan_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "migration_plan.json"))

    def test_vschema_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "vschema.json"))

    def test_scatter_analysis_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "scatter_analysis.json"))

    def test_conflict_report_exists(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "conflict_report.json")), (
            "conflict_report.json must exist in /app/output/"
        )


# ===================================================================
# Test: vhash algorithm correctness
# ===================================================================
class TestVHash:
    def test_router_has_vhash(self, router):
        assert hasattr(router, "vhash"), "Module must export vhash"
        assert callable(router.vhash)

    def test_router_has_route_id(self, router):
        assert hasattr(router, "route_id"), "Module must export route_id"
        assert callable(router.route_id)

    def test_vhash_zero_known_vector(self, router):
        """DES(key=0x00*8, plaintext=0x00*8) = 0x8ca64de9c1b123a7."""
        result = router.vhash(0)
        assert result.hex() == "8ca64de9c1b123a7", (
            f"vhash(0) must equal the well-known test vector; "
            f"got {result.hex()}"
        )

    def test_vhash_matches_vitess_reference(self, router):
        """vhash must produce identical output to the Vitess Go implementation."""
        test_keys = [1, 2, 42, 255, 1000, 5000, 10000, 65535, 99999, 2**32, 2**63 - 1]
        for key in test_keys:
            result = router.vhash(key)
            expected = vitess_vhash(key)
            assert result == expected, (
                f"vhash({key}): got {result.hex()}, expected {expected.hex()}"
            )

    def test_vhash_negative_int64_cast(self, router):
        """Negative int64 values must be cast to uint64 preserving the bit pattern."""
        result = router.vhash(-1)
        # -1 as int64 → uint64 = 0xFFFFFFFFFFFFFFFF
        expected = vitess_vhash(0xFFFFFFFFFFFFFFFF)
        assert result == expected, (
            f"vhash(-1): got {result.hex()}, expected {expected.hex()}"
        )

    def test_vhash_returns_bytes(self, router):
        result = router.vhash(42)
        assert isinstance(result, bytes), "vhash must return bytes"
        assert len(result) == 8, "vhash must return exactly 8 bytes"

    def test_vhash_large_values(self, router):
        """Large uint64 values near the max boundary."""
        for val in [2**64 - 1, 2**64 - 2, 2**48]:
            result = router.vhash(val)
            expected = vitess_vhash(val)
            assert result == expected, (
                f"vhash({val}): got {result.hex()}, expected {expected.hex()}"
            )


# ===================================================================
# Test: Hybrid routing logic
# ===================================================================
class TestHybridRouting:
    def test_legacy_routing_sample(self, router, legacy_db, table_config):
        """IDs at or below threshold must route via legacy SQLite lookup."""
        cursor = legacy_db.cursor()
        for table_name, config in table_config.items():
            threshold = config["threshold"]
            test_ids = [1, threshold // 4, threshold // 2, threshold]
            for record_id in test_ids:
                cursor.execute(
                    "SELECT shard_number FROM shard_map "
                    "WHERE table_name = ? AND record_id = ?",
                    (table_name, record_id),
                )
                row = cursor.fetchone()
                if row is None:
                    continue
                expected_shard = row[0]
                result_shard = router.route_id(table_name, record_id)
                assert result_shard == expected_shard, (
                    f"Legacy routing {table_name}/id={record_id}: "
                    f"got shard {result_shard}, expected {expected_shard}"
                )

    def test_hash_routing_sample(self, router, table_config):
        """IDs above threshold must route via hash vindex algorithm."""
        for table_name, config in table_config.items():
            threshold = config["threshold"]
            test_ids = [threshold + 1, threshold + 100, threshold + 9999, 100000]
            for record_id in test_ids:
                ksid = vitess_vhash(record_id)
                expected_shard = keyspace_id_to_shard(ksid)
                result_shard = router.route_id(table_name, record_id)
                assert result_shard == expected_shard, (
                    f"Hash routing {table_name}/id={record_id}: "
                    f"got shard {result_shard}, expected {expected_shard}"
                )

    def test_threshold_boundary_legacy(self, router, legacy_db, table_config):
        """At the exact threshold, routing must use legacy SQLite lookup."""
        cursor = legacy_db.cursor()
        for table_name, config in table_config.items():
            threshold = config["threshold"]
            cursor.execute(
                "SELECT shard_number FROM shard_map "
                "WHERE table_name = ? AND record_id = ?",
                (table_name, threshold),
            )
            row = cursor.fetchone()
            if row is None:
                continue
            expected = row[0]
            result = router.route_id(table_name, threshold)
            assert result == expected, (
                f"Boundary (legacy) {table_name}/id={threshold}: "
                f"got {result}, expected {expected}"
            )

    def test_threshold_boundary_hash(self, router, table_config):
        """One above threshold must use hash routing."""
        for table_name, config in table_config.items():
            above = config["threshold"] + 1
            ksid = vitess_vhash(above)
            expected_shard = keyspace_id_to_shard(ksid)
            result_shard = router.route_id(table_name, above)
            assert result_shard == expected_shard, (
                f"Boundary (hash) {table_name}/id={above}: "
                f"got {result_shard}, expected {expected_shard}"
            )

    def test_route_returns_valid_shard(self, router, table_config):
        """route_id must always return a shard number in [0, 7]."""
        for table_name in table_config:
            for rid in [1, 500, 50000, 999999]:
                shard = router.route_id(table_name, rid)
                assert 0 <= shard <= 7, (
                    f"route_id({table_name}, {rid}) returned {shard}, "
                    f"expected 0-7"
                )


# ===================================================================
# Test: Migration plan
# ===================================================================
class TestMigrationPlan:
    def test_structure(self):
        with open(os.path.join(OUTPUT_DIR, "migration_plan.json")) as f:
            plan = json.load(f)
        assert "coupled_groups" in plan, "Must contain 'coupled_groups'"
        assert "migration_order" in plan, "Must contain 'migration_order'"
        assert isinstance(plan["coupled_groups"], list)
        assert isinstance(plan["migration_order"], list)

    def test_transaction_coupling_correctness(self):
        """Connected components from the transaction log must be correct."""
        with open(os.path.join(OUTPUT_DIR, "migration_plan.json")) as f:
            plan = json.load(f)
        groups = plan["coupled_groups"]
        normalized = sorted([sorted(g) for g in groups])
        expected_groups = sorted(
            [
                sorted(["orders", "order_items", "payments", "refunds"]),
                sorted(["users", "user_addresses", "user_preferences"]),
                sorted(["listings", "listing_images", "listing_attributes", "reviews"]),
                sorted(["shops", "shop_settings"]),
                ["analytics_events"],
                ["notifications"],
            ]
        )
        assert normalized == expected_groups, (
            f"Coupling groups incorrect.\nGot:      {normalized}\nExpected: {expected_groups}"
        )

    def test_migration_order_all_tables(self, table_config):
        """Migration order must include every table exactly once."""
        with open(os.path.join(OUTPUT_DIR, "migration_plan.json")) as f:
            plan = json.load(f)
        all_tables = set()
        for step in plan["migration_order"]:
            tables_in_step = step if isinstance(step, list) else [step]
            all_tables.update(tables_in_step)
        expected_tables = set(table_config.keys())
        assert all_tables == expected_tables, (
            f"Missing: {expected_tables - all_tables}, "
            f"Extra: {all_tables - expected_tables}"
        )

    def test_migration_order_respects_coupling(self):
        """All tables in a coupled group must appear in the same migration step."""
        with open(os.path.join(OUTPUT_DIR, "migration_plan.json")) as f:
            plan = json.load(f)
        groups = plan["coupled_groups"]
        order = plan["migration_order"]
        for group in groups:
            if len(group) <= 1:
                continue
            steps_for_group = set()
            for step_idx, step in enumerate(order):
                step_tables = step if isinstance(step, list) else [step]
                for table in group:
                    if table in step_tables:
                        steps_for_group.add(step_idx)
            assert len(steps_for_group) == 1, (
                f"Coupled group {group} spans multiple migration steps: "
                f"indices {steps_for_group}"
            )


# ===================================================================
# Test: Conflict report
# ===================================================================
class TestConflictReport:
    def test_structure(self):
        with open(os.path.join(OUTPUT_DIR, "conflict_report.json")) as f:
            report = json.load(f)
        assert "per_table" in report, "Must contain 'per_table'"
        assert "overall_conflict_rate" in report, "Must contain 'overall_conflict_rate'"
        assert isinstance(report["per_table"], dict)

    def test_all_tables_present(self, table_config):
        with open(os.path.join(OUTPUT_DIR, "conflict_report.json")) as f:
            report = json.load(f)
        for table_name in table_config:
            assert table_name in report["per_table"], (
                f"Table '{table_name}' missing from conflict report"
            )

    def test_per_table_fields(self, table_config):
        """Each table entry must have conflicts, total, and conflict_rate."""
        with open(os.path.join(OUTPUT_DIR, "conflict_report.json")) as f:
            report = json.load(f)
        for table_name in table_config:
            entry = report["per_table"][table_name]
            assert "conflicts" in entry, f"{table_name}: missing 'conflicts'"
            assert "total" in entry, f"{table_name}: missing 'total'"
            assert "conflict_rate" in entry, f"{table_name}: missing 'conflict_rate'"
            assert isinstance(entry["conflicts"], int)
            assert isinstance(entry["total"], int)
            assert isinstance(entry["conflict_rate"], float)

    def test_conflict_counts_correct(self, table_config, legacy_db):
        """Independently recompute conflict counts and verify."""
        with open(os.path.join(OUTPUT_DIR, "conflict_report.json")) as f:
            report = json.load(f)

        cursor = legacy_db.cursor()
        for table_name, config in table_config.items():
            threshold = config["threshold"]
            conflicts = 0
            total = 0
            cursor.execute(
                "SELECT record_id, shard_number FROM shard_map WHERE table_name = ?",
                (table_name,),
            )
            for record_id, legacy_shard in cursor.fetchall():
                if record_id <= threshold:
                    total += 1
                    ksid = vitess_vhash(record_id)
                    hash_shard = keyspace_id_to_shard(ksid)
                    if legacy_shard != hash_shard:
                        conflicts += 1

            entry = report["per_table"][table_name]
            assert entry["conflicts"] == conflicts, (
                f"Table {table_name}: expected {conflicts} conflicts, "
                f"got {entry['conflicts']}"
            )
            assert entry["total"] == total, (
                f"Table {table_name}: expected {total} total, "
                f"got {entry['total']}"
            )

    def test_conflict_rate_calculation(self, table_config):
        """Verify conflict_rate = conflicts / total for each table."""
        with open(os.path.join(OUTPUT_DIR, "conflict_report.json")) as f:
            report = json.load(f)
        for table_name in table_config:
            entry = report["per_table"][table_name]
            if entry["total"] > 0:
                expected_rate = entry["conflicts"] / entry["total"]
            else:
                expected_rate = 0.0
            assert abs(entry["conflict_rate"] - expected_rate) < 1e-6, (
                f"Table {table_name}: conflict_rate should be "
                f"{expected_rate:.6f}, got {entry['conflict_rate']:.6f}"
            )

    def test_overall_conflict_rate(self, table_config):
        """Overall rate must be weighted average by legacy record count."""
        with open(os.path.join(OUTPUT_DIR, "conflict_report.json")) as f:
            report = json.load(f)
        total_conflicts = sum(
            report["per_table"][t]["conflicts"] for t in table_config
        )
        total_records = sum(
            report["per_table"][t]["total"] for t in table_config
        )
        if total_records > 0:
            expected_overall = total_conflicts / total_records
        else:
            expected_overall = 0.0
        assert abs(report["overall_conflict_rate"] - expected_overall) < 1e-6, (
            f"Overall conflict rate should be {expected_overall:.6f}, "
            f"got {report['overall_conflict_rate']:.6f}"
        )

    def test_conflict_rate_bounds(self, table_config):
        """Each conflict rate must be in [0.0, 1.0]."""
        with open(os.path.join(OUTPUT_DIR, "conflict_report.json")) as f:
            report = json.load(f)
        for table_name in table_config:
            rate = report["per_table"][table_name]["conflict_rate"]
            assert 0.0 <= rate <= 1.0, (
                f"Table {table_name}: conflict_rate {rate} out of bounds"
            )
        assert 0.0 <= report["overall_conflict_rate"] <= 1.0

    def test_conflicts_nontrivial(self, table_config):
        """With random legacy assignments and 8 shards, most records should
        conflict (probability ~7/8). Verify conflicts are non-zero to catch
        degenerate solutions that report zero conflicts."""
        with open(os.path.join(OUTPUT_DIR, "conflict_report.json")) as f:
            report = json.load(f)
        for table_name in table_config:
            entry = report["per_table"][table_name]
            assert entry["conflicts"] > 0, (
                f"Table {table_name}: expected non-zero conflicts "
                f"(random assignment vs. hash should produce ~87.5% conflicts)"
            )
        assert report["overall_conflict_rate"] > 0.5, (
            "Overall conflict rate should be substantial (>0.5) given random legacy assignments"
        )


# ===================================================================
# Test: VSchema
# ===================================================================
class TestVSchema:
    def test_valid_json(self):
        with open(os.path.join(OUTPUT_DIR, "vschema.json")) as f:
            vschema = json.load(f)
        assert isinstance(vschema, dict)

    def test_sharded_flag(self):
        with open(os.path.join(OUTPUT_DIR, "vschema.json")) as f:
            vschema = json.load(f)
        assert vschema.get("sharded") is True, "VSchema must have sharded: true"

    def test_has_hash_vindex(self):
        with open(os.path.join(OUTPUT_DIR, "vschema.json")) as f:
            vschema = json.load(f)
        assert "vindexes" in vschema, "Must define vindexes section"
        vindexes = vschema["vindexes"]
        has_hash = any(
            v.get("type") in ("hash", "xxhash") for v in vindexes.values()
        )
        assert has_hash, "Must include at least one hash-type vindex"

    def test_all_tables_present(self, table_config):
        with open(os.path.join(OUTPUT_DIR, "vschema.json")) as f:
            vschema = json.load(f)
        assert "tables" in vschema, "Must have a 'tables' section"
        for table_name in table_config:
            assert table_name in vschema["tables"], (
                f"Table '{table_name}' missing from VSchema"
            )

    def test_tables_have_column_vindexes(self, table_config):
        with open(os.path.join(OUTPUT_DIR, "vschema.json")) as f:
            vschema = json.load(f)
        for table_name, config in table_config.items():
            table_def = vschema["tables"][table_name]
            assert "column_vindexes" in table_def, (
                f"Table '{table_name}' must have column_vindexes"
            )
            cv_list = table_def["column_vindexes"]
            assert len(cv_list) > 0, (
                f"Table '{table_name}' must have at least one column vindex"
            )
            # Primary column vindex must reference the correct shard key
            primary = cv_list[0]
            col = primary.get("column", "")
            cols = primary.get("columns", [])
            shard_key = config["shard_key"]
            assert col == shard_key or shard_key in cols, (
                f"Table '{table_name}': primary vindex column must be "
                f"'{shard_key}', got column='{col}' columns={cols}"
            )


# ===================================================================
# Test: Scatter analysis
# ===================================================================
class TestScatterAnalysis:
    def _load_ground_truth(self):
        """Build ground truth from query workload + table config."""
        with open(os.path.join(APP_DIR, "table_config.json")) as f:
            table_config = json.load(f)
        with open(os.path.join(APP_DIR, "query_workload.jsonl")) as f:
            workload = [json.loads(line) for line in f]
        truth = {}
        for q in workload:
            shard_key = table_config[q["table"]]["shard_key"]
            sql_upper = q["sql"].upper()
            where_idx = sql_upper.find("WHERE")
            if where_idx >= 0:
                where_clause = q["sql"][where_idx:]
                is_scatter = shard_key not in where_clause
            else:
                is_scatter = True
            truth[q["query_id"]] = is_scatter
        return truth

    def test_structure(self):
        with open(os.path.join(OUTPUT_DIR, "scatter_analysis.json")) as f:
            analysis = json.load(f)
        assert isinstance(analysis, list), "scatter_analysis.json must be a list"
        assert len(analysis) > 0, "scatter_analysis.json must not be empty"

    def test_scatter_detection_correctness(self):
        """Each query must be correctly classified as scatter or targeted."""
        with open(os.path.join(OUTPUT_DIR, "scatter_analysis.json")) as f:
            analysis = json.load(f)
        scatter_map = {item["query_id"]: item["is_scatter"] for item in analysis}
        truth = self._load_ground_truth()
        for qid, expected in truth.items():
            assert qid in scatter_map, f"Query {qid} missing from scatter analysis"
            assert scatter_map[qid] == expected, (
                f"Query {qid}: expected is_scatter={expected}, "
                f"got {scatter_map[qid]}"
            )

    def test_all_queries_covered(self):
        """Every query from the workload must appear in the analysis."""
        with open(os.path.join(OUTPUT_DIR, "scatter_analysis.json")) as f:
            analysis = json.load(f)
        with open(os.path.join(APP_DIR, "query_workload.jsonl")) as f:
            workload = [json.loads(line) for line in f]
        analysis_ids = {item["query_id"] for item in analysis}
        workload_ids = {q["query_id"] for q in workload}
        assert workload_ids.issubset(analysis_ids), (
            f"Missing queries: {workload_ids - analysis_ids}"
        )
