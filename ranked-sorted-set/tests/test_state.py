
import json
import os
import shutil
import subprocess
import sys
import time

import pytest
import redis as redis_lib

REPORT_PATH = '/app/audit_report.json'

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def redis_client():
    """Connect to Redis; try starting it if not running."""
    r = redis_lib.Redis(host='localhost', port=6379, decode_responses=True)
    try:
        r.ping()
    except redis_lib.ConnectionError:
        subprocess.run(['redis-server', '--daemonize', 'yes', '--save', ''],
                        check=False)
        time.sleep(2)
        try:
            r.ping()
        except redis_lib.ConnectionError:
            pytest.skip("Cannot connect to Redis")
    return r


@pytest.fixture(scope='session')
def report():
    """Load the audit report directly from disk."""
    if not os.path.exists(REPORT_PATH):
        pytest.fail(f"Audit report not found at {REPORT_PATH}")
    with open(REPORT_PATH) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        pytest.fail("Audit report is not a JSON object")
    return data


# ---------------------------------------------------------------------------
# 1. Report existence and validity
# ---------------------------------------------------------------------------

class TestReportExists:
    def test_report_file_exists(self):
        assert os.path.exists(REPORT_PATH), \
            f"audit_report.json must exist at {REPORT_PATH}"

    def test_report_valid_json(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict), "Report must be a JSON object"


# ---------------------------------------------------------------------------
# 2. Report structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_has_sorted_sets_list(self, report):
        assert 'sorted_sets' in report, "Report must have 'sorted_sets'"
        assert isinstance(report['sorted_sets'], list)

    def test_sorted_set_count(self, report):
        zsets = [
            s for s in report['sorted_sets']
            if s.get('encoding') in ('listpack', 'skiplist', 'ziplist')
        ]
        assert len(zsets) == 25, \
            f"Expected 25 sorted sets in report, found {len(zsets)}"

    def test_each_set_has_required_fields(self, report):
        required = {'key', 'cardinality', 'encoding', 'memory_bytes'}
        for entry in report['sorted_sets']:
            enc = entry.get('encoding', '')
            if enc not in ('listpack', 'skiplist', 'ziplist'):
                continue
            missing = required - set(entry.keys())
            assert not missing, \
                f"Entry {entry.get('key', '?')} missing: {missing}"

    def test_has_theoretical_overhead(self, report):
        rstr = json.dumps(report).lower()
        assert 'theoretical' in rstr and 'overhead' in rstr, \
            "Report must include a theoretical skiplist overhead value"

    def test_has_suboptimal_identification(self, report):
        rstr = json.dumps(report).lower()
        markers = [
            'suboptimal', 'pathological', 'misconfigured',
            'should_be', 'encoding_optimal', 'needs_reencoding',
            'encoding_issue', 'recommendation',
        ]
        assert any(m in rstr for m in markers), \
            "Report must flag sets with suboptimal encoding"


# ---------------------------------------------------------------------------
# 3. Encoding analysis
# ---------------------------------------------------------------------------

class TestEncodingAnalysis:
    def _entries_by_prefix(self, report, prefix):
        return [
            e for e in report['sorted_sets']
            if e.get('key', '').startswith(prefix)
        ]

    def test_leaderboard_encoding_correct(self, report):
        for e in self._entries_by_prefix(report, 'leaderboard:'):
            assert e['encoding'] in ('listpack', 'ziplist'), \
                f"{e['key']} should be listpack, got {e['encoding']}"

    def test_analytics_encoding_correct(self, report):
        for e in self._entries_by_prefix(report, 'analytics:'):
            assert e['encoding'] == 'skiplist', \
                f"{e['key']} should be skiplist, got {e['encoding']}"

    def test_cardinality_leaderboard(self, report):
        for e in self._entries_by_prefix(report, 'leaderboard:'):
            assert 45 <= e['cardinality'] <= 55, \
                f"{e['key']}: expected ~50, got {e['cardinality']}"

    def test_cardinality_timeline(self, report):
        for e in self._entries_by_prefix(report, 'timeline:'):
            assert 295 <= e['cardinality'] <= 305, \
                f"{e['key']}: expected ~300, got {e['cardinality']}"

    def test_cardinality_index(self, report):
        for e in self._entries_by_prefix(report, 'index:'):
            assert 195 <= e['cardinality'] <= 205, \
                f"{e['key']}: expected ~200, got {e['cardinality']}"

    def test_cardinality_cache(self, report):
        for e in self._entries_by_prefix(report, 'cache:'):
            assert 445 <= e['cardinality'] <= 455, \
                f"{e['key']}: expected ~450, got {e['cardinality']}"

    def test_cardinality_analytics(self, report):
        for e in self._entries_by_prefix(report, 'analytics:'):
            assert 995 <= e['cardinality'] <= 1005, \
                f"{e['key']}: expected ~1000, got {e['cardinality']}"


# ---------------------------------------------------------------------------
# 4. Suboptimal-set identification
# ---------------------------------------------------------------------------

