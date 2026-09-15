#!/usr/bin/env python3
"""ANSI/NIST-ITL Biometric Transaction Forensic Toolkit.

Supports validation, reconstruction, hex analysis, and integrity verification
of ANSI/NIST-ITL 1-2011 traditional encoding biometric transaction files.
"""

import json
import os
import re
import struct
import subprocess
import sys

# Separator bytes
US = b'\x1f'
RS = b'\x1e'
GS = b'\x1d'
FS = b'\x1c'

# Repair defaults for missing mandatory Type-1 fields
REPAIR_DEFAULTS = {
    4: b'UNK',
    5: b'19700101',
    7: b'UNKNOWN',
    8: b'UNKNOWN',
    9: b'REPAIR000',
    11: b'19.69',
    12: b'19.69',
}


# ============================================================
# Parsing
# ============================================================

def parse_cnt(cnt_bytes):
    """Parse CNT field value into list of (idc, record_type) tuples."""
    subfields = cnt_bytes.split(RS)
    entries = []
    for i, sf in enumerate(subfields):
        if i == 0:
            continue  # skip Type-1 self-reference
        items = sf.split(US)
        if len(items) >= 2:
            try:
                entries.append((int(items[0]), int(items[1])))
            except ValueError:
                pass
    return entries


def get_cnt_total(cnt_bytes):
    """Get declared total record count from first CNT subfield."""
    subfields = cnt_bytes.split(RS)
    if subfields:
        items = subfields[0].split(US)
        if len(items) >= 2:
            try:
                return int(items[1])
            except ValueError:
                pass
    return 0


def parse_tagged_record(data, rtype):
    """Parse a tagged-field record.

    Returns (fields_dict, actual_byte_count).
    fields_dict maps field_number (int) -> value (bytes).
    """
    fs_pos = data.find(FS)
    if fs_pos == -1:
        fs_pos = len(data) - 1
    record_bytes = data[:fs_pos + 1]
    actual_len = len(record_bytes)

    inner = record_bytes[:-1]  # strip FS
    field_parts = inner.split(GS)

    fields = {}
    for part in field_parts:
        colon = part.find(b':')
        if colon == -1:
            continue
        tag = part[:colon].decode('ascii', errors='replace')
        value = part[colon + 1:]
        segs = tag.split('.')
        if len(segs) == 2:
            try:
                fnum = int(segs[1])
                fields[fnum] = value
            except ValueError:
                pass

    return fields, actual_len


def parse_binary_record(data):
    """Parse a Type-4 binary-header record.

    Returns (header_dict, actual_byte_count).
    """
    if len(data) < 4:
        return {}, len(data)

    declared_len = struct.unpack('>I', data[:4])[0]
    actual_len = min(declared_len, len(data))
    rec = data[:actual_len]

    header = {'declared_len': declared_len}
    if len(rec) >= 8:
        header['idc'] = struct.unpack('>I', rec[4:8])[0]
    if len(rec) >= 9:
        header['imp'] = rec[8]
    if len(rec) >= 15:
        header['fgp'] = list(rec[9:15])
    if len(rec) >= 16:
        header['isr'] = rec[15]
    if len(rec) >= 18:
        header['hll'] = struct.unpack('>H', rec[16:18])[0]
    if len(rec) >= 20:
        header['vll'] = struct.unpack('>H', rec[18:20])[0]
    if len(rec) >= 21:
        header['gca'] = rec[20]
    header['image_data'] = rec[21:] if len(rec) > 21 else b''

    return header, actual_len


