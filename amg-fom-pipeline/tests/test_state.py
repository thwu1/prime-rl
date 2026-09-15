
import json
import math
import os
import pytest

RESULTS_DIR = "/app/results"

# ── Expected run IDs for excluded runs ──
ERROR_RUN_IDS = {19, 37, 74, 127, 132}
NULL_RUN_IDS = {88, 166}
TIMING_ANOMALY_IDS = {190, 191, 192}
ALL_EXCLUDED_IDS = ERROR_RUN_IDS | NULL_RUN_IDS | TIMING_ANOMALY_IDS

# ── Expected median FOMs (computed from deterministic data) ──
# AMG: FOM = nnz * iterations / solve_time;  median solve_time == base
# Titan-X uses ACTUAL nnz=3.5M (not the standard 7M)
EXPECTED_MEDIANS = {
    ("Sierra-2", "amg"): 50000000.0,       # 7M*20 / 2.80
    ("Frontier-X", "amg"): 100000000.0,    # 7M*20 / 1.40
    ("Aurora-1", "amg"): 77777777.7778,    # 7M*20 / 1.80
    ("Titan-X", "amg"): 40000000.0,        # 3.5M*20 / 1.75  (correct nnz!)
    ("Nova-7", "amg"): 70000000.0,         # 7M*20 / 2.00
    ("Pulsar-3", "amg"): 63636363.6364,    # 7M*20 / 2.20
    ("Sierra-2", "kripke"): 2000000.0,     # 10M / 5.00
    ("Frontier-X", "kripke"): 5000000.0,   # 10M / 2.00
    ("Titan-X", "kripke"): 4000000.0,      # 10M / 2.50
    ("Nova-7", "stream"): 220000.0,        # identical across runs
    ("Sierra-2", "stream"): 135000.0,
    ("Frontier-X", "stream"): 310000.0,
    ("Sierra-2", "pennant"): 819200.0,     # 65536*100 / 8.00
    ("Frontier-X", "pennant"): 1638400.0,  # 65536*100 / 4.00
}

# ── Expected valid run counts ──
EXPECTED_VALID_COUNTS = {
    ("Sierra-2", "amg"): 8,
    ("Frontier-X", "amg"): 7,   # 1 ERROR
    ("Nova-7", "amg"): 7,       # 1 ERROR
    ("Pulsar-3", "amg"): 7,     # 1 NULL
    ("Aurora-1", "kripke"): 7,  # 1 ERROR
    ("Sierra-2", "stream"): 7,  # 1 ERROR
    ("Aurora-1", "stream"): 7,  # 1 NULL
    ("Titan-X", "pennant"): 7,  # 1 ERROR
    ("Pulsar-3", "pennant"): 5, # 3 timing anomaly
}

# ── Expected ranking order ──
EXPECTED_RANK_ORDER = [
    "Frontier-X", "Aurora-1", "Nova-7", "Titan-X", "Pulsar-3", "Sierra-2"
]

SYSTEMS = ["Sierra-2", "Frontier-X", "Aurora-1", "Titan-X", "Nova-7", "Pulsar-3"]
BENCHMARKS = ["amg", "kripke", "stream", "pennant"]

# ── Expected STREAM efficiency values ──
EXPECTED_STREAM_EFFICIENCY = {
    "Sierra-2": 0.84375,     # 135000 / 160000
    "Frontier-X": 0.775,     # 310000 / 400000
    "Aurora-1": 0.78125,     # 250000 / 320000
    "Titan-X": 0.80,         # 192000 / 240000
    "Nova-7": 0.78571,       # 220000 / 280000
    "Pulsar-3": 0.79545,     # 175000 / 220000
}

# ── Expected AMG/STREAM bandwidth ratios ──
EXPECTED_AMG_RATIOS = {
    "Sierra-2": 370.37,      # 50M / 135K
    "Frontier-X": 322.58,    # 100M / 310K
    "Aurora-1": 311.11,      # 77.78M / 250K
    "Titan-X": 208.33,       # 40M / 192K
    "Nova-7": 318.18,        # 70M / 220K
    "Pulsar-3": 363.64,      # 63.64M / 175K
}


def rel_close(a, b, tol=1e-3):
    if b == 0:
        return abs(a) < tol
    return abs(a - b) / abs(b) < tol


def load_json(name):
    path = os.path.join(RESULTS_DIR, name)
    assert os.path.exists(path), f"{path} not found"
    with open(path) as f:
        return json.load(f)


# ═══════════════════════════════════════════
# Audit Report Tests
# ═══════════════════════════════════════════

