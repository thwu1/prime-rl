#!/usr/bin/env python3
"""Generate synthetic LiDAR survey data for terrain analysis."""

import base64
import json
import os
import struct
import zlib

import numpy as np

np.random.seed(20240101)

ORIGIN_X = 500000.0
ORIGIN_Y = 4500000.0
AREA_SIZE = 200.0

# Encoded terrain model — do not modify
_SM = "eNpjYACDSAcGNMAIoUSgEnZwBUwQigNNh6UDM4TxwR5Ca0AV6DkAAJ3hBDg="


def _load_model():
    raw = zlib.decompress(base64.b64decode(_SM))
    terms = []
    off = 0
    while off < len(raw):
        t = struct.unpack_from('<B', raw, off)[0]
        off += 1
        a, fx, fy = struct.unpack_from('<3d', raw, off)
        off += 24
        terms.append((t, a, fx, fy))
    return terms


_TERMS = _load_model()


def _eval_surface(x, y):
    """Evaluate terrain elevation at given coordinates."""
    xl = x - ORIGIN_X
    yl = y - ORIGIN_Y
    z = np.zeros_like(x, dtype=np.float64) if hasattr(x, '__len__') else 0.0
    for t, a, fx, fy in _TERMS:
        if t == 0:
            z = z + a
        elif t == 1:
            z = z + a * np.sin(xl / fx)
        elif t == 2:
            z = z + a * np.cos(yl / fy)
        elif t == 3:
            z = z + a * np.sin(xl / fx) * np.cos(yl / fy)
    return z


def _gen_points():
    """Generate point cloud with terrain, vegetation, building, and noise."""
    px, py, pz = [], [], []

    # Terrain surface samples
    n_g = 50000
    gx = np.random.uniform(ORIGIN_X, ORIGIN_X + AREA_SIZE, n_g)
    gy = np.random.uniform(ORIGIN_Y, ORIGIN_Y + AREA_SIZE, n_g)
    gz = _eval_surface(gx, gy) + np.random.normal(0, 0.05, n_g)
    px.append(gx); py.append(gy); pz.append(gz)

    # Vegetation clusters
    n_t = 15
    tcx = np.random.uniform(10, AREA_SIZE - 10, n_t) + ORIGIN_X
    tcy = np.random.uniform(10, AREA_SIZE - 10, n_t) + ORIGIN_Y
    th = np.random.uniform(4, 18, n_t)
    tr = np.random.uniform(2, 6, n_t)
    for i in range(n_t):
        npts = int(np.random.uniform(300, 800))
        ang = np.random.uniform(0, 2 * np.pi, npts)
        rad = tr[i] * np.sqrt(np.random.uniform(0, 1, npts))
        hts = np.random.uniform(0.5, th[i], npts)
        rad *= (1.0 - 0.5 * hts / th[i])
        tx = tcx[i] + rad * np.cos(ang)
        ty = tcy[i] + rad * np.sin(ang)
        tz = _eval_surface(tx, ty) + hts
        px.append(tx); py.append(ty); pz.append(tz)

    # Structure footprint
    bcx, bcy = ORIGIN_X + 120.0, ORIGIN_Y + 80.0
    n_r = 2000
    bx = np.random.uniform(bcx - 12.5, bcx + 12.5, n_r)
    by = np.random.uniform(bcy - 9.0, bcy + 9.0, n_r)
    rb = _eval_surface(np.full(n_r, bcx), np.full(n_r, bcy))
    bz = rb + 8.0 + np.random.normal(0, 0.03, n_r)
    px.append(bx); py.append(by); pz.append(bz)

    # High noise
    n_hn = 400
    px.append(np.random.uniform(ORIGIN_X, ORIGIN_X + AREA_SIZE, n_hn))
    py.append(np.random.uniform(ORIGIN_Y, ORIGIN_Y + AREA_SIZE, n_hn))
    pz.append(np.random.uniform(200, 500, n_hn))

    # Low noise
    n_ln = 200
    px.append(np.random.uniform(ORIGIN_X, ORIGIN_X + AREA_SIZE, n_ln))
    py.append(np.random.uniform(ORIGIN_Y, ORIGIN_Y + AREA_SIZE, n_ln))
    pz.append(np.random.uniform(-50, 50, n_ln))

    ax = np.concatenate(px)
    ay = np.concatenate(py)
    az = np.concatenate(pz)
    idx = np.random.permutation(len(ax))
    return ax[idx], ay[idx], az[idx]


def _write_las(filename, x, y, z):
    """Write a minimal LAS 1.2 Format 0 file (all points unclassified)."""
    n = len(x)
    scale = 0.001
    off_x = float(np.floor(np.min(x)))
    off_y = float(np.floor(np.min(y)))
    off_z = float(np.floor(np.min(z)))

    xi = np.round((x - off_x) / scale).astype(np.int32)
    yi = np.round((y - off_y) / scale).astype(np.int32)
    zi = np.round((z - off_z) / scale).astype(np.int32)

    hdr_size = 227
    pt_len = 20

    header = b''
    header += b'LASF'
    header += struct.pack('<H', 0)
    header += struct.pack('<H', 0)
    header += b'\x00' * 16
    header += struct.pack('<BB', 1, 2)
    header += struct.pack('<32s', b'Synthetic Survey')
    header += struct.pack('<32s', b'generate_input.py')
    header += struct.pack('<HH', 195, 2025)
    header += struct.pack('<H', hdr_size)
    header += struct.pack('<I', hdr_size)
    header += struct.pack('<I', 0)
    header += struct.pack('<B', 0)
    header += struct.pack('<H', pt_len)
    header += struct.pack('<I', n)
    header += struct.pack('<5I', n, 0, 0, 0, 0)
    header += struct.pack('<ddd', scale, scale, scale)
    header += struct.pack('<ddd', off_x, off_y, off_z)
    header += struct.pack('<dd', float(np.max(x)), float(np.min(x)))
    header += struct.pack('<dd', float(np.max(y)), float(np.min(y)))
    header += struct.pack('<dd', float(np.max(z)), float(np.min(z)))

    assert len(header) == 227

    pt_dtype = np.dtype([
        ('X', '<i4'), ('Y', '<i4'), ('Z', '<i4'),
        ('Intensity', '<u2'), ('Flags', '<u1'),
        ('Classification', '<u1'), ('ScanAngle', '<i1'),
        ('UserData', '<u1'), ('PointSourceID', '<u2'),
    ])
    pts = np.zeros(n, dtype=pt_dtype)
    pts['X'] = xi
    pts['Y'] = yi
    pts['Z'] = zi
    pts['Flags'] = 0x09
    pts['Classification'] = 0
    pts['PointSourceID'] = 1

    with open(filename, 'wb') as f:
        f.write(header)
        f.write(pts.tobytes())


def main():
    os.makedirs('/app/data', exist_ok=True)
    x, y, z = _gen_points()
    _write_las('/app/data/survey.las', x, y, z)
    print(f"Generated {len(x)} points -> /app/data/survey.las")


if __name__ == '__main__':
    main()
