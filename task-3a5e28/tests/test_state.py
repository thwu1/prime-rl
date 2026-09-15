
import os
import json
import struct
import re
import subprocess

import pytest


EXPECTED_LINES = [
    "1.000000 INFO System initialized, clk=72000000Hz",
    "1.500000 DEBUG ADC ch3=2048",
    "2.000000 WARN temp=-23dC exceeds limit",
    "2.500000 ERROR fault @ 0x0800dead",
    "3.000000 INFO firmware v2.5.1",
    "3.500000 INFO payload [de, ad, be, ef]",
    "4.000000 DEBUG tag=SENSOR_A, seq=42",
    "4.500000 INFO state=Running(1024)",
    "5.000000 INFO state=Idle",
    '5.500000 INFO buf=b"Hello\\x00"',
    "6.000000 INFO delta=-1000 f=1.5",
    "6.500000 INFO ok=true ch=Z",
    "7.000000 INFO InitReady(5)Error(404)",
    "7.500000 INFO i16_hex=0xffff",
    "8.000000 INFO sensor=S { val: 2a, raw: 100 }",
]

EXPECTED_ANALYSIS = {
    "correct_firmware": "fw_alpha.elf",
    "total_frames": 18,
    "valid_frames": 15,
    "corrupt_frame_indices": [4, 10, 14],
}


def _read_output():
    with open("/app/output.txt") as f:
        return [l.rstrip("\n") for l in f.readlines() if l.strip()]


def _read_analysis():
    with open("/app/analysis.json") as f:
        return json.load(f)


# ============================================================
# Output existence and line count
# ============================================================


class TestOutputExists:
    def test_output_file_exists(self):
        assert os.path.isfile("/app/output.txt"), "output.txt not found"

    def test_analysis_file_exists(self):
        assert os.path.isfile("/app/analysis.json"), "analysis.json not found"


class TestLineCount:
    def test_output_line_count(self):
        lines = _read_output()
        assert len(lines) == 15, f"Expected 15 lines, got {len(lines)}"


# ============================================================
# Full line-by-line match
# ============================================================


class TestFullMatch:
    @pytest.mark.parametrize("line_idx", range(15))
    def test_line_matches(self, line_idx):
        lines = _read_output()
        assert len(lines) > line_idx, f"Not enough lines (got {len(lines)})"
        actual = lines[line_idx]
        expected = EXPECTED_LINES[line_idx]
        assert actual == expected, (
            f"Line {line_idx + 1} mismatch:\n"
            f"  Expected: {expected!r}\n"
            f"  Actual:   {actual!r}"
        )


# ============================================================
# Analysis JSON correctness
# ============================================================


class TestAnalysis:
    def test_correct_firmware(self):
        analysis = _read_analysis()
        assert analysis["correct_firmware"] == EXPECTED_ANALYSIS["correct_firmware"], (
            f"Expected firmware '{EXPECTED_ANALYSIS['correct_firmware']}', "
            f"got '{analysis.get('correct_firmware')}'"
        )

    def test_total_frames(self):
        analysis = _read_analysis()
        assert analysis["total_frames"] == EXPECTED_ANALYSIS["total_frames"], (
            f"Expected {EXPECTED_ANALYSIS['total_frames']} total frames, "
            f"got {analysis.get('total_frames')}"
        )

    def test_valid_frames(self):
        analysis = _read_analysis()
        assert analysis["valid_frames"] == EXPECTED_ANALYSIS["valid_frames"], (
            f"Expected {EXPECTED_ANALYSIS['valid_frames']} valid frames, "
            f"got {analysis.get('valid_frames')}"
        )

    def test_corrupt_frame_indices(self):
        analysis = _read_analysis()
        assert sorted(analysis["corrupt_frame_indices"]) == EXPECTED_ANALYSIS["corrupt_frame_indices"], (
            f"Expected corrupt indices {EXPECTED_ANALYSIS['corrupt_frame_indices']}, "
            f"got {sorted(analysis.get('corrupt_frame_indices', []))}"
        )


# ============================================================
# Timestamp and log level format
# ============================================================


class TestTimestampFormat:
    def test_timestamps_are_microsecond_format(self):
        lines = _read_output()
        for i, line in enumerate(lines):
            ts = line.split(" ")[0]
            assert re.match(r"^\d+\.\d{6}$", ts), (
                f"Line {i + 1}: timestamp '{ts}' not in N.NNNNNN format"
            )


class TestLogLevels:
    def test_valid_log_levels(self):
        lines = _read_output()
        valid_levels = {"TRACE", "DEBUG", "INFO", "WARN", "ERROR"}
        for i, line in enumerate(lines):
            parts = line.split(" ", 2)
            assert len(parts) >= 2, f"Line {i + 1}: cannot parse level"
            assert parts[1] in valid_levels, (
                f"Line {i + 1}: invalid level '{parts[1]}'"
            )


