#!/usr/bin/env python3
"""Tests for the SBR crossflash task.

"""
import struct
import os
import json
import subprocess

import pytest

OUTPUT_PATH = "/app/output/target.bin"
HEX_PATH = "/app/output/target.hex"
DIFF_PATH = "/app/output/diff_report.txt"
FIELD_MAP_PATH = "/app/output/field_map.json"
AUDIT_PATH = "/app/output/integrity_audit.json"
FUJITSU_ORIG = "/app/dumps/fujitsu_d2607_original.bin"

# Expected values for the Fujitsu-specific fields that must be preserved
EXPECTED_PHY_CONFIG = bytes([
    0x61, 0xf6, 0x22, 0x61, 0xf7, 0x36,
    0x4f, 0xb3, 0xf8, 0x00, 0xd7, 0x91
])
EXPECTED_TIMING = bytes([
    0x00, 0x0c, 0x5d, 0x00, 0x5c, 0x30,
    0x5a, 0x14, 0x75, 0x05, 0x10
])
EXPECTED_SAS_ADDR = bytes([
    0x50, 0x00, 0x05, 0x1E, 0x00, 0x4B, 0x91, 0xA2
])

CHECKSUM_TARGET = 0x5B


@pytest.fixture
def sbr_data():
    """Load the output SBR binary."""
    assert os.path.exists(OUTPUT_PATH), (
        f"Output file {OUTPUT_PATH} does not exist. "
        "The agent must write the target SBR to this path."
    )
    with open(OUTPUT_PATH, 'rb') as f:
        data = f.read()
    return data


# ───── Binary content tests ─────

def test_file_size(sbr_data):
    """SBR must be exactly 256 bytes."""
    assert len(sbr_data) == 256, (
        f"SBR must be exactly 256 bytes, got {len(sbr_data)}"
    )


def test_pci_vendor_id(sbr_data):
    """PCI Vendor ID must be 0x1000 (LSI Logic)."""
    vid = struct.unpack_from('<H', sbr_data, 0x0C)[0]
    assert vid == 0x1000, (
        f"PCI Vendor ID should be 0x1000 (LSI Logic), got 0x{vid:04X}"
    )


def test_pci_product_id(sbr_data):
    """PCI Product ID must be 0x0072 (IT/IR HBA mode)."""
    pid = struct.unpack_from('<H', sbr_data, 0x0E)[0]
    assert pid == 0x0072, (
        f"PCI Product ID should be 0x0072 (IT/IR mode), got 0x{pid:04X}"
    )


def test_interface_mode(sbr_data):
    """Interface mode byte must be 0x00 for IT/IR."""
    mode = sbr_data[0x10]
    assert mode == 0x00, (
        f"Interface mode should be 0x00 (IT/IR), got 0x{mode:02X}"
    )


def test_phy_lane_enable(sbr_data):
    """PHY lane enable must be 0x07 to activate all 8 SAS ports."""
    phy = sbr_data[0x12]
    assert phy == 0x07, (
        f"PHY lane enable should be 0x07 (all 8 ports), got 0x{phy:02X}"
    )


def test_subsystem_vendor_id(sbr_data):
    """Subsystem Vendor ID must be preserved as 0x1734 (Fujitsu)."""
    svid = struct.unpack_from('<H', sbr_data, 0x14)[0]
    assert svid == 0x1734, (
        f"Subsystem VID should be 0x1734 (Fujitsu), got 0x{svid:04X}"
    )


def test_subsystem_product_id(sbr_data):
    """Subsystem Product ID must be preserved as 0x1177."""
    spid = struct.unpack_from('<H', sbr_data, 0x16)[0]
    assert spid == 0x1177, (
        f"Subsystem PID should be 0x1177, got 0x{spid:04X}"
    )


def test_sas_address(sbr_data):
    """SAS World Wide Name must match the original Fujitsu address."""
    actual = sbr_data[0xD8:0xE0]
    assert actual == EXPECTED_SAS_ADDR, (
        f"SAS address mismatch. "
        f"Expected {EXPECTED_SAS_ADDR.hex(':')}, "
        f"got {actual.hex(':')}"
    )


def test_primary_checksum(sbr_data):
    """Primary checksum: sum of bytes 0x00-0x4B mod 256 must equal 0x5B."""
    total = sum(sbr_data[0x00:0x4C]) % 256
    assert total == CHECKSUM_TARGET, (
        f"Primary checksum invalid: sum(0x00..0x4B) mod 256 = "
        f"0x{total:02X}, expected 0x{CHECKSUM_TARGET:02X}"
    )


