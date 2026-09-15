
import json
import os
import pytest


CLEAN_IDS = {"R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09", "R10", "R11", "R12"}
ANOMALOUS_IDS = {"R13", "R14", "R15", "R16", "R17", "R18", "R19", "R20"}
MUST_EXCLUDE_IDS = {"R13", "R14", "R15", "R16", "R17", "R18"}
CACHE_ARTIFACT_IDS = {"R19", "R20"}


@pytest.fixture(scope="module")
def report():
    path = "/app/audit_report.json"
    assert os.path.exists(path), "audit_report.json not found at /app/audit_report.json"
    with open(path) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def anomaly_map(report):
    return {a["result_id"]: a for a in report["anomalies"]}


# ============================================================
# Structure
# ============================================================

class TestStructure:
    def test_has_anomalies(self, report):
        assert "anomalies" in report
        assert isinstance(report["anomalies"], list)

    def test_has_corrected_metrics(self, report):
        assert "corrected_metrics" in report
        assert isinstance(report["corrected_metrics"], dict)

    def test_has_total_results(self, report):
        assert report["total_results"] == 20

    def test_has_clean_count(self, report):
        assert "clean_count" in report
        assert isinstance(report["clean_count"], int)

    def test_has_excluded_count(self, report):
        assert "excluded_count" in report
        assert isinstance(report["excluded_count"], int)

    def test_counts_consistent(self, report):
        assert report["clean_count"] + report["excluded_count"] == report["total_results"]


# ============================================================
# Anomaly detection: roofline violations
# ============================================================

class TestRooflineViolations:
    def test_r13_detected(self, anomaly_map):
        assert "R13" in anomaly_map, \
            "R13 not detected: matmul kernel at ~1000us is faster than theoretical minimum ~7048us"

    def test_r13_excluded(self, anomaly_map):
        assert anomaly_map["R13"]["recommendation"] == "exclude"

    def test_r14_detected(self, anomaly_map):
        assert "R14" in anomaly_map, \
            "R14 not detected: attention kernel at ~0.05us is faster than theoretical minimum ~5.14us"

    def test_r14_excluded(self, anomaly_map):
        assert anomaly_map["R14"]["recommendation"] == "exclude"

    def test_r13_r14_same_type(self, anomaly_map):
        assert anomaly_map["R13"]["anomaly_type"] == anomaly_map["R14"]["anomaly_type"], \
            "R13 and R14 should have the same anomaly type (both exceed roofline)"


# ============================================================
# Anomaly detection: tolerance mismatches
# ============================================================

class TestToleranceMismatch:
    def test_r15_detected(self, anomaly_map):
        assert "R15" in anomaly_map, \
            "R15 not detected: fp32 result validated with atol=0.01 instead of 1e-4"

    def test_r15_excluded(self, anomaly_map):
        assert anomaly_map["R15"]["recommendation"] == "exclude"

    def test_r16_detected(self, anomaly_map):
        assert "R16" in anomaly_map, \
            "R16 not detected: fp32 result validated with atol=0.01 instead of 1e-4"

    def test_r16_excluded(self, anomaly_map):
        assert anomaly_map["R16"]["recommendation"] == "exclude"

    def test_r15_r16_same_type(self, anomaly_map):
        assert anomaly_map["R15"]["anomaly_type"] == anomaly_map["R16"]["anomaly_type"], \
            "R15 and R16 should have the same anomaly type (both tolerance mismatch)"


# ============================================================
# Anomaly detection: timing instability
# ============================================================

class TestTimingInstability:
    def test_r17_detected(self, anomaly_map):
        assert "R17" in anomaly_map, \
            "R17 not detected: kernel timing CV=0.46, trials range 800-3200us"

    def test_r17_excluded(self, anomaly_map):
        assert anomaly_map["R17"]["recommendation"] == "exclude"

    def test_r18_detected(self, anomaly_map):
        assert "R18" in anomaly_map, \
            "R18 not detected: kernel timing CV=0.53, trials range 30-150us"

    def test_r18_excluded(self, anomaly_map):
        assert anomaly_map["R18"]["recommendation"] == "exclude"

    def test_r17_r18_same_type(self, anomaly_map):
        assert anomaly_map["R17"]["anomaly_type"] == anomaly_map["R18"]["anomaly_type"], \
            "R17 and R18 should have the same anomaly type (both timing instability)"


# ============================================================
# Anomaly detection: cache artifacts
# ============================================================

