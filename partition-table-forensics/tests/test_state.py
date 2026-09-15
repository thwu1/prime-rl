
import subprocess
import json
import os
import struct
import hashlib
import pytest

TOOL = '/app/flash_forensics.py'
DUMPS = '/app/dumps'
GEN_TOOL = '/app/tools/gen_esp32part.py'
WORK = '/tmp/test_work'

PT_MAGIC = b'\xaa\x50'
PT_STRUCT = '<2sBBLL16sL'
MD5_MARKER_PREFIX = b'\xeb\xeb' + b'\xff' * 14


def run_tool(*args):
    result = subprocess.run(
        ['python3', TOOL] + list(args),
        capture_output=True, text=True, timeout=120
    )
    return result


def validate_binary(binary_path):
    """Validate using gen_esp32part.py (the authoritative oracle)."""
    result = subprocess.run(
        ['python3', GEN_TOOL, '--quiet', binary_path],
        capture_output=True, text=True, timeout=30
    )
    return result.returncode == 0


def gen_esp32part_csv(binary_path):
    result = subprocess.run(
        ['python3', GEN_TOOL, '--quiet', binary_path],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return None
    return result.stdout


def parse_pt_directly(filepath):
    """Parse a partition table binary independently of the tool under test."""
    with open(filepath, 'rb') as f:
        data = f.read()
    entries = []
    raw_entry_data = b''
    md5_info = {'present': False, 'valid': None}
    for offset in range(0, min(len(data), 0xC00), 32):
        chunk = data[offset:offset + 32]
        if len(chunk) != 32:
            break
        if chunk == b'\xff' * 32:
            break
        if chunk[:2] == b'\xeb\xeb':
            md5_info['present'] = True
            expected = hashlib.md5(raw_entry_data).digest()
            md5_info['valid'] = (expected == chunk[16:])
            break
        if chunk[:2] != PT_MAGIC:
            continue
        magic, ptype, subtype, pt_offset, size, name_bytes, flags = \
            struct.unpack(PT_STRUCT, chunk)
        name = name_bytes.split(b'\x00')[0].decode('ascii', errors='replace')
        entries.append({
            'name': name, 'type': ptype, 'subtype': subtype,
            'offset': pt_offset, 'size': size, 'flags': flags,
        })
        raw_entry_data += chunk
    return entries, md5_info


@pytest.fixture(autouse=True)
def setup_work_dir():
    os.makedirs(WORK, exist_ok=True)
    yield


# ==================== SCAN TESTS — flash_simple.bin ====================

class TestScanSimple:
    """Verify scan correctly identifies regions in the simple factory-only dump."""

    def test_scan_returns_valid_json(self):
        result = run_tool('scan', f'{DUMPS}/flash_simple.bin')
        assert result.returncode == 0, f"scan failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert 'regions' in output
        assert isinstance(output['regions'], list)

    def test_scan_reports_flash_size(self):
        result = run_tool('scan', f'{DUMPS}/flash_simple.bin')
        output = json.loads(result.stdout)
        assert output['flash_size'] == 0x40000

    def test_scan_detects_nvs_at_correct_offset(self):
        result = run_tool('scan', f'{DUMPS}/flash_simple.bin')
        output = json.loads(result.stdout)
        nvs = [r for r in output['regions'] if r['content_type'] == 'nvs']
        assert len(nvs) >= 1, f"No NVS region detected. Regions: {output['regions']}"
        assert any(r['offset'] == 0x9000 for r in nvs)

    def test_scan_nvs_correct_size(self):
        result = run_tool('scan', f'{DUMPS}/flash_simple.bin')
        output = json.loads(result.stdout)
        nvs = [r for r in output['regions']
               if r['content_type'] == 'nvs' and r['offset'] == 0x9000]
        assert nvs[0]['size'] == 0x6000, \
            f"NVS size 0x{nvs[0]['size']:x}, expected 0x6000"

    def test_scan_detects_phy(self):
        result = run_tool('scan', f'{DUMPS}/flash_simple.bin')
        output = json.loads(result.stdout)
        phy = [r for r in output['regions'] if r['content_type'] == 'phy']
        assert len(phy) >= 1
        assert any(r['offset'] == 0xF000 for r in phy)

    def test_scan_detects_factory_app(self):
        result = run_tool('scan', f'{DUMPS}/flash_simple.bin')
        output = json.loads(result.stdout)
        apps = [r for r in output['regions']
                if r['content_type'] == 'app' and r['offset'] == 0x10000]
        assert len(apps) == 1, f"No factory app at 0x10000. Regions: {output['regions']}"

    def test_scan_factory_app_size(self):
        result = run_tool('scan', f'{DUMPS}/flash_simple.bin')
        output = json.loads(result.stdout)
        apps = [r for r in output['regions']
                if r['content_type'] == 'app' and r['offset'] == 0x10000]
        assert apps[0]['size'] == 0x30000, \
            f"Factory size 0x{apps[0]['size']:x}, expected 0x30000"

    def test_scan_no_ota_data_in_simple(self):
        result = run_tool('scan', f'{DUMPS}/flash_simple.bin')
        output = json.loads(result.stdout)
        ota = [r for r in output['regions'] if r['content_type'] == 'ota_data']
        assert len(ota) == 0, "Simple dump should have no OTA data"


# ==================== SCAN TESTS — flash_ota.bin ====================

class TestScanOta:
    """Verify scan correctly identifies regions in the OTA-capable dump."""

    def test_scan_detects_ota_data(self):
        result = run_tool('scan', f'{DUMPS}/flash_ota.bin')
        output = json.loads(result.stdout)
        ota = [r for r in output['regions'] if r['content_type'] == 'ota_data']
        assert len(ota) >= 1
        assert any(r['offset'] == 0xD000 for r in ota)

    def test_scan_ota_data_size(self):
        result = run_tool('scan', f'{DUMPS}/flash_ota.bin')
        output = json.loads(result.stdout)
        ota = [r for r in output['regions']
               if r['content_type'] == 'ota_data' and r['offset'] == 0xD000]
        assert ota[0]['size'] == 0x2000

    def test_scan_detects_three_app_regions(self):
        """OTA dump has factory + ota_0 + ota_1 (plus bootloader at 0x1000)."""
        result = run_tool('scan', f'{DUMPS}/flash_ota.bin')
        output = json.loads(result.stdout)
        apps = [r for r in output['regions']
                if r['content_type'] == 'app' and r['offset'] >= 0x10000]
        assert len(apps) >= 3, \
            f"Expected 3 app regions after 0x10000, got {len(apps)}: {apps}"

    def test_scan_app_offsets_are_64kb_aligned(self):
        result = run_tool('scan', f'{DUMPS}/flash_ota.bin')
        output = json.loads(result.stdout)
        apps = [r for r in output['regions']
                if r['content_type'] == 'app' and r['offset'] >= 0x10000]
        for app in apps:
            assert app['offset'] % 0x10000 == 0, \
                f"App at 0x{app['offset']:x} not 64KB-aligned"

    def test_scan_nvs_four_pages(self):
        result = run_tool('scan', f'{DUMPS}/flash_ota.bin')
        output = json.loads(result.stdout)
        nvs = [r for r in output['regions']
               if r['content_type'] == 'nvs' and r['offset'] == 0x9000]
        assert len(nvs) >= 1
        assert nvs[0]['size'] == 0x4000

    def test_scan_flash_size(self):
        result = run_tool('scan', f'{DUMPS}/flash_ota.bin')
        output = json.loads(result.stdout)
        assert output['flash_size'] == 0x100000


# ==================== SCAN TESTS — flash_complex.bin ====================

class TestScanComplex:
    """Verify scan on the dump with a partially-intact partition table."""

    def test_scan_detects_phy(self):
        result = run_tool('scan', f'{DUMPS}/flash_complex.bin')
        output = json.loads(result.stdout)
        phy = [r for r in output['regions'] if r['content_type'] == 'phy']
        assert len(phy) >= 1
        assert any(r['offset'] == 0xF000 for r in phy)

    def test_scan_detects_all_app_regions(self):
        result = run_tool('scan', f'{DUMPS}/flash_complex.bin')
        output = json.loads(result.stdout)
        apps = [r for r in output['regions']
                if r['content_type'] == 'app' and r['offset'] >= 0x10000]
        offsets = sorted([a['offset'] for a in apps])
        assert 0x10000 in offsets, "Missing factory at 0x10000"
        assert 0x60000 in offsets, "Missing ota_0 at 0x60000"
        assert 0xB0000 in offsets, "Missing ota_1 at 0xB0000"


# ==================== RECONSTRUCT TESTS — flash_simple.bin ====================

class TestReconstructSimple:
    """Verify partition table reconstruction from the simple dump."""

    def test_reconstruct_creates_file(self):
        out = f'{WORK}/simple.bin'
        result = run_tool('reconstruct', f'{DUMPS}/flash_simple.bin', out)
        assert result.returncode == 0, f"reconstruct failed: {result.stderr}"
        assert os.path.exists(out)

    def test_reconstruct_passes_gen_validation(self):
        out = f'{WORK}/simple_valid.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_simple.bin', out)
        assert validate_binary(out), "Reconstructed table fails gen_esp32part.py"

    def test_reconstruct_correct_file_size(self):
        out = f'{WORK}/simple_size.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_simple.bin', out)
        assert os.path.getsize(out) == 0xC00

    def test_reconstruct_three_entries(self):
        out = f'{WORK}/simple_count.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_simple.bin', out)
        entries, _ = parse_pt_directly(out)
        assert len(entries) == 3, f"Expected 3 entries, got {len(entries)}: {entries}"

    def test_reconstruct_has_nvs_partition(self):
        out = f'{WORK}/simple_nvs.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_simple.bin', out)
        entries, _ = parse_pt_directly(out)
        nvs = [e for e in entries if e['type'] == 1 and e['subtype'] == 0x02]
        assert len(nvs) == 1
        assert nvs[0]['offset'] == 0x9000
        assert nvs[0]['size'] == 0x6000

    def test_reconstruct_has_phy_partition(self):
        out = f'{WORK}/simple_phy.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_simple.bin', out)
        entries, _ = parse_pt_directly(out)
        phy = [e for e in entries if e['type'] == 1 and e['subtype'] == 0x01]
        assert len(phy) == 1
        assert phy[0]['offset'] == 0xF000

    def test_reconstruct_has_factory_app(self):
        out = f'{WORK}/simple_factory.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_simple.bin', out)
        entries, _ = parse_pt_directly(out)
        apps = [e for e in entries if e['type'] == 0]
        assert len(apps) == 1
        assert apps[0]['subtype'] == 0x00  # factory
        assert apps[0]['offset'] == 0x10000

    def test_reconstruct_no_ota_partitions(self):
        out = f'{WORK}/simple_no_ota.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_simple.bin', out)
        entries, _ = parse_pt_directly(out)
        names = [e['name'] for e in entries]
        assert 'otadata' not in names
        assert not any(n.startswith('ota_') for n in names)

    def test_reconstruct_valid_md5(self):
        out = f'{WORK}/simple_md5.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_simple.bin', out)
        _, md5_info = parse_pt_directly(out)
        assert md5_info['present'] is True
        assert md5_info['valid'] is True