def test_mfg_page2_mirror(sbr_data):
    """Mfg Page 2 mirror (0x4C-0x97) must be an exact copy of 0x00-0x4B."""
    primary = sbr_data[0x00:0x4C]
    mirror = sbr_data[0x4C:0x98]
    if primary != mirror:
        for i in range(len(primary)):
            if primary[i] != mirror[i]:
                pytest.fail(
                    f"Mirror mismatch at offset {i}: "
                    f"primary[0x{i:02X}]=0x{primary[i]:02X}, "
                    f"mirror[0x{0x4C+i:02X}]=0x{mirror[i]:02X}"
                )


def test_sas_checksum(sbr_data):
    """SAS checksum: sum of bytes 0xD8-0xEF mod 256 must equal 0x5B."""
    total = sum(sbr_data[0xD8:0xF0]) % 256
    assert total == CHECKSUM_TARGET, (
        f"SAS checksum invalid: sum(0xD8..0xEF) mod 256 = "
        f"0x{total:02X}, expected 0x{CHECKSUM_TARGET:02X}"
    )


def test_phy_config_preserved(sbr_data):
    """PHY analog config (0x00-0x0B) must match the Fujitsu original."""
    actual = sbr_data[0x00:0x0C]
    assert actual == EXPECTED_PHY_CONFIG, (
        f"PHY config mismatch — must match Fujitsu hardware. "
        f"Expected {EXPECTED_PHY_CONFIG.hex()}, got {actual.hex()}"
    )


def test_timing_preserved(sbr_data):
    """Timing parameters (0x40-0x4A) must match the Fujitsu original."""
    actual = sbr_data[0x40:0x4B]
    assert actual == EXPECTED_TIMING, (
        f"Timing parameters mismatch — must match Fujitsu hardware. "
        f"Expected {EXPECTED_TIMING.hex()}, got {actual.hex()}"
    )


def test_reserved_regions_zero(sbr_data):
    """All reserved regions must be zeroed."""
    regions = [
        (0x18, 0x40, "0x18-0x3F"),
        (0x98, 0xD8, "0x98-0xD7"),
        (0xE0, 0xEF, "0xE0-0xEE"),
        (0xF0, 0x100, "0xF0-0xFF"),
    ]
    for start, end, label in regions:
        segment = sbr_data[start:end]
        if any(b != 0 for b in segment):
            nonzero = [(start + i, b) for i, b in enumerate(segment) if b != 0]
            first = nonzero[0]
            pytest.fail(
                f"Reserved region {label} should be all zeros. "
                f"First non-zero at 0x{first[0]:02X}=0x{first[1]:02X} "
                f"({len(nonzero)} non-zero bytes total)"
            )


# ───── Tool-proficiency artifact tests ─────

def test_hex_dump_exists():
    """target.hex must exist as an xxd-format hex dump."""
    assert os.path.exists(HEX_PATH), (
        f"{HEX_PATH} not found. Produce an xxd-format hex dump of target.bin."
    )
    with open(HEX_PATH) as f:
        content = f.read().strip()
    assert len(content) > 0, "target.hex is empty"
    first_line = content.split('\n')[0]
    assert first_line.startswith("00000000:") or first_line.startswith("0000000:"), (
        f"target.hex does not appear to be xxd format. First line: {first_line!r}"
    )


def test_hex_roundtrip(sbr_data):
    """xxd -r target.hex must reproduce target.bin byte-for-byte."""
    result = subprocess.run(
        ["xxd", "-r", HEX_PATH],
        capture_output=True
    )
    assert result.returncode == 0, (
        f"xxd -r failed with exit code {result.returncode}: "
        f"{result.stderr.decode()}"
    )
    assert result.stdout == sbr_data, (
        f"xxd -r output ({len(result.stdout)} bytes) does not match "
        f"target.bin ({len(sbr_data)} bytes) — hex dump is not a faithful "
        f"representation of the binary"
    )


def test_diff_report_exists():
    """diff_report.txt must exist with cmp -l byte-level comparison data."""
    assert os.path.exists(DIFF_PATH), (
        f"{DIFF_PATH} not found. Produce a cmp -l comparison between "
        f"the original Fujitsu dump and target.bin."
    )
    with open(DIFF_PATH) as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
    assert len(lines) >= 3, (
        f"diff_report.txt should have at least 3 lines of byte differences "
        f"(PID, mode, and PHY lane changes at minimum), got {len(lines)}"
    )


