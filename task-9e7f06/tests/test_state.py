"""
Tests for CUDA warptiling kernel autotuning database and analysis.

"""
import json
import os
import sqlite3

import pytest


# ============================================================================
# SQLite Database Tests
# ============================================================================

@pytest.fixture(scope="module")
def db():
    path = "/app/output/autotune.db"
    assert os.path.exists(path), f"Database file {path} does not exist"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


class TestDatabaseSchema:
    """Verify the SQLite database has the required schema."""

    def test_configurations_table_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='configurations'"
        )
        assert cur.fetchone() is not None, "Table 'configurations' does not exist"

    def test_configurations_columns(self, db):
        cur = db.execute("PRAGMA table_info(configurations)")
        columns = {row["name"] for row in cur.fetchall()}
        required = {
            "id", "num_threads", "bm", "bn", "bk", "wm", "wn", "wniter",
            "tm", "tn", "wmiter", "regs_per_thread", "smem_data_bytes",
            "smem_allocated_bytes", "max_blocks_by_regs", "max_blocks_by_smem",
            "max_blocks_by_warps", "max_blocks_per_sm", "active_warps",
            "occupancy_pct",
        }
        missing = required - columns
        assert not missing, f"Missing columns in configurations: {missing}"

    def test_bottlenecks_table_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bottlenecks'"
        )
        assert cur.fetchone() is not None, "Table 'bottlenecks' does not exist"

    def test_bottlenecks_columns(self, db):
        cur = db.execute("PRAGMA table_info(bottlenecks)")
        columns = {row["name"] for row in cur.fetchall()}
        assert "config_id" in columns, "Missing column 'config_id' in bottlenecks"
        assert "resource" in columns, "Missing column 'resource' in bottlenecks"

    def test_occupancy_index_exists(self, db):
        cur = db.execute("PRAGMA index_list(configurations)")
        indexes = [row["name"] for row in cur.fetchall()]
        assert any("occupancy" in idx.lower() for idx in indexes), \
            f"No occupancy index found. Indexes: {indexes}"

    def test_occupancy_histogram_view_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name='occupancy_histogram'"
        )
        assert cur.fetchone() is not None, "View 'occupancy_histogram' does not exist"

    def test_bottleneck_distribution_view_exists(self, db):
        cur = db.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name='bottleneck_distribution'"
        )
        assert cur.fetchone() is not None, "View 'bottleneck_distribution' does not exist"


class TestDatabaseContents:
    """Verify the database contains the correct data."""

    def test_total_configurations(self, db):
        count = db.execute("SELECT COUNT(*) FROM configurations").fetchone()[0]
        assert count == 984, f"Expected 984 configurations, got {count}"

    def test_unique_constraint(self, db):
        """Verify no duplicate configurations."""
        count = db.execute("""
            SELECT COUNT(*) FROM (
                SELECT num_threads, bm, bn, bk, wm, wn, wniter, tm, tn,
                       COUNT(*) as cnt
                FROM configurations
                GROUP BY num_threads, bm, bn, bk, wm, wn, wniter, tm, tn
                HAVING cnt > 1
            )
        """).fetchone()[0]
        assert count == 0, "Found duplicate configurations in database"

    def test_every_config_has_bottleneck(self, db):
        """Every configuration must have at least one bottleneck resource."""
        orphan_count = db.execute("""
            SELECT COUNT(*) FROM configurations c
            WHERE NOT EXISTS (
                SELECT 1 FROM bottlenecks b WHERE b.config_id = c.id
            )
        """).fetchone()[0]
        assert orphan_count == 0, \
            f"{orphan_count} configurations have no bottleneck entries"

    def test_bottleneck_resources_valid(self, db):
        """All bottleneck resources must be one of the allowed values."""
        invalid = db.execute("""
            SELECT DISTINCT resource FROM bottlenecks
            WHERE resource NOT IN ('registers', 'smem', 'warps')
        """).fetchall()
        assert len(invalid) == 0, \
            f"Invalid bottleneck resources: {[r[0] for r in invalid]}"


