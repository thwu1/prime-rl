"""Tests for GIAB benchmark strategy evaluation and optimization."""

import json
import os
import pytest

OUTPUT_DIR = "/app/output"
REF_LENGTH = 500000
TRUTH_SET_PATH = "/app/truth_set.json"


def load_truth_set():
    with open(TRUTH_SET_PATH) as f:
        ts = json.load(f)
    true_pos = {v["position"] for v in ts["variants"] if v["label"] == "validated_true"}
    false_pos = {v["position"] for v in ts["variants"] if v["label"] == "validated_false"}
    return true_pos, false_pos


def read_benchmark_regions(path):
    intervals = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            intervals.append((parts[0], int(parts[1]), int(parts[2])))
    return intervals


def pos_in_regions(pos_1based, regions):
    p = pos_1based - 1
    for _, s, e in regions:
        if s <= p < e:
            return True
    return False


class TestOutputFilesExist:
    def test_evaluation_json(self):
        assert os.path.isfile("/app/evaluation.json")

    def test_step_impact_json(self):
        assert os.path.isfile("/app/step_impact.json")

    def test_optimized_config_json(self):
        assert os.path.isfile("/app/optimized_config.json")

    def test_benchmark_regions(self):
        assert os.path.isfile(f"{OUTPUT_DIR}/benchmark_regions.bed")

    def test_exclusion_stats(self):
        assert os.path.isfile(f"{OUTPUT_DIR}/exclusion_stats.tsv")

    def test_benchmark_variants(self):
        assert os.path.isfile(f"{OUTPUT_DIR}/benchmark_variants.vcf")

    def test_variant_summary(self):
        assert os.path.isfile(f"{OUTPUT_DIR}/variant_summary.json")


class TestEvaluationMetrics:
    @pytest.fixture
    def evaluation(self):
        with open("/app/evaluation.json") as f:
            return json.load(f)

    def test_strategy_a_sensitivity(self, evaluation):
        val = evaluation["strategy_a"]["sensitivity"]
        assert abs(val - 0.9118) < 0.005, f"Strategy A sensitivity: expected ~0.9118, got {val}"

    def test_strategy_a_specificity(self, evaluation):
        val = evaluation["strategy_a"]["specificity"]
        assert abs(val - 1.0) < 0.005, f"Strategy A specificity: expected 1.0, got {val}"

    def test_strategy_a_composite(self, evaluation):
        val = evaluation["strategy_a"]["composite_score"]
        assert abs(val - 0.9225) < 0.005, f"Strategy A composite: expected ~0.9225, got {val}"

    def test_strategy_b_sensitivity(self, evaluation):
        val = evaluation["strategy_b"]["sensitivity"]
        assert abs(val - 1.0) < 0.005, f"Strategy B sensitivity: expected 1.0, got {val}"

    def test_strategy_b_specificity(self, evaluation):
        val = evaluation["strategy_b"]["specificity"]
        assert abs(val - 0.7273) < 0.005, f"Strategy B specificity: expected ~0.7273, got {val}"

    def test_strategy_b_composite(self, evaluation):
        val = evaluation["strategy_b"]["composite_score"]
        assert abs(val - 0.8601) < 0.005, f"Strategy B composite: expected ~0.8601, got {val}"

    def test_strategy_c_sensitivity(self, evaluation):
        val = evaluation["strategy_c"]["sensitivity"]
        assert abs(val - 0.9412) < 0.005, f"Strategy C sensitivity: expected ~0.9412, got {val}"

    def test_strategy_c_specificity(self, evaluation):
        val = evaluation["strategy_c"]["specificity"]
        assert abs(val - 1.0) < 0.005, f"Strategy C specificity: expected 1.0, got {val}"

    def test_strategy_c_composite(self, evaluation):
        val = evaluation["strategy_c"]["composite_score"]
        assert abs(val - 0.9402) < 0.005, f"Strategy C composite: expected ~0.9402, got {val}"

    def test_ranking_best(self, evaluation):
        assert evaluation["ranking"][0] == "strategy_c", (
            f"Best strategy should be strategy_c, got {evaluation['ranking'][0]}"
        )

    def test_ranking_worst(self, evaluation):
        assert evaluation["ranking"][2] == "strategy_b", (
            f"Worst strategy should be strategy_b, got {evaluation['ranking'][2]}"
        )

    def test_ranking_order(self, evaluation):
        assert evaluation["ranking"] == ["strategy_c", "strategy_a", "strategy_b"], (
            f"Ranking should be [strategy_c, strategy_a, strategy_b], got {evaluation['ranking']}"
        )

    def test_best_strategy(self, evaluation):
        assert evaluation["best_strategy"] == "strategy_c"


