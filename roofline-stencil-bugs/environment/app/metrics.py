"""Performance portability metrics for ECP proxy application evaluation.

Implements the Performance Portability metric Phi (Pennycook, Sewall,
Lee 2016) used to evaluate how well proxy applications perform across
different hardware platforms in the Exascale Computing Project.
"""



def performance_portability(efficiencies):
    """Compute the Performance Portability metric Phi.

    Phi(a, p, H) = |H| / sum(1/e_i for i in H)

    where H is the set of platforms achieving non-zero performance,
    and e_i is the application efficiency on platform i.
    This is the harmonic mean of the efficiencies across platforms.

    A Phi close to 1.0 means consistently high efficiency across all
    platforms. Low Phi indicates poor portability (high variance or
    low efficiency on some platforms).

    Args:
        efficiencies: List of efficiency values (0 < e_i <= 1) for
                      each platform where the app runs.

    Returns:
        Performance portability metric (0 < Phi <= 1), or 0.0 if empty.
    """
    if not efficiencies:
        return 0.0

    valid = [e for e in efficiencies if e > 0]
    if not valid:
        return 0.0

    n = len(valid)
    return sum(valid) / n


def app_efficiency(achieved_perf, peak_perf):
    """Compute application efficiency on a single platform.

    Efficiency e = achieved_performance / peak_performance.

    Args:
        achieved_perf: Measured performance [FLOP/s]
        peak_perf: Theoretical peak performance [FLOP/s]

    Returns:
        Efficiency ratio (0 <= e <= 1)
    """
    if peak_perf <= 0:
        return 0.0
    return achieved_perf / peak_perf


def cross_platform_summary(results):
    """Compute cross-platform performance summary.

    Args:
        results: List of dicts, each with 'achieved' and 'peak' keys [FLOP/s]

    Returns:
        Dict with per-platform efficiencies and overall Phi metric.
    """
    efficiencies = []
    for r in results:
        eff = app_efficiency(r["achieved"], r["peak"])
        efficiencies.append(eff)

    phi = performance_portability(efficiencies)
    return {
        "efficiencies": efficiencies,
        "phi": phi,
    }
