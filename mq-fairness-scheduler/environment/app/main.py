"""Multi-queue fair queuing simulation runner.

Usage: python3 main.py <scenario.json> <output.json>

"""

import sys
import json
import os
from traffic import TrafficGenerator
from scheduler import MultiQueueScheduler, compute_max_min_fair_rates
from metrics import jains_fairness_index, compute_throughputs


def run_scenario(scenario_path, output_path):
    gen = TrafficGenerator(scenario_path)

    num_queues = gen.config['num_queues']
    scheduler = MultiQueueScheduler(
        num_queues=num_queues,
        global_rate=gen.global_rate,
        burst_size=gen.global_rate * 0.01  # 10ms burst
    )

    dt = 0.001  # 1ms time steps
    send_log = []
    current_flows = set()

    t = 0.0
    while t < gen.duration_sec:
        active = gen.get_active_flows(t)
        active_ids = {f['id'] for f in active}

        # Add new flows
        for f in active:
            if f['id'] not in current_flows:
                scheduler.assign_flow(f['id'], f['queue'], f.get('weight', 1.0))
                current_flows.add(f['id'])

        # Remove departed flows
        for fid in list(current_flows - active_ids):
            scheduler.remove_flow(fid)
            current_flows.discard(fid)

        # Build demand map (bytes this time step)
        demands = {}
        for f in active:
            demand_bps = gen.get_flow_demand(f, t)
            if demand_bps == float('inf'):
                demands[f['id']] = float('inf')
            else:
                demands[f['id']] = demand_bps * dt

        # Schedule
        allocations = scheduler.schedule(demands, dt, t)

        for flow_id, bytes_sent in allocations.items():
            if bytes_sent > 0:
                send_log.append((t, flow_id, bytes_sent))

        t = round(t + dt, 6)  # Avoid float accumulation errors

    # Compute metrics
    throughputs = compute_throughputs(send_log, gen.duration_sec)

    weights = {}
    for f in gen.flows:
        weights[f['id']] = f.get('weight', 1.0)

    sorted_ids = sorted(throughputs.keys())
    active_weights = [weights[fid] for fid in sorted_ids]
    active_throughputs = [throughputs[fid] for fid in sorted_ids]

    jfi = jains_fairness_index(active_throughputs, active_weights)
    total_throughput = sum(throughputs.values())

    results = {
        'throughputs': {str(k): v for k, v in throughputs.items()},
        'jains_fairness_index': jfi,
        'total_throughput_bytes_per_sec': total_throughput,
        'global_rate_bytes_per_sec': gen.global_rate,
        'utilization': total_throughput / gen.global_rate,
    }

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <scenario.json> <output.json>", file=sys.stderr)
        sys.exit(1)

    results = run_scenario(sys.argv[1], sys.argv[2])
    print(f"JFI: {results['jains_fairness_index']:.6f}")
    print(f"Utilization: {results['utilization']:.4f}")
    print(f"Total throughput: {results['total_throughput_bytes_per_sec']:.0f} bytes/sec")
