#!/usr/bin/env python3
"""Generate synthetic I2C logic analyzer capture in sigrok session format (.sr)."""

import zipfile


class I2CBusSimulator:
    """Generates raw I2C bus signals (SCL/SDA) for sigrok session files.

    Each sample is one byte: bit 0 = SCL (probe1), bit 1 = SDA (probe2).
    Sample rate: 1 MHz  =>  100 kHz I2C  =>  10 samples per bit period.
    """

    def __init__(self):
        self.samples = []
        self.scl = 1
        self.sda = 1

    def _emit(self, n, scl=None, sda=None):
        if scl is not None:
            self.scl = scl
        if sda is not None:
            self.sda = sda
        for _ in range(n):
            self.samples.append((self.scl, self.sda))

    def idle(self, n=50):
        self._emit(n, scl=1, sda=1)

    # ---- I2C conditions ----

    def start(self):
        """START condition: SDA falls while SCL is HIGH."""
        self._emit(5, scl=1, sda=1)
        self._emit(5, scl=1, sda=0)   # SDA falls -> START
        self._emit(5, scl=0, sda=0)   # SCL falls, prepare for first bit

    def repeated_start(self):
        """Repeated START from mid-transaction (prev bit left SCL=1)."""
        self._emit(3, scl=0)           # pull SCL LOW first (safe for SDA)
        self._emit(3, sda=1)           # release SDA HIGH
        self._emit(4, scl=1)           # SCL rises  (SDA=1, stable)
        self._emit(4, sda=0)           # SDA falls  -> START
        self._emit(3, scl=0)           # SCL falls

    def stop(self):
        """STOP condition: SDA rises while SCL is HIGH."""
        self._emit(3, scl=0)           # pull SCL LOW (safe for SDA)
        self._emit(3, sda=0)           # ensure SDA LOW
        self._emit(4, scl=1)           # SCL rises  (SDA=0, stable)
        self._emit(4, sda=1)           # SDA rises  -> STOP

    # ---- bit / byte clocking ----

    def _clock_bit(self, bit):
        """Clock one bit: set SDA while SCL LOW, then pulse SCL HIGH."""
        self._emit(5, scl=0, sda=bit)  # setup: SDA = bit, SCL LOW
        self._emit(5, scl=1)           # sample: SCL HIGH

    def send_byte(self, val, ack):
        """Transmit 8 bits MSB-first, then ACK (SDA=0) or NACK (SDA=1)."""
        for i in range(7, -1, -1):
            self._clock_bit((val >> i) & 1)
        self._clock_bit(0 if ack else 1)

    # ---- transaction helpers ----

    def write_txn(self, addr7, reg, data):
        """Write transaction: S addr+W reg data... P"""
        self.start()
        self.send_byte((addr7 << 1) | 0, ack=True)
        self.send_byte(reg, ack=True)
        for b in data:
            self.send_byte(b, ack=True)
        self.stop()
        self.idle(30)

    def read_txn(self, addr7, reg, data):
        """Register read with repeated START: S addr+W reg Sr addr+R data... P"""
        self.start()
        self.send_byte((addr7 << 1) | 0, ack=True)
        self.send_byte(reg, ack=True)
        self.repeated_start()
        self.send_byte((addr7 << 1) | 1, ack=True)
        for i, b in enumerate(data):
            self.send_byte(b, ack=(i < len(data) - 1))  # NACK last byte
        self.stop()
        self.idle(30)

    def addr_nack(self, addr7):
        """Address probe with NACK (device not present)."""
        self.start()
        self.send_byte((addr7 << 1) | 0, ack=False)
        self.stop()
        self.idle(30)

    def data_nack_write(self, addr7, reg, data_byte):
        """Write transaction where the data byte is NACKed by slave."""
        self.start()
        self.send_byte((addr7 << 1) | 0, ack=True)
        self.send_byte(reg, ack=True)
        self.send_byte(data_byte, ack=False)
        self.stop()
        self.idle(30)

    # ---- output ----

    def write_sr(self, path, sample_rate=1000000):
        """Write sigrok session file (.sr = ZIP with metadata + raw data)."""
        metadata = (
            "[global]\n"
            "sigrok version=0.5.2\n"
            "\n"
            "[device 1]\n"
            "capturefile=logic-1\n"
            "total probes=2\n"
            f"samplerate={sample_rate}\n"
            "probe1=SCL\n"
            "probe2=SDA\n"
            "unitsize=1\n"
            "total analog=0\n"
        )
        raw = bytes((s[0] & 1) | ((s[1] & 1) << 1) for s in self.samples)
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('version', '2')
            zf.writestr('metadata', metadata)
            zf.writestr('logic-1-1', raw)


# ============================================================
# Sensor data constants
# ============================================================

BME280 = 0x76
MPU6050 = 0x69

