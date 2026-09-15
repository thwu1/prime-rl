"""
Tests for NIST SP 800-22 Rev. 1a Statistical Test Suite implementation.
Verifies structure, p-value accuracy, source classification, and assessment consistency.
"""

import json
import math
import os

import pytest
from scipy.special import erfc, gammaincc

RESULTS_PATH = "/app/results.json"
CONFIG_PATH = "/srv/nist/config.json"
DATA_DIR = "/srv/nist/data"

REQUIRED_TESTS = [
    "frequency", "block_frequency", "runs", "longest_run",
    "dft", "cumulative_sums", "approximate_entropy"
]


@pytest.fixture(scope="session")
def config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


def load_bitstreams(filepath, stream_length, num_streams):
    """Read a binary file and split into bitstreams (MSB first)."""
    with open(filepath, 'rb') as f:
        raw = f.read()
    all_bits = []
    for byte_val in raw:
        for bit_pos in range(7, -1, -1):
            all_bits.append((byte_val >> bit_pos) & 1)
    streams = []
    for i in range(num_streams):
        start = i * stream_length
        end = start + stream_length
        streams.append(all_bits[start:end])
    return streams


def reference_frequency_pvalue(bits):
    """Independently compute the Frequency (Monobit) test p-value."""
    n = len(bits)
    s = sum(2 * b - 1 for b in bits)
    s_obs = abs(s) / math.sqrt(n)
    return float(erfc(s_obs / math.sqrt(2)))


# ============================================================
# Structure Tests
# ============================================================

class TestStructure:
    """Verify output file structure and completeness."""

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found"

    def test_results_valid_json(self, results):
        assert isinstance(results, dict)

    def test_all_sources_present(self, results, config):
        for source in config["sources"]:
            assert source in results, f"Source '{source}' missing from results"

    def test_all_tests_present_per_source(self, results, config):
        for source in config["sources"]:
            for test_name in REQUIRED_TESTS:
                assert test_name in results[source], \
                    f"Test '{test_name}' missing for source '{source}'"

    def test_required_fields_present(self, results, config):
        required_fields = [
            "p_values", "proportion_passing", "proportion_result",
            "uniformity_pvalue", "uniformity_result"
        ]
        for source in config["sources"]:
            for test_name in REQUIRED_TESTS:
                entry = results[source][test_name]
                for field in required_fields:
                    assert field in entry, \
                        f"Field '{field}' missing in {source}/{test_name}"

    def test_p_values_correct_length(self, results, config):
        num_streams = config["num_streams"]
        for source in config["sources"]:
            for test_name in REQUIRED_TESTS:
                pvals = results[source][test_name]["p_values"]
                assert isinstance(pvals, list), \
                    f"p_values should be a list for {source}/{test_name}"
                assert len(pvals) == num_streams, \
                    f"Expected {num_streams} p-values for {source}/{test_name}, got {len(pvals)}"

    def test_p_values_in_valid_range(self, results, config):
        for source in config["sources"]:
            for test_name in REQUIRED_TESTS:
                for i, p in enumerate(results[source][test_name]["p_values"]):
                    assert isinstance(p, (int, float)), \
                        f"P-value must be numeric: {source}/{test_name}[{i}]"
                    assert 0.0 <= p <= 1.0, \
                        f"P-value {p} out of [0,1] at {source}/{test_name}[{i}]"

    def test_proportion_in_valid_range(self, results, config):
        for source in config["sources"]:
            for test_name in REQUIRED_TESTS:
                prop = results[source][test_name]["proportion_passing"]
                assert 0.0 <= prop <= 1.0, \
                    f"Proportion {prop} out of [0,1] for {source}/{test_name}"

    def test_result_labels_valid(self, results, config):
        for source in config["sources"]:
            for test_name in REQUIRED_TESTS:
                entry = results[source][test_name]
                assert entry["proportion_result"] in ("pass", "fail"), \
                    f"Invalid proportion_result for {source}/{test_name}"
                assert entry["uniformity_result"] in ("pass", "fail"), \
                    f"Invalid uniformity_result for {source}/{test_name}"

    def test_summary_structure(self, results, config):
        assert "summary" in results, "'summary' key missing from results"
        for source in config["sources"]:
            assert source in results["summary"], \
                f"Source '{source}' missing from summary"
            s = results["summary"][source]
            assert "overall" in s, f"'overall' missing in summary for {source}"
            assert "failing_tests" in s, f"'failing_tests' missing in summary for {source}"
            assert s["overall"] in ("pass", "fail"), \
                f"Invalid overall value for {source}"
            assert isinstance(s["failing_tests"], list), \
                f"failing_tests should be a list for {source}"


# ============================================================
# Source Classification Tests
# ============================================================

