
import statistics
from typing import Dict, List
from request import Request


def compute_metrics(completed: List[Request], memory=None) -> Dict:
    """Compute latency, SLO, and memory metrics from completed requests."""
    if not completed:
        return {"num_completed": 0}

    jcts = sorted(r.jct for r in completed)
    n = len(jcts)

    # Per-tier SLO compliance
    slo_met_total = sum(1 for r in completed if r.slo_met)
    slo_by_tier = {}
    for tier in [0, 1, 2]:
        tier_reqs = [r for r in completed if r.slo_tier == tier]
        if tier_reqs:
            met = sum(1 for r in tier_reqs if r.slo_met)
            slo_by_tier[f"slo_tier_{tier}_compliance"] = round(met / len(tier_reqs), 4)
            slo_by_tier[f"slo_tier_{tier}_count"] = len(tier_reqs)

    result = {
        "num_completed": n,
        "avg_jct": statistics.mean(jcts),
        "median_jct": statistics.median(jcts),
        "p95_jct": jcts[min(int(n * 0.95), n - 1)],
        "p99_jct": jcts[min(int(n * 0.99), n - 1)],
        "max_jct": jcts[-1],
        "min_jct": jcts[0],
        "total_preemptions": sum(r.preemption_count for r in completed),
        "slo_compliance": round(slo_met_total / n, 4),
        **slo_by_tier,
    }

    if memory:
        result["avg_fragmentation"] = round(memory.avg_fragmentation, 4)
        result["total_page_allocs"] = memory.total_page_allocs
        result["total_page_evictions"] = memory.total_page_evictions
        result["total_page_loads"] = memory.total_page_loads

    return result
