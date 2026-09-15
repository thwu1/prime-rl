#!/usr/bin/env python3
"""Tests for ESP32 partition table pipeline recovery."""
import hashlib
import os
import struct
import subprocess
import tempfile

import pytest

MAGIC = b'\xaa\x50'
MD5_MAGIC = b'\xeb\xeb'
STRUCT_FMT = '<2sBBLL16sL'
MAX_PARTITION_LENGTH = 0xC00  # 3072 bytes
GEN_TOOL = '/app/tools/gen_esp32part.py'

# ---------- Expected entries per config ----------
# (name, type, subtype, offset, size, flags)

EXPECTED_A = [
    ('nvs',       0x01, 0x02, 0x009000, 0x004000, 0x00),
    ('otadata',   0x01, 0x00, 0x00D000, 0x002000, 0x00),
    ('phy_init',  0x01, 0x01, 0x00F000, 0x001000, 0x00),
    ('factory',   0x00, 0x00, 0x010000, 0x100000, 0x00),
    ('ota_0',     0x00, 0x10, 0x110000, 0x16B000, 0x00),
    ('ota_1',     0x00, 0x11, 0x280000, 0x16B000, 0x00),
    ('coredump',  0x01, 0x03, 0x3EB000, 0x010000, 0x00),
    ('nvs_keys',  0x01, 0x04, 0x3FB000, 0x001000, 0x01),
    ('telemetry', 0x01, 0xFE, 0x3FC000, 0x004000, 0x00),
]

EXPECTED_B = [
    ('nvs',       0x01, 0x02, 0x009000, 0x004000, 0x00),
    ('otadata',   0x01, 0x00, 0x00D000, 0x002000, 0x00),
    ('phy_init',  0x01, 0x01, 0x00F000, 0x001000, 0x00),
    ('factory',   0x00, 0x00, 0x010000, 0x100000, 0x00),
    ('ota_0',     0x00, 0x10, 0x110000, 0x160000, 0x00),
    ('ota_1',     0x00, 0x11, 0x270000, 0x160000, 0x00),
    ('coredump',  0x01, 0x03, 0x3D0000, 0x010000, 0x00),
    ('nvs_keys',  0x01, 0x04, 0x3E0000, 0x001000, 0x01),
    ('telemetry', 0x01, 0xFE, 0x3E1000, 0x004000, 0x00),
]

EXPECTED_C = [
    ('nvs',       0x01, 0x02, 0x011000, 0x004000, 0x00),
    ('otadata',   0x01, 0x00, 0x015000, 0x002000, 0x00),
    ('phy_init',  0x01, 0x01, 0x017000, 0x001000, 0x00),
    ('factory',   0x00, 0x00, 0x020000, 0x100000, 0x00),
    ('ota_0',     0x00, 0x10, 0x120000, 0x760000, 0x00),
    ('ota_1',     0x00, 0x11, 0x880000, 0x760000, 0x00),
    ('coredump',  0x01, 0x03, 0xFE0000, 0x010000, 0x00),
    ('nvs_keys',  0x01, 0x04, 0xFF0000, 0x001000, 0x01),
    ('telemetry', 0x01, 0xFE, 0xFF1000, 0x004000, 0x00),
]

CONFIGS = {
    'config_a': {
        'expected': EXPECTED_A,
        'flash': 0x400000,
        'flags': ['--flash-size', '4MB'],
        'app_size_align': 0x1000,
        'ota_size': 0x16B000,
    },
    'config_b': {
        'expected': EXPECTED_B,
        'flash': 0x400000,
        'flags': ['--secure', 'v1', '--flash-size', '4MB'],
        'app_size_align': 0x10000,
        'ota_size': 0x160000,
    },
    'config_c': {
        'expected': EXPECTED_C,
        'flash': 0x1000000,
        'flags': ['--secure', 'v2', '--flash-size', '16MB', '--offset', '0x10000'],
        'app_size_align': 0x1000,
        'ota_size': 0x760000,
    },
}

NUM_ENTRIES = 9  # all configs have 9 entries


