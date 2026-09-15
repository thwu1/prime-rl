#!/usr/bin/env python3
"""Generate synthetic raw microscopy data with heterogeneous binary formats."""
import json
import os
import numpy as np


def pack_12bit(data_uint16):
    """Pack uint16 values (12-bit range) into 3-byte pairs, MSB-first."""
    flat = data_uint16.ravel().astype(np.uint16)
    n = len(flat)
    assert n % 2 == 0, "Need even number of values for 12-bit packing"
    a = flat[0::2]
    b = flat[1::2]
    b0 = ((a >> 4) & 0xFF).astype(np.uint8)
    b1 = (((a & 0x0F) << 4) | ((b >> 8) & 0x0F)).astype(np.uint8)
    b2 = (b & 0xFF).astype(np.uint8)
    packed = np.column_stack([b0, b1, b2]).ravel()
    return packed.tobytes()


def main():
    os.makedirs('/app/acquisition', exist_ok=True)
    np.random.seed(42)

    T, Z, Y, X = 2, 4, 384, 512
    yy, xx = np.meshgrid(np.arange(Y), np.arange(X), indexing='ij')

    # ── Channel 0: DAPI ── uint16, big-endian, TZYX ──────────────
    ch0 = np.random.randint(200, 3000, (T, Z, Y, X), dtype=np.uint16)
    for t in range(T):
        for z in range(Z):
            cy, cx = Y // 2 + t * 20, X // 2 - z * 15
            blob = (5000 * np.exp(
                -((yy - cy)**2 + (xx - cx)**2) / (2 * 80**2)
            )).astype(np.uint16)
            ch0[t, z] = np.clip(
                ch0[t, z].astype(np.int32) + blob, 0, 65535
            ).astype(np.uint16)
    ch0.astype('>u2').tofile('/app/acquisition/dapi.bin')

    # ── Channel 1: GFP ── float32, with ASCII header, TZYX ──────
    ch1 = np.random.uniform(0.05, 0.25, (T, Z, Y, X)).astype(np.float32)
    for t in range(T):
        for z in range(Z):
            cy, cx = Y // 3 + t * 15, X // 3 + z * 10
            blob = 0.7 * np.exp(
                -((yy - cy)**2 + (xx - cx)**2) / (2 * 60**2)
            )
            ch1[t, z] = np.clip(
                ch1[t, z] + blob.astype(np.float32), 0.0, 1.0
            )
    header_text = (
        b"INSTRUMENT:SpinDisk-7200\n"
        b"SERIAL:SD72-0042\n"
        b"GAIN:1.0\n"
        b"OFFSET:0.0\n"
        b"EXPOSURE_MS:100\n"
        b"LASER_POWER:15.0\n"
        b"CHANNEL:GFP\n"
        b"FILTER:525/50\n"
        b"BINNING:1x1\n"
        b"TEMPERATURE:23.5C\n"
        b"DATE:2024-03-15T10:32:15\n"
        b"NOTES:Standard_acquisition_protocol\n"
        b"END_HEADER\n"
    )
    header_size = ((len(header_text) + 63) // 64) * 64
    header = header_text + b'\x00' * (header_size - len(header_text))
    with open('/app/acquisition/gfp.bin', 'wb') as f:
        f.write(header)
        ch1.tofile(f)

    # ── Channel 2: mCherry ── uint16 LE, stored TZXY, with drift ─
    ch2 = np.random.randint(100, 2000, (T, Z, Y, X), dtype=np.uint16)
    for t in range(T):
        for z in range(Z):
            cy, cx = 2 * Y // 3 - t * 18, 2 * X // 3 + z * 20
            blob = (4000 * np.exp(
                -((yy - cy)**2 + (xx - cx)**2) / (2 * 70**2)
            )).astype(np.uint16)
            ch2[t, z] = np.clip(
                ch2[t, z].astype(np.int32) + blob, 0, 65535
            ).astype(np.uint16)
    # Store in TZXY order (X before Y)
    ch2.transpose(0, 1, 3, 2).copy().tofile('/app/acquisition/mcherry.bin')

    # ── Channel 3: TdTomato ── 12-bit packed, TZYX ───────────────
    ch3 = np.random.randint(50, 2000, (T, Z, Y, X), dtype=np.uint16)
    for t in range(T):
        for z in range(Z):
            cy = Y // 2 + t * 10 - z * 8
            cx = X // 2 + t * 12 + z * 5
            blob = (3000 * np.exp(
                -((yy - cy)**2 + (xx - cx)**2) / (2 * 90**2)
            )).astype(np.uint16)
            ch3[t, z] = np.clip(
                ch3[t, z].astype(np.int32) + blob, 0, 4095
            ).astype(np.uint16)
    packed_data = pack_12bit(ch3)
    with open('/app/acquisition/tdtomato.bin', 'wb') as f:
        f.write(packed_data)

    # ── Acquisition log ──────────────────────────────────────────
    log = """\
Acquisition Log - Experiment 2024-03-15_01
==========================================
Instrument: Custom spinning-disk confocal (SpinDisk-7200)
Objective: 40x/1.3NA oil immersion
Image dimensions: 384 x 512 pixels (height x width, Y x X)
Z-stack: 4 planes, 1.5 um step
Timelapse: 2 frames, 30 s interval
Pixel size: 0.325 um (XY)

All channels store frames in TZYX dimension order (T slowest, X fastest)
unless noted otherwise. Default byte order is little-endian unless noted.

Channel Configuration
---------------------

Ch0 "DAPI" (405nm excitation, PMT):
  16-bit unsigned integer. Detector byte stream uses network byte order
  (big-endian). Raw binary, no file header.

Ch1 "GFP" (488nm excitation, analog PMT):
  32-bit IEEE 754 single-precision float, values in [0.0, 1.0].
  Little-endian. Binary file begins with an ASCII instrument header
  terminated by the line "END_HEADER", followed by null-byte padding
  to the next 64-byte-aligned file offset. Pixel data starts at that
  aligned offset.
  For unified 16-bit output: map [0,1] to [0, 65535] linearly,
  round to nearest integer, clamp to uint16.

Ch2 "mCherry" (561nm excitation, sCMOS):
  16-bit unsigned integer, little-endian. This detector scans in
  column-major order, producing TZXY storage layout (X dimension
  varies before Y in memory). Transpose spatial dimensions to
  standard TZYX for assembly.
  Stage drift: dy=+3, dx=-5 pixels relative to DAPI reference.
  Apply integer pixel translation to align; zero-fill borders.

Ch3 "TdTomato" (594nm excitation, 12-bit sCMOS):
  12-bit detector with packed binary storage. Adjacent sample pairs
  are packed into 3 bytes with big-endian bit ordering: first sample
  occupies the most significant bits. TZYX dimension order.
  Expand 12-bit values to 16-bit unsigned via 4-bit left shift.
"""
    with open('/app/acquisition/acquisition_log.txt', 'w') as f:
        f.write(log)

    # ── Calibration ──────────────────────────────────────────────
    calibration = {
        "channels": ["DAPI", "GFP", "mCherry", "TdTomato"],
        "dimensions": {"T": 2, "Z": 4, "Y": 384, "X": 512},
        "physical_size": {
            "X": {"value": 0.325, "unit": "\u00b5m"},
            "Y": {"value": 0.325, "unit": "\u00b5m"},
            "Z": {"value": 1.5, "unit": "\u00b5m"}
        },
        "time_interval": {"value": 30.0, "unit": "s"},
        "output": {
            "path": "/app/output.ome.tif",
            "format": "bigtiff",
            "tile_size": [256, 256],
            "compression": "deflate",
            "pyramid_levels": 3,
            "include_thumbnail": True
        },
        "analysis": {
            "path": "/app/analysis.json"
        }
    }
    with open('/app/acquisition/calibration.json', 'w') as f:
        json.dump(calibration, f, indent=2, ensure_ascii=False)

    print("Generated acquisition data in /app/acquisition/")
    for fname in ['dapi.bin', 'gfp.bin', 'mcherry.bin', 'tdtomato.bin']:
        path = f'/app/acquisition/{fname}'
        print(f"  {fname}: {os.path.getsize(path)} bytes")


if __name__ == '__main__':
    main()