# ==================== RECONSTRUCT TESTS — flash_ota.bin ====================

class TestReconstructOta:
    """Verify partition table reconstruction from the OTA-capable dump."""

    def test_reconstruct_passes_gen_validation(self):
        out = f'{WORK}/ota_valid.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_ota.bin', out)
        assert validate_binary(out)

    def test_reconstruct_correct_file_size(self):
        out = f'{WORK}/ota_size.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_ota.bin', out)
        assert os.path.getsize(out) == 0xC00

    def test_reconstruct_six_entries(self):
        """nvs + otadata + phy_init + factory + ota_0 + ota_1 = 6."""
        out = f'{WORK}/ota_count.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_ota.bin', out)
        entries, _ = parse_pt_directly(out)
        assert len(entries) == 6, \
            f"Expected 6 entries, got {len(entries)}: {[e['name'] for e in entries]}"

    def test_reconstruct_has_otadata(self):
        out = f'{WORK}/ota_otadata.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_ota.bin', out)
        entries, _ = parse_pt_directly(out)
        ota_data = [e for e in entries if e['type'] == 1 and e['subtype'] == 0x00]
        assert len(ota_data) >= 1
        assert ota_data[0]['offset'] == 0xD000
        assert ota_data[0]['size'] == 0x2000

    def test_reconstruct_has_three_app_partitions(self):
        out = f'{WORK}/ota_apps.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_ota.bin', out)
        entries, _ = parse_pt_directly(out)
        apps = sorted([e for e in entries if e['type'] == 0],
                       key=lambda e: e['offset'])
        assert len(apps) == 3
        # First should be factory (subtype 0x00)
        assert apps[0]['subtype'] == 0x00
        # Second should be ota_0 (subtype 0x10)
        assert apps[1]['subtype'] == 0x10
        # Third should be ota_1 (subtype 0x11)
        assert apps[2]['subtype'] == 0x11

    def test_reconstruct_app_offsets_64kb_aligned(self):
        out = f'{WORK}/ota_align.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_ota.bin', out)
        entries, _ = parse_pt_directly(out)
        for e in entries:
            if e['type'] == 0:
                assert e['offset'] % 0x10000 == 0, \
                    f"APP '{e['name']}' offset 0x{e['offset']:x} not 64KB-aligned"

    def test_reconstruct_app_sizes_4kb_aligned(self):
        out = f'{WORK}/ota_app_size.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_ota.bin', out)
        entries, _ = parse_pt_directly(out)
        for e in entries:
            if e['type'] == 0:
                assert e['size'] % 0x1000 == 0, \
                    f"APP '{e['name']}' size 0x{e['size']:x} not 4KB-aligned"

    def test_reconstruct_no_overlaps(self):
        out = f'{WORK}/ota_overlap.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_ota.bin', out)
        entries, _ = parse_pt_directly(out)
        sorted_e = sorted(entries, key=lambda e: e['offset'])
        for i in range(len(sorted_e) - 1):
            end = sorted_e[i]['offset'] + sorted_e[i]['size']
            assert end <= sorted_e[i + 1]['offset'], \
                f"'{sorted_e[i]['name']}' (ends 0x{end:x}) overlaps " \
                f"'{sorted_e[i + 1]['name']}' (starts 0x{sorted_e[i + 1]['offset']:x})"

    def test_reconstruct_unique_names(self):
        out = f'{WORK}/ota_names.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_ota.bin', out)
        entries, _ = parse_pt_directly(out)
        names = [e['name'] for e in entries]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_reconstruct_valid_md5(self):
        out = f'{WORK}/ota_md5.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_ota.bin', out)
        _, md5_info = parse_pt_directly(out)
        assert md5_info['present'] is True
        assert md5_info['valid'] is True


