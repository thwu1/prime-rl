
"""
Verification tests for PE memory dump forensic reconstruction.

Tests derive expected values from the dump binary and case metadata
rather than hardcoding answers, to prevent trivial solution extraction.
"""

import json
import struct
import sqlite3
import os
import subprocess
import re
import hashlib
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_int(val):
    """Normalise a value (int or hex-string) to Python int."""
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        val = val.strip()
        if val.startswith(('0x', '0X')):
            return int(val, 16)
        return int(val)
    raise ValueError(f"Cannot convert {val!r} to int")


def parse_reloc_table(dump_data, dd_off):
    """Parse the base relocation table from the raw dump bytes."""
    reloc_rva  = struct.unpack_from('<I', dump_data, dd_off + 5 * 8)[0]
    reloc_size = struct.unpack_from('<I', dump_data, dd_off + 5 * 8 + 4)[0]

    entries = []  # (rva, relocated_value)
    pos = reloc_rva
    end = reloc_rva + reloc_size

    while pos < end:
        block_va   = struct.unpack_from('<I', dump_data, pos)[0]
        block_size = struct.unpack_from('<I', dump_data, pos + 4)[0]
        if block_size == 0:
            break

        n = (block_size - 8) // 2
        for j in range(n):
            raw = struct.unpack_from('<H', dump_data, pos + 8 + j * 2)[0]
            rtype  = (raw >> 12) & 0xF
            offset = raw & 0xFFF
            if rtype == 0:          # ABSOLUTE (padding)
                continue
            rva = block_va + offset
            if rtype == 10:         # DIR64
                val = struct.unpack_from('<Q', dump_data, rva)[0]
            elif rtype == 3:        # HIGHLOW
                val = struct.unpack_from('<I', dump_data, rva)[0]
            else:
                continue
            entries.append((rva, val, rtype))
        pos += block_size

    return entries


def count_iat_entries(dump_data, dd_off):
    """Count non-null IAT entries by walking the import directory in the dump."""
    import_rva = struct.unpack_from('<I', dump_data, dd_off + 1 * 8)[0]
    total = 0
    pos = import_rva
    while True:
        name_rva = struct.unpack_from('<I', dump_data, pos + 12)[0]
        ft_rva   = struct.unpack_from('<I', dump_data, pos + 16)[0]
        if name_rva == 0 and ft_rva == 0:
            break
        iat_pos = ft_rva
        while struct.unpack_from('<Q', dump_data, iat_pos)[0] != 0:
            total += 1
            iat_pos += 8
        pos += 20
    return total


def get_oh_and_dd(data):
    """Return (optional-header offset, data-directory offset) from raw PE."""
    e_lfanew = struct.unpack_from('<I', data, 0x3C)[0]
    oh_off = e_lfanew + 4 + 20        # after PE sig (4) + file header (20)
    dd_off = oh_off + 112             # data directories start at oh+0x70
    return oh_off, dd_off


def find_xor_key_from_dump(dump_data):
    """Find XOR key by scanning .text for MOV CL,imm8 followed by LEA RSI,[rip+disp32]."""
    for i in range(0x1000, 0x11C0 - 5):
        if dump_data[i] == 0xB1 and dump_data[i + 2:i + 5] == b'\x48\x8D\x35':
            return dump_data[i + 1]
    return None


def find_and_decrypt_config(dump_data, xor_key):
    """Find the CAFEBABE marker and decrypt the config block."""
    marker = b'\xCA\xFE\xBA\xBE'
    raw = bytes(dump_data) if not isinstance(dump_data, bytes) else dump_data
    idx = raw.find(marker)
    if idx < 0:
        return None
    length = struct.unpack_from('<I', dump_data, idx + 4)[0]
    encrypted = dump_data[idx + 8: idx + 8 + length]
    decrypted = bytes(b ^ xor_key for b in encrypted)
    return json.loads(decrypted)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def dump_data():
    with open('/app/dump.bin', 'rb') as f:
        return f.read()


@pytest.fixture(scope='module')
def case_info():
    with open('/app/case_info.json') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def exports_db():
    conn = sqlite3.connect('/app/exports.db')
    cur_dlls = conn.cursor()
    cur_exports = conn.cursor()
    db = {}
    for dll_name, base in cur_dlls.execute('SELECT name, base_address FROM dlls'):
        exports = {}
        for fn, rva in cur_exports.execute(
            'SELECT function_name, rva FROM exports WHERE dll_name = ?',
            (dll_name,)
        ):
            exports[fn] = rva
        db[dll_name] = {'base': base, 'exports': exports}
    conn.close()
    return db


