
"""
Benchmark Evaluation Pipeline

Implements multi-metric image scoring, tournament selection,
bootstrap confidence intervals, and full benchmark evaluation
with CLI interface, TOML configuration, and SQLite caching.
"""

import os
import sys
import json
import argparse
import sqlite3
import tomllib

import numpy as np
from scipy.stats import norm
from PIL import Image as PILImage


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _gaussian_kernel(size, sigma):
    """Create a normalized 2D Gaussian kernel."""
    coords = np.arange(size, dtype=np.float64) - (size - 1) / 2.0
    g = np.exp(-(coords ** 2) / (2.0 * sigma ** 2))
    kernel = np.outer(g, g)
    kernel /= kernel.sum()
    return kernel


def _convolve2d_valid(img, kernel):
    """2D convolution in valid mode using numpy stride tricks."""
    img = np.ascontiguousarray(img, dtype=np.float64)
    kh, kw = kernel.shape
    ih, iw = img.shape
    oh = ih - kh + 1
    ow = iw - kw + 1
    if oh <= 0 or ow <= 0:
        return np.array([[np.mean(img)]])
    shape = (oh, ow, kh, kw)
    strides = (img.strides[0], img.strides[1], img.strides[0], img.strides[1])
    windows = np.lib.stride_tricks.as_strided(img, shape=shape, strides=strides)
    return np.einsum('ijkl,kl->ij', windows, kernel)


def _ensure_same_size(img1, img2):
    """Resize img2 to match img1 dimensions if they differ."""
    if img1.shape[0] != img2.shape[0] or img1.shape[1] != img2.shape[1]:
        pil_img2 = PILImage.fromarray(img2.astype(np.uint8))
        pil_img2 = pil_img2.resize(
            (img1.shape[1], img1.shape[0]), PILImage.BILINEAR
        )
        img2 = np.array(pil_img2)
    return img2


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------

def photometric_loss(img1, img2):
    """Compute pixel-level distance between two images."""
    img2 = _ensure_same_size(img1, img2)
    img1_f = img1.astype(np.float64) / 255.0
    img2_f = img2.astype(np.float64) / 255.0
    img1_rgb = img1_f[:, :, :3]
    img2_rgb = img2_f[:, :, :3]
    return float(np.mean((img1_rgb - img2_rgb) ** 2))


def ssim_score(img1, img2, window_size=11, K1=0.01, K2=0.03):
    """Compute structural image similarity."""
    img2 = _ensure_same_size(img1, img2)
    img1_f = img1.astype(np.float64) / 255.0
    img2_f = img2.astype(np.float64) / 255.0

    L = 1.0
    C1 = (K1 * L) ** 2
    C2 = (K2 * L) ** 2

    kernel = _gaussian_kernel(window_size, 1.5)

    n_channels = min(img1_f.shape[2] if img1_f.ndim > 2 else 1, 3)
    ssim_per_channel = []

    for c in range(n_channels):
        ch1 = img1_f[:, :, c] if img1_f.ndim > 2 else img1_f
        ch2 = img2_f[:, :, c] if img2_f.ndim > 2 else img2_f

        mu1 = _convolve2d_valid(ch1, kernel)
        mu2 = _convolve2d_valid(ch2, kernel)

        mu1_sq = mu1 * mu1
        mu2_sq = mu2 * mu2
        mu1_mu2 = mu1 * mu2

        sigma1_sq = np.maximum(0, _convolve2d_valid(ch1 * ch1, kernel) - mu1_sq)
        sigma2_sq = np.maximum(0, _convolve2d_valid(ch2 * ch2, kernel) - mu2_sq)
        sigma12 = _convolve2d_valid(ch1 * ch2, kernel) - mu1_mu2

        numerator = (2.0 * mu1_mu2 + C1) * (2.0 * sigma12 + C2)
        denominator = (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)

        ssim_map = numerator / denominator
        ssim_per_channel.append(float(np.mean(ssim_map)))

    return float(np.mean(ssim_per_channel))


