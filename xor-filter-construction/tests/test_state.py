"""
Tests for the binary sensor format reverse-engineering task.
Contains an independent reference parser that computes expected answers
from the binary data, then compares against the agent's output files.
"""
import json
import os
import struct
import statistics
from collections import defaultdict

import pytest


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


def parse_binary():
    """Reference parser — returns list of parsed record dicts."""
    with open('/app/data/sensor_data.bin', 'rb') as f:
        data = f.read()

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
            'sv': sv,
        })

    return records


@pytest.fixture(scope='module')
def ref():
    """Compute reference answers from the binary data."""
    records = parse_binary()
    prod = [r for r in records if not r['is_cal']]
    TYPE_NAMES = ['temperature', 'pressure', 'humidity']

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

    # Queries
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

    return {
        'stats': {
            'total_records': len(records),
            'calibration_records': len(records) - len(prod),
            'production_records': len(prod),
            'by_type': by_type,
            'mean_primary': mean_primary,
            'unique_sensors': unique_sensors,
            'time_span_hours': time_span_hours,
        },
        'queries': {
            'hottest_sensor_id': hottest,
            'max_pressure': max_pressure,
            'min_humidity': min_humidity,
            'total_temp_records': by_type['temperature'],
            'high_quality_count': high_q,
            'sensor_7_records': s7,
            'median_temperature': median_temp,
            'pressure_std': pressure_std,
        },
    }


def load_output(name):
    path = '/app/output/{}'.format(name)
    assert os.path.isfile(path), '{} not found'.format(path)
    with open(path) as f:
        return json.load(f)


# ---- Stats tests ----

class TestStatsOutput:
    def test_stats_file_exists(self):
        assert os.path.isfile('/app/output/stats.json')

    def test_total_records(self, ref):
        s = load_output('stats.json')
        assert s['total_records'] == ref['stats']['total_records']

    def test_calibration_records(self, ref):
        s = load_output('stats.json')
        assert s['calibration_records'] == ref['stats']['calibration_records']

    def test_production_records(self, ref):
        s = load_output('stats.json')
        assert s['production_records'] == ref['stats']['production_records']

    def test_by_type_temperature(self, ref):
        s = load_output('stats.json')
        assert s['by_type']['temperature'] == ref['stats']['by_type']['temperature']

    def test_by_type_pressure(self, ref):
        s = load_output('stats.json')
        assert s['by_type']['pressure'] == ref['stats']['by_type']['pressure']

    def test_by_type_humidity(self, ref):
        s = load_output('stats.json')
        assert s['by_type']['humidity'] == ref['stats']['by_type']['humidity']

    def test_mean_temperature(self, ref):
        s = load_output('stats.json')
        assert abs(s['mean_primary']['temperature'] -
                   ref['stats']['mean_primary']['temperature']) < 0.05

    def test_mean_pressure(self, ref):
        s = load_output('stats.json')
        assert abs(s['mean_primary']['pressure'] -
                   ref['stats']['mean_primary']['pressure']) < 0.05

    def test_mean_humidity(self, ref):
        s = load_output('stats.json')
        assert abs(s['mean_primary']['humidity'] -
                   ref['stats']['mean_primary']['humidity']) < 0.05

    def test_unique_sensors(self, ref):
        s = load_output('stats.json')
        assert s['unique_sensors'] == ref['stats']['unique_sensors']

    def test_time_span_hours(self, ref):
        s = load_output('stats.json')
        assert abs(s['time_span_hours'] -
                   ref['stats']['time_span_hours']) < 0.1


# ---- Query tests ----

class TestQueriesOutput:
    def test_queries_file_exists(self):
        assert os.path.isfile('/app/output/queries.json')

    def test_hottest_sensor(self, ref):
        q = load_output('queries.json')
        assert q['hottest_sensor_id'] == ref['queries']['hottest_sensor_id']

    def test_max_pressure(self, ref):
        q = load_output('queries.json')
        assert abs(q['max_pressure'] -
                   ref['queries']['max_pressure']) < 0.01

    def test_min_humidity(self, ref):
        q = load_output('queries.json')
        assert abs(q['min_humidity'] -
                   ref['queries']['min_humidity']) < 0.01

    def test_total_temp_records(self, ref):
        q = load_output('queries.json')
        assert q['total_temp_records'] == ref['queries']['total_temp_records']

    def test_high_quality_count(self, ref):
        q = load_output('queries.json')
        assert q['high_quality_count'] == ref['queries']['high_quality_count']

    def test_sensor_7_records(self, ref):
        q = load_output('queries.json')
        assert q['sensor_7_records'] == ref['queries']['sensor_7_records']

    def test_median_temperature(self, ref):
        q = load_output('queries.json')
        assert abs(q['median_temperature'] -
                   ref['queries']['median_temperature']) < 0.01

    def test_pressure_std(self, ref):
        q = load_output('queries.json')
        assert abs(q['pressure_std'] -
                   ref['queries']['pressure_std']) < 0.1
