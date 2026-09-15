
import json
import os

import pytest

RESULTS_FILE = "/app/results.jsonl"


@pytest.fixture(scope="module")
def results():
    """Load all results from results.jsonl into a dict keyed by submission_id."""
    assert os.path.exists(RESULTS_FILE), f"{RESULTS_FILE} does not exist"
    entries = {}
    with open(RESULTS_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            entries[entry["submission_id"]] = entry
    return entries


class TestFileStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_FILE)

    def test_results_count(self, results):
        assert len(results) == 9, f"Expected 9 submissions, got {len(results)}"

    def test_results_sorted(self):
        with open(RESULTS_FILE) as f:
            lines = [l.strip() for l in f if l.strip()]
        ids = [json.loads(l)["submission_id"] for l in lines]
        assert ids == sorted(ids), "Results must be sorted by submission_id"

    def test_required_fields(self, results):
        required = {"submission_id", "problem_id", "verdict", "score", "testcase_results"}
        for sid, entry in results.items():
            missing = required - set(entry.keys())
            assert not missing, f"{sid} missing fields: {missing}"


class TestVerdicts:
    def test_add_correct_verdict(self, results):
        r = results["add/correct.cpp"]
        assert r["verdict"] == "AC"
        assert r["problem_id"] == "add"

    def test_add_wrong_verdict(self, results):
        r = results["add/wrong.py"]
        assert r["verdict"] == "WA"

    def test_add_broken_verdict(self, results):
        r = results["add/broken.cpp"]
        assert r["verdict"] == "CE"

    def test_add_slow_verdict(self, results):
        r = results["add/slow.py"]
        assert r["verdict"] == "TLE"

    def test_area_correct_verdict(self, results):
        r = results["area/correct.cpp"]
        assert r["verdict"] == "AC"
        assert r["problem_id"] == "area"

    def test_area_wrong_verdict(self, results):
        r = results["area/wrong.py"]
        assert r["verdict"] == "WA"

    def test_reorder_correct_verdict(self, results):
        r = results["reorder/correct.cpp"]
        assert r["verdict"] == "AC"

    def test_reorder_crash_verdict(self, results):
        r = results["reorder/crash.py"]
        assert r["verdict"] == "RE"

    def test_divisors_partial_verdict(self, results):
        r = results["divisors/partial.py"]
        assert r["verdict"] == "WA"


class TestScores:
    def test_add_correct_score(self, results):
        assert results["add/correct.cpp"]["score"] == pytest.approx(1.0)

    def test_add_wrong_score(self, results):
        assert results["add/wrong.py"]["score"] == pytest.approx(0.0)

    def test_add_broken_score(self, results):
        assert results["add/broken.cpp"]["score"] == pytest.approx(0.0)

    def test_add_slow_score(self, results):
        assert results["add/slow.py"]["score"] == pytest.approx(0.0)

    def test_area_correct_score(self, results):
        assert results["area/correct.cpp"]["score"] == pytest.approx(1.0)

    def test_area_wrong_score(self, results):
        assert results["area/wrong.py"]["score"] == pytest.approx(0.0)

    def test_divisors_partial_score(self, results):
        assert results["divisors/partial.py"]["score"] == pytest.approx(0.5)

    def test_reorder_correct_score(self, results):
        assert results["reorder/correct.cpp"]["score"] == pytest.approx(1.0)

    def test_reorder_crash_score(self, results):
        assert results["reorder/crash.py"]["score"] == pytest.approx(0.0)