def composite_distance(img1, img2, alpha=0.5, beta=0.5):
    """Weighted combination of distance metrics."""
    pl = photometric_loss(img1, img2)
    ss = ssim_score(img1, img2)
    return alpha * pl + beta * (1.0 - ss)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def multi_view_aggregate(per_view_scores):
    """Average metrics across views, ignoring None entries."""
    pl_vals = [s["pl"] for s in per_view_scores if s.get("pl") is not None]
    ssim_vals = [s["ssim"] for s in per_view_scores if s.get("ssim") is not None]
    return {
        "avg_pl": float(np.mean(pl_vals)) if pl_vals else None,
        "avg_ssim": float(np.mean(ssim_vals)) if ssim_vals else None,
    }


def trimmed_mean(values, trim_fraction=0.1):
    """Compute trimmed mean."""
    if not values:
        return 0.0
    vals = sorted(values)
    n = len(vals)
    k = int(n * trim_fraction)
    if 2 * k >= n:
        return float(np.mean(vals))
    trimmed = vals[k:n - k] if k > 0 else vals
    return float(np.mean(trimmed))


def bca_bootstrap_ci(values, confidence=0.95, n_bootstrap=10000, seed=42):
    """Bootstrap confidence interval with bias-correction and acceleration."""
    values = list(values)
    if len(values) == 0:
        return (0.0, 0.0)
    if len(values) == 1:
        return (float(values[0]), float(values[0]))

    values = np.array(values, dtype=np.float64)
    rng = np.random.RandomState(seed)
    observed = np.mean(values)
    n = len(values)

    boot_indices = rng.randint(0, n, size=(n_bootstrap, n))
    boot_means = np.mean(values[boot_indices], axis=1)

    prop_less = np.mean(boot_means < observed)
    prop_less = np.clip(prop_less, 1.0 / (2 * n_bootstrap), 1.0 - 1.0 / (2 * n_bootstrap))
    z0 = norm.ppf(prop_less)

    jackknife_values = np.array([
        np.mean(np.concatenate([values[:i], values[i + 1:]]))
        for i in range(n)
    ])
    theta_bar = np.mean(jackknife_values)
    diffs = theta_bar - jackknife_values
    denom_sq = np.sum(diffs ** 2)

    if denom_sq == 0:
        a = 0.0
    else:
        a = np.sum(diffs ** 3) / (6.0 * denom_sq ** 1.5)

    alpha_lo = (1.0 - confidence) / 2.0
    alpha_hi = 1.0 - alpha_lo
    z_lo = norm.ppf(alpha_lo)
    z_hi = norm.ppf(alpha_hi)

    def _adjust(z_alpha):
        d = 1.0 - a * (z0 + z_alpha)
        if abs(d) < 1e-10:
            return 0.5
        return norm.cdf(z0 + (z0 + z_alpha) / d)

    adj_lo = _adjust(z_lo)
    adj_hi = _adjust(z_hi)

    lower = float(np.percentile(boot_means, adj_lo * 100))
    upper = float(np.percentile(boot_means, adj_hi * 100))

    return (lower, upper)


# ---------------------------------------------------------------------------
# Swiss Tournament
# ---------------------------------------------------------------------------

