#!/usr/bin/env python3
"""PTP IEEE C37.238 Power Profile Conformance Analysis Engine.

Uses tshark for pcap protocol analysis, Python for BMCA/conformance computation,
and linuxptp config format knowledge for ptp4l configuration remediation.

"""

import json
import struct
import math
import subprocess
import re
import os


# ─────────────────── pcap / tshark integration ───────────────────


def get_ptp_frame_numbers(pcap_path):
    """Use tshark to identify frames containing PTP traffic in a pcap file."""
    cmd = ['tshark', '-r', pcap_path, '-Y', 'ptp',
           '-T', 'fields', '-e', 'frame.number']
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return set(int(n) for n in result.stdout.strip().split('\n') if n.strip())


def read_pcap_frames(pcap_path):
    """Read all raw frame data from a pcap file, keyed by 1-based frame number."""
    frames = {}
    with open(pcap_path, 'rb') as f:
        magic = struct.unpack('<I', f.read(4))[0]
        if magic == 0xa1b2c3d4:
            endian = '<'
        elif magic == 0xd4c3b2a1:
            endian = '>'
        else:
            raise ValueError(f"Invalid pcap magic: 0x{magic:08x}")
        f.read(20)  # skip rest of global header
        n = 0
        while True:
            hdr = f.read(16)
            if len(hdr) < 16:
                break
            n += 1
            _, _, incl_len, _ = struct.unpack(endian + 'IIII', hdr)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break
            frames[n] = data
    return frames


def extract_ptp_payload(frame_data):
    """Extract PTP payload from Ethernet frame, handling 802.1Q VLAN tags."""
    if len(frame_data) < 14:
        return None
    etype = struct.unpack('!H', frame_data[12:14])[0]
    if etype == 0x8100:  # 802.1Q VLAN tagged
        if len(frame_data) < 18:
            return None
        etype = struct.unpack('!H', frame_data[16:18])[0]
        offset = 18
    else:
        offset = 14
    if etype == 0x88F7:  # PTP ethertype
        return frame_data[offset:]
    return None


# ─────────────────── PTP message parsing ───────────────────


def parse_announce(data):
    """Parse a PTP Announce message from raw bytes into a field dict."""
    if len(data) < 64:
        raise ValueError(f"Too short: {len(data)} bytes")

    r = {}
    r["message_type"] = data[0] & 0x0F
    r["domain_number"] = data[4]

    r["alternate_master_flag"] = bool(data[6] & 0x01)
    r["two_step_flag"] = bool(data[6] & 0x02)

    r["source_clock_identity"] = data[20:28].hex()
    r["source_port_number"] = struct.unpack_from("!H", data, 28)[0]
    r["sequence_id"] = struct.unpack_from("!H", data, 30)[0]
    r["log_message_interval"] = struct.unpack_from("!b", data, 33)[0]

    r["current_utc_offset"] = struct.unpack_from("!H", data, 44)[0]
    r["gm_priority1"] = data[47]
    r["clock_class"] = data[48]
    r["clock_accuracy"] = data[49]
    r["offset_scaled_log_var"] = struct.unpack_from("!H", data, 50)[0]
    r["gm_priority2"] = data[52]
    r["gm_identity"] = data[53:61].hex()
    r["steps_removed"] = struct.unpack_from("!H", data, 61)[0]
    r["time_source"] = data[63]

    if len(data) >= 86:
        tlv_type = struct.unpack_from("!H", data, 64)[0]
        tlv_len = struct.unpack_from("!H", data, 66)[0]
        if tlv_type == 0x0003 and tlv_len == 0x0012:
            r["tlv_gm_time_inaccuracy"] = struct.unpack_from("!I", data, 76)[0]
            r["tlv_network_time_inaccuracy"] = struct.unpack_from("!I", data, 80)[0]
        else:
            r["tlv_gm_time_inaccuracy"] = 0
            r["tlv_network_time_inaccuracy"] = 0
    else:
        r["tlv_gm_time_inaccuracy"] = 0
        r["tlv_network_time_inaccuracy"] = 0

    return r


# ─────────────────── BMCA logic ───────────────────


