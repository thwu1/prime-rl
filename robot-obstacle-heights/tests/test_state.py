
import pytest
import sqlite3
import json
import os
import subprocess
import random


def simulate_query(obstacles, l, r, d):
    """Compute max achievable final height for query [l, r] with starting
    height in [0, d] using direct simulation."""
    m = d
    for i in range(l - 1, r):
        if m >= obstacles[i]:
            m = max(obstacles[i] - 1, m - obstacles[i])
    return m


class TestRobotObstacles:
    _db_loaded = False
    _suites = None
    _total = None

    @pytest.fixture(autouse=True)
    def setup(self):
        self.output_path = '/app/output.txt'

        if not TestRobotObstacles._db_loaded:
            conn = sqlite3.connect('/data/obstacles.db')
            c = conn.cursor()
            c.execute(
                'SELECT suite_id, max_height FROM test_suites ORDER BY suite_id')
            suites_raw = c.fetchall()

            suites = []
            total_offset = 0
            for suite_id, d in suites_raw:
                c.execute(
                    'SELECT height FROM obstacles '
                    'WHERE suite_id=? ORDER BY position', (suite_id,))
                obs = [h for (h,) in c.fetchall()]
                c.execute(
                    'SELECT query_id, range_start, range_end FROM queries '
                    'WHERE suite_id=? ORDER BY query_id', (suite_id,))
                qrs = c.fetchall()
                suites.append({
                    'id': suite_id,
                    'd': d,
                    'obstacles': obs,
                    'queries': qrs,
                    'offset': total_offset,
                })
                total_offset += len(qrs)

            TestRobotObstacles._suites = suites
            TestRobotObstacles._total = total_offset
            TestRobotObstacles._db_loaded = True
            conn.close()

        self.suites = TestRobotObstacles._suites
        self.total = TestRobotObstacles._total

    def _read(self):
        assert os.path.exists(self.output_path), \
            "Output file {} not found".format(self.output_path)
        with open(self.output_path) as f:
            return [int(line.strip()) for line in f if line.strip()]

    # ------------------------------------------------------------------
    # Format and structure checks
    # ------------------------------------------------------------------

    def test_output_exists(self):
        assert os.path.exists(self.output_path), \
            "Output file /app/output.txt not found"

    def test_validation_tool(self):
        result = subprocess.run(
            ['validate-output', self.output_path],
            capture_output=True, text=True)
        assert result.returncode == 0, \
            "validate-output failed: {} {}".format(
                result.stdout.strip(), result.stderr.strip())

    def test_answer_count(self):
        actual = self._read()
        assert len(actual) == self.total, \
            "Expected {} answers, got {}".format(self.total, len(actual))

    # ------------------------------------------------------------------
    # Suite 1: basic corridor (n=5, q=3, d=5)
    # ------------------------------------------------------------------

    def test_suite1_basic(self):
        actual = self._read()
        s = self.suites[0]
        for i, (qid, l, r) in enumerate(s['queries']):
            exp = simulate_query(s['obstacles'], l, r, s['d'])
            assert actual[s['offset'] + i] == exp, \
                "Suite 1, query {}: expected {}, got {}".format(
                    qid, exp, actual[s['offset'] + i])

    # ------------------------------------------------------------------
    # Suite 2: medium corridor (n=7, q=5, d=10)
    # ------------------------------------------------------------------

    def test_suite2_medium(self):
        actual = self._read()
        s = self.suites[1]
        for i, (qid, l, r) in enumerate(s['queries']):
            exp = simulate_query(s['obstacles'], l, r, s['d'])
            assert actual[s['offset'] + i] == exp, \
                "Suite 2, query {}: expected {}, got {}".format(
                    qid, exp, actual[s['offset'] + i])

    # ------------------------------------------------------------------
    # Suite 3: large d (n=10, q=8, d=10^9)
    # ------------------------------------------------------------------

    def test_suite3_large_d(self):
        actual = self._read()
        s = self.suites[2]
        for i, (qid, l, r) in enumerate(s['queries']):
            exp = simulate_query(s['obstacles'], l, r, s['d'])
            assert actual[s['offset'] + i] == exp, \
                "Suite 3, query {}: expected {}, got {}".format(
                    qid, exp, actual[s['offset'] + i])

    # ------------------------------------------------------------------
    # Suite 4: d=0 (all answers must be 0)
    # ------------------------------------------------------------------

    def test_suite4_zero_d(self):
        actual = self._read()
        s = self.suites[3]
        for i in range(len(s['queries'])):
            assert actual[s['offset'] + i] == 0, \
                "Suite 4 (d=0), answer {}: expected 0, got {}".format(
                    i + 1, actual[s['offset'] + i])

    # ------------------------------------------------------------------
    # Suite 5: stress test (n=q=100000) — sample-verify
    # ------------------------------------------------------------------

    def test_suite5_stress_sample(self):
        """Sample-verify 500 queries from the large 100K suite."""
        actual = self._read()
        s = self.suites[4]
        rng = random.Random(77331)
        n_sample = min(500, len(s['queries']))
        indices = sorted(rng.sample(range(len(s['queries'])), n_sample))

        mismatches = []
        for idx in indices:
            qid, l, r = s['queries'][idx]
            exp = simulate_query(s['obstacles'], l, r, s['d'])
            got = actual[s['offset'] + idx]
            if exp != got:
                mismatches.append((qid, l, r, exp, got))

        assert not mismatches, (
            "Suite 5: {} mismatches in {} sampled queries. ".format(
                len(mismatches), n_sample)
            + "; ".join(
                "q{} [{},{}]: exp {}, got {}".format(qid, l, r, e, g)
                for qid, l, r, e, g in mismatches[:10])
            + (" (+{} more)".format(len(mismatches) - 10)
               if len(mismatches) > 10 else ""))
