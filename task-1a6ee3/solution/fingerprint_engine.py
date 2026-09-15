#!/usr/bin/env python3
"""
p0f-compatible passive TCP/IP fingerprinting engine.

Parses a PCAP file containing TCP packets, extracts p0f-format signatures
from SYN packets, matches them against a fingerprint database, and writes
identification results to JSON.

Implements raw protocol parsing: PCAP -> Ethernet -> IPv4 -> TCP headers
and TCP options, without external packet-parsing libraries.
"""

import struct
import json
import socket
import os
import sys

# TCP option kind constants
TCPOPT_EOL = 0
TCPOPT_NOP = 1
TCPOPT_MSS = 2
TCPOPT_WSCALE = 3
TCPOPT_SACKOK = 4
TCPOPT_SACK = 5
TCPOPT_TSTAMP = 8

# IP header constants
IP4_DF = 0x4000
IP4_MBZ = 0x8000

# Standard initial TTL values used by common operating systems
STANDARD_TTLS = [32, 64, 128, 255]


def guess_initial_ttl(observed_ttl):
    """Guess the initial TTL by rounding up to the nearest standard value."""
    for ttl in STANDARD_TTLS:
        if observed_ttl <= ttl:
            return ttl
    return 255


# ---------------------------------------------------------------------------
# PCAP Parser
# ---------------------------------------------------------------------------

def parse_pcap(filename):
    """Parse a PCAP file and return a list of raw packet byte strings.

    Handles both little-endian (0xa1b2c3d4) and big-endian (0xd4c3b2a1)
    PCAP formats.  Only link type 1 (Ethernet) is supported.
    """
    packets = []
    with open(filename, 'rb') as f:
        magic_bytes = f.read(4)
        if len(magic_bytes) < 4:
            return packets

        magic = struct.unpack('<I', magic_bytes)[0]
        if magic == 0xa1b2c3d4:
            endian = '<'
        elif magic == 0xd4c3b2a1:
            endian = '>'
        else:
            raise ValueError(f"Invalid PCAP magic number: {magic:#010x}")

        _ver_major, _ver_minor = struct.unpack(f'{endian}HH', f.read(4))
        _thiszone, _sigfigs, _snaplen, network = struct.unpack(
            f'{endian}iIII', f.read(16))

        if network != 1:
            raise ValueError(f"Unsupported PCAP link type: {network} (need Ethernet/1)")

        while True:
            rec_hdr = f.read(16)
            if len(rec_hdr) < 16:
                break
            _ts_sec, _ts_usec, incl_len, _orig_len = struct.unpack(
                f'{endian}IIII', rec_hdr)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break
            packets.append(data)

    return packets


# ---------------------------------------------------------------------------
# Protocol Parsers
# ---------------------------------------------------------------------------

def parse_ethernet(raw):
    """Parse an Ethernet frame.

    Returns (ip_payload_bytes, ethertype) or (None, None) on failure.
    """
    if len(raw) < 14:
        return None, None
    ethertype = struct.unpack('!H', raw[12:14])[0]
    return raw[14:], ethertype


def parse_ipv4(data):
    """Parse an IPv4 header.

    Returns (ip_info_dict, tcp_payload_bytes) or (None, None) on failure.
    """
    if len(data) < 20:
        return None, None

    ver_ihl = data[0]
    version = (ver_ihl >> 4) & 0x0F
    ihl = ver_ihl & 0x0F
    header_len = ihl * 4

    if version != 4 or header_len < 20 or len(data) < header_len:
        return None, None

    tos = data[1]
    total_len = struct.unpack('!H', data[2:4])[0]
    identification = struct.unpack('!H', data[4:6])[0]
    flags_frag = struct.unpack('!H', data[6:8])[0]
    ttl = data[8]
    protocol = data[9]
    src_ip = socket.inet_ntoa(data[12:16])
    dst_ip = socket.inet_ntoa(data[16:20])

    ip_info = {
        'version': version,
        'header_len': header_len,
        'tos': tos,
        'total_len': total_len,
        'identification': identification,
        'flags_frag': flags_frag,
        'df': bool(flags_frag & IP4_DF),
        'mbz': bool(flags_frag & IP4_MBZ),
        'ttl': ttl,
        'protocol': protocol,
        'src_ip': src_ip,
        'dst_ip': dst_ip,
        'ip_opt_len': header_len - 20,
    }

    end = min(total_len, len(data))
    return ip_info, data[header_len:end]


