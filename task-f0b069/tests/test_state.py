"""Tests for ANSI/NIST-ITL forensic toolkit.

Verifies validation, reconstruction, hex analysis, integrity verification,
and HMAC signing across static corpus and dynamically generated transactions.
"""

import json
import os
import re
import struct
import subprocess
import sys

import pytest

sys.path.insert(0, '/app')

# ANSI/NIST-ITL separator bytes
US = b'\x1f'
RS = b'\x1e'
GS = b'\x1d'
FS = b'\x1c'

# Expected violations per static corpus file
EXPECTED = {
    'valid_basic.an2k': [],
    'valid_with_t4.an2k': [],
    'corrupt_t1_multi.an2k': [
        'T1_DAT_FORMAT', 'T1_LEN_MISMATCH', 'T1_MISSING_TCN',
        'T1_PRY_RANGE', 'T1_VER_FORMAT',
    ],
    'corrupt_t4_header.an2k': [
        'T4_GCA_VALUE', 'T4_IMP_RANGE', 'T4_LEN_MISMATCH',
    ],
    'corrupt_cnt.an2k': [
        'T1_CNT_COUNT', 'T1_CNT_MISSING_REF',
    ],
    'corrupt_t2_idc.an2k': ['T2_IDC_MISMATCH'],
    'corrupt_t4_idc.an2k': ['T4_IDC_MISMATCH'],
    'corrupt_mandatory.an2k': [
        'T1_MISSING_DAI', 'T1_MISSING_ORI', 'T1_MISSING_TOT',
    ],
    'corrupt_resolution.an2k': ['T4_RESOLUTION_LOW'],
    'corrupt_t4_dims.an2k': [
        'T4_FGP_RANGE', 'T4_HLL_ZERO', 'T4_VLL_ZERO',
    ],
    'corrupt_formats.an2k': [
        'T1_NSR_FORMAT', 'T1_NTR_FORMAT',
    ],
}

VALID_FILES = ['valid_basic.an2k', 'valid_with_t4.an2k']
CORRUPT_FILES = [f for f in EXPECTED if EXPECTED[f]]


# ---------- Helper functions for building test records ----------

def _build_tagged_record(rtype, fields_dict, override_len=None):
    """Build a tagged-field record from field dict."""
    parts = []
    for fnum in sorted(fields_dict.keys()):
        if fnum == 1:
            continue
        tag = f"{rtype}.{fnum:03d}:".encode('ascii')
        val = fields_dict[fnum]
        if isinstance(val, str):
            val = val.encode('ascii')
        parts.append(tag + val)

    len_tag = f"{rtype}.001:".encode('ascii')
    suffix = (GS + GS.join(parts) + FS) if parts else FS

    if override_len is not None:
        return len_tag + str(override_len).encode('ascii') + suffix

    start = len(len_tag) + 1 + len(suffix)
    for trial in range(start, start + 20):
        if len(len_tag + str(trial).encode('ascii') + suffix) == trial:
            return len_tag + str(trial).encode('ascii') + suffix
    raise ValueError("Cannot compute length")


