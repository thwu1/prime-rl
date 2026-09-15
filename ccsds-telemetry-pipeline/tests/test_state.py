#!/usr/bin/env python3
"""
Tests for the CCSDS TM telemetry processing pipeline.

Verifies that the Java pipeline correctly derandomizes frames,
verifies CRC, parses headers, and extracts space packets including
those spanning frame boundaries.

"""

import json
import os
import pytest


SPACECRAFT_ID = 42
VCID = 0
OCF_VALUE = 0xDEADBEEF
NUM_FRAMES = 5
NUM_PACKETS = 8

# Packet definitions: (APID, SeqFlags, SeqCount, UserDataLength)
PACKETS_DEF = [
    (100, 3, 0, 50),
    (200, 3, 0, 80),
    (100, 3, 1, 96),
    (300, 3, 0, 194),
    (200, 3, 1, 38),
    (400, 3, 0, 488),
    (100, 3, 2, 172),
    (500, 3, 0, 54),
]

# Expected FHP values per frame
EXPECTED_FHPS = [0, 0, 0, -1, 6]


def make_user_data(apid, seq_count, length):
    """Same deterministic data generator as the telemetry generator."""
    return bytes([(apid * 37 + seq_count * 13 + i * 7 + 3) & 0xFF for i in range(length)])


def load_output():
    """Load and parse the pipeline output JSON."""
    output_path = "/app/output.json"
    assert os.path.exists(output_path), f"Output file {output_path} does not exist"
    with open(output_path) as f:
        return json.load(f)


class TestFrames:
    """Verify TM frame header parsing."""

    def test_frame_count(self):
        output = load_output()
        assert len(output["frames"]) == NUM_FRAMES, \
            f"Expected {NUM_FRAMES} frames, got {len(output['frames'])}"

    def test_spacecraft_id(self):
        output = load_output()
        for frame in output["frames"]:
            assert frame["spacecraftId"] == SPACECRAFT_ID, \
                f"Frame {frame['index']}: spacecraftId={frame['spacecraftId']}, expected {SPACECRAFT_ID}"

    def test_vcid(self):
        output = load_output()
        for frame in output["frames"]:
            assert frame["vcid"] == VCID, \
                f"Frame {frame['index']}: vcid={frame['vcid']}, expected {VCID}"

    def test_frame_counts(self):
        output = load_output()
        for frame in output["frames"]:
            idx = frame["index"]
            assert frame["mcFrameCount"] == idx, \
                f"Frame {idx}: mcFrameCount={frame['mcFrameCount']}, expected {idx}"
            assert frame["vcFrameCount"] == idx, \
                f"Frame {idx}: vcFrameCount={frame['vcFrameCount']}, expected {idx}"

    def test_first_header_pointers(self):
        output = load_output()
        for i, frame in enumerate(output["frames"]):
            assert frame["firstHeaderPointer"] == EXPECTED_FHPS[i], \
                f"Frame {i}: FHP={frame['firstHeaderPointer']}, expected {EXPECTED_FHPS[i]}"

    def test_ocf_values(self):
        output = load_output()
        expected_ocf = f"0x{OCF_VALUE:08X}"
        for frame in output["frames"]:
            assert frame["ocf"] == expected_ocf, \
                f"Frame {frame['index']}: ocf={frame['ocf']}, expected {expected_ocf}"

    def test_crc_valid(self):
        output = load_output()
        for frame in output["frames"]:
            assert frame["crcValid"] is True, \
                f"Frame {frame['index']}: CRC validation failed"


class TestPackets:
    """Verify CCSDS Space Packet extraction."""

    def test_packet_count(self):
        output = load_output()
        assert len(output["packets"]) == NUM_PACKETS, \
            f"Expected {NUM_PACKETS} packets, got {len(output['packets'])}"

    def test_packet_apids(self):
        output = load_output()
        for i, (apid, sf, sc, udl) in enumerate(PACKETS_DEF):
            actual = output["packets"][i]["apid"]
            assert actual == apid, f"Packet {i}: apid={actual}, expected {apid}"

    def test_packet_sequence_flags(self):
        output = load_output()
        for i, (apid, sf, sc, udl) in enumerate(PACKETS_DEF):
            actual = output["packets"][i]["sequenceFlags"]
            assert actual == sf, f"Packet {i}: sequenceFlags={actual}, expected {sf}"

    def test_packet_sequence_counts(self):
        output = load_output()
        for i, (apid, sf, sc, udl) in enumerate(PACKETS_DEF):
            actual = output["packets"][i]["sequenceCount"]
            assert actual == sc, f"Packet {i}: sequenceCount={actual}, expected {sc}"

    def test_packet_data_lengths(self):
        output = load_output()
        for i, (apid, sf, sc, udl) in enumerate(PACKETS_DEF):
            expected_pdl = udl - 1  # Packet Data Length = user data length - 1
            actual = output["packets"][i]["dataLength"]
            assert actual == expected_pdl, \
                f"Packet {i}: dataLength={actual}, expected {expected_pdl}"

    def test_packet_user_data(self):
        output = load_output()
        for i, (apid, sf, sc, udl) in enumerate(PACKETS_DEF):
            expected_hex = make_user_data(apid, sc, udl).hex()
            actual_hex = output["packets"][i]["userDataHex"]
            assert actual_hex == expected_hex, \
                f"Packet {i} (APID {apid}): user data mismatch. " \
                f"First 20 chars: actual={actual_hex[:20]}, expected={expected_hex[:20]}"

    def test_spanning_packet_integrity(self):
        """Specifically verify packet 6 (APID 400) which spans 3 frames."""
        output = load_output()
        pkt = output["packets"][5]  # Index 5 = APID 400
        assert pkt["apid"] == 400
        assert pkt["dataLength"] == 487  # 488 - 1
        expected_data = make_user_data(400, 0, 488)
        assert pkt["userDataHex"] == expected_data.hex(), \
            "Multi-frame spanning packet (APID 400, 494 bytes) not correctly reassembled"

    def test_packet_ordering(self):
        """Verify packets are in correct order (by stream position)."""
        output = load_output()
        expected_apid_order = [100, 200, 100, 300, 200, 400, 100, 500]
        actual_apid_order = [p["apid"] for p in output["packets"]]
        assert actual_apid_order == expected_apid_order, \
            f"Packet order wrong: {actual_apid_order} vs expected {expected_apid_order}"