# ==================== RECONSTRUCT TESTS — flash_complex.bin ====================

class TestReconstructComplex:
    """Verify reconstruction from dump with partial partition table."""

    def test_reconstruct_passes_gen_validation(self):
        out = f'{WORK}/complex_valid.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_complex.bin', out)
        assert validate_binary(out)

    def test_reconstruct_six_entries(self):
        out = f'{WORK}/complex_count.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_complex.bin', out)
        entries, _ = parse_pt_directly(out)
        assert len(entries) == 6

    def test_reconstruct_preserves_intact_nvs(self):
        """The partial PT had nvs at 0x9000/0x4000 — must be preserved."""
        out = f'{WORK}/complex_nvs.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_complex.bin', out)
        entries, _ = parse_pt_directly(out)
        nvs = [e for e in entries if e['type'] == 1 and e['subtype'] == 0x02]
        assert len(nvs) >= 1
        assert nvs[0]['offset'] == 0x9000
        assert nvs[0]['size'] == 0x4000

    def test_reconstruct_preserves_intact_otadata(self):
        """The partial PT had otadata at 0xD000/0x2000 — must be preserved."""
        out = f'{WORK}/complex_otadata.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_complex.bin', out)
        entries, _ = parse_pt_directly(out)
        ota = [e for e in entries if e['type'] == 1 and e['subtype'] == 0x00]
        assert len(ota) >= 1
        assert ota[0]['offset'] == 0xD000
        assert ota[0]['size'] == 0x2000

    def test_reconstruct_adds_missing_phy(self):
        """PHY at 0xF000 was not in partial PT — must be reconstructed."""
        out = f'{WORK}/complex_phy.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_complex.bin', out)
        entries, _ = parse_pt_directly(out)
        phy = [e for e in entries if e['type'] == 1 and e['subtype'] == 0x01]
        assert len(phy) >= 1
        assert phy[0]['offset'] == 0xF000

    def test_reconstruct_adds_missing_apps(self):
        """App partitions were not in partial PT — must be reconstructed."""
        out = f'{WORK}/complex_apps.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_complex.bin', out)
        entries, _ = parse_pt_directly(out)
        apps = sorted([e for e in entries if e['type'] == 0],
                       key=lambda e: e['offset'])
        assert len(apps) >= 3
        assert apps[0]['offset'] == 0x10000
        assert apps[1]['offset'] == 0x60000
        assert apps[2]['offset'] == 0xB0000

    def test_reconstruct_no_duplicate_entries(self):
        """Merging intact PT + scan must not create duplicates."""
        out = f'{WORK}/complex_nodup.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_complex.bin', out)
        entries, _ = parse_pt_directly(out)
        names = [e['name'] for e in entries]
        assert len(names) == len(set(names)), f"Duplicates: {names}"
        offsets = [e['offset'] for e in entries]
        assert len(offsets) == len(set(offsets)), f"Duplicate offsets: {offsets}"

    def test_reconstruct_no_overlaps(self):
        out = f'{WORK}/complex_overlap.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_complex.bin', out)
        entries, _ = parse_pt_directly(out)
        sorted_e = sorted(entries, key=lambda e: e['offset'])
        for i in range(len(sorted_e) - 1):
            end = sorted_e[i]['offset'] + sorted_e[i]['size']
            assert end <= sorted_e[i + 1]['offset']

    def test_reconstruct_valid_md5(self):
        out = f'{WORK}/complex_md5.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_complex.bin', out)
        _, md5_info = parse_pt_directly(out)
        assert md5_info['present'] is True
        assert md5_info['valid'] is True


