#!/usr/bin/env python3
"""
Optimal Touring Game Engine

A tourist visits sites on a city grid, collecting value rewards.
Each site has a grid position, visit duration, reward value, and
visiting time window. Travel between sites takes Manhattan distance
minutes. The engine generates deterministic instances from seeds
and evaluates proposed tours for validity and total value.

"""

import json
import random
from typing import Dict, List, Tuple


def generate_instance(seed: int, num_sites: int = 60) -> Dict[int, dict]:
    """
    Generate a deterministic touring instance.

    Args:
        seed: Random seed for reproducibility.
        num_sites: Number of tourist sites to generate.

    Returns:
        Dictionary mapping site_id (int, 1-indexed) to a property dict:
        {
            'avenue': int (0-100),
            'street': int (0-100),
            'duration': int (1-200, minutes required at the site),
            'value': int (1-200, reward for completing the visit),
            'begin_hour': int (0-12, site opens at begin_hour * 60 minutes),
            'end_hour': int (begin_hour+1 to 21, site closes at end_hour * 60 minutes)
        }
    """
    rng = random.Random(seed)
    sites = {}
    for i in range(1, num_sites + 1):
        begin_hour = rng.randint(0, 12)
        end_hour = rng.randint(begin_hour + 1, 21)
        sites[i] = {
            'avenue': rng.randint(0, 100),
            'street': rng.randint(0, 100),
            'duration': rng.randint(1, 200),
            'value': rng.randint(1, 200),
            'begin_hour': begin_hour,
            'end_hour': end_hour,
        }
    return sites


def manhattan_distance(a: dict, b: dict) -> int:
    """Compute Manhattan distance between two sites."""
    return abs(a['avenue'] - b['avenue']) + abs(a['street'] - b['street'])


def evaluate_tour(sites: Dict[int, dict], tour: List[int]) -> Tuple[int, bool, str]:
    """
    Evaluate a proposed tour for validity and total value.

    Args:
        sites: Instance data from generate_instance().
        tour: Ordered list of site IDs to visit.

    Returns:
        (total_value, is_valid, error_message)

    Tour evaluation rules:
    - The tour begins at the first site's opening time (begin_hour * 60).
    - The tourist spends exactly 'duration' minutes at each site.
    - Travel to the next site takes manhattan_distance minutes.
    - For each site after the first, the arrival time must be at or after
      the site's opening time (begin_hour * 60). Early arrivals with
      waiting are NOT permitted.
    - The visit must complete before closing: arrival + duration <= end_hour * 60.
    - Each site may be visited at most once.
    - Any constraint violation invalidates the entire tour (value = 0).
    """
    if not tour:
        return 0, True, ""

    if len(set(tour)) != len(tour):
        return 0, False, "Duplicate sites in tour"

    for sid in tour:
        if sid not in sites:
            return 0, False, f"Site {sid} does not exist"

    total_value = 0
    current_time = None
    prev_site = None

    for sid in tour:
        site = sites[sid]

        if current_time is None:
            # First site: start at its opening time
            current_time = site['begin_hour'] * 60
            if current_time + site['duration'] > site['end_hour'] * 60:
                return 0, False, (
                    f"Cannot complete visit at first site {sid}: "
                    f"start={current_time}, duration={site['duration']}, "
                    f"closes={site['end_hour'] * 60}"
                )
            total_value += site['value']
            current_time += site['duration']
            prev_site = site
            continue

        # Compute travel time and arrival
        tt = manhattan_distance(prev_site, site)
        arrival = current_time + tt

        # Must not arrive before site opens
        if arrival < site['begin_hour'] * 60:
            return 0, False, (
                f"Arrived too early at site {sid}: "
                f"arrival={arrival}, opens={site['begin_hour'] * 60}"
            )

        # Must complete visit before site closes
        if arrival + site['duration'] > site['end_hour'] * 60:
            return 0, False, (
                f"Cannot complete visit at site {sid}: "
                f"arrival={arrival}, duration={site['duration']}, "
                f"closes={site['end_hour'] * 60}"
            )

        current_time = arrival + site['duration']
        total_value += site['value']
        prev_site = site

    return total_value, True, ""


if __name__ == '__main__':
    import sys
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    num_sites = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    inst = generate_instance(seed, num_sites)
    print(f"Instance: {num_sites} sites, seed={seed}")
    print(f"{'ID':>4} {'Ave':>4} {'St':>4} {'Dur':>5} {'Val':>5} {'Open':>5} {'Close':>6}")
    for sid in sorted(inst.keys()):
        p = inst[sid]
        print(f"{sid:>4} {p['avenue']:>4} {p['street']:>4} {p['duration']:>5} "
              f"{p['value']:>5} {p['begin_hour']*60:>5} {p['end_hour']*60:>6}")
