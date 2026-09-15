#!/usr/bin/env python3
"""ANSI/NIST-ITL 1-2011 Traditional Encoding Conformance Analyzer.

Parses biometric transaction files containing tagged-field records (Type-1, 2)
and binary-header records (Type-4), validates conformance per the specification,
and reports violations.
"""

import json
import os
import re
import struct
import sys

US = b'\x1f'
RS = b'\x1e'
GS = b'\x1d'
FS = b'\x1c'

# Record types using binary-header encoding (Types 3-6)
BINARY_TYPES = {3, 4, 5, 6}


def parse_tagged_fields(data):
    """Parse tagged-field data (without trailing FS) into {field_num: value_bytes}.

    Each field is 'type.num:value', fields separated by GS.
    Returns dict mapping field number to raw value bytes.
    """
    fields = {}
    for field_data in data.split(GS):
        if not field_data:
            continue
        colon_pos = field_data.find(b':')
        if colon_pos == -1:
            continue
        tag = field_data[:colon_pos]
        value = field_data[colon_pos + 1:]
        try:
            tag_str = tag.decode('ascii')
            dot_pos = tag_str.find('.')
            if dot_pos == -1:
                continue
            fnum = int(tag_str[dot_pos + 1:])
            fields[fnum] = value
        except (ValueError, UnicodeDecodeError):
            continue
    return fields


def parse_cnt(cnt_bytes):
    """Parse CNT field value into (total_count, [(idc, record_type), ...]).

    CNT structure: subfield1(type=1, total) RS subfield2(idc, rt) RS ...
    Items within subfields separated by US, subfields separated by RS.
    """
    subfields = cnt_bytes.split(RS)
    if not subfields:
        return 0, []

    first_items = subfields[0].split(US)
    total = 0
    if len(first_items) >= 2:
        try:
            total = int(first_items[1].decode('ascii'))
        except (ValueError, UnicodeDecodeError):
            pass

    entries = []
    for sf in subfields[1:]:
        items = sf.split(US)
        if len(items) >= 2:
            try:
                idc = int(items[0].decode('ascii'))
                rt = int(items[1].decode('ascii'))
                entries.append((idc, rt))
            except (ValueError, UnicodeDecodeError):
                continue

    return total, entries


def parse_type4_header(data):
    """Parse Type-4 binary record header fields.

    Returns dict with parsed field values.
    Layout: 4B len, 4B IDC, 1B IMP, 6B FGP, 1B ISR, 2B HLL, 2B VLL, 1B GCA
    """
    result = {'actual_len': len(data)}

    if len(data) >= 4:
        result['len'] = struct.unpack('>I', data[0:4])[0]
    if len(data) >= 8:
        result['idc'] = struct.unpack('>I', data[4:8])[0]
    if len(data) >= 9:
        result['imp'] = data[8]
    if len(data) >= 15:
        result['fgp'] = list(data[9:15])
    if len(data) >= 16:
        result['isr'] = data[15]
    if len(data) >= 18:
        result['hll'] = struct.unpack('>H', data[16:18])[0]
    if len(data) >= 20:
        result['vll'] = struct.unpack('>H', data[18:20])[0]
    if len(data) >= 21:
        result['gca'] = data[20]

    return result


def _valid_date(val):
    """Check YYYYMMDD: 8 digits, month 01-12, day 01-31."""
    if len(val) != 8 or not val.isdigit():
        return False
    month = int(val[4:6])
    day = int(val[6:8])
    return 1 <= month <= 12 and 1 <= day <= 31


def _valid_resolution(val):
    """Check dd.dd pattern: exactly 2 digits, dot, 2 digits."""
    return bool(re.match(r'^\d{2}\.\d{2}$', val))