def parse_entry(data):
    """Parse a 32-byte partition entry."""
    magic, type_id, subtype, offset, size, name_raw, flags = struct.unpack(STRUCT_FMT, data)
    if b'\x00' in name_raw:
        name_raw = name_raw[:name_raw.index(b'\x00')]
    name = name_raw.decode('ascii')
    return magic, type_id, subtype, offset, size, name, flags


def read_binary(config_name):
    """Read a config's output binary."""
    path = f'/app/output/{config_name}.bin'
    assert os.path.exists(path), f"{path} does not exist"
    with open(path, 'rb') as f:
        return f.read()


# ---------- Tool regression fix tests ----------

class TestToolFixes:
    """Verify that gen_esp32part.py regressions have been fixed."""

    def test_adjacent_partitions_accepted(self):
        """Adjacent partitions (end == start of next) must not be rejected as overlapping."""
        # Use offsets above 0xA000 to isolate this test from PARTITION_TABLE_SIZE bugs
        csv_content = (
            "p1,data,nvs,0xA000,0x4000,\n"
            "p2,data,ota,0xE000,0x2000,\n"
        )
        csv_fd, csv_path = tempfile.mkstemp(suffix='.csv')
        bin_fd, bin_path = tempfile.mkstemp(suffix='.bin')
        os.close(csv_fd)
        os.close(bin_fd)
        try:
            with open(csv_path, 'w') as f:
                f.write(csv_content)
            result = subprocess.run(
                ['python3', GEN_TOOL, '-q', '--flash-size', '4MB', csv_path, bin_path],
                capture_output=True, text=True
            )
            assert result.returncode == 0, (
                f"Adjacent partitions wrongly rejected: {result.stderr}"
            )
        finally:
            os.unlink(csv_path)
            if os.path.exists(bin_path):
                os.unlink(bin_path)

    def test_partition_at_0x9000_with_default_offset(self):
        """With default PT offset 0x8000, a partition at 0x9000 must be valid.
        PT occupies one 4KB sector [0x8000, 0x9000), so 0x9000 is the first valid offset."""
        csv_content = "nvs,data,nvs,0x9000,0x4000,\n"
        csv_fd, csv_path = tempfile.mkstemp(suffix='.csv')
        bin_fd, bin_path = tempfile.mkstemp(suffix='.bin')
        os.close(csv_fd)
        os.close(bin_fd)
        try:
            with open(csv_path, 'w') as f:
                f.write(csv_content)
            result = subprocess.run(
                ['python3', GEN_TOOL, '-q', '--flash-size', '4MB', csv_path, bin_path],
                capture_output=True, text=True
            )
            assert result.returncode == 0, (
                f"Partition at 0x9000 wrongly rejected: {result.stderr}"
            )
        finally:
            os.unlink(csv_path)
            if os.path.exists(bin_path):
                os.unlink(bin_path)

    def test_partition_at_0x11000_with_custom_offset(self):
        """With PT offset 0x10000, a partition at 0x11000 must be valid.
        PT occupies one 4KB sector [0x10000, 0x11000), so 0x11000 is the first valid offset."""
        csv_content = "nvs,data,nvs,0x11000,0x4000,\n"
        csv_fd, csv_path = tempfile.mkstemp(suffix='.csv')
        bin_fd, bin_path = tempfile.mkstemp(suffix='.bin')
        os.close(csv_fd)
        os.close(bin_fd)
        try:
            with open(csv_path, 'w') as f:
                f.write(csv_content)
            result = subprocess.run(
                ['python3', GEN_TOOL, '-q', '--offset', '0x10000', '--flash-size', '16MB',
                 csv_path, bin_path],
                capture_output=True, text=True
            )
            assert result.returncode == 0, (
                f"Partition at 0x11000 wrongly rejected: {result.stderr}"
            )
        finally:
            os.unlink(csv_path)
            if os.path.exists(bin_path):
                os.unlink(bin_path)

    def test_three_adjacent_partitions(self):
        """Three tightly-packed adjacent partitions must all be accepted."""
        csv_content = (
            "p1,data,nvs,0xA000,0x3000,\n"
            "p2,data,ota,0xD000,0x2000,\n"
            "p3,data,phy,0xF000,0x1000,\n"
        )
        csv_fd, csv_path = tempfile.mkstemp(suffix='.csv')
        bin_fd, bin_path = tempfile.mkstemp(suffix='.bin')
        os.close(csv_fd)
        os.close(bin_fd)
        try:
            with open(csv_path, 'w') as f:
                f.write(csv_content)
            result = subprocess.run(
                ['python3', GEN_TOOL, '-q', '--flash-size', '4MB', csv_path, bin_path],
                capture_output=True, text=True
            )
            assert result.returncode == 0, (
                f"Adjacent partitions wrongly rejected: {result.stderr}"
            )
        finally:
            os.unlink(csv_path)
            if os.path.exists(bin_path):
                os.unlink(bin_path)