def _build_type4_record(idc, imp=0, fgp=None, isr=0, hll=512, vll=512,
                        gca=0, image_size=50, override_len=None):
    """Build a Type-4 binary-header record."""
    if fgp is None:
        fgp = [1, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
    fgp = (fgp + [0xFF] * 6)[:6]
    header = struct.pack('>I', idc)
    header += struct.pack('B', imp)
    for f in fgp:
        header += struct.pack('B', f)
    header += struct.pack('B', isr)
    header += struct.pack('>H', hll)
    header += struct.pack('>H', vll)
    header += struct.pack('B', gca)
    header += bytes([i % 256 for i in range(image_size)])
    total_len = 4 + len(header)
    length_bytes = struct.pack('>I', override_len if override_len else total_len)
    return length_bytes + header


def _make_cnt(entries):
    """Build CNT field value bytes."""
    total = 1 + len(entries)
    first = b'1' + US + str(total).encode('ascii')
    rest = [str(idc).encode('ascii') + US + str(rt).encode('ascii')
            for idc, rt in entries]
    return RS.join([first] + rest)


def _make_t1_fields(cnt_entries, overrides=None):
    """Build standard Type-1 field dict."""
    fields = {
        2: '0300', 3: _make_cnt(cnt_entries), 4: 'TST', 5: '20240101',
        7: 'DAITEST', 8: 'ORITEST', 9: 'TCNDYN', 11: '19.69', 12: '19.69',
    }
    if overrides:
        for k, v in overrides.items():
            if v is None:
                fields.pop(k, None)
            else:
                fields[k] = v
    return fields


def _write_temp(name, data):
    """Write transaction data to a temp file and return path."""
    path = f'/tmp/dyn_{name}.an2k'
    with open(path, 'wb') as f:
        f.write(data)
    return path


# ---------- Fixtures ----------

@pytest.fixture(scope="session")
def run_toolkit():
    """Run the toolkit to produce all outputs."""
    if os.path.exists('/app/report.json'):
        os.remove('/app/report.json')
    result = subprocess.run(
        ['python3', '/app/toolkit.py'],
        capture_output=True, text=True, cwd='/app',
    )
    assert result.returncode == 0, (
        f"Toolkit failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists('/app/report.json'), "Toolkit did not create /app/report.json"


@pytest.fixture(scope="session")
def results(run_toolkit):
    """Load report.json produced by the toolkit."""
    with open('/app/report.json') as f:
        return json.load(f)


@pytest.fixture(scope="session")
def analyze_fn():
    """Import analyze_file from toolkit."""
    from toolkit import analyze_file
    return analyze_file


@pytest.fixture(scope="session")
def reconstruct_fn():
    """Import reconstruct_file from toolkit."""
    from toolkit import reconstruct_file
    return reconstruct_file


# ========================================================
# SECTION 1: Static validation tests
# ========================================================

def test_report_file_created(run_toolkit):
    assert os.path.exists('/app/report.json')


def test_all_corpus_files_present(results):
    for fname in EXPECTED:
        assert fname in results, f"Missing results for {fname}"


@pytest.mark.parametrize("filename,expected_violations", list(EXPECTED.items()))
def test_violations(results, filename, expected_violations):
    actual = sorted(results.get(filename, []))
    expected = sorted(expected_violations)
    assert actual == expected, (
        f"Violations mismatch for {filename}:\n"
        f"  Expected: {expected}\n"
        f"  Actual:   {actual}"
    )


def test_valid_basic_clean(results):
    assert results.get('valid_basic.an2k') == []


def test_valid_with_t4_clean(results):
    assert results.get('valid_with_t4.an2k') == []


def test_total_violation_count(results):
    total = sum(len(v) for v in results.values())
    expected_total = sum(len(v) for v in EXPECTED.values())
    assert total == expected_total, (
        f"Total violations: expected {expected_total}, got {total}"
    )


def test_report_values_are_sorted(results):
    for fname, violations in results.items():
        assert violations == sorted(violations), (
            f"Violations for {fname} not sorted"
        )


# ========================================================
# SECTION 2: Reconstruction tests
# ========================================================

def test_reconstructed_dir_exists(run_toolkit):
    assert os.path.isdir('/app/reconstructed')


def test_reconstructed_files_exist(run_toolkit):
    for fname in EXPECTED:
        path = f'/app/reconstructed/{fname}'
        assert os.path.exists(path), f"Missing reconstructed file: {fname}"


def test_reconstructed_pass_validation(run_toolkit, analyze_fn):
    """All reconstructed files must pass validation with zero violations."""
    for fname in EXPECTED:
        path = f'/app/reconstructed/{fname}'
        violations = analyze_fn(path)
        assert violations == [], (
            f"Reconstructed {fname} has violations: {violations}"
        )


def test_reconstructed_valid_files_unchanged(run_toolkit):
    """Valid files must produce byte-identical reconstructed output."""
    for fname in VALID_FILES:
        orig = f'/app/corpus/{fname}'
        recon = f'/app/reconstructed/{fname}'
        with open(orig, 'rb') as f:
            orig_data = f.read()
        with open(recon, 'rb') as f:
            recon_data = f.read()
        assert orig_data == recon_data, (
            f"Reconstructed {fname} differs from original "
            f"(orig={len(orig_data)} bytes, recon={len(recon_data)} bytes)"
        )


def test_reconstructed_t1_multi_ver_repaired(run_toolkit):
    """corrupt_t1_multi: VER must be repaired to '0300'."""
    with open('/app/reconstructed/corrupt_t1_multi.an2k', 'rb') as f:
        data = f.read()
    assert b'1.002:0300' in data, "VER not repaired to '0300'"


def test_reconstructed_t1_multi_dat_repaired(run_toolkit):
    """corrupt_t1_multi: DAT must be repaired to '19700101'."""
    with open('/app/reconstructed/corrupt_t1_multi.an2k', 'rb') as f:
        data = f.read()
    assert b'1.005:19700101' in data, "DAT not repaired to '19700101'"


def test_reconstructed_t1_multi_pry_removed(run_toolkit):
    """corrupt_t1_multi: invalid PRY must be removed."""
    with open('/app/reconstructed/corrupt_t1_multi.an2k', 'rb') as f:
        data = f.read()
    assert b'1.006:' not in data, "PRY field should be removed"


def test_reconstructed_t1_multi_tcn_inserted(run_toolkit):
    """corrupt_t1_multi: missing TCN must be inserted with default."""
    with open('/app/reconstructed/corrupt_t1_multi.an2k', 'rb') as f:
        data = f.read()
    assert b'1.009:REPAIR000' in data, "TCN not inserted with default 'REPAIR000'"


def test_reconstructed_mandatory_fields_inserted(run_toolkit):
    """corrupt_mandatory: missing TOT, DAI, ORI must be inserted."""
    with open('/app/reconstructed/corrupt_mandatory.an2k', 'rb') as f:
        data = f.read()
    assert b'1.004:UNK' in data, "TOT not inserted"
    assert b'1.007:UNKNOWN' in data, "DAI not inserted"
    assert b'1.008:UNKNOWN' in data, "ORI not inserted"


def test_reconstructed_t4_header_imp_repaired(run_toolkit):
    """corrupt_t4_header: IMP must be repaired to 0."""
    with open('/app/reconstructed/corrupt_t4_header.an2k', 'rb') as f:
        data = f.read()
    # Find Type-4 start (after two FS-terminated tagged records)
    first_fs = data.index(FS)
    second_fs = data.index(FS, first_fs + 1)
    t4_start = second_fs + 1
    assert t4_start + 21 <= len(data), "Type-4 record too short"
    imp = data[t4_start + 8]
    assert imp == 0, f"IMP should be 0, got {imp}"
    gca = data[t4_start + 20]
    assert gca == 0, f"GCA should be 0, got {gca}"


def test_reconstructed_t4_dims_repaired(run_toolkit):
    """corrupt_t4_dims: HLL/VLL must be non-zero, FGP must be valid."""
    with open('/app/reconstructed/corrupt_t4_dims.an2k', 'rb') as f:
        data = f.read()
    first_fs = data.index(FS)
    second_fs = data.index(FS, first_fs + 1)
    t4_start = second_fs + 1
    hll = struct.unpack('>H', data[t4_start + 16:t4_start + 18])[0]
    vll = struct.unpack('>H', data[t4_start + 18:t4_start + 20])[0]
    assert hll > 0, f"HLL should be > 0, got {hll}"
    assert vll > 0, f"VLL should be > 0, got {vll}"
    fgp = list(data[t4_start + 9:t4_start + 15])
    for fb in fgp:
        assert fb <= 10 or fb == 0xFF, f"FGP byte {fb} out of valid range"


def test_reconstructed_resolution_nsr_fixed(run_toolkit):
    """corrupt_resolution: NSR must be raised to at least 19.69."""
    with open('/app/reconstructed/corrupt_resolution.an2k', 'rb') as f:
        data = f.read()
    # Check that NSR field is '19.69'
    assert b'1.011:19.69' in data, "NSR not repaired to '19.69'"


def test_reconstructed_formats_fixed(run_toolkit):
    """corrupt_formats: NSR/NTR must be valid dd.dd format."""
    with open('/app/reconstructed/corrupt_formats.an2k', 'rb') as f:
        data = f.read()
    assert b'1.011:19.69' in data, "NSR not repaired"
    assert b'1.012:19.69' in data, "NTR not repaired"


# ========================================================
# SECTION 3: Hex analysis tests
# ========================================================

def test_hexanalysis_dir_exists(run_toolkit):
    assert os.path.isdir('/app/hexanalysis')


def test_hexanalysis_files_exist(run_toolkit):
    for fname in EXPECTED:
        path = f'/app/hexanalysis/{fname}.hexdump'
        assert os.path.exists(path), f"Missing hex dump: {fname}.hexdump"


def test_hexanalysis_has_type1_annotation(run_toolkit):
    """Every hex dump must annotate the Type-1 record at offset 0."""
    for fname in EXPECTED:
        with open(f'/app/hexanalysis/{fname}.hexdump') as f:
            content = f.read()
        assert re.search(
            r'^# --- Record Type 1 at offset 00000000 \(0 bytes\) ---$',
            content, re.MULTILINE
        ), f"Missing Type-1 annotation in {fname}.hexdump"


def test_hexanalysis_has_type4_annotation(run_toolkit):
    """Hex dumps with Type-4 records must have Type-4 annotations."""
    t4_files = [f for f in EXPECTED if 't4' in f or f == 'valid_with_t4.an2k'
                or f == 'corrupt_resolution.an2k']
    for fname in t4_files:
        with open(f'/app/hexanalysis/{fname}.hexdump') as f:
            content = f.read()
        assert re.search(
            r'^# --- Record Type 4 at offset [0-9a-f]{8} \(\d+ bytes\) ---$',
            content, re.MULTILINE
        ), f"Missing Type-4 annotation in {fname}.hexdump"


def test_hexanalysis_matches_xxd(run_toolkit):
    """Non-annotation lines must exactly match xxd output."""
    for fname in EXPECTED:
        dump_path = f'/app/hexanalysis/{fname}.hexdump'
        corpus_path = f'/app/corpus/{fname}'

        with open(dump_path) as f:
            dump_lines = [l.rstrip('\n') for l in f
                          if l.strip() and not l.startswith('#')]

        result = subprocess.run(
            ['xxd', corpus_path], capture_output=True, text=True
        )
        xxd_lines = [l for l in result.stdout.rstrip('\n').split('\n')
                     if l.strip()]

        assert dump_lines == xxd_lines, (
            f"Hex dump for {fname} doesn't match xxd output "
            f"(dump has {len(dump_lines)} data lines, "
            f"xxd has {len(xxd_lines)} lines)"
        )


# ========================================================
# SECTION 4: Checksum tests
# ========================================================

def test_checksums_file_exists(run_toolkit):
    assert os.path.exists('/app/checksums.txt'), "checksums.txt not created"


def test_checksums_format(run_toolkit):
    """Each line must be '{64-hex-chars}  {filename}'."""
    with open('/app/checksums.txt') as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) > 0, "checksums.txt is empty"
    for line in lines:
        assert re.match(r'^[0-9a-f]{64}  .+\.an2k$', line), (
            f"Bad checksum line format: {line}"
        )


def test_checksums_cover_all_files(run_toolkit):
    """checksums.txt must have an entry for every corpus file."""
    with open('/app/checksums.txt') as f:
        fnames = {l.strip().split()[1] for l in f if l.strip()}
    for fname in EXPECTED:
        assert fname in fnames, f"Missing checksum for {fname}"


def test_checksums_match_independent(run_toolkit):
    """Hash values must match independent sha256sum computation."""
    with open('/app/checksums.txt') as f:
        recorded = {}
        for l in f:
            l = l.strip()
            if l:
                parts = l.split()
                recorded[parts[1]] = parts[0]

    for fname in EXPECTED:
        path = f'/app/reconstructed/{fname}'
        result = subprocess.run(
            ['sha256sum', path], capture_output=True, text=True
        )
        actual_hash = result.stdout.split()[0]
        assert fname in recorded, f"Missing checksum entry for {fname}"
        assert recorded[fname] == actual_hash, (
            f"Hash mismatch for {fname}: "
            f"recorded={recorded[fname]}, actual={actual_hash}"
        )


# ========================================================
# SECTION 5: HMAC integrity signature tests
# ========================================================

def test_integrity_sig_exists(run_toolkit):
    assert os.path.exists('/app/integrity.sig'), "integrity.sig not created"


def test_integrity_sig_format(run_toolkit):
    """Each line must be '{64-hex-chars}  {filename}'."""
    with open('/app/integrity.sig') as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) > 0, "integrity.sig is empty"
    for line in lines:
        assert re.match(r'^[0-9a-f]{64}  .+\.an2k$', line), (
            f"Bad integrity.sig line format: {line}"
        )


