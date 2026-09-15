#!/usr/bin/env python3
"""
Passive TCP OS fingerprinter (p0f-style).
Reads standard libpcap files, extracts TCP SYN signatures, matches against
a p0f-compatible fingerprint database.

"""
import struct
import socket
import json
import sys

# ---------- pcap parsing ----------

PCAP_MAGIC_LE = 0xa1b2c3d4
PCAP_MAGIC_BE = 0xd4c3b2a1


def parse_pcap(filepath):
    """Parse a libpcap file. Yields (timestamp_float, raw_bytes) per packet."""
    with open(filepath, 'rb') as f:
        ghdr = f.read(24)
        if len(ghdr) < 24:
            raise ValueError("Truncated pcap global header")
        magic = struct.unpack('<I', ghdr[:4])[0]
        if magic == PCAP_MAGIC_LE:
            endian = '<'
        elif magic == PCAP_MAGIC_BE:
            endian = '>'
        else:
            raise ValueError(f"Unknown pcap magic: {hex(magic)}")

        _ver_maj, _ver_min, _tz, _sigfigs, _snaplen, linktype = struct.unpack(
            endian + 'HHiIII', ghdr[4:])
        if linktype != 1:
            raise ValueError(f"Unsupported link type {linktype}; only Ethernet (1) supported")

        while True:
            phdr = f.read(16)
            if len(phdr) < 16:
                break
            ts_sec, ts_usec, incl_len, _orig_len = struct.unpack(endian + 'IIII', phdr)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break
            yield (ts_sec + ts_usec / 1_000_000.0, data)


# ---------- protocol dissectors ----------

def parse_ethernet(data):
    """Return (ethertype, payload) or None."""
    if len(data) < 14:
        return None
    ethertype = struct.unpack('!H', data[12:14])[0]
    return (ethertype, data[14:])


def parse_ipv4(data):
    """Return dict of IPv4 header fields + payload, or None."""
    if len(data) < 20:
        return None
    vhl = data[0]
    version = (vhl >> 4) & 0xf
    ihl = vhl & 0xf
    if version != 4 or ihl < 5:
        return None
    hdr_len = ihl * 4
    if len(data) < hdr_len:
        return None

    tos = data[1]
    total_len = struct.unpack('!H', data[2:4])[0]
    ident = struct.unpack('!H', data[4:6])[0]
    flags_frag = struct.unpack('!H', data[6:8])[0]
    ttl = data[8]
    protocol = data[9]
    src_ip = data[12:16]
    dst_ip = data[16:20]

    df = bool(flags_frag & 0x4000)
    mbz = bool(flags_frag & 0x8000)
    ecn = tos & 0x03

    end = min(total_len, len(data))
    payload = data[hdr_len:end]

    return {
        'version': version,
        'tos': tos,
        'ident': ident,
        'df': df,
        'mbz': mbz,
        'ttl': ttl,
        'protocol': protocol,
        'src_ip': src_ip,
        'dst_ip': dst_ip,
        'ip_opts_len': hdr_len - 20,
        'ecn': ecn,
        'payload': payload,
    }


def parse_tcp(data):
    """Return dict of TCP header fields + options_data + payload, or None."""
    if len(data) < 20:
        return None
    src_port, dst_port = struct.unpack('!HH', data[0:4])
    seq = struct.unpack('!I', data[4:8])[0]
    ack_seq = struct.unpack('!I', data[8:12])[0]
    doff_flags = struct.unpack('!H', data[12:14])[0]
    data_offset = (doff_flags >> 12) & 0xf
    window = struct.unpack('!H', data[14:16])[0]
    urg_ptr = struct.unpack('!H', data[18:20])[0]

    flags = {
        'syn': bool(doff_flags & 0x002),
        'ack': bool(doff_flags & 0x010),
        'fin': bool(doff_flags & 0x001),
        'rst': bool(doff_flags & 0x004),
        'psh': bool(doff_flags & 0x008),
        'urg': bool(doff_flags & 0x020),
    }

    tcp_hdr_len = data_offset * 4
    if tcp_hdr_len < 20:
        return None

    options_end = min(tcp_hdr_len, len(data))
    options_data = data[20:options_end]
    payload = data[tcp_hdr_len:] if tcp_hdr_len <= len(data) else b''

    return {
        'src_port': src_port,
        'dst_port': dst_port,
        'seq': seq,
        'ack_seq': ack_seq,
        'data_offset': data_offset,
        'flags': flags,
        'window': window,
        'urg_ptr': urg_ptr,
        'options_data': options_data,
        'payload': payload,
    }


# ---------- TCP option parsing ----------

