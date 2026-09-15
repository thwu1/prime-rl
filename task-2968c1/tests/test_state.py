"""
Tests for the automated bug discovery pipeline.
Verifies outcomes only: correct output files, genuine crashes,
diverse bug categories, valid rankings, and minimal test cases.

"""
import pytest
import sys
import os
import json
import subprocess

sys.path.insert(0, '/app')


@pytest.fixture(scope='module')
def pipeline_results():
    """Run the pipeline once and return parsed results."""
    result = subprocess.run(
        ['python3', '/app/pipeline.py'],
        capture_output=True, text=True, timeout=600,
        cwd='/app'
    )
    assert result.returncode == 0, \
        f"Pipeline failed (rc={result.returncode}):\nstderr: {result.stderr[:3000]}"

    paths = {
        'crashes': '/app/results/crashes.json',
        'rankings': '/app/results/rankings.json',
        'minimized': '/app/results/minimized.json',
    }

    for name, path in paths.items():
        assert os.path.exists(path), f"{name} not created at {path}"

    data = {}
    for name, path in paths.items():
        with open(path) as f:
            data[name] = json.load(f)

    return data


# ---------------------------------------------------------------------------
# Crash discovery tests
# ---------------------------------------------------------------------------

class TestCrashes:
    def test_finds_enough_failures(self, pipeline_results):
        crashes = pipeline_results['crashes']
        assert len(crashes) >= 5, \
            f"Expected >= 5 failure-inducing inputs, got {len(crashes)}"

    def test_crashes_schema(self, pipeline_results):
        """Verify crashes.json conforms to the documented schema."""
        crashes = pipeline_results['crashes']
        assert isinstance(crashes, list)
        for entry in crashes:
            assert isinstance(entry, dict)
            assert 'input' in entry and isinstance(entry['input'], str)
            assert 'target_output' in entry and isinstance(entry['target_output'], str)
            assert 'reference_output' in entry and isinstance(entry['reference_output'], str)

    def test_crashes_are_genuine(self, pipeline_results):
        """Re-run discovered inputs and confirm target != reference."""
        from target import execute as target_exec
        from reference import execute as ref_exec

        confirmed = 0
        for crash in pipeline_results['crashes'][:25]:
            inp = crash['input']
            try:
                t = str(target_exec(inp))
            except Exception as e:
                t = f"ERR:{type(e).__name__}"
            try:
                r = str(ref_exec(inp))
            except Exception as e:
                r = f"ERR:{type(e).__name__}"
            if t != r:
                confirmed += 1

        assert confirmed >= 5, f"Only {confirmed} genuine failures confirmed"

    def test_bug_diversity(self, pipeline_results):
        """Check that at least 2 distinct categories of output difference exist."""
        from target import execute as target_exec
        from reference import execute as ref_exec

        categories = set()

        for crash in pipeline_results['crashes']:
            inp = crash['input']
            try:
                t = str(target_exec(inp))
                r = str(ref_exec(inp))
            except Exception:
                continue

            if t == r:
                continue

            ts, rs = t.strip(), r.strip()

            # Boolean flip: True <-> False
            if {ts, rs} <= {'True', 'False'} and ts != rs:
                categories.add('boolean')
                continue

            # Type representation: "0"/"1" vs "True"/"False"
            if (ts in ('0', '1') and rs in ('True', 'False')) or \
               (rs in ('0', '1') and ts in ('True', 'False')):
                categories.add('type_repr')
                continue

            # Numeric difference
            try:
                tv, rv = float(ts), float(rs)
                if tv != rv:
                    categories.add('numeric')
                    continue
            except (ValueError, OverflowError):
                pass

            # String / other difference
            if ts != rs:
                categories.add('string')

        assert len(categories) >= 2, \
            f"Expected >= 2 bug categories, got {len(categories)}: {categories}"


# ---------------------------------------------------------------------------
# Suspiciousness ranking tests
# ---------------------------------------------------------------------------