@pytest.fixture(scope='module')
def header_info():
    with open('/app/analysis/header_info.json') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def relocations():
    with open('/app/analysis/relocations.json') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def imports_info():
    with open('/app/analysis/imports_reconstructed.json') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def restored_data():
    with open('/app/analysis/restored.bin', 'rb') as f:
        return f.read()


@pytest.fixture(scope='module')
def code_analysis():
    with open('/app/analysis/code_analysis.json') as f:
        return json.load(f)


@pytest.fixture(scope='module')
def config_decoded():
    with open('/app/analysis/config_decoded.json') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Test: output files exist
# ---------------------------------------------------------------------------

class TestOutputExists:
    def test_analysis_dir(self):
        assert os.path.isdir('/app/analysis')

    def test_header_info(self):
        assert os.path.isfile('/app/analysis/header_info.json')

    def test_relocations(self):
        assert os.path.isfile('/app/analysis/relocations.json')

    def test_imports(self):
        assert os.path.isfile('/app/analysis/imports_reconstructed.json')

    def test_restored(self):
        assert os.path.isfile('/app/analysis/restored.bin')

    def test_code_analysis(self):
        assert os.path.isfile('/app/analysis/code_analysis.json')

    def test_detection_yar(self):
        assert os.path.isfile('/app/analysis/detection.yar')

    def test_config_decoded(self):
        assert os.path.isfile('/app/analysis/config_decoded.json')


# ---------------------------------------------------------------------------
# Test: header_info.json
# ---------------------------------------------------------------------------

class TestHeaderInfo:
    def test_machine_amd64(self, header_info):
        m = header_info.get('machine', '')
        assert m.upper() in ('AMD64', 'X86_64', 'X64', '0X8664', 'IMAGE_FILE_MACHINE_AMD64'), \
            f"Expected AMD64 machine, got {m}"

    def test_section_count(self, header_info):
        assert header_info.get('number_of_sections') == 4

    def test_entry_point(self, header_info):
        ep = to_int(header_info.get('entry_point_rva', 0))
        assert ep == 0x1000, f"Expected EP 0x1000, got {hex(ep)}"

    def test_original_imagebase(self, header_info, case_info):
        expected = to_int(case_info['original_imagebase'])
        for key in ('original_image_base', 'original_imagebase'):
            if key in header_info:
                assert to_int(header_info[key]) == expected
                return
        pytest.fail("original_image_base / original_imagebase not found in header_info")

    def test_size_of_image(self, header_info):
        soi = to_int(header_info.get('size_of_image', 0))
        assert soi == 0x5000

    def test_sections_listed(self, header_info):
        names = {s.get('name', '') for s in header_info.get('sections', [])}
        for exp in ('.text', '.rdata', '.data', '.reloc'):
            assert exp in names, f"Section {exp} missing"


# ---------------------------------------------------------------------------
# Test: relocations.json
# ---------------------------------------------------------------------------

class TestRelocations:
    def test_delta(self, relocations, case_info):
        expected_delta = to_int(case_info['load_address']) - to_int(case_info['original_imagebase'])
        reported = to_int(relocations.get('delta', 0))
        assert reported == expected_delta

    def test_total_entries(self, relocations, dump_data):
        oh, dd = get_oh_and_dd(dump_data)
        expected = len(parse_reloc_table(dump_data, dd))
        reported = relocations.get('total_entries', 0)
        assert reported == expected, f"Expected {expected} entries, got {reported}"

    def test_all_entries_present(self, relocations, dump_data, case_info):
        """Every relocation RVA from the dump must appear in the output."""
        oh, dd = get_oh_and_dd(dump_data)
        expected_relocs = parse_reloc_table(dump_data, dd)
        delta = to_int(case_info['load_address']) - to_int(case_info['original_imagebase'])

        # Collect reported entries
        reported = {}
        for block in relocations.get('blocks', []):
            for entry in block.get('entries', []):
                rva = to_int(entry.get('rva', 0))
                orig = to_int(entry.get('original_value', 0))
                reported[rva] = orig

        for rva, relocated_val, _ in expected_relocs:
            assert rva in reported, f"Relocation at RVA {hex(rva)} not found"
            expected_orig = relocated_val - delta
            assert reported[rva] == expected_orig, \
                f"RVA {hex(rva)}: expected orig {hex(expected_orig)}, got {hex(reported[rva])}"


# ---------------------------------------------------------------------------
# Test: imports_reconstructed.json
# ---------------------------------------------------------------------------

