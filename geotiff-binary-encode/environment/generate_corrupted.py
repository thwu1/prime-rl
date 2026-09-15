#!/usr/bin/env python3
"""
Generate corrupted GeoTIFF 1.1 files for diagnostic repair task.
Each file contains multiple OGC 19-008r4 conformance violations
that must be diagnosed and fixed.
"""
import struct
import os

E = '<'  # little-endian

T_ASCII = 2
T_SHORT = 3
T_LONG = 4
T_DOUBLE = 12


def build_geotiff(width, height, bps, gk_header, gk_entries,
                  double_params, ascii_bytes, pixel_scale, tiepoint):
    """
    Build a valid GeoTIFF 1.1 file from components.
    Returns (bytearray, offsets_dict) where offsets_dict maps structure
    names to their byte positions in the file.
    """
    offsets = {}
    img_data = bytes(width * height * (bps // 8))

    # Pack GeoKey directory
    gk_shorts = list(gk_header)
    for entry in gk_entries:
        gk_shorts.extend(entry)
    gk_raw = struct.pack(f'{E}{len(gk_shorts)}H', *gk_shorts)

    dp_raw = struct.pack(f'{E}{len(double_params)}d', *double_params) if double_params else b''
    ps_raw = struct.pack(f'{E}{len(pixel_scale)}d', *pixel_scale)
    tp_raw = struct.pack(f'{E}{len(tiepoint)}d', *tiepoint)
    ap_raw = ascii_bytes if ascii_bytes else b''

    # Collect all tags: (tag_id, tiff_type, is_external, count_or_val, ext_data)
    tags = []
    tags.append((256, T_SHORT, False, width, None))
    tags.append((257, T_SHORT, False, height, None))
    tags.append((258, T_SHORT, False, bps, None))
    tags.append((259, T_SHORT, False, 1, None))
    tags.append((262, T_SHORT, False, 1, None))
    tags.append((273, T_LONG, False, 0, None))        # StripOffsets placeholder
    tags.append((277, T_SHORT, False, 1, None))
    tags.append((278, T_SHORT, False, height, None))
    tags.append((279, T_LONG, False, len(img_data), None))
    tags.append((33550, T_DOUBLE, True, len(pixel_scale), ps_raw))
    tags.append((33922, T_DOUBLE, True, len(tiepoint), tp_raw))
    tags.append((34735, T_SHORT, True, len(gk_shorts), gk_raw))
    if dp_raw:
        tags.append((34736, T_DOUBLE, True, len(double_params), dp_raw))
    if ap_raw:
        tags.append((34737, T_ASCII, True, len(ap_raw), ap_raw))

    tags.sort(key=lambda t: t[0])

    n = len(tags)
    ifd_sz = 2 + n * 12 + 4
    dat_start = 8 + ifd_sz

    ext = bytearray()

    def alloc(name, data):
        off = dat_start + len(ext)
        offsets[name] = off
        ext.extend(data)
        if len(ext) % 2:
            ext.append(0)
        return off

    # Build IFD entries
    entries = []
    for tag_id, ttype, is_ext, count_or_val, ext_data in tags:
        if is_ext:
            off = alloc(f'tag_{tag_id}', ext_data)
            vb = struct.pack(f'{E}I', off)
            entries.append((tag_id, ttype, count_or_val, vb))
        else:
            if ttype == T_SHORT:
                vb = struct.pack(f'{E}HH', count_or_val, 0)
            else:
                vb = struct.pack(f'{E}I', count_or_val)
            entries.append((tag_id, ttype, 1, vb))

    # Allocate raster data
    img_off = alloc('image', img_data)

    # Fix StripOffsets
    for i, (tid, tt, c, vb) in enumerate(entries):
        if tid == 273:
            entries[i] = (tid, tt, c, struct.pack(f'{E}I', img_off))

    # Assemble binary
    out = bytearray()
    out.extend(b'II')
    out.extend(struct.pack(f'{E}H', 42))
    out.extend(struct.pack(f'{E}I', 8))

    out.extend(struct.pack(f'{E}H', n))
    for i, (tid, tt, c, vb) in enumerate(entries):
        offsets[f'ifd_{tid}'] = len(out)
        out.extend(struct.pack(f'{E}H', tid))
        out.extend(struct.pack(f'{E}H', tt))
        out.extend(struct.pack(f'{E}I', c))
        out.extend(vb[:4])

    out.extend(struct.pack(f'{E}I', 0))  # next IFD
    out.extend(ext)

    return out, offsets


# ──────────────────────────────────────────────────────────────
# File 1: Geographic 2D CRS — WGS 84 (EPSG:4326)
# Corruptions:
#   1. GeoKeyDirectoryTag header KeyDirectoryVersion = 2 (must be 1)
#   2. GTRasterTypeGeoKey = 3 (reserved value; must be 1 or 2)
#   3. GeoKey entries in reverse order (must be ascending by KeyID)
# ──────────────────────────────────────────────────────────────
def make_geographic():
    data, off = build_geotiff(
        8, 8, 8,
        gk_header=(1, 1, 1, 3),
        gk_entries=[
            (1024, 0, 1, 2),     # GTModelTypeGeoKey = Geographic
            (1025, 0, 1, 1),     # GTRasterTypeGeoKey = PixelIsArea
            (2048, 0, 1, 4326),  # GeodeticCRSGeoKey = WGS 84
        ],
        double_params=[],
        ascii_bytes=None,
        pixel_scale=(1.0, 1.0, 0.0),
        tiepoint=(0.0, 0.0, 0.0, -180.0, 90.0, 0.0),
    )

    gk = off['tag_34735']

    # Corruption 1: KeyDirectoryVersion 1 -> 2
    struct.pack_into(f'{E}H', data, gk, 2)

    # Corruption 2: GTRasterTypeGeoKey value 1 -> 3 (reserved)
    # Entry 1 value field at gk + 8(header) + 8(entry0) + 6(value_offset_within_entry)
    struct.pack_into(f'{E}H', data, gk + 22, 3)

    # Corruption 3: Reverse entry order (swap entries 0 and 2)
    e0 = bytes(data[gk + 8: gk + 16])
    e2 = bytes(data[gk + 24: gk + 32])
    data[gk + 8: gk + 16] = e2
    data[gk + 24: gk + 32] = e0

    return bytes(data)


# ──────────────────────────────────────────────────────────────
# File 2: Projected CRS — UTM zone 17N (EPSG:32617)
# Corruptions:
#   1. IFD tags not sorted (33922 before 33550) — TIFF 6.0 violation
#   2. ModelPixelScaleTag count = 2 instead of 3
#   3. GeoKeyDirectoryTag MinorRevision = 0 (must be 1 for GeoTIFF 1.1)
# ──────────────────────────────────────────────────────────────
def make_projected():
    data, off = build_geotiff(
        16, 16, 8,
        gk_header=(1, 1, 1, 3),
        gk_entries=[
            (1024, 0, 1, 1),      # GTModelTypeGeoKey = Projected
            (1025, 0, 1, 1),      # GTRasterTypeGeoKey = PixelIsArea
            (3072, 0, 1, 32617),  # ProjectedCRSGeoKey = UTM 17N
        ],
        double_params=[],
        ascii_bytes=None,
        pixel_scale=(500.0, 500.0, 0.0),
        tiepoint=(0.0, 0.0, 0.0, 500000.0, 4649776.22, 0.0),
    )

    # Corruption 1: swap IFD entries for tags 33550 and 33922
    a = off['ifd_33550']
    b = off['ifd_33922']
    ea = bytes(data[a:a + 12])
    eb = bytes(data[b:b + 12])
    data[a:a + 12] = eb
    data[b:b + 12] = ea
    # After swap: tag 33550's entry is at position b, tag 33922's at position a

    # Corruption 2: ModelPixelScaleTag (now at position b) count 3 -> 2
    struct.pack_into(f'{E}I', data, b + 4, 2)

    # Corruption 3: GeoKey MinorRevision 1 -> 0
    gk = off['tag_34735']
    struct.pack_into(f'{E}H', data, gk + 4, 0)

    return bytes(data)


# ──────────────────────────────────────────────────────────────
# File 3: User-defined Transverse Mercator on WGS 84
# Corruptions:
#   1. ProjScaleAtNatOriginGeoKey (3092) stored as SHORT=1
#      instead of DOUBLE=0.9996 (wrong TIFFTagLocation)
#   2. GeoAsciiParamsTag: pipe delimiters replaced with semicolons,
#      null terminator replaced (violates OGC 19-008r4 Req 24)
#   3. ProjNatOriginLongGeoKey (3080) value offset wrong — points
#      to double index 2 (500000.0) instead of index 0 (-75.0)
# ──────────────────────────────────────────────────────────────
def make_userdefined():
    ascii_data = b'Custom TM Zone|\x00'

    data, off = build_geotiff(
        8, 8, 8,
        gk_header=(1, 1, 1, 12),
        gk_entries=[
            (1024, 0, 1, 1),        # GTModelTypeGeoKey = Projected
            (1025, 0, 1, 2),        # GTRasterTypeGeoKey = PixelIsPoint
            (2048, 0, 1, 4326),     # GeodeticCRSGeoKey = WGS 84
            (3072, 0, 1, 32767),    # ProjectedCRSGeoKey = user-defined
            (3073, 34737, 15, 0),   # ProjectedCitationGeoKey = ASCII
            (3075, 0, 1, 9807),     # ProjMethodGeoKey = TM
            (3076, 0, 1, 9001),     # ProjLinearUnitsGeoKey = metre
            (3080, 34736, 1, 0),    # ProjNatOriginLongGeoKey -> double[0]=-75.0
            (3081, 34736, 1, 1),    # ProjNatOriginLatGeoKey -> double[1]=0.0
            (3082, 34736, 1, 2),    # ProjFalseEastingGeoKey -> double[2]=500000.0
            (3083, 34736, 1, 3),    # ProjFalseNorthingGeoKey -> double[3]=0.0
            (3092, 34736, 1, 4),    # ProjScaleAtNatOriginGeoKey -> double[4]=0.9996
        ],
        double_params=[-75.0, 0.0, 500000.0, 0.0, 0.9996],
        ascii_bytes=ascii_data,
        pixel_scale=(500.0, 500.0, 0.0),
        tiepoint=(0.0, 0.0, 0.0, 500000.0, 4649776.22, 0.0),
    )

    gk = off['tag_34735']

    # Corruption 1: entry 11 (3092) — change DOUBLE storage to SHORT
    # Entry 11 at gk + 8 + 11*8 = gk + 96
    e = gk + 96
    struct.pack_into(f'{E}H', data, e + 2, 0)  # TIFFTagLocation: 34736 -> 0
    struct.pack_into(f'{E}H', data, e + 6, 1)  # ValueOffset: 4 -> 1 (SHORT val=1)

    # Corruption 2: ASCII params — wrong delimiters
    ap = off['tag_34737']
    data[ap + 14] = ord(';')    # pipe -> semicolon
    data[ap + 15] = ord(';')    # null terminator -> semicolon

    # Corruption 3: entry 7 (3080) — wrong double index
    e = gk + 8 + 7 * 8
    struct.pack_into(f'{E}H', data, e + 6, 2)  # ValueOffset: 0 -> 2

    return bytes(data)


# ──────────────────────────────────────────────────────────────
# File 4: Compound CRS — UTM 17N + EGM96 vertical
# Corruptions:
#   1. GeoKeyDirectoryTag NumberOfKeys = 5 (actually 7 entries;
#      last 2 are hidden/unreachable)
#   2. VerticalCitationGeoKey (4097) stored as SHORT=0
#      instead of ASCII (wrong TIFFTagLocation, lost citation)
#   3. GeoKey sort order violated: VerticalGeoKey (4096) appears
#      before ProjectedCRSGeoKey (3072)
# ──────────────────────────────────────────────────────────────
def make_compound():
    ascii_data = b'EGM96 geoid height|\x00'

    data, off = build_geotiff(
        8, 8, 8,
        gk_header=(1, 1, 1, 7),
        gk_entries=[
            (1024, 0, 1, 1),        # GTModelTypeGeoKey = Projected
            (1025, 0, 1, 1),        # GTRasterTypeGeoKey = PixelIsArea
            (3072, 0, 1, 32617),    # ProjectedCRSGeoKey = UTM 17N
            (4096, 0, 1, 5773),     # VerticalGeoKey = EGM96
            (4097, 34737, 19, 0),   # VerticalCitationGeoKey = ASCII
            (4098, 0, 1, 5171),     # VerticalDatumGeoKey
            (4099, 0, 1, 9001),     # VerticalUnitsGeoKey = metre
        ],
        double_params=[],
        ascii_bytes=ascii_data,
        pixel_scale=(1000.0, 1000.0, 1.0),
        tiepoint=(0.0, 0.0, 0.0, 500000.0, 4649776.22, 100.0),
    )

    gk = off['tag_34735']

    # Corruption 1: NumberOfKeys 7 -> 5 (hides last 2 entries)
    struct.pack_into(f'{E}H', data, gk + 6, 5)

    # Corruption 2: entry 4 (4097) — ASCII -> SHORT
    e = gk + 8 + 4 * 8
    struct.pack_into(f'{E}H', data, e + 2, 0)   # TIFFTagLocation: 34737 -> 0
    struct.pack_into(f'{E}H', data, e + 4, 1)   # Count: 19 -> 1
    # ValueOffset stays 0 (SHORT value = 0)

    # Corruption 3: swap entries 2 (3072) and 3 (4096)
    e2 = gk + 8 + 2 * 8
    e3 = gk + 8 + 3 * 8
    tmp = bytes(data[e2:e2 + 8])
    data[e2:e2 + 8] = data[e3:e3 + 8]
    data[e3:e3 + 8] = tmp

    return bytes(data)


def main():
    out_dir = '/app/corrupted'
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs('/app/fixed', exist_ok=True)

    files = {
        'geographic.tif': make_geographic(),
        'projected.tif': make_projected(),
        'userdefined.tif': make_userdefined(),
        'compound.tif': make_compound(),
    }

    for name, data in files.items():
        path = os.path.join(out_dir, name)
        with open(path, 'wb') as f:
            f.write(data)
        print(f'Created {path} ({len(data)} bytes)')

    print('Done. Corrupted files written to /app/corrupted/')


if __name__ == '__main__':
    main()