def qualify_announce(parsed, receiver_clock_identity):
    """Check Announce qualification per IEEE 1588-2008 Section 9.3.2.5."""
    if parsed["source_clock_identity"] == receiver_clock_identity:
        return False, "same_clock_identity"
    if parsed["steps_removed"] >= 255:
        return False, "steps_removed_ge_255"
    if parsed["alternate_master_flag"]:
        return False, "alternate_master_flag"
    return True, None


def dataset_cmp(a, b):
    """IEEE 1588-2008 Data Set Comparison Algorithm (Section 9.3.4)."""
    if a["gm_identity"] != b["gm_identity"]:
        for key in (
            "gm_priority1",
            "clock_class",
            "clock_accuracy",
            "offset_scaled_log_var",
            "gm_priority2",
        ):
            if a[key] != b[key]:
                return a[key] - b[key]
        a_id = int(a["gm_identity"], 16)
        b_id = int(b["gm_identity"], 16)
        if a_id != b_id:
            return -1 if a_id < b_id else 1
        return 0
    else:
        sr_diff = a["steps_removed"] - b["steps_removed"]
        if abs(sr_diff) > 1:
            return sr_diff
        if sr_diff == 0:
            a_sid = int(a.get("source_clock_identity", "0"), 16)
            b_sid = int(b.get("source_clock_identity", "0"), 16)
            if a_sid != b_sid:
                return -1 if a_sid < b_sid else 1
            return a.get("source_port_number", 0) - b.get("source_port_number", 0)
        return sr_diff


# ─────────────────── Timing statistics ───────────────────


def compute_timing(timestamps):
    """Compute timing stats per NISTIR 8002 Appendix D."""
    if len(timestamps) < 2:
        return None
    ts = sorted(timestamps)
    intervals = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
    n = len(intervals)
    mean = sum(intervals) / n
    variance = sum((x - mean) ** 2 for x in intervals) / n
    sigma = math.sqrt(variance)
    margin = 1.645 * sigma / math.sqrt(n)
    ci_low = mean - margin
    ci_high = mean + margin
    conformant = ci_low >= 0.7 and ci_high <= 1.3
    return {
        "mean_interval": round(mean, 6),
        "ci90_low": round(ci_low, 6),
        "ci90_high": round(ci_high, 6),
        "conformant": conformant,
    }


# ─────────────────── ptp4l config analysis ───────────────────


