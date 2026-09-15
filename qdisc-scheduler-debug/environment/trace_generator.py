#!/usr/bin/env python3
"""Generate a multi-class network traffic trace for the hierarchical shaper task."""
import csv
import random
import json
import sys


def generate_trace(spec_path, output_path):
    with open(spec_path) as f:
        spec = json.load(f)

    duration_sec = spec['duration_sec']
    random.seed(42)
    packets = []

    for tc in spec['traffic_classes']:
        class_name = tc['name']
        dscp = tc['dscp']
        for flow_info in tc['flows']:
            flow_id = flow_info['flow_id']
            rate_bps = flow_info['rate_bps']
            pkt_size = flow_info['packet_size_bytes']
            pattern = flow_info.get('pattern', 'cbr')

            if pattern == 'cbr':
                interval_ns = int(pkt_size * 8 / rate_bps * 1e9)
                t = random.randint(0, interval_ns // 2)
                while t < duration_sec * 1e9:
                    packets.append({
                        'arrival_ns': int(t),
                        'flow_id': flow_id,
                        'size_bytes': pkt_size,
                        'dscp': dscp,
                        'class_name': class_name,
                    })
                    jitter = random.randint(-interval_ns // 20, interval_ns // 20)
                    t += interval_ns + jitter

            elif pattern == 'bursty':
                burst_size = flow_info.get('burst_packets', 12)
                accel = 3
                fast_interval_ns = int(pkt_size * 8 / (rate_bps * accel) * 1e9)
                burst_duration_ns = fast_interval_ns * burst_size
                pause_ns = burst_duration_ns * (accel - 1)
                t = random.randint(0, pause_ns // 2)
                while t < duration_sec * 1e9:
                    for _ in range(burst_size):
                        if t >= duration_sec * 1e9:
                            break
                        actual_size = pkt_size + random.randint(-50, 50)
                        packets.append({
                            'arrival_ns': int(t),
                            'flow_id': flow_id,
                            'size_bytes': actual_size,
                            'dscp': dscp,
                            'class_name': class_name,
                        })
                        jitter = random.randint(-fast_interval_ns // 20,
                                                fast_interval_ns // 20)
                        t += fast_interval_ns + jitter
                    jitter = random.randint(-pause_ns // 10, pause_ns // 10)
                    t += pause_ns + jitter

            elif pattern == 'bulk':
                interval_ns = int(pkt_size * 8 / rate_bps * 1e9)
                t = random.randint(0, interval_ns)
                while t < duration_sec * 1e9:
                    actual_size = pkt_size + random.randint(-100, 100)
                    actual_size = max(64, actual_size)
                    packets.append({
                        'arrival_ns': int(t),
                        'flow_id': flow_id,
                        'size_bytes': actual_size,
                        'dscp': dscp,
                        'class_name': class_name,
                    })
                    jitter = random.randint(-interval_ns // 10, interval_ns // 10)
                    t += interval_ns + jitter

    packets.sort(key=lambda p: (p['arrival_ns'], p['flow_id']))
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'arrival_ns', 'flow_id', 'size_bytes', 'dscp', 'class_name'])
        writer.writeheader()
        writer.writerows(packets)

    print(f"Generated {len(packets)} packets across "
          f"{len(set(p['flow_id'] for p in packets))} flows")


if __name__ == '__main__':
    spec_path = sys.argv[1] if len(sys.argv) > 1 else '/app/traffic_spec.json'
    output_path = sys.argv[2] if len(sys.argv) > 2 else '/app/trace.csv'
    generate_trace(spec_path, output_path)
