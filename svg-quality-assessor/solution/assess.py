#!/usr/bin/env python3

"""SVG Optimization Quality Assessor.

Evaluates SVG optimizations by rasterizing original/optimized pairs and
computing visual-fidelity and compression metrics.
"""

import argparse
import json
import math
import os
from io import BytesIO

import cairosvg
import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim_metric


RASTER_SIZE = 224


def rasterize_svg(svg_string: str, resolution: int = RASTER_SIZE) -> Image.Image:
    """Rasterize an SVG string to an RGB PIL Image.

    Returns a solid white image on any failure.
    """
    try:
        png_bytes = cairosvg.svg2png(
            bytestring=svg_string.encode("utf-8"),
            output_width=resolution,
            output_height=resolution,
            background_color="white",
        )
        return Image.open(BytesIO(png_bytes)).convert("RGB")
    except Exception:
        return Image.new("RGB", (resolution, resolution), (255, 255, 255))


def compute_mse(img_a: Image.Image, img_b: Image.Image) -> float:
    """Mean Squared Error on float64 [0, 1] pixel arrays."""
    a = np.asarray(img_a, dtype=np.float64) / 255.0
    b = np.asarray(img_b, dtype=np.float64) / 255.0
    return float(np.mean((a - b) ** 2))


def compute_ssim(img_a: Image.Image, img_b: Image.Image) -> float:
    """SSIM on float64 [0, 1] pixel arrays."""
    a = np.asarray(img_a, dtype=np.float64) / 255.0
    b = np.asarray(img_b, dtype=np.float64) / 255.0
    return float(ssim_metric(a, b, win_size=7, channel_axis=-1, data_range=1.0))


def quality_score(ssim_val: float, mse_val: float,
                  compression_ratio: float, target_pct: float) -> float:
    cr = max(compression_ratio, 0.0)
    target_frac = target_pct / 100.0
    if target_frac <= 0:
        target_frac = 1e-10
    return math.sqrt(ssim_val) * (1.0 - math.sqrt(mse_val)) * min(cr / target_frac, 1.0)


def quality_tier(q: float) -> str:
    if q >= 0.8:
        return "excellent"
    if q >= 0.6:
        return "good"
    if q >= 0.4:
        return "fair"
    return "poor"


def assess(input_path: str, output_path: str) -> None:
    with open(input_path, "r", encoding="utf-8") as fh:
        samples = json.load(fh)

    results = []
    for sample in samples:
        orig = sample["original_svg"]
        opt = sample["optimized_svg"]
        target_pct = sample["target_compression_pct"]

        orig_bytes = len(orig.encode("utf-8"))
        opt_bytes = len(opt.encode("utf-8"))

        cr = max(1.0 - opt_bytes / orig_bytes, 0.0)
        met = cr >= target_pct / 100.0

        img_orig = rasterize_svg(orig)
        img_opt = rasterize_svg(opt)

        mse_val = compute_mse(img_orig, img_opt)
        ssim_val = compute_ssim(img_orig, img_opt)

        q = quality_score(ssim_val, mse_val, cr, target_pct)
        tier = quality_tier(q)

        results.append({
            "id": sample["id"],
            "original_size_bytes": orig_bytes,
            "optimized_size_bytes": opt_bytes,
            "compression_ratio": cr,
            "target_compression_pct": target_pct,
            "target_met": met,
            "mse": mse_val,
            "ssim": ssim_val,
            "quality_score": q,
            "quality_tier": tier,
        })

    n = len(results)
    tier_counts = {"excellent": 0, "good": 0, "fair": 0, "poor": 0}
    for r in results:
        tier_counts[r["quality_tier"]] += 1

    aggregate = {
        "mean_mse": sum(r["mse"] for r in results) / n,
        "mean_ssim": sum(r["ssim"] for r in results) / n,
        "mean_compression_ratio": sum(r["compression_ratio"] for r in results) / n,
        "target_hit_rate": sum(1 for r in results if r["target_met"]) / n,
        "tier_counts": tier_counts,
        "total_samples": n,
    }

    output = {"samples": results, "aggregate": aggregate}

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate SVG optimization quality"
    )
    parser.add_argument("--input", required=True, help="Path to samples.json")
    parser.add_argument("--output", required=True, help="Path to output assessment.json")
    args = parser.parse_args()
    assess(args.input, args.output)


if __name__ == "__main__":
    main()
