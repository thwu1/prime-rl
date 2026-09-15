#!/usr/bin/env python3

"""
Reference solution for I2C bus forensics.
Decodes sigrok capture via sigrok-cli, then performs sensor-specific analysis.
"""

import subprocess
import re
import json
import sys


# ============================================================
# Step 1  —  Decode I2C protocol via sigrok-cli
# ============================================================

def decode_capture():
    result = subprocess.run(
        ['sigrok-cli', '-i', '/app/capture.sr',
         '-P', 'i2c:scl=SCL:sda=SDA', '-A', 'i2c'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"sigrok-cli error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


# ============================================================
# Step 2  —  Parse sigrok annotations into transactions
# ============================================================

def parse_annotations(text):
    """Parse sigrok I2C annotations into structured transactions."""
    transactions = []
    current_phases = []
    current_phase = None
    anomaly = None
    last_evt = None    # 'address' | 'data'
    last_dir = None    # 'write'  | 'read'

    for line in text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        # strip optional sample-range prefix and decoder prefix
        line = re.sub(r'^\d+[-\u2013]\d+\s+', '', line)
        line = re.sub(r'^i2c-\d+:\s*', '', line)
        ann = line.strip()

        if ann in ('Start', 'S'):
            if current_phases or current_phase is not None:
                # repeated start inside existing transaction
                if current_phase is not None and current_phase['address'] is not None:
                    current_phases.append(current_phase)
                current_phase = {'address': None, 'direction': None, 'data': []}
            else:
                current_phase = {'address': None, 'direction': None, 'data': []}
                anomaly = None
            last_evt = None

        elif ann in ('Start repeat', 'Sr'):
            if current_phase is not None:
                current_phases.append(current_phase)
            current_phase = {'address': None, 'direction': None, 'data': []}
            last_evt = None

        elif ann in ('Stop', 'P'):
            if current_phase is not None:
                current_phases.append(current_phase)
            transactions.append({'phases': current_phases, 'anomaly': anomaly})
            current_phases = []
            current_phase = None
            anomaly = None
            last_evt = None

        elif ann.startswith('Address write:') or ann.startswith('AW:'):
            addr = int(ann.split(':')[1].strip(), 16)
            if current_phase is not None:
                current_phase['address'] = addr
                current_phase['direction'] = 'write'
            last_evt, last_dir = 'address', 'write'

        elif ann.startswith('Address read:') or ann.startswith('AR:'):
            addr = int(ann.split(':')[1].strip(), 16)
            if current_phase is not None:
                current_phase['address'] = addr
                current_phase['direction'] = 'read'
            last_evt, last_dir = 'address', 'read'

        elif ann.startswith('Data write:') or ann.startswith('DW:'):
            b = int(ann.split(':')[1].strip(), 16)
            if current_phase is not None:
                current_phase['data'].append(b)
            last_evt, last_dir = 'data', 'write'

        elif ann.startswith('Data read:') or ann.startswith('DR:'):
            b = int(ann.split(':')[1].strip(), 16)
            if current_phase is not None:
                current_phase['data'].append(b)
            last_evt, last_dir = 'data', 'read'

        elif ann in ('ACK', 'A'):
            pass

        elif ann in ('NACK', 'N'):
            if last_evt == 'address' and current_phase is not None:
                anomaly = {
                    'type': 'address_nack',
                    'address': current_phase['address'],
                    'description': (
                        f"Device 0x{current_phase['address']:02x} did not "
                        f"acknowledge address byte (not present on bus)"
                    ),
                }
            elif last_evt == 'data' and last_dir == 'write' and current_phase is not None:
                reg = current_phase['data'][0] if current_phase['data'] else None
                anomaly = {
                    'type': 'data_nack',
                    'address': current_phase['address'],
                    'register': f"0x{reg:02x}" if reg is not None else None,
                    'description': (
                        f"Data NACK during write to device "
                        f"0x{current_phase['address']:02x}"
                        + (f" register 0x{reg:02x}" if reg is not None else "")
                    ),
                }
            # NACK in read direction = normal master end-of-read

    return transactions


# ============================================================
# Step 3  —  Register data extraction
# ============================================================

def extract_register_reads(transactions, dev_addr):
    """Return {register: data_bytes} for write-then-read transactions."""
    reads = {}
    for txn in transactions:
        if txn['anomaly'] is not None:
            continue
        ph = txn['phases']
        if len(ph) == 2:
            wr, rd = ph
            if (wr['address'] == dev_addr and wr['direction'] == 'write'
                    and rd['address'] == dev_addr and rd['direction'] == 'read'
                    and len(wr['data']) >= 1):
                reads[wr['data'][0]] = rd['data']
    return reads


# ============================================================
# Step 4  —  BME280 decoding
# ============================================================

ACCEL_RANGES = {0: '+-2g', 1: '+-4g', 2: '+-8g', 3: '+-16g'}
ACCEL_SENS   = {0: 16384.0, 1: 8192.0, 2: 4096.0, 3: 2048.0}
GYRO_RANGES  = {0: '+-250dps', 1: '+-500dps', 2: '+-1000dps', 3: '+-2000dps'}
GYRO_SENS    = {0: 131.0, 1: 65.5, 2: 32.8, 3: 16.4}


def decode_bme280_calibration(cal1, cal2):
    def u16(b, o): return b[o] | (b[o+1] << 8)
    def s16(b, o):
        v = u16(b, o)
        return v - 65536 if v >= 32768 else v
    def s8(v):
        return v - 256 if v >= 128 else v

    c = {}
    c['dig_T1'] = u16(cal1, 0)
    c['dig_T2'] = s16(cal1, 2)
    c['dig_T3'] = s16(cal1, 4)
    for i in range(9):
        key = f'dig_P{i+1}'
        c[key] = u16(cal1, 6 + i*2) if i == 0 else s16(cal1, 6 + i*2)
    c['dig_H1'] = cal1[25]
    c['dig_H2'] = s16(cal2, 0)
    c['dig_H3'] = cal2[2]

    e4, e5, e6 = cal2[3], cal2[4], cal2[5]
    dh4 = (e4 << 4) | (e5 & 0x0F)
    if dh4 >= 2048:
        dh4 -= 4096
    c['dig_H4'] = dh4
    dh5 = (e6 << 4) | ((e5 >> 4) & 0x0F)
    if dh5 >= 2048:
        dh5 -= 4096
    c['dig_H5'] = dh5
    c['dig_H6'] = s8(cal2[6])
    return c


def decode_bme280_raw(raw):
    adc_P = (raw[0] << 12) | (raw[1] << 4) | (raw[2] >> 4)
    adc_T = (raw[3] << 12) | (raw[4] << 4) | (raw[5] >> 4)
    adc_H = (raw[6] << 8) | raw[7]
    return adc_T, adc_P, adc_H


def bme280_compensate_temperature(adc_T, cal):
    var1 = (adc_T / 16384.0 - cal['dig_T1'] / 1024.0) * cal['dig_T2']
    var2 = ((adc_T / 131072.0 - cal['dig_T1'] / 8192.0) ** 2) * cal['dig_T3']
    t_fine = var1 + var2
    return t_fine / 5120.0, t_fine


def bme280_compensate_pressure(adc_P, t_fine, cal):
    var1 = t_fine / 2.0 - 64000.0
    var2 = var1 * var1 * cal['dig_P6'] / 32768.0
    var2 = var2 + var1 * cal['dig_P5'] * 2.0
    var2 = var2 / 4.0 + cal['dig_P4'] * 65536.0
    var1 = (cal['dig_P3'] * var1 * var1 / 524288.0 + cal['dig_P2'] * var1) / 524288.0
    var1 = (1.0 + var1 / 32768.0) * cal['dig_P1']
    if var1 == 0:
        return 0.0
    p = 1048576.0 - adc_P
    p = ((p - var2 / 4096.0) * 6250.0) / var1
    var1 = cal['dig_P9'] * p * p / 2147483648.0
    var2 = p * cal['dig_P8'] / 32768.0
    p = p + (var1 + var2 + cal['dig_P7']) / 16.0
    return p / 100.0


def bme280_compensate_humidity(adc_H, t_fine, cal):
    h = t_fine - 76800.0
    if h == 0:
        return 0.0
    h = (adc_H - (cal['dig_H4'] * 64.0 + (cal['dig_H5'] / 16384.0) * h)) * \
        (cal['dig_H2'] / 65536.0 * (1.0 + cal['dig_H6'] / 67108864.0 * h *
        (1.0 + cal['dig_H3'] / 67108864.0 * h)))
    h = h * (1.0 - cal['dig_H1'] * h / 524288.0)
    return max(0.0, min(100.0, h))


# ============================================================
# Step 5  —  MPU6050 decoding
# ============================================================

def decode_mpu6050_config(gyro_cfg, accel_cfg):
    fs_sel = (gyro_cfg >> 3) & 0x03
    afs_sel = (accel_cfg >> 3) & 0x03
    return {
        'accel_range': ACCEL_RANGES[afs_sel],
        'gyro_range': GYRO_RANGES[fs_sel],
        'afs_sel': afs_sel,
        'fs_sel': fs_sel,
    }


def decode_mpu6050_sensor(data, cfg):
    def s16be(b, o):
        v = (b[o] << 8) | b[o+1]
        return v - 65536 if v >= 32768 else v

    raw = {
        'accel_x': s16be(data, 0),
        'accel_y': s16be(data, 2),
        'accel_z': s16be(data, 4),
        'gyro_x': s16be(data, 8),
        'gyro_y': s16be(data, 10),
        'gyro_z': s16be(data, 12),
    }
    a_s = ACCEL_SENS[cfg['afs_sel']]
    g_s = GYRO_SENS[cfg['fs_sel']]
    cal = {
        'accel_g': {k: raw[f'accel_{k}'] / a_s for k in 'xyz'},
        'gyro_dps': {k: raw[f'gyro_{k}'] / g_s for k in 'xyz'},
    }
    return raw, cal


# ============================================================
# Main
# ============================================================

def main():
    # Decode capture
    raw_output = decode_capture()
    transactions = parse_annotations(raw_output)

    # Discover devices
    responding = set()
    failed = set()
    for txn in transactions:
        for ph in txn['phases']:
            a = ph['address']
            if a is None:
                continue
            if txn['anomaly'] and txn['anomaly']['type'] == 'address_nack':
                failed.add(a)
            else:
                responding.add(a)
    failed -= responding

    # Extract register data
    bme_reads = extract_register_reads(transactions, 0x76)
    mpu_reads = extract_register_reads(transactions, 0x69)

    # --- BME280 ---
    bme_chip_id = bme_reads.get(0xD0, [0])[0]
    bme_cal = decode_bme280_calibration(
        bme_reads.get(0x88, [0]*26),
        bme_reads.get(0xE1, [0]*7),
    )
    adc_T, adc_P, adc_H = decode_bme280_raw(bme_reads.get(0xF7, [0]*8))
    temp_c, t_fine = bme280_compensate_temperature(adc_T, bme_cal)
    press_hpa = bme280_compensate_pressure(adc_P, t_fine, bme_cal)
    humid_pct = bme280_compensate_humidity(adc_H, t_fine, bme_cal)

    # --- MPU6050 ---
    mpu_who = mpu_reads.get(0x75, [0])[0]
    mpu_cfg = decode_mpu6050_config(
        mpu_reads.get(0x1B, [0])[0],
        mpu_reads.get(0x1C, [0])[0],
    )
    mpu_raw, mpu_cal = decode_mpu6050_sensor(
        mpu_reads.get(0x3B, [0]*14), mpu_cfg,
    )

    # Anomalies
    anomalies = []
    for idx, txn in enumerate(transactions):
        if txn['anomaly']:
            a = txn['anomaly'].copy()
            a['transaction_index'] = idx
            a['address'] = f"0x{a['address']:02x}"
            anomalies.append(a)

    n_ok = sum(1 for t in transactions if t['anomaly'] is None)
    n_fail = sum(1 for t in transactions if t['anomaly'] is not None)

    output = {
        'devices_found': [
            {'address': f'0x{a:02x}', 'type': 'read_write'}
            for a in sorted(responding)
        ],
        'failed_addresses': [f'0x{a:02x}' for a in sorted(failed)],
        'bme280': {
            'chip_id': f'0x{bme_chip_id:02x}',
            'calibration': bme_cal,
            'raw_adc': {
                'temperature': adc_T,
                'pressure': adc_P,
                'humidity': adc_H,
            },
            'compensated': {
                'temperature_c': round(temp_c, 2),
                'pressure_hpa': round(press_hpa, 2),
                'humidity_pct': round(humid_pct, 2),
            },
        },
        'mpu6050': {
            'who_am_i': f'0x{mpu_who:02x}',
            'config': {
                'accel_range': mpu_cfg['accel_range'],
                'gyro_range': mpu_cfg['gyro_range'],
            },
            'raw': mpu_raw,
            'calibrated': mpu_cal,
        },
        'anomalies': anomalies,
        'summary': {
            'total_transactions': len(transactions),
            'successful_transactions': n_ok,
            'failed_transactions': n_fail,
            'total_anomalies': len(anomalies),
            'devices_responding': len(responding),
        },
    }

    with open('/app/output.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"Analysis complete -> /app/output.json")
    print(f"  Devices: {len(responding)} responding, {len(failed)} failed")
    print(f"  BME280:  T={temp_c:.2f}C  P={press_hpa:.2f}hPa  H={humid_pct:.2f}%")
    print(f"  Anomalies: {len(anomalies)}")


if __name__ == '__main__':
    main()