def validate_type1(fields, actual_len):
    """Validate Type-1 record fields. Returns list of violation codes."""
    violations = []

    # LEN (1.001)
    if 1 in fields:
        try:
            declared = int(fields[1].decode('ascii'))
            if declared != actual_len:
                violations.append('T1_LEN_MISMATCH')
        except (ValueError, UnicodeDecodeError):
            violations.append('T1_LEN_MISMATCH')

    # VER (1.002)
    if 2 in fields:
        try:
            ver = fields[2].decode('ascii')
            if not (len(ver) == 4 and ver.isdigit()):
                violations.append('T1_VER_FORMAT')
        except UnicodeDecodeError:
            violations.append('T1_VER_FORMAT')

    # Mandatory presence-only checks
    for fnum, code in [(4, 'T1_MISSING_TOT'), (7, 'T1_MISSING_DAI'),
                       (8, 'T1_MISSING_ORI'), (9, 'T1_MISSING_TCN')]:
        if fnum not in fields or not fields[fnum].strip():
            violations.append(code)

    # DAT (1.005)
    if 5 not in fields:
        violations.append('T1_MISSING_DAT')
    else:
        try:
            dat = fields[5].decode('ascii')
            if not _valid_date(dat):
                violations.append('T1_DAT_FORMAT')
        except UnicodeDecodeError:
            violations.append('T1_DAT_FORMAT')

    # PRY (1.006) -- optional
    if 6 in fields:
        try:
            pry = fields[6].decode('ascii')
            if not (len(pry) == 1 and pry.isdigit() and 1 <= int(pry) <= 9):
                violations.append('T1_PRY_RANGE')
        except UnicodeDecodeError:
            violations.append('T1_PRY_RANGE')

    # NSR (1.011)
    if 11 not in fields:
        violations.append('T1_MISSING_NSR')
    else:
        try:
            nsr = fields[11].decode('ascii')
            if not _valid_resolution(nsr):
                violations.append('T1_NSR_FORMAT')
        except UnicodeDecodeError:
            violations.append('T1_NSR_FORMAT')

    # NTR (1.012)
    if 12 not in fields:
        violations.append('T1_MISSING_NTR')
    else:
        try:
            ntr = fields[12].decode('ascii')
            if not _valid_resolution(ntr):
                violations.append('T1_NTR_FORMAT')
        except UnicodeDecodeError:
            violations.append('T1_NTR_FORMAT')

    return violations


def validate_type2(fields, actual_len, expected_idc):
    """Validate Type-2 record fields."""
    violations = []

    # LEN (2.001)
    if 1 in fields:
        try:
            declared = int(fields[1].decode('ascii'))
            if declared != actual_len:
                violations.append('T2_LEN_MISMATCH')
        except (ValueError, UnicodeDecodeError):
            violations.append('T2_LEN_MISMATCH')

    # IDC (2.002)
    if 2 in fields:
        try:
            idc = int(fields[2].decode('ascii'))
            if idc != expected_idc:
                violations.append('T2_IDC_MISMATCH')
        except (ValueError, UnicodeDecodeError):
            violations.append('T2_IDC_MISMATCH')

    return violations


def validate_type4(header, expected_idc, nsr_value):
    """Validate Type-4 record fields and cross-record checks."""
    violations = []

    # LEN
    if 'len' in header:
        if header['len'] != header['actual_len']:
            violations.append('T4_LEN_MISMATCH')

    # IDC
    if 'idc' in header:
        if header['idc'] != expected_idc:
            violations.append('T4_IDC_MISMATCH')

    # IMP (0-15)
    if 'imp' in header:
        if header['imp'] > 15:
            violations.append('T4_IMP_RANGE')

    # FGP (each byte 0-10 or 255)
    if 'fgp' in header:
        for b in header['fgp']:
            if not (0 <= b <= 10 or b == 255):
                violations.append('T4_FGP_RANGE')
                break

    # ISR (0 or 1)
    if 'isr' in header:
        if header['isr'] not in (0, 1):
            violations.append('T4_ISR_VALUE')

    # HLL (> 0)
    if 'hll' in header:
        if header['hll'] == 0:
            violations.append('T4_HLL_ZERO')

    # VLL (> 0)
    if 'vll' in header:
        if header['vll'] == 0:
            violations.append('T4_VLL_ZERO')

    # GCA (0 or 1)
    if 'gca' in header:
        if header['gca'] not in (0, 1):
            violations.append('T4_GCA_VALUE')

    # Image data presence (record > 21 bytes)
    if header['actual_len'] <= 21:
        violations.append('T4_NO_IMAGE_DATA')

    # Cross-record: resolution check when ISR=1
    if 'isr' in header and header['isr'] == 1 and nsr_value is not None:
        try:
            nsr_float = float(nsr_value)
            if nsr_float < 19.69:
                violations.append('T4_RESOLUTION_LOW')
        except (ValueError, TypeError):
            pass  # Missing/malformed NSR handled by T1_MISSING_NSR/T1_NSR_FORMAT

    return violations