# ============================================================
# Specific feature tests
# ============================================================


class TestInternedString:
    def test_istr_sensor_a(self):
        lines = _read_output()
        assert "tag=SENSOR_A" in lines[6], f"Line 7: {lines[6]}"


class TestFormatSequence:
    def test_format_sequence_output(self):
        lines = _read_output()
        assert "InitReady(5)Error(404)" in lines[12], f"Line 13: {lines[12]}"


class TestSignedHexFormatting:
    def test_i16_neg1_hex(self):
        lines = _read_output()
        assert "0xffff" in lines[13], (
            f"Line 14: expected '0xffff' (two's complement), got: {lines[13]}"
        )

    def test_no_negative_sign_in_hex(self):
        lines = _read_output()
        assert "-0x" not in lines[13], (
            f"Line 14: signed hex should use two's complement, not '-0x' prefix"
        )


class TestDisplayHintPropagation:
    def test_nested_hex_propagation(self):
        lines = _read_output()
        assert "val: 2a" in lines[14], (
            f"Line 15: :? hint should propagate outer :x to inner u8, got: {lines[14]}"
        )
        assert "raw: 100" in lines[14], (
            f"Line 15: :? hint should propagate outer :x to inner u16, got: {lines[14]}"
        )


class TestHexFormatting:
    def test_alternate_hex_with_padding(self):
        lines = _read_output()
        assert "0x0800dead" in lines[3], f"Line 4: {lines[3]}"


class TestNestedFormat:
    def test_nested_format_with_args(self):
        lines = _read_output()
        assert "state=Running(1024)" in lines[7], f"Line 8: {lines[7]}"

    def test_nested_format_no_args(self):
        lines = _read_output()
        assert "state=Idle" in lines[8], f"Line 9: {lines[8]}"


class TestAsciiDisplay:
    def test_ascii_byte_string_escaping(self):
        lines = _read_output()
        assert 'b"Hello\\x00"' in lines[9], f"Line 10: {lines[9]}"


class TestByteSliceHex:
    def test_hex_formatted_byte_slice(self):
        lines = _read_output()
        assert "[de, ad, be, ef]" in lines[5], f"Line 6: {lines[5]}"


class TestSignedIntegers:
    def test_negative_i16(self):
        lines = _read_output()
        assert "temp=-23dC" in lines[2], f"Line 3: {lines[2]}"

    def test_negative_i32(self):
        lines = _read_output()
        assert "delta=-1000" in lines[10], f"Line 11: {lines[10]}"


class TestFloatFormatting:
    def test_f32_value(self):
        lines = _read_output()
        assert "f=1.5" in lines[10], f"Line 11: {lines[10]}"


class TestBoolAndChar:
    def test_bool_true(self):
        lines = _read_output()
        assert "ok=true" in lines[11], f"Line 12: {lines[11]}"

    def test_char_value(self):
        lines = _read_output()
        assert "ch=Z" in lines[11], f"Line 12: {lines[11]}"


# ============================================================
# ELF and binary helpers for dynamic anti-cheat tests
# ============================================================


def _serialize_table(table):
    """Serialize a string table to .defmt binary section format."""
    buf = bytearray()
    buf.extend(b'dFmT')
    buf.append(4)
    encoding = 0 if table.get("encoding", "raw") == "raw" else 1
    buf.append(encoding)
    has_ts = 1 if "timestamp" in table else 0
    buf.append(has_ts)
    buf.append(0)
    entries = table.get("entries", {})
    buf.extend(struct.pack('<H', len(entries)))
    buf.extend(b'\x00\x00')

    if has_ts:
        ts = table["timestamp"]
        ts_tag = ts["tag"].encode('utf-8')
        ts_fmt = ts["string"].encode('utf-8')
        buf.append(len(ts_tag))
        buf.extend(ts_tag)
        buf.extend(struct.pack('<H', len(ts_fmt)))
        buf.extend(ts_fmt)

    for idx_str in sorted(entries.keys(), key=lambda x: int(x)):
        entry = entries[idx_str]
        idx = int(idx_str)
        tag = entry["tag"].encode('utf-8')
        fmt = entry["string"].encode('utf-8')
        buf.extend(struct.pack('<H', idx))
        buf.append(len(tag))
        buf.extend(tag)
        buf.extend(struct.pack('<H', len(fmt)))
        buf.extend(fmt)

    return bytes(buf)