def test_field_map_valid():
    """field_map.json must document the reverse-engineered SBR field layout."""
    assert os.path.exists(FIELD_MAP_PATH), (
        f"{FIELD_MAP_PATH} not found. Produce a JSON field map of the "
        f"reverse-engineered SBR layout."
    )
    with open(FIELD_MAP_PATH) as f:
        data = json.load(f)

    assert "fields" in data, "field_map.json must contain a 'fields' key"
    fields = data["fields"]
    assert isinstance(fields, list), "'fields' must be an array"
    assert len(fields) >= 10, (
        f"Expected at least 10 field entries, got {len(fields)}"
    )

    for i, entry in enumerate(fields):
        assert "offset_hex" in entry, f"Field {i} missing 'offset_hex'"
        assert "size_bytes" in entry, f"Field {i} missing 'size_bytes'"
        assert "description" in entry, f"Field {i} missing 'description'"
        assert isinstance(entry["size_bytes"], int), (
            f"Field {i} 'size_bytes' must be an integer"
        )

    documented_offsets = set()
    for entry in fields:
        try:
            val = int(entry["offset_hex"], 16)
            documented_offsets.add(f"0x{val:02x}")
        except (ValueError, TypeError):
            documented_offsets.add(entry["offset_hex"].lower())

    required_offsets = {
        "0x0c", "0x0e", "0x10", "0x12", "0x14", "0x16",
        "0x4b", "0x4c", "0xd8", "0xef"
    }
    missing = required_offsets - documented_offsets
    assert not missing, (
        f"field_map.json missing required offset entries: "
        f"{', '.join(sorted(missing))}"
    )


# ───── Integrity audit tests ─────

def test_integrity_audit_structure():
    """integrity_audit.json must exist with correct structure for all dumps."""
    assert os.path.exists(AUDIT_PATH), (
        f"{AUDIT_PATH} not found. Produce an integrity audit of all dumps."
    )
    with open(AUDIT_PATH) as f:
        data = json.load(f)

    assert "samples" in data, "integrity_audit.json must contain a 'samples' key"
    samples = data["samples"]
    assert isinstance(samples, list), "'samples' must be an array"

    filenames = {s["filename"] for s in samples}
    expected_files = {
        "supermicro_itir.bin", "supermicro_imr.bin",
        "fujitsu_d2607_original.bin", "dell_h200.bin",
        "ibm_m1015.bin", "lsi_generic_template.bin"
    }
    missing = expected_files - filenames
    assert not missing, f"Audit missing samples: {', '.join(sorted(missing))}"

    for s in samples:
        assert "filename" in s, "Audit entry missing 'filename'"
        assert "valid" in s, f"Entry for {s.get('filename', '?')} missing 'valid'"
        assert "issues" in s, f"Entry for {s.get('filename', '?')} missing 'issues'"
        assert isinstance(s["valid"], bool), (
            f"'valid' must be boolean for {s['filename']}"
        )
        assert isinstance(s["issues"], list), (
            f"'issues' must be an array for {s['filename']}"
        )


def test_integrity_audit_detects_ibm_corruption():
    """IBM M1015 has a corrupted timing byte that breaks its checksum.
    The manifest claims it is 'working' — the agent must detect the
    corruption through binary analysis, not manifest inspection."""
    with open(AUDIT_PATH) as f:
        data = json.load(f)
    ibm = next(s for s in data["samples"] if s["filename"] == "ibm_m1015.bin")
    assert ibm["valid"] is False, (
        "IBM M1015 has silent corruption (broken primary checksum and "
        "mirror inconsistency) but was not flagged as invalid"
    )
    assert len(ibm["issues"]) > 0, (
        "IBM M1015 is invalid but has empty issues list — "
        "must describe what integrity check failed"
    )


def test_integrity_audit_detects_lsi_corruption():
    """LSI generic template has a subtle mirror inconsistency — primary
    checksum is valid, but the mirror region doesn't match the primary.
    This requires checking BOTH checksums AND mirror consistency."""
    with open(AUDIT_PATH) as f:
        data = json.load(f)
    lsi = next(
        s for s in data["samples"]
        if s["filename"] == "lsi_generic_template.bin"
    )
    assert lsi["valid"] is False, (
        "LSI generic template has a mirror inconsistency (primary checksum "
        "passes but mirror doesn't match primary) — was not flagged as invalid"
    )
    assert len(lsi["issues"]) > 0, (
        "LSI template is invalid but has empty issues list — "
        "must describe the mirror inconsistency"
    )


def test_integrity_audit_valid_samples():
    """The four structurally sound samples must be marked as valid."""
    with open(AUDIT_PATH) as f:
        data = json.load(f)
    valid_files = {
        "supermicro_itir.bin", "supermicro_imr.bin",
        "fujitsu_d2607_original.bin", "dell_h200.bin"
    }
    for fname in valid_files:
        sample = next(s for s in data["samples"] if s["filename"] == fname)
        assert sample["valid"] is True, (
            f"{fname} is structurally sound but was incorrectly "
            f"flagged as invalid with issues: {sample.get('issues', [])}"
        )
