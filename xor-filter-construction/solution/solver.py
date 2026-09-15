#!/usr/bin/env python3
"""
Solution: reverse-engineer and parse the SensorStream binary format.

Discovered format (from binary analysis):
  Header: 32 bytes
    [0:4]   magic '\x89SEN'
    [4:6]   version uint16 LE
    [6:10]  record_count uint32 LE
    [10:18] start_ts uint64 LE
    [18:26] end_ts uint64 LE
    [26:28] sensor_count uint16 LE
    [28:32] header CRC32 uint32 LE

  Record: 32 bytes (mixed endianness!)
    [0]     type_byte: bits 0-2 = type, bit 3 = calibration, bits 4-7 = quality
    [1:3]   sensor_id uint16 BE
    [3]     reserved 0x00
    [4:12]  timestamp int64 LE (milliseconds since epoch)
    [12:20] primary_value float64 BE
    [20:28] secondary_value float64 BE
    [28:30] CRC-16/CCITT uint16 LE
    [30:32] padding 0xFF 0xFF
"""
import struct
import json
import os
import statistics
from collections import defaultdict


def crc16_ccitt(data):
    """CRC-16/CCITT-FALSE: init=0xFFFF, poly=0x1021."""
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
    with open('/app/data/sensor_data.bin', 'rb') as f:
        data = f.read()

    # Parse header
    assert data[0:4] == b'\x89SEN', "Bad magic"
    record_count = struct.unpack('<I', data[6:10])[0]

    TYPE_NAMES = ['temperature', 'pressure', 'humidity']
    records = []

    for i in range(record_count):
        off = 32 + i * 32
        rec = data[off:off + 32]

        type_byte = rec[0]
        rec_type = type_byte & 0x07
        is_cal = bool(type_byte & 0x08)
        quality = (type_byte >> 4) & 0x0F

        sensor_id = struct.unpack('>H', rec[1:3])[0]
        ts = struct.unpack('<q', rec[4:12])[0]
        pv = struct.unpack('>d', rec[12:20])[0]
        sv = struct.unpack('>d', rec[20:28])[0]

        exp_crc = struct.unpack('<H', rec[28:30])[0]
        got_crc = crc16_ccitt(rec[0:28])
        assert exp_crc == got_crc, "CRC mismatch at record {}".format(i)

        records.append({
            'rec_type': rec_type,
            'type_name': TYPE_NAMES[rec_type],
            'is_cal': is_cal,
            'quality': quality,
            'sensor_id': sensor_id,
            'ts': ts,
            'pv': pv,
        })

    # Compute stats (production records only)
    prod = [r for r in records if not r['is_cal']]
    cal_count = len(records) - len(prod)

    by_type = {}
    vals_by_type = {}
    for tn in TYPE_NAMES:
        typed = [r for r in prod if r['type_name'] == tn]
        by_type[tn] = len(typed)
        vals_by_type[tn] = [r['pv'] for r in typed]

    mean_primary = {}
    for tn in TYPE_NAMES:
        v = vals_by_type[tn]
        mean_primary[tn] = round(sum(v) / len(v), 4) if v else 0.0

    unique_sensors = len(set(r['sensor_id'] for r in prod))

    all_ts = [r['ts'] for r in records]
    time_span_hours = round((max(all_ts) - min(all_ts)) / 3600000.0, 4)

    os.makedirs('/app/output', exist_ok=True)

    stats = {
        'total_records': len(records),
        'calibration_records': cal_count,
        'production_records': len(prod),
        'by_type': by_type,
        'mean_primary': mean_primary,
        'unique_sensors': unique_sensors,
        'time_span_hours': time_span_hours,
    }
    with open('/app/output/stats.json', 'w') as f:
        json.dump(stats, f, indent=2)

    # Compute queries
    temp_by_sensor = defaultdict(list)
    for r in prod:
        if r['type_name'] == 'temperature':
            temp_by_sensor[r['sensor_id']].append(r['pv'])

    hottest = max(temp_by_sensor,
                  key=lambda s: sum(temp_by_sensor[s]) / len(temp_by_sensor[s]))
    max_pressure = round(max(vals_by_type['pressure']), 4)
    min_humidity = round(min(vals_by_type['humidity']), 4)
    high_q = sum(1 for r in prod if r['quality'] >= 12)
    s7 = sum(1 for r in prod if r['sensor_id'] == 7)
    median_temp = round(statistics.median(vals_by_type['temperature']), 4)
    pressure_std = round(statistics.stdev(vals_by_type['pressure']), 4)

    queries = {
        'hottest_sensor_id': hottest,
        'max_pressure': max_pressure,
        'min_humidity': min_humidity,
        'total_temp_records': by_type['temperature'],
        'high_quality_count': high_q,
        'sensor_7_records': s7,
        'median_temperature': median_temp,
        'pressure_std': pressure_std,
    }
    with open('/app/output/queries.json', 'w') as f:
        json.dump(queries, f, indent=2)

    print("Done. Stats: {} total, {} calibration, {} production".format(
        len(records), cal_count, len(prod)))
    for tn in TYPE_NAMES:
        print("  {}: {} records, mean={}".format(tn, by_type[tn], mean_primary[tn]))


if __name__ == '__main__':
    main()
