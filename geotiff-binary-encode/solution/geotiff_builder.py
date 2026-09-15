#!/usr/bin/env python3

"""
Constructs valid GeoTIFF 1.1 files from JSON CRS specifications.
Writes TIFF 6.0 binary format using only Python's standard library.
Implements GeoKey encoding per OGC 19-008r4.
"""

import struct
import json
import os

# TIFF tag type IDs
TIFF_SHORT = 3
TIFF_LONG = 4
TIFF_DOUBLE = 12
TIFF_ASCII = 2

# GeoKey name -> numeric ID
GEOKEY_MAP = {
    'GTModelTypeGeoKey': 1024,
    'GTRasterTypeGeoKey': 1025,
    'GeodeticCRSGeoKey': 2048,
    'GeodeticCitationGeoKey': 2049,
    'GeodeticDatumGeoKey': 2050,
    'PrimeMeridianGeoKey': 2051,
    'GeogLinearUnitsGeoKey': 2052,
    'GeogAngularUnitsGeoKey': 2054,
    'EllipsoidGeoKey': 2056,
    'GeogAzimuthUnitsGeoKey': 2060,
    'ProjectedCRSGeoKey': 3072,
    'ProjectedCitationGeoKey': 3073,
    'ProjectionGeoKey': 3074,
    'ProjMethodGeoKey': 3075,
    'ProjLinearUnitsGeoKey': 3076,
    'ProjLinearUnitSizeGeoKey': 3077,
    'ProjStdParallel1GeoKey': 3078,
    'ProjStdParallel2GeoKey': 3079,
    'ProjNatOriginLongGeoKey': 3080,
    'ProjNatOriginLatGeoKey': 3081,
    'ProjFalseEastingGeoKey': 3082,
    'ProjFalseNorthingGeoKey': 3083,
    'ProjFalseOriginLongGeoKey': 3084,
    'ProjFalseOriginLatGeoKey': 3085,
    'ProjFalseOriginEastingGeoKey': 3086,
    'ProjFalseOriginNorthingGeoKey': 3087,
    'ProjCenterLongGeoKey': 3088,
    'ProjCenterLatGeoKey': 3089,
    'ProjCenterEastingGeoKey': 3090,
    'ProjCenterNorthingGeoKey': 3091,
    'ProjScaleAtNatOriginGeoKey': 3092,
    'ProjScaleAtCenterGeoKey': 3093,
    'ProjAzimuthAngleGeoKey': 3094,
    'ProjStraightVertPoleLongGeoKey': 3095,
    'VerticalGeoKey': 4096,
    'VerticalCitationGeoKey': 4097,
    'VerticalDatumGeoKey': 4098,
    'VerticalUnitsGeoKey': 4099,
    'CoordinateEpochGeoKey': 5120,
}

# DOUBLE-type GeoKey IDs (projection params, unit sizes, ellipsoid dims, etc.)
DOUBLE_KEY_IDS = {
    2053, 2055, 2057, 2058, 2059, 2061,
    3077, 3078, 3079, 3080, 3081, 3082, 3083, 3084, 3085,
    3086, 3087, 3088, 3089, 3090, 3091, 3092, 3093, 3094, 3095,
    5120,
}

# ASCII-type GeoKey IDs (citation keys)
ASCII_KEY_IDS = {2049, 3073, 4097}

ENDIAN = '<'  # little-endian


