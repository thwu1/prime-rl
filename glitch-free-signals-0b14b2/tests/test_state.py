
import json
import os
import pytest

RESULTS_FILE = "/tmp/test_results.json"
STDERR_FILE = "/tmp/test_stderr.txt"

def load_results():
    if not os.path.exists(RESULTS_FILE):
        pytest.fail(f"Results file not found: {RESULTS_FILE}")
    with open(RESULTS_FILE) as f:
        content = f.read().strip()
    if not content:
        stderr = ""
        if os.path.exists(STDERR_FILE):
            with open(STDERR_FILE) as f:
                stderr = f.read().strip()
        pytest.fail(f"Empty results file. stderr: {stderr}")
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        stderr = ""
        if os.path.exists(STDERR_FILE):
            with open(STDERR_FILE) as f:
                stderr = f.read().strip()
        pytest.fail(f"Failed to parse results JSON: {e}\nContent: {content[:500]}\nstderr: {stderr[:500]}")


RESULTS = None

def get_results():
    global RESULTS
    if RESULTS is None:
        RESULTS = load_results()
    return RESULTS


def find_test(name):
    results = get_results()
    for r in results:
        if r["name"] == name:
            return r
    pytest.fail(f"Test '{name}' not found in results. Available: {[r['name'] for r in results]}")


class TestBasicReactivity:
    def test_basic_signal(self):
        r = find_test("basic_signal")
        assert r["pass"], f"basic_signal failed: {r.get('detail', '')}"

    def test_basic_computed(self):
        r = find_test("basic_computed")
        assert r["pass"], f"basic_computed failed: {r.get('detail', '')}"


class TestGlitchFreedom:
    def test_diamond_glitch_free(self):
        r = find_test("diamond_glitch_free")
        assert r["pass"], f"diamond_glitch_free failed: {r.get('detail', '')}"

    def test_deep_diamond(self):
        r = find_test("deep_diamond")
        assert r["pass"], f"deep_diamond failed: {r.get('detail', '')}"


class TestDynamicDependencies:
    def test_dynamic_deps_conditional(self):
        r = find_test("dynamic_deps_conditional")
        assert r["pass"], f"dynamic_deps_conditional failed: {r.get('detail', '')}"


class TestEqualityCutoff:
    def test_computed_equality_cutoff(self):
        r = find_test("computed_equality_cutoff")
        assert r["pass"], f"computed_equality_cutoff failed: {r.get('detail', '')}"

    def test_computed_custom_equality_cutoff(self):
        r = find_test("computed_custom_equality_cutoff")
        assert r["pass"], f"computed_custom_equality_cutoff failed: {r.get('detail', '')}"


class TestSafetyGuards:
    def test_cycle_detection(self):
        r = find_test("cycle_detection")
        assert r["pass"], f"cycle_detection failed: {r.get('detail', '')}"

    def test_write_guard_computed(self):
        r = find_test("write_guard_computed")
        assert r["pass"], f"write_guard_computed failed: {r.get('detail', '')}"

    def test_write_in_effect_allowed(self):
        r = find_test("write_in_effect_allowed")
        assert r["pass"], f"write_in_effect_allowed failed: {r.get('detail', '')}"


class TestEffects:
    def test_effect_diamond_dedup(self):
        r = find_test("effect_diamond_dedup")
        assert r["pass"], f"effect_diamond_dedup failed: {r.get('detail', '')}"

    def test_effect_overlapping_deps(self):
        r = find_test("effect_overlapping_deps")
        assert r["pass"], f"effect_overlapping_deps failed: {r.get('detail', '')}"

    def test_effect_cleanup(self):
        r = find_test("effect_cleanup")
        assert r["pass"], f"effect_cleanup failed: {r.get('detail', '')}"

    def test_effect_destroy(self):
        r = find_test("effect_destroy")
        assert r["pass"], f"effect_destroy failed: {r.get('detail', '')}"


class TestUntracked:
    def test_untracked_reads(self):
        r = find_test("untracked_reads")
        assert r["pass"], f"untracked_reads failed: {r.get('detail', '')}"


class TestSignalEquality:
    def test_signal_equality_no_notification(self):
        r = find_test("signal_equality_no_notification")
        assert r["pass"], f"signal_equality_no_notification failed: {r.get('detail', '')}"


class TestIntegration:
    def test_complex_reactive_graph(self):
        r = find_test("complex_reactive_graph")
        assert r["pass"], f"complex_reactive_graph failed: {r.get('detail', '')}"
