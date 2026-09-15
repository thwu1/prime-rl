"""
Tests for Oracle Performance Advisor Audit.

Validates the corrected diagnosis, consultant evaluation, remediation script,
and the SQLite analysis database.

"""

import json
import os
import re
import sqlite3
import pytest


@pytest.fixture
def report():
    path = "/app/corrected_diagnosis.json"
    assert os.path.exists(path), "corrected_diagnosis.json not found at /app/"
    with open(path) as f:
        data = json.load(f)
    return data


@pytest.fixture
def evaluation():
    path = "/app/evaluation.json"
    assert os.path.exists(path), "evaluation.json not found at /app/"
    with open(path) as f:
        data = json.load(f)
    return data


@pytest.fixture
def remediation():
    path = "/app/remediation.sql"
    assert os.path.exists(path), "remediation.sql not found at /app/"
    with open(path) as f:
        return f.read()


@pytest.fixture
def analysis_db():
    path = "/app/analysis.db"
    assert os.path.exists(path), "analysis.db not found at /app/"
    conn = sqlite3.connect(path)
    yield conn
    conn.close()


# -- Analysis DB Tests --------------------------------------------------------


class TestAnalysisDB:
    REQUIRED_TABLES = [
        "sysstat", "system_event", "db_cache_advice",
        "librarycache", "pgastat", "pga_target_advice", "sqlarea"
    ]

    def test_tables_exist(self, analysis_db):
        cursor = analysis_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0].lower() for row in cursor.fetchall()}
        for t in self.REQUIRED_TABLES:
            assert t in tables, f"Table '{t}' missing from analysis.db (found: {tables})"

    def test_sysstat_has_rows(self, analysis_db):
        cursor = analysis_db.execute("SELECT COUNT(*) FROM sysstat")
        count = cursor.fetchone()[0]
        assert count >= 20, f"sysstat should have >= 20 rows, got {count}"

    def test_system_event_has_rows(self, analysis_db):
        cursor = analysis_db.execute("SELECT COUNT(*) FROM system_event")
        count = cursor.fetchone()[0]
        assert count >= 10, f"system_event should have >= 10 rows, got {count}"

    def test_sqlarea_has_rows(self, analysis_db):
        cursor = analysis_db.execute("SELECT COUNT(*) FROM sqlarea")
        count = cursor.fetchone()[0]
        assert count >= 6, f"sqlarea should have >= 6 rows, got {count}"


# -- Evaluation Tests ---------------------------------------------------------


