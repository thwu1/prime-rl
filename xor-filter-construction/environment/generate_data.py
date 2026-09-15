#!/usr/bin/env python3
"""
Generate binary sensor data for the reverse-engineering task.
Deterministic with fixed seed. Produces sensor_data.bin and known_records.json.
"""
import struct
import random
import json
import os
import binascii


SEED = 0x4C454D49  # "LEMI"
RECORD_COUNT = 50000
SENSOR_COUNT = 100
START_TS_MS = 1704067200000  # 2024-01-01 00:00:00 UTC in milliseconds
END_TS_MS = 1706659200000    # 2024-01-31 00:00:00 UTC in milliseconds
CAL_RATE = 0.02              # ~2% calibration records


def crc16_ccitt(data):
    """CRC-16/CCITT-FALSE: init=0xFFFF, poly=0x1021, no final XOR."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def main():
    rng = random.Random(SEED)
    os.makedirs('/app/data', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)

    # Generate sorted timestamps across 30-day window
    timestamps = sorted(rng.randint(START_TS_MS, END_TS_MS) for _ in range(RECORD_COUNT))

    all_records = []
    raw_bytes_list = []

    for i in range(RECORD_COUNT):
        rec_type = rng.randint(0, 2)  # 0=temperature, 1=pressure, 2=humidity
        is_cal = rng.random() < CAL_RATE
        quality = rng.randint(0, 15)
        sensor_id = rng.randint(0, SENSOR_COUNT - 1)
        ts = timestamps[i]

        if rec_type == 0:  # temperature in Celsius
            pv = rng.gauss(20.0, 15.0)
            pv = max(-50.0, min(70.0, pv))
            sv = pv * 1.8 + 32.0  # Fahrenheit conversion
        elif rec_type == 1:  # pressure in hPa
            pv = rng.gauss(1013.25, 20.0)
            pv = max(900.0, min(1100.0, pv))
            sv = pv * 0.02953  # convert to inHg
        else:  # humidity in percent
            pv = rng.gauss(60.0, 20.0)
            pv = max(0.0, min(100.0, pv))
            sv = pv / 100.0  # fraction

        # Type/flags byte layout:
        #   bits 0-2: record type (0/1/2)
        #   bit 3:    calibration flag
        #   bits 4-7: quality score (0-15)
        type_byte = rec_type | (int(is_cal) << 3) | (quality << 4)

        # Record: 32 bytes with MIXED ENDIANNESS
        # Byte  0:     type/flags (uint8)
        # Bytes 1-2:   sensor_id (uint16 big-endian)
        # Byte  3:     reserved (0x00)
        # Bytes 4-11:  timestamp (int64 little-endian)
        # Bytes 12-19: primary value (float64 big-endian)
        # Bytes 20-27: secondary value (float64 big-endian)
        # Bytes 28-29: CRC-16/CCITT of bytes 0-27 (uint16 little-endian)
        # Bytes 30-31: padding (0xFF 0xFF)
        rb = struct.pack('B', type_byte)
        rb += struct.pack('>H', sensor_id)
        rb += b'\x00'
        rb += struct.pack('<q', ts)
        rb += struct.pack('>d', pv)
        rb += struct.pack('>d', sv)
        crc = crc16_ccitt(rb)
        rb += struct.pack('<H', crc)
        rb += b'\xFF\xFF'
        assert len(rb) == 32

        raw_bytes_list.append(rb)
        all_records.append({
            'rec_type': rec_type,
            'is_cal': is_cal,
            'quality': quality,
            'sensor_id': sensor_id,
            'ts': ts,
            'pv': pv,
            'sv': sv,
        })

    # Build 32-byte file header
    hdr = b'\x89SEN'                                      # bytes 0-3:   magic
    hdr += struct.pack('<H', 3)                            # bytes 4-5:   version
    hdr += struct.pack('<I', RECORD_COUNT)                 # bytes 6-9:   record count
    hdr += struct.pack('<Q', START_TS_MS)                  # bytes 10-17: start timestamp
    hdr += struct.pack('<Q', END_TS_MS)                    # bytes 18-25: end timestamp
    hdr += struct.pack('<H', SENSOR_COUNT)                 # bytes 26-27: sensor count
    hdr += struct.pack('<I', binascii.crc32(hdr) & 0xFFFFFFFF)  # bytes 28-31: CRC32
    assert len(hdr) == 32

    with open('/app/data/sensor_data.bin', 'wb') as f:
        f.write(hdr)
        for rb in raw_bytes_list:
            f.write(rb)

    # Select 20 diverse known records for cross-referencing
    cal_idxs = [i for i, r in enumerate(all_records) if r['is_cal']]
    known_set = set()

    # Include first, last, and 3 calibration records
    known_set.add(0)
    known_set.add(RECORD_COUNT - 1)
    for ci in cal_idxs[:3]:
        known_set.add(ci)

    # Include records from each type spread across the file
    for rt in range(3):
        typed = [i for i, r in enumerate(all_records)
                 if r['rec_type'] == rt and not r['is_cal']]
        step = max(1, len(typed) // 5)
        for j in range(0, len(typed), step):
            known_set.add(typed[j])
            if len(known_set) >= 20:
                break
        if len(known_set) >= 20:
            break

    # Fill to exactly 20
    fillers = [100, 500, 1000, 2500, 5000, 10000, 20000, 30000, 40000]
    for fi in fillers:
        if len(known_set) >= 20:
            break
        known_set.add(fi)

    known_idxs = sorted(known_set)[:20]

    known_out = []
    for idx in known_idxs:
        r = all_records[idx]
        known_out.append({
            'record_index': idx,
            'byte_offset': 32 + idx * 32,
            'expected_type': ['temperature', 'pressure', 'humidity'][r['rec_type']],
            'expected_sensor_id': r['sensor_id'],
            'expected_timestamp_ms': r['ts'],
            'expected_primary_value': r['pv'],
            'expected_secondary_value': r['sv'],
        })

    with open('/app/data/known_records.json', 'w') as f:
        json.dump(known_out, f, indent=2)

    # Summary
    n_cal = sum(1 for r in all_records if r['is_cal'])
    tc = [0, 0, 0]
    for r in all_records:
        if not r['is_cal']:
            tc[r['rec_type']] += 1
    print("Records: {} (cal={}, temp={}, pres={}, hum={})".format(
        RECORD_COUNT, n_cal, tc[0], tc[1], tc[2]))
    print("Known records: {}, calibration in known: {}".format(
        len(known_idxs),
        sum(1 for i in known_idxs if all_records[i]['is_cal'])))
    print("File size: {} bytes".format(32 + RECORD_COUNT * 32))


if __name__ == '__main__':
    main()
