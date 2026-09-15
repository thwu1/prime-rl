import json
import os
import argparse
from .rasterizer import rasterize
from .metrics import compute_mse, compute_ssim
from .histogram import compute_histogram_distance
from .scorer import compression_ratio, quality_score, quality_tier


def process(input_path, output_path):
    with open(input_path) as f:
        pairs = json.load(f)

    results = []
    for pair in pairs:
        orig_svg = pair["original_svg"]
        opt_svg = pair["optimized_svg"]
        target_pct = pair["target_compression_pct"]

        orig_bytes = len(orig_svg.encode("utf-8"))
        opt_bytes = len(opt_svg.encode("utf-8"))

        cr = compression_ratio(orig_svg, opt_svg)
        target_met = cr >= target_pct / 100.0

        img_orig = rasterize(orig_svg)
        img_opt = rasterize(opt_svg)

        mse = compute_mse(img_orig, img_opt)
        ssim = compute_ssim(img_orig, img_opt)
        hist_dist = compute_histogram_distance(img_orig, img_opt)

        q = quality_score(ssim, mse, hist_dist, cr, target_pct)
        tier = quality_tier(q)

        results.append(
            {
                "id": pair["id"],
                "original_size_bytes": orig_bytes,
                "optimized_size_bytes": opt_bytes,
                "compression_ratio": cr,
                "target_compression_pct": target_pct,
                "target_met": target_met,
                "mse": mse,
                "ssim": ssim,
                "histogram_distance": hist_dist,
                "quality_score": q,
                "quality_tier": tier,
            }
        )

    n = len(results)
    tier_counts = {"excellent": 0, "good": 0, "fair": 0, "poor": 0}
    for r in results:
        tier_counts[r["quality_tier"]] += 1

    aggregate = {
        "mean_mse": sum(r["mse"] for r in results) / n,
        "mean_ssim": sum(r["ssim"] for r in results) / n,
        "mean_histogram_distance": sum(r["histogram_distance"] for r in results) / n,
        "mean_compression_ratio": sum(r["compression_ratio"] for r in results) / n,
        "target_hit_rate": sum(1 for r in results if r["target_met"]) / n,
        "tier_counts": tier_counts,
        "total_samples": n,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({"samples": results, "aggregate": aggregate}, f, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    process(args.input, args.output)
