
"""
Tests for the ESP32 TWAI CAN bus acceptance filter tool.

Validates three operations:
  - match: test a CAN frame against a filter configuration
  - synthesize: compute optimal filter registers for a set of frames
  - parse-dump: decode a binary register dump file
"""

import subprocess
import os
import json
import pytest

TOOL = "/app/twai_filter.py"


def run_match(mode, reg_hex, frame_spec):
    """Run a match command and return stdout stripped."""
    reg_hex = reg_hex.replace(" ", "")
    result = subprocess.run(
        ["python3", TOOL, "match", mode, reg_hex, frame_spec],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"match failed: {result.stderr}"
    return result.stdout.strip()


def run_synthesize(mode, frame_specs):
    """Run a synthesize command and return stdout stripped."""
    result = subprocess.run(
        ["python3", TOOL, "synthesize", mode] + frame_specs,
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"synthesize failed: {result.stderr}"
    return result.stdout.strip()


def run_parse_dump(file_path):
    """Run a parse-dump command and return parsed JSON."""
    result = subprocess.run(
        ["python3", TOOL, "parse-dump", file_path],
        capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"parse-dump failed: {result.stderr}"
    return json.loads(result.stdout.strip())


def code_mask_to_registers(code: int, mask: int) -> str:
    """Convert logical code/mask to register hex (mask inverted)."""
    code_bytes = code.to_bytes(4, 'big')
    inv_mask = (~mask) & 0xFFFFFFFF
    mask_bytes = inv_mask.to_bytes(4, 'big')
    return (code_bytes + mask_bytes).hex()


# =============================================================================
# SINGLE STANDARD FILTER - MATCHING
# =============================================================================

class TestSingleStandardMatch:
    """Test SingleStandard filter matching (11-bit ID + RTR + 2 payload bytes)."""

    def test_exact_id_match_accept(self):
        """ID 0x541 exact match, don't care RTR/payload."""
        regs = code_mask_to_registers(0xA8200000, 0xFFE00000)
        assert run_match("single_standard", regs, "std:0x541:0:aabb") == "ACCEPT"

    def test_exact_id_match_reject(self):
        """ID 0x540 should be rejected when filter is for 0x541."""
        regs = code_mask_to_registers(0xA8200000, 0xFFE00000)
        assert run_match("single_standard", regs, "std:0x540:0:aabb") == "REJECT"

    def test_id_wildcard_lsb(self):
        """Don't care about ID LSB -> accept both 0x540 and 0x541."""
        regs = code_mask_to_registers(0xA8200000, 0xFFC00000)
        assert run_match("single_standard", regs, "std:0x540:0:") == "ACCEPT"
        assert run_match("single_standard", regs, "std:0x541:0:") == "ACCEPT"
        assert run_match("single_standard", regs, "std:0x543:0:") == "REJECT"

    def test_rtr_care_accept(self):
        """RTR bit must match: code RTR=1, frame RTR=1 -> accept."""
        regs = code_mask_to_registers(0xA8300000, 0xFFF00000)
        assert run_match("single_standard", regs, "std:0x541:1:") == "ACCEPT"

    def test_rtr_care_reject(self):
        """RTR bit must match: code RTR=1, frame RTR=0 -> reject."""
        regs = code_mask_to_registers(0xA8300000, 0xFFF00000)
        assert run_match("single_standard", regs, "std:0x541:0:aabb") == "REJECT"

    def test_payload_exact_match(self):
        """Exact payload match: 0xCAFE."""
        code = (0x541 << 21) | (0xCA << 8) | 0xFE
        mask = 0xFFE0FFFF
        regs = code_mask_to_registers(code, mask)
        assert run_match("single_standard", regs, "std:0x541:0:cafe") == "ACCEPT"

    def test_payload_mismatch_reject(self):
        """Payload mismatch in second byte -> reject."""
        code = (0x541 << 21) | (0xCA << 8) | 0xFE
        mask = 0xFFE0FFFF
        regs = code_mask_to_registers(code, mask)
        assert run_match("single_standard", regs, "std:0x541:0:caff") == "REJECT"

    def test_accept_all(self):
        """Register mask all 0xFF = all don't care -> accept everything."""
        regs = "00000000ffffffff"
        assert run_match("single_standard", regs, "std:0x7ff:1:dead") == "ACCEPT"
        assert run_match("single_standard", regs, "std:0x000:0:0000") == "ACCEPT"

    def test_reject_all_but_zero(self):
        """Exact match for ID=0, RTR=0, payload=0x0000."""
        regs = "0000000000000000"
        assert run_match("single_standard", regs, "std:0x000:0:0000") == "ACCEPT"
        assert run_match("single_standard", regs, "std:0x001:0:0000") == "REJECT"

    def test_payload_shorter_than_two_bytes(self):
        """When frame has <2 payload bytes, missing bytes treated as 0x00."""
        code = (0x100 << 21) | (0xAB << 8) | 0x00
        mask = 0xFFE0FFFF
        regs = code_mask_to_registers(code, mask)
        assert run_match("single_standard", regs, "std:0x100:0:ab") == "ACCEPT"

    def test_empty_payload_match(self):
        """Empty payload, filter cares about payload = 0x0000."""
        code = (0x100 << 21)
        mask = 0xFFE0FFFF
        regs = code_mask_to_registers(code, mask)
        assert run_match("single_standard", regs, "std:0x100:0:") == "ACCEPT"


# =============================================================================
# SINGLE EXTENDED FILTER - MATCHING
# =============================================================================

class TestSingleExtendedMatch:
    """Test SingleExtended filter matching (29-bit ID + RTR)."""

    def test_exact_id_accept(self):
        """Exact 29-bit ID match."""
        ext_id = 0x15040000
        code = ext_id << 3
        mask = 0xFFFFFFF8
        regs = code_mask_to_registers(code, mask)
        assert run_match("single_extended", regs, "ext:0x15040000:0:") == "ACCEPT"

    def test_exact_id_reject(self):
        """Wrong 29-bit ID -> reject."""
        ext_id = 0x15040000
        code = ext_id << 3
        mask = 0xFFFFFFF8
        regs = code_mask_to_registers(code, mask)
        assert run_match("single_extended", regs, "ext:0x15040001:0:") == "REJECT"

    def test_rtr_match(self):
        """RTR bit at position 2 in extended mode."""
        ext_id = 0x1ABCDEF0
        code = (ext_id << 3) | (1 << 2)
        mask = 0xFFFFFFFC
        regs = code_mask_to_registers(code, mask)
        assert run_match("single_extended", regs, "ext:0x1ABCDEF0:1:") == "ACCEPT"
        assert run_match("single_extended", regs, "ext:0x1ABCDEF0:0:") == "REJECT"

    def test_partial_id_wildcard(self):
        """Don't care about lower 4 bits of ID -> accept range."""
        ext_id_base = 0x1ABCDE00
        code = ext_id_base << 3
        mask = 0xFFFFFF80
        regs = code_mask_to_registers(code, mask)
        assert run_match("single_extended", regs, "ext:0x1ABCDE00:0:") == "ACCEPT"
        assert run_match("single_extended", regs, "ext:0x1ABCDE0F:0:") == "ACCEPT"
        assert run_match("single_extended", regs, "ext:0x1ABCDE10:0:") == "REJECT"

    def test_max_extended_id(self):
        """Maximum extended ID 0x1FFFFFFF."""
        ext_id = 0x1FFFFFFF
        code = ext_id << 3
        mask = 0xFFFFFFF8
        regs = code_mask_to_registers(code, mask)
        assert run_match("single_extended", regs, "ext:0x1FFFFFFF:0:") == "ACCEPT"
        assert run_match("single_extended", regs, "ext:0x1FFFFFFE:0:") == "REJECT"

    def test_zero_extended_id(self):
        """Extended ID = 0."""
        code = 0
        mask = 0xFFFFFFF8
        regs = code_mask_to_registers(code, mask)
        assert run_match("single_extended", regs, "ext:0x00000000:0:") == "ACCEPT"
        assert run_match("single_extended", regs, "ext:0x00000001:0:") == "REJECT"


# =============================================================================
# DUAL STANDARD FILTER - MATCHING
# =============================================================================

class TestDualStandardMatch:
    """Test DualStandard filter matching.

    Filter 1: ID at bits 31-21, RTR at bit 20, payload byte split: upper nibble bits 19-16, lower nibble bits 3-0
    Filter 2: ID at bits 15-5, RTR at bit 4
    Frame accepted if EITHER filter matches.
    """

    def test_filter1_id_only_accept(self):
        """Filter 1 matches ID, don't care about rest."""
        f1_code = 0x541 << 21
        f1_mask = 0xFFE00000
        code = f1_code
        mask = f1_mask
        regs = code_mask_to_registers(code, mask)
        assert run_match("dual_standard", regs, "std:0x541:0:") == "ACCEPT"

    def test_filter2_id_only_accept(self):
        """Filter 2 matches ID, filter 1 rejects."""
        f1_code = 0x000 << 21
        f1_mask = 0xFFE00000
        f2_code = 0x200 << 5
        f2_mask = 0x0000FFE0
        code = f1_code | f2_code
        mask = f1_mask | f2_mask
        regs = code_mask_to_registers(code, mask)
        assert run_match("dual_standard", regs, "std:0x200:0:") == "ACCEPT"

    def test_both_reject(self):
        """Neither filter matches -> reject."""
        f1_code = 0x100 << 21
        f1_mask = 0xFFE00000
        f2_code = 0x200 << 5
        f2_mask = 0x0000FFE0
        code = f1_code | f2_code
        mask = f1_mask | f2_mask
        regs = code_mask_to_registers(code, mask)
        assert run_match("dual_standard", regs, "std:0x300:0:") == "REJECT"

    def test_filter1_split_payload_accept(self):
        """Filter 1 with split payload byte: upper nibble at bits 19-16, lower at bits 3-0."""
        f1_id = 0x100 << 21
        f1_payload_upper = 0xA << 16
        f1_payload_lower = 0xB
        code = f1_id | f1_payload_upper | f1_payload_lower
        mask = 0xFFE00000 | 0x000F0000 | 0x0000000F
        regs = code_mask_to_registers(code, mask)
        assert run_match("dual_standard", regs, "std:0x100:0:ab") == "ACCEPT"

    def test_filter1_split_payload_reject(self):
        """Split payload: wrong lower nibble -> reject (filter 2 also rejects)."""
        f1_id = 0x100 << 21
        f1_payload_upper = 0xA << 16
        f1_payload_lower = 0xB
        f2_code = 0x7FF << 5
        f2_mask = 0x0000FFE0
        code = (f1_id | f1_payload_upper | f1_payload_lower) | f2_code
        mask = (0xFFE00000 | 0x000F0000 | 0x0000000F) | f2_mask
        regs = code_mask_to_registers(code, mask)
        assert run_match("dual_standard", regs, "std:0x100:0:ac") == "REJECT"

    def test_filter2_rtr_match(self):
        """Filter 2 RTR at bit 4."""
        f1_code = 0x7FF << 21
        f1_mask = 0xFFE00000
        f2_code = (0x100 << 5) | (1 << 4)
        f2_mask = 0x0000FFF0
        code = f1_code | f2_code
        mask = f1_mask | f2_mask
        regs = code_mask_to_registers(code, mask)
        assert run_match("dual_standard", regs, "std:0x100:1:") == "ACCEPT"
        assert run_match("dual_standard", regs, "std:0x100:0:") == "REJECT"

    def test_either_filter_accept(self):
        """If either filter matches, accept."""
        f1_code = 0x100 << 21
        f2_code = 0x200 << 5
        code = f1_code | f2_code
        mask = 0xFFE00000 | 0x0000FFE0
        regs = code_mask_to_registers(code, mask)
        assert run_match("dual_standard", regs, "std:0x100:0:") == "ACCEPT"
        assert run_match("dual_standard", regs, "std:0x200:0:") == "ACCEPT"
        assert run_match("dual_standard", regs, "std:0x300:0:") == "REJECT"


# =============================================================================
# DUAL EXTENDED FILTER - MATCHING
# =============================================================================

class TestDualExtendedMatch:
    """Test DualExtended filter matching.

    Each filter matches the upper 16 bits of (ID << 3).
    Filter 1: register bits 31-16
    Filter 2: register bits 15-0
    """

    def test_filter1_accept(self):
        """Filter 1 matches upper 16 bits of shifted ID."""
        code = 0xA8200000
        mask = 0xFFFF0000
        regs = code_mask_to_registers(code, mask)
        assert run_match("dual_extended", regs, "ext:0x15040000:0:") == "ACCEPT"
        assert run_match("dual_extended", regs, "ext:0x15040001:0:") == "ACCEPT"

    def test_filter1_reject(self):
        """Filter 1 upper 16 bits don't match, filter 2 also configured to reject."""
        code = 0xA820FFFF
        mask = 0xFFFFFFFF
        regs = code_mask_to_registers(code, mask)
        assert run_match("dual_extended", regs, "ext:0x00000000:0:") == "REJECT"

    def test_filter2_accept(self):
        """Filter 2 matches."""
        code = 0xFFFFA820
        mask = 0xFFFFFFFF
        regs = code_mask_to_registers(code, mask)
        assert run_match("dual_extended", regs, "ext:0x15040000:0:") == "ACCEPT"

    def test_neither_match(self):
        """Neither filter matches -> reject."""
        code = 0xA820A820
        mask = 0xFFFFFFFF
        regs = code_mask_to_registers(code, mask)
        assert run_match("dual_extended", regs, "ext:0x00000000:0:") == "REJECT"

    def test_filter2_partial_id(self):
        """Dual extended only checks upper 16 bits of (ID<<3), lower bits of ID are ignored."""
        code = 0xA820FFFF
        mask = 0xFFFFFFFF
        regs = code_mask_to_registers(code, mask)
        assert run_match("dual_extended", regs, "ext:0x15041234:0:") == "ACCEPT"
        assert run_match("dual_extended", regs, "ext:0x15045678:0:") == "REJECT"


# =============================================================================
# FILTER SYNTHESIS
# =============================================================================

class TestSingleStandardSynthesize:
    """Test synthesis of SingleStandard filters."""

    def test_single_frame_exact(self):
        """Synthesize from one frame -> exact match."""
        reg_hex = run_synthesize("single_standard", ["std:0x541:0:cafe"])
        assert run_match("single_standard", reg_hex, "std:0x541:0:cafe") == "ACCEPT"
        assert run_match("single_standard", reg_hex, "std:0x540:0:cafe") == "REJECT"
        assert run_match("single_standard", reg_hex, "std:0x541:0:caff") == "REJECT"
        assert run_match("single_standard", reg_hex, "std:0x541:1:") == "REJECT"

    def test_two_frames_id_differ_lsb(self):
        """Two IDs differing in LSB -> wildcard that bit."""
        reg_hex = run_synthesize("single_standard", [
            "std:0x540:0:0000",
            "std:0x541:0:0000"
        ])
        assert run_match("single_standard", reg_hex, "std:0x540:0:0000") == "ACCEPT"
        assert run_match("single_standard", reg_hex, "std:0x541:0:0000") == "ACCEPT"
        assert run_match("single_standard", reg_hex, "std:0x542:0:0000") == "REJECT"

    def test_multiple_frames_rtr_disagree(self):
        """Frames with different RTR -> RTR becomes don't care."""
        reg_hex = run_synthesize("single_standard", [
            "std:0x100:0:0000",
            "std:0x100:1:"
        ])
        assert run_match("single_standard", reg_hex, "std:0x100:0:0000") == "ACCEPT"
        assert run_match("single_standard", reg_hex, "std:0x100:1:") == "ACCEPT"
        assert run_match("single_standard", reg_hex, "std:0x101:0:0000") == "REJECT"

    def test_payload_disagree(self):
        """Different payloads -> payload bits become don't care where they differ."""
        reg_hex = run_synthesize("single_standard", [
            "std:0x100:0:ff00",
            "std:0x100:0:00ff"
        ])
        assert run_match("single_standard", reg_hex, "std:0x100:0:ff00") == "ACCEPT"
        assert run_match("single_standard", reg_hex, "std:0x100:0:00ff") == "ACCEPT"
        assert run_match("single_standard", reg_hex, "std:0x101:0:ff00") == "REJECT"


class TestSingleExtendedSynthesize:
    """Test synthesis of SingleExtended filters."""

    def test_single_frame_exact(self):
        """Single extended frame -> exact match."""
        reg_hex = run_synthesize("single_extended", ["ext:0x1ABCDEF0:1:"])
        assert run_match("single_extended", reg_hex, "ext:0x1ABCDEF0:1:") == "ACCEPT"
        assert run_match("single_extended", reg_hex, "ext:0x1ABCDEF1:1:") == "REJECT"
        assert run_match("single_extended", reg_hex, "ext:0x1ABCDEF0:0:") == "REJECT"

    def test_two_frames_differ(self):
        """Two extended IDs -> wildcard differing bits."""
        reg_hex = run_synthesize("single_extended", [
            "ext:0x10000000:0:",
            "ext:0x10000001:0:"
        ])
        assert run_match("single_extended", reg_hex, "ext:0x10000000:0:") == "ACCEPT"
        assert run_match("single_extended", reg_hex, "ext:0x10000001:0:") == "ACCEPT"
        assert run_match("single_extended", reg_hex, "ext:0x10000002:0:") == "REJECT"


class TestDualStandardSynthesize:
    """Test synthesis of DualStandard filters."""

    def test_two_distinct_ids(self):
        """Two very different IDs -> each assigned to its own filter."""
        reg_hex = run_synthesize("dual_standard", [
            "std:0x100:0:aa",
            "std:0x200:0:bb"
        ])
        assert run_match("dual_standard", reg_hex, "std:0x100:0:aa") == "ACCEPT"
        assert run_match("dual_standard", reg_hex, "std:0x200:0:bb") == "ACCEPT"
        assert run_match("dual_standard", reg_hex, "std:0x300:0:cc") == "REJECT"

    def test_single_frame(self):
        """Single frame -> assigned to filter 1, filter 2 accepts nothing extra if possible."""
        reg_hex = run_synthesize("dual_standard", ["std:0x555:0:de"])
        assert run_match("dual_standard", reg_hex, "std:0x555:0:de") == "ACCEPT"


class TestDualExtendedSynthesize:
    """Test synthesis of DualExtended filters."""

    def test_two_distinct_ids(self):
        """Two extended IDs with different upper bits -> each to its own filter."""
        reg_hex = run_synthesize("dual_extended", [
            "ext:0x10000000:0:",
            "ext:0x08000000:0:"
        ])
        assert run_match("dual_extended", reg_hex, "ext:0x10000000:0:") == "ACCEPT"
        assert run_match("dual_extended", reg_hex, "ext:0x08000000:0:") == "ACCEPT"
        assert run_match("dual_extended", reg_hex, "ext:0x00000000:0:") == "REJECT"


# =============================================================================
# EDGE CASES AND INTEGRATION
# =============================================================================

class TestEdgeCases:
    """Edge cases and integration tests."""

    def test_all_accept_single_standard(self):
        """Register mask all 0xFF -> accept everything."""
        assert run_match("single_standard", "00000000ffffffff", "std:0x7ff:1:ffff") == "ACCEPT"
        assert run_match("single_standard", "00000000ffffffff", "std:0x000:0:0000") == "ACCEPT"

    def test_all_accept_single_extended(self):
        """Register mask all 0xFF -> accept everything."""
        assert run_match("single_extended", "00000000ffffffff", "ext:0x1FFFFFFF:1:") == "ACCEPT"

    def test_max_standard_id(self):
        """Maximum standard ID 0x7FF."""
        code = 0x7FF << 21
        mask = 0xFFE00000
        regs = code_mask_to_registers(code, mask)
        assert run_match("single_standard", regs, "std:0x7ff:0:") == "ACCEPT"
        assert run_match("single_standard", regs, "std:0x7fe:0:") == "REJECT"

    def test_synthesize_then_match_roundtrip(self):
        """Synthesize a filter and verify all input frames pass, plus a control frame fails."""
        frames = [
            "std:0x100:0:aabb",
            "std:0x100:0:aacc",
            "std:0x100:0:aadd",
        ]
        reg_hex = run_synthesize("single_standard", frames)
        for f in frames:
            assert run_match("single_standard", reg_hex, f) == "ACCEPT"
        assert run_match("single_standard", reg_hex, "std:0x100:0:bbcc") == "REJECT"

    def test_synthesize_extended_roundtrip(self):
        """Synthesize extended filter roundtrip."""
        frames = [
            "ext:0x1ABC0000:0:",
            "ext:0x1ABC0001:0:",
            "ext:0x1ABC0002:0:",
            "ext:0x1ABC0003:0:",
        ]
        reg_hex = run_synthesize("single_extended", frames)
        for f in frames:
            assert run_match("single_extended", reg_hex, f) == "ACCEPT"
        assert run_match("single_extended", reg_hex, "ext:0x1ABC0004:0:") == "REJECT"

    def test_dual_standard_split_payload_roundtrip(self):
        """Synthesize dual standard with payload and verify split-nibble layout."""
        frames = [
            "std:0x100:0:ab",
            "std:0x200:0:cd",
        ]
        reg_hex = run_synthesize("dual_standard", frames)
        for f in frames:
            assert run_match("dual_standard", reg_hex, f) == "ACCEPT"
        assert run_match("dual_standard", reg_hex, "std:0x300:0:ef") == "REJECT"

    def test_synthesis_tightness_single_standard(self):
        """Verify synthesis produces the tightest filter (fewest don't-care bits)."""
        reg_hex = run_synthesize("single_standard", [
            "std:0x100:0:aa00",
            "std:0x101:0:aa00"
        ])
        assert run_match("single_standard", reg_hex, "std:0x100:0:aa00") == "ACCEPT"
        assert run_match("single_standard", reg_hex, "std:0x101:0:aa00") == "ACCEPT"
        assert run_match("single_standard", reg_hex, "std:0x102:0:aa00") == "REJECT"
        assert run_match("single_standard", reg_hex, "std:0x100:0:ab00") == "REJECT"


# =============================================================================
# BINARY REGISTER DUMP PARSING
# =============================================================================

class TestParseDump:
    """Test parse-dump command for binary register dump files."""

    def test_parse_dump_entry_count(self):
        """Parse the reference register dump file and verify entry count."""
        data = run_parse_dump("/app/reference/register_configs.bin")
        assert isinstance(data, list)
        assert len(data) == 6

    def test_parse_dump_modes(self):
        """Verify each entry has the correct mode."""
        data = run_parse_dump("/app/reference/register_configs.bin")
        expected_modes = [
            "single_standard", "single_extended", "dual_standard",
            "dual_extended", "single_standard", "single_extended"
        ]
        for i, mode in enumerate(expected_modes):
            assert data[i]["mode"] == mode, f"Entry {i}: expected {mode}, got {data[i]['mode']}"

    def test_parse_dump_reg_hex_values(self):
        """Verify register hex values are correct and lowercase."""
        data = run_parse_dump("/app/reference/register_configs.bin")
        assert data[0]["reg_hex"] == "a8200000001fffff"
        assert data[1]["reg_hex"] == "d5e6f78400000003"
        assert data[2]["reg_hex"] == "20004000001f001f"
        assert data[3]["reg_hex"] == "a820504000000000"
        assert data[4]["reg_hex"] == "fff0dead00000000"
        assert data[5]["reg_hex"] == "00000000ffffffff"

    def test_parse_dump_labels(self):
        """Verify labels are correctly extracted."""
        data = run_parse_dump("/app/reference/register_configs.bin")
        expected_labels = [
            "ecu_engine", "chassis_sensor", "body_controller",
            "brake_monitor", "diag_request", "promiscuous"
        ]
        for i, label in enumerate(expected_labels):
            assert data[i]["label"] == label, f"Entry {i}: expected {label}, got {data[i]['label']}"

    def test_parse_dump_json_structure(self):
        """Verify each entry has exactly the required fields."""
        data = run_parse_dump("/app/reference/register_configs.bin")
        for i, entry in enumerate(data):
            assert set(entry.keys()) == {"mode", "reg_hex", "label"}, \
                f"Entry {i}: unexpected keys {entry.keys()}"

    def test_parse_dump_cross_validate_ecu_engine(self):
        """Use parsed ecu_engine config (single_standard, ID 0x541) to match frames."""
        data = run_parse_dump("/app/reference/register_configs.bin")
        e = data[0]
        assert e["label"] == "ecu_engine"
        assert run_match(e["mode"], e["reg_hex"], "std:0x541:0:aabb") == "ACCEPT"
        assert run_match(e["mode"], e["reg_hex"], "std:0x541:1:ffff") == "ACCEPT"
        assert run_match(e["mode"], e["reg_hex"], "std:0x540:0:aabb") == "REJECT"

    def test_parse_dump_cross_validate_diag_request(self):
        """Use parsed diag_request config (exact match) to match frames."""
        data = run_parse_dump("/app/reference/register_configs.bin")
        e = data[4]
        assert e["label"] == "diag_request"
        assert run_match(e["mode"], e["reg_hex"], "std:0x7ff:1:dead") == "ACCEPT"
        assert run_match(e["mode"], e["reg_hex"], "std:0x7ff:0:dead") == "REJECT"
        assert run_match(e["mode"], e["reg_hex"], "std:0x7ff:1:deaf") == "REJECT"

    def test_parse_dump_cross_validate_promiscuous(self):
        """Promiscuous filter (all don't-care) should accept any frame."""
        data = run_parse_dump("/app/reference/register_configs.bin")
        e = data[5]
        assert e["label"] == "promiscuous"
        assert run_match(e["mode"], e["reg_hex"], "ext:0x1FFFFFFF:1:deadbeef") == "ACCEPT"
        assert run_match(e["mode"], e["reg_hex"], "ext:0x00000000:0:") == "ACCEPT"

    def test_parse_dump_cross_validate_chassis_sensor(self):
        """Use parsed chassis_sensor config (single_extended) to verify match behavior."""
        data = run_parse_dump("/app/reference/register_configs.bin")
        e = data[1]
        assert e["label"] == "chassis_sensor"
        # This config has ID=0x1ABCDEF0, RTR=1 with care on all ID bits + RTR
        assert run_match(e["mode"], e["reg_hex"], "ext:0x1ABCDEF0:1:") == "ACCEPT"
        assert run_match(e["mode"], e["reg_hex"], "ext:0x1ABCDEF0:0:") == "REJECT"
        assert run_match(e["mode"], e["reg_hex"], "ext:0x1ABCDEF1:1:") == "REJECT"

    def test_parse_dump_cross_validate_body_controller(self):
        """Use parsed body_controller config (dual_standard) to verify dual filter."""
        data = run_parse_dump("/app/reference/register_configs.bin")
        e = data[2]
        assert e["label"] == "body_controller"
        # Dual standard: filter1 ID=0x100, filter2 ID=0x200
        assert run_match(e["mode"], e["reg_hex"], "std:0x100:0:") == "ACCEPT"
        assert run_match(e["mode"], e["reg_hex"], "std:0x200:0:") == "ACCEPT"
        assert run_match(e["mode"], e["reg_hex"], "std:0x300:0:") == "REJECT"
