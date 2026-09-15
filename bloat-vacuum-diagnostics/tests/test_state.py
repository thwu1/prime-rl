"""Tests for PostgreSQL bloat estimation queries and vacuum advisory function.

"""

import subprocess
import os
import pytest

DBNAME = "testdb"


def psql(query, dbname=DBNAME):
    """Run a SQL query via psql, return output lines."""
    result = subprocess.run(
        ["psql", "-U", "postgres", "-d", dbname,
         "-t", "-A", "-F", "\t", "-c", query],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql error (rc={result.returncode}): {result.stderr}")
    lines = [line for line in result.stdout.strip().split('\n') if line.strip()]
    return lines


def psql_file(filepath, dbname=DBNAME):
    """Run a SQL file via psql, return (stdout, stderr, returncode)."""
    result = subprocess.run(
        ["psql", "-U", "postgres", "-d", dbname,
         "-t", "-A", "-F", "\t", "-f", filepath],
        capture_output=True, text=True, timeout=120
    )
    return result.stdout, result.stderr, result.returncode


def safe_float(s, default=0.0):
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def safe_int(s, default=0):
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return default


# ============================================================
# Table Bloat Estimation Tests
# ============================================================

class TestTableBloatEstimate:
    """Tests for the fixed /app/bloat_estimate.sql query."""

    def _get_results(self):
        stdout, stderr, rc = psql_file("/app/bloat_estimate.sql")
        assert rc == 0, f"bloat_estimate.sql failed: {stderr}"
        rows = []
        for line in stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) >= 10:
                rows.append({
                    'current_database': parts[0],
                    'schemaname': parts[1],
                    'tblname': parts[2],
                    'real_size': safe_int(parts[3]),
                    'extra_size': safe_int(parts[4]),
                    'extra_pct': safe_float(parts[5]),
                    'fillfactor': safe_int(parts[6], 100),
                    'bloat_size': safe_int(parts[7]),
                    'bloat_pct': safe_float(parts[8]),
                    'is_na': parts[9].strip().lower() in ('t', 'true'),
                })
        return rows

    def _get_public_rows(self):
        return [r for r in self._get_results() if r['schemaname'] == 'public']

    def test_query_executes(self):
        """The bloat_estimate.sql query should execute without errors."""
        stdout, stderr, rc = psql_file("/app/bloat_estimate.sql")
        assert rc == 0, f"Query failed: {stderr}"

    def test_returns_test_tables(self):
        """All test tables should appear in results."""
        rows = self._get_public_rows()
        table_names = {r['tblname'] for r in rows}
        for tbl in ['test_minimal', 'test_moderate', 'test_heavy']:
            assert tbl in table_names, f"Table '{tbl}' not found in bloat results"

    def test_default_fillfactor_is_100(self):
        """Tables without explicit fillfactor should default to 100."""
        rows = self._get_public_rows()
        for r in rows:
            if r['tblname'] in ('test_minimal', 'test_moderate', 'test_heavy'):
                assert r['fillfactor'] == 100, (
                    f"Table {r['tblname']} fillfactor={r['fillfactor']}, "
                    f"expected 100 (table default)"
                )

    def test_clean_table_low_extra_pct(self):
        """A clean table (no DML) should have very low extra_pct."""
        rows = self._get_public_rows()
        minimal = [r for r in rows if r['tblname'] == 'test_minimal']
        assert len(minimal) == 1, "test_minimal not found in results"
        assert minimal[0]['extra_pct'] < 5.0, (
            f"Clean table test_minimal has extra_pct={minimal[0]['extra_pct']:.2f}%, "
            f"expected < 5% for a table with no DML"
        )

    def test_moderate_bloat_detected(self):
        """Moderately bloated table should have meaningful extra_pct."""
        rows = self._get_public_rows()
        moderate = [r for r in rows if r['tblname'] == 'test_moderate']
        assert len(moderate) == 1
        assert moderate[0]['extra_pct'] > 10.0, (
            f"test_moderate has extra_pct={moderate[0]['extra_pct']:.2f}%, "
            f"expected > 10% after updating ~40% of rows"
        )

    def test_heavy_bloat_detected(self):
        """Heavily bloated table should have high extra_pct."""
        rows = self._get_public_rows()
        heavy = [r for r in rows if r['tblname'] == 'test_heavy']
        assert len(heavy) == 1
        assert heavy[0]['extra_pct'] > 35.0, (
            f"test_heavy has extra_pct={heavy[0]['extra_pct']:.2f}%, "
            f"expected > 35% after 50% updates + 33% deletes"
        )

    def test_bloat_accuracy_vs_pgstattuple(self):
        """Estimated bloat within 15pp of pgstattuple ground truth."""
        rows = self._get_public_rows()
        for tbl in ['test_moderate', 'test_heavy']:
            gt_lines = psql(
                f"SELECT dead_tuple_percent + free_percent "
                f"FROM pgstattuple('{tbl}')"
            )
            assert len(gt_lines) > 0, f"pgstattuple returned no data for {tbl}"
            actual_wasted = safe_float(gt_lines[0])

            est_row = [r for r in rows if r['tblname'] == tbl]
            assert len(est_row) == 1, f"{tbl} not found in bloat estimate results"
            est_extra = est_row[0]['extra_pct']

            diff = abs(est_extra - actual_wasted)
            assert diff < 15.0, (
                f"Table {tbl}: estimated extra_pct={est_extra:.1f}%, "
                f"pgstattuple wasted={actual_wasted:.1f}%, "
                f"difference={diff:.1f}pp exceeds 15pp tolerance"
            )


