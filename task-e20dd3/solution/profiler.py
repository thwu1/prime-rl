#!/usr/bin/env python3
"""
TCP Host Profiler — Network forensics pipeline.

Uses tshark for packet filtering and metadata extraction, combined with
raw pcap binary analysis for TCP option parsing. Performs OS fingerprinting
via p0f-compatible signatures, TCP timestamp clock analysis, hop distance
estimation, and NAT gateway detection.

"""
import subprocess
import json
import sys
import struct
from collections import defaultdict

COMMON_TTLS = [32, 64, 128, 255]


def guess_initial_ttl(observed):
    for t in COMMON_TTLS:
        if observed <= t:
            return t
    return 255


# -----------------------------------------------------------------------
# Raw pcap reading (for TCP option bytes and IP header fields)
# -----------------------------------------------------------------------

def read_pcap_packets(path):
    """Read pcap file, return dict mapping 1-based frame number to raw bytes."""
    packets = {}
    with open(path, 'rb') as f:
        ghdr = f.read(24)
        if len(ghdr) < 24:
            return packets
        magic = struct.unpack('<I', ghdr[:4])[0]
        if magic == 0xa1b2c3d4:
            endian = '<'
        elif magic == 0xd4c3b2a1:
            endian = '>'
        else:
            return packets

        frame = 1
        while True:
            phdr = f.read(16)
            if len(phdr) < 16:
                break
            _, _, incl_len, _ = struct.unpack(endian + 'IIII', phdr)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break
            packets[frame] = data
            frame += 1
    return packets


def extract_tcp_opts_raw(pkt_bytes, ip_hdr_len, tcp_hdr_len):
    """Extract raw TCP option bytes from an Ethernet frame."""
    start = 14 + ip_hdr_len + 20  # eth(14) + ip_hdr + tcp base(20)
    end = 14 + ip_hdr_len + tcp_hdr_len
    if end > len(pkt_bytes):
        return b''
    return pkt_bytes[start:end]


def extract_ip_fields_raw(pkt_bytes):
    """Extract IP-level fields directly from raw Ethernet frame bytes.

    This bypasses tshark's boolean field formatting which varies between
    versions (outputs '1', 'True', 'Set', etc.), ensuring reliable
    detection of DF flag, IP ID, ECN, and reserved bit.
    """
    if len(pkt_bytes) < 34:  # 14 eth + 20 min IP header
        return None
    ip_start = 14  # After Ethernet header

    tos = pkt_bytes[ip_start + 1]
    ecn = tos & 0x03

    ip_id = struct.unpack('!H', pkt_bytes[ip_start + 4:ip_start + 6])[0]

    flags_frag = struct.unpack('!H', pkt_bytes[ip_start + 6:ip_start + 8])[0]
    df = bool(flags_frag & 0x4000)
    mbz = bool(flags_frag & 0x8000)

    return {'df': df, 'ip_id': ip_id, 'ecn': ecn, 'mbz': mbz}


# -----------------------------------------------------------------------
# TCP option parsing
# -----------------------------------------------------------------------

def parse_tcp_options(data, total_opts_len=None):
    """Parse raw TCP option bytes into structured list."""
    options = []
    i = 0
    eff_total = total_opts_len if total_opts_len is not None else len(data)

    while i < len(data):
        kind = data[i]
        if kind == 0:  # EOL
            pad = eff_total - i - 1
            options.append(('eol', pad))
            break
        elif kind == 1:  # NOP
            options.append(('nop', None))
            i += 1
        elif kind == 2:  # MSS
            if i + 4 > len(data):
                break
            val = struct.unpack('!H', data[i + 2:i + 4])[0]
            options.append(('mss', val))
            i += data[i + 1]
        elif kind == 3:  # Window Scale
            if i + 3 > len(data):
                break
            options.append(('ws', data[i + 2]))
            i += data[i + 1]
        elif kind == 4:  # SACK Permitted
            if i + 2 > len(data):
                break
            options.append(('sok', None))
            i += data[i + 1]
        elif kind == 5:  # SACK
            if i + 2 > len(data):
                break
            options.append(('sack', None))
            i += data[i + 1]
        elif kind == 8:  # Timestamps
            if i + 10 > len(data):
                break
            ts1 = struct.unpack('!I', data[i + 2:i + 6])[0]
            ts2 = struct.unpack('!I', data[i + 6:i + 10])[0]
            options.append(('ts', (ts1, ts2)))
            i += data[i + 1]
        else:  # Unknown
            if i + 2 > len(data):
                break
            opt_len = data[i + 1]
            if opt_len < 2:
                break
            options.append((f'?{kind}', None))
            i += opt_len

    return options