def parse_transaction(filepath):
    """Parse a transaction file into a list of record dicts."""
    with open(filepath, 'rb') as f:
        data = f.read()

    records = []
    pos = 0

    if not data:
        return records

    # Type-1 is always first, always tagged
    t1_fields, t1_len = parse_tagged_record(data[pos:], 1)
    records.append({
        'type': 1,
        'encoding': 'tagged',
        'fields': t1_fields,
        'raw': data[pos:pos + t1_len],
        'offset': pos,
    })
    pos += t1_len

    # CNT determines subsequent record types
    cnt_entries = parse_cnt(t1_fields.get(3, b''))

    for idc, rtype in cnt_entries:
        if pos >= len(data):
            break

        if 3 <= rtype <= 6:
            header, rec_len = parse_binary_record(data[pos:])
            records.append({
                'type': rtype,
                'encoding': 'binary',
                'header': header,
                'raw': data[pos:pos + rec_len],
                'offset': pos,
                'expected_idc': idc,
            })
        else:
            fields, rec_len = parse_tagged_record(data[pos:], rtype)
            records.append({
                'type': rtype,
                'encoding': 'tagged',
                'fields': fields,
                'raw': data[pos:pos + rec_len],
                'offset': pos,
                'expected_idc': idc,
            })
        pos += rec_len

    return records


# ============================================================
# Validation
# ============================================================

def _val_str(b):
    """Decode bytes to ASCII string for validation checks."""
    if isinstance(b, bytes):
        return b.decode('ascii', errors='replace')
    return str(b)


def analyze_file(filepath):
    """Validate a transaction file.

    Returns sorted, deduplicated list of violation code strings.
    """
    violations = set()
    records = parse_transaction(filepath)
    if not records:
        return []

    t1 = records[0]
    t1f = t1['fields']

    # --- Type-1 checks ---

    # LEN
    if 1 in t1f:
        try:
            if int(_val_str(t1f[1])) != len(t1['raw']):
                violations.add('T1_LEN_MISMATCH')
        except ValueError:
            violations.add('T1_LEN_MISMATCH')

    # VER
    if 2 in t1f:
        v = _val_str(t1f[2])
        if len(v) != 4 or not v.isdigit():
            violations.add('T1_VER_FORMAT')

    # CNT
    cnt_entries = []
    if 3 in t1f:
        cnt_entries = parse_cnt(t1f[3])
        declared = get_cnt_total(t1f[3])
        if declared != len(records):
            violations.add('T1_CNT_COUNT')
        for idc, rt in cnt_entries:
            if not any(r['type'] == rt and r.get('expected_idc') == idc
                       for r in records[1:]):
                violations.add('T1_CNT_MISSING_REF')

    # Mandatory fields (non-empty)
    for fnum, vcode in [(4, 'T1_MISSING_TOT'), (7, 'T1_MISSING_DAI'),
                        (8, 'T1_MISSING_ORI'), (9, 'T1_MISSING_TCN')]:
        if fnum not in t1f or t1f[fnum] == b'':
            violations.add(vcode)

    # DAT
    if 5 not in t1f:
        violations.add('T1_MISSING_DAT')
    else:
        d = _val_str(t1f[5])
        if len(d) != 8 or not d.isdigit():
            violations.add('T1_DAT_FORMAT')
        else:
            m, dy = int(d[4:6]), int(d[6:8])
            if m < 1 or m > 12 or dy < 1 or dy > 31:
                violations.add('T1_DAT_FORMAT')

    # PRY
    if 6 in t1f:
        p = _val_str(t1f[6])
        if len(p) != 1 or not p.isdigit() or not (1 <= int(p) <= 9):
            violations.add('T1_PRY_RANGE')

    # NSR
    if 11 not in t1f:
        violations.add('T1_MISSING_NSR')
    else:
        if not re.match(r'^\d{2}\.\d{2}$', _val_str(t1f[11])):
            violations.add('T1_NSR_FORMAT')

    # NTR
    if 12 not in t1f:
        violations.add('T1_MISSING_NTR')
    else:
        if not re.match(r'^\d{2}\.\d{2}$', _val_str(t1f[12])):
            violations.add('T1_NTR_FORMAT')

    # --- Subsequent records ---
    for rec in records[1:]:
        if rec['encoding'] == 'tagged':
            rt = rec['type']
            rf = rec['fields']
            # LEN
            if 1 in rf:
                try:
                    if int(_val_str(rf[1])) != len(rec['raw']):
                        violations.add(f'T{rt}_LEN_MISMATCH')
                except ValueError:
                    violations.add(f'T{rt}_LEN_MISMATCH')
            # IDC (Type-2)
            if rt == 2 and 2 in rf:
                eidc = rec.get('expected_idc')
                if eidc is not None:
                    try:
                        if int(_val_str(rf[2])) != eidc:
                            violations.add('T2_IDC_MISMATCH')
                    except ValueError:
                        violations.add('T2_IDC_MISMATCH')

        elif rec['encoding'] == 'binary' and rec['type'] == 4:
            h = rec['header']
            if h.get('declared_len') != len(rec['raw']):
                violations.add('T4_LEN_MISMATCH')
            eidc = rec.get('expected_idc')
            if eidc is not None and h.get('idc') != eidc:
                violations.add('T4_IDC_MISMATCH')
            if h.get('imp', 0) > 15:
                violations.add('T4_IMP_RANGE')
            for fb in h.get('fgp', []):
                if fb > 10 and fb != 0xFF:
                    violations.add('T4_FGP_RANGE')
                    break
            if h.get('isr', 0) not in (0, 1):
                violations.add('T4_ISR_VALUE')
            if h.get('hll', 0) == 0:
                violations.add('T4_HLL_ZERO')
            if h.get('vll', 0) == 0:
                violations.add('T4_VLL_ZERO')
            if h.get('gca', 0) not in (0, 1):
                violations.add('T4_GCA_VALUE')
            if len(rec['raw']) <= 21:
                violations.add('T4_NO_IMAGE_DATA')
            # Cross-record: resolution
            isr = h.get('isr', 0)
            if isr == 1 and 11 in t1f:
                nsr_s = _val_str(t1f[11])
                if re.match(r'^\d{2}\.\d{2}$', nsr_s):
                    if float(nsr_s) < 19.69:
                        violations.add('T4_RESOLUTION_LOW')

    return sorted(violations)