# ============================================================
# Index Bloat Estimation Tests
# ============================================================

class TestIndexBloatEstimate:
    """Tests for the fixed /app/index_bloat_estimate.sql query."""

    def _get_results(self):
        stdout, stderr, rc = psql_file("/app/index_bloat_estimate.sql")
        assert rc == 0, f"index_bloat_estimate.sql failed: {stderr}"
        rows = []
        for line in stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) >= 11:
                rows.append({
                    'current_database': parts[0],
                    'schemaname': parts[1],
                    'tblname': parts[2],
                    'idxname': parts[3],
                    'real_size': safe_int(parts[4]),
                    'extra_size': safe_int(parts[5]),
                    'extra_pct': safe_float(parts[6]),
                    'fillfactor': safe_int(parts[7], 90),
                    'bloat_size': safe_int(parts[8]),
                    'bloat_pct': safe_float(parts[9]),
                    'is_na': parts[10].strip().lower() in ('t', 'true'),
                })
        return rows

    def _get_public_rows(self):
        return [r for r in self._get_results() if r['schemaname'] == 'public']

    def test_query_executes(self):
        """index_bloat_estimate.sql should execute without errors."""
        stdout, stderr, rc = psql_file("/app/index_bloat_estimate.sql")
        assert rc == 0, f"Query failed: {stderr}"

    def test_returns_test_indexes(self):
        """Test indexes should appear in results."""
        rows = self._get_public_rows()
        idx_names = {r['idxname'] for r in rows}
        for idx in ['idx_minimal_a', 'idx_heavy_category']:
            assert idx in idx_names, f"Index '{idx}' not found in results"

    def test_default_fillfactor_is_90(self):
        """Btree indexes without explicit fillfactor should default to 90."""
        rows = self._get_public_rows()
        for r in rows:
            if r['idxname'] in ('idx_minimal_a', 'idx_moderate_name',
                                'idx_heavy_category', 'idx_heavy_counter'):
                assert r['fillfactor'] == 90, (
                    f"Index {r['idxname']} fillfactor={r['fillfactor']}, "
                    f"expected 90 (btree default)"
                )

    def test_values_reasonable(self):
        """Index bloat values should be in reasonable ranges."""
        rows = self._get_public_rows()
        assert len(rows) > 0, "No public indexes found"
        for r in rows:
            assert r['real_size'] > 0, (
                f"Index {r['idxname']} has zero real_size"
            )
            assert r['extra_pct'] > -50, (
                f"Index {r['idxname']} has unreasonably negative "
                f"extra_pct: {r['extra_pct']}"
            )

    def test_clean_index_reasonable_extra(self):
        """Clean index on unmodified table should have low extra_pct."""
        rows = self._get_public_rows()
        idx = [r for r in rows if r['idxname'] == 'idx_minimal_a']
        assert len(idx) == 1, "idx_minimal_a not found"
        assert idx[0]['extra_pct'] < 25.0, (
            f"Clean index idx_minimal_a has extra_pct={idx[0]['extra_pct']:.2f}%, "
            f"expected < 25% for unmodified table"
        )

    def test_bloated_index_detected(self):
        """Indexes on heavily modified table should show bloat."""
        rows = self._get_public_rows()
        heavy_idx = [r for r in rows if r['tblname'] == 'test_heavy']
        assert len(heavy_idx) > 0, "No indexes found for test_heavy"
        max_bloat = max(r['extra_pct'] for r in heavy_idx)
        assert max_bloat > 15.0, (
            f"Max index bloat on test_heavy is {max_bloat:.2f}%, "
            f"expected > 15% after heavy DML"
        )


