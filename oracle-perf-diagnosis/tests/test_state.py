
import json
import os
import sqlite3
import struct
import pytest


RESULTS_PATH = "/app/diagnosis/results.json"


@pytest.fixture
def results():
    assert os.path.isfile(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestResultsStructure:
    """Verify the output JSON has the required structure."""

    def test_top_level_keys(self, results):
        required = {
            "metrics", "memory_recommendations", "wait_analysis",
            "sql_tuning", "primary_bottleneck", "report_evaluation",
        }
        assert required.issubset(set(results.keys())), \
            f"Missing keys: {required - set(results.keys())}"

    def test_metrics_keys(self, results):
        required = {
            "buffer_cache_hit_ratio", "library_cache_hit_ratio",
            "soft_parse_ratio", "in_memory_sort_ratio",
            "execute_to_parse_ratio", "db_time_cpu_pct", "db_time_wait_pct",
        }
        assert required.issubset(set(results["metrics"].keys())), \
            f"Missing metric keys: {required - set(results['metrics'].keys())}"

    def test_memory_rec_keys(self, results):
        required = {"db_cache_size_mb", "pga_aggregate_target_mb"}
        assert required.issubset(set(results["memory_recommendations"].keys()))

    def test_wait_analysis_keys(self, results):
        required = {"top_event", "top_event_time_sec", "total_wait_time_sec"}
        assert required.issubset(set(results["wait_analysis"].keys()))

    def test_sql_tuning_keys(self, results):
        required = {"top_sql_by_elapsed", "literal_sql_ids", "cursor_sharing"}
        assert required.issubset(set(results["sql_tuning"].keys()))

    def test_report_evaluation_keys(self, results):
        assert "report_evaluation" in results
        eval_data = results["report_evaluation"]
        assert "report_a" in eval_data, "Missing report_a in evaluation"
        assert "report_b" in eval_data, "Missing report_b in evaluation"
        assert "better_report" in eval_data, "Missing better_report in evaluation"


class TestBufferCacheHitRatio:
    """
    Buffer cache hit ratio from sysstat deltas.
    Delta: physical_reads=13000000, physical_reads_direct=700000,
           consistent_gets=33000000, db_block_gets=17000000.
    Correct: 1 - (13000000-700000)/(33000000+17000000) = 0.754
    Accept range [0.74, 0.76].
    """

    def test_buffer_cache_hit_ratio_range(self, results):
        ratio = results["metrics"]["buffer_cache_hit_ratio"]
        assert 0.74 <= ratio <= 0.76, \
            f"Buffer cache hit ratio {ratio} not in [0.74, 0.76]."

    def test_buffer_cache_hit_ratio_indicates_problem(self, results):
        ratio = results["metrics"]["buffer_cache_hit_ratio"]
        assert ratio < 0.90, "Hit ratio should indicate a problem (< 0.90)"


class TestLibraryCacheHitRatio:
    """
    Library cache hit ratio from shared_pool_stats.
    pinhits/pins = 5660000/6500000 = 0.87077
    Accept [0.86, 0.88].
    """

    def test_library_cache_hit_ratio(self, results):
        ratio = results["metrics"]["library_cache_hit_ratio"]
        assert 0.86 <= ratio <= 0.88, \
            f"Library cache hit ratio {ratio} not in [0.86, 0.88]. Expected ~0.8708."


class TestSoftParseRatio:
    """
    Soft parse ratio from sysstat deltas.
    (parse_total - parse_hard) / parse_total = (2800000-840000)/2800000 = 0.70
    """

    def test_soft_parse_ratio(self, results):
        ratio = results["metrics"]["soft_parse_ratio"]
        assert 0.69 <= ratio <= 0.71, \
            f"Soft parse ratio {ratio} not in [0.69, 0.71]. Expected 0.70."


class TestInMemorySortRatio:
    """
    In-memory sort ratio from sysstat deltas.
    sorts_memory / (sorts_memory + sorts_disk) = 200000/215000 = 0.9302
    """

    def test_in_memory_sort_ratio(self, results):
        ratio = results["metrics"]["in_memory_sort_ratio"]
        assert 0.92 <= ratio <= 0.94, \
            f"In-memory sort ratio {ratio} not in [0.92, 0.94]. Expected ~0.9302."


class TestExecuteToParseRatio:
    """
    Execute-to-parse ratio from sysstat deltas.
    1 - (parse_total / execute_count) = 1 - 2800000/3300000 = 0.1515
    """

    def test_execute_to_parse_ratio(self, results):
        ratio = results["metrics"]["execute_to_parse_ratio"]
        assert 0.13 <= ratio <= 0.17, \
            f"Execute-to-parse ratio {ratio} not in [0.13, 0.17]. Expected ~0.1515."


class TestDBTimeSplit:
    """
    DB time CPU/wait split from time_model.
    DB CPU / DB time = 5400000000/18000000000 = 0.30
    Wait = 0.70
    """

    def test_db_time_cpu_pct(self, results):
        pct = results["metrics"]["db_time_cpu_pct"]
        assert 0.28 <= pct <= 0.32, \
            f"DB time CPU pct {pct} not in [0.28, 0.32]. Expected 0.30."

    def test_db_time_wait_pct(self, results):
        pct = results["metrics"]["db_time_wait_pct"]
        assert 0.68 <= pct <= 0.72, \
            f"DB time wait pct {pct} not in [0.68, 0.72]. Expected 0.70."

    def test_cpu_wait_sum_to_one(self, results):
        cpu = results["metrics"]["db_time_cpu_pct"]
        wait = results["metrics"]["db_time_wait_pct"]
        assert abs(cpu + wait - 1.0) < 0.05, \
            f"CPU ({cpu}) + wait ({wait}) should sum to ~1.0"


class TestMemoryRecommendations:
    """
    Buffer cache: knee at 768 MB from advisory curve analysis. Accept [640, 768, 896].
    PGA: first target with overalloc=0 AND cache_hit>=95% with diminishing returns. Accept [768, 1024].
    """

    def test_db_cache_size_recommendation(self, results):
        size = results["memory_recommendations"]["db_cache_size_mb"]
        assert size in [640, 768, 896], \
            f"db_cache_size_mb={size} not in acceptable range [640, 768, 896]."

    def test_db_cache_size_is_increase(self, results):
        size = results["memory_recommendations"]["db_cache_size_mb"]
        assert size > 512, f"Must recommend increase from current 512 MB, got {size}"

    def test_pga_target_recommendation(self, results):
        size = results["memory_recommendations"]["pga_aggregate_target_mb"]
        assert size in [768, 1024], \
            f"pga_aggregate_target_mb={size} not in [768, 1024]."

    def test_pga_target_is_increase(self, results):
        size = results["memory_recommendations"]["pga_aggregate_target_mb"]
        assert size > 512, f"Must recommend increase from current 512 MB, got {size}"


class TestWaitAnalysis:
    """
    Top event by time: 'db file sequential read' at 4250 seconds.
    Total wait time: 12600 seconds.
    """

    def test_top_event_name(self, results):
        event = results["wait_analysis"]["top_event"]
        assert event == "db file sequential read", \
            f"Top event should be 'db file sequential read', got '{event}'"

    def test_top_event_time(self, results):
        time_sec = results["wait_analysis"]["top_event_time_sec"]
        assert 4200 <= time_sec <= 4300, \
            f"Top event time {time_sec} not in [4200, 4300]. Expected 4250."

    def test_total_wait_time(self, results):
        total = results["wait_analysis"]["total_wait_time_sec"]
        assert 12400 <= total <= 12800, \
            f"Total wait time {total} not in [12400, 12800]. Expected 12600."


class TestSQLTuning:
    """
    Top 3 by elapsed_time: 9r4fg7h1kp5m2, 4x7kf9q2ua3h1, 6j3mw2f9xp4a7.
    Literal SQL: 7m2nd5p8bc9k3 (version_count=184000).
    Cursor sharing: FORCE.
    """

    def test_top_sql_first(self, results):
        top = results["sql_tuning"]["top_sql_by_elapsed"]
        assert len(top) >= 3, f"Expected at least 3 top SQL IDs, got {len(top)}"
        assert top[0] == "9r4fg7h1kp5m2", \
            f"First SQL should be 9r4fg7h1kp5m2, got {top[0]}"

    def test_top_sql_contains_expected(self, results):
        top = results["sql_tuning"]["top_sql_by_elapsed"][:3]
        expected = {"9r4fg7h1kp5m2", "4x7kf9q2ua3h1", "6j3mw2f9xp4a7"}
        assert expected == set(top), \
            f"Top 3 SQL should be {expected}, got {set(top)}"

    def test_literal_sql_detected(self, results):
        literal = results["sql_tuning"]["literal_sql_ids"]
        assert "7m2nd5p8bc9k3" in literal, \
            f"Should detect 7m2nd5p8bc9k3 as literal SQL (version_count=184000)"

    def test_cursor_sharing_force(self, results):
        cs = results["sql_tuning"]["cursor_sharing"]
        assert cs.upper() == "FORCE", \
            f"cursor_sharing should be FORCE due to literal SQL, got '{cs}'"


class TestPrimaryBottleneck:
    """
    Primary bottleneck is buffer_cache (root cause), not io (symptom).
    Evidence: BCHR=0.754 (<0.90), free buffer waits significant,
    I/O waits dominate but avg wait times are low (0.5ms seq, 1.2ms scattered)
    indicating fast I/O subsystem — the problem is too many reads from undersized cache.
    """

    def test_primary_bottleneck(self, results):
        bottleneck = results["primary_bottleneck"]
        assert bottleneck == "buffer_cache", \
            f"Primary bottleneck should be 'buffer_cache' (root cause, not 'io' symptom), got '{bottleneck}'"


class TestSQLiteDatabase:
    """Verify SQLite database was created with loaded data."""

    def test_db_exists(self):
        assert os.path.isfile("/app/audit.db"), \
            "SQLite database not found at /app/audit.db"

    def test_has_tables(self):
        conn = sqlite3.connect("/app/audit.db")
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        assert len(tables) >= 3, \
            f"Expected at least 3 tables in SQLite DB, found {len(tables)}: {tables}"

    def test_has_data(self):
        conn = sqlite3.connect("/app/audit.db")
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        total_rows = 0
        for table in tables:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            total_rows += cursor.fetchone()[0]
        conn.close()
        assert total_rows >= 20, \
            f"Expected at least 20 total rows in SQLite DB, found {total_rows}"


class TestGnuplotCharts:
    """Verify gnuplot advisory curve charts were generated as valid PNG files."""

    def test_db_cache_chart_exists(self):
        path = "/app/diagnosis/db_cache_advisory.png"
        assert os.path.isfile(path), \
            f"DB cache advisory chart not found at {path}"

    def test_db_cache_chart_is_png(self):
        with open("/app/diagnosis/db_cache_advisory.png", "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', \
            "db_cache_advisory.png is not a valid PNG file"

    def test_pga_chart_exists(self):
        path = "/app/diagnosis/pga_advisory.png"
        assert os.path.isfile(path), \
            f"PGA advisory chart not found at {path}"

    def test_pga_chart_is_png(self):
        with open("/app/diagnosis/pga_advisory.png", "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', \
            "pga_advisory.png is not a valid PNG file"


class TestReportEvaluation:
    """
    Verify the peer review evaluation of the two DBA reports.

    Report A (Alice) errors: buffer_cache_hit_ratio (0.7847 vs 0.754),
      execute_to_parse_ratio (0.30 vs 0.1515), db_cache_size_mb (1024 vs 768),
      pga_aggregate_target_mb (384 vs 1024), primary_bottleneck (io vs buffer_cache).
      Score: 7/12 = 0.583

    Report B (Bob) errors: library_cache_hit_ratio (0.98 vs 0.87),
      top_sql_by_elapsed (wrong order), literal_sql_ids (empty), cursor_sharing (EXACT vs FORCE).
      Score: 8/12 = 0.667

    Better report: B
    """

    def test_report_a_has_accuracy(self, results):
        ra = results["report_evaluation"]["report_a"]
        assert "accuracy_score" in ra, "Missing accuracy_score for report_a"
        assert "incorrect_claims" in ra, "Missing incorrect_claims for report_a"
        assert isinstance(ra["accuracy_score"], (int, float))
        assert isinstance(ra["incorrect_claims"], list)

    def test_report_b_has_accuracy(self, results):
        rb = results["report_evaluation"]["report_b"]
        assert "accuracy_score" in rb, "Missing accuracy_score for report_b"
        assert "incorrect_claims" in rb, "Missing incorrect_claims for report_b"

    def test_report_a_identifies_bchr_error(self, results):
        """Report A has buffer_cache_hit_ratio=0.7847, clearly wrong (correct ~0.754)."""
        claims = results["report_evaluation"]["report_a"]["incorrect_claims"]
        assert any("buffer_cache_hit" in c.lower() for c in claims), \
            f"Should identify buffer_cache_hit_ratio as incorrect in Report A. Got: {claims}"

    def test_report_a_identifies_bottleneck_error(self, results):
        """Report A says primary_bottleneck=io, should be buffer_cache."""
        claims = results["report_evaluation"]["report_a"]["incorrect_claims"]
        assert any("bottleneck" in c.lower() for c in claims), \
            f"Should identify primary_bottleneck as incorrect in Report A. Got: {claims}"

    def test_report_b_identifies_lchr_error(self, results):
        """Report B has library_cache_hit_ratio=0.98, clearly wrong (correct ~0.87)."""
        claims = results["report_evaluation"]["report_b"]["incorrect_claims"]
        assert any("library_cache_hit" in c.lower() for c in claims), \
            f"Should identify library_cache_hit_ratio as incorrect in Report B. Got: {claims}"

    def test_report_b_identifies_cursor_error(self, results):
        """Report B says cursor_sharing=EXACT, should be FORCE."""
        claims = results["report_evaluation"]["report_b"]["incorrect_claims"]
        assert any("cursor" in c.lower() for c in claims), \
            f"Should identify cursor_sharing as incorrect in Report B. Got: {claims}"

    def test_better_report_is_b(self, results):
        """Report B is more accurate overall and should be identified as better."""
        better = results["report_evaluation"]["better_report"].upper()
        assert better == "B", \
            f"Better report should be B, got '{better}'"

    def test_report_b_more_accurate_than_a(self, results):
        """Report B accuracy score should exceed Report A accuracy score."""
        score_a = results["report_evaluation"]["report_a"]["accuracy_score"]
        score_b = results["report_evaluation"]["report_b"]["accuracy_score"]
        assert score_b > score_a, \
            f"Report B score ({score_b}) should exceed Report A score ({score_a})"
