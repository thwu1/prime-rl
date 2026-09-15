#!/usr/bin/env python3
"""Radiometric calibration: convert raw DN values to TOA reflectance.

Reads binary .cal calibration files and applies per-band gain/offset
correction to convert raw digital numbers to top-of-atmosphere reflectance.
Calibrated arrays are saved as .npy files for downstream processing.
"""
import os
import struct
from pathlib import Path

import numpy as np
from PIL import Image

FEATURE_DIR = Path("/app/data/features")
CAL_DIR = Path("/app/data/calibration")
OUTPUT_DIR = Path("/app/calibrated")


def parse_cal_file(cal_path):
    """Parse a binary .cal file and return calibration coefficients.

    Returns dict mapping band names to (gain, offset) tuples.
    See /app/docs/FORMAT_SPEC.md for the file format description.
    """
    coeffs = {}
    with open(cal_path, 'rb') as f:
        magic = f.read(4)
        if magic != b'SCAL':
            raise ValueError(
                "Invalid calibration file: expected SCAL magic, got {}".format(
                    magic))

        version = struct.unpack('>H', f.read(2))[0]
        n_bands = struct.unpack('>H', f.read(2))[0]

        for _ in range(n_bands):
            name_raw = f.read(16)
            band_name = name_raw.rstrip(b'\x00').decode('ascii')
            gain = struct.unpack('>d', f.read(8))[0]
            offset = struct.unpack('>d', f.read(8))[0]
            coeffs[band_name] = (gain, offset)

    return coeffs


def calibrate_band(dn_array, gain, offset):
    """Apply radiometric calibration to a single band.

    Formula: TOA = gain * DN + offset
    """
    dn = dn_array.astype(np.float64)
    toa = offset * dn + gain
    return toa


def main():
    if not FEATURE_DIR.exists():
        print("ERROR: Feature directory not found: {}".format(FEATURE_DIR))
        raise SystemExit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    chips = sorted(d for d in FEATURE_DIR.iterdir() if d.is_dir())
    if not chips:
        print("ERROR: No chip directories found in {}".format(FEATURE_DIR))
        raise SystemExit(1)

    print("Calibrating {} chips...".format(len(chips)))

    for chip_dir in chips:
        chip_id = chip_dir.name
        cal_path = CAL_DIR / "{}.cal".format(chip_id)

        if not cal_path.exists():
            print("  WARNING: No calibration file for {}".format(chip_id))
            continue

        coeffs = parse_cal_file(cal_path)
        out_dir = OUTPUT_DIR / chip_id
        os.makedirs(out_dir, exist_ok=True)

        for band_name, (gain, offset) in coeffs.items():
            band_path = chip_dir / "{}.tif".format(band_name)
            if not band_path.exists():
                print("  WARNING: Missing {} in {}".format(
                    band_name, chip_id))
                continue

            dn = np.array(Image.open(band_path))
            toa = calibrate_band(dn, gain, offset)
            np.save(str(out_dir / "{}.npy".format(band_name)), toa)

        print("  Calibrated: {}".format(chip_id))

    print("Calibration complete.")


if __name__ == "__main__":
    main()