def analyze_file(filepath):
    """Analyze a transaction file and return sorted, deduplicated violation codes."""
    with open(filepath, 'rb') as f:
        data = f.read()

    violations = set()
    pos = 0

    # --- Parse Type-1 record (always first, tagged, FS-terminated) ---
    fs_pos = data.find(FS, pos)
    if fs_pos == -1:
        return sorted(violations)

    t1_data = data[pos:fs_pos]
    t1_len = fs_pos - pos + 1  # Include FS byte
    t1_fields = parse_tagged_fields(t1_data)
    violations.update(validate_type1(t1_fields, t1_len))
    pos = fs_pos + 1

    # --- Extract CNT for record sequence ---
    cnt_total = 0
    cnt_entries = []
    if 3 in t1_fields:
        cnt_total, cnt_entries = parse_cnt(t1_fields[3])

    # Extract NSR value for cross-record validation (only if valid format)
    nsr_value = None
    if 11 in t1_fields:
        try:
            nsr_str = t1_fields[11].decode('ascii')
            if _valid_resolution(nsr_str):
                nsr_value = nsr_str
        except UnicodeDecodeError:
            pass

    # --- Parse subsequent records per CNT order ---
    found_records = 1  # Type-1 already counted

    for expected_idc, expected_type in cnt_entries:
        if pos >= len(data):
            violations.add('T1_CNT_MISSING_REF')
            continue

        if expected_type in BINARY_TYPES:
            # Binary-header record
            if pos + 4 > len(data):
                violations.add('T1_CNT_MISSING_REF')
                continue

            declared_len = struct.unpack('>I', data[pos:pos + 4])[0]
            actual_remaining = len(data) - pos
            record_len = min(declared_len, actual_remaining)
            record_data = data[pos:pos + record_len]

            if expected_type == 4:
                header = parse_type4_header(record_data)
                violations.update(validate_type4(header, expected_idc, nsr_value))

            pos += record_len
            found_records += 1

        else:
            # Tagged-field record
            fs_pos = data.find(FS, pos)
            if fs_pos == -1:
                violations.add('T1_CNT_MISSING_REF')
                continue

            record_data = data[pos:fs_pos]
            record_len = fs_pos - pos + 1  # Include FS
            record_fields = parse_tagged_fields(record_data)

            if expected_type == 2:
                violations.update(
                    validate_type2(record_fields, record_len, expected_idc)
                )

            pos = fs_pos + 1
            found_records += 1

    # CNT count validation
    if cnt_total != found_records:
        violations.add('T1_CNT_COUNT')

    return sorted(violations)


def main():
    corpus_dir = '/app/corpus'
    results = {}

    for fname in sorted(os.listdir(corpus_dir)):
        if fname.endswith('.an2k'):
            filepath = os.path.join(corpus_dir, fname)
            results[fname] = analyze_file(filepath)

    with open('/app/report.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Analyzed {len(results)} files, wrote /app/report.json")


if __name__ == '__main__':
    main()