# BME280 calibration block 1: registers 0x88-0xA1 (26 bytes, little-endian)
# dig_T1=27504 dig_T2=26435 dig_T3=-1000
# dig_P1=36477 dig_P2=-10685 dig_P3=3024 dig_P4=2855 dig_P5=140
# dig_P6=-7 dig_P7=15500 dig_P8=-14600 dig_P9=6000
# unused=0x00 dig_H1=75
bme_cal1 = [
    0x70, 0x6B,  # dig_T1 = 27504
    0x43, 0x67,  # dig_T2 = 26435
    0x18, 0xFC,  # dig_T3 = -1000
    0x7D, 0x8E,  # dig_P1 = 36477
    0x43, 0xD6,  # dig_P2 = -10685
    0xD0, 0x0B,  # dig_P3 = 3024
    0x27, 0x0B,  # dig_P4 = 2855
    0x8C, 0x00,  # dig_P5 = 140
    0xF9, 0xFF,  # dig_P6 = -7
    0x8C, 0x3C,  # dig_P7 = 15500
    0xF8, 0xC6,  # dig_P8 = -14600
    0x70, 0x17,  # dig_P9 = 6000
    0x00,        # unused
    0x4B,        # dig_H1 = 75
]

# BME280 calibration block 2: registers 0xE1-0xE7 (7 bytes)
# dig_H2=370 dig_H3=0 dig_H4=313 dig_H5=50 dig_H6=30
bme_cal2 = [
    0x72, 0x01,  # dig_H2 = 370
    0x00,        # dig_H3 = 0
    0x13,        # H4[11:4] = 19
    0x29,        # H4[3:0]=9 | H5[3:0]=2 -> H4=313, H5=50
    0x03,        # H5[11:4] = 3
    0x1E,        # dig_H6 = 30
]

# BME280 raw measurements: registers 0xF7-0xFE (8 bytes)
# adc_P = 415744, adc_T = 520192, adc_H = 28000
bme_raw = [
    0x65, 0x80, 0x00,  # pressure
    0x7F, 0x00, 0x00,  # temperature
    0x6D, 0x60,        # humidity
]

# MPU6050 sensor burst: registers 0x3B-0x48 (14 bytes, big-endian)
# accel: 819, -328, 16548  temp: 0  gyro: 197, -105, 39
mpu_sensor = [
    0x03, 0x33,  # accel_x =  819
    0xFE, 0xB8,  # accel_y = -328
    0x40, 0xA4,  # accel_z = 16548
    0x00, 0x00,  # temperature (unused in output)
    0x00, 0xC5,  # gyro_x  =  197
    0xFF, 0x97,  # gyro_y  = -105
    0x00, 0x27,  # gyro_z  =   39
]

# ============================================================
# Build capture: 13 transactions, 2 anomalies
# ============================================================

sim = I2CBusSimulator()
sim.idle(100)

# Txn 0: BME280 read chip ID (reg 0xD0 -> 0x60)
sim.read_txn(BME280, 0xD0, [0x60])
# Txn 1: BME280 write ctrl_hum (reg 0xF2 <- 0x01)
sim.write_txn(BME280, 0xF2, [0x01])
# Txn 2: BME280 write ctrl_meas (reg 0xF4 <- 0x27)
sim.write_txn(BME280, 0xF4, [0x27])
# Txn 3: BME280 read calibration block 1 (reg 0x88, 26 bytes)
sim.read_txn(BME280, 0x88, bme_cal1)
# Txn 4: BME280 read calibration block 2 (reg 0xE1, 7 bytes)
sim.read_txn(BME280, 0xE1, bme_cal2)
# Txn 5: BME280 read raw measurements (reg 0xF7, 8 bytes)
sim.read_txn(BME280, 0xF7, bme_raw)
# Txn 6: ANOMALY — address NACK (device 0x50 not on bus)
sim.addr_nack(0x50)
# Txn 7: MPU6050 write PWR_MGMT_1 (reg 0x6B <- 0x00, wake up)
sim.write_txn(MPU6050, 0x6B, [0x00])
# Txn 8: MPU6050 read WHO_AM_I (reg 0x75 -> 0x68)
sim.read_txn(MPU6050, 0x75, [0x68])
# Txn 9: MPU6050 read GYRO_CONFIG (reg 0x1B -> 0x00)
sim.read_txn(MPU6050, 0x1B, [0x00])
# Txn 10: MPU6050 read ACCEL_CONFIG (reg 0x1C -> 0x00)
sim.read_txn(MPU6050, 0x1C, [0x00])
# Txn 11: ANOMALY — data NACK writing to read-only WHO_AM_I register
sim.data_nack_write(MPU6050, 0x75, 0x00)
# Txn 12: MPU6050 read sensor burst (reg 0x3B, 14 bytes)
sim.read_txn(MPU6050, 0x3B, mpu_sensor)

sim.write_sr('/app/capture.sr')
print(f"Generated /app/capture.sr: {len(sim.samples)} samples, "
      f"{len(sim.samples) + 256} bytes approx")
