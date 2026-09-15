"""Fault localization metrics."""

import math
from typing import Dict, List, Set, Tuple


def ochiai(passed_coverage: List[Set[Tuple[str, int]]],
           failed_coverage: List[Set[Tuple[str, int]]]) -> Dict[Tuple[str, int], float]:
    """Compute Ochiai suspiciousness for each program location.

    ochiai(e) = ef / sqrt(total_failed * (ef + ep))
    where ef = #failing runs covering e, ep = #passing runs covering e.
    """
    all_events: Set[Tuple[str, int]] = set()
    for cov in passed_coverage + failed_coverage:
        all_events |= cov

    total_failed = len(failed_coverage)
    scores: Dict[Tuple[str, int], float] = {}

    for event in all_events:
        ef = sum(1 for cov in failed_coverage if event in cov)
        ep = sum(1 for cov in passed_coverage if event in cov)
        total_with = ef + ep

        if total_failed == 0 or total_with == 0 or ef == 0:
            scores[event] = 0.0
        else:
            scores[event] = ef / math.sqrt(total_failed * total_with)

    return scores


def tarantula(passed_coverage: List[Set[Tuple[str, int]]],
              failed_coverage: List[Set[Tuple[str, int]]]) -> Dict[Tuple[str, int], float]:
    """Compute Tarantula suspiciousness for each program location."""
    all_events: Set[Tuple[str, int]] = set()
    for cov in passed_coverage + failed_coverage:
        all_events |= cov

    tf = len(failed_coverage)
    tp = len(passed_coverage)
    scores: Dict[Tuple[str, int], float] = {}

    for event in all_events:
        ef = sum(1 for cov in failed_coverage if event in cov)
        ep = sum(1 for cov in passed_coverage if event in cov)

        if tf == 0 or ef == 0:
            scores[event] = 0.0
            continue
        fr = ef / tf
        pr = ep / tp if tp > 0 else 0.0
        denom = fr + pr
        scores[event] = fr / denom if denom > 0 else 0.0

    return scores
