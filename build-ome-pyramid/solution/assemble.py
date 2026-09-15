#!/usr/bin/env python3
"""Assemble heterogeneous microscopy binary data into pyramidal OME-TIFF.

"""

import json
import os

import numpy as np
import tifffile


def find_header_end(filepath):
    """Find pixel data offset past END_HEADER marker, 64-byte aligned."""
    with open(filepath, 'rb') as f:
        content = f.read()
    marker = b'END_HEADER\n'
    pos = content.find(marker)
    if pos == -1:
        return 0
    end = pos + len(marker)
    return ((end + 63) // 64) * 64


def unpack_12bit(data_bytes, n_values):
    """Unpack MSB-first 12-bit packed pairs from 3-byte groups."""
    packed = np.frombuffer(data_bytes, dtype=np.uint8)
    b0 = packed[0::3].astype(np.uint16)
    b1 = packed[1::3].astype(np.uint16)
    b2 = packed[2::3].astype(np.uint16)
    a = (b0 << 4) | (b1 >> 4)
    b = ((b1 & 0x0F) << 8) | b2
    result = np.empty(n_values, dtype=np.uint16)
    result[0::2] = a[:n_values // 2]
    result[1::2] = b[:n_values // 2]
    return result


def apply_drift(data, dy, dx, fill_value=0):
    """Integer-pixel spatial translation with border fill."""
    h, w = data.shape[-2], data.shape[-1]
    out = np.full_like(data, fill_value)
    dy_s, dy_e = max(0, dy), min(h, h + dy)
    dx_s, dx_e = max(0, dx), min(w, w + dx)
    if dy_e > dy_s and dx_e > dx_s:
        out[..., dy_s:dy_e, dx_s:dx_e] = \
            data[..., dy_s - dy:dy_e - dy, dx_s - dx:dx_e - dx]
    return out


def downsample_2x(arr):
    """Area-averaged 2x spatial downsampling."""
    *lead, h, w = arr.shape
    nh, nw = h // 2, w // 2
    cropped = arr[..., :nh * 2, :nw * 2]
    reshaped = cropped.reshape(*lead, nh, 2, nw, 2)
    return reshaped.astype(np.float64).mean(axis=(-3, -1)).round().astype(arr.dtype)


def main():
    base = '/app/acquisition'

    with open(f'{base}/calibration.json') as f:
        cal = json.load(f)

    T = cal['dimensions']['T']
    Z = cal['dimensions']['Z']
    Y = cal['dimensions']['Y']
    X = cal['dimensions']['X']
    n_pixels = T * Z * Y * X
    ch_names = cal['channels']

    # ── Ch0 DAPI: big-endian uint16 ──────────────────────────────
    ch0 = np.fromfile(
        f'{base}/dapi.bin', dtype='>u2'
    ).reshape(T, Z, Y, X).astype(np.uint16)

    # ── Ch1 GFP: float32 with ASCII header, rescale to uint16 ───
    header_offset = find_header_end(f'{base}/gfp.bin')
    with open(f'{base}/gfp.bin', 'rb') as f:
        f.seek(header_offset)
        ch1_raw = np.frombuffer(f.read(), dtype='<f4').reshape(T, Z, Y, X)
    ch1 = np.clip(
        ch1_raw.astype(np.float64) * 65535.0, 0, 65535
    ).round().astype(np.uint16)

    # ── Ch2 mCherry: uint16 LE in TZXY order, transpose + drift ─
    ch2_raw = np.fromfile(
        f'{base}/mcherry.bin', dtype='<u2'
    ).reshape(T, Z, X, Y)  # TZXY storage
    ch2_yx = ch2_raw.transpose(0, 1, 3, 2)  # -> TZYX
    ch2 = apply_drift(ch2_yx, dy=3, dx=-5)

    # ── Ch3 TdTomato: 12-bit packed, left-shift to uint16 ───────
    with open(f'{base}/tdtomato.bin', 'rb') as f:
        packed_data = f.read()
    ch3_12 = unpack_12bit(packed_data, n_pixels).reshape(T, Z, Y, X)
    ch3 = (ch3_12.astype(np.uint16) << 4)

    # ── Assemble TCZYX ───────────────────────────────────────────
    data = np.stack([ch0, ch1, ch2, ch3], axis=1)
    _, C, _, _, _ = data.shape

    # ── Pyramid ──────────────────────────────────────────────────
    n_levels = cal['output']['pyramid_levels']
    levels = [data]
    current = data
    for _ in range(n_levels - 1):
        current = downsample_2x(current)
        levels.append(current)

    # ── Write pyramidal OME-TIFF ─────────────────────────────────
    tile_h, tile_w = cal['output']['tile_size']
    compression = cal['output']['compression']
    ps = cal['physical_size']

    ome_meta = {
        'axes': 'TCZYX',
        'PhysicalSizeX': ps['X']['value'],
        'PhysicalSizeXUnit': ps['X']['unit'],
        'PhysicalSizeY': ps['Y']['value'],
        'PhysicalSizeYUnit': ps['Y']['unit'],
        'PhysicalSizeZ': ps['Z']['value'],
        'PhysicalSizeZUnit': ps['Z']['unit'],
        'TimeIncrement': cal['time_interval']['value'],
        'TimeIncrementUnit': cal['time_interval']['unit'],
        'Channel': {'Name': ch_names},
    }

    write_opts = dict(
        photometric='minisblack',
        tile=(tile_h, tile_w),
        compression=compression,
    )

    out_path = cal['output']['path']
    with tifffile.TiffWriter(out_path, bigtiff=True) as tif:
        tif.write(
            data,
            subifds=n_levels - 1,
            resolution=(1e4 / ps['X']['value'], 1e4 / ps['Y']['value']),
            resolutionunit='CENTIMETER',
            metadata=ome_meta,
            **write_opts,
        )
        for i in range(1, n_levels):
            mag = 2 ** i
            tif.write(
                levels[i],
                subfiletype=1,
                resolution=(
                    1e4 / (ps['X']['value'] * mag),
                    1e4 / (ps['Y']['value'] * mag),
                ),
                resolutionunit='CENTIMETER',
                **write_opts,
            )
        if cal['output'].get('include_thumbnail', False):
            thumb = data[0, 0, 0, ::8, ::8]
            tif.write(thumb, metadata={'Name': 'thumbnail'})

    # ── Analysis report ──────────────────────────────────────────
    analysis = {
        'dimensions': {'T': T, 'C': C, 'Z': Z, 'Y': Y, 'X': X},
        'channels': [],
        'pyramid_levels': [],
        'format': {
            'type': 'BigTIFF',
            'compression': compression,
            'tile_size': [tile_h, tile_w],
        },
    }
    for i, name in enumerate(ch_names):
        ch_data = data[:, i]
        analysis['channels'].append({
            'name': name,
            'min': int(ch_data.min()),
            'max': int(ch_data.max()),
            'mean': float(ch_data.astype(np.float64).mean()),
            'std': float(ch_data.astype(np.float64).std()),
        })
    for i, lvl in enumerate(levels):
        analysis['pyramid_levels'].append({
            'level': i,
            'shape': list(lvl.shape),
            'downsample_factor': 2 ** i,
        })

    with open(cal['analysis']['path'], 'w') as f:
        json.dump(analysis, f, indent=2)

    print(f'Written {out_path} ({os.path.getsize(out_path)} bytes)')
    print(f'Written {cal["analysis"]["path"]}')


if __name__ == '__main__':
    main()
