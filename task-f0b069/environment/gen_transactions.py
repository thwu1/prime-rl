#!/usr/bin/env python3
"""Generate ANSI/NIST-ITL test transaction files with deliberate conformance violations.

These files use the traditional (binary) encoding format defined in NIST SP 500-290.
Separator hierarchy: FS(0x1C) between records, GS(0x1D) between fields,
RS(0x1E) between subfields, US(0x1F) between information items.
"""

import os
import sys

US = b'\x1f'
RS = b'\x1e'
GS = b'\x1d'
FS = b'\x1c'


def encode_field(rtype, fnum, value):
    """Create a tagged field: '{rtype}.{fnum:03d}:{value}'."""
    tag = f"{rtype}.{fnum:03d}:".encode('ascii')
    if isinstance(value, str):
        value = value.encode('ascii')
    return tag + value


def build_record(rtype, fields, override_len=None):
    """Build a text-based ANSI/NIST-ITL record.

    Computes the LEN field (X.001) automatically to match actual byte count,
    unless override_len is set (for testing LEN mismatch violations).
    """
    parts = []
    for fnum in sorted(fields.keys()):
        if fnum == 1:
            continue
        parts.append(encode_field(rtype, fnum, fields[fnum]))

    len_tag = f"{rtype}.001:".encode('ascii')

    if parts:
        suffix = GS + GS.join(parts) + FS
    else:
        suffix = FS

    if override_len is not None:
        len_val = str(override_len).encode('ascii')
        return len_tag + len_val + suffix

    # Iteratively solve for LEN since the length value is part of the record
    start = len(len_tag) + 1 + len(suffix)
    for trial in range(start, start + 20):
        len_val = str(trial).encode('ascii')
        candidate = len_tag + len_val + suffix
        if len(candidate) == trial:
            return candidate

    raise ValueError(f"Cannot compute record length for type {rtype}")


def make_cnt(total, entries):
    """Build CNT field value.

    Args:
        total: total number of records including Type-1
        entries: list of (idc, record_type) tuples for non-Type-1 records
    """
    first = b'1' + US + str(total).encode('ascii')
    rest = [str(idc).encode('ascii') + US + str(rt).encode('ascii')
            for idc, rt in entries]
    return RS.join([first] + rest)


# ---- Transaction generators ----

def gen_valid():
    """No violations."""
    cnt = make_cnt(2, [(0, 2)])
    t1 = build_record(1, {
        2: '0300', 3: cnt, 4: 'CAR', 5: '20240715',
        7: 'TESTDAI001', 8: 'TESTORI001', 9: 'TCN20240715A001',
        11: '19.69', 12: '19.69',
    })
    t2 = build_record(2, {2: '0'})
    return t1 + t2


def gen_bad_version():
    """VER has wrong format (not 4 digits)."""
    cnt = make_cnt(2, [(0, 2)])
    t1 = build_record(1, {
        2: '05.2', 3: cnt, 4: 'CAR', 5: '20240715',
        7: 'TESTDAI001', 8: 'TESTORI001', 9: 'TCN20240715A002',
        11: '19.69', 12: '19.69',
    })
    t2 = build_record(2, {2: '0'})
    return t1 + t2


def gen_bad_date():
    """DAT has valid 8-digit format but invalid month (13)."""
    cnt = make_cnt(2, [(0, 2)])
    t1 = build_record(1, {
        2: '0300', 3: cnt, 4: 'CAR', 5: '20241315',
        7: 'TESTDAI001', 8: 'TESTORI001', 9: 'TCN20240715A003',
        11: '19.69', 12: '19.69',
    })
    t2 = build_record(2, {2: '0'})
    return t1 + t2


def gen_cnt_mismatch():
    """CNT declares 3 records (includes Type-4) but only Type-1 + Type-2 exist."""
    cnt = make_cnt(3, [(0, 2), (1, 4)])
    t1 = build_record(1, {
        2: '0300', 3: cnt, 4: 'CAR', 5: '20240715',
        7: 'TESTDAI001', 8: 'TESTORI001', 9: 'TCN20240715A004',
        11: '19.69', 12: '19.69',
    })
    t2 = build_record(2, {2: '0'})
    return t1 + t2


def gen_missing_fields():
    """Missing mandatory DAI (1.007) and ORI (1.008)."""
    cnt = make_cnt(2, [(0, 2)])
    t1 = build_record(1, {
        2: '0300', 3: cnt, 4: 'CAR', 5: '20240715',
        9: 'TCN20240715A005', 11: '19.69', 12: '19.69',
    })
    t2 = build_record(2, {2: '0'})
    return t1 + t2


def gen_len_mismatch():
    """Type-1 LEN says 999 but actual is ~141."""
    cnt = make_cnt(2, [(0, 2)])
    t1 = build_record(1, {
        2: '0300', 3: cnt, 4: 'CAR', 5: '20240715',
        7: 'TESTDAI001', 8: 'TESTORI001', 9: 'TCN20240715A006',
        11: '19.69', 12: '19.69',
    }, override_len=999)
    t2 = build_record(2, {2: '0'})
    return t1 + t2


def gen_idc_error():
    """Type-2 IDC is 5 but CNT declares IDC 0 for the Type-2 record."""
    cnt = make_cnt(2, [(0, 2)])
    t1 = build_record(1, {
        2: '0300', 3: cnt, 4: 'CAR', 5: '20240715',
        7: 'TESTDAI001', 8: 'TESTORI001', 9: 'TCN20240715A007',
        11: '19.69', 12: '19.69',
    })
    t2 = build_record(2, {2: '5'})
    return t1 + t2


def gen_multi_error():
    """Multiple violations: bad VER, bad DAT, bad PRY, missing TCN, bad NSR."""
    cnt = make_cnt(2, [(0, 2)])
    t1 = build_record(1, {
        2: 'v300', 3: cnt, 4: 'CAR', 5: '15-07-2024',
        6: '0', 7: 'TESTDAI001', 8: 'TESTORI001',
        11: '500', 12: '19.69',
    })
    t2 = build_record(2, {2: '0'})
    return t1 + t2


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else '/app/transactions'
    os.makedirs(outdir, exist_ok=True)

    files = {
        'valid.an2k': gen_valid(),
        'bad_version.an2k': gen_bad_version(),
        'bad_date.an2k': gen_bad_date(),
        'cnt_mismatch.an2k': gen_cnt_mismatch(),
        'missing_fields.an2k': gen_missing_fields(),
        'len_mismatch.an2k': gen_len_mismatch(),
        'idc_error.an2k': gen_idc_error(),
        'multi_error.an2k': gen_multi_error(),
    }

    for name, data in sorted(files.items()):
        path = os.path.join(outdir, name)
        with open(path, 'wb') as f:
            f.write(data)
        print(f"Generated {path} ({len(data)} bytes)")


if __name__ == '__main__':
    main()