# ============================================================
# Reconstruction
# ============================================================

def _solve_tagged_len(rtype, fields):
    """Build a tagged record with correct self-referential LEN.

    fields: dict mapping field_number -> bytes value (field 1 excluded).
    Returns complete record bytes.
    """
    parts = []
    for fnum in sorted(fields.keys()):
        if fnum == 1:
            continue
        tag = f"{rtype}.{fnum:03d}:".encode('ascii')
        val = fields[fnum]
        if isinstance(val, str):
            val = val.encode('ascii')
        parts.append(tag + val)

    len_tag = f"{rtype}.001:".encode('ascii')
    suffix = (GS + GS.join(parts) + FS) if parts else FS

    base = len(len_tag) + len(suffix)
    for trial in range(base + 1, base + 20):
        if len(len_tag) + len(str(trial).encode('ascii')) + len(suffix) == trial:
            return len_tag + str(trial).encode('ascii') + suffix

    raise ValueError(f"Cannot solve self-referential LEN for type {rtype}")


def _build_binary_from_header(header):
    """Build a Type-4 binary record from header dict."""
    body = struct.pack('>I', header.get('idc', 0))
    body += struct.pack('B', header.get('imp', 0))
    for fb in header.get('fgp', [0xFF] * 6):
        body += struct.pack('B', fb)
    body += struct.pack('B', header.get('isr', 0))
    body += struct.pack('>H', header.get('hll', 1))
    body += struct.pack('>H', header.get('vll', 1))
    body += struct.pack('B', header.get('gca', 0))
    body += header.get('image_data', b'\x00')
    total = 4 + len(body)
    return struct.pack('>I', total) + body