def test_integrity_sig_covers_all_files(run_toolkit):
    """integrity.sig must have an entry for every corpus file."""
    with open('/app/integrity.sig') as f:
        fnames = {l.strip().split()[1] for l in f if l.strip()}
    for fname in EXPECTED:
        assert fname in fnames, f"Missing HMAC for {fname}"


def test_integrity_sig_sorted(run_toolkit):
    """Lines in integrity.sig must be sorted by filename."""
    with open('/app/integrity.sig') as f:
        fnames = [l.strip().split()[1] for l in f if l.strip()]
    assert fnames == sorted(fnames), "integrity.sig not sorted by filename"


def test_integrity_sig_matches_openssl(run_toolkit):
    """HMAC values must match independent openssl dgst computation."""
    with open('/app/hmac.key') as f:
        key = f.read().strip()

    with open('/app/integrity.sig') as f:
        recorded = {}
        for l in f:
            l = l.strip()
            if l:
                parts = l.split()
                recorded[parts[1]] = parts[0]

    for fname in EXPECTED:
        path = f'/app/reconstructed/{fname}'
        result = subprocess.run(
            ['openssl', 'dgst', '-sha256', '-hmac', key, path],
            capture_output=True, text=True
        )
        m = re.search(r'=\s*([0-9a-f]+)', result.stdout)
        assert m, f"openssl dgst failed for {fname}: {result.stderr}"
        actual_hmac = m.group(1)
        assert fname in recorded, f"Missing HMAC entry for {fname}"
        assert recorded[fname] == actual_hmac, (
            f"HMAC mismatch for {fname}: "
            f"recorded={recorded[fname]}, actual={actual_hmac}"
        )