class TestSuboptimalIdentification:
    def test_medium_sets_flagged(self, report):
        """Timeline, index, and cache sets must be flagged as suboptimal."""
        flagged = set()
        for entry in report.get('sorted_sets', []):
            key = entry.get('key', '')
            is_flagged = (
                entry.get('encoding_optimal') is False
                or entry.get('optimal') is False
                or entry.get('suboptimal') is True
                or entry.get('should_be_skiplist') is True
                or entry.get('needs_reencoding') is True
                or entry.get('encoding_issue') is True
                or bool(entry.get('recommendation'))
            )
            if is_flagged:
                flagged.add(key)

        for prefix in ('timeline:', 'index:', 'cache:'):
            hits = [k for k in flagged if k.startswith(prefix)]
            assert len(hits) >= 3, \
                f"Need >=3 {prefix}* sets flagged, got {len(hits)}: {hits}"

    def test_leaderboard_not_flagged(self, report):
        """Small leaderboard sets should NOT be flagged as suboptimal."""
        for entry in report.get('sorted_sets', []):
            key = entry.get('key', '')
            if not key.startswith('leaderboard:'):
                continue
            is_flagged = (
                entry.get('encoding_optimal') is False
                or entry.get('optimal') is False
                or entry.get('suboptimal') is True
                or entry.get('needs_reencoding') is True
            )
            assert not is_flagged, \
                f"{key} (card ~50) should NOT be flagged as suboptimal"


# ---------------------------------------------------------------------------
# 5. Theoretical overhead
# ---------------------------------------------------------------------------

class TestTheoreticalOverhead:
    def _find_overhead(self, report):
        """Find the theoretical overhead value anywhere in the report."""
        for key, val in report.items():
            if 'theoretical' in key.lower() and 'overhead' in key.lower():
                if isinstance(val, (int, float)):
                    return val
        # Try nested
        for key, val in report.items():
            if isinstance(val, dict):
                for k2, v2 in val.items():
                    if 'overhead' in k2.lower() and isinstance(v2, (int, float)):
                        return v2
        return None

    def test_skiplist_overhead_in_range(self, report):
        overhead = self._find_overhead(report)
        assert overhead is not None, \
            "Could not locate theoretical overhead numeric value"
        assert 25 <= overhead <= 50, \
            f"Theoretical skiplist overhead {overhead} not in [25, 50]"


# ---------------------------------------------------------------------------
# 6. Recommendation
# ---------------------------------------------------------------------------

class TestRecommendation:
    def test_threshold_recommendation(self, report):
        rstr = json.dumps(report)
        has_rec = False

        if 'recommended_max_listpack_entries' in report:
            val = report['recommended_max_listpack_entries']
            assert isinstance(val, int) and val <= 128, \
                f"Recommended threshold {val} should be <= 128"
            has_rec = True

        if not has_rec:
            # Accept mention of 128 alongside listpack/threshold
            lower = rstr.lower()
            if '128' in rstr and ('listpack' in lower or 'threshold' in lower
                                   or 'max' in lower):
                has_rec = True

        if not has_rec:
            for entry in report.get('sorted_sets', []):
                if entry.get('recommendation'):
                    has_rec = True
                    break
            if report.get('recommendation') or report.get('recommendations'):
                has_rec = True

        assert has_rec, "Report must recommend a listpack threshold (<=128)"


# ---------------------------------------------------------------------------
# 7. Redis config actually fixed
# ---------------------------------------------------------------------------

class TestConfigFix:
    def test_listpack_threshold_lowered(self, redis_client):
        cfg = redis_client.config_get('zset-max-listpack-entries')
        threshold = int(cfg.get('zset-max-listpack-entries', 500))
        assert threshold <= 128, \
            f"zset-max-listpack-entries = {threshold}, should be <= 128"

    def test_medium_sets_reencoded(self, redis_client):
        """Sorted sets with > 128 entries should now be skiplist."""
        for prefix in ('timeline:', 'index:', 'cache:'):
            cursor = 0
            while True:
                cursor, keys = redis_client.scan(
                    cursor, match=f'{prefix}*', count=100)
                for key in keys:
                    if redis_client.type(key) != 'zset':
                        continue
                    card = redis_client.zcard(key)
                    if card > 128:
                        enc = redis_client.object('encoding', key)
                        assert enc == 'skiplist', \
                            f"{key} (card={card}) still {enc}, want skiplist"
                if cursor == 0:
                    break


# ---------------------------------------------------------------------------
# 8. Profiler tool fixed (runs last alphabetically)
# ---------------------------------------------------------------------------

class TestZZProfilerFixed:
    def test_profiler_runs_without_error(self, redis_client):
        path = '/app/tools/profiler.py'
        if not os.path.exists(path):
            pytest.skip("profiler.py not found")

        # Back up existing report
        bak = REPORT_PATH + '.testbak'
        if os.path.exists(REPORT_PATH):
            shutil.copy2(REPORT_PATH, bak)

        result = subprocess.run(
            [sys.executable, path],
            capture_output=True, text=True, timeout=120,
        )

        # Restore original report
        if os.path.exists(bak):
            shutil.move(bak, REPORT_PATH)

        assert result.returncode == 0, \
            f"profiler.py failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
