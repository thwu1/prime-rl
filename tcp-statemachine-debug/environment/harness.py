#!/usr/bin/env python3
"""Scenario evaluation harness for TCP congestion control algorithms.

Loads a compact scenario specification, expands it into an event stream,
feeds the events to a CongestionController implementation, and reports
performance metrics.

Usage:
    python3 /app/harness.py /app/scenarios/scenario_a.json [...]
"""

import json
import sys
import importlib.util


def load_cc_class():
    """Dynamically load CongestionController from /app/tcp_sim/congestion.py."""
    spec = importlib.util.spec_from_file_location(
        'congestion', '/app/tcp_sim/congestion.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CongestionController


def expand_events(scenario):
    """Expand a compact scenario spec into a list of event dicts."""
    base_rtt = scenario['base_rtt']
    jitter = scenario.get('rtt_jitter', 0.0)
    n_acks = scenario['num_acks']
    dup_set = set(scenario['loss_pattern'].get('dup_ack_sets', []))
    to_set = set(scenario['loss_pattern'].get('timeouts', []))

    events = []
    t = 0.0
    for i in range(n_acks):
        t += base_rtt

        if i in dup_set:
            for j in range(3):
                events.append({
                    'time': round(t + j * base_rtt / 100, 6),
                    'type': 'dup_ack',
                })
            t += base_rtt

        if i in to_set:
            events.append({'time': round(t, 6), 'type': 'timeout'})
            t += base_rtt

        rtt_var = (i % 7 - 3) * jitter / 3
        rtt = base_rtt + rtt_var
        events.append({
            'time': round(t, 6),
            'type': 'ack',
            'bytes': 1460,
            'rtt': round(abs(rtt), 6),
        })

    return events


def run_scenario(cc_class, scenario):
    """Run a single scenario and return metrics dict."""
    events = expand_events(scenario)
    cc = cc_class()

    cwnd_samples = []
    for ev in events:
        if ev['type'] == 'ack':
            cc.on_ack(ev['bytes'], ev['rtt'])
        elif ev['type'] == 'dup_ack':
            cc.on_duplicate_ack()
        elif ev['type'] == 'timeout':
            cc.on_timeout()

        cwnd_samples.append(cc.get_cwnd())

    avg_cwnd = sum(cwnd_samples) / len(cwnd_samples) if cwnd_samples else 0
    return {
        'name': scenario.get('name', '?'),
        'avg_cwnd': round(avg_cwnd, 1),
        'max_cwnd': max(cwnd_samples) if cwnd_samples else 0,
        'final_cwnd': cc.get_cwnd(),
        'final_ssthresh': cc.get_ssthresh(),
        'final_state': cc.get_state(),
        'num_events': len(events),
    }


def main():
    if len(sys.argv) < 2:
        print('Usage: python3 harness.py <scenario.json> [...]')
        sys.exit(1)

    cc_class = load_cc_class()
    for path in sys.argv[1:]:
        with open(path) as f:
            spec = json.load(f)
        metrics = run_scenario(cc_class, spec)
        target = spec.get('targets', {}).get('min_avg_cwnd', 0)
        ok = 'PASS' if metrics['avg_cwnd'] >= target else 'FAIL'
        print(f"\n=== {metrics['name']} ({ok}) ===")
        for k, v in metrics.items():
            print(f'  {k}: {v}')
        if target:
            print(f'  target_avg_cwnd: {target}')


if __name__ == '__main__':
    main()
