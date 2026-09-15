#!/usr/bin/env python3
"""
BLE Multi-Layer Encryption Forensics Analyzer.

Parses BLLC binary captures and HCI btsnoop logs to detect protocol
violations, derive session keys, and identify cross-layer security issues.
"""
import struct
import json
import os
import glob

# === Constants ===
MAGIC = b'BLLC'
DIR_C2P = 0x00
DIR_P2C = 0x01
LLID_CONTROL = 0x03

LL_TERMINATE_IND = 0x02
LL_ENC_REQ = 0x03
LL_ENC_RSP = 0x04
LL_START_ENC_REQ = 0x05
LL_START_ENC_RSP = 0x06
LL_PAUSE_ENC_REQ = 0x0A
LL_PAUSE_ENC_RSP = 0x0B

ENC_TIMEOUT_US = 40_000_000

IDLE = 'IDLE'
WAIT_ENC_RSP = 'WAIT_ENC_RSP'
WAIT_START_ENC_REQ = 'WAIT_START_ENC_REQ'
WAIT_START_ENC_RSP_C = 'WAIT_START_ENC_RSP_C'
WAIT_START_ENC_RSP_P = 'WAIT_START_ENC_RSP_P'
ENCRYPTED = 'ENCRYPTED'
PAUSING_WAIT_P = 'PAUSING_WAIT_P'
PAUSING_WAIT_C = 'PAUSING_WAIT_C'


# === BLLC Parsing ===

def parse_trace(filepath):
    """Parse a BLLC binary trace file into packet dicts."""
    packets = []
    with open(filepath, 'rb') as f:
        magic = f.read(4)
        if magic != MAGIC:
            raise ValueError(f"Bad magic: {magic!r}")
        version = struct.unpack('<H', f.read(2))[0]
        pkt_count = struct.unpack('<I', f.read(4))[0]

        for _ in range(pkt_count):
            ts = struct.unpack('<Q', f.read(8))[0]
            direction = struct.unpack('B', f.read(1))[0]
            pdu_len = struct.unpack('<H', f.read(2))[0]
            pdu_raw = f.read(pdu_len)

            pkt = {'timestamp_us': ts, 'direction': direction}

            if pdu_len >= 2:
                llid = pdu_raw[0] & 0x03
                payload_len = pdu_raw[1]
                payload = pdu_raw[2:2 + payload_len]
                pkt['llid'] = llid

                if llid == LLID_CONTROL and len(payload) >= 1:
                    pkt['opcode'] = payload[0]
                    pkt['ctrl_data'] = payload[1:]

            packets.append(pkt)

    return packets


# === LL Violation Detection ===

def analyze_trace(packets, trace_filename):
    """Run encryption state machine and detect LL-level violations."""
    violations = []
    state = IDLE
    enc_req_ts = None

    for idx, pkt in enumerate(packets):
        if pkt.get('llid') != LLID_CONTROL:
            continue
        opcode = pkt.get('opcode')
        if opcode is None:
            continue
        direction = pkt['direction']
        ts = pkt['timestamp_us']

        if opcode == LL_ENC_REQ:
            if direction == DIR_P2C:
                violations.append({
                    'type': 'WRONG_INITIATOR',
                    'packet_index': idx,
                    'description': (
                        f'LL_ENC_REQ sent by peripheral at packet {idx}. '
                        f'Only the central may initiate encryption.'
                    ),
                })
            else:
                state = WAIT_ENC_RSP
                enc_req_ts = ts

        elif opcode == LL_ENC_RSP:
            if state == WAIT_ENC_RSP:
                state = WAIT_START_ENC_REQ

        elif opcode == LL_START_ENC_REQ:
            if state == WAIT_ENC_RSP:
                violations.append({
                    'type': 'OUT_OF_ORDER',
                    'packet_index': idx,
                    'description': (
                        f'LL_START_ENC_REQ at packet {idx} received before '
                        f'LL_ENC_RSP. Expected LL_ENC_RSP first.'
                    ),
                })
            if state in (WAIT_ENC_RSP, WAIT_START_ENC_REQ):
                state = WAIT_START_ENC_RSP_C

        elif opcode == LL_START_ENC_RSP:
            if direction == DIR_C2P:
                if state == WAIT_START_ENC_RSP_C:
                    state = WAIT_START_ENC_RSP_P
            elif direction == DIR_P2C:
                if state == WAIT_START_ENC_RSP_P:
                    if enc_req_ts is not None:
                        duration = ts - enc_req_ts
                        if duration > ENC_TIMEOUT_US:
                            violations.append({
                                'type': 'ENCRYPTION_TIMEOUT',
                                'packet_index': idx,
                                'description': (
                                    f'Encryption procedure completed at packet '
                                    f'{idx} after {duration / 1_000_000:.1f}s, '
                                    f'exceeding 40-second timeout.'
                                ),
                            })
                    state = ENCRYPTED
                    enc_req_ts = None
                elif state == ENCRYPTED:
                    violations.append({
                        'type': 'DUPLICATE_PDU',
                        'packet_index': idx,
                        'description': (
                            f'Duplicate LL_START_ENC_RSP from peripheral '
                            f'at packet {idx}. Encryption already established.'
                        ),
                    })

        elif opcode == LL_PAUSE_ENC_REQ:
            if state == ENCRYPTED:
                state = PAUSING_WAIT_P

        elif opcode == LL_PAUSE_ENC_RSP:
            if state == PAUSING_WAIT_P and direction == DIR_P2C:
                state = PAUSING_WAIT_C
            elif state == PAUSING_WAIT_C and direction == DIR_C2P:
                state = IDLE

        elif opcode == LL_TERMINATE_IND:
            if state not in (IDLE, ENCRYPTED):
                violations.append({
                    'type': 'TERMINATION_DURING_ENCRYPTION',
                    'packet_index': idx,
                    'description': (
                        f'LL_TERMINATE_IND at packet {idx} during encryption '
                        f'procedure (state: {state}).'
                    ),
                })

    return {
        'trace_file': trace_filename,
        'total_packets': len(packets),
        'violations': violations,
    }