# -----------------------------------------------------------------------
# Signature generation
# -----------------------------------------------------------------------

def build_signature(ttl, ip_opts_len, window, tcp_options,
                    df, ip_id, ecn, mbz, seq, ack_seq, ack_flag,
                    urg_ptr, urg_flag, psh_flag, has_payload):
    """Build a p0f-compatible signature string."""
    ittl = guess_initial_ttl(ttl)

    mss = ws = None
    for opt in tcp_options:
        if opt[0] == 'mss':
            mss = opt[1]
        elif opt[0] == 'ws':
            ws = opt[1]

    mss_s = str(mss) if mss is not None else '*'

    # Window size interpretation
    w = str(window)
    if mss and mss > 0:
        if window % mss == 0:
            w = f"mss*{window // mss}"
        elif window % (mss + 40) == 0:
            w = f"mtu*{window // (mss + 40)}"
    sc = str(ws) if ws is not None else '*'

    # Option layout
    layout = []
    for opt in tcp_options:
        n = opt[0]
        if n == 'eol':
            layout.append(f"eol+{opt[1]}")
        elif n in ('nop', 'mss', 'ws', 'sok', 'sack', 'ts'):
            layout.append(n)
        elif n.startswith('?'):
            layout.append(n)
    ol = ','.join(layout)

    # Quirks in canonical order
    q = []
    if df:
        q.append('df')
    if df and ip_id != 0:
        q.append('id+')
    if not df and ip_id == 0:
        q.append('id-')
    if ecn:
        q.append('ecn')
    if mbz:
        q.append('0+')
    if seq == 0:
        q.append('seq-')
    if not ack_flag and ack_seq != 0:
        q.append('ack+')
    if ack_flag and ack_seq == 0:
        q.append('ack-')
    if not urg_flag and urg_ptr != 0:
        q.append('uptr+')
    if urg_flag:
        q.append('urgf+')
    if psh_flag:
        q.append('pushf+')
    for opt in tcp_options:
        if opt[0] == 'ts':
            if opt[1][0] == 0:
                q.append('ts1-')
            if opt[1][1] != 0:
                q.append('ts2+')
            break
    if ws is not None and ws > 14:
        q.append('exws')

    pclass = '+' if has_payload else '0'
    return f"4:{ittl}:{ip_opts_len}:{mss_s}:{w},{sc}:{ol}:{','.join(q)}:{pclass}"


# -----------------------------------------------------------------------
# Fingerprint database
# -----------------------------------------------------------------------

def load_db(path):
    """Parse p0f fingerprint database."""
    entries = []
    section = label = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(';'):
                continue
            if line.startswith('[') and line.endswith(']'):
                section = line[1:-1]
                continue
            if line.startswith('label'):
                _, _, v = line.partition('=')
                label = v.strip()
            elif line.startswith('sig'):
                _, _, v = line.partition('=')
                entries.append({
                    'section': section,
                    'label': label,
                    'sig': v.strip(),
                })
    return entries