def build_geotiff(spec, output_path):
    """Build a GeoTIFF 1.1 file from a JSON spec dictionary."""
    width = spec['image']['width']
    height = spec['image']['height']
    bps = spec['image']['bits_per_sample']

    # ── Classify and sort GeoKeys ──────────────────────────────────
    short_entries = []   # (key_id, value)
    double_entries = []  # (key_id, float_value)
    ascii_entries = []   # (key_id, string_value)

    for key_name, value in spec['geokeys'].items():
        key_id = GEOKEY_MAP[key_name]
        if key_id in ASCII_KEY_IDS:
            ascii_entries.append((key_id, str(value)))
        elif key_id in DOUBLE_KEY_IDS:
            double_entries.append((key_id, float(value)))
        else:
            short_entries.append((key_id, int(value)))

    # ── Build GeoKey directory entries (sorted by key ID) ──────────
    double_params = []
    ascii_concat = b''

    all_key_entries = []

    for key_id, val in short_entries:
        all_key_entries.append((key_id, 0, 1, val))

    for key_id, val in double_entries:
        idx = len(double_params)
        double_params.append(val)
        all_key_entries.append((key_id, 34736, 1, idx))

    for key_id, text in ascii_entries:
        offset = len(ascii_concat)
        encoded = text.encode('ascii') + b'|'
        all_key_entries.append((key_id, 34737, len(encoded), offset))
        ascii_concat += encoded

    # Add null terminator
    if ascii_concat:
        ascii_concat += b'\x00'

    # Sort entries by KeyID
    all_key_entries.sort(key=lambda e: e[0])

    num_geokeys = len(all_key_entries)

    # Build GeoKeyDirectoryTag value array (header + entries)
    geokey_dir_shorts = [1, 1, 1, num_geokeys]
    for entry in all_key_entries:
        geokey_dir_shorts.extend(entry)

    # ── Pack tag data ──────────────────────────────────────────────
    geokey_dir_data = struct.pack(
        ENDIAN + f'{len(geokey_dir_shorts)}H', *geokey_dir_shorts
    )
    double_param_data = (
        struct.pack(ENDIAN + f'{len(double_params)}d', *double_params)
        if double_params else b''
    )
    ascii_param_data = ascii_concat

    pixel_scale_data = struct.pack(
        ENDIAN + '3d', *spec['model_pixel_scale']
    )
    tiepoint_data = struct.pack(
        ENDIAN + '6d', *spec['model_tiepoint']
    )

    image_data = bytes(width * height * (bps // 8))

    # ── Determine IFD tag count ────────────────────────────────────
    # Required TIFF tags: 256-279 (9 tags)
    # Required GeoTIFF tags: 33550, 33922, 34735 (3 tags)
    # Optional: 34736 (if doubles), 34737 (if ascii)
    num_tags = 9 + 3
    if double_param_data:
        num_tags += 1
    if ascii_param_data:
        num_tags += 1

    # ── Calculate file layout ──────────────────────────────────────
    # Header: 8 bytes
    # IFD: 2 (count) + num_tags * 12 (entries) + 4 (next IFD ptr)
    ifd_size = 2 + num_tags * 12 + 4
    data_start = 8 + ifd_size

    extra = bytearray()

    def alloc(blob):
        """Append blob to extra data area, return its file offset."""
        offset = data_start + len(extra)
        extra.extend(blob)
        if len(extra) % 2 != 0:
            extra.extend(b'\x00')
        return offset

    # Allocate external tag data (order doesn't matter for correctness)
    ps_off = alloc(pixel_scale_data)
    tp_off = alloc(tiepoint_data)
    gk_off = alloc(geokey_dir_data)
    dp_off = alloc(double_param_data) if double_param_data else 0
    ap_off = alloc(ascii_param_data) if ascii_param_data else 0
    img_off = alloc(image_data)

    # ── Build sorted IFD entries ───────────────────────────────────
    # Each entry: (tag_id, type, count, value_or_offset)
    ifd = []
    ifd.append((256, TIFF_SHORT, 1, width))
    ifd.append((257, TIFF_SHORT, 1, height))
    ifd.append((258, TIFF_SHORT, 1, bps))
    ifd.append((259, TIFF_SHORT, 1, 1))           # No compression
    ifd.append((262, TIFF_SHORT, 1, 1))           # BlackIsZero
    ifd.append((273, TIFF_LONG, 1, img_off))      # StripOffsets
    ifd.append((277, TIFF_SHORT, 1, 1))           # SamplesPerPixel
    ifd.append((278, TIFF_SHORT, 1, height))      # RowsPerStrip
    ifd.append((279, TIFF_LONG, 1, len(image_data)))  # StripByteCounts

    ifd.append((33550, TIFF_DOUBLE, 3, ps_off))
    ifd.append((33922, TIFF_DOUBLE, 6, tp_off))
    ifd.append((34735, TIFF_SHORT, len(geokey_dir_shorts), gk_off))

    if double_param_data:
        ifd.append((34736, TIFF_DOUBLE, len(double_params), dp_off))
    if ascii_param_data:
        ifd.append((34737, TIFF_ASCII, len(ascii_param_data), ap_off))

    ifd.sort(key=lambda e: e[0])

    # ── Write TIFF binary ─────────────────────────────────────────
    out = bytearray()

    # Header
    out.extend(b'II')
    out.extend(struct.pack(ENDIAN + 'H', 42))
    out.extend(struct.pack(ENDIAN + 'I', 8))  # IFD at offset 8

    # IFD entry count
    out.extend(struct.pack(ENDIAN + 'H', num_tags))

    # IFD entries
    TYPE_SIZES = {TIFF_SHORT: 2, TIFF_LONG: 4, TIFF_DOUBLE: 8, TIFF_ASCII: 1}
    for tag_id, tag_type, count, val in ifd:
        out.extend(struct.pack(ENDIAN + 'H', tag_id))
        out.extend(struct.pack(ENDIAN + 'H', tag_type))
        out.extend(struct.pack(ENDIAN + 'I', count))

        total_bytes = count * TYPE_SIZES[tag_type]
        if total_bytes <= 4:
            if tag_type == TIFF_SHORT:
                out.extend(struct.pack(ENDIAN + 'H', val))
                out.extend(b'\x00' * 2)
            elif tag_type == TIFF_LONG:
                out.extend(struct.pack(ENDIAN + 'I', val))
            elif tag_type == TIFF_ASCII and count <= 4:
                chunk = ascii_param_data[:count].ljust(4, b'\x00')
                out.extend(chunk)
            else:
                out.extend(struct.pack(ENDIAN + 'I', val))
        else:
            out.extend(struct.pack(ENDIAN + 'I', val))

    # Next IFD pointer (0 = none)
    out.extend(struct.pack(ENDIAN + 'I', 0))

    # External data
    out.extend(extra)

    # Write to disk
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(out)
    print(f"  Created {output_path} ({len(out)} bytes)")


def main():
    specs_dir = '/app/specs'
    output_dir = '/app/output'

    for spec_file in sorted(os.listdir(specs_dir)):
        if not spec_file.endswith('.json'):
            continue
        spec_path = os.path.join(specs_dir, spec_file)
        with open(spec_path) as f:
            spec = json.load(f)

        out_name = spec_file.replace('.json', '.tif')
        out_path = os.path.join(output_dir, out_name)

        print(f"Building {out_name} — {spec['description']}")
        build_geotiff(spec, out_path)

    print("Done.")


if __name__ == '__main__':
    main()