def _create_elf(section_data, output_path):
    """Create a minimal ELF64 relocatable file with a .defmt section."""
    elf = bytearray()

    ehdr_size = 64
    defmt_offset = ehdr_size
    defmt_size = len(section_data)
    shstrtab_content = b'\x00.defmt\x00.shstrtab\x00'
    shstrtab_offset = defmt_offset + defmt_size
    shstrtab_size = len(shstrtab_content)

    raw_shdr_offset = shstrtab_offset + shstrtab_size
    shdr_offset = (raw_shdr_offset + 7) & ~7
    shdr_padding = shdr_offset - raw_shdr_offset

    elf.extend(b'\x7fELF')
    elf.append(2)
    elf.append(1)
    elf.append(1)
    elf.extend(b'\x00' * 9)
    elf.extend(struct.pack('<H', 1))
    elf.extend(struct.pack('<H', 62))
    elf.extend(struct.pack('<I', 1))
    elf.extend(struct.pack('<Q', 0))
    elf.extend(struct.pack('<Q', 0))
    elf.extend(struct.pack('<Q', shdr_offset))
    elf.extend(struct.pack('<I', 0))
    elf.extend(struct.pack('<H', 64))
    elf.extend(struct.pack('<H', 0))
    elf.extend(struct.pack('<H', 0))
    elf.extend(struct.pack('<H', 64))
    elf.extend(struct.pack('<H', 3))
    elf.extend(struct.pack('<H', 2))

    elf.extend(section_data)
    elf.extend(shstrtab_content)
    elf.extend(b'\x00' * shdr_padding)
    elf.extend(b'\x00' * 64)

    elf.extend(struct.pack('<I', 1))
    elf.extend(struct.pack('<I', 1))
    elf.extend(struct.pack('<Q', 2))
    elf.extend(struct.pack('<Q', 0))
    elf.extend(struct.pack('<Q', defmt_offset))
    elf.extend(struct.pack('<Q', defmt_size))
    elf.extend(struct.pack('<I', 0))
    elf.extend(struct.pack('<I', 0))
    elf.extend(struct.pack('<Q', 1))
    elf.extend(struct.pack('<Q', 0))

    elf.extend(struct.pack('<I', 8))
    elf.extend(struct.pack('<I', 3))
    elf.extend(struct.pack('<Q', 0))
    elf.extend(struct.pack('<Q', 0))
    elf.extend(struct.pack('<Q', shstrtab_offset))
    elf.extend(struct.pack('<Q', shstrtab_size))
    elf.extend(struct.pack('<I', 0))
    elf.extend(struct.pack('<I', 0))
    elf.extend(struct.pack('<Q', 1))
    elf.extend(struct.pack('<Q', 0))

    with open(output_path, 'wb') as f:
        f.write(bytes(elf))


def _crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


def _cobs_encode(data):
    output = bytearray()
    code_idx = len(output)
    output.append(0)
    code = 1
    for byte in data:
        if byte == 0:
            output[code_idx] = code
            code_idx = len(output)
            output.append(0)
            code = 1
        else:
            output.append(byte)
            code += 1
            if code == 0xFF:
                output[code_idx] = code
                code_idx = len(output)
                output.append(0)
                code = 1
    output[code_idx] = code
    return bytes(output)


def _make_capture(raw_frames):
    """Build a COBS-framed capture from raw defmt frames."""
    capture = bytearray()
    for frame_data in raw_frames:
        crc = _crc16(frame_data)
        full = frame_data + struct.pack("<H", crc)
        encoded = _cobs_encode(full)
        capture.extend(encoded)
        capture.append(0x00)
    return bytes(capture)


# ============================================================
# Dynamic decode tests (anti-cheat)
# ============================================================