def reconstruct_file(filepath, outpath):
    """Repair all violations and write a valid transaction to outpath."""
    records = parse_transaction(filepath)
    if not records:
        with open(filepath, 'rb') as f:
            data = f.read()
        with open(outpath, 'wb') as f:
            f.write(data)
        return

    # --- Mutable copies ---
    t1_fields = {k: bytes(v) for k, v in records[0]['fields'].items() if k != 1}

    rec_data = []  # [(encoding, rtype, fields_or_header, expected_idc)]
    for rec in records[1:]:
        if rec['encoding'] == 'tagged':
            flds = {k: bytes(v) for k, v in rec['fields'].items() if k != 1}
            rec_data.append(('tagged', rec['type'], flds, rec.get('expected_idc')))
        else:
            h = dict(rec['header'])
            if 'fgp' in h:
                h['fgp'] = list(h['fgp'])
            if 'image_data' in h:
                h['image_data'] = bytes(h['image_data'])
            rec_data.append(('binary', rec['type'], h, rec.get('expected_idc')))

    # --- PHASE 1: Field-level repairs ---

    # Type-1 VER
    if 2 in t1_fields:
        v = _val_str(t1_fields[2])
        if len(v) != 4 or not v.isdigit():
            t1_fields[2] = b'0300'

    # Type-1 DAT
    if 5 not in t1_fields or t1_fields[5] == b'':
        t1_fields[5] = b'19700101'
    else:
        d = _val_str(t1_fields[5])
        ok = (len(d) == 8 and d.isdigit() and
              1 <= int(d[4:6]) <= 12 and 1 <= int(d[6:8]) <= 31)
        if not ok:
            t1_fields[5] = b'19700101'

    # Type-1 PRY
    if 6 in t1_fields:
        p = _val_str(t1_fields[6])
        if len(p) != 1 or not p.isdigit() or not (1 <= int(p) <= 9):
            del t1_fields[6]

    # Type-1 missing mandatory
    for fnum, default in REPAIR_DEFAULTS.items():
        if fnum not in t1_fields or t1_fields[fnum] == b'':
            t1_fields[fnum] = default

    # Type-1 NSR/NTR format
    if 11 in t1_fields and not re.match(r'^\d{2}\.\d{2}$', _val_str(t1_fields[11])):
        t1_fields[11] = b'19.69'
    if 12 in t1_fields and not re.match(r'^\d{2}\.\d{2}$', _val_str(t1_fields[12])):
        t1_fields[12] = b'19.69'

    # Non-Type-1 repairs
    for enc, rtype, data, eidc in rec_data:
        if enc == 'tagged' and rtype == 2:
            if 2 in data and eidc is not None:
                try:
                    if int(_val_str(data[2])) != eidc:
                        data[2] = str(eidc).encode('ascii')
                except ValueError:
                    data[2] = str(eidc).encode('ascii')
        elif enc == 'binary' and rtype == 4:
            h = data
            if h.get('imp', 0) > 15:
                h['imp'] = 0
            if 'fgp' in h:
                for j in range(len(h['fgp'])):
                    if h['fgp'][j] > 10 and h['fgp'][j] != 0xFF:
                        h['fgp'][j] = 0xFF
            if h.get('isr', 0) not in (0, 1):
                h['isr'] = 0
            if h.get('hll', 0) == 0:
                h['hll'] = 1
            if h.get('vll', 0) == 0:
                h['vll'] = 1
            if h.get('gca', 0) not in (0, 1):
                h['gca'] = 0
            if not h.get('image_data'):
                h['image_data'] = b'\x00'
            if eidc is not None and h.get('idc') != eidc:
                h['idc'] = eidc

    # --- PHASE 2: Cross-record repairs ---
    for enc, rtype, data, eidc in rec_data:
        if enc == 'binary' and rtype == 4:
            if data.get('isr') == 1 and 11 in t1_fields:
                nsr_s = _val_str(t1_fields[11])
                if re.match(r'^\d{2}\.\d{2}$', nsr_s) and float(nsr_s) < 19.69:
                    t1_fields[11] = b'19.69'

    # --- PHASE 3: Structural repairs (CNT) ---
    actual_entries = []
    for enc, rtype, data, eidc in rec_data:
        actual_entries.append((eidc if eidc is not None else 0, rtype))

    total = 1 + len(actual_entries)
    cnt_parts = [b'1' + US + str(total).encode('ascii')]
    for idc, rt in actual_entries:
        cnt_parts.append(str(idc).encode('ascii') + US + str(rt).encode('ascii'))
    t1_fields[3] = RS.join(cnt_parts)

    # --- PHASE 4: Length recomputation & assembly ---
    output = _solve_tagged_len(1, t1_fields)
    for enc, rtype, data, eidc in rec_data:
        if enc == 'tagged':
            output += _solve_tagged_len(rtype, data)
        else:
            output += _build_binary_from_header(data)

    with open(outpath, 'wb') as f:
        f.write(output)