# ---------- File structure tests ----------

class TestFileStructure:
    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_file_exists(self, config_name):
        path = f'/app/output/{config_name}.bin'
        assert os.path.exists(path), f"{path} not found"

    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_file_size(self, config_name):
        data = read_binary(config_name)
        assert len(data) == MAX_PARTITION_LENGTH, (
            f"{config_name}: expected {MAX_PARTITION_LENGTH} bytes, got {len(data)}"
        )

    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_entry_count(self, config_name):
        data = read_binary(config_name)
        count = 0
        for i in range(0, MAX_PARTITION_LENGTH, 32):
            chunk = data[i:i + 32]
            if chunk == b'\xff' * 32:
                break
            if chunk[:2] == MD5_MAGIC:
                break
            if chunk[:2] == MAGIC:
                count += 1
            else:
                break
        assert count == NUM_ENTRIES, (
            f"{config_name}: expected {NUM_ENTRIES} entries, found {count}"
        )


# ---------- Entry correctness tests ----------

class TestEntryCorrectness:
    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    @pytest.mark.parametrize("idx", range(NUM_ENTRIES))
    def test_entry_name(self, config_name, idx):
        data = read_binary(config_name)
        entry_data = data[idx * 32:(idx + 1) * 32]
        _, _, _, _, _, name, _ = parse_entry(entry_data)
        exp_name = CONFIGS[config_name]['expected'][idx][0]
        assert name == exp_name, (
            f"{config_name} entry {idx}: name '{name}' != '{exp_name}'"
        )

    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    @pytest.mark.parametrize("idx", range(NUM_ENTRIES))
    def test_entry_type(self, config_name, idx):
        data = read_binary(config_name)
        entry_data = data[idx * 32:(idx + 1) * 32]
        _, type_id, _, _, _, _, _ = parse_entry(entry_data)
        exp = CONFIGS[config_name]['expected'][idx]
        assert type_id == exp[1], (
            f"{config_name} entry {idx} ({exp[0]}): type 0x{type_id:02x} != 0x{exp[1]:02x}"
        )

    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    @pytest.mark.parametrize("idx", range(NUM_ENTRIES))
    def test_entry_subtype(self, config_name, idx):
        data = read_binary(config_name)
        entry_data = data[idx * 32:(idx + 1) * 32]
        _, _, subtype, _, _, _, _ = parse_entry(entry_data)
        exp = CONFIGS[config_name]['expected'][idx]
        assert subtype == exp[2], (
            f"{config_name} entry {idx} ({exp[0]}): subtype 0x{subtype:02x} != 0x{exp[2]:02x}"
        )

    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    @pytest.mark.parametrize("idx", range(NUM_ENTRIES))
    def test_entry_offset(self, config_name, idx):
        data = read_binary(config_name)
        entry_data = data[idx * 32:(idx + 1) * 32]
        _, _, _, offset, _, _, _ = parse_entry(entry_data)
        exp = CONFIGS[config_name]['expected'][idx]
        assert offset == exp[3], (
            f"{config_name} entry {idx} ({exp[0]}): offset 0x{offset:x} != 0x{exp[3]:x}"
        )

    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    @pytest.mark.parametrize("idx", range(NUM_ENTRIES))
    def test_entry_size(self, config_name, idx):
        data = read_binary(config_name)
        entry_data = data[idx * 32:(idx + 1) * 32]
        _, _, _, _, size, _, _ = parse_entry(entry_data)
        exp = CONFIGS[config_name]['expected'][idx]
        assert size == exp[4], (
            f"{config_name} entry {idx} ({exp[0]}): size 0x{size:x} != 0x{exp[4]:x}"
        )

    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    @pytest.mark.parametrize("idx", range(NUM_ENTRIES))
    def test_entry_flags(self, config_name, idx):
        data = read_binary(config_name)
        entry_data = data[idx * 32:(idx + 1) * 32]
        _, _, _, _, _, _, flags = parse_entry(entry_data)
        exp = CONFIGS[config_name]['expected'][idx]
        assert flags == exp[5], (
            f"{config_name} entry {idx} ({exp[0]}): flags 0x{flags:x} != 0x{exp[5]:x}"
        )


