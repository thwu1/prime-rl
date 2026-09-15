#!/usr/bin/env python3
"""Solution: Evaluate benchmark strategies, identify weaknesses, design optimized config."""

import gzip
import json
import os
import subprocess


def read_bed(filepath):
    intervals = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            intervals.append((parts[0], int(parts[1]), int(parts[2])))
    return intervals


def filter_by_min_length(intervals, min_length):
    if min_length <= 0:
        return intervals
    return [(c, s, e) for c, s, e in intervals if (e - s) >= min_length]


def apply_slop(intervals, slop_bp, ref_length):
    if slop_bp <= 0:
        return intervals
    return [
        (c, max(0, s - slop_bp), min(ref_length, e + slop_bp))
        for c, s, e in intervals
    ]


def merge_intervals(intervals, merge_distance=0):
    if not intervals:
        return []
    sorted_ivls = sorted(intervals, key=lambda x: (x[0], x[1]))
    merged = [list(sorted_ivls[0])]
    for chrom, start, end in sorted_ivls[1:]:
        prev = merged[-1]
        if chrom == prev[0] and start <= prev[2] + merge_distance:
            prev[2] = max(prev[2], end)
        else:
            merged.append([chrom, start, end])
    return [(c, s, e) for c, s, e in merged]


def subtract_intervals(benchmark, to_remove):
    if not to_remove:
        return benchmark[:]
    result = []
    to_remove_sorted = sorted(to_remove, key=lambda x: x[1])
    for chrom, b_start, b_end in benchmark:
        current_start = b_start
        for _, r_start, r_end in to_remove_sorted:
            if r_end <= current_start:
                continue
            if r_start >= b_end:
                break
            if r_start > current_start:
                result.append((chrom, current_start, r_start))
            current_start = max(current_start, r_end)
        if current_start < b_end:
            result.append((chrom, current_start, b_end))
    return result


def coverage(intervals):
    return sum(end - start for _, start, end in intervals)


def pos_in_intervals(pos_0based, intervals):
    for _, start, end in intervals:
        if start <= pos_0based < end:
            return True
        if start > pos_0based:
            break
    return False


def get_all_vcf_positions(vcf_path):
    positions = []
    opener = gzip.open(vcf_path, "rt") if vcf_path.endswith(".gz") else open(vcf_path)
    with opener as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.strip().split("\t")
            positions.append(int(parts[1]))
    return positions


def run_pipeline_and_get_regions(config_path, output_dir):
    subprocess.run(
        ["python3", "/app/pipeline.py", config_path, output_dir],
        check=True, capture_output=True
    )
    return read_bed(os.path.join(output_dir, "benchmark_regions.bed"))


def compute_metrics(regions, variant_positions, true_set, false_set, ref_length):
    retained = set()
    for p in variant_positions:
        if pos_in_intervals(p - 1, regions):
            retained.add(p)

    tp_retained = len(retained & true_set)
    fp_excluded = len(false_set - retained)
    sens = tp_retained / len(true_set) if true_set else 0
    spec = fp_excluded / len(false_set) if false_set else 0
    cov = coverage(regions) / ref_length
    composite = 0.4 * sens + 0.4 * spec + 0.2 * cov

    return {
        "sensitivity": round(sens, 4),
        "specificity": round(spec, 4),
        "coverage_fraction": round(cov, 4),
        "composite_score": round(composite, 4),
        "retained_variants": len(retained),
        "excluded_variants": len(variant_positions) - len(retained),
    }


def step_by_step_impact(config, variant_positions, true_set, false_set):
    ref_name = config["reference_name"]
    ref_length = config["reference_length"]
    benchmark = [(ref_name, 0, ref_length)]
    impact = []

    for step in config["steps"]:
        before_retained = set()
        for p in variant_positions:
            if pos_in_intervals(p - 1, benchmark):
                before_retained.add(p)

        intervals = read_bed(step["file"])
        intervals = filter_by_min_length(intervals, step.get("min_length", 0))
        intervals = apply_slop(intervals, step.get("slop_bp", 0), ref_length)
        intervals = merge_intervals(intervals, step.get("merge_distance", 0))
        benchmark = subtract_intervals(benchmark, intervals)

        after_retained = set()
        for p in variant_positions:
            if pos_in_intervals(p - 1, benchmark):
                after_retained.add(p)

        lost = before_retained - after_retained
        true_lost = sorted(lost & true_set)
        false_lost = sorted(lost & false_set)

        impact.append({
            "step_name": step["name"],
            "validated_true_lost": len(true_lost),
            "validated_false_excluded": len(false_lost),
            "true_positions_lost": true_lost,
            "false_positions_excluded": false_lost,
        })

    return impact


