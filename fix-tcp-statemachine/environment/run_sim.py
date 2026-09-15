#!/usr/bin/env python3

"""TCP simulation harness for interactive testing.

Usage:
    python3 /app/run_sim.py --list-scenarios
    python3 /app/run_sim.py --scenario low_loss
    python3 /app/run_sim.py --loss 0.1 --seed 42 --data-size 10000

Reads scenario configs from /app/scenarios/config.json.
Output is JSON suitable for piping to jq.
"""

import argparse
import hashlib
import json
import sys

sys.path.insert(0, '/app')


def load_scenarios():
    with open('/app/scenarios/config.json') as f:
        return json.load(f)['scenarios']


def run_transfer(data, loss_rate, reorder_rate, seed, base_delay_ms, max_time_ms=300000):
    from tcp_sim.network import LossyChannel
    from tcp_sim.connection import TcpConnection, State

    channel = LossyChannel(
        loss_rate=loss_rate, reorder_rate=reorder_rate,
        seed=seed, base_delay_ms=base_delay_ms
    )

    # Handshake
    server = TcpConnection(local_port=80, iss=1000)
    client = TcpConnection(local_port=5000, iss=100)

    syns = client.connect(80)
    syn_acks = server.on_segment(syns[0])
    acks = client.on_segment(syn_acks[0])
    server.on_segment(acks[0])

    # Queue all data
    initial_segs = server.send_data(data)
    for seg in initial_segs:
        channel.send(seg, 'a_to_b', 0)

    received = bytearray()
    time_ms = 0
    tick_interval = 10
    retransmissions = 0

    while time_ms < max_time_ms:
        time_ms += tick_interval

        # Tick first (update time, handle retransmissions)
        for seg in server.tick(time_ms):
            retransmissions += 1 if seg.data else 0
            channel.send(seg, 'a_to_b', time_ms)
        for seg in client.tick(time_ms):
            channel.send(seg, 'b_to_a', time_ms)

        # Deliver
        for seg, direction in channel.deliver(time_ms):
            if direction == 'a_to_b':
                for r in client.on_segment(seg):
                    channel.send(r, 'b_to_a', time_ms)
            else:
                for r in server.on_segment(seg):
                    channel.send(r, 'a_to_b', time_ms)

        chunk = client.read_data()
        if chunk:
            received.extend(chunk)

        if (len(received) >= len(data)
                and channel.pending() == 0
                and len(server.unacked) == 0):
            break

    expected_sha = hashlib.sha256(data).hexdigest()
    actual_sha = hashlib.sha256(bytes(received)).hexdigest()

    return {
        'success': len(received) == len(data),
        'integrity': actual_sha == expected_sha,
        'bytes_sent': len(data),
        'bytes_received': len(received),
        'time_ms': time_ms,
        'retransmissions': retransmissions,
        'sha256_expected': expected_sha,
        'sha256_actual': actual_sha,
    }


def main():
    parser = argparse.ArgumentParser(description='TCP simulation harness')
    parser.add_argument('--scenario', help='Run a named scenario from config.json')
    parser.add_argument('--list-scenarios', action='store_true',
                        help='List available scenarios')
    parser.add_argument('--loss', type=float, default=0.0,
                        help='Packet loss rate [0.0-1.0]')
    parser.add_argument('--reorder', type=float, default=0.0,
                        help='Reorder probability [0.0-1.0]')
    parser.add_argument('--seed', type=int, default=42, help='PRNG seed')
    parser.add_argument('--delay', type=int, default=50,
                        help='Base delay in ms')
    parser.add_argument('--data-size', type=int, default=10000,
                        help='Bytes to transfer')
    parser.add_argument('--max-time', type=int, default=300000,
                        help='Max simulation time in ms')

    args = parser.parse_args()

    if args.list_scenarios:
        for s in load_scenarios():
            print(f"  {s['name']:15s} loss={s['loss_rate']:.0%} "
                  f"reorder={s.get('reorder_rate', 0):.0%} "
                  f"delay={s['base_delay_ms']}ms "
                  f"data={s['data_size']}B — {s['description']}")
        return 0

    if args.scenario:
        sc = next((s for s in load_scenarios() if s['name'] == args.scenario), None)
        if not sc:
            print(f"Unknown scenario: {args.scenario}", file=sys.stderr)
            return 1
        data = bytes(range(256)) * (sc['data_size'] // 256 + 1)
        data = data[:sc['data_size']]
        result = run_transfer(
            data, sc['loss_rate'], sc.get('reorder_rate', 0.0),
            sc['seed'], sc['base_delay_ms'])
    else:
        data = bytes(range(256)) * (args.data_size // 256 + 1)
        data = data[:args.data_size]
        result = run_transfer(
            data, args.loss, args.reorder, args.seed,
            args.delay, args.max_time)

    print(json.dumps(result, indent=2))
    return 0 if result['success'] and result['integrity'] else 1


if __name__ == '__main__':
    sys.exit(main() or 0)
