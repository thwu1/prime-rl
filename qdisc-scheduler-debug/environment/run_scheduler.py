#!/usr/bin/env python3
"""Run the CAKE-inspired packet scheduler simulation."""
import json
import sys
from collections import Counter
from scheduler import load_trace, save_output, CAKESimulator


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else '/app/config.json'
    trace_path = sys.argv[2] if len(sys.argv) > 2 else '/app/trace.csv'
    output_path = sys.argv[3] if len(sys.argv) > 3 else '/app/output.csv'

    with open(config_path) as f:
        config = json.load(f)

    print(f"Config: rate={config['rate_mbps']}Mbps, "
          f"queues={config.get('num_queues', 64)}, "
          f"quantum={config.get('quantum', 1500)}", file=sys.stderr)

    packets = load_trace(trace_path)
    print(f"Loaded {len(packets)} packets from {trace_path}", file=sys.stderr)

    sim = CAKESimulator(config)
    results = sim.run(packets)
    save_output(results, output_path)

    print(f"\nResults: {len(results)} packets scheduled", file=sys.stderr)

    if results:
        total_bytes = sum(r['size_bytes'] for r in results)
        duration_ns = results[-1]['dequeue_ns'] - results[0]['dequeue_ns']
        if duration_ns > 0:
            rate_mbps = total_bytes * 8 / (duration_ns / 1e9) / 1e6
            print(f"Output rate: {rate_mbps:.1f} Mbps", file=sys.stderr)

        flow_counts = Counter(r['flow_id'] for r in results)
        print(f"Per-flow packets: {dict(sorted(flow_counts.items()))}",
              file=sys.stderr)


if __name__ == '__main__':
    main()