def test_integrity_sig_differs_from_checksums(run_toolkit):
    """HMAC-SHA256 and SHA-256 must produce different values (keyed vs unkeyed)."""
    with open('/app/integrity.sig') as f:
        hmac_map = {}
        for l in f:
            l = l.strip()
            if l:
                parts = l.split()
                hmac_map[parts[1]] = parts[0]

    with open('/app/checksums.txt') as f:
        sha_map = {}
        for l in f:
            l = l.strip()
            if l:
                parts = l.split()
                sha_map[parts[1]] = parts[0]

    # At least one file must have different HMAC vs SHA-256 (all should differ)
    diff_count = sum(1 for fn in EXPECTED
                     if fn in hmac_map and fn in sha_map
                     and hmac_map[fn] != sha_map[fn])
    assert diff_count == len(EXPECTED), (
        f"Expected all {len(EXPECTED)} files to have different HMAC vs SHA-256, "
        f"but only {diff_count} differ"
    )


# ========================================================
# SECTION 6: Dynamic validation tests (anti-hardcoding)
# ========================================================

def test_dynamic_missing_dat(analyze_fn):
    """Type-1 missing DAT field."""
    fields = _make_t1_fields([(0, 2)], overrides={5: None})
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    path = _write_temp('missing_dat', t1 + t2)
    violations = analyze_fn(path)
    assert 'T1_MISSING_DAT' in violations