def match_sig(observed, db):
    """Match observed signature against database. Returns first match or None."""
    o = observed.split(':')
    if len(o) != 8:
        return None
    ow = o[4].split(',', 1) if ',' in o[4] else [o[4], '*']
    oq = set(o[6].split(',')) if o[6] else set()

    for e in db:
        if e.get('section') != 'tcp:request':
            continue
        d = e['sig'].split(':')
        if len(d) != 8:
            continue
        dw = d[4].split(',', 1) if ',' in d[4] else [d[4], '*']
        dq = set(d[6].split(',')) if d[6] else set()

        ok = True
        for i in (0, 1, 2, 3):
            if d[i] != '*' and d[i] != o[i]:
                ok = False
                break
        if not ok:
            continue
        if dw[0] != '*' and dw[0] != ow[0]:
            continue
        if dw[1] != '*' and dw[1] != ow[1]:
            continue
        if d[5] != o[5]:
            continue
        if dq != oq:
            continue
        if d[7] != '*' and d[7] != o[7]:
            continue
        return e
    return None


# -----------------------------------------------------------------------
# tshark extraction
# -----------------------------------------------------------------------

TSHARK_FIELDS = [
    'frame.number',             # 0
    'frame.time_epoch',         # 1
    'ip.src', 'ip.dst',        # 2, 3
    'tcp.srcport', 'tcp.dstport',  # 4, 5
    'ip.ttl',                   # 6
    'ip.hdr_len',              # 7
    'tcp.window_size_value',   # 8
    'tcp.seq', 'tcp.ack',     # 9, 10
    'tcp.urgent_pointer',      # 11
    'tcp.flags',               # 12
    'tcp.hdr_len',             # 13
    'tcp.len',                 # 14
]


def run_tshark(pcap_path):
    """Run tshark to extract SYN-only IPv4 packet metadata."""
    cmd = [
        'tshark', '-r', pcap_path, '-n',
        '-Y', 'tcp.flags.syn==1 && tcp.flags.ack==0 && ip',
        '-T', 'fields', '-E', 'separator=\t',
        '-o', 'tcp.relative_sequence_numbers:FALSE',
    ]
    for f in TSHARK_FIELDS:
        cmd.extend(['-e', f])

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"tshark error (exit {r.returncode}): {r.stderr}")

    rows = []
    for line in r.stdout.strip().split('\n'):
        if not line.strip():
            continue
        p = line.split('\t')
        while len(p) < len(TSHARK_FIELDS):
            p.append('')
        rows.append(p)
    return rows


def parse_tshark_row(row):
    """Parse a single tshark -T fields row into a dict of typed values."""
    frame_num = int(row[0])
    pcap_time = float(row[1]) if row[1] else 0.0
    src_ip = row[2]
    dst_ip = row[3]
    src_port = int(row[4]) if row[4] else 0
    dst_port = int(row[5]) if row[5] else 0
    ttl = int(row[6]) if row[6] else 64

    ip_hdr_len = int(row[7]) if row[7] else 20
    ip_opts_len = ip_hdr_len - 20
    window = int(row[8]) if row[8] else 0

    seq = int(row[9]) if row[9] else 0
    ack_seq = int(row[10]) if row[10] else 0
    urg_ptr = int(row[11]) if row[11] else 0

    fl = row[12]
    if fl.startswith('0x'):
        flags = int(fl, 16)
    else:
        flags = int(fl) if fl else 0
    ack_f = bool(flags & 0x10)
    psh_f = bool(flags & 0x08)
    urg_f = bool(flags & 0x20)

    tcp_hdr_len = int(row[13]) if row[13] else 20
    tcp_payload_len = int(row[14]) if row[14] else 0

    return {
        'frame_num': frame_num,
        'pcap_time': pcap_time,
        'src_ip': src_ip,
        'dst_ip': dst_ip,
        'src_port': src_port,
        'dst_port': dst_port,
        'ttl': ttl,
        'ip_hdr_len': ip_hdr_len,
        'ip_opts_len': ip_opts_len,
        'window': window,
        'seq': seq,
        'ack_seq': ack_seq,
        'urg_ptr': urg_ptr,
        'ack_flag': ack_f,
        'psh_flag': psh_f,
        'urg_flag': urg_f,
        'tcp_hdr_len': tcp_hdr_len,
        'has_payload': tcp_payload_len > 0,
    }