class TestEvaluation:
    def test_has_all_consultants(self, evaluation):
        for key in ["consultant_A", "consultant_B", "consultant_C"]:
            assert key in evaluation, f"evaluation.json missing '{key}'"

    def test_has_best_report(self, evaluation):
        assert "best_report" in evaluation
        assert evaluation["best_report"] == "consultant_C", (
            f"Expected best_report='consultant_C', got {evaluation['best_report']}"
        )

    def test_consultant_c_ranked_first(self, evaluation):
        assert evaluation["consultant_C"]["rank"] == 1, (
            f"Consultant C should be rank 1, got {evaluation['consultant_C']['rank']}"
        )

    def test_consultant_b_ranked_last(self, evaluation):
        assert evaluation["consultant_B"]["rank"] == 3, (
            f"Consultant B should be rank 3, got {evaluation['consultant_B']['rank']}"
        )

    def test_consultant_a_ranked_second(self, evaluation):
        assert evaluation["consultant_A"]["rank"] == 2, (
            f"Consultant A should be rank 2, got {evaluation['consultant_A']['rank']}"
        )

    def test_accuracy_ordering(self, evaluation):
        score_c = evaluation["consultant_C"]["accuracy_score"]
        score_a = evaluation["consultant_A"]["accuracy_score"]
        score_b = evaluation["consultant_B"]["accuracy_score"]
        assert score_c > score_a > score_b, (
            f"Expected C ({score_c}) > A ({score_a}) > B ({score_b})"
        )

    def test_consultant_b_has_more_errors_than_c(self, evaluation):
        errors_b = len(evaluation["consultant_B"]["errors"])
        errors_c = len(evaluation["consultant_C"]["errors"])
        assert errors_b > errors_c, (
            f"Consultant B should have more errors ({errors_b}) than C ({errors_c})"
        )

    def test_consultant_b_buffer_cache_error_identified(self, evaluation):
        """Consultant B has wrong buffer cache hit ratio (0.90 vs correct 0.85)"""
        errors = evaluation["consultant_B"]["errors"]
        fields = [e["field"].lower() for e in errors]
        found = any("buffer_cache" in f and "hit_ratio" in f for f in fields)
        assert found, (
            f"Expected consultant B error about buffer_cache.hit_ratio, found fields: {fields}"
        )

    def test_consultant_b_library_root_cause_error(self, evaluation):
        """Consultant B has wrong library cache root cause"""
        errors = evaluation["consultant_B"]["errors"]
        fields = [e["field"].lower() for e in errors]
        found = any("library_cache" in f and "root_cause" in f for f in fields)
        assert found, (
            f"Expected consultant B error about library_cache.root_cause, found fields: {fields}"
        )

    def test_consultant_a_sql_id_error(self, evaluation):
        """Consultant A identified wrong problematic SQL"""
        errors = evaluation["consultant_A"]["errors"]
        fields = [e["field"].lower() for e in errors]
        found = any("sql_id" in f for f in fields)
        assert found, (
            f"Expected consultant A error about problematic_sql.sql_id, found fields: {fields}"
        )

    def test_consultant_a_pga_error(self, evaluation):
        """Consultant A has wrong PGA recommended target"""
        errors = evaluation["consultant_A"]["errors"]
        fields = [e["field"].lower() for e in errors]
        found = any("pga" in f and "recommended" in f for f in fields)
        assert found, (
            f"Expected consultant A error about pga.recommended_target_mb, found fields: {fields}"
        )


# -- Buffer Cache Tests -------------------------------------------------------


class TestBufferCache:
    def test_hit_ratio(self, report):
        bc = report["buffer_cache"]
        assert "hit_ratio" in bc
        assert abs(bc["hit_ratio"] - 0.85) < 0.02, (
            f"Expected buffer cache hit ratio ~0.85, got {bc['hit_ratio']}"
        )

    def test_current_size(self, report):
        bc = report["buffer_cache"]
        assert "current_size_mb" in bc
        assert bc["current_size_mb"] == 512, (
            f"Expected current buffer cache size 512 MB, got {bc['current_size_mb']}"
        )

    def test_recommended_size(self, report):
        bc = report["buffer_cache"]
        assert "recommended_size_mb" in bc
        rec = bc["recommended_size_mb"]
        assert 640 <= rec <= 1024, (
            f"Expected recommended size between 640-1024 MB, got {rec}"
        )

    def test_status_undersized(self, report):
        bc = report["buffer_cache"]
        assert "status" in bc
        assert bc["status"] == "undersized", (
            f"Expected buffer cache status 'undersized', got {bc['status']}"
        )


# -- Library Cache Tests -------------------------------------------------------


class TestLibraryCache:
    def test_hit_ratio(self, report):
        lc = report["library_cache"]
        assert "hit_ratio" in lc
        assert abs(lc["hit_ratio"] - 0.925) < 0.01, (
            f"Expected library cache hit ratio ~0.925, got {lc['hit_ratio']}"
        )

    def test_reloads(self, report):
        lc = report["library_cache"]
        assert "reloads" in lc
        assert lc["reloads"] == 150000, (
            f"Expected reloads 150000, got {lc['reloads']}"
        )

    def test_hard_parse_ratio(self, report):
        lc = report["library_cache"]
        assert "hard_parse_ratio" in lc
        assert abs(lc["hard_parse_ratio"] - 0.48) < 0.02, (
            f"Expected hard parse ratio ~0.48, got {lc['hard_parse_ratio']}"
        )

    def test_root_cause_literal_sql(self, report):
        lc = report["library_cache"]
        assert "root_cause" in lc
        assert "literal" in lc["root_cause"].lower(), (
            f"Expected root cause containing 'literal', got {lc['root_cause']}"
        )