class TestStepImpact:
    @pytest.fixture
    def impact(self):
        with open("/app/step_impact.json") as f:
            return json.load(f)

    def test_analyzed_strategy(self, impact):
        assert impact["analyzed_strategy"] == "strategy_c"

    def test_weakest_step(self, impact):
        assert impact["weakest_step"] == "tandem_repeats", (
            f"Weakest step should be tandem_repeats, got {impact['weakest_step']}"
        )

    def test_tandem_repeat_true_loss(self, impact):
        tr_step = None
        for step in impact["steps"]:
            if step["step_name"] == "tandem_repeats":
                tr_step = step
                break
        assert tr_step is not None, "tandem_repeats step not found in impact analysis"
        assert tr_step["validated_true_lost"] == 2, (
            f"tandem_repeats should lose 2 true variants, got {tr_step['validated_true_lost']}"
        )

    def test_tandem_repeat_false_exclusion(self, impact):
        tr_step = None
        for step in impact["steps"]:
            if step["step_name"] == "tandem_repeats":
                tr_step = step
                break
        assert tr_step is not None
        assert tr_step["validated_false_excluded"] == 0, (
            f"tandem_repeats should exclude 0 false variants, got {tr_step['validated_false_excluded']}"
        )

    def test_tandem_repeat_positions_lost(self, impact):
        tr_step = None
        for step in impact["steps"]:
            if step["step_name"] == "tandem_repeats":
                tr_step = step
                break
        assert tr_step is not None
        lost = sorted(tr_step["true_positions_lost"])
        assert lost == [100500, 310500], (
            f"Expected true positions lost [100500, 310500], got {lost}"
        )

    def test_other_steps_no_true_loss(self, impact):
        for step in impact["steps"]:
            if step["step_name"] != "tandem_repeats":
                assert step["validated_true_lost"] == 0, (
                    f"Step {step['step_name']} should not lose true variants, "
                    f"but lost {step['validated_true_lost']}"
                )


class TestOptimizedConfig:
    @pytest.fixture
    def config(self):
        with open("/app/optimized_config.json") as f:
            return json.load(f)

    def test_valid_json(self, config):
        assert "reference_name" in config
        assert "reference_length" in config
        assert "steps" in config
        assert isinstance(config["steps"], list)
        assert len(config["steps"]) >= 1

    def test_has_required_fields(self, config):
        assert config["reference_name"] == "chr_test"
        assert config["reference_length"] == 500000
        assert "variants_file" in config

    def test_steps_have_required_fields(self, config):
        for step in config["steps"]:
            assert "name" in step, f"Step missing name field: {step}"
            assert "file" in step, f"Step missing file field: {step}"


class TestOptimizedBenchmarkQuality:
    @pytest.fixture
    def regions(self):
        return read_benchmark_regions(f"{OUTPUT_DIR}/benchmark_regions.bed")

    @pytest.fixture
    def truth(self):
        return load_truth_set()

    def test_sensitivity_perfect(self, regions, truth):
        true_pos, _ = truth
        retained = {p for p in true_pos if pos_in_regions(p, regions)}
        missed = true_pos - retained
        assert len(missed) == 0, (
            f"Optimized benchmark misses {len(missed)} validated_true variants: {sorted(missed)}"
        )

    def test_specificity_perfect(self, regions, truth):
        _, false_pos = truth
        retained_false = {p for p in false_pos if pos_in_regions(p, regions)}
        assert len(retained_false) == 0, (
            f"Optimized benchmark retains {len(retained_false)} validated_false variants: "
            f"{sorted(retained_false)}"
        )

    def test_composite_score_threshold(self, regions, truth):
        true_pos, false_pos = truth
        all_positions = true_pos | false_pos
        retained_true = sum(1 for p in true_pos if pos_in_regions(p, regions))
        excluded_false = sum(1 for p in false_pos if not pos_in_regions(p, regions))
        sens = retained_true / len(true_pos)
        spec = excluded_false / len(false_pos)
        cov = sum(e - s for _, s, e in regions) / REF_LENGTH
        composite = 0.4 * sens + 0.4 * spec + 0.2 * cov
        assert composite >= 0.96, (
            f"Composite score {composite:.4f} below threshold 0.96 "
            f"(sens={sens:.4f}, spec={spec:.4f}, cov={cov:.4f})"
        )

    def test_coverage_reasonable(self, regions):
        cov_bp = sum(e - s for _, s, e in regions)
        cov_pct = cov_bp / REF_LENGTH
        assert 0.70 <= cov_pct <= 0.95, (
            f"Coverage {cov_pct:.4f} outside reasonable range [0.70, 0.95]"
        )