def main():
    os.chdir("/app")

    # Load truth set
    with open("truth_set.json") as f:
        truth = json.load(f)
    true_set = {v["position"] for v in truth["variants"] if v["label"] == "validated_true"}
    false_set = {v["position"] for v in truth["variants"] if v["label"] == "validated_false"}
    ref_length = truth["reference_length"]

    # Get all variant positions
    variant_positions = get_all_vcf_positions("calls.vcf.gz")

    # Step 1: Evaluate each strategy
    strategies = {}
    for name in ["strategy_a", "strategy_b", "strategy_c"]:
        config_path = f"strategies/{name}.json"
        out_dir = f"/tmp/{name}_output"
        regions = run_pipeline_and_get_regions(config_path, out_dir)
        metrics = compute_metrics(regions, variant_positions, true_set, false_set, ref_length)
        strategies[name] = metrics

    # Rank by composite score
    ranked = sorted(strategies.keys(), key=lambda k: -strategies[k]["composite_score"])

    evaluation = dict(strategies)
    evaluation["ranking"] = ranked
    evaluation["best_strategy"] = ranked[0]

    with open("evaluation.json", "w") as f:
        json.dump(evaluation, f, indent=2)
        f.write("\n")

    print(f"Evaluation complete. Ranking: {ranked}")
    for name in ranked:
        m = strategies[name]
        print(f"  {name}: composite={m['composite_score']}, "
              f"sens={m['sensitivity']}, spec={m['specificity']}, "
              f"cov={m['coverage_fraction']}")

    # Step 2: Per-step impact analysis for best strategy
    best = ranked[0]
    with open(f"strategies/{best}.json") as f:
        best_config = json.load(f)

    impact = step_by_step_impact(best_config, variant_positions, true_set, false_set)

    # Identify weakest step: most true variants lost with fewest false variants excluded
    weakest = None
    worst_ratio = -1
    for step_info in impact:
        if step_info["validated_true_lost"] > 0:
            ratio = step_info["validated_true_lost"] / max(1, step_info["validated_false_excluded"])
            if ratio > worst_ratio:
                worst_ratio = ratio
                weakest = step_info["step_name"]

    if weakest is None:
        weakest = "none"
        reason = "No step excludes validated_true variants"
    else:
        for s in impact:
            if s["step_name"] == weakest:
                reason = (
                    f"Excludes {s['validated_true_lost']} validated_true variant(s) "
                    f"at positions {s['true_positions_lost']} while only excluding "
                    f"{s['validated_false_excluded']} validated_false variant(s). "
                    f"This step harms sensitivity without improving specificity."
                )

    step_impact = {
        "analyzed_strategy": best,
        "steps": impact,
        "weakest_step": weakest,
        "weakest_step_reason": reason,
    }

    with open("step_impact.json", "w") as f:
        json.dump(step_impact, f, indent=2)
        f.write("\n")

    print(f"\nWeakest step: {weakest}")
    print(f"Reason: {reason}")

    # Step 3: Design optimized config
    # The weakest step (tandem_repeats) excludes true variants without excluding
    # any false variants. Fix: increase min_length to skip the small TRs that
    # contain validated_true variants (both are 1000bp, so min_length > 1000).
    optimized = dict(best_config)
    optimized_steps = []
    for step in best_config["steps"]:
        s = dict(step)
        if s["name"] == "tandem_repeats":
            s["min_length"] = 1001
        optimized_steps.append(s)
    optimized["steps"] = optimized_steps

    with open("optimized_config.json", "w") as f:
        json.dump(optimized, f, indent=2)
        f.write("\n")

    # Step 4: Run pipeline with optimized config
    subprocess.run(
        ["python3", "/app/pipeline.py", "optimized_config.json", "output"],
        check=True,
    )

    # Verify optimized quality
    opt_regions = read_bed("output/benchmark_regions.bed")
    opt_metrics = compute_metrics(opt_regions, variant_positions, true_set, false_set, ref_length)
    print(f"\nOptimized benchmark: composite={opt_metrics['composite_score']}, "
          f"sens={opt_metrics['sensitivity']}, spec={opt_metrics['specificity']}, "
          f"cov={opt_metrics['coverage_fraction']}, "
          f"retained={opt_metrics['retained_variants']}")


if __name__ == "__main__":
    main()