class TestAuditReport:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = load_json("audit_report.json")

    def test_total_runs(self):
        assert self.data["total_runs"] == 192

    def test_excluded_count(self):
        assert len(self.data["excluded_runs"]) == 10

    def test_error_runs_excluded(self):
        ids = {r["run_id"] for r in self.data["excluded_runs"]}
        for eid in ERROR_RUN_IDS:
            assert eid in ids, f"ERROR run {eid} not excluded"

    def test_null_runs_excluded(self):
        ids = {r["run_id"] for r in self.data["excluded_runs"]}
        for nid in NULL_RUN_IDS:
            assert nid in ids, f"NULL-measurement run {nid} not excluded"

    def test_timing_anomaly_excluded(self):
        ids = {r["run_id"] for r in self.data["excluded_runs"]}
        for tid in TIMING_ANOMALY_IDS:
            assert tid in ids, f"Timing-anomaly run {tid} not excluded"

    def test_excluded_runs_have_reason(self):
        for r in self.data["excluded_runs"]:
            assert "reason" in r and len(r["reason"]) > 0

    # ── Quality flags ──

    def test_quality_flags_count(self):
        assert len(self.data["quality_flags"]) == 3

    def test_titan_amg_flagged(self):
        flags = self.data["quality_flags"]
        match = [f for f in flags
                 if f["system"] == "Titan-X" and f["benchmark"] == "amg"]
        assert len(match) == 1, "Titan-X AMG quality flag missing"

    def test_nova_stream_flagged(self):
        flags = self.data["quality_flags"]
        match = [f for f in flags
                 if f["system"] == "Nova-7" and f["benchmark"] == "stream"]
        assert len(match) == 1, "Nova-7 STREAM quality flag missing"

    def test_pulsar_pennant_flagged(self):
        flags = self.data["quality_flags"]
        match = [f for f in flags
                 if f["system"] == "Pulsar-3" and f["benchmark"] == "pennant"]
        assert len(match) == 1, "Pulsar-3 PENNANT quality flag missing"

    def test_quality_flags_have_details(self):
        for f in self.data["quality_flags"]:
            assert "details" in f and len(f["details"]) > 0

    # ── FOM discrepancies ──

    def test_discrepancy_count(self):
        assert len(self.data["fom_discrepancies"]) == 55

    def test_kripke_discrepancy_pct(self):
        """All valid Kripke runs should show pct_error ~ -90 (reported missing iterations)."""
        disc = self.data["fom_discrepancies"]
        kripke_like = [d for d in disc if -92 < d["pct_error"] < -88]
        assert len(kripke_like) == 47, (
            f"Expected 47 Kripke discrepancies with pct_error~-90, got {len(kripke_like)}"
        )

    def test_titan_amg_discrepancy_pct(self):
        """Titan-X AMG runs should show pct_error ~ +100 (reported uses wrong nnz)."""
        disc = self.data["fom_discrepancies"]
        titan_like = [d for d in disc if 98 < d["pct_error"] < 102]
        assert len(titan_like) == 8, (
            f"Expected 8 Titan-X AMG discrepancies with pct_error~100, got {len(titan_like)}"
        )

    def test_discrepancy_fields(self):
        for d in self.data["fom_discrepancies"]:
            assert "run_id" in d
            assert "reported_fom" in d
            assert "computed_fom" in d
            assert "pct_error" in d


# ═══════════════════════════════════════════
# Performance Summary Tests
# ═══════════════════════════════════════════

