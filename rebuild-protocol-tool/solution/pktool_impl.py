#!/usr/bin/env python3
"""MeshLink Protocol packet analyzer — solution implementation."""

import sys
import struct

MAGIC = b'ML'
MSG_TYPES = {0: 'HELLO', 1: 'DATA', 2: 'ACK', 3: 'ERROR', 4: 'ROUTE', 5: 'FRAGMENT'}

LFSR_POLY = 0xB4BCD35C
LFSR_ZERO_SEED = 0x0000ACE1


def crc16_ccitt(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


def lfsr_transform(data, seed):
    """Descramble/scramble using Galois LFSR keystream."""
    state = seed if seed != 0 else LFSR_ZERO_SEED
    result = bytearray(len(data))
    for i in range(len(data)):
        lsb = state & 1
        state >>= 1
        if lsb:
            state ^= LFSR_POLY
        state &= 0xFFFFFFFF
        result[i] = data[i] ^ (state & 0xFF)
    return bytes(result)


def parse_packets(data):
    packets = []
    offset = 0
    while offset < len(data):
        if offset + 8 > len(data):
            packets.append({'_error': 'TRUNCATED'})
            break
        magic = data[offset:offset + 2]
        if magic != MAGIC:
            packets.append({'_error': 'INVALID_MAGIC', '_magic': magic})
            nxt = offset + 1
            while nxt + 1 < len(data):
                if data[nxt:nxt + 2] == MAGIC:
                    break
                nxt += 1
            if nxt + 1 >= len(data):
                break
            offset = nxt
            continue
        version = data[offset + 2]
        msg_type = data[offset + 3]
        payload_len = struct.unpack('>H', data[offset + 4:offset + 6])[0]
        crc_expected = struct.unpack('>H', data[offset + 6:offset + 8])[0]
        if offset + 8 + payload_len > len(data):
            packets.append({'_error': 'TRUNCATED', 'type': msg_type, 'payload_len': payload_len})
            break
        payload = data[offset + 8:offset + 8 + payload_len]
        crc_data = data[offset + 2:offset + 6] + payload
        crc_computed = crc16_ccitt(crc_data)
        crc_valid = crc_expected == crc_computed
        pkt = {
            'version': version, 'type': msg_type,
            'type_name': MSG_TYPES.get(msg_type, 'UNKNOWN'),
            'payload_len': payload_len, 'payload': payload,
            'crc_expected': crc_expected, 'crc_computed': crc_computed,
            'crc_valid': crc_valid,
            '_error': None if crc_valid else 'CRC_MISMATCH',
        }
        if crc_valid:
            _parse_payload(pkt, payload)
        packets.append(pkt)
        offset += 8 + payload_len
    return packets


def _parse_payload(pkt, payload):
    t = pkt['type']
    try:
        if t == 0:
            if len(payload) < 4:
                pkt['_parse_error'] = True; return
            pkt['node_id'] = struct.unpack('>I', payload[0:4])[0]
            name_data = payload[4:]
            null = name_data.find(b'\x00')
            pkt['node_name'] = (name_data[:null] if null >= 0 else name_data).decode('utf-8', errors='replace')
        elif t == 1:
            if len(payload) < 5:
                pkt['_parse_error'] = True; return
            pkt['channel'] = payload[0]
            pkt['sequence'] = struct.unpack('>I', payload[1:5])[0]
            raw_data = payload[5:]
            if payload[0] & 0x80:
                pkt['data'] = lfsr_transform(raw_data, pkt['sequence'])
                pkt['scrambled'] = True
            else:
                pkt['data'] = raw_data
                pkt['scrambled'] = False
        elif t == 2:
            if len(payload) < 4:
                pkt['_parse_error'] = True; return
            pkt['sequence'] = struct.unpack('>I', payload[0:4])[0]
        elif t == 3:
            if len(payload) < 2:
                pkt['_parse_error'] = True; return
            pkt['error_code'] = struct.unpack('>H', payload[0:2])[0]
            pkt['error_message'] = payload[2:].decode('utf-8', errors='replace')
        elif t == 4:
            if len(payload) < 1:
                pkt['_parse_error'] = True; return
            pkt['hop_count'] = payload[0]
            node_data = payload[1:]
            pkt['route_nodes'] = [struct.unpack('>I', node_data[i:i + 4])[0]
                                  for i in range(0, len(node_data) - 3, 4)]
        elif t == 5:
            if len(payload) < 8:
                pkt['_parse_error'] = True; return
            pkt['msg_id'] = struct.unpack('>I', payload[0:4])[0]
            pkt['frag_idx'] = struct.unpack('>H', payload[4:6])[0]
            pkt['total_frags'] = struct.unpack('>H', payload[6:8])[0]
            pkt['frag_data'] = payload[8:]
    except Exception:
        pkt['_parse_error'] = True


def _decode_packet(idx, pkt, gap=None):
    print(f"Packet #{idx + 1}:")
    err = pkt.get('_error')
    if err == 'TRUNCATED':
        print("  [TRUNCATED]")
        print()
        return
    if err == 'INVALID_MAGIC':
        m = pkt['_magic']
        print(f"  [INVALID MAGIC: 0x{m[0]:02x}{m[1]:02x}]")
        print()
        return
    t = pkt['type']
    tn = pkt['type_name']
    print(f"  Type: {tn} ({t})")
    if err == 'CRC_MISMATCH':
        print(f"  CRC: INVALID (expected 0x{pkt['crc_expected']:04X}, computed 0x{pkt['crc_computed']:04X})")
        print(f"  Payload: {pkt['payload'].hex()} ({pkt['payload_len']} bytes)")
        print()
        return
    if pkt.get('_parse_error'):
        print("  [MALFORMED PAYLOAD]")
        print()
        return
    if t == 0:
        print(f"  Node ID: 0x{pkt['node_id']:08X}")
        print(f"  Node Name: \"{pkt['node_name']}\"")
    elif t == 1:
        print(f"  Channel: {pkt['channel']}")
        print(f"  Sequence: {pkt['sequence']}")
        if gap and gap.get('has_gap'):
            print(f"  [Sequence gap on channel {gap['channel']}: expected {gap['expected']}, got {gap['got']}]")
        d = pkt['data']
        if pkt.get('scrambled'):
            print(f"  Scrambled: yes")
        print(f"  Data: {d.hex()} ({len(d)} bytes)")
    elif t == 2:
        print(f"  Sequence: {pkt['sequence']}")
    elif t == 3:
        print(f"  Error Code: 0x{pkt['error_code']:04X}")
        print(f"  Error Message: \"{pkt['error_message']}\"")
    elif t == 4:
        print(f"  Hop Count: {pkt['hop_count']}")
        nodes_str = ", ".join(f"0x{n:08X}" for n in pkt['route_nodes'])
        print(f"  Route: [{nodes_str}]")
    elif t == 5:
        print(f"  Message ID: 0x{pkt['msg_id']:08X}")
        print(f"  Fragment: {pkt['frag_idx']}/{pkt['total_frags']}")
        fd = pkt['frag_data']
        print(f"  Fragment Data: {fd.hex()} ({len(fd)} bytes)")
    else:
        print(f"  Payload: {pkt['payload'].hex()} ({pkt['payload_len']} bytes)")
    print()


def cmd_decode(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    packets = parse_packets(data)

    ch_last_seq = {}  # channel -> last sequence number

    for i, pkt in enumerate(packets):
        gap = None
        err = pkt.get('_error')
        if err is None and pkt['type'] == 1 and pkt['payload_len'] >= 5:
            ch = pkt['payload'][0]
            seq = struct.unpack('>I', pkt['payload'][1:5])[0]
            if ch in ch_last_seq:
                expected = (ch_last_seq[ch] + 1) & 0xFFFFFFFF
                if seq != expected:
                    gap = {'has_gap': True, 'channel': ch, 'expected': expected, 'got': seq}
            ch_last_seq[ch] = seq
        _decode_packet(i, pkt, gap)


def cmd_validate(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    packets = parse_packets(data)
    all_valid = True
    for i, pkt in enumerate(packets):
        err = pkt.get('_error')
        if err is None:
            print(f"Packet #{i + 1}: OK")
        elif err == 'TRUNCATED':
            print(f"Packet #{i + 1}: TRUNCATED")
            all_valid = False
        elif err == 'INVALID_MAGIC':
            m = pkt['_magic']
            print(f"Packet #{i + 1}: INVALID_MAGIC (0x{m[0]:02x}{m[1]:02x})")
            all_valid = False
        elif err == 'CRC_MISMATCH':
            print(f"Packet #{i + 1}: CRC_MISMATCH (expected 0x{pkt['crc_expected']:04X}, computed 0x{pkt['crc_computed']:04X})")
            all_valid = False
    sys.exit(0 if all_valid else 1)


def cmd_stats(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    packets = parse_packets(data)
    type_counts = {name: 0 for name in MSG_TYPES.values()}
    unknown_count = 0
    total_payload = 0
    invalid_count = 0
    scrambled_count = 0
    for pkt in packets:
        err = pkt.get('_error')
        if err in ('TRUNCATED', 'INVALID_MAGIC'):
            invalid_count += 1
            continue
        tn = MSG_TYPES.get(pkt['type'])
        if tn:
            type_counts[tn] += 1
        else:
            unknown_count += 1
        total_payload += pkt['payload_len']
        if err == 'CRC_MISMATCH':
            invalid_count += 1
        if pkt['type'] == 1 and err is None and pkt['payload_len'] >= 5 and (pkt['payload'][0] & 0x80):
            scrambled_count += 1
    print(f"Total packets: {len(packets)}")
    for name in ['HELLO', 'DATA', 'ACK', 'ERROR', 'ROUTE', 'FRAGMENT']:
        print(f"  {name}: {type_counts[name]}")
    if unknown_count > 0:
        print(f"  UNKNOWN: {unknown_count}")
    print(f"Total payload bytes: {total_payload}")
    print(f"Invalid packets: {invalid_count}")
    if scrambled_count > 0:
        print(f"Scrambled DATA packets: {scrambled_count}")


def _matches_filter(pkt, expr):
    if pkt.get('_error') is not None:
        return False
    for part in expr.split(','):
        part = part.strip()
        if '=' not in part:
            continue
        key, val = part.split('=', 1)
        key = key.strip()
        val = val.strip()
        if key == 'type':
            tn = MSG_TYPES.get(pkt['type'], 'UNKNOWN')
            if tn.upper() != val.upper():
                return False
        elif key == 'channel':
            if pkt['type'] != 1 or pkt.get('payload_len', 0) < 5:
                return False
            if pkt['payload'][0] != int(val):
                return False
        elif key == 'seq':
            target = int(val, 0)
            if pkt['type'] == 1:
                if pkt.get('payload_len', 0) < 5:
                    return False
                if struct.unpack('>I', pkt['payload'][1:5])[0] != target:
                    return False
            elif pkt['type'] == 2:
                if pkt.get('payload_len', 0) < 4:
                    return False
                if struct.unpack('>I', pkt['payload'][0:4])[0] != target:
                    return False
            else:
                return False
        elif key == 'node_id':
            if pkt['type'] != 0 or pkt.get('payload_len', 0) < 4:
                return False
            if struct.unpack('>I', pkt['payload'][0:4])[0] != int(val, 0):
                return False
        elif key == 'error_code':
            if pkt['type'] != 3 or pkt.get('payload_len', 0) < 2:
                return False
            if struct.unpack('>H', pkt['payload'][0:2])[0] != int(val, 0):
                return False
        elif key == 'msg_id':
            if pkt['type'] != 5 or pkt.get('payload_len', 0) < 8:
                return False
            if struct.unpack('>I', pkt['payload'][0:4])[0] != int(val, 0):
                return False
        elif key == 'hop_count':
            if pkt['type'] != 4 or pkt.get('payload_len', 0) < 1:
                return False
            if pkt['payload'][0] != int(val):
                return False
    return True


def cmd_filter(expr, filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    packets = parse_packets(data)
    midx = 0
    for pkt in packets:
        if _matches_filter(pkt, expr):
            _decode_packet(midx, pkt, None)
            midx += 1
    if midx == 0:
        print("No matching packets.")


def cmd_reassemble(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    packets = parse_packets(data)

    # Collect valid FRAGMENT packets
    frags = []
    for pkt in packets:
        if pkt.get('_error') is not None:
            continue
        if pkt['type'] != 5:
            continue
        if pkt['payload_len'] < 8:
            continue
        frags.append({
            'msg_id': struct.unpack('>I', pkt['payload'][0:4])[0],
            'frag_idx': struct.unpack('>H', pkt['payload'][4:6])[0],
            'total': struct.unpack('>H', pkt['payload'][6:8])[0],
            'data': pkt['payload'][8:],
            'orig_order': len(frags),
        })

    if not frags:
        print("No fragment packets found.")
        return

    # Sort by msg_id, then frag_idx, then original order (stable dedup)
    frags.sort(key=lambda f: (f['msg_id'], f['frag_idx'], f['orig_order']))

    # Group by msg_id
    groups = {}
    for frag in frags:
        mid = frag['msg_id']
        if mid not in groups:
            groups[mid] = []
        groups[mid].append(frag)

    first_msg = True
    for mid in sorted(groups.keys()):
        group = groups[mid]

        # Determine total: use maximum if fragments disagree
        first_total = group[0]['total']
        total = first_total
        has_conflict = False
        for frag in group[1:]:
            if frag['total'] != first_total:
                has_conflict = True
                if frag['total'] > total:
                    total = frag['total']

        if not first_msg:
            print()
        first_msg = False

        # Deduplicate by frag_idx (keep first occurrence)
        seen = set()
        unique_frags = []
        for frag in group:
            if frag['frag_idx'] not in seen:
                seen.add(frag['frag_idx'])
                unique_frags.append(frag)

        unique_count = len(unique_frags)

        if unique_count >= total:
            print(f"Message 0x{mid:08X}: COMPLETE ({total}/{total})")
            unique_frags.sort(key=lambda f: f['frag_idx'])
            concat = b''.join(f['data'] for f in unique_frags)
            print(f"  {concat.hex()} ({len(concat)} bytes)")
        else:
            present = {f['frag_idx'] for f in unique_frags}
            missing = [idx for idx in range(total) if idx not in present]
            missing_str = ", ".join(str(idx) for idx in missing)
            print(f"Message 0x{mid:08X}: INCOMPLETE ({unique_count}/{total}, missing: {missing_str})")

        if has_conflict:
            print("  [Warning: inconsistent fragment counts]")


def main():
    if len(sys.argv) < 2:
        print("Usage: pktool <command> [args...]", file=sys.stderr)
        print("Commands: decode, validate, stats, filter, reassemble", file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'decode':
        if len(sys.argv) != 3:
            print("Usage: pktool decode <file>", file=sys.stderr); sys.exit(1)
        cmd_decode(sys.argv[2])
    elif cmd == 'validate':
        if len(sys.argv) != 3:
            print("Usage: pktool validate <file>", file=sys.stderr); sys.exit(1)
        cmd_validate(sys.argv[2])
    elif cmd == 'stats':
        if len(sys.argv) != 3:
            print("Usage: pktool stats <file>", file=sys.stderr); sys.exit(1)
        cmd_stats(sys.argv[2])
    elif cmd == 'filter':
        if len(sys.argv) != 4:
            print("Usage: pktool filter <expr> <file>", file=sys.stderr); sys.exit(1)
        cmd_filter(sys.argv[2], sys.argv[3])
    elif cmd == 'reassemble':
        if len(sys.argv) != 3:
            print("Usage: pktool reassemble <file>", file=sys.stderr); sys.exit(1)
        cmd_reassemble(sys.argv[2])
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