def test_dynamic_missing_nsr(analyze_fn):
    """Type-1 missing NSR field."""
    fields = _make_t1_fields([(0, 2)], overrides={11: None})
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    path = _write_temp('missing_nsr', t1 + t2)
    violations = analyze_fn(path)
    assert 'T1_MISSING_NSR' in violations


def test_dynamic_missing_ntr(analyze_fn):
    """Type-1 missing NTR field."""
    fields = _make_t1_fields([(0, 2)], overrides={12: None})
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    path = _write_temp('missing_ntr', t1 + t2)
    violations = analyze_fn(path)
    assert 'T1_MISSING_NTR' in violations


def test_dynamic_t2_bad_len(analyze_fn):
    """Type-2 with wrong LEN."""
    fields = _make_t1_fields([(0, 2)])
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'}, override_len=999)
    path = _write_temp('t2_bad_len', t1 + t2)
    violations = analyze_fn(path)
    assert 'T2_LEN_MISMATCH' in violations


def test_dynamic_t4_bad_isr(analyze_fn):
    """Type-4 with invalid ISR value (not 0 or 1)."""
    fields = _make_t1_fields([(0, 2), (1, 4)])
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    t4 = _build_type4_record(idc=1, isr=2)
    path = _write_temp('t4_bad_isr', t1 + t2 + t4)
    violations = analyze_fn(path)
    assert 'T4_ISR_VALUE' in violations


