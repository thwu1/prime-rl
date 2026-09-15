"""
Verification tests for miniSEED v3 record produced by mseed3pack.

Tests independently parse the binary header, validate CRC-32C, decode
the Steim2 payload, and compare against expected sample values.

"""

import os
import re
import struct
import pytest

OUTPUT_FILE = "/app/output.mseed3"
SINEDATA_FILE = "/app/sinedata.h"
NUM_SAMPLES = 400
EXPECTED_SID = b"FDSN:XX_TEST_00_B_H_Z"
EXPECTED_ENCODING = 11  # Steim2
EXPECTED_SAMPLE_RATE = 40.0
EXPECTED_YEAR = 2024
EXPECTED_DAY = 1


# ======================================================================
# Reference CRC-32C (Castagnoli) implementation
# ======================================================================
def crc32c(data: bytes) -> int:
    """Compute CRC-32C using Castagnoli polynomial 0x82F63B78."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x82F63B78
            else:
                crc >>= 1
    return crc ^ 0xFFFFFFFF


# ======================================================================
# Reference Steim2 decoder
# ======================================================================
def _sign_extend(value, bits):
    """Sign-extend an unsigned value of given bit width."""
    sign_bit = 1 << (bits - 1)
    if value >= sign_bit:
        value -= (1 << bits)
    return value


def decode_steim2(payload: bytes, expected_samples: int) -> list:
    """Decode Steim2-encoded payload into a list of int32 samples."""
    num_frames = len(payload) // 64
    if num_frames == 0:
        return []

    samples = []

    for frame_idx in range(num_frames):
        frame_bytes = payload[frame_idx * 64:(frame_idx + 1) * 64]
        frame = list(struct.unpack('<16I', frame_bytes))

        diffs = []

        if frame_idx == 0:
            # Word 1 = X0 (forward integration constant)
            x0 = struct.unpack('<i', struct.pack('<I', frame[1]))[0]
            # Word 2 = Xn (reverse integration constant, checked later)
            samples.append(x0)
            start_word = 3
        else:
            start_word = 1

        nibble_word = frame[0]

        for widx in range(start_word, 16):
            nibble = (nibble_word >> (30 - 2 * widx)) & 0x3
            word = frame[widx]

            if nibble == 0:
                # Special / no data
                pass

            elif nibble == 1:
                # 4 x 8-bit differences (byte-level)
                word_bytes = struct.pack('<I', word)
                for b in word_bytes:
                    diffs.append(_sign_extend(b, 8))

            elif nibble == 2:
                # Consult dnib (top 2 bits of word)
                dnib = (word >> 30) & 0x3

                if dnib == 1:
                    # 1 x 30-bit difference
                    val = word & 0x3FFFFFFF
                    diffs.append(_sign_extend(val, 30))

                elif dnib == 2:
                    # 2 x 15-bit differences
                    for i in range(2):
                        val = (word >> (15 - i * 15)) & 0x7FFF
                        diffs.append(_sign_extend(val, 15))

                elif dnib == 3:
                    # 3 x 10-bit differences
                    for i in range(3):
                        val = (word >> (20 - i * 10)) & 0x3FF
                        diffs.append(_sign_extend(val, 10))

                else:
                    raise ValueError(f"Invalid dnib={dnib} for nibble=10")

            elif nibble == 3:
                # Consult dnib
                dnib = (word >> 30) & 0x3

                if dnib == 0:
                    # 5 x 6-bit differences
                    for i in range(5):
                        val = (word >> (24 - i * 6)) & 0x3F
                        diffs.append(_sign_extend(val, 6))

                elif dnib == 1:
                    # 6 x 5-bit differences
                    for i in range(6):
                        val = (word >> (25 - i * 5)) & 0x1F
                        diffs.append(_sign_extend(val, 5))

                elif dnib == 2:
                    # 7 x 4-bit differences
                    for i in range(7):
                        val = (word >> (24 - i * 4)) & 0xF
                        diffs.append(_sign_extend(val, 4))

                else:
                    raise ValueError(f"Invalid dnib={dnib} for nibble=11")

        # Apply differences via integration
        if frame_idx == 0:
            # Skip first difference (inter-record diff0)
            start_diff = 1
        else:
            start_diff = 0

        for i in range(start_diff, len(diffs)):
            if len(samples) >= expected_samples:
                break
            samples.append(samples[-1] + diffs[i])

    return samples[:expected_samples]


# ======================================================================
# Load expected sample values from sinedata.h
# ======================================================================
def load_expected_samples():
    """Parse the double array from sinedata.h and truncate to int32."""
    with open(SINEDATA_FILE, 'r') as f:
        content = f.read()

    # Extract all numbers from the dsinedata array initializer
    match = re.search(r'dsinedata\[.*?\]\s*=\s*\{(.*?)\}', content, re.DOTALL)
    assert match is not None, "Could not find dsinedata array in sinedata.h"

    numbers = re.findall(r'-?\d+\.?\d*', match.group(1))
    doubles = [float(x) for x in numbers]

    # Truncate to int32 (matching C's (int32_t) cast = truncation toward zero)
    return [int(x) for x in doubles[:NUM_SAMPLES]]


# ======================================================================
# Fixtures
# ======================================================================
@pytest.fixture
def record_data():
    """Read the output miniSEED v3 record."""
    assert os.path.exists(OUTPUT_FILE), f"Output file {OUTPUT_FILE} does not exist"
    with open(OUTPUT_FILE, 'rb') as f:
        data = f.read()
    assert len(data) > 40, f"Output file too small: {len(data)} bytes"
    return data


@pytest.fixture
def expected_samples():
    """Load expected integer sample values."""
    return load_expected_samples()


# ======================================================================
# Tests
# ======================================================================
class TestHeader:
    """Verify miniSEED v3 fixed header fields."""

    def test_indicator(self, record_data):
        indicator = record_data[0:2]
        assert indicator == b'MS', f"Expected indicator 'MS', got {indicator!r}"

    def test_version(self, record_data):
        version = record_data[2]
        assert version == 3, f"Expected format version 3, got {version}"

    def test_encoding(self, record_data):
        encoding = record_data[15]
        assert encoding == EXPECTED_ENCODING, \
            f"Expected encoding={EXPECTED_ENCODING} (Steim2), got {encoding}"

    def test_year(self, record_data):
        year = struct.unpack_from('<H', record_data, 8)[0]
        assert year == EXPECTED_YEAR, f"Expected year={EXPECTED_YEAR}, got {year}"

    def test_day(self, record_data):
        day = struct.unpack_from('<H', record_data, 10)[0]
        assert day == EXPECTED_DAY, f"Expected day={EXPECTED_DAY}, got {day}"

    def test_sample_rate(self, record_data):
        rate = struct.unpack_from('<d', record_data, 16)[0]
        assert abs(rate - EXPECTED_SAMPLE_RATE) < 1e-9, \
            f"Expected sample rate={EXPECTED_SAMPLE_RATE}, got {rate}"

    def test_sample_count(self, record_data):
        count = struct.unpack_from('<I', record_data, 24)[0]
        assert count == NUM_SAMPLES, \
            f"Expected {NUM_SAMPLES} samples in header, got {count}"

    def test_sid(self, record_data):
        sid_len = record_data[33]
        assert sid_len == len(EXPECTED_SID), \
            f"Expected SID length {len(EXPECTED_SID)}, got {sid_len}"
        sid = record_data[40:40 + sid_len]
        assert sid == EXPECTED_SID, \
            f"Expected SID {EXPECTED_SID!r}, got {sid!r}"

    def test_record_size_consistent(self, record_data):
        sid_len = record_data[33]
        extra_len = struct.unpack_from('<H', record_data, 34)[0]
        data_len = struct.unpack_from('<I', record_data, 36)[0]
        expected_total = 40 + sid_len + extra_len + data_len
        assert len(record_data) == expected_total, \
            f"Record size {len(record_data)} != expected {expected_total}"


class TestCRC:
    """Verify CRC-32C integrity."""

    def test_crc_valid(self, record_data):
        stored_crc = struct.unpack_from('<I', record_data, 28)[0]
        assert stored_crc != 0, \
            "CRC field is zero; compute_crc32c appears unimplemented"
        # Zero the CRC field for computation
        modified = bytearray(record_data)
        modified[28:32] = b'\x00\x00\x00\x00'
        computed = crc32c(bytes(modified))
        assert stored_crc == computed, \
            f"CRC mismatch: stored=0x{stored_crc:08X}, computed=0x{computed:08X}"


class TestSteim2:
    """Verify Steim2 payload decodes correctly."""

    def _get_payload(self, record_data):
        sid_len = record_data[33]
        extra_len = struct.unpack_from('<H', record_data, 34)[0]
        data_len = struct.unpack_from('<I', record_data, 36)[0]
        data_offset = 40 + sid_len + extra_len
        return record_data[data_offset:data_offset + data_len]

    def test_payload_size(self, record_data):
        payload = self._get_payload(record_data)
        assert len(payload) > 0, "Empty data payload"
        assert len(payload) % 64 == 0, \
            f"Payload size {len(payload)} not a multiple of 64 bytes"

    def test_sample_count(self, record_data):
        payload = self._get_payload(record_data)
        decoded = decode_steim2(payload, NUM_SAMPLES)
        assert len(decoded) == NUM_SAMPLES, \
            f"Decoded {len(decoded)} samples, expected {NUM_SAMPLES}"

    def test_sample_values(self, record_data, expected_samples):
        payload = self._get_payload(record_data)
        decoded = decode_steim2(payload, NUM_SAMPLES)
        mismatches = []
        for i in range(min(len(decoded), NUM_SAMPLES)):
            if decoded[i] != expected_samples[i]:
                mismatches.append(
                    f"Sample[{i}]: decoded={decoded[i]}, expected={expected_samples[i]}"
                )
                if len(mismatches) >= 5:
                    break
        assert not mismatches, \
            f"Sample value mismatches (first {len(mismatches)}):\n" + \
            "\n".join(mismatches)

    def test_xn_check(self, record_data, expected_samples):
        """Verify reverse integration constant matches last sample."""
        payload = self._get_payload(record_data)
        # Xn is stored at word 2 of frame 0 (offset 8 bytes into payload)
        xn = struct.unpack_from('<i', payload, 8)[0]
        decoded = decode_steim2(payload, NUM_SAMPLES)
        last_sample = decoded[-1]
        assert xn == last_sample, \
            f"Xn={xn} != last decoded sample={last_sample}"
        assert xn == expected_samples[-1], \
            f"Xn={xn} != expected last sample={expected_samples[-1]}"

    def test_x0_check(self, record_data, expected_samples):
        """Verify forward integration constant matches first sample."""
        payload = self._get_payload(record_data)
        # X0 is stored at word 1 of frame 0 (offset 4 bytes into payload)
        x0 = struct.unpack_from('<i', payload, 4)[0]
        assert x0 == expected_samples[0], \
            f"X0={x0} != expected first sample={expected_samples[0]}"

    def test_packing_modes_used(self, record_data):
        """Verify all 7 Steim2 packing modes are present in the output.

        The expanding-sinusoid test data produces differences spanning
        all bit-width ranges, so a correct encoder must use every mode.
        """
        payload = self._get_payload(record_data)
        num_frames = len(payload) // 64

        observed_modes = set()
        for frame_idx in range(num_frames):
            frame = struct.unpack_from('<16I', payload, frame_idx * 64)
            nibble_word = frame[0]
            start_word = 3 if frame_idx == 0 else 1

            for widx in range(start_word, 16):
                nibble = (nibble_word >> (30 - 2 * widx)) & 0x3
                if nibble == 0:
                    continue
                elif nibble == 1:
                    observed_modes.add("4x8")
                elif nibble == 2:
                    dnib = (frame[widx] >> 30) & 0x3
                    if dnib == 1:
                        observed_modes.add("1x30")
                    elif dnib == 2:
                        observed_modes.add("2x15")
                    elif dnib == 3:
                        observed_modes.add("3x10")
                elif nibble == 3:
                    dnib = (frame[widx] >> 30) & 0x3
                    if dnib == 0:
                        observed_modes.add("5x6")
                    elif dnib == 1:
                        observed_modes.add("6x5")
                    elif dnib == 2:
                        observed_modes.add("7x4")

        all_modes = {"7x4", "6x5", "5x6", "4x8", "3x10", "2x15", "1x30"}
        missing = all_modes - observed_modes
        assert not missing, \
            f"Missing Steim2 packing modes: {missing}. " \
            f"Observed: {observed_modes}. All 7 modes required."