# ---------- MD5 integrity ----------

class TestMD5:
    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_md5_present(self, config_name):
        data = read_binary(config_name)
        md5_off = NUM_ENTRIES * 32
        record = data[md5_off:md5_off + 32]
        assert record[:2] == MD5_MAGIC, (
            f"{config_name}: MD5 marker not found at offset {md5_off}"
        )

    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_md5_correct(self, config_name):
        data = read_binary(config_name)
        md5_off = NUM_ENTRIES * 32
        entry_bytes = data[:md5_off]
        expected = hashlib.md5(entry_bytes).digest()
        actual = data[md5_off + 16:md5_off + 32]
        assert actual == expected, (
            f"{config_name}: MD5 mismatch: got {actual.hex()}, expected {expected.hex()}"
        )


# ---------- Padding ----------

class TestPadding:
    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_trailing_padding(self, config_name):
        data = read_binary(config_name)
        pad_start = (NUM_ENTRIES + 1) * 32
        padding = data[pad_start:]
        assert len(padding) > 0, f"{config_name}: no padding after MD5"
        assert padding == b'\xff' * len(padding), (
            f"{config_name}: non-0xFF bytes in padding"
        )


# ---------- Layout constraints ----------

class TestLayoutConstraints:
    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_no_overlaps(self, config_name):
        data = read_binary(config_name)
        parts = []
        for idx in range(NUM_ENTRIES):
            entry = data[idx * 32:(idx + 1) * 32]
            _, _, _, offset, size, name, _ = parse_entry(entry)
            parts.append((name, offset, offset + size))
        parts.sort(key=lambda x: x[1])
        for i in range(len(parts) - 1):
            na, _, ea = parts[i]
            nb, sb, _ = parts[i + 1]
            assert ea <= sb, (
                f"{config_name}: '{na}' (ends 0x{ea:x}) overlaps '{nb}' (starts 0x{sb:x})"
            )

    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_fits_in_flash(self, config_name):
        data = read_binary(config_name)
        flash = CONFIGS[config_name]['flash']
        for idx in range(NUM_ENTRIES):
            entry = data[idx * 32:(idx + 1) * 32]
            _, _, _, offset, size, name, _ = parse_entry(entry)
            assert offset + size <= flash, (
                f"{config_name}: '{name}' exceeds flash (0x{offset + size:x} > 0x{flash:x})"
            )

    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_app_offset_alignment(self, config_name):
        data = read_binary(config_name)
        for idx in range(NUM_ENTRIES):
            entry = data[idx * 32:(idx + 1) * 32]
            _, type_id, _, offset, _, name, _ = parse_entry(entry)
            if type_id == 0x00:  # app
                assert offset % 0x10000 == 0, (
                    f"{config_name}: app '{name}' offset 0x{offset:x} not 64KB aligned"
                )

    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_app_size_alignment(self, config_name):
        data = read_binary(config_name)
        align = CONFIGS[config_name]['app_size_align']
        for idx in range(NUM_ENTRIES):
            entry = data[idx * 32:(idx + 1) * 32]
            _, type_id, _, _, size, name, _ = parse_entry(entry)
            if type_id == 0x00:  # app
                assert size % align == 0, (
                    f"{config_name}: app '{name}' size 0x{size:x} not aligned to 0x{align:x}"
                )

    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_data_offset_alignment(self, config_name):
        data = read_binary(config_name)
        for idx in range(NUM_ENTRIES):
            entry = data[idx * 32:(idx + 1) * 32]
            _, type_id, _, offset, _, name, _ = parse_entry(entry)
            if type_id == 0x01:  # data
                assert offset % 0x1000 == 0, (
                    f"{config_name}: data '{name}' offset 0x{offset:x} not 4KB aligned"
                )