class TestOptimizedBenchmarkConsistency:
    @pytest.fixture
    def regions(self):
        return read_benchmark_regions(f"{OUTPUT_DIR}/benchmark_regions.bed")

    @pytest.fixture
    def summary(self):
        with open(f"{OUTPUT_DIR}/variant_summary.json") as f:
            return json.load(f)

    def test_regions_sorted_nonoverlapping(self, regions):
        for i in range(len(regions) - 1):
            assert regions[i][2] <= regions[i + 1][1], (
                f"Intervals overlap or unsorted at index {i}: "
                f"{regions[i]} and {regions[i + 1]}"
            )

    def test_no_negative_starts(self, regions):
        for chrom, start, end in regions:
            assert start >= 0, f"Negative start: {start}"

    def test_within_ref_bounds(self, regions):
        for chrom, start, end in regions:
            assert end <= REF_LENGTH, f"Exceeds reference length: {end}"

    def test_variant_count_matches_vcf(self, summary):
        vcf_count = 0
        with open(f"{OUTPUT_DIR}/benchmark_variants.vcf") as f:
            for line in f:
                if not line.startswith("#"):
                    vcf_count += 1
        assert summary["total_variants"] == vcf_count, (
            f"Summary total_variants ({summary['total_variants']}) != "
            f"VCF data lines ({vcf_count})"
        )

    def test_snp_indel_sum(self, summary):
        assert summary["snp_count"] + summary["indel_count"] == summary["total_variants"]

    def test_het_hom_sum(self, summary):
        assert summary["het_count"] + summary["hom_alt_count"] == summary["total_variants"]

    def test_coverage_matches_regions(self, summary):
        regions = read_benchmark_regions(f"{OUTPUT_DIR}/benchmark_regions.bed")
        cov_bp = sum(e - s for _, s, e in regions)
        assert summary["benchmark_coverage_bp"] == cov_bp, (
            f"Summary coverage {summary['benchmark_coverage_bp']} != "
            f"computed from BED {cov_bp}"
        )

    def test_vcf_has_header(self):
        with open(f"{OUTPUT_DIR}/benchmark_variants.vcf") as f:
            first_line = f.readline()
            assert first_line.startswith("##fileformat=VCF"), (
                "Benchmark VCF missing fileformat header"
            )

    def test_vcf_positions_in_benchmark(self):
        regions = read_benchmark_regions(f"{OUTPUT_DIR}/benchmark_regions.bed")
        with open(f"{OUTPUT_DIR}/benchmark_variants.vcf") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.strip().split("\t")
                pos = int(parts[1])
                assert pos_in_regions(pos, regions), (
                    f"VCF variant at position {pos} not within benchmark regions"
                )

    def test_exclusion_stats_valid(self):
        rows = []
        with open(f"{OUTPUT_DIR}/exclusion_stats.tsv") as f:
            header = f.readline().strip().split("\t")
            assert len(header) == 4
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                rows.append({
                    "step_name": parts[0],
                    "bases_excluded": int(parts[1]),
                    "cumulative_excluded": int(parts[2]),
                    "remaining_bases": int(parts[3]),
                })
        assert len(rows) >= 1, "No exclusion steps in stats"
        cumulative = 0
        for row in rows:
            cumulative += row["bases_excluded"]
            assert row["cumulative_excluded"] == cumulative
            assert row["remaining_bases"] == REF_LENGTH - cumulative