def parse_tcp_options(opt_bytes):
    """Parse TCP options from raw bytes.

    Returns a list of (name, info_dict) tuples where name is one of:
    'mss', 'nop', 'ws', 'sok', 'sack', 'ts', 'eol', or '?'.
    """
    options = []
    pos = 0
    opt_end = len(opt_bytes)

    while pos < opt_end:
        kind = opt_bytes[pos]

        if kind == TCPOPT_EOL:
            remaining = opt_end - pos - 1
            # Check if any padding bytes after EOL are non-zero
            eol_nz = False
            for j in range(pos + 1, opt_end):
                if opt_bytes[j] != 0:
                    eol_nz = True
                    break
            options.append(('eol', {'pad': remaining, 'nz': eol_nz}))
            break

        if kind == TCPOPT_NOP:
            options.append(('nop', {}))
            pos += 1
            continue

        # All other options have at least a length byte
        if pos + 1 >= opt_end:
            break
        length = opt_bytes[pos + 1]
        if length < 2 or pos + length > opt_end:
            break

        if kind == TCPOPT_MSS:
            if length >= 4 and pos + 4 <= opt_end:
                mss_val = struct.unpack('!H', opt_bytes[pos + 2:pos + 4])[0]
                options.append(('mss', {'value': mss_val, 'len': length}))
            pos += length
        elif kind == TCPOPT_WSCALE:
            if length >= 3 and pos + 3 <= opt_end:
                ws_val = opt_bytes[pos + 2]
                options.append(('ws', {'value': ws_val, 'len': length}))
            pos += length
        elif kind == TCPOPT_SACKOK:
            options.append(('sok', {'len': length}))
            pos += length
        elif kind == TCPOPT_SACK:
            options.append(('sack', {'len': length}))
            pos += length
        elif kind == TCPOPT_TSTAMP:
            if length >= 10 and pos + 10 <= opt_end:
                ts_val = struct.unpack('!I', opt_bytes[pos + 2:pos + 6])[0]
                ts_ecr = struct.unpack('!I', opt_bytes[pos + 6:pos + 10])[0]
                options.append(('ts', {
                    'ts_val': ts_val, 'ts_ecr': ts_ecr, 'len': length}))
            pos += length
        else:
            options.append(('?', {'kind': kind, 'len': length}))
            pos += length

    return options


def parse_tcp(data):
    """Parse a TCP header including options.

    Returns (tcp_info_dict, payload_bytes) or (None, None) on failure.
    """
    if len(data) < 20:
        return None, None

    src_port, dst_port = struct.unpack('!HH', data[0:4])
    seq = struct.unpack('!I', data[4:8])[0]
    ack_seq = struct.unpack('!I', data[8:12])[0]

    flags_field = struct.unpack('!H', data[12:14])[0]
    data_offset = (flags_field >> 12) & 0x0F
    data_offset_bytes = data_offset * 4

    if data_offset_bytes < 20 or len(data) < data_offset_bytes:
        return None, None

    # Decode TCP flags
    urg = bool(flags_field & 0x020)
    ack = bool(flags_field & 0x010)
    psh = bool(flags_field & 0x008)
    rst = bool(flags_field & 0x004)
    syn = bool(flags_field & 0x002)
    fin = bool(flags_field & 0x001)
    ece = bool(flags_field & 0x040)
    cwr = bool(flags_field & 0x080)

    window = struct.unpack('!H', data[14:16])[0]
    urg_ptr = struct.unpack('!H', data[18:20])[0]

    opt_bytes = data[20:data_offset_bytes]
    options = parse_tcp_options(opt_bytes)
    payload = data[data_offset_bytes:]

    tcp_info = {
        'src_port': src_port,
        'dst_port': dst_port,
        'seq': seq,
        'ack_seq': ack_seq,
        'data_offset': data_offset,
        'syn': syn,
        'ack': ack,
        'fin': fin,
        'rst': rst,
        'psh': psh,
        'urg': urg,
        'ece': ece,
        'cwr': cwr,
        'window': window,
        'urg_ptr': urg_ptr,
        'options': options,
        'has_payload': len(payload) > 0,
    }

    return tcp_info, payload


# ---------------------------------------------------------------------------
# Signature Extraction
# ---------------------------------------------------------------------------

