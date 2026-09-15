#!/usr/bin/env python3
"""Generate SIDP capture data for the task environment."""
import struct
import json
import zlib

def crc16_ccitt_false(data):
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

def build_param(tag, value):
    return struct.pack('>HH', tag, len(value)) + value

def build_message(service_group, service_id, params):
    payload = struct.pack('>BBB', service_group, service_id, len(params))
    for p in params:
        payload += p
    return payload

def build_fragment(transfer_id, frag_index, frag_total, data):
    return struct.pack('>HHH', transfer_id, frag_index, frag_total) + data

def build_packet(version, flags, session_id, sequence, payload, priority=0, timestamp=0):
    hdr = struct.pack('>2sBBIHH', b'SD', version, flags, session_id, sequence, len(payload))
    if version == 2:
        hdr += struct.pack('>BI', priority, timestamp)
    packet = hdr + payload
    if flags & 0x80:
        crc = crc16_ccitt_false(packet)
        packet += struct.pack('>H', crc)
    return packet

def generate():
    packets = []
    SID1 = 0x00001234
    seq1 = 0

    # 0: SessionOpen request
    seq1 += 1
    msg = build_message(0x01, 0x01, [build_param(0x0001, b'DiagClient-1')])
    packets.append(build_packet(1, 0x00, SID1, seq1, msg))

    # 1: SessionOpen response
    seq1 += 1
    msg = build_message(0x01, 0x01, [build_param(0x0002, struct.pack('>I', 3600))])
    packets.append(build_packet(1, 0x01, SID1, seq1, msg))

    # 2: DeviceInfo request
    seq1 += 1
    msg = build_message(0x02, 0x01, [])
    packets.append(build_packet(1, 0x00, SID1, seq1, msg))

    # 3: DeviceInfo response
    seq1 += 1
    msg = build_message(0x02, 0x01, [
        build_param(0x0101, b'IndustrialPLC-X500'),
        build_param(0x0102, b'3.14.2'),
        build_param(0x0103, b'SN-20240815-0042'),
    ])
    packets.append(build_packet(1, 0x01, SID1, seq1, msg))

    # 4: SecurityAccess RequestSeed request
    seq1 += 1
    msg = build_message(0x03, 0x01, [])
    packets.append(build_packet(1, 0x00, SID1, seq1, msg))

    # 5: SecurityAccess RequestSeed response
    seq1 += 1
    seed = bytes([0xA5, 0x3C, 0x7E, 0x19, 0xD2, 0x8B, 0x4F, 0x60])
    msg = build_message(0x03, 0x01, [build_param(0x0301, seed)])
    packets.append(build_packet(1, 0x01, SID1, seq1, msg))

    # 6: SecurityAccess SendKey request
    seq1 += 1
    key = bytes([b ^ 0x5A for b in reversed(seed)])
    msg = build_message(0x03, 0x02, [build_param(0x0302, key)])
    packets.append(build_packet(1, 0x00, SID1, seq1, msg))

    # 7: SecurityAccess SendKey response (success)
    seq1 += 1
    msg = build_message(0x03, 0x02, [build_param(0x0303, bytes([0x00]))])
    packets.append(build_packet(1, 0x01, SID1, seq1, msg))

    # 8: ReadParam temperature request
    seq1 += 1
    msg = build_message(0x04, 0x01, [build_param(0x0401, struct.pack('>H', 0x0001))])
    packets.append(build_packet(1, 0x00, SID1, seq1, msg))

    # 9: ReadParam temperature response (72.5)
    seq1 += 1
    msg = build_message(0x04, 0x01, [
        build_param(0x0401, struct.pack('>H', 0x0001)),
        build_param(0x0402, struct.pack('>f', 72.5)),
    ])
    packets.append(build_packet(1, 0x01, SID1, seq1, msg))

    # 10: ReadParam pressure request
    seq1 += 1
    msg = build_message(0x04, 0x01, [build_param(0x0401, struct.pack('>H', 0x0002))])
    packets.append(build_packet(1, 0x00, SID1, seq1, msg))

    # 11: ReadParam pressure response (1013.25)
    seq1 += 1
    msg = build_message(0x04, 0x01, [
        build_param(0x0401, struct.pack('>H', 0x0002)),
        build_param(0x0402, struct.pack('>f', 1013.25)),
    ])
    packets.append(build_packet(1, 0x01, SID1, seq1, msg))

    # 12: ReadParam fw_string request
    seq1 += 1
    msg = build_message(0x04, 0x01, [build_param(0x0401, struct.pack('>H', 0x0010))])
    packets.append(build_packet(1, 0x00, SID1, seq1, msg))

    # 13: ReadParam fw_string response
    seq1 += 1
    msg = build_message(0x04, 0x01, [
        build_param(0x0401, struct.pack('>H', 0x0010)),
        build_param(0x0402, b'PLC-X500-FW-3.14.2-release'),
    ])
    packets.append(build_packet(1, 0x01, SID1, seq1, msg))

    # 14: StartTransfer (v2, checksum)
    seq1 += 1
    fw_data = bytes(range(256)) * 2  # 512 bytes
    fw_crc32 = zlib.crc32(fw_data) & 0xFFFFFFFF
    msg = build_message(0x05, 0x01, [
        build_param(0x0501, struct.pack('>I', len(fw_data))),
        build_param(0x0502, struct.pack('>I', fw_crc32)),
    ])
    packets.append(build_packet(2, 0x80, SID1, seq1, msg, priority=7, timestamp=1723747200))

    # 15: StartTransfer response (v2, checksum)
    seq1 += 1
    msg = build_message(0x05, 0x01, [build_param(0x0503, bytes([0x00]))])
    packets.append(build_packet(2, 0x81, SID1, seq1, msg, priority=7, timestamp=1723747200))

    # 16-18: Firmware fragments (v2, fragmented+checksum)
    FRAG_SIZE = 200
    frag_count = (len(fw_data) + FRAG_SIZE - 1) // FRAG_SIZE
    for i in range(frag_count):
        seq1 += 1
        chunk = fw_data[i*FRAG_SIZE:(i+1)*FRAG_SIZE]
        frag_payload = build_fragment(0x0001, i, frag_count, chunk)
        flags = 0x04 | 0x80
        packets.append(build_packet(2, flags, SID1, seq1, frag_payload, priority=7, timestamp=1723747201+i))

    # 19: EndTransfer (v2, checksum)
    seq1 += 1
    msg = build_message(0x05, 0x02, [])
    packets.append(build_packet(2, 0x80, SID1, seq1, msg, priority=7, timestamp=1723747210))

    # 20: EndTransfer response (v2, checksum)
    seq1 += 1
    msg = build_message(0x05, 0x02, [build_param(0x0503, bytes([0x00]))])
    packets.append(build_packet(2, 0x81, SID1, seq1, msg, priority=7, timestamp=1723747210))

    # Session 2
    SID2 = 0x00005678
    seq2 = 0

    # 21: SessionOpen
    seq2 += 1
    msg = build_message(0x01, 0x01, [build_param(0x0001, b'MonitorTool-7')])
    packets.append(build_packet(1, 0x00, SID2, seq2, msg))

    # 22: SessionOpen response
    seq2 += 1
    msg = build_message(0x01, 0x01, [build_param(0x0002, struct.pack('>I', 1800))])
    packets.append(build_packet(1, 0x01, SID2, seq2, msg))

    # 23: ReadParam voltage request
    seq2 += 1
    msg = build_message(0x04, 0x01, [build_param(0x0401, struct.pack('>H', 0x0003))])
    packets.append(build_packet(1, 0x00, SID2, seq2, msg))

    # 24: ReadParam voltage response (24.125)
    seq2 += 1
    msg = build_message(0x04, 0x01, [
        build_param(0x0401, struct.pack('>H', 0x0003)),
        build_param(0x0402, struct.pack('>f', 24.125)),
    ])
    packets.append(build_packet(1, 0x01, SID2, seq2, msg))

    # --- Anomalies ---

    # 25: Wrong sync
    seq1 += 1
    msg = build_message(0x04, 0x01, [build_param(0x0401, struct.pack('>H', 0x0001))])
    bad_pkt = build_packet(1, 0x00, SID1, seq1, msg)
    bad_pkt = b'SE' + bad_pkt[2:]
    packets.append(bad_pkt)

    # 26: Bad checksum
    seq1 += 1
    msg = build_message(0x04, 0x01, [build_param(0x0401, struct.pack('>H', 0x0005))])
    bad_pkt = build_packet(2, 0x80, SID1, seq1, msg, priority=3, timestamp=1723747220)
    bad_pkt = bad_pkt[:-2] + struct.pack('>H', 0xDEAD)
    packets.append(bad_pkt)

    # 27: Invalid fragment index
    seq1 += 1
    frag_payload = build_fragment(0x0099, 5, 3, b'invalid_fragment_data')
    packets.append(build_packet(1, 0x04, SID1, seq1, frag_payload))

    # 28: SessionClose request
    seq1 = 30
    msg = build_message(0x01, 0x02, [])
    packets.append(build_packet(1, 0x00, SID1, seq1, msg))

    # 29: SessionClose response
    seq1 += 1
    msg = build_message(0x01, 0x02, [])
    packets.append(build_packet(1, 0x01, SID1, seq1, msg))

    return packets

if __name__ == '__main__':
    packets = generate()
    with open('/app/capture.hex', 'w') as f:
        for pkt in packets:
            f.write(pkt.hex() + '\n')
    print(f"Generated {len(packets)} packets to /app/capture.hex")