# ==================== CHECK TESTS ====================

class TestCheck:
    """Verify the check subcommand against reconstructed tables."""

    def _get_reconstructed(self, dump_name):
        out = f'{WORK}/check_{dump_name}.bin'
        run_tool('reconstruct', f'{DUMPS}/{dump_name}.bin', out)
        return out

    def test_check_returns_valid_json(self):
        out = self._get_reconstructed('flash_simple')
        result = run_tool('check', out)
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert 'entries' in output
        assert 'md5' in output
        assert 'issues' in output

    def test_check_entry_has_required_fields(self):
        out = self._get_reconstructed('flash_simple')
        result = run_tool('check', out)
        output = json.loads(result.stdout)
        required = {'name', 'type', 'subtype', 'offset', 'size', 'flags', 'valid_magic'}
        for entry in output['entries']:
            for field in required:
                assert field in entry, f"Missing field '{field}'"

    def test_check_valid_table_has_no_issues(self):
        out = self._get_reconstructed('flash_ota')
        result = run_tool('check', out)
        output = json.loads(result.stdout)
        assert len(output['issues']) == 0, \
            f"Valid table has issues: {output['issues']}"

    def test_check_md5_reported_correctly(self):
        out = self._get_reconstructed('flash_simple')
        result = run_tool('check', out)
        output = json.loads(result.stdout)
        assert output['md5']['present'] is True
        assert output['md5']['valid'] is True

    def test_check_entry_count_matches_direct_parse(self):
        out = self._get_reconstructed('flash_ota')
        entries_direct, _ = parse_pt_directly(out)
        result = run_tool('check', out)
        output = json.loads(result.stdout)
        assert len(output['entries']) == len(entries_direct)