def extract_signature(ip_info, tcp_info):
    """Extract a p0f-format signature string from parsed IP and TCP info.

    Format: ver:ittl:olen:mss:wsize,scale:olayout:quirks:pclass
    """
    ver = ip_info['version']
    ittl = guess_initial_ttl(ip_info['ttl'])
    olen = ip_info['ip_opt_len']

    # Extract specific option values
    mss = -1
    wscale = -1
    ts_val = None
    ts_ecr = None

    for opt_name, opt_data in tcp_info['options']:
        if opt_name == 'mss':
            mss = opt_data['value']
        elif opt_name == 'ws':
            wscale = opt_data['value']
        elif opt_name == 'ts':
            ts_val = opt_data['ts_val']
            ts_ecr = opt_data['ts_ecr']

    # --- Window size classification ---
    window = tcp_info['window']
    if mss > 0 and window > 0 and window % mss == 0:
        wsize_str = f"mss*{window // mss}"
    elif mss > 0 and (mss + 40) > 0 and window > 0 and window % (mss + 40) == 0:
        wsize_str = f"mtu*{window // (mss + 40)}"
    else:
        wsize_str = str(window)

    scale_str = str(wscale) if wscale >= 0 else "-1"

    # --- Options layout ---
    olayout_parts = []
    for opt_name, opt_data in tcp_info['options']:
        if opt_name == 'mss':
            olayout_parts.append('mss')
        elif opt_name == 'nop':
            olayout_parts.append('nop')
        elif opt_name == 'ws':
            olayout_parts.append('ws')
        elif opt_name == 'sok':
            olayout_parts.append('sok')
        elif opt_name == 'sack':
            olayout_parts.append('sack')
        elif opt_name == 'ts':
            olayout_parts.append('ts')
        elif opt_name == 'eol':
            olayout_parts.append(f"eol+{opt_data['pad']}")
        elif opt_name == '?':
            olayout_parts.append(f"?{opt_data['kind']}")
    olayout = ','.join(olayout_parts)

    # --- Quirks ---
    quirks = []

    # DF flag
    if ip_info['df']:
        quirks.append('df')
        if ip_info['identification'] != 0:
            quirks.append('id+')
    else:
        if ip_info['identification'] == 0:
            quirks.append('id-')

    # MBZ (must-be-zero) bit
    if ip_info['mbz']:
        quirks.append('0+')

    # ECN
    if ip_info['tos'] & 0x03:
        quirks.append('ecn')

    # Zero sequence number
    if tcp_info['seq'] == 0:
        quirks.append('seq-')

    # ACK anomalies
    if tcp_info['ack']:
        if tcp_info['ack_seq'] == 0:
            quirks.append('ack-')
    else:
        if tcp_info['ack_seq'] != 0:
            quirks.append('ack+')

    # URG anomalies
    if tcp_info['urg']:
        quirks.append('urgf')
    else:
        if tcp_info['urg_ptr'] != 0:
            quirks.append('uptr+')

    # PUSH flag in SYN
    if tcp_info['psh']:
        quirks.append('pushf')

    # Timestamp quirks
    if ts_val is not None:
        if ts_val == 0:
            quirks.append('ts1-')
        if ts_ecr is not None and ts_ecr != 0:
            quirks.append('ts2+')

    # Non-zero EOL padding
    for opt_name, opt_data in tcp_info['options']:
        if opt_name == 'eol' and opt_data.get('nz'):
            quirks.append('opt+')
            break

    # Excessive window scale
    if wscale > 14:
        quirks.append('exws')

    # Bad option lengths
    bad = False
    for opt_name, opt_data in tcp_info['options']:
        if opt_name == 'mss' and opt_data.get('len') != 4:
            bad = True
        elif opt_name == 'ws' and opt_data.get('len') != 3:
            bad = True
        elif opt_name == 'sok' and opt_data.get('len') != 2:
            bad = True
        elif opt_name == 'ts' and opt_data.get('len') != 10:
            bad = True
    if bad:
        quirks.append('bad')

    quirks_str = ','.join(quirks)

    # Payload class
    pclass = 1 if tcp_info['has_payload'] else 0

    # MSS field in signature
    mss_str = str(mss) if mss > 0 else '*'

    return f"{ver}:{ittl}:{olen}:{mss_str}:{wsize_str},{scale_str}:{olayout}:{quirks_str}:{pclass}"


