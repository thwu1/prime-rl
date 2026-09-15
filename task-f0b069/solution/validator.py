#!/usr/bin/env python3
"""ANSI/NIST-ITL 1-2011 Conformance Validator.

Parses biometric transaction files in traditional encoding and checks conformance
against Type-1 and Type-2 record requirements defined in NIST SP 500-290.

Traditional encoding uses:
  FS (0x1C) - terminates each logical record
  GS (0x1D) - separates fields within a record
  RS (0x1E) - separates subfields within a field
  US (0x1F) - separates information items within a subfield

Each field begins with a tagged identifier: {record_type}.{field_number:03d}:{value}
"""

import json
import os
import re
import sys

FS = 0x1C  # File Separator
GS = 0x1D  # Group Separator
RS = 0x1E  # Record Separator
US = 0x1F  # Unit Separator


def parse_transaction(data):
    """Parse a transaction file into a list of record dicts.

    Each record dict contains:
      _type: int record type number
      _raw_length: int actual byte length including FS terminator
      _fields: dict of field_number (int) -> value (bytes)
    """
    records_raw = data.split(bytes([FS]))
    # Last element is empty (after trailing FS)
    if records_raw and records_raw[-1] == b'':
        records_raw = records_raw[:-1]

    records = []
    for rec_bytes in records_raw:
        if not rec_bytes:
            continue

        fields_raw = rec_bytes.split(bytes([GS]))
        record = {
            '_type': None,
            '_raw_length': len(rec_bytes) + 1,  # +1 for FS byte
            '_fields': {},
        }

        for field_raw in fields_raw:
            colon_pos = field_raw.find(b':')
            if colon_pos < 0:
                continue

            tag = field_raw[:colon_pos].decode('ascii', errors='replace')
            value = field_raw[colon_pos + 1:]

            dot_pos = tag.find('.')
            if dot_pos < 0:
                continue

            try:
                rtype = int(tag[:dot_pos])
                fnum = int(tag[dot_pos + 1:])
            except ValueError:
                continue

            if record['_type'] is None:
                record['_type'] = rtype
            record['_fields'][fnum] = value

        if record['_type'] is not None:
            records.append(record)

    return records


def parse_cnt_entries(cnt_value):
    """Parse CNT field value into (declared_count, entries).

    Returns:
      declared_count: int total declared record count
      entries: list of (idc, record_type) tuples for non-Type-1 records
    """
    subfields = cnt_value.split(bytes([RS]))
    declared_count = 0
    entries = []

    if subfields:
        first_items = subfields[0].split(bytes([US]))
        if len(first_items) >= 2:
            try:
                declared_count = int(first_items[1].decode('ascii'))
            except (ValueError, UnicodeDecodeError):
                pass

        for sf in subfields[1:]:
            items = sf.split(bytes([US]))
            if len(items) >= 2:
                try:
                    idc = int(items[0].decode('ascii'))
                    rtype = int(items[1].decode('ascii'))
                    entries.append((idc, rtype))
                except (ValueError, UnicodeDecodeError):
                    pass

    return declared_count, entries