# ==================== GEN_ESP32PART.PY ROUND-TRIP TESTS ====================

class TestGenRoundTrip:
    """Verify reconstructed tables survive gen_esp32part.py binary->CSV->binary round-trip.

    This confirms full interoperability with the ESP-IDF toolchain: the tool's
    output must use standard type/subtype values, correct alignment, and proper
    naming conventions so that gen_esp32part.py can losslessly convert the binary
    to CSV and back.
    """

    def _verify_roundtrip(self, dump_name):
        """Reconstruct a PT binary, convert it to CSV via gen_esp32part.py,
        then convert the CSV back to binary and compare byte-for-byte."""
        out_bin = f'{WORK}/rt_{dump_name}.bin'
        result = run_tool('reconstruct', f'{DUMPS}/{dump_name}.bin', out_bin)
        assert result.returncode == 0, f"reconstruct failed: {result.stderr}"

        # Binary -> CSV via gen_esp32part.py
        csv_result = subprocess.run(
            ['python3', GEN_TOOL, '--quiet', out_bin],
            capture_output=True, text=True, timeout=30
        )
        assert csv_result.returncode == 0, \
            f"gen_esp32part.py binary->CSV failed: {csv_result.stderr}"
        assert len(csv_result.stdout.strip()) > 0, "CSV output is empty"

        csv_path = f'{WORK}/rt_{dump_name}.csv'
        with open(csv_path, 'w') as f:
            f.write(csv_result.stdout)

        # CSV -> Binary via gen_esp32part.py
        rt_bin = f'{WORK}/rt_{dump_name}_roundtrip.bin'
        rt_result = subprocess.run(
            ['python3', GEN_TOOL, '--quiet', csv_path, rt_bin],
            capture_output=True, text=True, timeout=30
        )
        assert rt_result.returncode == 0, \
            f"gen_esp32part.py CSV->binary failed: {rt_result.stderr}"

        # Byte-for-byte comparison
        with open(out_bin, 'rb') as f:
            original = f.read()
        with open(rt_bin, 'rb') as f:
            roundtripped = f.read()
        assert original == roundtripped, \
            f"Round-trip mismatch for {dump_name}: " \
            f"original {len(original)} bytes vs roundtripped {len(roundtripped)} bytes"

    def test_simple_roundtrip(self):
        self._verify_roundtrip('flash_simple')

    def test_ota_roundtrip(self):
        self._verify_roundtrip('flash_ota')

    def test_complex_roundtrip(self):
        self._verify_roundtrip('flash_complex')

    def test_csv_contains_partition_names(self):
        """Verify gen_esp32part.py CSV output contains expected partition names."""
        out = f'{WORK}/rt_csv_names.bin'
        run_tool('reconstruct', f'{DUMPS}/flash_ota.bin', out)
        csv = gen_esp32part_csv(out)
        assert csv is not None, "gen_esp32part.py failed to produce CSV"
        # The CSV must contain recognizable ESP-IDF partition names
        assert 'factory' in csv, "Missing 'factory' in CSV output"
        assert 'ota_0' in csv, "Missing 'ota_0' in CSV output"
        assert 'ota_1' in csv, "Missing 'ota_1' in CSV output"
        assert 'nvs' in csv, "Missing 'nvs' in CSV output"


