
import hashlib
import struct
import binascii
import os
import pytest

FRAME_SPECS = [
    (0, 32),
    (1, 70),
    (2, 100),
    (3, 150),
    (4, 45),
]


def make_payload(frame_idx, size):
    data = bytearray()
    chunk = 0
    while len(data) < size:
        h = hashlib.sha256(f"wifi_frame_{frame_idx}_chunk_{chunk}".encode()).digest()
        data.extend(h)
        chunk += 1
    return bytes(data[:size])


@pytest.mark.parametrize("frame_idx,payload_size", FRAME_SPECS)
def test_decoded_file_exists(frame_idx, payload_size):
    path = f"/app/decoded/frame_{frame_idx}.hex"
    assert os.path.isfile(path), f"Missing decoded output: {path}"


@pytest.mark.parametrize("frame_idx,payload_size", FRAME_SPECS)
def test_decoded_payload_matches(frame_idx, payload_size):
    path = f"/app/decoded/frame_{frame_idx}.hex"
    assert os.path.isfile(path), f"Missing: {path}"

    with open(path) as f:
        actual_hex = f.read().strip().lower()

    expected = make_payload(frame_idx, payload_size)
    expected_hex = expected.hex()

    assert actual_hex == expected_hex, (
        f"Frame {frame_idx}: payload mismatch. "
        f"Expected {len(expected_hex)} hex chars, got {len(actual_hex)}."
    )


@pytest.mark.parametrize("frame_idx,payload_size", FRAME_SPECS)
def test_crc32_valid(frame_idx, payload_size):
    path = f"/app/decoded/frame_{frame_idx}.hex"
    assert os.path.isfile(path), f"Missing: {path}"

    with open(path) as f:
        payload_hex = f.read().strip().lower()

    payload = bytes.fromhex(payload_hex)
    crc_val = binascii.crc32(payload) & 0xFFFFFFFF
    psdu = payload + struct.pack("<I", crc_val)
    residual = binascii.crc32(psdu) & 0xFFFFFFFF
    assert residual == 0x2144DF1C, (
        f"Frame {frame_idx}: CRC-32 residual 0x{residual:08X} != 0x2144DF1C"
    )


@pytest.mark.parametrize("frame_idx,payload_size", FRAME_SPECS)
def test_payload_length(frame_idx, payload_size):
    path = f"/app/decoded/frame_{frame_idx}.hex"
    assert os.path.isfile(path), f"Missing: {path}"

    with open(path) as f:
        payload_hex = f.read().strip().lower()

    actual_bytes = len(payload_hex) // 2
    assert actual_bytes == payload_size, (
        f"Frame {frame_idx}: expected {payload_size} bytes, got {actual_bytes}"
    )