class TestRankings:
    def test_not_empty(self, pipeline_results):
        assert len(pipeline_results['rankings']) > 0, \
            "Rankings should not be empty"

    def test_schema(self, pipeline_results):
        """Verify rankings.json conforms to the documented schema."""
        rankings = pipeline_results['rankings']
        assert isinstance(rankings, list)
        for entry in rankings:
            assert isinstance(entry, dict)
            assert 'location' in entry
            assert isinstance(entry['location'], list) and len(entry['location']) == 2
            assert isinstance(entry['location'][0], str)
            assert isinstance(entry['location'][1], int)
            assert 'score' in entry
            assert isinstance(entry['score'], (int, float))

    def test_scores_in_range(self, pipeline_results):
        for r in pipeline_results['rankings']:
            assert 0.0 <= r['score'] <= 1.0 + 1e-9, \
                f"Score out of range: {r['score']}"

    def test_sorted_descending(self, pipeline_results):
        scores = [r['score'] for r in pipeline_results['rankings']]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1] - 1e-9, \
                f"Rankings not sorted: {scores[i]} < {scores[i + 1]}"

    def test_includes_target_lines(self, pipeline_results):
        """Rankings should include lines from target.py."""
        target_entries = [
            r for r in pipeline_results['rankings']
            if 'target.py' in r['location'][0]
        ]
        assert len(target_entries) > 0, \
            "Rankings should include lines from target.py"

    def test_top_scores_nonzero(self, pipeline_results):
        """Top-ranked entries should have meaningful suspiciousness scores."""
        rankings = pipeline_results['rankings']
        if len(rankings) >= 3:
            assert rankings[0]['score'] > 0.1, \
                f"Top suspiciousness score too low: {rankings[0]['score']}"


# ---------------------------------------------------------------------------
# Minimized input tests
# ---------------------------------------------------------------------------

class TestMinimized:
    def test_schema(self, pipeline_results):
        """Verify minimized.json conforms to the documented schema."""
        minimized = pipeline_results['minimized']
        assert isinstance(minimized, list)
        for entry in minimized:
            assert isinstance(entry, dict)
            assert 'original' in entry and isinstance(entry['original'], str)
            assert 'minimized' in entry and isinstance(entry['minimized'], str)
            assert 'target_output' in entry and isinstance(entry['target_output'], str)
            assert 'reference_output' in entry and isinstance(entry['reference_output'], str)

    def test_has_minimized_inputs(self, pipeline_results):
        assert len(pipeline_results['minimized']) > 0, \
            "Should have at least 1 minimized input"

    def test_minimized_are_shorter(self, pipeline_results):
        for m in pipeline_results['minimized']:
            assert len(m['minimized']) <= len(m['original']), \
                f"Minimized not shorter: {len(m['minimized'])} > {len(m['original'])}"

    def test_minimized_still_trigger_bugs(self, pipeline_results):
        """Minimized inputs should still trigger the bug."""
        from target import execute as target_exec
        from reference import execute as ref_exec

        confirmed = 0
        for m in pipeline_results['minimized'][:10]:
            inp = m['minimized']
            try:
                t = str(target_exec(inp))
            except Exception as e:
                t = f"ERR:{type(e).__name__}"
            try:
                r = str(ref_exec(inp))
            except Exception as e:
                r = f"ERR:{type(e).__name__}"
            if t != r:
                confirmed += 1

        assert confirmed >= 1, "At least 1 minimized input should still trigger a bug"

    def test_minimality(self, pipeline_results):
        """At least one minimized input must be truly minimal:
        removing any single character should eliminate the failure."""
        from target import execute as target_exec
        from reference import execute as ref_exec

        def is_failure(inp):
            try:
                t = str(target_exec(inp))
            except Exception as e:
                t = f"ERR:{type(e).__name__}"
            try:
                r = str(ref_exec(inp))
            except Exception as e:
                r = f"ERR:{type(e).__name__}"
            return t != r

        found_minimal = False
        for m in pipeline_results['minimized'][:8]:
            inp = m['minimized']
            if not is_failure(inp):
                continue
            if len(inp) <= 1:
                found_minimal = True
                break
            all_removals_pass = True
            for i in range(len(inp)):
                reduced = inp[:i] + inp[i + 1:]
                if len(reduced) > 0 and is_failure(reduced):
                    all_removals_pass = False
                    break
            if all_removals_pass:
                found_minimal = True
                break

        assert found_minimal, \
            "At least one minimized input should be 1-minimal " \
            "(removing any single character eliminates the failure)"
