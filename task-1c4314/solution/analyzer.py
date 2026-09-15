#!/usr/bin/env python3
"""DERP protocol capture analyzer — reference implementation.

Parses a DPCAP v1 binary capture file containing multiplexed DERP protocol
frames and produces a JSON analysis report.
"""

import struct
import json
import sys

FILE_MAGIC = b'DPCAP\x01\x00\x00'
KEY_LEN = 32

FRAME_NAMES = {
    0x01: 'FrameServerKey',
    0x02: 'FrameClientInfo',
    0x03: 'FrameServerInfo',
    0x04: 'FrameSendPacket',
    0x05: 'FrameRecvPacket',
    0x06: 'FrameKeepAlive',
    0x07: 'FrameNotePreferred',
    0x08: 'FramePeerGone',
    0x09: 'FramePeerPresent',
    0x0a: 'FrameForwardPacket',
    0x10: 'FrameWatchConns',
    0x11: 'FrameClosePeer',
    0x12: 'FramePing',
    0x13: 'FramePong',
    0x14: 'FrameHealth',
    0x15: 'FrameRestarting',
}


def read_exact(f, n):
    """Read exactly n bytes or return short read."""
    data = f.read(n)
    return data if len(data) == n else None


def parse_capture(filename):
    """Parse DPCAP file into list of record dicts."""
    records = []
    with open(filename, 'rb') as f:
        magic = read_exact(f, 8)
        if magic != FILE_MAGIC:
            raise ValueError(f"Bad file magic: {magic!r}")

        while True:
            # Envelope header: 2B conn_id + 1B direction
            env = read_exact(f, 3)
            if env is None:
                break
            conn_id = struct.unpack('>H', env[:2])[0]
            direction = env[2]

            # DERP frame header: 1B type + 4B length
            fhdr = read_exact(f, 5)
            if fhdr is None:
                break
            frame_type = fhdr[0]
            payload_len = struct.unpack('>I', fhdr[1:5])[0]

            # Payload
            if payload_len > 0:
                payload = read_exact(f, payload_len)
                if payload is None:
                    break
            else:
                payload = b''

            records.append({
                'conn_id': conn_id,
                'direction': direction,
                'frame_type': frame_type,
                'payload': payload,
            })

    return records


def analyze(records):
    """Produce analysis dict from parsed records."""
    result = {}

    # --- Total frames ---
    result['total_frames'] = len(records)

    # --- Frame type counts ---
    type_counts = {}
    for r in records:
        name = FRAME_NAMES.get(r['frame_type'],
                               f"Unknown_0x{r['frame_type']:02x}")
        type_counts[name] = type_counts.get(name, 0) + 1
    result['frame_type_counts'] = dict(sorted(type_counts.items()))

    # --- Connection-to-key mapping (from FrameClientInfo) ---
    conn_to_key = {}
    for r in records:
        if r['frame_type'] == 0x02 and len(r['payload']) >= KEY_LEN:
            conn_to_key[r['conn_id']] = r['payload'][:KEY_LEN]

    # --- Unique client keys ---
    unique_keys = sorted(set(k.hex() for k in conn_to_key.values()))
    result['unique_client_keys'] = unique_keys

    # --- Routing table ---
    routing = {}
    for key_hex in unique_keys:
        routing[key_hex] = {
            'packets_sent': 0,
            'bytes_sent': 0,
            'packets_received': 0,
            'bytes_received': 0,
        }

    for r in records:
        if r['frame_type'] == 0x04:  # FrameSendPacket (C->S)
            sender_key = conn_to_key.get(r['conn_id'])
            if sender_key:
                h = sender_key.hex()
                if h in routing:
                    routing[h]['packets_sent'] += 1
                    # Payload = 32B dest key + data; exclude the key
                    routing[h]['bytes_sent'] += max(0, len(r['payload']) - KEY_LEN)

        elif r['frame_type'] == 0x05:  # FrameRecvPacket (S->C)
            receiver_key = conn_to_key.get(r['conn_id'])
            if receiver_key:
                h = receiver_key.hex()
                if h in routing:
                    routing[h]['packets_received'] += 1
                    # Payload = 32B src key + data; exclude the key
                    routing[h]['bytes_received'] += max(0, len(r['payload']) - KEY_LEN)

    result['routing_table'] = routing

    # --- Mesh forward count ---
    result['mesh_forward_count'] = sum(
        1 for r in records if r['frame_type'] == 0x0a
    )

    # --- Peer gone events ---
    peer_gone = []
    for r in records:
        if r['frame_type'] == 0x08 and len(r['payload']) >= KEY_LEN + 1:
            peer_gone.append({
                'peer_key_hex': r['payload'][:KEY_LEN].hex(),
                'reason_code': r['payload'][KEY_LEN],
            })
    result['peer_gone_events'] = peer_gone

    # --- Health warnings ---
    health = []
    for r in records:
        if r['frame_type'] == 0x14 and len(r['payload']) > 0:
            msg = r['payload'].decode('utf-8', errors='replace')
            if msg:
                health.append(msg)
    result['health_warnings'] = health

    # --- Server restart ---
    restart = None
    for r in records:
        if r['frame_type'] == 0x15 and len(r['payload']) >= 8:
            reconnect_in, try_for = struct.unpack('>II', r['payload'][:8])
            restart = {
                'reconnect_in_ms': reconnect_in,
                'try_for_ms': try_for,
            }
    result['server_restart'] = restart

    # --- Preferred clients ---
    preferred = set()
    for r in records:
        if r['frame_type'] == 0x07 and len(r['payload']) >= 1:
            if r['payload'][0] == 0x01:
                sender_key = conn_to_key.get(r['conn_id'])
                if sender_key:
                    preferred.add(sender_key.hex())
    result['preferred_clients'] = sorted(preferred)

    # --- Close peer targets ---
    close_targets = []
    for r in records:
        if r['frame_type'] == 0x11 and len(r['payload']) >= KEY_LEN:
            close_targets.append(r['payload'][:KEY_LEN].hex())
    result['close_peer_targets'] = close_targets

    # --- Connection count ---
    result['connections'] = len(set(r['conn_id'] for r in records))

    # --- Watch conns connections ---
    result['watch_conns_connections'] = sorted(
        set(r['conn_id'] for r in records if r['frame_type'] == 0x10)
    )

    return result


def main():
    input_file = sys.argv[1] if len(sys.argv) > 1 else '/app/capture.bin'
    output_file = sys.argv[2] if len(sys.argv) > 2 else '/app/analysis.json'

    records = parse_capture(input_file)
    result = analyze(records)

    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"Analysis complete: {result['total_frames']} frames -> {output_file}")


if __name__ == '__main__':
    main()