class TestTestcaseResults:
    def test_add_correct_testcases(self, results):
        r = results["add/correct.cpp"]
        assert len(r["testcase_results"]) == 3
        for tc in r["testcase_results"]:
            assert tc["verdict"] == "AC"
            assert isinstance(tc["time_ms"], int)
            assert tc["time_ms"] >= 0
            assert isinstance(tc["memory_kb"], int)
            assert tc["memory_kb"] > 0

    def test_add_wrong_testcases(self, results):
        r = results["add/wrong.py"]
        assert len(r["testcase_results"]) == 3
        verdicts = {tc["testcase"]: tc["verdict"] for tc in r["testcase_results"]}
        assert verdicts[1] == "WA"
        assert verdicts[2] == "AC"
        assert verdicts[3] == "WA"

    def test_add_broken_testcases(self, results):
        r = results["add/broken.cpp"]
        assert r["testcase_results"] == []

    def test_add_slow_testcases(self, results):
        r = results["add/slow.py"]
        assert len(r["testcase_results"]) == 3
        for tc in r["testcase_results"]:
            assert tc["verdict"] == "TLE"
            assert tc["time_ms"] == -1
            assert tc["memory_kb"] == -1

    def test_area_correct_testcases(self, results):
        """Area uses a floating-point testlib bridged checker; verify AC on both test cases."""
        r = results["area/correct.cpp"]
        assert len(r["testcase_results"]) == 2
        for tc in r["testcase_results"]:
            assert tc["verdict"] == "AC"
            assert isinstance(tc["memory_kb"], int)
            assert tc["memory_kb"] > 0

    def test_area_wrong_testcases(self, results):
        """Wrong submission computes perimeter instead of area; both test cases WA."""
        r = results["area/wrong.py"]
        assert len(r["testcase_results"]) == 2
        for tc in r["testcase_results"]:
            assert tc["verdict"] == "WA"

    def test_divisors_partial_testcases(self, results):
        r = results["divisors/partial.py"]
        assert len(r["testcase_results"]) == 4
        verdicts = {tc["testcase"]: tc["verdict"] for tc in r["testcase_results"]}
        assert verdicts[1] == "AC"
        assert verdicts[2] == "AC"
        assert verdicts[3] == "WA"
        assert verdicts[4] == "WA"

    def test_reorder_correct_testcases(self, results):
        """Reorder uses a testlib bridged checker; verify AC on both test cases."""
        r = results["reorder/correct.cpp"]
        assert len(r["testcase_results"]) == 2
        for tc in r["testcase_results"]:
            assert tc["verdict"] == "AC"
            assert isinstance(tc["memory_kb"], int)
            assert tc["memory_kb"] > 0

    def test_reorder_crash_testcases(self, results):
        r = results["reorder/crash.py"]
        assert len(r["testcase_results"]) == 2
        for tc in r["testcase_results"]:
            assert tc["verdict"] == "RE"

    def test_testcase_structure(self, results):
        """All testcase_results entries have correct field types including memory_kb."""
        for sid, entry in results.items():
            for tc in entry["testcase_results"]:
                assert "testcase" in tc, f"{sid}: missing testcase field"
                assert "verdict" in tc, f"{sid}: missing verdict field"
                assert "time_ms" in tc, f"{sid}: missing time_ms field"
                assert "memory_kb" in tc, f"{sid}: missing memory_kb field"
                assert isinstance(tc["testcase"], int)
                assert tc["verdict"] in ("AC", "WA", "RE", "TLE")
                assert isinstance(tc["time_ms"], int)
                assert isinstance(tc["memory_kb"], int)
                if tc["verdict"] == "TLE":
                    assert tc["time_ms"] == -1
                    assert tc["memory_kb"] == -1
                else:
                    assert tc["time_ms"] >= 0
                    assert tc["memory_kb"] > 0


class TestResourceEnforcement:
    """Verify that resource management is working correctly."""

    def test_memory_reported_for_ac(self, results):
        """AC submissions must report positive memory_kb."""
        r = results["add/correct.cpp"]
        for tc in r["testcase_results"]:
            assert tc["memory_kb"] > 0, "memory_kb should be positive for AC"
            assert tc["memory_kb"] < 262144, "memory_kb should be under the 256MB limit"

    def test_memory_reported_for_python_ac(self, results):
        """Python AC test cases should report positive memory."""
        r = results["divisors/partial.py"]
        for tc in r["testcase_results"]:
            if tc["verdict"] == "AC":
                assert tc["memory_kb"] > 0

    def test_tle_resource_fields(self, results):
        """TLE submissions should have -1 for both time_ms and memory_kb."""
        r = results["add/slow.py"]
        for tc in r["testcase_results"]:
            assert tc["time_ms"] == -1
            assert tc["memory_kb"] == -1

    def test_re_has_valid_memory(self, results):
        """RE submissions should still report non-negative memory_kb."""
        r = results["reorder/crash.py"]
        for tc in r["testcase_results"]:
            assert tc["memory_kb"] >= 0


class TestBridgedCheckers:
    """Verify that testlib-based bridged checkers work for different comparison types."""

    def test_derangement_checker_accepts(self, results):
        """Reorder checker validates permutation and derangement properties."""
        r = results["reorder/correct.cpp"]
        assert r["verdict"] == "AC"
        assert r["score"] == pytest.approx(1.0)

    def test_floating_point_checker_accepts(self, results):
        """Area checker accepts output within epsilon tolerance."""
        r = results["area/correct.cpp"]
        assert r["verdict"] == "AC"
        assert r["score"] == pytest.approx(1.0)
        for tc in r["testcase_results"]:
            assert tc["verdict"] == "AC"
            assert tc["time_ms"] >= 0

    def test_floating_point_checker_rejects(self, results):
        """Area checker rejects output outside epsilon tolerance."""
        r = results["area/wrong.py"]
        assert r["verdict"] == "WA"
        assert r["score"] == pytest.approx(0.0)
        for tc in r["testcase_results"]:
            assert tc["verdict"] == "WA"