class TestCacheArtifacts:
    def test_r19_detected(self, anomaly_map):
        assert "R19" in anomaly_map, \
            "R19 not detected: bimodal timing with warm cluster ~7700us and cold cluster ~14000us"

    def test_r20_detected(self, anomaly_map):
        assert "R20" in anomaly_map, \
            "R20 not detected: bimodal timing with warm cluster ~59us and cold cluster ~105us"

    def test_r19_recommendation(self, anomaly_map):
        assert anomaly_map["R19"]["recommendation"] in ("correct", "exclude"), \
            "R19 should be 'correct' or 'exclude'"

    def test_r20_recommendation(self, anomaly_map):
        assert anomaly_map["R20"]["recommendation"] in ("correct", "exclude"), \
            "R20 should be 'correct' or 'exclude'"

    def test_r19_r20_same_type(self, anomaly_map):
        assert anomaly_map["R19"]["anomaly_type"] == anomaly_map["R20"]["anomaly_type"], \
            "R19 and R20 should have the same anomaly type (both cache artifacts)"


# ============================================================
# No false positives
# ============================================================

class TestNoFalsePositives:
    def test_clean_not_flagged(self, anomaly_map):
        flagged = set(anomaly_map.keys())
        false_positives = flagged & CLEAN_IDS
        assert len(false_positives) == 0, \
            f"Clean results falsely flagged as anomalous: {false_positives}"


# ============================================================
# Anomaly type diversity
# ============================================================

class TestAnomalyTypes:
    def test_all_anomalies_have_type(self, report):
        for a in report["anomalies"]:
            assert "anomaly_type" in a, f"Missing anomaly_type for {a['result_id']}"
            assert len(a["anomaly_type"]) > 0

    def test_at_least_three_distinct_types(self, anomaly_map):
        types = set()
        for a in anomaly_map.values():
            types.add(a["anomaly_type"])
        assert len(types) >= 3, \
            f"Expected at least 3 distinct anomaly types, got {len(types)}: {types}"

    def test_roofline_different_from_tolerance(self, anomaly_map):
        if "R13" in anomaly_map and "R15" in anomaly_map:
            assert anomaly_map["R13"]["anomaly_type"] != anomaly_map["R15"]["anomaly_type"], \
                "Roofline violations and tolerance mismatches should be different types"

    def test_instability_different_from_roofline(self, anomaly_map):
        if "R17" in anomaly_map and "R13" in anomaly_map:
            assert anomaly_map["R17"]["anomaly_type"] != anomaly_map["R13"]["anomaly_type"], \
                "Timing instability and roofline violations should be different types"


# ============================================================
# Corrected metrics
# ============================================================

class TestCorrectedMetrics:
    def test_has_a100(self, report):
        assert "A100" in report["corrected_metrics"]

    def test_has_v100(self, report):
        assert "V100" in report["corrected_metrics"]

    def test_a100_fast_0(self, report):
        v = report["corrected_metrics"]["A100"]["fast_0.0"]
        # 6/8 = 0.75 (cache corrected) or 5/7 ~= 0.714 (cache excluded)
        assert 0.70 <= v <= 0.76, f"A100 fast_0.0 = {v}, expected ~0.75"

    def test_a100_fast_1(self, report):
        v = report["corrected_metrics"]["A100"]["fast_1.0"]
        # 5/8 = 0.625 (cache corrected) or 4/7 ~= 0.571 (cache excluded)
        assert 0.55 <= v <= 0.66, f"A100 fast_1.0 = {v}, expected ~0.625"

    def test_a100_fast_2(self, report):
        v = report["corrected_metrics"]["A100"]["fast_2.0"]
        # 1/8 = 0.125 (cache corrected) or 1/7 ~= 0.143 (cache excluded)
        assert 0.10 <= v <= 0.16, f"A100 fast_2.0 = {v}, expected ~0.125"

    def test_v100_fast_0(self, report):
        v = report["corrected_metrics"]["V100"]["fast_0.0"]
        # 6/6 = 1.0 or 5/5 = 1.0
        assert 0.95 <= v <= 1.0, f"V100 fast_0.0 = {v}, expected ~1.0"

    def test_v100_fast_1(self, report):
        v = report["corrected_metrics"]["V100"]["fast_1.0"]
        # 5/6 ~= 0.833 (cache corrected) or 4/5 = 0.8 (cache excluded)
        assert 0.78 <= v <= 0.86, f"V100 fast_1.0 = {v}, expected ~0.833"

    def test_v100_fast_2(self, report):
        v = report["corrected_metrics"]["V100"]["fast_2.0"]
        # 0/6 = 0.0 or 0/5 = 0.0
        assert v <= 0.05, f"V100 fast_2.0 = {v}, expected 0.0"


# ============================================================
# Counts
# ============================================================

class TestCounts:
    def test_excluded_count_range(self, report):
        # 6 if cache artifacts corrected, 8 if all excluded
        assert 6 <= report["excluded_count"] <= 8, \
            f"excluded_count = {report['excluded_count']}, expected 6-8"

    def test_clean_count_range(self, report):
        # 14 if cache corrected, 12 if all excluded
        assert 12 <= report["clean_count"] <= 14, \
            f"clean_count = {report['clean_count']}, expected 12-14"