class TestImports:
    def test_dll_count(self, imports_info, dump_data):
        oh, dd = get_oh_and_dd(dump_data)
        import_rva = struct.unpack_from('<I', dump_data, dd + 1 * 8)[0]
        expected = 0
        pos = import_rva
        while True:
            nr = struct.unpack_from('<I', dump_data, pos + 12)[0]
            ft = struct.unpack_from('<I', dump_data, pos + 16)[0]
            if nr == 0 and ft == 0:
                break
            expected += 1
            pos += 20
        reported = len(imports_info.get('imports', []))
        assert reported == expected, f"Expected {expected} DLLs, got {reported}"

    def test_total_function_count(self, imports_info, dump_data):
        oh, dd = get_oh_and_dd(dump_data)
        expected = count_iat_entries(dump_data, dd)
        reported = sum(len(i.get('functions', [])) for i in imports_info.get('imports', []))
        assert reported == expected, f"Expected {expected} functions, got {reported}"

    def test_no_unknown_functions(self, imports_info):
        for imp in imports_info.get('imports', []):
            for fn in imp.get('functions', []):
                name = fn.get('name', '')
                assert name and name.upper() not in ('UNKNOWN', ''), \
                    f"Unresolved function in {imp.get('dll_name', '?')}: {fn}"

    def test_resolved_addresses_match_exports(self, imports_info, exports_db):
        for imp in imports_info.get('imports', []):
            dll = imp.get('dll_name', '')
            if dll not in exports_db:
                continue
            db = exports_db[dll]
            dll_base = to_int(db['base'])
            for fn in imp.get('functions', []):
                name = fn.get('name', '')
                addr = to_int(fn.get('resolved_address', 0))
                assert name in db['exports'], \
                    f"{dll}!{name} not in exports DB"
                exp_rva = to_int(db['exports'][name])
                assert addr == dll_base + exp_rva, \
                    f"{dll}!{name}: addr {hex(addr)} != base+rva {hex(dll_base + exp_rva)}"


# ---------------------------------------------------------------------------
# Test: restored.bin
# ---------------------------------------------------------------------------

class TestRestoredBinary:
    def test_file_size(self, restored_data, dump_data):
        assert len(restored_data) == len(dump_data), \
            f"Size mismatch: {len(restored_data)} vs {len(dump_data)}"

    def test_mz_signature(self, restored_data):
        assert restored_data[:2] == b'MZ'

    def test_pe_signature(self, restored_data):
        elf = struct.unpack_from('<I', restored_data, 0x3C)[0]
        assert struct.unpack_from('<I', restored_data, elf)[0] == 0x4550

    def test_imagebase_restored(self, restored_data, case_info):
        oh, _ = get_oh_and_dd(restored_data)
        magic = struct.unpack_from('<H', restored_data, oh)[0]
        if magic == 0x020B:
            ib = struct.unpack_from('<Q', restored_data, oh + 24)[0]
        else:
            ib = struct.unpack_from('<I', restored_data, oh + 28)[0]
        expected = to_int(case_info['original_imagebase'])
        assert ib == expected, \
            f"ImageBase not restored: {hex(ib)} != {hex(expected)}"

    def test_relocations_reversed(self, restored_data, dump_data, case_info):
        """Every relocated value in the restored binary must equal the
        original pre-relocation value derived from the dump."""
        oh, dd = get_oh_and_dd(dump_data)
        delta = to_int(case_info['load_address']) - to_int(case_info['original_imagebase'])
        relocs = parse_reloc_table(dump_data, dd)

        checked = 0
        for rva, relocated_val, rtype in relocs:
            expected_orig = relocated_val - delta
            if rtype == 10:
                actual = struct.unpack_from('<Q', restored_data, rva)[0]
            elif rtype == 3:
                actual = struct.unpack_from('<I', restored_data, rva)[0]
            else:
                continue
            assert actual == expected_orig, \
                f"RVA {hex(rva)}: restored {hex(actual)} != expected {hex(expected_orig)}"
            checked += 1

        assert checked >= 10, f"Only {checked} relocations verified, expected >=10"

    def test_non_relocated_bytes_unchanged(self, restored_data, dump_data):
        """Bytes that are NOT at relocation targets must be identical to the dump
        (except the ImageBase field)."""
        oh_r, dd_r = get_oh_and_dd(restored_data)
        oh_d, dd_d = get_oh_and_dd(dump_data)
        relocs = parse_reloc_table(dump_data, dd_d)

        # Build set of modified byte ranges
        skip = set()
        # ImageBase field (8 bytes at oh+24)
        for i in range(oh_d + 24, oh_d + 32):
            skip.add(i)
        # Relocation targets (8 bytes each for DIR64)
        for rva, _, rtype in relocs:
            sz = 8 if rtype == 10 else 4
            for i in range(rva, rva + sz):
                skip.add(i)

        mismatches = 0
        for i in range(min(len(dump_data), len(restored_data))):
            if i in skip:
                continue
            if dump_data[i] != restored_data[i]:
                mismatches += 1
        assert mismatches == 0, f"{mismatches} non-relocation bytes differ between dump and restored"