class TestConfigA:
    """Config A: Blog's A6000 warptiling config (register-bottlenecked)."""

    @pytest.fixture
    def row(self, db):
        cur = db.execute("""
            SELECT * FROM configurations
            WHERE num_threads=128 AND bm=128 AND bn=128 AND bk=16
              AND wm=64 AND wn=64 AND wniter=4 AND tm=8 AND tn=4
        """)
        row = cur.fetchone()
        assert row is not None, "Config A not found in database"
        return row

    def test_wmiter(self, row):
        assert row["wmiter"] == 1

    def test_regs_per_thread(self, row):
        assert row["regs_per_thread"] == 155

    def test_smem_data_bytes(self, row):
        assert row["smem_data_bytes"] == 16384

    def test_smem_allocated_bytes(self, row):
        assert row["smem_allocated_bytes"] == 17408

    def test_max_blocks_by_regs(self, row):
        assert row["max_blocks_by_regs"] == 3

    def test_max_blocks_by_smem(self, row):
        assert row["max_blocks_by_smem"] == 5

    def test_max_blocks_by_warps(self, row):
        assert row["max_blocks_by_warps"] == 12

    def test_max_blocks_per_sm(self, row):
        assert row["max_blocks_per_sm"] == 3

    def test_active_warps(self, row):
        assert row["active_warps"] == 12

    def test_occupancy(self, row):
        assert abs(row["occupancy_pct"] - 25.0) < 0.01

    def test_bottleneck(self, db, row):
        resources = db.execute(
            "SELECT resource FROM bottlenecks WHERE config_id = ? ORDER BY resource",
            (row["id"],)
        ).fetchall()
        assert [r[0] for r in resources] == ["registers"]


class TestConfigB:
    """Config B: Shared-memory-limited configuration."""

    @pytest.fixture
    def row(self, db):
        cur = db.execute("""
            SELECT * FROM configurations
            WHERE num_threads=128 AND bm=64 AND bn=128 AND bk=32
              AND wm=16 AND wn=128 AND wniter=1 AND tm=4 AND tn=4
        """)
        row = cur.fetchone()
        assert row is not None, "Config B not found in database"
        return row

    def test_wmiter(self, row):
        assert row["wmiter"] == 4

    def test_regs_per_thread(self, row):
        assert row["regs_per_thread"] == 87

    def test_smem_data_bytes(self, row):
        assert row["smem_data_bytes"] == 24576

    def test_smem_allocated_bytes(self, row):
        assert row["smem_allocated_bytes"] == 25600

    def test_max_blocks_per_sm(self, row):
        assert row["max_blocks_per_sm"] == 4

    def test_active_warps(self, row):
        assert row["active_warps"] == 16

    def test_occupancy(self, row):
        assert abs(row["occupancy_pct"] - 33.33) < 0.01

    def test_bottleneck(self, db, row):
        resources = db.execute(
            "SELECT resource FROM bottlenecks WHERE config_id = ? ORDER BY resource",
            (row["id"],)
        ).fetchall()
        assert [r[0] for r in resources] == ["smem"]


class TestConfigC:
    """Config C: Maximum occupancy configuration (100%)."""

    @pytest.fixture
    def row(self, db):
        cur = db.execute("""
            SELECT * FROM configurations
            WHERE num_threads=256 AND bm=64 AND bn=64 AND bk=16
              AND wm=16 AND wn=32 AND wniter=1 AND tm=4 AND tn=4
        """)
        row = cur.fetchone()
        assert row is not None, "Config C not found in database"
        return row

    def test_wmiter(self, row):
        assert row["wmiter"] == 1

    def test_regs_per_thread(self, row):
        assert row["regs_per_thread"] == 39

    def test_smem_data_bytes(self, row):
        assert row["smem_data_bytes"] == 8192

    def test_smem_allocated_bytes(self, row):
        assert row["smem_allocated_bytes"] == 9216

    def test_max_blocks_by_regs(self, row):
        assert row["max_blocks_by_regs"] == 6

    def test_max_blocks_by_smem(self, row):
        assert row["max_blocks_by_smem"] == 11

    def test_max_blocks_by_warps(self, row):
        assert row["max_blocks_by_warps"] == 6

    def test_max_blocks_per_sm(self, row):
        assert row["max_blocks_per_sm"] == 6

    def test_active_warps(self, row):
        assert row["active_warps"] == 48

    def test_occupancy(self, row):
        assert abs(row["occupancy_pct"] - 100.0) < 0.01

    def test_bottleneck(self, db, row):
        resources = db.execute(
            "SELECT resource FROM bottlenecks WHERE config_id = ? ORDER BY resource",
            (row["id"],)
        ).fetchall()
        assert [r[0] for r in resources] == ["registers", "warps"]