# === Encryption Parameter Extraction ===

def extract_encryption_params(packets):
    """Extract Rand, EDIV, SKDm, SKDs from the first valid Central-initiated
    encryption setup in a trace."""
    params = {}
    for pkt in packets:
        if pkt.get('llid') != LLID_CONTROL:
            continue
        opcode = pkt.get('opcode')
        ctrl_data = pkt.get('ctrl_data', b'')

        if opcode == LL_ENC_REQ and pkt['direction'] == DIR_C2P:
            # CtrData: Rand(8) + EDIV(2) + SKDm(8) + IVm(4) = 22 bytes
            if len(ctrl_data) >= 22 and 'rand' not in params:
                params['rand'] = ctrl_data[0:8]
                params['ediv'] = struct.unpack('<H', ctrl_data[8:10])[0]
                params['skdm'] = ctrl_data[10:18]
                params['ivm'] = ctrl_data[18:22]

        elif opcode == LL_ENC_RSP:
            # CtrData: SKDs(8) + IVs(4) = 12 bytes
            if len(ctrl_data) >= 12 and 'skds' not in params:
                params['skds'] = ctrl_data[0:8]
                params['ivs'] = ctrl_data[8:12]

    return params


# === btsnoop HCI Log Parsing ===

def parse_btsnoop(path):
    """Parse a btsnoop HCI UART H4 log file (datalink type 1002).

    Returns a list of dicts for encryption-related events:
    - LE_LTK_REQUEST: {type, handle, rand, ediv}
    - KEY_SIZE: {type, handle, key_size}
    """
    events = []
    with open(path, 'rb') as f:
        # File header (16 bytes)
        ident = f.read(8)
        if ident != b'btsnoop\x00':
            raise ValueError(f"Not a btsnoop file: {ident!r}")
        version = struct.unpack('>I', f.read(4))[0]
        datalink = struct.unpack('>I', f.read(4))[0]
        if datalink != 1002:
            raise ValueError(f"Expected HCI UART H4 (1002), got {datalink}")

        while True:
            hdr = f.read(24)
            if len(hdr) < 24:
                break
            orig_len, incl_len, flags, drops, ts = struct.unpack('>IIIIq', hdr)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break

            if len(data) < 1:
                continue
            h4_type = data[0]
            payload = data[1:]

            # Parse HCI Events (H4 type 0x04)
            if h4_type == 0x04 and len(payload) >= 2:
                evt_code = payload[0]
                param_len = payload[1]
                params = payload[2:2 + param_len]

                # LE Meta Event (0x3E)
                if evt_code == 0x3E and len(params) >= 1:
                    subevent = params[0]
                    # LE Long Term Key Request (subevent 0x05)
                    if subevent == 0x05 and len(params) >= 13:
                        handle = struct.unpack('<H', params[1:3])[0]
                        rand = params[3:11]
                        ediv = struct.unpack('<H', params[11:13])[0]
                        events.append({
                            'type': 'LE_LTK_REQUEST',
                            'handle': handle,
                            'rand': rand,
                            'ediv': ediv,
                        })

                # Command Complete (0x0E)
                elif evt_code == 0x0E and len(params) >= 4:
                    cmd_opcode = struct.unpack('<H', params[1:3])[0]
                    # Read Encryption Key Size (opcode 0x1408)
                    if cmd_opcode == 0x1408 and len(params) >= 7:
                        cmd_status = params[3]
                        handle = struct.unpack('<H', params[4:6])[0]
                        key_size = params[6]
                        if cmd_status == 0:
                            events.append({
                                'type': 'KEY_SIZE',
                                'handle': handle,
                                'key_size': key_size,
                            })

    return events


# === Session Key Derivation ===

def derive_session_key(ltk, skds, skdm):
    """Derive BLE session key: SK = AES-128-ECB(LTK, SKDs || SKDm)."""
    from Crypto.Cipher import AES
    skd = skds + skdm  # SKDs (8 bytes MSB) || SKDm (8 bytes LSB)
    cipher = AES.new(ltk, AES.MODE_ECB)
    return cipher.encrypt(skd)


# === Main Analysis ===