# ---------------------------------------------------------------------------
# Test: code_analysis.json
# ---------------------------------------------------------------------------

class TestCodeAnalysis:
    def test_xor_key_correct(self, code_analysis, dump_data):
        """XOR key must match the immediate operand in the MOV CL instruction."""
        expected_key = find_xor_key_from_dump(dump_data)
        assert expected_key is not None, "Could not find XOR key pattern in dump"
        reported = to_int(code_analysis.get('xor_key', '0'))
        assert reported == expected_key, \
            f"XOR key {hex(reported)} != expected {hex(expected_key)}"

    def test_function_entry_points(self, code_analysis):
        """Must identify at least the main function and decrypt routine."""
        functions = code_analysis.get('functions', [])
        entries = set()
        for f in functions:
            ep = f.get('entry_point', '0')
            entries.add(to_int(ep))
        assert 0x1000 in entries, "Function at 0x1000 not identified"
        assert 0x1100 in entries, "Decrypt routine at 0x1100 not identified"

    def test_decrypt_routine_address(self, code_analysis):
        addr = to_int(code_analysis.get('decrypt_routine_address', '0'))
        assert addr == 0x1100


# ---------------------------------------------------------------------------
# Test: detection.yar (YARA rule)
# ---------------------------------------------------------------------------

class TestYaraRule:
    def test_yar_file_exists(self):
        assert os.path.isfile('/app/analysis/detection.yar')

    def test_yara_matches_dump(self):
        """Run yara against the dump and verify it produces a match."""
        result = subprocess.run(
            ['yara', '/app/analysis/detection.yar', '/app/dump.bin'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"YARA error: {result.stderr}"
        assert result.stdout.strip(), \
            f"YARA rule did not match dump.bin (stderr: {result.stderr.strip()})"

    def test_yara_no_false_positive(self):
        """Rule must not match arbitrary non-PE data."""
        data = hashlib.sha512(b'not_a_pe_binary').digest() * 128
        test_file = '/tmp/test_nonpe.bin'
        with open(test_file, 'wb') as f:
            f.write(data)
        result = subprocess.run(
            ['yara', '/app/analysis/detection.yar', test_file],
            capture_output=True, text=True, timeout=30
        )
        assert not result.stdout.strip(), "YARA rule matched non-PE data (too broad)"

    def test_rule_has_strings(self):
        """Verify the rule has substantive string definitions."""
        with open('/app/analysis/detection.yar') as f:
            content = f.read()
        strings = re.findall(r'\$\w+\s*=', content)
        assert len(strings) >= 2, \
            f"Rule has only {len(strings)} string definitions, expected >=2"


# ---------------------------------------------------------------------------
# Test: config_decoded.json
# ---------------------------------------------------------------------------

class TestConfigDecoded:
    def test_config_has_required_keys(self, config_decoded):
        for key in ('c2', 'port', 'interval', 'mutex'):
            assert key in config_decoded, f"Key '{key}' missing from decoded config"

    def test_config_values_match(self, config_decoded, dump_data):
        """Independently decrypt the config from the dump and compare."""
        xor_key = find_xor_key_from_dump(dump_data)
        assert xor_key is not None, "Could not find XOR key in dump"

        expected = find_and_decrypt_config(dump_data, xor_key)
        assert expected is not None, "Could not decrypt config from dump"

        for key in expected:
            assert config_decoded.get(key) == expected[key], \
                f"Config key '{key}': got {config_decoded.get(key)!r}, expected {expected[key]!r}"

    def test_c2_is_ip(self, config_decoded):
        """C2 field should be an IP address."""
        c2 = config_decoded.get('c2', '')
        parts = c2.split('.')
        assert len(parts) == 4, f"C2 '{c2}' does not look like an IP address"

    def test_port_is_integer(self, config_decoded):
        assert isinstance(config_decoded.get('port'), int), \
            f"Port should be integer, got {type(config_decoded.get('port'))}"