# ---------- OTA slot tests ----------

class TestOTASlots:
    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_ota_slots_equal(self, config_name):
        data = read_binary(config_name)
        ota0 = data[4 * 32:5 * 32]
        ota1 = data[5 * 32:6 * 32]
        _, _, _, _, size0, _, _ = parse_entry(ota0)
        _, _, _, _, size1, _, _ = parse_entry(ota1)
        assert size0 == size1, (
            f"{config_name}: OTA slots unequal: ota_0=0x{size0:x}, ota_1=0x{size1:x}"
        )

    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_ota_slots_maximized(self, config_name):
        data = read_binary(config_name)
        ota0 = data[4 * 32:5 * 32]
        _, _, _, _, size, _, _ = parse_entry(ota0)
        expected = CONFIGS[config_name]['ota_size']
        assert size == expected, (
            f"{config_name}: OTA slot 0x{size:x} != maximum 0x{expected:x}"
        )


# ---------- gen_esp32part.py round-trip test ----------

class TestToolRoundTrip:
    @pytest.mark.parametrize("config_name", list(CONFIGS.keys()))
    def test_roundtrip(self, config_name):
        """Binary -> CSV -> Binary must produce identical output with correct flags."""
        bin_path = f'/app/output/{config_name}.bin'
        cfg = CONFIGS[config_name]
        flags = cfg['flags']

        csv_fd, csv_path = tempfile.mkstemp(suffix='.csv')
        os.close(csv_fd)
        rt_fd, rt_path = tempfile.mkstemp(suffix='.bin')
        os.close(rt_fd)

        try:
            # Binary -> CSV (with validation)
            cmd1 = ['python3', GEN_TOOL, '-q'] + flags + [bin_path, csv_path]
            r1 = subprocess.run(cmd1, capture_output=True, text=True)
            assert r1.returncode == 0, (
                f"{config_name} binary->CSV failed: {r1.stderr}"
            )

            # CSV -> Binary (with validation)
            cmd2 = ['python3', GEN_TOOL, '-q'] + flags + [csv_path, rt_path]
            r2 = subprocess.run(cmd2, capture_output=True, text=True)
            assert r2.returncode == 0, (
                f"{config_name} CSV->binary failed: {r2.stderr}"
            )

            # Compare bytes
            with open(bin_path, 'rb') as f1:
                original = f1.read()
            with open(rt_path, 'rb') as f2:
                roundtrip = f2.read()
            assert original == roundtrip, (
                f"{config_name}: round-trip produced different binary"
            )
        finally:
            os.unlink(csv_path)
            os.unlink(rt_path)


# ---------- Cross-config consistency ----------

class TestCrossConfig:
    def test_all_configs_share_partition_names(self):
        """All three configs must have the same partition names in the same order."""
        names = {}
        for config_name in CONFIGS:
            data = read_binary(config_name)
            cfg_names = []
            for idx in range(NUM_ENTRIES):
                entry = data[idx * 32:(idx + 1) * 32]
                _, _, _, _, _, name, _ = parse_entry(entry)
                cfg_names.append(name)
            names[config_name] = cfg_names

        ref = names['config_a']
        for config_name, cfg_names in names.items():
            assert cfg_names == ref, (
                f"{config_name} partition names differ from config_a: {cfg_names} != {ref}"
            )

    def test_config_b_ota_smaller_than_a(self):
        """Secure boot v1 64KB size alignment should yield smaller OTA than config_a."""
        data_a = read_binary('config_a')
        data_b = read_binary('config_b')
        _, _, _, _, size_a, _, _ = parse_entry(data_a[4 * 32:5 * 32])
        _, _, _, _, size_b, _, _ = parse_entry(data_b[4 * 32:5 * 32])
        assert size_b < size_a, (
            f"config_b OTA (0x{size_b:x}) should be < config_a OTA (0x{size_a:x}) "
            "due to secure boot v1 size alignment"
        )
