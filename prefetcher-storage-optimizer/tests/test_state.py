
import json
import os
import math
import pytest


@pytest.fixture(scope="session")
def results():
    """Load the results.json produced by the audit pipeline."""
    results_path = "/app/results.json"
    assert os.path.exists(results_path), (
        f"results.json not found at {results_path}. "
        "Did you run the audit pipeline?"
    )
    with open(results_path) as f:
        data = json.load(f)
    return data


# ──────────────────────────────────────────────
#  Original configuration storage verification
# ──────────────────────────────────────────────

class TestOriginalConfig:
    """Verify the storage breakdown for the original PIPS configuration."""

    def test_has_original_config(self, results):
        assert "original_config" in results

    def test_entry_data_bits(self, results):
        assert results["original_config"]["entry_data_bits"] == 82

    def test_lht_entry_bits(self, results):
        assert results["original_config"]["lht_entry_bits"] == 101

    def test_scc_entry_bits(self, results):
        assert results["original_config"]["scc_entry_bits"] == 100

    def test_lht_entries(self, results):
        assert results["original_config"]["lht_entries"] == 10240

    def test_scc_entries(self, results):
        assert results["original_config"]["scc_entries"] == 128

    def test_lht_bits(self, results):
        assert results["original_config"]["lht_bits"] == 1034240

    def test_scc_bits(self, results):
        assert results["original_config"]["scc_bits"] == 12800

    def test_misc_bits(self, results):
        assert results["original_config"]["misc_bits"] == 350

    def test_total_bits(self, results):
        assert results["original_config"]["total_bits"] == 1047390

    def test_total_bits_consistency(self, results):
        oc = results["original_config"]
        assert oc["total_bits"] == oc["lht_bits"] + oc["scc_bits"] + oc["misc_bits"]

    def test_total_kb(self, results):
        expected_kb = 1047390 / 8192
        assert abs(results["original_config"]["total_kb"] - expected_kb) < 0.001

    def test_within_budget(self, results):
        assert results["original_config"]["within_budget"] is True


# ──────────────────────────────────────────────
#  Parameter sweep results
# ──────────────────────────────────────────────

class TestSweep:
    """Verify the parameter sweep dimensions and valid config count."""

    def test_total_configs_evaluated(self, results):
        assert results["sweep"]["total_configs_evaluated"] == 2448

    def test_valid_configs(self, results):
        assert results["sweep"]["valid_configs"] == 1407


# ──────────────────────────────────────────────
#  Pareto front verification
# ──────────────────────────────────────────────

EXPECTED_PARETO = [
    (14336, 2048),
    (13312, 8192),
    (12288, 32768),
    (11264, 262144),
    (10240, 2097152),
    (9216, 16777216),
    (8192, 134217728),
]


class TestParetoFront:
    """Verify the non-dominated frontier on (lht_entries, max_reach)."""

    def test_pareto_length(self, results):
        assert len(results["pareto_front"]) == 7

    def test_pareto_points(self, results):
        actual = [
            (p["lht_entries"], p["max_reach"]) for p in results["pareto_front"]
        ]
        assert actual == EXPECTED_PARETO

    def test_pareto_entries_descending(self, results):
        entries = [p["lht_entries"] for p in results["pareto_front"]]
        for i in range(len(entries) - 1):
            assert entries[i] > entries[i + 1], (
                f"Frontier entries must be strictly decreasing: "
                f"{entries[i]} vs {entries[i+1]}"
            )

    def test_pareto_reach_ascending(self, results):
        reaches = [p["max_reach"] for p in results["pareto_front"]]
        for i in range(len(reaches) - 1):
            assert reaches[i] < reaches[i + 1], (
                f"Frontier reach must be strictly increasing: "
                f"{reaches[i]} vs {reaches[i+1]}"
            )

    def test_pareto_non_dominated(self, results):
        """No point on the front should dominate another."""
        pf = results["pareto_front"]
        for i, a in enumerate(pf):
            for j, b in enumerate(pf):
                if i == j:
                    continue
                dominated = (
                    a["lht_entries"] >= b["lht_entries"]
                    and a["max_reach"] >= b["max_reach"]
                    and (
                        a["lht_entries"] > b["lht_entries"]
                        or a["max_reach"] > b["max_reach"]
                    )
                )
                assert not dominated, (
                    f"Point {i} dominates point {j}: "
                    f"({a['lht_entries']},{a['max_reach']}) vs "
                    f"({b['lht_entries']},{b['max_reach']})"
                )

    def test_original_config_on_pareto(self, results):
        """The original (10240, 2097152) must appear on the frontier."""
        for p in results["pareto_front"]:
            if p["lht_entries"] == 10240 and p["max_reach"] == 2097152:
                return
        pytest.fail("Original config (entries=10240, reach=2097152) not on frontier")

    def test_pareto_within_budget(self, results):
        for p in results["pareto_front"]:
            assert p["total_bits"] <= 1048576, (
                f"Frontier point exceeds budget: {p['total_bits']} bits"
            )

    def test_pareto_combined_scores(self, results):
        for p in results["pareto_front"]:
            expected = 2 * p["lht_entries"] * p["max_reach"] / (
                p["lht_entries"] + p["max_reach"]
            )
            assert abs(p["combined_score"] - expected) < 0.01, (
                f"combined_score mismatch for ({p['lht_entries']}, {p['max_reach']})"
            )


# ──────────────────────────────────────────────
#  Best combined (harmonic mean) configuration
# ──────────────────────────────────────────────

class TestBestCombined:
    """Verify the configuration maximizing harmonic mean of entries and reach."""

    def test_best_offsetbits(self, results):
        assert results["best_combined"]["offsetbits"] == 19

    def test_best_entries(self, results):
        assert results["best_combined"]["lht_entries"] == 11264

    def test_best_reach(self, results):
        assert results["best_combined"]["max_reach"] == 262144

    def test_best_score_value(self, results):
        expected = 2 * 11264 * 262144 / (11264 + 262144)
        actual = results["best_combined"]["combined_score"]
        assert abs(actual - expected) < 0.01, (
            f"Best combined score: expected {expected:.4f}, got {actual:.4f}"
        )

    def test_best_is_on_pareto(self, results):
        bc = results["best_combined"]
        for p in results["pareto_front"]:
            if (
                p["lht_entries"] == bc["lht_entries"]
                and p["max_reach"] == bc["max_reach"]
            ):
                return
        pytest.fail("best_combined is not on the frontier")

    def test_best_is_global_max(self, results):
        """The best_combined score must be >= all other frontier scores."""
        bc_score = results["best_combined"]["combined_score"]
        for p in results["pareto_front"]:
            assert bc_score >= p["combined_score"] - 0.01, (
                f"best_combined score {bc_score:.2f} < frontier point score "
                f"{p['combined_score']:.2f}"
            )