def parse_tcp_options(data):
    """Parse TCP options bytes. Returns list of (name, value_or_none) tuples."""
    options = []
    i = 0
    total = len(data)

    while i < total:
        kind = data[i]

        if kind == 0:  # EOL
            pad = total - i - 1
            options.append(('eol', pad))
            break
        elif kind == 1:  # NOP
            options.append(('nop', None))
            i += 1
        elif kind == 2:  # MSS
            if i + 4 > total:
                break
            mss_val = struct.unpack('!H', data[i+2:i+4])[0]
            options.append(('mss', mss_val))
            i += data[i+1]
        elif kind == 3:  # Window Scale
            if i + 3 > total:
                break
            ws_val = data[i+2]
            options.append(('ws', ws_val))
            i += data[i+1]
        elif kind == 4:  # SACK Permitted
            if i + 2 > total:
                break
            options.append(('sok', None))
            i += data[i+1]
        elif kind == 5:  # SACK
            if i + 2 > total:
                break
            opt_len = data[i+1]
            options.append(('sack', None))
            i += opt_len
        elif kind == 8:  # Timestamps
            if i + 10 > total:
                break
            ts1 = struct.unpack('!I', data[i+2:i+6])[0]
            ts2 = struct.unpack('!I', data[i+6:i+10])[0]
            options.append(('ts', (ts1, ts2)))
            i += data[i+1]
        else:
            # Unknown option
            if i + 2 > total:
                break
            opt_len = data[i+1]
            if opt_len < 2:
                break
            options.append((f'?{kind}', None))
            i += opt_len

    return options


# ---------- signature computation ----------

COMMON_TTLS = [32, 64, 128, 255]


def guess_initial_ttl(observed):
    """Guess original TTL from observed value."""
    for ittl in COMMON_TTLS:
        if observed <= ittl:
            return ittl
    return 255


def ip_to_str(ip_bytes):
    return socket.inet_ntoa(ip_bytes)


def compute_signature(ip_info, tcp_info, tcp_options):
    """Compute p0f-compatible signature string."""
    ver = ip_info['version']
    ittl = guess_initial_ttl(ip_info['ttl'])
    olen = ip_info['ip_opts_len']

    # Extract MSS and WS values from options
    mss_val = None
    ws_val = None
    for opt in tcp_options:
        if opt[0] == 'mss':
            mss_val = opt[1]
        elif opt[0] == 'ws':
            ws_val = opt[1]

    mss_str = str(mss_val) if mss_val is not None else '*'

    # Window size representation
    window = tcp_info['window']
    wsize_str = str(window)
    if mss_val is not None and mss_val > 0:
        if window % mss_val == 0:
            wsize_str = f"mss*{window // mss_val}"
        elif window % (mss_val + 40) == 0:
            wsize_str = f"mtu*{window // (mss_val + 40)}"

    scale_str = str(ws_val) if ws_val is not None else '*'

    # Option layout
    olayout_parts = []
    for opt in tcp_options:
        name = opt[0]
        if name == 'eol':
            olayout_parts.append(f"eol+{opt[1]}")
        elif name in ('nop', 'mss', 'ws', 'sok', 'sack', 'ts'):
            olayout_parts.append(name)
        elif name.startswith('?'):
            olayout_parts.append(name)
    olayout = ','.join(olayout_parts)

    # Quirks — canonical order
    quirks = []
    if ip_info['df']:
        quirks.append('df')
    if ip_info['df'] and ip_info['ident'] != 0:
        quirks.append('id+')
    if not ip_info['df'] and ip_info['ident'] == 0:
        quirks.append('id-')
    if ip_info['ecn'] != 0:
        quirks.append('ecn')
    if ip_info['mbz']:
        quirks.append('0+')
    if tcp_info['seq'] == 0:
        quirks.append('seq-')
    if not tcp_info['flags']['ack'] and tcp_info['ack_seq'] != 0:
        quirks.append('ack+')
    if tcp_info['flags']['ack'] and tcp_info['ack_seq'] == 0:
        quirks.append('ack-')
    if not tcp_info['flags']['urg'] and tcp_info['urg_ptr'] != 0:
        quirks.append('uptr+')
    if tcp_info['flags']['urg']:
        quirks.append('urgf+')
    if tcp_info['flags']['psh']:
        quirks.append('pushf+')

    # Timestamp-related quirks
    for opt in tcp_options:
        if opt[0] == 'ts':
            ts1, ts2 = opt[1]
            if ts1 == 0:
                quirks.append('ts1-')
            if ts2 != 0:
                quirks.append('ts2+')
            break

    if ws_val is not None and ws_val > 14:
        quirks.append('exws')

    quirks_str = ','.join(quirks)

    # Payload class
    pclass = '+' if len(tcp_info['payload']) > 0 else '0'

    return f"{ver}:{ittl}:{olen}:{mss_str}:{wsize_str},{scale_str}:{olayout}:{quirks_str}:{pclass}"


