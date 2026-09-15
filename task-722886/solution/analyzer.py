#!/usr/bin/env python3
"""iperf3 JSON performance analysis tool.

Reads iperf3 JSON capture files from /app/captures/, auto-detects test type
from the JSON schema, computes metrics, and writes /app/analysis_report.json.
"""

import json
import os


def compute_jains_fairness(values):
    """Compute Jain's fairness index: (sum(xi))^2 / (n * sum(xi^2))"""
    n = len(values)
    if n == 0:
        return 0.0
    sum_x = sum(values)
    sum_x_sq = sum(x ** 2 for x in values)
    if sum_x_sq == 0:
        return 0.0
    return (sum_x ** 2) / (n * sum_x_sq)


def detect_test_type(data):
    """Determine the iperf3 test type from JSON schema fields."""
    test_start = data['start']['test_start']
    protocol = test_start.get('protocol', 'TCP')

    if protocol == 'UDP':
        return 'udp'

    if test_start.get('bidir', 0) == 1:
        return 'tcp_bidir'

    if test_start.get('num_streams', 1) > 1:
        return 'tcp_parallel'

    return 'tcp_single'


def analyze_tcp_single(data):
    """Extract metrics for a TCP single-stream test."""
    end = data['end']
    sender = end['streams'][0]['sender']
    receiver = end['streams'][0]['receiver']
    cpu = end['cpu_utilization_percent']

    sender_bps = sender['bits_per_second']
    receiver_bps = receiver['bits_per_second']
    retransmits = sender.get('retransmits', 0)
    sender_bytes = sender['bytes']
    mean_rtt_us = sender.get('mean_rtt', 0)

    sender_mb = sender_bytes / 1048576.0
    retransmit_rate = retransmits / sender_mb if sender_mb > 0 else 0.0
    efficiency = (receiver_bps / sender_bps) * 100.0 if sender_bps > 0 else 0.0

    if efficiency >= 99.5 and retransmit_rate <= 0.01:
        classification = 'optimal'
    elif efficiency >= 98.0 and retransmit_rate <= 0.1:
        classification = 'acceptable'
    else:
        classification = 'degraded'

    return {
        'sender_bps': sender_bps,
        'receiver_bps': receiver_bps,
        'retransmits': retransmits,
        'retransmit_rate_per_mb': retransmit_rate,
        'mean_rtt_ms': mean_rtt_us / 1000.0,
        'throughput_efficiency': efficiency,
        'cpu_host_total': cpu['host_total'],
        'classification': classification,
    }


def analyze_udp(data):
    """Extract metrics for a UDP test.

    sender_bps comes from sum_sent (sender's perspective).
    jitter/loss/out_of_order come from sum (receiver's perspective).
    """
    end = data['end']
    sum_sent = end['sum_sent']
    # Receiver perspective with jitter/loss data
    sum_recv = end.get('sum', end.get('sum_received', {}))
    cpu = end['cpu_utilization_percent']

    lost_percent = sum_recv.get('lost_percent', 0.0)

    if lost_percent <= 0.1:
        classification = 'optimal'
    elif lost_percent <= 1.0:
        classification = 'acceptable'
    else:
        classification = 'degraded'

    return {
        'sender_bps': sum_sent['bits_per_second'],
        'jitter_ms': sum_recv.get('jitter_ms', 0.0),
        'lost_packets': sum_recv.get('lost_packets', 0),
        'total_packets': sum_recv.get('packets', 0),
        'lost_percent': lost_percent,
        'out_of_order': sum_recv.get('out_of_order', 0),
        'cpu_host_total': cpu['host_total'],
        'classification': classification,
    }


def analyze_tcp_parallel(data):
    """Extract metrics for a TCP parallel-stream test."""
    end = data['end']
    streams = end['streams']
    cpu = end['cpu_utilization_percent']

    per_stream_sender_bps = [s['sender']['bits_per_second'] for s in streams]
    total_retransmits = sum(s['sender'].get('retransmits', 0) for s in streams)

    aggregate_sender = sum(per_stream_sender_bps)
    aggregate_receiver = sum(s['receiver']['bits_per_second'] for s in streams)

    fairness = compute_jains_fairness(per_stream_sender_bps)

    if fairness >= 0.99:
        classification = 'optimal'
    elif fairness >= 0.95:
        classification = 'acceptable'
    else:
        classification = 'degraded'

    return {
        'num_streams': len(streams),
        'aggregate_sender_bps': aggregate_sender,
        'aggregate_receiver_bps': aggregate_receiver,
        'per_stream_sender_bps': per_stream_sender_bps,
        'total_retransmits': total_retransmits,
        'jains_fairness_index': fairness,
        'cpu_host_total': cpu['host_total'],
        'classification': classification,
    }


def analyze_tcp_bidir(data):
    """Extract metrics for a TCP bidirectional test.

    First stream (index 0) = upload (client -> server).
    Second stream (index 1) = download (server -> client).
    """
    end = data['end']
    streams = end['streams']
    cpu = end['cpu_utilization_percent']

    upload_bps = streams[0]['sender']['bits_per_second']
    download_bps = streams[1]['sender']['bits_per_second']

    min_bps = min(upload_bps, download_bps)
    max_bps = max(upload_bps, download_bps)
    asymmetry = max_bps / min_bps if min_bps > 0 else float('inf')

    if asymmetry <= 1.1:
        classification = 'optimal'
    elif asymmetry <= 1.5:
        classification = 'acceptable'
    else:
        classification = 'degraded'

    return {
        'upload_sender_bps': upload_bps,
        'download_sender_bps': download_bps,
        'asymmetry_ratio': asymmetry,
        'cpu_host_total': cpu['host_total'],
        'classification': classification,
    }


def main():
    captures_dir = '/app/captures'
    report = {}

    for filename in sorted(os.listdir(captures_dir)):
        if not filename.endswith('.json'):
            continue

        filepath = os.path.join(captures_dir, filename)
        with open(filepath, 'r') as f:
            data = json.load(f)

        key = filename[:-5]  # strip .json
        test_type = detect_test_type(data)

        if test_type == 'tcp_single':
            report[key] = analyze_tcp_single(data)
        elif test_type == 'udp':
            report[key] = analyze_udp(data)
        elif test_type == 'tcp_parallel':
            report[key] = analyze_tcp_parallel(data)
        elif test_type == 'tcp_bidir':
            report[key] = analyze_tcp_bidir(data)

    with open('/app/analysis_report.json', 'w') as f:
        json.dump(report, f, indent=2)


if __name__ == '__main__':
    main()