def test_dynamic_t4_no_image(analyze_fn):
    """Type-4 with no image data (record exactly 21 bytes)."""
    fields = _make_t1_fields([(0, 2), (1, 4)])
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    t4 = _build_type4_record(idc=1, image_size=0)
    path = _write_temp('t4_no_image', t1 + t2 + t4)
    violations = analyze_fn(path)
    assert 'T4_NO_IMAGE_DATA' in violations


def test_dynamic_valid_with_t4(analyze_fn):
    """Dynamically built valid transaction with Type-4 -- zero violations."""
    fields = _make_t1_fields([(0, 2), (1, 4)])
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    t4 = _build_type4_record(idc=1)
    path = _write_temp('valid_t4', t1 + t2 + t4)
    violations = analyze_fn(path)
    assert violations == []


def test_dynamic_valid_basic(analyze_fn):
    """Dynamically built valid basic transaction -- zero violations."""
    fields = _make_t1_fields([(0, 2)])
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    path = _write_temp('valid_basic', t1 + t2)
    violations = analyze_fn(path)
    assert violations == []


def test_dynamic_combined_t1_t4_violations(analyze_fn):
    """Transaction with both Type-1 and Type-4 violations."""
    fields = _make_t1_fields([(0, 2), (1, 4)], overrides={
        2: 'XX',
        5: 'bad',
    })
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    t4 = _build_type4_record(idc=1, imp=16, gca=3)
    path = _write_temp('combined', t1 + t2 + t4)
    violations = analyze_fn(path)
    assert 'T1_VER_FORMAT' in violations
    assert 'T1_DAT_FORMAT' in violations
    assert 'T4_IMP_RANGE' in violations
    assert 'T4_GCA_VALUE' in violations


# ========================================================
# SECTION 7: Dynamic reconstruction tests (anti-hardcoding)
# ========================================================

def test_dynamic_reconstruct_basic(analyze_fn, reconstruct_fn):
    """Dynamically built corrupted file: reconstruct then validate."""
    fields = _make_t1_fields([(0, 2)], overrides={
        2: 'XX',
        5: 'bad',
    })
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    src = _write_temp('dyn_recon', t1 + t2)
    dst = '/tmp/dyn_recon_repaired.an2k'
    reconstruct_fn(src, dst)
    violations = analyze_fn(dst)
    assert violations == [], f"Reconstructed has violations: {violations}"