def swiss_tournament(candidates, target, n_rounds, metric_fn, seed=42):
    """Swiss-system tournament selection with tiebreaking."""
    n = len(candidates)
    if n == 0:
        return []
    if n == 1:
        return [(0, 0.0, 0.0)]

    scores = [0.0] * n
    opponents = [[] for _ in range(n)]

    distances = [metric_fn(candidates[i], target) for i in range(n)]

    for _ in range(n_rounds):
        ranking = sorted(range(n), key=lambda i: (-scores[i], i))

        paired = [False] * n
        matches = []

        for idx in range(len(ranking)):
            ci = ranking[idx]
            if paired[ci]:
                continue
            for jdx in range(idx + 1, len(ranking)):
                cj = ranking[jdx]
                if paired[cj]:
                    continue
                if cj in opponents[ci]:
                    continue
                matches.append((ci, cj))
                paired[ci] = True
                paired[cj] = True
                break

        for idx in reversed(range(len(ranking))):
            ci = ranking[idx]
            if not paired[ci]:
                scores[ci] += 1.0
                break

        for ci, cj in matches:
            if distances[ci] < distances[cj] or (distances[ci] == distances[cj] and ci < cj):
                scores[ci] += 1.0
            else:
                scores[cj] += 1.0
            opponents[ci].append(cj)
            opponents[cj].append(ci)

    buchholz = [sum(scores[opp] for opp in opponents[i]) for i in range(n)]
    ranking = sorted(range(n), key=lambda i: (-scores[i], -buchholz[i], i))

    return [(i, scores[i], buchholz[i]) for i in ranking]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config(path):
    """Load evaluation parameters from a TOML configuration file."""
    with open(path, "rb") as f:
        return tomllib.load(f)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def init_cache(db_path="/app/cache.db"):
    """Initialize the SQLite metric cache database."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS metric_cache ("
        "goal_path TEXT, "
        "candidate_path TEXT, "
        "photometric_loss REAL, "
        "ssim_score REAL, "
        "PRIMARY KEY (goal_path, candidate_path))"
    )
    conn.commit()
    return conn


def _cache_lookup(conn, goal_path, candidate_path):
    """Look up cached metrics for an image pair."""
    cursor = conn.execute(
        "SELECT photometric_loss, ssim_score FROM metric_cache "
        "WHERE goal_path = ? AND candidate_path = ?",
        (goal_path, candidate_path)
    )
    return cursor.fetchone()


def _cache_store(conn, goal_path, candidate_path, pl, ssim_val):
    """Store computed metrics in the cache."""
    conn.execute(
        "INSERT OR REPLACE INTO metric_cache "
        "(goal_path, candidate_path, photometric_loss, ssim_score) "
        "VALUES (?, ?, ?, ?)",
        (goal_path, candidate_path, pl, ssim_val)
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

def evaluate_benchmark(data_dir, config=None, cache_db=None):
    """Process a benchmark results directory and produce an evaluation report."""
    if config is None:
        config = {}

    alpha = config.get("metrics", {}).get("alpha", 0.5)
    beta = config.get("metrics", {}).get("beta", 0.5)
    trim_frac = config.get("aggregation", {}).get("trim_fraction", 0.1)
    ci_confidence = config.get("bootstrap", {}).get("confidence", 0.95)
    ci_n_bootstrap = config.get("bootstrap", {}).get("n_bootstrap", 10000)
    ci_seed = config.get("bootstrap", {}).get("seed", 42)

    cache_conn = None
    if cache_db:
        cache_conn = init_cache(cache_db)

    tasks_result = {}
    task_distances_all = {}

    task_dirs = sorted(
        [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d))]
    )

    for task_name in task_dirs:
        task_path = os.path.join(data_dir, task_name)
        instances = {}
        inst_best_dists = []

        inst_dirs = sorted(
            [d for d in os.listdir(task_path)
             if os.path.isdir(os.path.join(task_path, d))]
        )

        for inst_name in inst_dirs:
            inst_path = os.path.join(task_path, inst_name)
            goal_dir = os.path.join(inst_path, "goal")
            if not os.path.isdir(goal_dir):
                continue

            goal_views = sorted(
                [f for f in os.listdir(goal_dir) if f.lower().endswith(".png")]
            )
            if not goal_views:
                continue

            cand_dirs = sorted(
                [d for d in os.listdir(inst_path)
                 if d.startswith("candidate_")
                 and os.path.isdir(os.path.join(inst_path, d))]
            )

            per_candidate = {}
            for cand_dir_name in cand_dirs:
                cand_idx = cand_dir_name.split("_")[1]
                cand_path = os.path.join(inst_path, cand_dir_name)

                view_scores = []
                for vf in goal_views:
                    goal_img_path = os.path.join(goal_dir, vf)
                    cand_img_path = os.path.join(cand_path, vf)

                    if not os.path.exists(cand_img_path):
                        view_scores.append({"pl": None, "ssim": None})
                        continue

                    cached = None
                    if cache_conn:
                        cached = _cache_lookup(
                            cache_conn, goal_img_path, cand_img_path
                        )

                    if cached:
                        pl, ss = cached
                    else:
                        gi = np.array(
                            PILImage.open(goal_img_path).convert("RGB")
                        )
                        ci = np.array(
                            PILImage.open(cand_img_path).convert("RGB")
                        )
                        pl = photometric_loss(gi, ci)
                        ss = ssim_score(gi, ci)
                        if cache_conn:
                            _cache_store(
                                cache_conn, goal_img_path, cand_img_path, pl, ss
                            )

                    view_scores.append({"pl": pl, "ssim": ss})

                agg = multi_view_aggregate(view_scores)
                if agg["avg_pl"] is not None and agg["avg_ssim"] is not None:
                    comp = alpha * agg["avg_pl"] + beta * (1.0 - agg["avg_ssim"])
                else:
                    comp = float("inf")

                per_candidate[cand_idx] = {
                    "avg_pl": agg["avg_pl"],
                    "avg_ssim": agg["avg_ssim"],
                    "composite": comp,
                }

            if per_candidate:
                best_cand = min(
                    per_candidate.keys(),
                    key=lambda k: per_candidate[k]["composite"]
                )
                instances[inst_name] = {
                    "best_candidate": int(best_cand),
                    "best_composite_distance": per_candidate[best_cand]["composite"],
                    "per_candidate": per_candidate,
                }
                inst_best_dists.append(per_candidate[best_cand]["composite"])

        if inst_best_dists:
            tm = trimmed_mean(inst_best_dists, trim_frac)
            ci = bca_bootstrap_ci(
                inst_best_dists,
                confidence=ci_confidence,
                n_bootstrap=ci_n_bootstrap,
                seed=ci_seed,
            )
            tasks_result[task_name] = {
                "instances": instances,
                "trimmed_mean_distance": tm,
                "ci_lower": ci[0],
                "ci_upper": ci[1],
            }
            task_distances_all[task_name] = inst_best_dists

    task_means = [
        tasks_result[t]["trimmed_mean_distance"]
        for t in tasks_result
        if tasks_result[t]["trimmed_mean_distance"] > 0
    ]
    if task_means:
        harmonic = len(task_means) / sum(1.0 / m for m in task_means)
    else:
        harmonic = 0.0

    all_dists = [d for dlist in task_distances_all.values() for d in dlist]
    if all_dists:
        oci = bca_bootstrap_ci(
            all_dists,
            confidence=ci_confidence,
            n_bootstrap=ci_n_bootstrap,
            seed=ci_seed,
        )
    else:
        oci = (0.0, 0.0)

    if cache_conn:
        cache_conn.close()

    return {
        "tasks": tasks_result,
        "overall": {
            "harmonic_mean_distance": harmonic,
            "ci_lower": oci[0],
            "ci_upper": oci[1],
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark evaluation pipeline"
    )
    parser.add_argument(
        "--data-dir", required=True,
        help="Path to benchmark data directory"
    )
    parser.add_argument(
        "--output", required=True,
        help="Path to write JSON evaluation report"
    )
    parser.add_argument(
        "--config", default="/app/config.toml",
        help="Path to TOML config file"
    )
    parser.add_argument(
        "--cache-db", default=None,
        help="Path to SQLite cache database"
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    report = evaluate_benchmark(
        args.data_dir, config=cfg, cache_db=args.cache_db
    )

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)