class TestSourceClassification:
    """Verify correct identification of generator quality."""

    def test_biased_source_fails_overall(self, results):
        assert results["summary"]["biased.bin"]["overall"] == "fail", \
            "Biased source (Bernoulli p=0.47) must fail overall"

    def test_biased_frequency_fails(self, results):
        failing = results["summary"]["biased.bin"]["failing_tests"]
        assert "frequency" in failing, \
            "Biased source must fail the frequency test"

    def test_biased_block_frequency_fails(self, results):
        failing = results["summary"]["biased.bin"]["failing_tests"]
        assert "block_frequency" in failing, \
            "Biased source must fail the block_frequency test"

    def test_biased_runs_fails(self, results):
        failing = results["summary"]["biased.bin"]["failing_tests"]
        assert "runs" in failing, \
            "Biased source must fail the runs test (prerequisite |pi-0.5| >= tau)"

    def test_biased_cumulative_sums_fails(self, results):
        failing = results["summary"]["biased.bin"]["failing_tests"]
        assert "cumulative_sums" in failing, \
            "Biased source must fail the cumulative_sums test"

    def test_periodic_source_fails_overall(self, results):
        assert results["summary"]["periodic.bin"]["overall"] == "fail", \
            "Periodic source (period=5000) must fail overall"

    def test_periodic_dft_fails(self, results):
        failing = results["summary"]["periodic.bin"]["failing_tests"]
        assert "dft" in failing, \
            "Periodic source must fail the DFT (spectral) test"

    def test_periodic_approximate_entropy_fails(self, results):
        failing = results["summary"]["periodic.bin"]["failing_tests"]
        assert "approximate_entropy" in failing, \
            "Periodic source must fail the approximate_entropy test"

    def test_csprng_frequency_passes(self, results):
        """CSPRNG should at minimum pass the frequency test."""
        entry = results["csprng.bin"]["frequency"]
        assert entry["proportion_result"] == "pass", \
            "CSPRNG frequency proportion should pass"

    def test_csprng_approximate_entropy_passes(self, results):
        """CSPRNG should pass the approximate_entropy test."""
        entry = results["csprng.bin"]["approximate_entropy"]
        assert entry["proportion_result"] == "pass", \
            "CSPRNG approximate_entropy proportion should pass"


# ============================================================
# P-Value Accuracy Tests
# ============================================================

class TestPValueAccuracy:
    """Verify p-value computations are mathematically correct."""

    def test_biased_frequency_pvalues_very_small(self, results):
        """Biased(0.47) source on 100K bits gives frequency p-values near zero."""
        pvals = results["biased.bin"]["frequency"]["p_values"]
        for i, p in enumerate(pvals):
            assert p < 0.001, \
                f"Biased frequency p_value[{i}] = {p}, expected < 0.001"

    def test_csprng_frequency_pvalues_reasonable(self, results):
        """CSPRNG should produce mostly large frequency p-values."""
        pvals = results["csprng.bin"]["frequency"]["p_values"]
        above = sum(1 for p in pvals if p > 0.01)
        assert above >= len(pvals) * 0.7, \
            f"Only {above}/{len(pvals)} CSPRNG frequency p-values > 0.01; expected >= 70%"

    def test_periodic_dft_pvalues_very_small(self, results):
        """Periodic source (period 5000, 20 reps) gives DFT p-values near zero."""
        pvals = results["periodic.bin"]["dft"]["p_values"]
        for i, p in enumerate(pvals):
            assert p < 0.01, \
                f"Periodic DFT p_value[{i}] = {p}, expected < 0.01"

    def test_frequency_pvalues_match_reference(self, results, config):
        """Compare reported frequency p-values against independently computed values."""
        stream_length = config["stream_length_bits"]
        num_streams = config["num_streams"]

        for source in config["sources"]:
            filepath = os.path.join(DATA_DIR, source)
            streams = load_bitstreams(filepath, stream_length, num_streams)
            reported = results[source]["frequency"]["p_values"]

            for i, stream in enumerate(streams):
                ref = reference_frequency_pvalue(stream)
                assert abs(reported[i] - ref) < 1e-6, \
                    f"Frequency p-value mismatch for {source}[{i}]: " \
                    f"reported={reported[i]:.10f}, reference={ref:.10f}"

    def test_biased_runs_pvalues_zero(self, results):
        """Biased data fails the runs prerequisite, so p-values should be 0."""
        pvals = results["biased.bin"]["runs"]["p_values"]
        for i, p in enumerate(pvals):
            assert p < 1e-6, \
                f"Biased runs p_value[{i}] = {p}, expected 0.0 (prerequisite failure)"

    def test_periodic_approximate_entropy_pvalues_very_small(self, results):
        """Periodic source (period 5000) gives ApEn p-values near zero."""
        pvals = results["periodic.bin"]["approximate_entropy"]["p_values"]
        for i, p in enumerate(pvals):
            assert p < 0.01, \
                f"Periodic ApEn p_value[{i}] = {p}, expected < 0.01"

    def test_csprng_approximate_entropy_pvalues_reasonable(self, results):
        """CSPRNG should produce mostly large ApEn p-values."""
        pvals = results["csprng.bin"]["approximate_entropy"]["p_values"]
        above = sum(1 for p in pvals if p > 0.01)
        assert above >= len(pvals) * 0.7, \
            f"Only {above}/{len(pvals)} CSPRNG ApEn p-values > 0.01; expected >= 70%"


