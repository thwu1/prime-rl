"""
Gated scoring system for kernel optimization evaluation.

Scoring rules:
- 0 points if compilation fails
- +20 points for compilation
- +100 points for correctness (requires compilation)
- +speedup_ratio * 100 points for performance (requires both)
"""


def resolve_speedup_ratio(speedup_ratio, base_time, opt_time):
    """
    Resolve the speedup ratio to use for scoring.

    Prefer an explicit positive speedup_ratio. Fall back to
    base_time / opt_time if both are positive. Otherwise return 0.0.
    """
    if isinstance(speedup_ratio, (int, float)) and speedup_ratio > 0:
        return float(speedup_ratio)
    if isinstance(base_time, (int, float)) and isinstance(opt_time, (int, float)):
        if base_time > 0 and opt_time > 0:
            return base_time / opt_time
    return 0.0


def score(pass_compilation, pass_correctness, base_time, opt_time, speedup_ratio=0.0):
    """
    Calculate gated optimization task score.

    Returns:
        0.0  if compilation failed
        20.0 if only compilation passed
        120.0 if compilation + correctness passed (no speedup data)
        120.0 + speedup*100 if all passed with performance data
    """
    total = 0.0

    if not pass_compilation:
        return 0.0

    total += 20.0

    if not pass_correctness:
        return total

    total += 100.0

    effective_speedup = resolve_speedup_ratio(speedup_ratio, base_time, opt_time)
    if effective_speedup > 0:
        total += effective_speedup * 100.0

    return total