# ==================== CROSS-VALIDATION TESTS ====================

class TestCrossValidation:
    """Verify scan -> reconstruct -> check pipeline consistency."""

    def test_all_dumps_reconstruct_and_validate(self):
        """Every dump must produce a table that passes gen_esp32part.py."""
        for dump in ['flash_simple', 'flash_ota', 'flash_complex']:
            out = f'{WORK}/cross_{dump}.bin'
            result = run_tool('reconstruct', f'{DUMPS}/{dump}.bin', out)
            assert result.returncode == 0, f"{dump}: reconstruct failed"
            assert validate_binary(out), f"{dump}: fails gen_esp32part.py"

    def test_all_reconstructed_tables_check_clean(self):
        """check on reconstructed tables must report zero issues."""
        for dump in ['flash_simple', 'flash_ota', 'flash_complex']:
            out = f'{WORK}/crosscheck_{dump}.bin'
            run_tool('reconstruct', f'{DUMPS}/{dump}.bin', out)
            result = run_tool('check', out)
            output = json.loads(result.stdout)
            assert len(output['issues']) == 0, \
                f"{dump} check issues: {output['issues']}"

    def test_scan_region_count_matches_reconstruction(self):
        """Number of scan regions (after 0x9000) should match entry count."""
        for dump, expected_count in [
            ('flash_simple', 3),
            ('flash_ota', 6),
            ('flash_complex', 6),
        ]:
            out = f'{WORK}/scanmatch_{dump}.bin'
            run_tool('reconstruct', f'{DUMPS}/{dump}.bin', out)
            entries, _ = parse_pt_directly(out)
            assert len(entries) == expected_count, \
                f"{dump}: expected {expected_count} entries, got {len(entries)}"