# ============================================================
# Two-Level Assessment Consistency Tests
# ============================================================

class TestAssessmentConsistency:
    """Verify proportion and uniformity calculations are self-consistent."""

    def test_proportion_matches_pvalues(self, results, config):
        """Reported proportion must equal actual count(p >= alpha) / m."""
        alpha = config["significance_level"]
        m = config["num_streams"]

        for source in config["sources"]:
            for test_name in REQUIRED_TESTS:
                entry = results[source][test_name]
                pvals = entry["p_values"]
                passing = sum(1 for p in pvals if p >= alpha)
                expected = passing / m
                assert abs(entry["proportion_passing"] - expected) < 1e-9, \
                    f"Proportion mismatch for {source}/{test_name}: " \
                    f"reported={entry['proportion_passing']}, computed={expected}"

    def test_proportion_result_matches_threshold(self, results, config):
        """proportion_result must be consistent with the minimum pass rate."""
        alpha = config["significance_level"]
        m = config["num_streams"]
        p_hat = 1.0 - alpha
        min_rate = p_hat - 3.0 * math.sqrt(p_hat * (1.0 - p_hat) / m)

        for source in config["sources"]:
            for test_name in REQUIRED_TESTS:
                entry = results[source][test_name]
                expected = "pass" if entry["proportion_passing"] >= min_rate else "fail"
                assert entry["proportion_result"] == expected, \
                    f"Proportion result wrong for {source}/{test_name}: " \
                    f"prop={entry['proportion_passing']:.4f}, min_rate={min_rate:.4f}, " \
                    f"reported='{entry['proportion_result']}', expected='{expected}'"

    def test_uniformity_pvalue_in_range(self, results, config):
        """Uniformity p-value must be in [0, 1]."""
        for source in config["sources"]:
            for test_name in REQUIRED_TESTS:
                up = results[source][test_name]["uniformity_pvalue"]
                assert 0.0 <= up <= 1.0, \
                    f"Uniformity p-value {up} out of range for {source}/{test_name}"

    def test_uniformity_result_matches_pvalue(self, results, config):
        """uniformity_result must be 'pass' iff uniformity_pvalue >= 0.0001."""
        for source in config["sources"]:
            for test_name in REQUIRED_TESTS:
                entry = results[source][test_name]
                expected = "pass" if entry["uniformity_pvalue"] >= 0.0001 else "fail"
                assert entry["uniformity_result"] == expected, \
                    f"Uniformity result wrong for {source}/{test_name}: " \
                    f"pval={entry['uniformity_pvalue']}, " \
                    f"reported='{entry['uniformity_result']}', expected='{expected}'"

    def test_uniformity_pvalue_recomputed(self, results, config):
        """Recompute uniformity p-value from the reported p-values and check."""
        m = config["num_streams"]

        for source in config["sources"]:
            for test_name in REQUIRED_TESTS:
                entry = results[source][test_name]
                pvals = entry["p_values"]

                # Bin p-values into 10 equal sub-intervals of [0, 1)
                bins = [0] * 10
                for p in pvals:
                    idx = min(int(p * 10), 9)
                    bins[idx] += 1

                expected_count = m / 10.0
                chi_sq = sum((f - expected_count) ** 2 / expected_count for f in bins)
                ref_up = float(gammaincc(9.0 / 2.0, chi_sq / 2.0))

                assert abs(entry["uniformity_pvalue"] - ref_up) < 1e-4, \
                    f"Uniformity p-value mismatch for {source}/{test_name}: " \
                    f"reported={entry['uniformity_pvalue']:.6f}, recomputed={ref_up:.6f}"

    def test_summary_consistent_with_tests(self, results, config):
        """Summary overall/failing_tests must match individual test results."""
        for source in config["sources"]:
            expected_failing = []
            for test_name in REQUIRED_TESTS:
                entry = results[source][test_name]
                if entry["proportion_result"] == "fail" or entry["uniformity_result"] == "fail":
                    expected_failing.append(test_name)

            expected_overall = "pass" if len(expected_failing) == 0 else "fail"
            assert results["summary"][source]["overall"] == expected_overall, \
                f"Summary overall wrong for {source}: " \
                f"reported='{results['summary'][source]['overall']}', expected='{expected_overall}'"

            reported_set = set(results["summary"][source]["failing_tests"])
            expected_set = set(expected_failing)
            assert reported_set == expected_set, \
                f"Failing tests mismatch for {source}: " \
                f"reported={reported_set}, expected={expected_set}"
