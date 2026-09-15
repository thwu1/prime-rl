#!/usr/bin/env python3
"""Entry point: loads SLA spec + trace, runs the hierarchical shaper, writes output.

"""
import csv
import json
import sys
import os


def load_trace(path):
    packets = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            packets.append({
                'arrival_ns': int(row['arrival_ns']),
                'flow_id': int(row['flow_id']),
                'size_bytes': int(row['size_bytes']),
                'dscp': int(row['dscp']),
            })
    return packets


def main():
    spec_path = sys.argv[1] if len(sys.argv) > 1 else '/app/sla_spec.json'
    trace_path = sys.argv[2] if len(sys.argv) > 2 else '/app/trace.csv'
    output_path = sys.argv[3] if len(sys.argv) > 3 else '/app/output.csv'

    with open(spec_path) as f:
        spec = json.load(f)

    packets = load_trace(trace_path)
    print(f"Loaded {len(packets)} packets from trace")

    sys.path.insert(0, '/app')
    try:
        from shaper import HierarchicalShaper
    except ImportError as e:
        print(f"ERROR: Could not import HierarchicalShaper from /app/shaper.py: {e}")
        sys.exit(1)

    shaper = HierarchicalShaper(spec)

    for pkt in packets:
        shaper.enqueue({
            'arrival_ns': pkt['arrival_ns'],
            'flow_id': pkt['flow_id'],
            'size_bytes': pkt['size_bytes'],
            'dscp': pkt['dscp'],
        })

    output = shaper.run()

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'dequeue_ns', 'flow_id', 'size_bytes', 'dscp',
            'class_name', 'queue_id', 'scheduling_delay_ns',
        ])
        writer.writeheader()
        for pkt in output:
            writer.writerow(pkt)

    print(f"Wrote {len(output)} scheduled packets to {output_path}")

    if output:
        classes = {}
        for pkt in output:
            cn = pkt['class_name']
            if cn not in classes:
                classes[cn] = {'count': 0, 'bytes': 0, 'delays': []}
            classes[cn]['count'] += 1
            classes[cn]['bytes'] += pkt['size_bytes']
            classes[cn]['delays'].append(pkt['scheduling_delay_ns'])

        duration_ns = output[-1]['dequeue_ns'] - output[0]['dequeue_ns']
        total_bytes = sum(c['bytes'] for c in classes.values())
        total_rate = (total_bytes * 8 / (duration_ns / 1e9) / 1e6
                      if duration_ns > 0 else 0)

        print(f"\n--- Summary ---")
        print(f"Duration: {duration_ns / 1e9:.3f}s")
        print(f"Total throughput: {total_rate:.1f} Mbps "
              f"(target: {spec['link_rate_mbps']} Mbps)")
        for cn, stats in sorted(classes.items()):
            rate = (stats['bytes'] * 8 / (duration_ns / 1e9) / 1e6
                    if duration_ns > 0 else 0)
            sorted_d = sorted(stats['delays'])
            p99 = sorted_d[int(len(sorted_d) * 0.99)] / 1e6
            print(f"  {cn}: {stats['count']} pkts, {rate:.2f} Mbps, "
                  f"p99 delay: {p99:.2f} ms")


if __name__ == '__main__':
    main()
