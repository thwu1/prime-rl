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
    return math.sqrt(ssim_val) * (1.0 - mse_val) * min(cr / target_frac, 1.0)


def quality_tier(score):
    if score >= 0.8:
        return "excellent"
    if score >= 0.6:
        return "good"
    if score >= 0.4:
        return "fair"
    return "poor"
