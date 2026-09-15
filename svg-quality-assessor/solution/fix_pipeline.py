#!/usr/bin/env python3

"""Fix all bugs in the SVG evaluation pipeline."""

import os

PIPELINE_DIR = "/app/pipeline"

# Bug 1: config.py uses black background instead of white
config_py = '''\
RASTER_SIZE = 256
BACKGROUND_COLOR = "white"
'''

# Bug 2: metrics.py computes MAE (np.abs) instead of MSE (squared)
# Bug 3: metrics.py uses data_range=255.0 instead of 1.0
# Bug 4: metrics.py uses gaussian_weights=False instead of True
metrics_py = '''\
import numpy as np
from skimage.metrics import structural_similarity


def compute_mse(img_a, img_b):
    """Mean Squared Error on float64 [0, 1] pixel arrays."""
    a = np.asarray(img_a, dtype=np.float64) / 255.0
    b = np.asarray(img_b, dtype=np.float64) / 255.0
    return float(np.mean((a - b) ** 2))


def compute_ssim(img_a, img_b):
    """Gaussian-weighted Structural Similarity on float64 [0, 1] arrays."""
    a = np.asarray(img_a, dtype=np.float64) / 255.0
    b = np.asarray(img_b, dtype=np.float64) / 255.0
    return float(
        structural_similarity(
            a, b, win_size=7, channel_axis=-1,
            data_range=1.0, gaussian_weights=True,
        )
    )
'''

# Bug 5: histogram.py operates on RGB instead of HSV
# Bug 6: histogram.py uses Bhattacharyya coefficient (sqrt(h1*h2))
#         instead of histogram intersection (min(h1, h2))
histogram_py = '''\
import numpy as np


def compute_histogram_distance(img_a, img_b):
    """Color histogram intersection distance in HSV space.

    Converts images to HSV, computes L1-normalized histograms for each channel,
    measures histogram intersection similarity with channel weights
    H=0.5, S=0.3, V=0.2, and returns 1 - weighted_similarity.
    """
    hsv_a = np.array(img_a.convert("HSV"))
    hsv_b = np.array(img_b.convert("HSV"))

    weights = [0.5, 0.3, 0.2]
    similarity = 0.0

    for ch in range(3):
        hist_a, _ = np.histogram(hsv_a[:, :, ch].ravel(), bins=32, range=(0, 256))
        hist_b, _ = np.histogram(hsv_b[:, :, ch].ravel(), bins=32, range=(0, 256))

        ha = hist_a.astype(np.float64)
        hb = hist_b.astype(np.float64)

        sum_a = ha.sum()
        sum_b = hb.sum()

        if sum_a > 0:
            ha /= sum_a
        if sum_b > 0:
            hb /= sum_b

        hi = float(np.minimum(ha, hb).sum())
        similarity += weights[ch] * hi

    return float(1.0 - similarity)
'''

# Bug 7: scorer.py uses (1-mse) instead of (1-sqrt(mse))
# Bug 8: scorer.py omits histogram_distance from quality formula
scorer_py = '''\
import math


def compression_ratio(original_svg, optimized_svg):
    orig_bytes = len(original_svg.encode("utf-8"))
    opt_bytes = len(optimized_svg.encode("utf-8"))
    return max(1.0 - opt_bytes / orig_bytes, 0.0)


def quality_score(ssim_val, mse_val, hist_dist, comp_ratio, target_pct):
    target_frac = target_pct / 100.0
    if target_frac <= 0:
        target_frac = 1e-10
    cr = max(comp_ratio, 0.0)
    return (math.sqrt(ssim_val) * (1.0 - math.sqrt(mse_val))
            * (1.0 - 0.3 * hist_dist) * min(cr / target_frac, 1.0))


def quality_tier(score):
    if score >= 0.8:
        return "excellent"
    if score >= 0.6:
        return "good"
    if score >= 0.4:
        return "fair"
    return "poor"
'''

# Bug 9: run.py sorts results alphabetically instead of preserving input order
run_py = '''\
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
'''

fixes = {
    "config.py": config_py,
    "metrics.py": metrics_py,
    "histogram.py": histogram_py,
    "scorer.py": scorer_py,
    "run.py": run_py,
}

for filename, content in fixes.items():
    path = os.path.join(PIPELINE_DIR, filename)
    with open(path, "w") as f:
        f.write(content)
    print(f"Fixed {path}")

print("All pipeline bugs fixed.")