def main():
    captures_dir = '/app/captures/ll'
    hci_log_path = '/app/captures/hci/central.btsnoop'
    results_dir = '/app/results'
    ltk_path = '/app/ltk.hex'

    os.makedirs(results_dir, exist_ok=True)

    # Read LTK
    with open(ltk_path) as f:
        ltk = bytes.fromhex(f.read().strip())
    print(f"LTK: {ltk.hex()}")

    # ---- Phase 1: Parse and analyze all LL traces ----
    trace_files = sorted(glob.glob(os.path.join(captures_dir, '*.bllc')))
    all_results = {}
    all_params = {}

    for trace_path in trace_files:
        filename = os.path.basename(trace_path)
        name = filename.replace('.bllc', '')
        packets = parse_trace(trace_path)

        # Run state machine violation detection
        result = analyze_trace(packets, filename)
        result_path = os.path.join(results_dir, f'{name}.json')
        with open(result_path, 'w') as f:
            json.dump(result, f, indent=2)

        all_results[name] = result

        # Extract encryption parameters
        params = extract_encryption_params(packets)
        if params.get('skdm') and params.get('skds'):
            all_params[name] = params

        n_v = len(result['violations'])
        print(f"{filename}: {result['total_packets']} packets, {n_v} violation(s)")
        for v in result['violations']:
            print(f"  [{v['type']}] packet {v['packet_index']}")

    # ---- Phase 2: Derive session keys for violation-free traces ----
    session_keys = {}
    for name, result in sorted(all_results.items()):
        if name in all_params and len(result['violations']) == 0:
            params = all_params[name]
            sk = derive_session_key(ltk, params['skds'], params['skdm'])
            session_keys[name] = sk.hex()
            print(f"Session key for {name}: {sk.hex()}")

    sk_path = os.path.join(results_dir, 'session_keys.json')
    with open(sk_path, 'w') as f:
        json.dump(session_keys, f, indent=2)
    print(f"Session keys written: {list(session_keys.keys())}")

    # ---- Phase 3: Parse HCI btsnoop log ----
    print(f"\nParsing HCI btsnoop log: {hci_log_path}")
    hci_events = parse_btsnoop(hci_log_path)
    print(f"Extracted {len(hci_events)} HCI events")

    # Build mapping: (rand_bytes, ediv_int) -> handle
    rand_ediv_to_handle = {}
    handle_to_key_size = {}

    for evt in hci_events:
        if evt['type'] == 'LE_LTK_REQUEST':
            key = (evt['rand'], evt['ediv'])
            rand_ediv_to_handle[key] = evt['handle']
            print(f"  LTK Request: handle=0x{evt['handle']:04x}, "
                  f"rand={evt['rand'].hex()}, ediv=0x{evt['ediv']:04x}")
        elif evt['type'] == 'KEY_SIZE':
            handle_to_key_size[evt['handle']] = evt['key_size']
            print(f"  Key Size: handle=0x{evt['handle']:04x}, "
                  f"key_size={evt['key_size']}")

    # ---- Phase 4: Cross-layer correlation ----
    # Map LL traces to HCI connection handles via Rand+EDIV
    trace_to_handle = {}
    for name, params in all_params.items():
        if 'rand' in params and 'ediv' in params:
            key = (params['rand'], params['ediv'])
            if key in rand_ediv_to_handle:
                handle = rand_ediv_to_handle[key]
                trace_to_handle[name] = handle
                print(f"\nCorrelation: {name} -> handle 0x{handle:04x}")

    # ---- Phase 5: Security audit ----
    findings = []

    # Check KEY_SIZE_REDUCTION (only visible via HCI)
    for name, handle in sorted(trace_to_handle.items()):
        if handle in handle_to_key_size:
            key_size = handle_to_key_size[handle]
            if key_size < 16:
                finding = {
                    'type': 'KEY_SIZE_REDUCTION',
                    'connection_handle': f'0x{handle:04x}',
                    'effective_key_size': key_size,
                    'trace_file': f'{name}.bllc',
                }
                findings.append(finding)
                print(f"FINDING: KEY_SIZE_REDUCTION on {name} "
                      f"(handle 0x{handle:04x}, key_size={key_size})")

    # Check SKD_REUSE (same SKDs||SKDm across connections)
    skd_to_traces = {}
    for name, params in all_params.items():
        skd_hex = (params['skds'] + params['skdm']).hex()
        if skd_hex not in skd_to_traces:
            skd_to_traces[skd_hex] = []
        skd_to_traces[skd_hex].append(f'{name}.bllc')

    for skd_hex, traces in skd_to_traces.items():
        if len(traces) > 1:
            finding = {
                'type': 'SKD_REUSE',
                'traces': sorted(traces),
            }
            findings.append(finding)
            print(f"FINDING: SKD_REUSE across {sorted(traces)}")

    audit_path = os.path.join(results_dir, 'security_audit.json')
    with open(audit_path, 'w') as f:
        json.dump({'findings': findings}, f, indent=2)
    print(f"\nSecurity audit: {len(findings)} finding(s)")


if __name__ == '__main__':
    main()
