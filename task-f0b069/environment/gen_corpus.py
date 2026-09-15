#!/usr/bin/env python3
"""Generate ANSI/NIST-ITL test corpus with Type-1, Type-2, and Type-4 records.

Creates transaction files with deliberate conformance violations for testing.
Type-1/Type-2 use tagged-field encoding; Type-4 uses binary-header encoding.
"""

import os
import struct
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


def build_tagged_record(rtype, fields, override_len=None):
    """Build a tagged-field record (Type-1, Type-2).

    Computes the LEN field (x.001) to match actual byte count,
    unless override_len is set for testing LEN mismatch violations.
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

    # Solve self-referential length: LEN includes its own representation
    start = len(len_tag) + 1 + len(suffix)
    for trial in range(start, start + 20):
        len_val = str(trial).encode('ascii')
        candidate = len_tag + len_val + suffix
        if len(candidate) == trial:
            return candidate

    raise ValueError(f"Cannot compute record length for type {rtype}")


def build_type4_record(idc, imp=0, fgp=None, isr=0, hll=512, vll=512,
                       gca=0, image_size=100, override_len=None):
    """Build a Type-4 binary-header record.

    Layout: 4B length, 4B IDC, 1B IMP, 6B FGP, 1B ISR,
            2B HLL, 2B VLL, 1B GCA, image data
    """
    if fgp is None:
        fgp = [1, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
    fgp = (fgp + [0xFF] * 6)[:6]

    # Build header (after length field)
    header = struct.pack('>I', idc)          # IDC: 4 bytes
    header += struct.pack('B', imp)          # IMP: 1 byte
    for f in fgp:
        header += struct.pack('B', f)        # FGP: 6 bytes
    header += struct.pack('B', isr)          # ISR: 1 byte
    header += struct.pack('>H', hll)         # HLL: 2 bytes
    header += struct.pack('>H', vll)         # VLL: 2 bytes
    header += struct.pack('B', gca)          # GCA: 1 byte

    # Image data: deterministic bytes
    image_data = bytes([i % 256 for i in range(image_size)])
    header += image_data

    total_len = 4 + len(header)  # 4 for the length field itself
    if override_len is not None:
        length_bytes = struct.pack('>I', override_len)
    else:
        length_bytes = struct.pack('>I', total_len)

    return length_bytes + header


def make_cnt(entries):
    """Build CNT field value bytes.

    entries: [(idc, record_type), ...] for non-Type-1 records
    Total = 1 (Type-1) + len(entries)
    """
    total = 1 + len(entries)
    first = b'1' + US + str(total).encode('ascii')
    rest = [str(idc).encode('ascii') + US + str(rt).encode('ascii')
            for idc, rt in entries]
    return RS.join([first] + rest)


def make_t1(cnt_entries, overrides=None, override_len=None):
    """Build a standard Type-1 record."""
    fields = {
        2: '0300',
        3: make_cnt(cnt_entries),
        4: 'CRM',
        5: '20240115',
        7: 'MDNISTTST',
        8: 'MDFBI00901',
        9: 'TCN2024011500001',
        11: '19.69',
        12: '19.69',
    }
    if overrides:
        for k, v in overrides.items():
            if v is None:
                fields.pop(k, None)
            else:
                fields[k] = v
    return build_tagged_record(1, fields, override_len=override_len)


def make_t2(idc_val='0', override_len=None):
    """Build a standard Type-2 record."""
    return build_tagged_record(2, {2: idc_val}, override_len=override_len)


def write_file(outdir, name, data):
    path = os.path.join(outdir, name)
    with open(path, 'wb') as f:
        f.write(data)
    print(f"Generated {path} ({len(data)} bytes)")


def generate_corpus(outdir):
    os.makedirs(outdir, exist_ok=True)

    # 1. valid_basic.an2k -- Valid Type-1 + Type-2, no violations
    t1 = make_t1([(0, 2)])
    t2 = make_t2('0')
    write_file(outdir, 'valid_basic.an2k', t1 + t2)

    # 2. valid_with_t4.an2k -- Valid Type-1 + Type-2 + Type-4, no violations
    t1 = make_t1([(0, 2), (1, 4)])
    t2 = make_t2('0')
    t4 = build_type4_record(idc=1)
    write_file(outdir, 'valid_with_t4.an2k', t1 + t2 + t4)

    # 3. corrupt_t1_multi.an2k -- Multiple Type-1 violations
    #    Bad VER, bad DAT, bad PRY, missing TCN, wrong LEN
    t1 = make_t1([(0, 2)], overrides={
        2: '30',           # Not 4 digits -> T1_VER_FORMAT
        5: '2024-01-15',   # Contains hyphens -> T1_DAT_FORMAT
        6: '0',            # Out of 1-9 range -> T1_PRY_RANGE
        9: None,           # Missing -> T1_MISSING_TCN
    }, override_len=999)   # Wrong LEN -> T1_LEN_MISMATCH
    t2 = make_t2('0')
    write_file(outdir, 'corrupt_t1_multi.an2k', t1 + t2)

    # 4. corrupt_t4_header.an2k -- Type-4 header violations
    t1 = make_t1([(0, 2), (1, 4)])
    t2 = make_t2('0')
    t4 = build_type4_record(idc=1, imp=20, gca=5, override_len=9999)
    # IMP=20 (>15) -> T4_IMP_RANGE, GCA=5 -> T4_GCA_VALUE, LEN wrong -> T4_LEN_MISMATCH
    write_file(outdir, 'corrupt_t4_header.an2k', t1 + t2 + t4)

    # 5. corrupt_cnt.an2k -- CNT count mismatch + missing records
    #    CNT claims 4 records but only Type-1 + Type-2 exist
    t1 = make_t1([(0, 2), (1, 4), (2, 10)])
    t2 = make_t2('0')
    write_file(outdir, 'corrupt_cnt.an2k', t1 + t2)

    # 6. corrupt_t2_idc.an2k -- Type-2 IDC doesn't match CNT
    t1 = make_t1([(0, 2)])  # CNT says IDC=0 for Type-2
    t2 = make_t2('5')       # But Type-2 has IDC=5
    write_file(outdir, 'corrupt_t2_idc.an2k', t1 + t2)

    # 7. corrupt_t4_idc.an2k -- Type-4 IDC doesn't match CNT
    t1 = make_t1([(0, 2), (1, 4)])  # CNT says IDC=1 for Type-4
    t2 = make_t2('0')
    t4 = build_type4_record(idc=99)  # IDC=99, should be 1
    write_file(outdir, 'corrupt_t4_idc.an2k', t1 + t2 + t4)

    # 8. corrupt_mandatory.an2k -- Missing mandatory fields
    t1 = make_t1([(0, 2)], overrides={
        4: None,  # Missing TOT -> T1_MISSING_TOT
        7: None,  # Missing DAI -> T1_MISSING_DAI
        8: None,  # Missing ORI -> T1_MISSING_ORI
    })
    t2 = make_t2('0')
    write_file(outdir, 'corrupt_mandatory.an2k', t1 + t2)

    # 9. corrupt_resolution.an2k -- Cross-record: Type-4 ISR=1 but NSR too low
    t1 = make_t1([(0, 2), (1, 4)], overrides={
        11: '10.00',  # Valid format but < 19.69
        12: '10.00',
    })
    t2 = make_t2('0')
    t4 = build_type4_record(idc=1, isr=1)  # ISR=1 -> use NSR -> 10.00 < 19.69
    write_file(outdir, 'corrupt_resolution.an2k', t1 + t2 + t4)

    # 10. corrupt_t4_dims.an2k -- Type-4 dimension violations
    t1 = make_t1([(0, 2), (1, 4)])
    t2 = make_t2('0')
    t4 = build_type4_record(
        idc=1, hll=0, vll=0,
        fgp=[1, 20, 0xFF, 0xFF, 0xFF, 0xFF],
    )
    # HLL=0 -> T4_HLL_ZERO, VLL=0 -> T4_VLL_ZERO, FGP byte 20 -> T4_FGP_RANGE
    write_file(outdir, 'corrupt_t4_dims.an2k', t1 + t2 + t4)

    # 11. corrupt_formats.an2k -- NSR/NTR format violations
    t1 = make_t1([(0, 2)], overrides={
        11: '500ppi',  # Not dd.dd -> T1_NSR_FORMAT
        12: '19',      # Not dd.dd -> T1_NTR_FORMAT
    })
    t2 = make_t2('0')
    write_file(outdir, 'corrupt_formats.an2k', t1 + t2)


if __name__ == '__main__':
    outdir = sys.argv[1] if len(sys.argv) > 1 else '/app/corpus'
    generate_corpus(outdir)
