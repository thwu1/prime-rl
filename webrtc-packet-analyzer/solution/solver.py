#!/usr/bin/env python3
"""
WebRTC multi-capture session forensic analyzer.
Merges partial captures, verifies session integrity, and performs
full protocol-level analysis producing a structured diagnostic report.
"""

import struct
import hmac as hmac_mod
import hashlib
import json
import subprocess
import re
import socket


MAGIC_COOKIE = 0x2112A442

STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_RESPONSE = 0x0101

ATTR_USERNAME = 0x0006
ATTR_MESSAGE_INTEGRITY = 0x0008
ATTR_USE_CANDIDATE = 0x0025


def run_cmd(cmd, shell=False):
    """Run a command and return stdout."""
    result = subprocess.run(cmd, capture_output=True, text=True, shell=shell)
    return result.stdout, result.returncode


def capinfos_packet_count(filepath):
    """Get packet count from capinfos."""
    stdout, rc = run_cmd(['capinfos', '-c', filepath])
    if rc != 0:
        raise RuntimeError(f"capinfos failed on {filepath}")
    for line in stdout.split('\n'):
        if 'Number of packets' in line:
            return int(line.split(':')[1].strip())
    raise RuntimeError(f"Could not parse packet count from capinfos for {filepath}")


def capinfos_duration(filepath):
    """Get capture duration in seconds from capinfos."""
    stdout, rc = run_cmd(['capinfos', '-u', filepath])
    if rc != 0:
        raise RuntimeError(f"capinfos failed on {filepath}")
    for line in stdout.split('\n'):
        if 'Capture duration' in line:
            match = re.search(r'([\d.]+)', line.split(':', 1)[1])
            if match:
                return float(match.group(1))
    raise RuntimeError(f"Could not parse duration from capinfos for {filepath}")


def verify_hmac(config_path, hmac_path, key_path):
    """Verify HMAC-SHA256 signature using openssl dgst."""
    with open(key_path) as f:
        key = f.read().strip()

    stdout, rc = run_cmd(
        f'openssl dgst -sha256 -hmac "{key}" {config_path}',
        shell=True
    )
    if rc != 0:
        return False

    # Parse openssl output: "HMAC-SHA2-256(file)= hexdigest" or similar
    computed_hmac = stdout.strip().split('= ')[-1].strip()

    with open(hmac_path) as f:
        expected_hmac = f.read().strip()

    return computed_hmac == expected_hmac


def read_pcap(filename):
    """Parse a libpcap file and extract UDP payloads with IP:port metadata."""
    packets = []
    with open(filename, 'rb') as f:
        ghdr = f.read(24)
        if len(ghdr) < 24:
            return packets
        magic = struct.unpack("<I", ghdr[0:4])[0]
        if magic == 0xa1b2c3d4:
            endian = "<"
        elif magic == 0xd4c3b2a1:
            endian = ">"
        else:
            raise ValueError(f"Not a valid pcap file (magic: {hex(magic)})")

        while True:
            phdr = f.read(16)
            if len(phdr) < 16:
                break
            ts_sec, ts_usec, incl_len, orig_len = struct.unpack(f"{endian}IIII", phdr)
            frame = f.read(incl_len)
            if len(frame) < incl_len:
                break

            timestamp_us = ts_sec * 1_000_000 + ts_usec

            # Ethernet header: 14 bytes
            if len(frame) < 14:
                continue
            ethertype = struct.unpack("!H", frame[12:14])[0]
            if ethertype != 0x0800:
                continue

            # IPv4 header
            ip_start = 14
            if len(frame) < ip_start + 20:
                continue
            ihl = (frame[ip_start] & 0x0F) * 4
            protocol = frame[ip_start + 9]
            if protocol != 17:  # Not UDP
                continue
            src_ip = socket.inet_ntoa(frame[ip_start + 12:ip_start + 16])
            dst_ip = socket.inet_ntoa(frame[ip_start + 16:ip_start + 20])

            # UDP header
            udp_start = ip_start + ihl
            if len(frame) < udp_start + 8:
                continue
            src_port, dst_port = struct.unpack("!HH", frame[udp_start:udp_start + 4])
            udp_len = struct.unpack("!H", frame[udp_start + 4:udp_start + 6])[0]
            payload = frame[udp_start + 8:udp_start + 8 + (udp_len - 8)]

            packets.append({
                "timestamp_us": timestamp_us,
                "src": f"{src_ip}:{src_port}",
                "dst": f"{dst_ip}:{dst_port}",
                "payload": payload
            })

    return packets


def classify_packet(payload):
    """Classify a WebRTC multiplexed packet by its first byte."""
    if len(payload) < 1:
        return "unknown"
    b0 = payload[0]
    if 0 <= b0 <= 3:
        if len(payload) >= 8:
            magic = struct.unpack("!I", payload[4:8])[0]
            if magic == MAGIC_COOKIE:
                return "stun"
        return "unknown"
    elif 20 <= b0 <= 63:
        return "dtls"
    elif 128 <= b0 <= 191:
        if len(payload) >= 2:
            b1 = payload[1]
            if 200 <= b1 <= 211:
                return "rtcp"
            else:
                return "rtp"
        return "unknown"
    else:
        return "unknown"