class TestPerformanceSummary:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = load_json("performance_summary.json")

    def test_all_systems_present(self):
        for s in SYSTEMS:
            assert s in self.data, f"System {s} missing"

    def test_all_benchmarks_present(self):
        for s in SYSTEMS:
            for b in BENCHMARKS:
                assert b in self.data[s], f"{s}/{b} missing"

    def test_required_fields(self):
        fields = {"median_fom", "mean_fom", "std_fom",
                  "ci_lower", "ci_upper", "valid_run_count", "flagged"}
        for s in SYSTEMS:
            for b in BENCHMARKS:
                entry = self.data[s][b]
                for f in fields:
                    assert f in entry, f"{s}/{b} missing field '{f}'"

    def test_median_fom_spot_checks(self):
        for (sys, bench), expected in EXPECTED_MEDIANS.items():
            actual = self.data[sys][bench]["median_fom"]
            assert rel_close(actual, expected, tol=1e-3), (
                f"median_fom {sys}/{bench}: got {actual}, expected {expected}"
            )

    def test_valid_run_counts(self):
        for (sys, bench), expected in EXPECTED_VALID_COUNTS.items():
            actual = self.data[sys][bench]["valid_run_count"]
            assert actual == expected, (
                f"valid_run_count {sys}/{bench}: got {actual}, expected {expected}"
            )

    def test_default_valid_count_is_8(self):
        """System-benchmark pairs without known exclusions should have 8 valid runs."""
        for s in SYSTEMS:
            for b in BENCHMARKS:
                if (s, b) not in EXPECTED_VALID_COUNTS:
                    actual = self.data[s][b]["valid_run_count"]
                    assert actual == 8, (
                        f"{s}/{b} expected 8 valid runs, got {actual}"
                    )

    def test_nova_stream_flagged(self):
        assert self.data["Nova-7"]["stream"]["flagged"] is True

    def test_nova_stream_zero_std(self):
        std = self.data["Nova-7"]["stream"]["std_fom"]
        assert std < 1.0, f"Nova-7 STREAM std should be ~0, got {std}"

    def test_titan_amg_uses_correct_nnz(self):
        """Titan-X AMG median must reflect actual nnz=3.5M, not standard 7M."""
        actual = self.data["Titan-X"]["amg"]["median_fom"]
        wrong_fom = 80000000.0   # would be 7M*20/1.75 if using wrong nnz
        correct_fom = 40000000.0  # 3.5M*20/1.75
        assert rel_close(actual, correct_fom, tol=1e-3), (
            f"Titan-X AMG median {actual} is wrong; expected ~{correct_fom} (not {wrong_fom})"
        )

    def test_ci_bounds_consistent(self):
        for s in SYSTEMS:
            for b in BENCHMARKS:
                e = self.data[s][b]
                if e["valid_run_count"] >= 2 and e["std_fom"] > 0:
                    assert e["ci_lower"] < e["mean_fom"] < e["ci_upper"], (
                        f"{s}/{b}: CI bounds [{e['ci_lower']}, {e['ci_upper']}] "
                        f"don't contain mean {e['mean_fom']}"
                    )


# ═══════════════════════════════════════════
# Efficiency Analysis Tests
# ═══════════════════════════════════════════

class TestEfficiencyAnalysis:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = load_json("efficiency_analysis.json")

    # ── Structure tests ──

    def test_stream_efficiency_all_systems(self):
        se = self.data["stream_efficiency"]
        for s in SYSTEMS:
            assert s in se, f"System {s} missing from stream_efficiency"
            assert "measured_bandwidth" in se[s]
            assert "theoretical_peak" in se[s]
            assert "efficiency" in se[s]

    def test_cross_benchmark_structure(self):
        cba = self.data["cross_benchmark_analysis"]
        assert "amg_bandwidth_ratios" in cba
        assert "fleet_mean" in cba
        assert "fleet_std" in cba
        assert "outlier_threshold_sigma" in cba
        assert "outliers" in cba

    def test_cross_benchmark_all_systems(self):
        ratios = self.data["cross_benchmark_analysis"]["amg_bandwidth_ratios"]
        for s in SYSTEMS:
            assert s in ratios, f"System {s} missing from amg_bandwidth_ratios"

    # ── Physical plausibility ──

    def test_no_efficiency_exceeds_one(self):
        """No system can have bandwidth efficiency > 1.0 (physically impossible)."""
        for s in SYSTEMS:
            eff = self.data["stream_efficiency"][s]["efficiency"]
            assert eff <= 1.0, f"{s} efficiency {eff} exceeds physical limit of 1.0"

    def test_all_efficiencies_in_plausible_range(self):
        """Well-configured systems achieve 75-90% bandwidth efficiency."""
        for s in SYSTEMS:
            eff = self.data["stream_efficiency"][s]["efficiency"]
            assert 0.70 <= eff <= 0.90, (
                f"{s} efficiency {eff} outside plausible range [0.70, 0.90]"
            )

    # ── Specific efficiency values ──

    def test_sierra_2_efficiency(self):
        eff = self.data["stream_efficiency"]["Sierra-2"]["efficiency"]
        assert rel_close(eff, 0.84375, tol=1e-3), (
            f"Sierra-2 efficiency {eff}, expected ~0.84375"
        )

    def test_titan_x_efficiency(self):
        eff = self.data["stream_efficiency"]["Titan-X"]["efficiency"]
        assert rel_close(eff, 0.80, tol=1e-3), (
            f"Titan-X efficiency {eff}, expected ~0.80"
        )

    def test_frontier_x_efficiency(self):
        eff = self.data["stream_efficiency"]["Frontier-X"]["efficiency"]
        assert rel_close(eff, 0.775, tol=1e-3), (
            f"Frontier-X efficiency {eff}, expected ~0.775"
        )

    # ── Cross-benchmark outlier detection ──

    def test_titan_x_is_outlier(self):
        """Titan-X AMG/STREAM ratio deviates from fleet due to non-standard nnz."""
        outliers = self.data["cross_benchmark_analysis"]["outliers"]
        assert "Titan-X" in outliers, (
            "Titan-X should be flagged as cross-benchmark outlier"
        )

    def test_only_one_outlier(self):
        outliers = self.data["cross_benchmark_analysis"]["outliers"]
        assert len(outliers) == 1, (
            f"Expected exactly 1 outlier (Titan-X), got {len(outliers)}: {outliers}"
        )

    def test_titan_x_has_lowest_ratio(self):
        """Titan-X should have lowest AMG/STREAM ratio due to non-standard config."""
        ratios = self.data["cross_benchmark_analysis"]["amg_bandwidth_ratios"]
        titan_ratio = ratios["Titan-X"]
        for s, r in ratios.items():
            if s != "Titan-X":
                assert r > titan_ratio, (
                    f"{s} ratio {r} should be > Titan-X ratio {titan_ratio}"
                )

    # ── Fleet statistics ──

    def test_fleet_mean(self):
        fm = self.data["cross_benchmark_analysis"]["fleet_mean"]
        assert rel_close(fm, 315.70, tol=0.01), (
            f"Fleet mean {fm}, expected ~315.70"
        )

    def test_fleet_std(self):
        fs = self.data["cross_benchmark_analysis"]["fleet_std"]
        assert rel_close(fs, 58.14, tol=0.05), (
            f"Fleet std {fs}, expected ~58.14"
        )

    def test_outlier_threshold_from_config(self):
        threshold = self.data["cross_benchmark_analysis"]["outlier_threshold_sigma"]
        assert threshold == 1.5

    # ── AMG/STREAM ratio spot checks ──

    def test_sierra_2_ratio(self):
        ratio = self.data["cross_benchmark_analysis"]["amg_bandwidth_ratios"]["Sierra-2"]
        assert rel_close(ratio, 370.37, tol=0.01)

    def test_titan_x_ratio(self):
        ratio = self.data["cross_benchmark_analysis"]["amg_bandwidth_ratios"]["Titan-X"]
        assert rel_close(ratio, 208.33, tol=0.01)