def test_dynamic_reconstruct_t4(analyze_fn, reconstruct_fn):
    """Dynamically built T4 with violations: reconstruct then validate."""
    fields = _make_t1_fields([(0, 2), (1, 4)])
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    t4 = _build_type4_record(idc=1, imp=20, hll=0, vll=0, gca=5)
    src = _write_temp('dyn_recon_t4', t1 + t2 + t4)
    dst = '/tmp/dyn_recon_t4_repaired.an2k'
    reconstruct_fn(src, dst)
    violations = analyze_fn(dst)
    assert violations == [], f"Reconstructed has violations: {violations}"


def test_dynamic_reconstruct_cross_record(analyze_fn, reconstruct_fn):
    """Dynamically built cross-record violation: reconstruct resolves it."""
    fields = _make_t1_fields([(0, 2), (1, 4)], overrides={11: '10.00'})
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    t4 = _build_type4_record(idc=1, isr=1)
    src = _write_temp('dyn_recon_cross', t1 + t2 + t4)

    # Confirm violation exists before reconstruction
    v_before = analyze_fn(src)
    assert 'T4_RESOLUTION_LOW' in v_before

    dst = '/tmp/dyn_recon_cross_repaired.an2k'
    reconstruct_fn(src, dst)
    v_after = analyze_fn(dst)
    assert v_after == [], f"Reconstructed has violations: {v_after}"

    # Verify NSR was updated in the reconstructed file
    with open(dst, 'rb') as f:
        data = f.read()
    assert b'1.011:19.69' in data


def test_dynamic_reconstruct_valid_identity(analyze_fn, reconstruct_fn):
    """Dynamically built valid file: reconstruction is byte-identical."""
    fields = _make_t1_fields([(0, 2)])
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    src = _write_temp('dyn_identity', t1 + t2)
    dst = '/tmp/dyn_identity_repaired.an2k'
    reconstruct_fn(src, dst)

    with open(src, 'rb') as f:
        orig = f.read()
    with open(dst, 'rb') as f:
        recon = f.read()
    assert orig == recon, (
        f"Valid file not byte-identical after reconstruction "
        f"(orig={len(orig)}, recon={len(recon)})"
    )


def test_dynamic_reconstruct_missing_fields(analyze_fn, reconstruct_fn):
    """Dynamically built file missing mandatory fields: reconstruction inserts defaults."""
    fields = _make_t1_fields([(0, 2)], overrides={
        4: None, 7: None, 9: None,
    })
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    src = _write_temp('dyn_missing', t1 + t2)
    dst = '/tmp/dyn_missing_repaired.an2k'
    reconstruct_fn(src, dst)
    violations = analyze_fn(dst)
    assert violations == [], f"Reconstructed has violations: {violations}"

    with open(dst, 'rb') as f:
        data = f.read()
    assert b'1.004:UNK' in data
    assert b'1.007:UNKNOWN' in data
    assert b'1.009:REPAIR000' in data


def test_dynamic_reconstruct_no_image(analyze_fn, reconstruct_fn):
    """Dynamically built T4 with no image data: reconstruction adds a byte."""
    fields = _make_t1_fields([(0, 2), (1, 4)])
    t1 = _build_tagged_record(1, fields)
    t2 = _build_tagged_record(2, {2: '0'})
    t4 = _build_type4_record(idc=1, image_size=0)
    src = _write_temp('dyn_no_img', t1 + t2 + t4)
    dst = '/tmp/dyn_no_img_repaired.an2k'
    reconstruct_fn(src, dst)
    violations = analyze_fn(dst)
    assert violations == [], f"Reconstructed has violations: {violations}"

    # Reconstructed Type-4 record must be > 21 bytes
    with open(dst, 'rb') as f:
        data = f.read()
    first_fs = data.index(FS)
    second_fs = data.index(FS, first_fs + 1)
    t4_start = second_fs + 1
    t4_len = struct.unpack('>I', data[t4_start:t4_start + 4])[0]
    assert t4_len > 21, f"Reconstructed T4 length {t4_len} should be > 21"