# ============================================================
# Vacuum Advisory Function Tests
# ============================================================

class TestVacuumAdvisory:
    """Tests for the /app/vacuum_advisory.sql function."""

    @pytest.fixture(autouse=True)
    def setup_function(self):
        """Create the vacuum_advisory function from the solver's file."""
        assert os.path.exists("/app/vacuum_advisory.sql"), (
            "/app/vacuum_advisory.sql not found"
        )
        stdout, stderr, rc = psql_file("/app/vacuum_advisory.sql")
        assert rc == 0, f"vacuum_advisory.sql failed to execute: {stderr}"

    def _get_results(self):
        lines = psql("SELECT * FROM vacuum_advisory('public')")
        rows = []
        for line in lines:
            parts = line.split('\t')
            if len(parts) >= 9:
                rows.append({
                    'table_name': parts[0].strip(),
                    'table_size_bytes': safe_int(parts[1]),
                    'estimated_bloat_pct': safe_float(parts[2]),
                    'dead_tuple_count': safe_int(parts[3]),
                    'dead_tuple_pct': safe_float(parts[4]),
                    'max_index_bloat_pct': safe_float(parts[5]),
                    'last_vacuum': parts[6].strip() if parts[6].strip() else None,
                    'last_autovacuum': parts[7].strip() if parts[7].strip() else None,
                    'recommendation': parts[8].strip(),
                })
        return rows

    def test_function_callable(self):
        """vacuum_advisory function should be callable and return rows."""
        lines = psql("SELECT count(*) FROM vacuum_advisory('public')")
        assert len(lines) > 0
        count = int(lines[0].strip())
        assert count >= 3, f"Expected >= 3 rows, got {count}"

    def test_returns_all_test_tables(self):
        """All test tables should appear in vacuum_advisory output."""
        rows = self._get_results()
        table_names = {r['table_name'] for r in rows}
        for tbl in ['test_minimal', 'test_moderate', 'test_heavy']:
            assert tbl in table_names, (
                f"Table '{tbl}' not found in vacuum_advisory results"
            )

    def test_correct_columns(self):
        """Output should have expected column values."""
        rows = self._get_results()
        for r in rows:
            assert r['table_size_bytes'] > 0, (
                f"{r['table_name']} has zero table_size_bytes"
            )
            assert 0 <= r['estimated_bloat_pct'] <= 100, (
                f"{r['table_name']} has bloat_pct={r['estimated_bloat_pct']}"
            )
            assert r['dead_tuple_count'] >= 0, (
                f"{r['table_name']} has negative dead_tuple_count"
            )
            assert 0 <= r['dead_tuple_pct'] <= 100, (
                f"{r['table_name']} has dead_tuple_pct={r['dead_tuple_pct']}"
            )
            assert 0 <= r['max_index_bloat_pct'] <= 100 or r['max_index_bloat_pct'] == 0, (
                f"{r['table_name']} has max_index_bloat={r['max_index_bloat_pct']}"
            )
            assert r['recommendation'] in ('OK', 'VACUUM', 'VACUUM FULL', 'REINDEX'), (
                f"{r['table_name']} has invalid recommendation: {r['recommendation']}"
            )

    def test_recommendation_consistency(self):
        """Each recommendation should follow the priority rules."""
        rows = self._get_results()
        for r in rows:
            bp = r['estimated_bloat_pct']
            ibp = r['max_index_bloat_pct']
            dp = r['dead_tuple_pct']
            rec = r['recommendation']

            if bp > 50:
                assert rec == 'VACUUM FULL', (
                    f"{r['table_name']}: bloat={bp:.1f}% > 50 "
                    f"=> expected VACUUM FULL, got {rec}"
                )
            elif ibp > 30 and bp <= 50:
                assert rec == 'REINDEX', (
                    f"{r['table_name']}: idx_bloat={ibp:.1f}% > 30, "
                    f"bloat={bp:.1f}% <= 50 => expected REINDEX, got {rec}"
                )
            elif bp > 20 or dp > 5:
                assert rec == 'VACUUM', (
                    f"{r['table_name']}: bloat={bp:.1f}% or dead={dp:.1f}% "
                    f"=> expected VACUUM, got {rec}"
                )
            else:
                assert rec == 'OK', (
                    f"{r['table_name']}: low bloat/dead => expected OK, got {rec}"
                )

    def test_clean_table_gets_ok(self):
        """Clean table with no DML should get OK recommendation."""
        rows = self._get_results()
        minimal = [r for r in rows if r['table_name'] == 'test_minimal']
        assert len(minimal) == 1
        assert minimal[0]['recommendation'] == 'OK', (
            f"Clean table got '{minimal[0]['recommendation']}', expected 'OK'"
        )

    def test_heavy_bloat_gets_vacuum_or_full(self):
        """Heavily bloated table should get VACUUM FULL or VACUUM."""
        rows = self._get_results()
        heavy = [r for r in rows if r['table_name'] == 'test_heavy']
        assert len(heavy) == 1
        assert heavy[0]['recommendation'] in ('VACUUM FULL', 'VACUUM'), (
            f"Heavy table got '{heavy[0]['recommendation']}', "
            f"expected 'VACUUM FULL' or 'VACUUM'"
        )
        # If estimated bloat > 50%, must specifically be VACUUM FULL
        if heavy[0]['estimated_bloat_pct'] > 50:
            assert heavy[0]['recommendation'] == 'VACUUM FULL', (
                f"Bloat={heavy[0]['estimated_bloat_pct']:.1f}% > 50% "
                f"but got '{heavy[0]['recommendation']}'"
            )

    def test_dead_tuples_for_modified_tables(self):
        """Modified tables should have positive dead tuple counts."""
        rows = self._get_results()
        for tbl in ['test_moderate', 'test_heavy']:
            row = [r for r in rows if r['table_name'] == tbl]
            assert len(row) == 1, f"{tbl} not found"
            assert row[0]['dead_tuple_count'] > 0, (
                f"{tbl} should have dead tuples, got {row[0]['dead_tuple_count']}"
            )
            assert row[0]['dead_tuple_pct'] > 1.0, (
                f"{tbl} should have dead_tuple_pct > 1%, "
                f"got {row[0]['dead_tuple_pct']:.2f}%"
            )