# ═══════════════════════════════════════════
# Ranking Tests
# ═══════════════════════════════════════════

class TestRanking:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.data = load_json("ranking.json")

    def test_rankings_key(self):
        assert "rankings" in self.data

    def test_ranking_count(self):
        assert len(self.data["rankings"]) == 6

    def test_ranking_order(self):
        order = [r["system"] for r in self.data["rankings"]]
        assert order == EXPECTED_RANK_ORDER, (
            f"Ranking order wrong: {order}, expected {EXPECTED_RANK_ORDER}"
        )

    def test_ranks_sequential(self):
        ranks = [r["rank"] for r in self.data["rankings"]]
        assert ranks == [1, 2, 3, 4, 5, 6]

    def test_reference_score_is_one(self):
        ref = [r for r in self.data["rankings"] if r["system"] == "Sierra-2"]
        assert len(ref) == 1
        assert rel_close(ref[0]["score"], 1.0, tol=1e-3), (
            f"Reference system score should be ~1.0, got {ref[0]['score']}"
        )

    def test_frontier_highest_score(self):
        scores = {r["system"]: r["score"] for r in self.data["rankings"]}
        assert scores["Frontier-X"] > scores["Aurora-1"]
        assert scores["Frontier-X"] > 2.0

    def test_scores_descending(self):
        scores = [r["score"] for r in self.data["rankings"]]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Scores not descending at position {i}: {scores[i]} < {scores[i+1]}"
            )

    def test_flagged_systems_have_flags(self):
        """Titan-X, Nova-7, Pulsar-3 should have non-empty flags."""
        for r in self.data["rankings"]:
            if r["system"] in ("Titan-X", "Nova-7", "Pulsar-3"):
                assert len(r["flags"]) > 0, (
                    f"{r['system']} should have quality flags"
                )

    def test_clean_systems_no_flags(self):
        for r in self.data["rankings"]:
            if r["system"] in ("Sierra-2", "Frontier-X", "Aurora-1"):
                assert len(r["flags"]) == 0, (
                    f"{r['system']} should have no flags, got {r['flags']}"
                )

    def test_ranking_has_required_fields(self):
        for r in self.data["rankings"]:
            assert "rank" in r
            assert "system" in r
            assert "score" in r
            assert "flags" in r