# ---------------------------------------------------------------------------
# Signature Database
# ---------------------------------------------------------------------------

def parse_sig_database(filename):
    """Parse a p0f-format signature database file.

    Returns a list of dicts with 'label' and 'sig' keys.
    """
    entries = []
    current_label = None

    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(';') or line.startswith('['):
                continue

            if line.startswith('label'):
                _, _, value = line.partition('=')
                current_label = value.strip()
            elif line.startswith('sig'):
                _, _, value = line.partition('=')
                sig = value.strip()
                if current_label is not None:
                    entries.append({'label': current_label, 'sig': sig})

    return entries


def match_signature(extracted_sig, db_entries):
    """Match an extracted signature against database entries.

    Database entries may use '*' as wildcard for ver, mss, and pclass fields.
    All other fields must match exactly (string comparison).

    Returns (os_class, os_name) or (None, None) if no match.
    """
    parts = extracted_sig.split(':')
    if len(parts) != 8:
        return None, None

    ext_ver, ext_ittl, ext_olen, ext_mss = parts[0], parts[1], parts[2], parts[3]
    ext_wsize_scale = parts[4]
    ext_olayout = parts[5]
    ext_quirks = parts[6]
    ext_pclass = parts[7]

    for entry in db_entries:
        db_parts = entry['sig'].split(':')
        if len(db_parts) != 8:
            continue

        db_ver, db_ittl, db_olen, db_mss = db_parts[0], db_parts[1], db_parts[2], db_parts[3]
        db_wsize_scale = db_parts[4]
        db_olayout = db_parts[5]
        db_quirks = db_parts[6]
        db_pclass = db_parts[7]

        # Match each field (wildcards allowed in ver, mss, pclass)
        if db_ver != '*' and db_ver != ext_ver:
            continue
        if db_ittl != ext_ittl:
            continue
        if db_olen != ext_olen:
            continue
        if db_mss != '*' and db_mss != ext_mss:
            continue
        if db_wsize_scale != ext_wsize_scale:
            continue
        if db_olayout != ext_olayout:
            continue
        if db_quirks != ext_quirks:
            continue
        if db_pclass != '*' and db_pclass != ext_pclass:
            continue

        # Match found — parse the label
        label = entry['label']
        label_parts = label.split(':')
        if len(label_parts) >= 3:
            os_class = label_parts[1]
            os_name = ':'.join(label_parts[2:])
        elif len(label_parts) == 2:
            os_class = label_parts[1]
            os_name = ''
        else:
            os_class = label
            os_name = ''

        return os_class, os_name

    return None, None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    pcap_file = '/app/captures/syn_packets.pcap'
    db_file = '/app/signatures/tcp_syn.fp'
    output_file = '/app/results.json'

    if not os.path.exists(pcap_file):
        print(f"Error: PCAP file not found: {pcap_file}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(db_file):
        print(f"Error: Database file not found: {db_file}", file=sys.stderr)
        sys.exit(1)

    packets = parse_pcap(pcap_file)
    db_entries = parse_sig_database(db_file)

    results = []

    for idx, raw_pkt in enumerate(packets):
        # Parse Ethernet
        ip_data, ethertype = parse_ethernet(raw_pkt)
        if ethertype != 0x0800 or ip_data is None:
            continue

        # Parse IPv4
        ip_info, tcp_data = parse_ipv4(ip_data)
        if ip_info is None or ip_info['protocol'] != 6:
            continue

        # Parse TCP
        tcp_info, _payload = parse_tcp(tcp_data)
        if tcp_info is None:
            continue

        # Filter: SYN only (SYN set, ACK not set)
        if not tcp_info['syn'] or tcp_info['ack']:
            continue

        # Extract p0f signature
        sig = extract_signature(ip_info, tcp_info)

        # Match against database
        os_class, os_name = match_signature(sig, db_entries)

        results.append({
            'packet_index': idx,
            'src_ip': ip_info['src_ip'],
            'dst_ip': ip_info['dst_ip'],
            'src_port': tcp_info['src_port'],
            'dst_port': tcp_info['dst_port'],
            'signature': sig,
            'os_class': os_class if os_class else 'unknown',
            'os_name': os_name if os_name else 'unknown',
        })

    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Processed {len(packets)} PCAP packets, "
          f"extracted {len(results)} SYN signatures, "
          f"wrote {output_file}")


if __name__ == '__main__':
    main()