class TestOccupancyHistogramView:
    """Verify the occupancy_histogram SQL view."""

    EXPECTED = {
        0.0: 92,
        8.33: 180,
        16.67: 244,
        25.0: 164,
        33.33: 186,
        41.67: 66,
        66.67: 36,
        75.0: 12,
        83.33: 2,
        100.0: 2,
    }

    def test_distinct_levels(self, db):
        rows = db.execute("SELECT * FROM occupancy_histogram").fetchall()
        assert len(rows) == 10, f"Expected 10 occupancy levels, got {len(rows)}"

    def test_histogram_values(self, db):
        rows = db.execute("SELECT * FROM occupancy_histogram").fetchall()
        actual = {row["occupancy_pct"]: row["config_count"] for row in rows}
        for expected_occ, expected_count in self.EXPECTED.items():
            matched = None
            for actual_occ, actual_count in actual.items():
                if abs(float(actual_occ) - expected_occ) < 0.01:
                    matched = actual_count
                    break
            assert matched is not None, \
                f"No bin found for occupancy {expected_occ}%"
            assert matched == expected_count, \
                f"Occupancy {expected_occ}%: expected {expected_count}, got {matched}"

    def test_histogram_total(self, db):
        total = db.execute(
            "SELECT SUM(config_count) FROM occupancy_histogram"
        ).fetchone()[0]
        assert total == 984, f"Histogram total {total} != 984"


class TestBottleneckDistributionView:
    """Verify the bottleneck_distribution SQL view."""

    def test_registers_only(self, db):
        row = db.execute(
            "SELECT config_count FROM bottleneck_distribution WHERE category='registers_only'"
        ).fetchone()
        assert row is not None, "Category 'registers_only' not found in view"
        assert row[0] == 832, f"registers_only: expected 832, got {row[0]}"

    def test_smem_only(self, db):
        row = db.execute(
            "SELECT config_count FROM bottleneck_distribution WHERE category='smem_only'"
        ).fetchone()
        assert row is not None, "Category 'smem_only' not found in view"
        assert row[0] == 66, f"smem_only: expected 66, got {row[0]}"

    def test_multiple(self, db):
        row = db.execute(
            "SELECT config_count FROM bottleneck_distribution WHERE category='multiple'"
        ).fetchone()
        assert row is not None, "Category 'multiple' not found in view"
        assert row[0] == 86, f"multiple: expected 86, got {row[0]}"

    def test_distribution_total(self, db):
        total = db.execute(
            "SELECT SUM(config_count) FROM bottleneck_distribution"
        ).fetchone()[0]
        assert total == 984, f"Distribution total {total} != 984"


# ============================================================================
# JSON Output Tests
# ============================================================================

@pytest.fixture(scope="module")
def analysis():
    path = "/app/output/analysis.json"
    assert os.path.exists(path), f"Output file {path} does not exist"
    with open(path) as f:
        data = json.load(f)
    return data


class TestJSONAggregates:
    """Verify JSON aggregate statistics."""

    def test_total_valid_configs(self, analysis):
        assert analysis["total_valid_configs"] == 984

    def test_max_occupancy(self, analysis):
        assert abs(analysis["max_occupancy_pct"] - 100.0) < 0.01

    def test_num_at_max(self, analysis):
        assert analysis["num_configs_at_max_occupancy"] == 2

    def test_num_above_50(self, analysis):
        assert analysis["num_configs_above_50pct_occupancy"] == 52

    def test_bottleneck_registers(self, analysis):
        assert analysis["bottleneck_distribution"]["registers_only"] == 832

    def test_bottleneck_smem(self, analysis):
        assert analysis["bottleneck_distribution"]["smem_only"] == 66

    def test_bottleneck_warps(self, analysis):
        assert analysis["bottleneck_distribution"]["warps_only"] == 0

    def test_bottleneck_multiple(self, analysis):
        assert analysis["bottleneck_distribution"]["multiple"] == 86


class TestJSONSpecificConfigs:
    """Verify specific configuration analyses in JSON."""

    def test_config_a_valid(self, analysis):
        cfg = next(c for c in analysis["specific_configs"] if c["label"] == "A")
        assert cfg["valid"] is True
        assert cfg["regs_per_thread"] == 155
        assert cfg["smem_bytes"] == 16384
        assert abs(cfg["occupancy_pct"] - 25.0) < 0.01
        assert cfg["max_blocks_per_sm"] == 3

    def test_config_c_full_occupancy(self, analysis):
        cfg = next(c for c in analysis["specific_configs"] if c["label"] == "C")
        assert cfg["valid"] is True
        assert abs(cfg["occupancy_pct"] - 100.0) < 0.01
        assert sorted(cfg["bottleneck"]) == ["registers", "warps"]

    def test_config_d_invalid(self, analysis):
        cfg = next(c for c in analysis["specific_configs"] if c["label"] == "D")
        assert cfg["valid"] is False
        assert cfg["occupancy_pct"] is None
        assert cfg["regs_per_thread"] is None