def parse_stun_attributes(payload):
    """Extract TLV attributes from a STUN message."""
    attrs = []
    offset = 20
    while offset + 4 <= len(payload):
        attr_type, attr_len = struct.unpack("!HH", payload[offset:offset + 4])
        offset += 4
        if offset + attr_len > len(payload):
            break
        attr_value = payload[offset:offset + attr_len]
        attrs.append((attr_type, attr_len, attr_value, offset - 4))
        padded_len = attr_len + ((4 - (attr_len % 4)) % 4)
        offset += padded_len
    return attrs


def verify_stun_integrity(payload, key):
    """Verify STUN MESSAGE-INTEGRITY attribute."""
    attrs = parse_stun_attributes(payload)
    mi_attr = None
    mi_offset = None
    for attr_type, attr_len, attr_value, attr_pos in attrs:
        if attr_type == ATTR_MESSAGE_INTEGRITY:
            mi_attr = attr_value
            mi_offset = attr_pos
            break

    if mi_attr is None:
        return None

    msg_type = struct.unpack("!HH", payload[0:4])[0]
    mi_end = mi_offset + 4 + 20
    adjusted_length = mi_end - 20

    header = struct.pack("!HH", msg_type, adjusted_length) + payload[4:20]
    hmac_input = header + payload[20:mi_offset]

    expected = hmac_mod.new(key.encode('utf-8'), hmac_input, hashlib.sha1).digest()
    return hmac_mod.compare_digest(expected, mi_attr)


def parse_rtp_header(payload):
    """Parse an RTP packet header."""
    if len(payload) < 12:
        return None
    b0, b1 = payload[0], payload[1]
    version = (b0 >> 6) & 0x03
    padding = (b0 >> 5) & 0x01
    extension = (b0 >> 4) & 0x01
    cc = b0 & 0x0F
    marker = (b1 >> 7) & 0x01
    pt = b1 & 0x7F
    seq, ts, ssrc = struct.unpack("!HII", payload[2:12])
    return {
        "version": version, "padding": padding, "extension": extension,
        "cc": cc, "marker": marker, "pt": pt, "seq": seq,
        "timestamp": ts, "ssrc": ssrc
    }


def parse_rtcp_header(payload):
    """Parse an RTCP packet header."""
    if len(payload) < 4:
        return None
    b0, pt = payload[0], payload[1]
    version = (b0 >> 6) & 0x03
    rc = b0 & 0x1F
    length = struct.unpack("!H", payload[2:4])[0]
    return {"version": version, "pt": pt, "rc": rc, "length": length}