# -- PGA Tests -----------------------------------------------------------------


class TestPGA:
    def test_current_target(self, report):
        pga = report["pga"]
        assert "current_target_mb" in pga
        assert pga["current_target_mb"] == 256, (
            f"Expected PGA current target 256 MB, got {pga['current_target_mb']}"
        )

    def test_recommended_target(self, report):
        pga = report["pga"]
        assert "recommended_target_mb" in pga
        assert pga["recommended_target_mb"] == 512, (
            f"Expected PGA recommended target 512 MB, got {pga['recommended_target_mb']}"
        )

    def test_cache_hit_pct(self, report):
        pga = report["pga"]
        assert "cache_hit_pct" in pga
        assert abs(pga["cache_hit_pct"] - 62.5) < 1.0, (
            f"Expected PGA cache hit ~62.5%, got {pga['cache_hit_pct']}"
        )

    def test_multipass_ratio(self, report):
        pga = report["pga"]
        assert "multipass_ratio" in pga
        assert abs(pga["multipass_ratio"] - 0.15) < 0.02, (
            f"Expected multipass ratio ~0.15, got {pga['multipass_ratio']}"
        )

    def test_overalloc_count(self, report):
        pga = report["pga"]
        assert "overalloc_count" in pga
        assert pga["overalloc_count"] == 45, (
            f"Expected overalloc count 45, got {pga['overalloc_count']}"
        )


# -- Wait Event Tests ----------------------------------------------------------


class TestWaitEvents:
    def test_top_events_exist(self, report):
        assert "top_wait_events" in report
        events = report["top_wait_events"]
        assert len(events) >= 3, f"Expected at least 3 top wait events, got {len(events)}"

    def test_top_event_is_db_file_sequential_read(self, report):
        events = report["top_wait_events"]
        top = events[0]
        assert "event" in top
        assert "db file sequential read" in top["event"].lower(), (
            f"Expected top event 'db file sequential read', got {top['event']}"
        )

    def test_top_event_time(self, report):
        events = report["top_wait_events"]
        top = events[0]
        assert "time_waited_s" in top
        assert abs(top["time_waited_s"] - 35000.0) < 100, (
            f"Expected ~35000s for top event, got {top['time_waited_s']}"
        )

    def test_second_event_is_latch_shared_pool(self, report):
        events = report["top_wait_events"]
        second = events[1]
        assert "latch" in second["event"].lower() and "shared pool" in second["event"].lower(), (
            f"Expected second event 'latch: shared pool', got {second['event']}"
        )

    def test_third_event_is_direct_path(self, report):
        events = report["top_wait_events"]
        third = events[2]
        assert "direct path" in third["event"].lower(), (
            f"Expected third event to contain 'direct path', got {third['event']}"
        )


# -- Problematic SQL Tests -----------------------------------------------------


class TestProblematicSQL:
    def test_sql_id(self, report):
        sql = report["problematic_sql"]
        assert "sql_id" in sql
        assert sql["sql_id"] == "abc123def456", (
            f"Expected problematic SQL ID 'abc123def456', got {sql['sql_id']}"
        )

    def test_buffer_gets_per_exec(self, report):
        sql = report["problematic_sql"]
        assert "buffer_gets_per_exec" in sql
        assert abs(sql["buffer_gets_per_exec"] - 500.0) < 5, (
            f"Expected ~500 buffer gets/exec, got {sql['buffer_gets_per_exec']}"
        )

    def test_disk_reads_per_exec(self, report):
        sql = report["problematic_sql"]
        assert "disk_reads_per_exec" in sql
        assert abs(sql["disk_reads_per_exec"] - 150.0) < 5, (
            f"Expected ~150 disk reads/exec, got {sql['disk_reads_per_exec']}"
        )

    def test_issue_is_full_table_scan(self, report):
        sql = report["problematic_sql"]
        assert "issue" in sql
        assert "full" in sql["issue"].lower() and "scan" in sql["issue"].lower(), (
            f"Expected issue containing 'full' and 'scan', got {sql['issue']}"
        )

    def test_missing_index_columns(self, report):
        sql = report["problematic_sql"]
        assert "missing_index_columns" in sql
        cols = [c.lower() for c in sql["missing_index_columns"]]
        assert "customer_id" in cols, f"Expected 'customer_id' in missing index columns, got {cols}"
        assert "order_date" in cols, f"Expected 'order_date' in missing index columns, got {cols}"


