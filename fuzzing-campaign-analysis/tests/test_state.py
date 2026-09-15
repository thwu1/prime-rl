"""Tests for Magma fuzzing campaign analysis pipeline.

Verifies correct parsing, statistical computation, edge case handling,
and output format compliance.
"""

import json
import os

import pytest

RESULTS_PATH = "/app/results.json"
STATISTICS_PATH = "/app/statistics.json"
REPORT_PATH = "/app/report.txt"
TIMEOUT = 300  # 5m campaign timeout in seconds


@pytest.fixture
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture
def statistics():
    with open(STATISTICS_PATH) as f:
        return json.load(f)


# ──────────────────────────────────────────────
# results.json existence and structure
# ──────────────────────────────────────────────

class TestResultsExistence:
    def test_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found at /app/results.json"

    def test_valid_json(self):
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)


class TestResultsStructure:
    def test_has_all_fuzzers(self, results):
        assert "afl" in results
        assert "aflplusplus" in results
        assert "honggfuzz" in results

    def test_has_both_targets(self, results):
        for fuzzer in ["afl", "aflplusplus", "honggfuzz"]:
            assert "libpng" in results[fuzzer], f"{fuzzer} missing libpng"
            assert "libtiff" in results[fuzzer], f"{fuzzer} missing libtiff"

    def test_has_programs(self, results):
        for fuzzer in ["afl", "aflplusplus", "honggfuzz"]:
            assert "libpng_read_fuzzer" in results[fuzzer]["libpng"]
            assert "tiffcp" in results[fuzzer]["libtiff"]

    def test_run_ids_are_strings(self, results):
        runs = results["afl"]["libpng"]["libpng_read_fuzzer"]
        for run_id in runs:
            assert isinstance(run_id, str), f"run_id {run_id} should be a string"

    def test_run_has_reached_and_triggered(self, results):
        run0 = results["afl"]["libpng"]["libpng_read_fuzzer"]["0"]
        assert "reached" in run0
        assert "triggered" in run0


# ──────────────────────────────────────────────
# Exact time-to-reach / time-to-trigger values
# ──────────────────────────────────────────────

class TestSpecificValues:
    def test_afl_libpng_run0_reached(self, results):
        run = results["afl"]["libpng"]["libpng_read_fuzzer"]["0"]
        assert run["reached"]["PNG001"] == 25
        assert run["reached"]["PNG002"] == 40
        assert run["reached"]["PNG003"] == 75
        assert run["reached"]["PNG005"] == 15

    def test_afl_libpng_run0_triggered(self, results):
        run = results["afl"]["libpng"]["libpng_read_fuzzer"]["0"]
        assert run["triggered"]["PNG001"] == 60
        assert run["triggered"]["PNG003"] == 120
        assert run["triggered"]["PNG005"] == 35

    def test_afl_libpng_run0_png004_absent(self, results):
        """PNG004 was never reached by AFL — must not appear."""
        run = results["afl"]["libpng"]["libpng_read_fuzzer"]["0"]
        assert "PNG004" not in run["reached"]
        assert "PNG004" not in run["triggered"]

    def test_afl_libpng_run0_png002_not_triggered(self, results):
        """PNG002 reached but not triggered in run 0."""
        run = results["afl"]["libpng"]["libpng_read_fuzzer"]["0"]
        assert "PNG002" in run["reached"]
        assert "PNG002" not in run["triggered"]

    def test_afl_libpng_run2_png002_triggered(self, results):
        """PNG002 triggered only in AFL run 2."""
        run = results["afl"]["libpng"]["libpng_read_fuzzer"]["2"]
        assert run["triggered"]["PNG002"] == 150

    def test_aflpp_libtiff_run0_values(self, results):
        run = results["aflplusplus"]["libtiff"]["tiffcp"]["0"]
        assert run["reached"]["TIF001"] == 5
        assert run["triggered"]["TIF001"] == 10
        assert run["reached"]["TIF003"] == 100
        assert run["triggered"]["TIF003"] == 200

    def test_honggfuzz_libpng_run1_values(self, results):
        run = results["honggfuzz"]["libpng"]["libpng_read_fuzzer"]["1"]
        assert run["reached"]["PNG001"] == 40
        assert run["triggered"]["PNG001"] == 90
        assert run["triggered"]["PNG005"] == 55

    def test_aflpp_libpng_run1_png001_trigger(self, results):
        run = results["aflplusplus"]["libpng"]["libpng_read_fuzzer"]["1"]
        assert run["triggered"]["PNG001"] == 65

    def test_afl_libtiff_run2_values(self, results):
        run = results["afl"]["libtiff"]["tiffcp"]["2"]
        assert run["reached"]["TIF001"] == 10
        assert run["triggered"]["TIF001"] == 20
        assert run["triggered"]["TIF002"] == 75
        assert "TIF003" not in run["triggered"]
        assert run["reached"]["TIF004"] == 25
        assert "TIF004" not in run["triggered"]

    def test_honggfuzz_libtiff_run2_tif003_reached_not_triggered(self, results):
        """honggfuzz reaches TIF003 in run 2 at 150s but never triggers it."""
        run = results["honggfuzz"]["libtiff"]["tiffcp"]["2"]
        assert run["reached"]["TIF003"] == 150
        assert "TIF003" not in run["triggered"]


