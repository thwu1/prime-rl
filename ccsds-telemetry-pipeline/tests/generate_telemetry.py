#!/usr/bin/env python3
"""
Generate CCSDS TM test telemetry data.

Creates a binary file of randomized TM transfer frames containing
embedded CCSDS Space Packets, some of which span frame boundaries.

"""

import struct
import os

FRAME_LENGTH = 256
SPACECRAFT_ID = 42
VCID = 0
OCF_VALUE = 0xDEADBEEF
DATA_FIELD_SIZE = 244  # 256 - 6(header) - 4(OCF) - 2(CRC)


def ccsds_tm_random_sequence():
    """Generate the 255-byte CCSDS TM pseudo-random sequence per CCSDS 131.0-B-3."""
    seq = bytearray(255)
    lfsr = 0xFF
    for i in range(255):
        byte_val = 0
        for j in range(8):
            byte_val = ((byte_val << 1) | (lfsr & 1)) & 0xFF
            bit = ((lfsr >> 0) ^ (lfsr >> 3) ^ (lfsr >> 5) ^ (lfsr >> 7)) & 1
            lfsr = ((lfsr >> 1) | (bit << 7)) & 0xFF
        seq[i] = byte_val
    return bytes(seq)


def randomize_tm(data):
    """Apply CCSDS TM randomization (XOR with pseudo-random sequence)."""
    seq = ccsds_tm_random_sequence()
    result = bytearray(data)
    for i in range(len(result)):
        result[i] ^= seq[i % 255]
    return bytes(result)


def crc16_ccitt(data):
    """Compute CRC-16-CCITT: polynomial 0x1021, initial value 0xFFFF."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def make_space_packet(apid, seq_flags, seq_count, user_data):
    """Build a CCSDS Space Packet with the given parameters."""
    pdl = len(user_data) - 1  # Packet Data Length = user data bytes - 1
    word01 = (0 << 13) | (0 << 12) | (0 << 11) | (apid & 0x7FF)
    word23 = ((seq_flags & 0x3) << 14) | (seq_count & 0x3FFF)
    header = struct.pack('>HHH', word01, word23, pdl)
    return header + user_data


def make_user_data(apid, seq_count, length):
    """Generate deterministic pseudo-random user data."""
    return bytes([(apid * 37 + seq_count * 13 + i * 7 + 3) & 0xFF for i in range(length)])


def build_tm_frame(frame_index, data_field, fhp, ocf_value):
    """Build a complete TM frame with header, data field, OCF, and CRC."""
    # Primary header bytes 0-1
    word01 = (0 << 14) | (SPACECRAFT_ID << 4) | (VCID << 1) | 1  # OCF flag = 1
    mcfc = frame_index & 0xFF
    vcfc = frame_index & 0xFF

    # First Header Pointer encoding
    if fhp < 0:
        fhp_val = 0x7FF  # no packet starts in this frame
    else:
        fhp_val = fhp & 0x7FF

    # TFDFS: no sec header, sync=0, pkt_order=0, seg_len_id=3, FHP
    tfdfs = (0 << 15) | (0 << 14) | (0 << 13) | (3 << 11) | fhp_val

    header = struct.pack('>HBBH', word01, mcfc, vcfc, tfdfs)

    # Assemble frame: header + data field + OCF
    ocf_bytes = struct.pack('>I', ocf_value)
    frame_no_crc = header + data_field + ocf_bytes

    assert len(frame_no_crc) == FRAME_LENGTH - 2, \
        f"Frame without CRC is {len(frame_no_crc)} bytes, expected {FRAME_LENGTH - 2}"

    # Compute and append CRC
    crc = crc16_ccitt(frame_no_crc)
    crc_bytes = struct.pack('>H', crc)
    frame = frame_no_crc + crc_bytes

    assert len(frame) == FRAME_LENGTH, f"Frame is {len(frame)} bytes, expected {FRAME_LENGTH}"
    return frame


def generate():
    """Generate test telemetry data."""
    # Define packets: (APID, SeqFlags, SeqCount, UserDataLength)
    # Sizes chosen so packets pack exactly into 5 frames of 244 bytes each
    # with specific cross-frame spanning patterns:
    #   Frame 0: P1(56) + P2(86) + P3(102) = 244
    #   Frame 1: P4(200) + P5(44) = 244
    #   Frame 2: P6 starts (244 of 494 bytes)
    #   Frame 3: P6 continues (244 more, 6 remaining) -- no new packet starts
    #   Frame 4: P6 ends(6) + P7(178) + P8(60) = 244
    packets_def = [
        (100, 3, 0, 50),    # P1: total 56
        (200, 3, 0, 80),    # P2: total 86
        (100, 3, 1, 96),    # P3: total 102
        (300, 3, 0, 194),   # P4: total 200
        (200, 3, 1, 38),    # P5: total 44
        (400, 3, 0, 488),   # P6: total 494 (spans 3 frames!)
        (100, 3, 2, 172),   # P7: total 178
        (500, 3, 0, 54),    # P8: total 60
    ]

    # Build the continuous packet stream
    packet_bytes_list = []
    packet_start_positions = []
    pos = 0
    for apid, sf, sc, udl in packets_def:
        ud = make_user_data(apid, sc, udl)
        pkt = make_space_packet(apid, sf, sc, ud)
        packet_bytes_list.append(pkt)
        packet_start_positions.append(pos)
        pos += len(pkt)

    packet_stream = b''.join(packet_bytes_list)
    total_data = len(packet_stream)
    num_frames = 5
    assert total_data == num_frames * DATA_FIELD_SIZE, \
        f"Total packet data {total_data} != {num_frames * DATA_FIELD_SIZE}"

    # Build frames
    frames = []
    for frame_idx in range(num_frames):
        frame_data_start = frame_idx * DATA_FIELD_SIZE
        frame_data_end = frame_data_start + DATA_FIELD_SIZE
        data_field = packet_stream[frame_data_start:frame_data_end]

        # Find FHP: offset of first packet that starts within this frame's data
        fhp = -1
        for ps in sorted(packet_start_positions):
            if frame_data_start <= ps < frame_data_end:
                fhp = ps - frame_data_start
                break

        # Build frame, compute CRC, then randomize
        frame = build_tm_frame(frame_idx, data_field, fhp, OCF_VALUE)
        randomized_frame = randomize_tm(frame)
        frames.append(randomized_frame)

    # Write binary telemetry file
    os.makedirs('/app', exist_ok=True)
    with open('/app/telemetry.bin', 'wb') as f:
        for frame in frames:
            f.write(frame)

    print(f"Generated {len(frames)} frames ({len(frames) * FRAME_LENGTH} bytes) "
          f"containing {len(packets_def)} packets")


if __name__ == '__main__':
    generate()