# -- Root Causes Ranked Tests --------------------------------------------------


class TestRootCauses:
    def test_root_causes_exist(self, report):
        assert "root_causes_ranked" in report
        rc = report["root_causes_ranked"]
        assert len(rc) >= 3, f"Expected at least 3 root causes, got {len(rc)}"

    def test_top_root_cause_is_buffer_cache(self, report):
        rc = report["root_causes_ranked"]
        top = rc[0].lower()
        assert "buffer" in top or "cache" in top, (
            f"Expected top root cause related to buffer cache, got {rc[0]}"
        )

    def test_contains_pga_issue(self, report):
        rc_lower = [r.lower() for r in report["root_causes_ranked"]]
        found = any("pga" in r or ("memory" in r and "pga" in r) for r in rc_lower)
        assert found, f"Expected a root cause related to PGA, got {report['root_causes_ranked']}"

    def test_contains_parsing_issue(self, report):
        rc_lower = [r.lower() for r in report["root_causes_ranked"]]
        found = any("pars" in r or "literal" in r or "cursor" in r for r in rc_lower)
        assert found, (
            f"Expected a root cause related to hard parsing/literal SQL, "
            f"got {report['root_causes_ranked']}"
        )

    def test_contains_index_issue(self, report):
        rc_lower = [r.lower() for r in report["root_causes_ranked"]]
        found = any("index" in r for r in rc_lower)
        assert found, (
            f"Expected a root cause related to missing index, got {report['root_causes_ranked']}"
        )


# -- Remediation SQL Tests -----------------------------------------------------


class TestRemediation:
    def test_db_cache_size_alter(self, remediation):
        pattern = r"ALTER\s+SYSTEM\s+SET\s+db_cache_size"
        assert re.search(pattern, remediation, re.IGNORECASE), (
            "remediation.sql must contain ALTER SYSTEM SET db_cache_size"
        )

    def test_db_cache_size_scope(self, remediation):
        lines = remediation.lower()
        assert "db_cache_size" in lines and "scope" in lines, (
            "db_cache_size ALTER SYSTEM should specify SCOPE"
        )

    def test_pga_aggregate_target_alter(self, remediation):
        pattern = r"ALTER\s+SYSTEM\s+SET\s+pga_aggregate_target"
        assert re.search(pattern, remediation, re.IGNORECASE), (
            "remediation.sql must contain ALTER SYSTEM SET pga_aggregate_target"
        )

    def test_cursor_sharing_alter(self, remediation):
        pattern = r"ALTER\s+SYSTEM\s+SET\s+cursor_sharing"
        assert re.search(pattern, remediation, re.IGNORECASE), (
            "remediation.sql must contain ALTER SYSTEM SET cursor_sharing"
        )

    def test_cursor_sharing_force(self, remediation):
        lower = remediation.lower()
        assert "cursor_sharing" in lower and "force" in lower, (
            "cursor_sharing should be set to FORCE"
        )

    def test_create_index(self, remediation):
        pattern = r"CREATE\s+INDEX"
        assert re.search(pattern, remediation, re.IGNORECASE), (
            "remediation.sql must contain CREATE INDEX"
        )

    def test_index_on_customer_id(self, remediation):
        lower = remediation.lower()
        assert "customer_id" in lower, (
            "CREATE INDEX should reference customer_id column"
        )

    def test_index_on_orders_table(self, remediation):
        lower = remediation.lower()
        assert "orders" in lower, (
            "CREATE INDEX should reference orders table"
        )