# ---------- fingerprint database ----------

def parse_fingerprint_db(filepath):
    """Parse p0f-style fingerprint database. Returns list of {section, label, sig}."""
    entries = []
    current_section = None
    current_label = None

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(';'):
                continue
            if line.startswith('[') and line.endswith(']'):
                current_section = line[1:-1]
                continue
            if line.startswith('label'):
                _, _, val = line.partition('=')
                current_label = val.strip()
            elif line.startswith('sig'):
                _, _, val = line.partition('=')
                sig_str = val.strip()
                entries.append({
                    'section': current_section,
                    'label': current_label,
                    'sig': sig_str,
                })

    return entries


def match_signature(observed_sig, db_entries):
    """Match an observed signature against database entries. Returns first match or None."""
    obs_parts = observed_sig.split(':')
    if len(obs_parts) != 8:
        return None

    obs_ver, obs_ittl, obs_olen, obs_mss = obs_parts[0], obs_parts[1], obs_parts[2], obs_parts[3]
    obs_ws_combined = obs_parts[4]
    obs_olayout = obs_parts[5]
    obs_quirks = obs_parts[6]
    obs_pclass = obs_parts[7]

    obs_wsize, obs_scale = obs_ws_combined.split(',', 1) if ',' in obs_ws_combined else (obs_ws_combined, '*')
    obs_quirk_set = set(obs_quirks.split(',')) if obs_quirks else set()

    for entry in db_entries:
        if entry.get('section') != 'tcp:request':
            continue
        db_parts = entry['sig'].split(':')
        if len(db_parts) != 8:
            continue

        db_ver, db_ittl, db_olen, db_mss = db_parts[0], db_parts[1], db_parts[2], db_parts[3]
        db_ws_combined = db_parts[4]
        db_olayout = db_parts[5]
        db_quirks = db_parts[6]
        db_pclass = db_parts[7]

        db_wsize, db_scale = db_ws_combined.split(',', 1) if ',' in db_ws_combined else (db_ws_combined, '*')
        db_quirk_set = set(db_quirks.split(',')) if db_quirks else set()

        if db_ver != '*' and db_ver != obs_ver:
            continue
        if db_ittl != '*' and db_ittl != obs_ittl:
            continue
        if db_olen != '*' and db_olen != obs_olen:
            continue
        if db_mss != '*' and db_mss != obs_mss:
            continue
        if db_wsize != '*' and db_wsize != obs_wsize:
            continue
        if db_scale != '*' and db_scale != obs_scale:
            continue
        if db_olayout != obs_olayout:
            continue
        if db_quirk_set != obs_quirk_set:
            continue
        if db_pclass != '*' and db_pclass != obs_pclass:
            continue

        return entry

    return None


# ---------- main ----------

def analyze_pcap(pcap_path, db_path, output_path):
    """Full analysis pipeline."""
    db_entries = parse_fingerprint_db(db_path)
    results = []

    for ts, raw in parse_pcap(pcap_path):
        eth = parse_ethernet(raw)
        if eth is None:
            continue
        ethertype, eth_payload = eth
        if ethertype != 0x0800:
            continue

        ip_info = parse_ipv4(eth_payload)
        if ip_info is None:
            continue
        if ip_info['protocol'] != 6:
            continue

        tcp_info = parse_tcp(ip_info['payload'])
        if tcp_info is None:
            continue

        # Only SYN-only packets (SYN=1, ACK=0)
        if not tcp_info['flags']['syn'] or tcp_info['flags']['ack']:
            continue

        tcp_options = parse_tcp_options(tcp_info['options_data'])
        sig = compute_signature(ip_info, tcp_info, tcp_options)
        match = match_signature(sig, db_entries)

        results.append({
            'src_ip': ip_to_str(ip_info['src_ip']),
            'dst_ip': ip_to_str(ip_info['dst_ip']),
            'src_port': tcp_info['src_port'],
            'dst_port': tcp_info['dst_port'],
            'signature': sig,
            'os': match['label'] if match else 'unknown',
        })

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == '__main__':
    pcap_path = sys.argv[1] if len(sys.argv) > 1 else '/app/traffic.pcap'
    db_path = sys.argv[2] if len(sys.argv) > 2 else '/app/fingerprints.db'
    output_path = sys.argv[3] if len(sys.argv) > 3 else '/app/results.json'
    analyze_pcap(pcap_path, db_path, output_path)
