#!/usr/bin/env python3
"""Cache replacement policy evaluation harness.

Runs all registered policies against all trace files and writes
structured results to /app/results.json.
"""

import json
import os
import sys
import traceback

sys.path.insert(0, '/app')

from simulator.cache import simulate
from simulator.utils import parse_trace, geomean
from policies.lru import LRUPolicy
from policies.srrip import SRRIPPolicy
from policies.drrip import DRRIPPolicy
from policies.opt import BeladyOPT
from policies.ship import SHiPPolicy


def main():
    with open('/app/config.json') as f:
        config = json.load(f)

    num_sets = config['num_sets']
    num_ways = config['num_ways']
    block_size = config['block_size']
    trace_dir = config['trace_dir']

    trace_files = sorted(
        tf for tf in os.listdir(trace_dir)
        if tf.endswith('.txt') and os.path.isfile(os.path.join(trace_dir, tf))
    )

    all_traces = {}
    for tf in trace_files:
        all_traces[tf] = parse_trace(os.path.join(trace_dir, tf))

    results = {"policies": {}}

    policy_factories = [
        ('lru', lambda acc: LRUPolicy(num_sets, num_ways)),
        ('srrip', lambda acc: SRRIPPolicy(num_sets, num_ways)),
        ('drrip', lambda acc: DRRIPPolicy(num_sets, num_ways)),
        ('opt', lambda acc: BeladyOPT(num_sets, num_ways, acc, block_size)),
        ('ship', lambda acc: SHiPPolicy(num_sets, num_ways)),
    ]

    for pname, make_policy in policy_factories:
        pdata = {"per_trace": {}}
        storage = None

        for tf in trace_files:
            accesses = all_traces[tf]
            tname = os.path.splitext(tf)[0]

            try:
                policy = make_policy(accesses)
                hits, misses = simulate(accesses, num_sets, num_ways,
                                        block_size, policy)
            except NotImplementedError as e:
                print(f"Policy '{pname}' not implemented: {e}",
                      file=sys.stderr)
                sys.exit(1)
            except Exception as e:
                print(f"Error in policy '{pname}' on trace '{tname}': {e}",
                      file=sys.stderr)
                traceback.print_exc()
                sys.exit(1)

            total = hits + misses
            mr = misses / total if total > 0 else 0.0
            hr = hits / total if total > 0 else 0.0

            pdata["per_trace"][tname] = {
                "accesses": total,
                "hits": hits,
                "misses": misses,
                "miss_rate": round(mr, 10),
                "hit_rate": round(hr, 10),
            }

            if storage is None:
                try:
                    storage = policy.storage_bytes()
                except (NotImplementedError, Exception):
                    storage = 0

        pdata["storage_bytes"] = storage if storage is not None else 0
        results["policies"][pname] = pdata

    # Compute geometric mean miss-rate reduction (LRU_mr / policy_mr)
    lru_traces = results["policies"]["lru"]["per_trace"]
    for pname, _ in policy_factories:
        pol_traces = results["policies"][pname]["per_trace"]
        ratios = []
        for tname in sorted(pol_traces):
            lru_mr = lru_traces[tname]["miss_rate"]
            pol_mr = pol_traces[tname]["miss_rate"]
            if lru_mr > 0 and pol_mr > 0:
                ratios.append(lru_mr / pol_mr)
            elif lru_mr == 0 and pol_mr == 0:
                ratios.append(1.0)
            elif pol_mr == 0:
                ratios.append(100.0)
            else:
                ratios.append(lru_mr / pol_mr)
        results["policies"][pname]["geomean_miss_rate_reduction"] = round(
            geomean(ratios), 10
        )

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