# ──────────────────────────────────────────────
# Edge case handling
# ──────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_csv_handling(self, results):
        """afl/libpng/libpng_read_fuzzer/3 had empty CSV — excluded or empty."""
        runs = results["afl"]["libpng"]["libpng_read_fuzzer"]
        if "3" in runs:
            assert runs["3"]["reached"] == {}
            assert runs["3"]["triggered"] == {}

    def test_truncated_csv_included(self, results):
        """honggfuzz/libpng/libpng_read_fuzzer/3 had valid but short CSV."""
        runs = results["honggfuzz"]["libpng"]["libpng_read_fuzzer"]
        if "3" in runs:
            # Short campaign with all-zero counters: no bugs found
            assert runs["3"]["reached"] == {}
            assert runs["3"]["triggered"] == {}

    def test_libtiff_clean_3reps(self, results):
        """All libtiff campaigns have exactly 3 clean repetitions."""
        for fuzzer in ["afl", "aflplusplus", "honggfuzz"]:
            runs = results[fuzzer]["libtiff"]["tiffcp"]
            assert len(runs) == 3, (
                f"{fuzzer}/libtiff/tiffcp has {len(runs)} runs, expected 3"
            )


# ──────────────────────────────────────────────
# statistics.json existence and structure
# ──────────────────────────────────────────────