def validate_type1(record, all_records):
    """Validate a Type-1 record. Returns list of violation codes."""
    violations = []
    fields = record['_fields']

    # 1.001 LEN — must match actual record byte length
    if 1 in fields:
        try:
            declared_len = int(fields[1].decode('ascii'))
            if declared_len != record['_raw_length']:
                violations.append('T1_LEN_MISMATCH')
        except (ValueError, UnicodeDecodeError):
            violations.append('T1_LEN_MISMATCH')

    # 1.002 VER — exactly 4 decimal digits
    if 2 in fields:
        ver = fields[2].decode('ascii', errors='replace')
        if not re.match(r'^\d{4}$', ver):
            violations.append('T1_VER_FORMAT')

    # 1.003 CNT — consistency checks
    if 3 in fields:
        declared_count, cnt_entries = parse_cnt_entries(fields[3])

        # Check declared count matches actual number of records
        if declared_count != len(all_records):
            violations.append('T1_CNT_COUNT')

        # Check each referenced record type exists in the transaction
        actual_types = {rec['_type'] for rec in all_records}
        for _idc, rtype in cnt_entries:
            if rtype not in actual_types:
                violations.append('T1_CNT_RECORDS_MISSING')
                break  # Report once

    # 1.004 TOT — mandatory
    if 4 not in fields:
        violations.append('T1_TOT_MISSING')

    # 1.005 DAT — mandatory, format YYYYMMDD with valid month/day
    if 5 in fields:
        dat = fields[5].decode('ascii', errors='replace')
        if not re.match(r'^\d{8}$', dat):
            violations.append('T1_DAT_FORMAT')
        else:
            mm = int(dat[4:6])
            dd = int(dat[6:8])
            if mm < 1 or mm > 12 or dd < 1 or dd > 31:
                violations.append('T1_DAT_FORMAT')
    else:
        violations.append('T1_DAT_MISSING')

    # 1.006 PRY — optional, but if present must be single digit 1-9
    if 6 in fields:
        pry = fields[6].decode('ascii', errors='replace')
        if not re.match(r'^[1-9]$', pry):
            violations.append('T1_PRY_RANGE')

    # 1.007 DAI — mandatory
    if 7 not in fields:
        violations.append('T1_DAI_MISSING')

    # 1.008 ORI — mandatory
    if 8 not in fields:
        violations.append('T1_ORI_MISSING')

    # 1.009 TCN — mandatory
    if 9 not in fields:
        violations.append('T1_TCN_MISSING')

    # 1.011 NSR — mandatory, format nn.nn (two digits, dot, two digits)
    if 11 in fields:
        nsr = fields[11].decode('ascii', errors='replace')
        if not re.match(r'^\d{2}\.\d{2}$', nsr):
            violations.append('T1_NSR_FORMAT')
    else:
        violations.append('T1_NSR_MISSING')

    # 1.012 NTR — mandatory, format nn.nn
    if 12 in fields:
        ntr = fields[12].decode('ascii', errors='replace')
        if not re.match(r'^\d{2}\.\d{2}$', ntr):
            violations.append('T1_NTR_FORMAT')
    else:
        violations.append('T1_NTR_MISSING')

    return violations


def validate_type2(record, cnt_entries):
    """Validate a Type-2 record. Returns list of violation codes."""
    violations = []
    fields = record['_fields']

    # 2.002 IDC — must match what CNT declares for this record type
    if 2 in fields:
        try:
            idc = int(fields[2].decode('ascii'))
            matching = [e for e in cnt_entries if e[1] == 2]
            if matching:
                expected_idcs = [e[0] for e in matching]
                if idc not in expected_idcs:
                    violations.append('T2_IDC_MISMATCH')
        except (ValueError, UnicodeDecodeError):
            pass

    return violations


def validate_file(filepath):
    """Validate a single ANSI/NIST-ITL transaction file.

    Args:
        filepath: path to .an2k file

    Returns:
        Sorted list of violation code strings.
    """
    with open(filepath, 'rb') as f:
        data = f.read()

    records = parse_transaction(data)
    all_violations = []

    # Find Type-1 record and parse CNT entries
    type1 = None
    cnt_entries = []
    for rec in records:
        if rec['_type'] == 1:
            type1 = rec
            if 3 in rec['_fields']:
                _, cnt_entries = parse_cnt_entries(rec['_fields'][3])
            break

    # Validate Type-1
    if type1:
        all_violations.extend(validate_type1(type1, records))

    # Validate Type-2 records
    for rec in records:
        if rec['_type'] == 2:
            all_violations.extend(validate_type2(rec, cnt_entries))

    return sorted(set(all_violations))


def main():
    """Process all .an2k files in /app/transactions/ and write results.json."""
    trans_dir = '/app/transactions'
    results = {}

    for fname in sorted(os.listdir(trans_dir)):
        if fname.endswith('.an2k'):
            fpath = os.path.join(trans_dir, fname)
            violations = validate_file(fpath)
            results[fname] = violations

    output_path = '/app/results.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, sort_keys=True)

    print(f"Results written to {output_path}")
    for fname, viols in sorted(results.items()):
        status = "PASS" if not viols else f"FAIL ({len(viols)} violations)"
        print(f"  {fname}: {status}")
        for v in viols:
            print(f"    - {v}")


if __name__ == '__main__':
    main()