def analyze_ptp4l_config(config_path):
    """Analyze ptp4l config for Power Profile violations."""
    params = {}
    with open(config_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('['):
                parts = line.split()
                if len(parts) >= 2:
                    params[parts[0]] = parts[-1]

    required = {
        'priority1': '128',
        'priority2': '128',
        'logAnnounceInterval': '0',
        'logSyncInterval': '0',
        'logMinPdelayReqInterval': '0',
        'announceReceiptTimeout': '3',
        'delay_mechanism': 'P2P',
        'network_transport': 'L2',
    }

    violations = {}
    for param, req_val in required.items():
        cur_val = params.get(param)
        if cur_val is not None and cur_val != req_val:
            violations[param] = {"current": cur_val, "required": req_val}

    return violations


def write_corrected_config(original_path, output_path, violations):
    """Write corrected ptp4l config fixing all violations."""
    with open(original_path) as f:
        content = f.read()
    for param, info in violations.items():
        content = re.sub(
            rf'^{re.escape(param)}\s+.*$',
            f'{param}\t\t{info["required"]}',
            content,
            flags=re.MULTILINE,
        )
    with open(output_path, 'w') as f:
        f.write(content)


# ─────────────────── Main analysis pipeline ───────────────────


def main():
    # 1. Read topology and capture log
    with open('/app/scenario/topology.json') as f:
        topology = json.load(f)
    with open('/app/scenario/capture_log.json') as f:
        capture_log = json.load(f)

    clocks = topology['clocks']

    # 2. Use tshark to identify PTP frames in each pcap file
    pcap_files = ['segment1.pcap', 'segment2.pcap']
    ptp_frames_by_pcap = {}
    for pcap in pcap_files:
        path = f'/app/scenario/{pcap}'
        ptp_frames_by_pcap[pcap] = get_ptp_frame_numbers(path)

    # 3. Read raw frame data from pcap files
    raw_frames_by_pcap = {}
    for pcap in pcap_files:
        path = f'/app/scenario/{pcap}'
        raw_frames_by_pcap[pcap] = read_pcap_frames(path)

    # 4. Parse PTP payloads for tshark-identified PTP frames
    parsed_pcap = {}  # (pcap_file, frame_num) -> parsed PTP fields
    for pcap, ptp_frame_nums in ptp_frames_by_pcap.items():
        raw = raw_frames_by_pcap[pcap]
        for fnum in ptp_frame_nums:
            if fnum in raw:
                payload = extract_ptp_payload(raw[fnum])
                if payload and len(payload) >= 64:
                    parsed_pcap[(pcap, fnum)] = parse_announce(payload)

    # 5. Map capture_log entries to parsed frames
    parsed_all = {}
    for entry in capture_log:
        key = (entry['pcap_file'], entry['frame_number'])
        if key in parsed_pcap:
            p = dict(parsed_pcap[key])
            p['_recv_ts'] = entry['receive_timestamp']
            p['_recv_clock'] = entry['received_at_clock']
            p['_recv_port'] = entry['received_at_port']
            p['_src_name'] = entry['source_clock']
            parsed_all[entry['id']] = p

    # 6. Qualify / disqualify
    disqualified = {}
    qualified = {}

    for mid, p in parsed_all.items():
        rc = p['_recv_clock']
        rp = p['_recv_port']
        if rc not in clocks:
            continue
        ok, reason = qualify_announce(p, clocks[rc]['clock_identity'])
        if not ok:
            disqualified[mid] = reason
        else:
            qualified.setdefault((rc, rp), []).append(p)

    # 7. Foreign master window filter
    fm_qualified = {}
    for key, msgs in qualified.items():
        by_src = {}
        for m in msgs:
            by_src.setdefault(m['source_clock_identity'], []).append(m)
        ok_sources = {}
        for src, sm in by_src.items():
            sm.sort(key=lambda x: x['_recv_ts'])
            passed = False
            for i in range(len(sm)):
                cnt = 1
                for j in range(i + 1, len(sm)):
                    if sm[j]['_recv_ts'] - sm[i]['_recv_ts'] <= 4.0:
                        cnt += 1
                    else:
                        break
                if cnt >= 2:
                    passed = True
                    break
            if passed:
                ok_sources[src] = sm
        fm_qualified[key] = ok_sources

    # 8. BMCA per clock
    bmca_results = {}
    for cname, cinfo in clocks.items():
        nports = cinfo.get('num_ports', 1)

        d0 = {
            'gm_priority1': cinfo['priority1'],
            'clock_class': cinfo['clock_class'],
            'clock_accuracy': cinfo['clock_accuracy'],
            'offset_scaled_log_var': cinfo['offset_scaled_log_var'],
            'gm_priority2': cinfo['priority2'],
            'gm_identity': cinfo['clock_identity'],
            'steps_removed': 0,
            'source_clock_identity': cinfo['clock_identity'],
            'source_port_number': 0,
        }

        erbest = {}
        for port in range(1, nports + 1):
            sources = fm_qualified.get((cname, port), {})
            best = None
            for src_id, src_msgs in sources.items():
                newest = max(src_msgs, key=lambda x: x['_recv_ts'])
                ds = {
                    'gm_priority1': newest['gm_priority1'],
                    'clock_class': newest['clock_class'],
                    'clock_accuracy': newest['clock_accuracy'],
                    'offset_scaled_log_var': newest['offset_scaled_log_var'],
                    'gm_priority2': newest['gm_priority2'],
                    'gm_identity': newest['gm_identity'],
                    'steps_removed': newest['steps_removed'],
                    'source_clock_identity': newest['source_clock_identity'],
                    'source_port_number': newest['source_port_number'],
                }
                if best is None or dataset_cmp(ds, best) < 0:
                    best = ds
            if best is not None:
                erbest[port] = best

        ebest = None
        ebest_port = None
        for port, er in erbest.items():
            if ebest is None or dataset_cmp(er, ebest) < 0:
                ebest = er
                ebest_port = port

        port_states = {}
        selected_gm = cinfo['clock_identity']

        if ebest is not None:
            if dataset_cmp(d0, ebest) <= 0:
                for port in range(1, nports + 1):
                    port_states[str(port)] = 'MASTER'
            else:
                selected_gm = ebest['gm_identity']
                for port in range(1, nports + 1):
                    if port == ebest_port:
                        port_states[str(port)] = 'SLAVE'
                    elif port in erbest:
                        if erbest[port]['gm_identity'] == ebest['gm_identity']:
                            port_states[str(port)] = 'PASSIVE'
                        else:
                            port_states[str(port)] = 'MASTER'
                    else:
                        port_states[str(port)] = 'MASTER'
        else:
            for port in range(1, nports + 1):
                port_states[str(port)] = 'MASTER'

        if cinfo.get('slave_only', False):
            for p in port_states:
                if port_states[p] == 'MASTER':
                    port_states[p] = 'LISTENING'
            if ebest is not None:
                selected_gm = ebest['gm_identity']

        bmca_results[cname] = {
            'selected_grandmaster': selected_gm,
            'port_states': port_states,
        }

    # 9. Conformance checking
    conformance = {}
    for cname, cinfo in clocks.items():
        src_msgs = [
            parsed_all[mid]
            for mid in parsed_all
            if parsed_all[mid]['_src_name'] == cname
        ]
        if not src_msgs:
            continue

        cr = {}
        gmc = cinfo.get('gm_capable', False)
        so = cinfo.get('slave_only', False)

        lais = {m['log_message_interval'] for m in src_msgs}
        if gmc:
            cr['logAnnounceInterval'] = 'PASS' if lais == {0} else 'FAIL'
        else:
            cr['logAnnounceInterval'] = 'N/A'

        p1s = {m['gm_priority1'] for m in src_msgs}
        p2s = {m['gm_priority2'] for m in src_msgs}
        if so:
            cr['priority1'] = 'PASS' if p1s == {255} else 'FAIL'
            cr['priority2'] = 'PASS' if p2s == {255} else 'FAIL'
        elif gmc:
            cr['priority1'] = 'PASS' if p1s == {128} else 'FAIL'
            cr['priority2'] = 'PASS' if p2s == {128} else 'FAIL'
        else:
            cr['priority1'] = 'N/A'
            cr['priority2'] = 'N/A'

        doms = {m['domain_number'] for m in src_msgs}
        cr['domainNumber'] = 'PASS' if doms == {0} else 'FAIL'

        conformance[cname] = cr

    # 10. Timing statistics (deduplicated per source clock by sequence_id)
    timing_stats = {}
    for cname in clocks:
        src_msgs = [
            parsed_all[mid]
            for mid in parsed_all
            if parsed_all[mid]['_src_name'] == cname
        ]
        if not src_msgs:
            continue
        by_seq = {}
        for m in src_msgs:
            sid = m['sequence_id']
            ts = m['_recv_ts']
            if sid not in by_seq or ts < by_seq[sid]:
                by_seq[sid] = ts
        ts_list = sorted(by_seq.values())
        if len(ts_list) >= 2:
            timing_stats[cname] = compute_timing(ts_list)

    # 11. Analyze and fix ptp4l configuration
    config_path = '/app/configs/gm_b_ptp4l.conf'
    violations = analyze_ptp4l_config(config_path)
    write_corrected_config(config_path, '/app/corrected_gm_b.cfg', violations)

    # 12. Build output
    clean_parsed = {}
    for mid, p in parsed_all.items():
        clean_parsed[mid] = {
            k: v for k, v in p.items() if not k.startswith('_')
        }

    results = {
        'parsed_fields': clean_parsed,
        'disqualified_messages': disqualified,
        'bmca_results': bmca_results,
        'conformance': conformance,
        'timing_stats': timing_stats,
        'config_violations': {'gm_b': violations},
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print('Results written to /app/results.json')
    print(f'Corrected config written to /app/corrected_gm_b.cfg')


if __name__ == '__main__':
    main()