def main():
    # === Step 1: Merge captures using mergecap ===
    print("Merging captures with mergecap...")
    merge_result = subprocess.run([
        'mergecap', '-F', 'pcap', '-w', '/app/merged.pcap',
        '/app/captures/tap_alpha.pcap', '/app/captures/tap_beta.pcap'
    ], capture_output=True, text=True)
    if merge_result.returncode != 0:
        raise RuntimeError(f"mergecap failed: {merge_result.stderr}")
    print("Merged capture written to /app/merged.pcap")

    # === Step 2: Extract capture metadata using capinfos ===
    print("Extracting capture metadata with capinfos...")
    alpha_count = capinfos_packet_count('/app/captures/tap_alpha.pcap')
    beta_count = capinfos_packet_count('/app/captures/tap_beta.pcap')
    merged_count = capinfos_packet_count('/app/merged.pcap')
    duration = capinfos_duration('/app/merged.pcap')

    print(f"  tap_alpha: {alpha_count} packets")
    print(f"  tap_beta: {beta_count} packets")
    print(f"  merged: {merged_count} packets, {duration}s duration")

    # === Step 3: Verify session config HMAC using openssl ===
    print("Verifying session config HMAC with openssl...")
    hmac_valid = verify_hmac(
        '/app/session_config.json',
        '/app/session_integrity.hmac',
        '/app/hmac_key.txt'
    )
    print(f"  HMAC valid: {hmac_valid}")

    # === Step 4: Load session config ===
    with open("/app/session_config.json") as f:
        config = json.load(f)

    local_ufrag = config["local_ufrag"]
    local_pwd = config["local_pwd"]
    remote_ufrag = config["remote_ufrag"]
    remote_pwd = config["remote_pwd"]
    clock_rates = {int(k): v for k, v in config["rtp_clock_rates"].items()}

    # === Step 5: Parse merged pcap and analyze protocols ===
    print("Analyzing merged capture...")
    packets = read_pcap("/app/merged.pcap")

    # Counters
    counts = {"total": 0, "stun": 0, "dtls": 0, "rtp": 0, "rtcp": 0, "unknown": 0}
    stun_stats = {
        "binding_requests": 0, "binding_responses": 0,
        "integrity_valid": 0, "integrity_invalid": 0,
        "nominated_pair": {"src": "", "dst": ""}
    }

    txn_keys = {}
    rtp_streams = {}
    rtcp_sr = 0
    rtcp_rr = 0

    for pkt in packets:
        payload = pkt["payload"]
        proto = classify_packet(payload)
        counts["total"] += 1
        counts[proto] += 1

        if proto == "stun":
            msg_type = struct.unpack("!H", payload[0:2])[0]
            txn_id = payload[8:20]

            if msg_type == STUN_BINDING_REQUEST:
                stun_stats["binding_requests"] += 1
            elif msg_type == STUN_BINDING_RESPONSE:
                stun_stats["binding_responses"] += 1

            attrs = parse_stun_attributes(payload)
            username_str = None
            has_mi = False
            has_use_candidate = False

            for attr_type, attr_len, attr_value, _ in attrs:
                if attr_type == ATTR_USERNAME:
                    username_str = attr_value.decode('utf-8', errors='replace')
                elif attr_type == ATTR_MESSAGE_INTEGRITY:
                    has_mi = True
                elif attr_type == ATTR_USE_CANDIDATE:
                    has_use_candidate = True

            key = None
            if username_str:
                parts = username_str.split(":")
                if len(parts) >= 1:
                    first_ufrag = parts[0]
                    if first_ufrag == local_ufrag:
                        key = local_pwd
                    elif first_ufrag == remote_ufrag:
                        key = remote_pwd
                if key:
                    txn_keys[txn_id] = key
            else:
                key = txn_keys.get(txn_id)

            if has_mi and key:
                valid = verify_stun_integrity(payload, key)
                if valid:
                    stun_stats["integrity_valid"] += 1
                else:
                    stun_stats["integrity_invalid"] += 1
            elif has_mi:
                stun_stats["integrity_invalid"] += 1

            if has_use_candidate and msg_type == STUN_BINDING_REQUEST:
                stun_stats["nominated_pair"]["src"] = pkt["src"]
                stun_stats["nominated_pair"]["dst"] = pkt["dst"]

        elif proto == "rtp":
            hdr = parse_rtp_header(payload)
            if hdr:
                ssrc = hdr["ssrc"]
                if ssrc not in rtp_streams:
                    rtp_streams[ssrc] = {
                        "seqs": [], "arrivals": [], "timestamps": [], "pt": hdr["pt"]
                    }
                rtp_streams[ssrc]["seqs"].append(hdr["seq"])
                rtp_streams[ssrc]["arrivals"].append(pkt["timestamp_us"])
                rtp_streams[ssrc]["timestamps"].append(hdr["timestamp"])

        elif proto == "rtcp":
            hdr = parse_rtcp_header(payload)
            if hdr:
                if hdr["pt"] == 200:
                    rtcp_sr += 1
                elif hdr["pt"] == 201:
                    rtcp_rr += 1

    # Compute RTP statistics
    rtp_analysis = {}
    for ssrc, stream in rtp_streams.items():
        seqs = stream["seqs"]
        arrivals = stream["arrivals"]
        timestamps = stream["timestamps"]
        pt = stream["pt"]
        clock_rate = clock_rates.get(pt, 48000)

        first_seq = min(seqs)
        last_seq = max(seqs)
        expected = last_seq - first_seq + 1
        received = len(seqs)
        lost = expected - received
        loss_rate = lost / expected if expected > 0 else 0.0

        jitter = 0.0
        for i in range(1, len(arrivals)):
            arrival_diff_rtp = (arrivals[i] - arrivals[i - 1]) * clock_rate / 1_000_000.0
            ts_diff = float(timestamps[i] - timestamps[i - 1])
            d = abs(arrival_diff_rtp - ts_diff)
            jitter = jitter + (d - jitter) / 16.0

        duration_ms = (arrivals[-1] - arrivals[0]) / 1000.0 if len(arrivals) > 1 else 0.0

        ssrc_hex = f"0x{ssrc:08x}"
        rtp_analysis[ssrc_hex] = {
            "packet_count": received,
            "loss_count": lost,
            "loss_rate": round(loss_rate, 4),
            "jitter": round(jitter, 2),
            "duration_ms": round(duration_ms, 3),
            "first_seq": first_seq,
            "last_seq": last_seq
        }

    # === Step 6: Build and write report ===
    report = {
        "capture_info": {
            "tap_alpha_packets": alpha_count,
            "tap_beta_packets": beta_count,
            "merged_total_packets": merged_count,
            "capture_duration_sec": round(duration, 3)
        },
        "session_integrity": {
            "config_hmac_valid": hmac_valid
        },
        "packet_counts": counts,
        "stun_analysis": stun_stats,
        "rtp_analysis": rtp_analysis,
        "rtcp_analysis": {
            "sender_reports": rtcp_sr,
            "receiver_reports": rtcp_rr
        }
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to /app/report.json")


if __name__ == "__main__":
    main()