class TestDynamicDecode:
    """Verify the decoder processes actual ELF and binary data by creating
    fresh firmware ELF files and COBS-framed captures at test time."""

    def _save_originals(self):
        orig = {}
        for path in ["/app/capture.bin", "/app/output.txt", "/app/analysis.json"]:
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    orig[path] = f.read()
        orig_fw = {}
        for name in os.listdir("/app/firmware"):
            p = f"/app/firmware/{name}"
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    orig_fw[name] = f.read()
        return orig, orig_fw

    def _restore_originals(self, orig, orig_fw):
        for path, data in orig.items():
            with open(path, "wb") as f:
                f.write(data)
        for name, data in orig_fw.items():
            with open(f"/app/firmware/{name}", "wb") as f:
                f.write(data)
        for path in ["/app/output.txt", "/app/analysis.json"]:
            if path not in orig and os.path.isfile(path):
                os.remove(path)

    def test_dynamic_basic(self):
        """Create a fresh ELF + capture with simple frames and verify decoding."""
        test_table = {
            "encoding": "raw",
            "timestamp": {"tag": "Timestamp", "string": "{=u32:us}"},
            "entries": {
                "0": {"tag": "Info", "string": "dyn_val={=u16}"}
            }
        }
        raw_frame = (
            struct.pack("<H", 0) +
            struct.pack("<I", 5000000) +
            struct.pack("<H", 12345)
        )
        test_capture = _make_capture([raw_frame])

        orig, orig_fw = self._save_originals()
        try:
            with open("/app/capture.bin", "wb") as f:
                f.write(test_capture)
            section_data = _serialize_table(test_table)
            for name in ["fw_alpha.elf", "fw_beta.elf", "fw_gamma.elf"]:
                _create_elf(section_data, f"/app/firmware/{name}")

            result = subprocess.run(
                ["python3", "/app/decoder.py"],
                capture_output=True, text=True, timeout=30, cwd="/app"
            )
            assert result.returncode == 0, f"Decoder failed: {result.stderr}"
            assert os.path.isfile("/app/output.txt"), "No output.txt after dynamic decode"

            with open("/app/output.txt") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            assert len(lines) == 1, f"Expected 1 line, got {len(lines)}"
            assert lines[0] == "5.000000 INFO dyn_val=12345", (
                f"Dynamic basic mismatch: {lines[0]!r}"
            )
        finally:
            self._restore_originals(orig, orig_fw)

    def test_dynamic_corrupt_detection(self):
        """Test that corrupt frames are correctly identified and skipped."""
        test_table = {
            "encoding": "raw",
            "timestamp": {"tag": "Timestamp", "string": "{=u32:us}"},
            "entries": {
                "0": {"tag": "Info", "string": "x={=u8}"}
            }
        }

        raw1 = struct.pack("<H", 0) + struct.pack("<I", 1000000) + struct.pack("<B", 10)
        raw2 = struct.pack("<H", 0) + struct.pack("<I", 3000000) + struct.pack("<B", 30)

        raw_corrupt = struct.pack("<H", 0) + struct.pack("<I", 2000000) + struct.pack("<B", 20)
        crc = _crc16(raw_corrupt)
        corrupted = bytearray(raw_corrupt)
        corrupted[3] ^= 0xFF
        corrupt_full = bytes(corrupted) + struct.pack("<H", crc)
        corrupt_cobs = _cobs_encode(corrupt_full)

        capture = bytearray()
        for raw in [raw1]:
            crc_val = _crc16(raw)
            full = raw + struct.pack("<H", crc_val)
            capture.extend(_cobs_encode(full))
            capture.append(0x00)
        capture.extend(corrupt_cobs)
        capture.append(0x00)
        for raw in [raw2]:
            crc_val = _crc16(raw)
            full = raw + struct.pack("<H", crc_val)
            capture.extend(_cobs_encode(full))
            capture.append(0x00)

        orig, orig_fw = self._save_originals()
        try:
            with open("/app/capture.bin", "wb") as f:
                f.write(bytes(capture))
            section_data = _serialize_table(test_table)
            for name in ["fw_alpha.elf", "fw_beta.elf", "fw_gamma.elf"]:
                _create_elf(section_data, f"/app/firmware/{name}")

            result = subprocess.run(
                ["python3", "/app/decoder.py"],
                capture_output=True, text=True, timeout=30, cwd="/app"
            )
            assert result.returncode == 0, f"Decoder failed: {result.stderr}"

            with open("/app/output.txt") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            assert len(lines) == 2, (
                f"Expected 2 lines (corrupt skipped), got {len(lines)}"
            )

            with open("/app/analysis.json") as f:
                analysis = json.load(f)
            assert analysis["total_frames"] == 3
            assert analysis["valid_frames"] == 2
            assert 1 in analysis["corrupt_frame_indices"]
        finally:
            self._restore_originals(orig, orig_fw)

    def test_dynamic_istr(self):
        """Test decoder handles interned strings from fresh ELF data."""
        test_table = {
            "encoding": "raw",
            "timestamp": {"tag": "Timestamp", "string": "{=u32:us}"},
            "entries": {
                "0": {"tag": "Info", "string": "name={=istr}"},
                "1": {"tag": "Str", "string": "DYN_TEST_STR"}
            }
        }
        raw_frame = (
            struct.pack("<H", 0) +
            struct.pack("<I", 3000000) +
            struct.pack("<H", 1)
        )
        test_capture = _make_capture([raw_frame])

        orig, orig_fw = self._save_originals()
        try:
            with open("/app/capture.bin", "wb") as f:
                f.write(test_capture)
            section_data = _serialize_table(test_table)
            for name in ["fw_alpha.elf", "fw_beta.elf", "fw_gamma.elf"]:
                _create_elf(section_data, f"/app/firmware/{name}")

            result = subprocess.run(
                ["python3", "/app/decoder.py"],
                capture_output=True, text=True, timeout=30, cwd="/app"
            )
            assert result.returncode == 0, f"Decoder failed: {result.stderr}"

            with open("/app/output.txt") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
            assert len(lines) == 1
            assert lines[0] == "3.000000 INFO name=DYN_TEST_STR", (
                f"Dynamic istr mismatch: {lines[0]!r}"
            )
        finally:
            self._restore_originals(orig, orig_fw)
