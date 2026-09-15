#!/usr/bin/env python3
"""Build pyramidal OME-TIFF from raw microscopy data.

"""

import json
import os

import numpy as np
import tifffile


DTYPE_MAP = {'uint16': 'u2', 'float32': 'f4', 'uint8': 'u1'}


def read_channel(ch_info, base_dir):
    """Read a raw binary channel and return as uint16 array in TZYX order."""
    filepath = os.path.join(base_dir, ch_info['file'])

    # Build the numpy dtype with correct byte order
    bo = '>' if ch_info['byte_order'] == 'big' else '<'
    file_dtype = np.dtype(f"{bo}{DTYPE_MAP[ch_info['dtype']]}")

    data = np.fromfile(filepath, dtype=file_dtype).reshape(ch_info['shape'])

    # Convert to native byte order
    native_dtype = np.dtype(ch_info['dtype'])
    data = data.astype(native_dtype)

    # Reorder dimensions to TZYX
    if ch_info['dimension_order'] == 'TZXY':
        data = data.transpose(0, 1, 3, 2)

    # Rescale float data to uint16 if requested
    if 'rescale' in ch_info:
        r = ch_info['rescale']
        in_lo, in_hi = r['input_range']
        out_lo, out_hi = r['output_range']
        data = data.astype(np.float64)
        data = (data - in_lo) / (in_hi - in_lo) * (out_hi - out_lo) + out_lo
        data = np.clip(data, out_lo, out_hi).round().astype(np.uint16)
    else:
        data = data.astype(np.uint16)

    # Apply spatial correction (translation) if specified
    if 'spatial_correction' in ch_info:
        sc = ch_info['spatial_correction']
        dy, dx = sc['dy'], sc['dx']
        fv = sc.get('fill_value', 0)
        H, W = data.shape[-2], data.shape[-1]

        result = np.full_like(data, fv)

        # output[y,x] = input[y - dy, x - dx]
        dy_s = max(0, dy)
        dy_e = min(H, H + dy)
        dx_s = max(0, dx)
        dx_e = min(W, W + dx)

        if dy_e > dy_s and dx_e > dx_s:
            result[..., dy_s:dy_e, dx_s:dx_e] = \
                data[..., dy_s - dy:dy_e - dy, dx_s - dx:dx_e - dx]

        data = result

    return data


def downsample_2x(arr):
    """Area-averaged 2x downsampling on the last two spatial dimensions."""
    *lead, H, W = arr.shape
    nH, nW = H // 2, W // 2
    cropped = arr[..., :nH * 2, :nW * 2]
    reshaped = cropped.reshape(*lead, nH, 2, nW, 2)
    return reshaped.astype(np.float64).mean(axis=(-3, -1)).round().astype(arr.dtype)


def main():
    base_dir = '/app/raw_data'
    with open(os.path.join(base_dir, 'metadata.json')) as f:
        meta = json.load(f)

    # Read and preprocess each channel
    channels = [read_channel(ch, base_dir) for ch in meta['channels']]

    # Stack into TCZYX array
    data = np.stack(channels, axis=1)  # (T, C, Z, Y, X)
    T, C, Z, Y, X = data.shape

    # Build multi-resolution pyramid
    n_levels = meta['output']['pyramid_levels']
    levels = [data]
    current = data
    for _ in range(n_levels - 1):
        current = downsample_2x(current)
        levels.append(current)

    # Extract output parameters
    out_path = meta['output']['path']
    tile_h, tile_w = meta['output']['tile_size']
    compression = meta['output']['compression']

    ps = meta['physical_size']
    px_x = ps['X']['value']
    px_y = ps['Y']['value']
    px_z = ps['Z']['value']
    ti_val = meta['time_interval']['value']
    ti_unit = meta['time_interval']['unit']

    ch_names = [ch['name'] for ch in meta['channels']]

    # OME metadata for the ImageDescription tag
    ome_meta = {
        'axes': 'TCZYX',
        'PhysicalSizeX': px_x,
        'PhysicalSizeXUnit': ps['X']['unit'],
        'PhysicalSizeY': px_y,
        'PhysicalSizeYUnit': ps['Y']['unit'],
        'PhysicalSizeZ': px_z,
        'PhysicalSizeZUnit': ps['Z']['unit'],
        'TimeIncrement': ti_val,
        'TimeIncrementUnit': ti_unit,
        'Channel': {'Name': ch_names},
    }

    write_opts = dict(
        photometric='minisblack',
        tile=(tile_h, tile_w),
        compression=compression,
    )

    # Write pyramidal OME-TIFF
    with tifffile.TiffWriter(out_path, bigtiff=True) as tif:
        # Base level with SubIFD slots for pyramid
        tif.write(
            data,
            subifds=n_levels - 1,
            resolution=(1e4 / px_x, 1e4 / px_y),
            resolutionunit='CENTIMETER',
            metadata=ome_meta,
            **write_opts,
        )
        # Pyramid sub-levels as SubIFDs
        for i in range(1, n_levels):
            mag = 2 ** i
            tif.write(
                levels[i],
                subfiletype=1,
                resolution=(1e4 / (px_x * mag), 1e4 / (px_y * mag)),
                resolutionunit='CENTIMETER',
                **write_opts,
            )
        # Thumbnail as a separate series
        if meta['output'].get('include_thumbnail', False):
            thumb = data[0, 0, 0, ::8, ::8]
            tif.write(thumb, metadata={'Name': 'thumbnail'})

    # Write analysis report
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

    with open(meta['analysis']['path'], 'w') as f:
        json.dump(analysis, f, indent=2)

    print(f'Written {out_path} ({os.path.getsize(out_path)} bytes)')
    print(f'Written {meta["analysis"]["path"]}')


if __name__ == '__main__':
    main()