class TestStatisticsStructure:
    def test_file_exists(self):
        assert os.path.exists(STATISTICS_PATH)

    def test_valid_json(self):
        with open(STATISTICS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_pairwise_and_coverage(self, statistics):
        assert "pairwise" in statistics
        assert "coverage" in statistics

    def test_pairwise_keys_alphabetical(self, statistics):
        for key in statistics["pairwise"]:
            parts = key.split("_vs_")
            assert len(parts) == 2, f"Malformed pairwise key: {key}"
            assert parts[0] < parts[1], f"Key not in alphabetical order: {key}"

    def test_all_fuzzer_pairs_present(self, statistics):
        expected = {"afl_vs_aflplusplus", "afl_vs_honggfuzz", "aflplusplus_vs_honggfuzz"}
        actual = set(statistics["pairwise"].keys())
        assert expected == actual


# ──────────────────────────────────────────────
# A12 effect size values
# ──────────────────────────────────────────────

class TestA12Values:
    def test_afl_vs_aflpp_png001(self, statistics):
        """AFL triggers [60,70,55] vs AFL++ [35,65,30] → A12 = 7/9 ≈ 0.778."""
        entry = statistics["pairwise"]["afl_vs_aflplusplus"]
        bug = entry["libpng/libpng_read_fuzzer"]["PNG001"]
        assert abs(bug["a12"] - 7.0 / 9.0) < 0.01

    def test_afl_vs_aflpp_png005(self, statistics):
        """AFL [35,40,30] vs AFL++ [20,25,15] → A12 = 1.0 (strict dominance)."""
        entry = statistics["pairwise"]["afl_vs_aflplusplus"]
        bug = entry["libpng/libpng_read_fuzzer"]["PNG005"]
        assert abs(bug["a12"] - 1.0) < 0.01

    def test_aflpp_vs_honggfuzz_tif001(self, statistics):
        """AFL++ [10,15,10] vs honggfuzz [20,40,15] → A12 = 0.5/9 ≈ 0.056."""
        entry = statistics["pairwise"]["aflplusplus_vs_honggfuzz"]
        bug = entry["libtiff/tiffcp"]["TIF001"]
        assert abs(bug["a12"] - 0.5 / 9.0) < 0.01

    def test_afl_vs_honggfuzz_tif001(self, statistics):
        """AFL [25,30,20] vs honggfuzz [20,40,15] → A12 = 5.5/9 ≈ 0.611."""
        entry = statistics["pairwise"]["afl_vs_honggfuzz"]
        bug = entry["libtiff/tiffcp"]["TIF001"]
        assert abs(bug["a12"] - 5.5 / 9.0) < 0.01

    def test_identical_timeout_a12(self, statistics):
        """PNG004 never triggered by afl or honggfuzz → all timeouts → A12 ≈ 0.5."""
        entry = statistics["pairwise"]["afl_vs_honggfuzz"]
        bug = entry["libpng/libpng_read_fuzzer"]["PNG004"]
        assert abs(bug["a12"] - 0.5) < 0.01

    def test_a12_range(self, statistics):
        """All A12 values must be in [0, 1]."""
        for pair_key, targets in statistics["pairwise"].items():
            for tp_key, bugs in targets.items():
                for bug_id, entry in bugs.items():
                    assert 0.0 <= entry["a12"] <= 1.0, (
                        f"A12 out of range for {pair_key}/{tp_key}/{bug_id}: {entry['a12']}"
                    )


# ──────────────────────────────────────────────
# A12 magnitude classification
# ──────────────────────────────────────────────

class TestA12Magnitude:
    def test_has_magnitude_field(self, statistics):
        entry = statistics["pairwise"]["afl_vs_aflplusplus"]
        bug = entry["libpng/libpng_read_fuzzer"]["PNG001"]
        assert "a12_magnitude" in bug

    def test_large_upper(self, statistics):
        """A12 = 7/9 ≈ 0.778 > 0.71 → large."""
        entry = statistics["pairwise"]["afl_vs_aflplusplus"]
        bug = entry["libpng/libpng_read_fuzzer"]["PNG001"]
        assert bug["a12_magnitude"] == "large"

    def test_large_strict_dominance(self, statistics):
        """A12 = 1.0 → large."""
        entry = statistics["pairwise"]["afl_vs_aflplusplus"]
        bug = entry["libpng/libpng_read_fuzzer"]["PNG005"]
        assert bug["a12_magnitude"] == "large"

    def test_negligible(self, statistics):
        """A12 = 0.5 → negligible."""
        entry = statistics["pairwise"]["afl_vs_honggfuzz"]
        bug = entry["libpng/libpng_read_fuzzer"]["PNG004"]
        assert bug["a12_magnitude"] == "negligible"

    def test_small_effect(self, statistics):
        """A12 = 5.5/9 ≈ 0.611, which is in (0.56, 0.64] → small."""
        entry = statistics["pairwise"]["afl_vs_honggfuzz"]
        bug = entry["libtiff/tiffcp"]["TIF001"]
        assert bug["a12_magnitude"] == "small"

    def test_large_lower(self, statistics):
        """A12 = 0.5/9 ≈ 0.056 < 0.29 → large."""
        entry = statistics["pairwise"]["aflplusplus_vs_honggfuzz"]
        bug = entry["libtiff/tiffcp"]["TIF001"]
        assert bug["a12_magnitude"] == "large"


# ──────────────────────────────────────────────
# P-values
# ──────────────────────────────────────────────

class TestPValues:
    def test_p_values_present(self, statistics):
        for pair_key, targets in statistics["pairwise"].items():
            for tp_key, bugs in targets.items():
                for bug_id, entry in bugs.items():
                    assert "p_value" in entry, (
                        f"Missing p_value for {pair_key}/{tp_key}/{bug_id}"
                    )

    def test_p_value_range(self, statistics):
        for pair_key, targets in statistics["pairwise"].items():
            for tp_key, bugs in targets.items():
                for bug_id, entry in bugs.items():
                    p = entry["p_value"]
                    if p is not None:
                        assert 0.0 <= p <= 1.0, (
                            f"p_value out of range for {pair_key}/{tp_key}/{bug_id}: {p}"
                        )


# ──────────────────────────────────────────────
# Coverage
# ──────────────────────────────────────────────

class TestCoverage:
    def test_aflpp_reaches_all_bugs(self, statistics):
        """AFL++ reaches all 10 bugs across both targets."""
        cov = statistics["coverage"]["aflplusplus"]
        expected = {
            "PNG001", "PNG002", "PNG003", "PNG004", "PNG005",
            "TIF001", "TIF002", "TIF003", "TIF004", "TIF005",
        }
        assert set(cov["unique_reached"]) == expected

    def test_afl_does_not_reach_png004(self, statistics):
        cov = statistics["coverage"]["afl"]
        assert "PNG004" not in cov["unique_reached"]

    def test_afl_does_not_trigger_tif003(self, statistics):
        cov = statistics["coverage"]["afl"]
        assert "TIF003" not in cov["unique_triggered"]

    def test_aflpp_triggers_tif003(self, statistics):
        cov = statistics["coverage"]["aflplusplus"]
        assert "TIF003" in cov["unique_triggered"]

    def test_afl_triggers_png002(self, statistics):
        """AFL triggers PNG002 in rep 2 of libpng."""
        cov = statistics["coverage"]["afl"]
        assert "PNG002" in cov["unique_triggered"]

    def test_honggfuzz_reaches_tif003(self, statistics):
        """honggfuzz reaches TIF003 in libtiff rep 2."""
        cov = statistics["coverage"]["honggfuzz"]
        assert "TIF003" in cov["unique_reached"]

    def test_honggfuzz_does_not_trigger_tif003(self, statistics):
        """honggfuzz never triggers TIF003."""
        cov = statistics["coverage"]["honggfuzz"]
        assert "TIF003" not in cov["unique_triggered"]

    def test_coverage_lists_sorted(self, statistics):
        for fuzzer in ["afl", "aflplusplus", "honggfuzz"]:
            cov = statistics["coverage"][fuzzer]
            assert cov["unique_reached"] == sorted(cov["unique_reached"])
            assert cov["unique_triggered"] == sorted(cov["unique_triggered"])


# ──────────────────────────────────────────────
# report.txt
# ──────────────────────────────────────────────

class TestReport:
    def test_file_exists(self):
        assert os.path.exists(REPORT_PATH), "report.txt not found"

    def test_nonempty(self):
        content = open(REPORT_PATH).read()
        assert len(content) > 200, "Report is too short"

    def test_mentions_fuzzers(self):
        content = open(REPORT_PATH).read().lower()
        assert "afl" in content
        assert "aflplusplus" in content or "afl++" in content
        assert "honggfuzz" in content

    def test_mentions_campaigns(self):
        content = open(REPORT_PATH).read().lower()
        assert "campaign" in content