# ============================================================
# Hex Analysis
# ============================================================

def hexdump_file(filepath):
    """Produce annotated xxd hex dump with record boundary markers."""
    records = parse_transaction(filepath)
    result = subprocess.run(['xxd', filepath], capture_output=True, text=True)
    xxd_lines = result.stdout.rstrip('\n').split('\n')

    offsets = {rec['offset']: rec['type'] for rec in records}
    done = set()
    out = []

    for line in xxd_lines:
        if not line.strip():
            continue
        colon = line.find(':')
        if colon > 0:
            try:
                lo = int(line[:colon].strip(), 16)
                for off in sorted(offsets):
                    if off not in done and lo <= off < lo + 16:
                        out.append(
                            f"# --- Record Type {offsets[off]} "
                            f"at offset {off:08x} ({off} bytes) ---"
                        )
                        done.add(off)
            except ValueError:
                pass
        out.append(line)

    return '\n'.join(out) + '\n'


# ============================================================
# Integrity Verification
# ============================================================

def compute_checksums(recon_dir, outpath):
    """Compute SHA-256 hashes of reconstructed files using sha256sum."""
    files = sorted(f for f in os.listdir(recon_dir) if f.endswith('.an2k'))
    lines = []
    for f in files:
        path = os.path.join(recon_dir, f)
        r = subprocess.run(['sha256sum', path], capture_output=True, text=True)
        h = r.stdout.split()[0]
        lines.append(f"{h}  {f}")
    with open(outpath, 'w') as fp:
        fp.write('\n'.join(lines) + '\n')


def compute_hmac(recon_dir, key_path, outpath):
    """Compute HMAC-SHA256 of reconstructed files using openssl dgst."""
    with open(key_path) as f:
        key = f.read().strip()

    files = sorted(f for f in os.listdir(recon_dir) if f.endswith('.an2k'))
    lines = []
    for fname in files:
        path = os.path.join(recon_dir, fname)
        r = subprocess.run(
            ['openssl', 'dgst', '-sha256', '-hmac', key, path],
            capture_output=True, text=True
        )
        m = re.search(r'=\s*([0-9a-f]+)', r.stdout)
        if m:
            lines.append(f"{m.group(1)}  {fname}")
    with open(outpath, 'w') as fp:
        fp.write('\n'.join(lines) + '\n')


# ============================================================
# Main
# ============================================================

def main():
    corpus = '/app/corpus'
    recon = '/app/reconstructed'
    hexdir = '/app/hexanalysis'

    os.makedirs(recon, exist_ok=True)
    os.makedirs(hexdir, exist_ok=True)

    files = sorted(f for f in os.listdir(corpus) if f.endswith('.an2k'))

    # Validation
    report = {}
    for f in files:
        report[f] = analyze_file(os.path.join(corpus, f))
    with open('/app/report.json', 'w') as fp:
        json.dump(report, fp, indent=2)

    # Reconstruction
    for f in files:
        reconstruct_file(os.path.join(corpus, f), os.path.join(recon, f))

    # Hex analysis
    for f in files:
        dump = hexdump_file(os.path.join(corpus, f))
        with open(os.path.join(hexdir, f + '.hexdump'), 'w') as fp:
            fp.write(dump)

    # Checksums
    compute_checksums(recon, '/app/checksums.txt')

    # HMAC integrity signatures
    compute_hmac(recon, '/app/hmac.key', '/app/integrity.sig')


if __name__ == '__main__':
    main()