# -----------------------------------------------------------------------
# Clock analysis
# -----------------------------------------------------------------------

def estimate_clock(ts_pairs):
    """Linear regression on (pcap_time, tsval) pairs.

    Returns (frequency_hz, uptime_seconds) or (None, None).
    """
    if len(ts_pairs) < 2:
        return None, None

    n = len(ts_pairs)
    xs, ys = zip(*ts_pairs)
    mx = sum(xs) / n
    my = sum(ys) / n

    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)

    if den == 0:
        return None, None

    freq = round(num / den)
    if freq <= 0:
        return None, None

    uptime = int(ys[0] / freq)
    return freq, uptime


# -----------------------------------------------------------------------
# Main pipeline
# -----------------------------------------------------------------------

def analyze(pcap_path, db_path, output_path):
    db = load_db(db_path)
    tshark_rows = run_tshark(pcap_path)
    raw_pkts = read_pcap_packets(pcap_path)

    hosts = defaultdict(lambda: {
        'syns': [],
        'sigs': [],
        'ts_pairs': [],
    })

    for row in tshark_rows:
        p = parse_tshark_row(row)

        # Get raw packet bytes from pcap
        pkt_bytes = raw_pkts.get(p['frame_num'], b'')

        # Extract IP-level fields (DF, IP ID, ECN, MBZ) directly from
        # raw bytes instead of tshark output, because tshark's boolean
        # field format varies between versions ('1', 'True', 'Set', etc.)
        ip_raw = extract_ip_fields_raw(pkt_bytes)
        if ip_raw:
            df = ip_raw['df']
            ip_id = ip_raw['ip_id']
            ecn = ip_raw['ecn']
            mbz = ip_raw['mbz']
        else:
            df = False
            ip_id = 0
            ecn = 0
            mbz = False

        # Extract TCP options from raw bytes
        opts_raw = extract_tcp_opts_raw(pkt_bytes, p['ip_hdr_len'], p['tcp_hdr_len'])
        tcp_opts = parse_tcp_options(opts_raw, p['tcp_hdr_len'] - 20)

        sig = build_signature(
            p['ttl'], p['ip_opts_len'], p['window'], tcp_opts,
            df, ip_id, ecn, mbz,
            p['seq'], p['ack_seq'], p['ack_flag'],
            p['urg_ptr'], p['urg_flag'], p['psh_flag'],
            p['has_payload'],
        )

        ts_val = None
        for opt in tcp_opts:
            if opt[0] == 'ts':
                ts_val = opt[1][0]
                break

        h = hosts[p['src_ip']]
        h['syns'].append({'ttl': p['ttl']})
        h['sigs'].append(sig)
        if ts_val is not None:
            h['ts_pairs'].append((p['pcap_time'], ts_val))

    # Build per-host report
    report = []
    for ip in sorted(hosts):
        h = hosts[ip]
        distinct = list(dict.fromkeys(h['sigs']))

        counts = defaultdict(int)
        for s in h['sigs']:
            counts[s] += 1
        primary = max(counts, key=counts.get)

        m = match_sig(primary, db)
        os_label = m['label'] if m else 'unknown'

        ttl = h['syns'][0]['ttl']
        dist = guess_initial_ttl(ttl) - ttl

        nat = len(distinct) > 1

        if nat:
            freq, uptime = None, None
        else:
            freq, uptime = estimate_clock(h['ts_pairs'])

        entry = {
            'ip': ip,
            'os': os_label,
            'signature': primary,
            'distance': dist,
            'uptime_seconds': uptime,
            'timestamp_frequency_hz': freq,
            'nat_detected': nat,
            'syn_count': len(h['syns']),
        }
        if nat:
            entry['signatures'] = sorted(distinct)

        report.append(entry)

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <pcap> <fingerprints.db> <output.json>",
              file=sys.stderr)
        sys.exit(1)
    analyze(sys.argv[1], sys.argv[2], sys.argv[3])
