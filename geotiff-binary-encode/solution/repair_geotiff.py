#!/usr/bin/env python3

"""
Diagnose conformance violations in corrupted GeoTIFF files and reconstruct
corrected versions per OGC 19-008r4.

Approach:
1. Parse each corrupted TIFF to extract raster data and geo-transform
2. Diagnose violations by inspecting GeoKey directory, IFD order, tag counts,
   value storage types, ASCII encoding, and parameter offsets
3. Reconstruct correct GeoTIFF files using the manifest CRS specifications
"""

import struct
import os
import sys

E = '<'

T_ASCII = 2
T_SHORT = 3
T_LONG = 4
T_DOUBLE = 12


class CorruptedTiffReader:
    """Read corrupted TIFF files, tolerating structural violations."""

    TYPE_SIZES = {1:1, 2:1, 3:2, 4:4, 5:8, 6:1, 7:1, 8:2, 9:4, 10:8, 11:4, 12:8}

    def __init__(self, path):
        with open(path, 'rb') as f:
            self.data = f.read()
        self.path = path
        bo = self.data[:2]
        self.endian = '<' if bo == b'II' else '>'
        self.ifd_offset = struct.unpack_from(self.endian + 'I', self.data, 4)[0]
        self._parse_ifd()

    def _parse_ifd(self):
        off = self.ifd_offset
        n = struct.unpack_from(self.endian + 'H', self.data, off)[0]
        off += 2
        self.tags = {}
        self.tag_order = []
        for _ in range(n):
            tid = struct.unpack_from(self.endian + 'H', self.data, off)[0]
            tt = struct.unpack_from(self.endian + 'H', self.data, off + 2)[0]
            cnt = struct.unpack_from(self.endian + 'I', self.data, off + 4)[0]
            ts = self.TYPE_SIZES.get(tt, 1)
            total = cnt * ts
            doff = off + 8 if total <= 4 else struct.unpack_from(self.endian + 'I', self.data, off + 8)[0]
            self.tags[tid] = {'type': tt, 'count': cnt, 'offset': doff}
            self.tag_order.append(tid)
            off += 12

    def read_short(self, tag_id):
        t = self.tags.get(tag_id)
        if not t: return None
        return struct.unpack_from(self.endian + 'H', self.data, t['offset'])[0]

    def read_doubles(self, tag_id, override_count=None):
        t = self.tags.get(tag_id)
        if not t: return None
        cnt = override_count or t['count']
        return list(struct.unpack_from(self.endian + f'{cnt}d', self.data, t['offset']))

    def read_shorts(self, tag_id, override_count=None):
        t = self.tags.get(tag_id)
        if not t: return None
        cnt = override_count or t['count']
        return list(struct.unpack_from(self.endian + f'{cnt}H', self.data, t['offset']))

    def read_raster(self):
        strip_off_tag = self.tags.get(273)
        strip_cnt_tag = self.tags.get(279)
        if not strip_off_tag or not strip_cnt_tag:
            return b''
        if strip_off_tag['type'] == T_LONG:
            off = struct.unpack_from(self.endian + 'I', self.data, strip_off_tag['offset'])[0]
        else:
            off = struct.unpack_from(self.endian + 'H', self.data, strip_off_tag['offset'])[0]
        if strip_cnt_tag['type'] == T_LONG:
            cnt = struct.unpack_from(self.endian + 'I', self.data, strip_cnt_tag['offset'])[0]
        else:
            cnt = struct.unpack_from(self.endian + 'H', self.data, strip_cnt_tag['offset'])[0]
        return self.data[off:off + cnt]

    def diag(self, msg):
        print(f"  [{os.path.basename(self.path)}] {msg}", file=sys.stderr)


def build_clean_geotiff(width, height, bps, gk_header, gk_entries,
                        double_params, ascii_bytes, pixel_scale, tiepoint,
                        raster_data=None):
    """Build a correct GeoTIFF 1.1 file from clean parameters."""
    if raster_data is None:
        raster_data = bytes(width * height * (bps // 8))

    gk_shorts = list(gk_header)
    for e in gk_entries:
        gk_shorts.extend(e)
    gk_raw = struct.pack(f'{E}{len(gk_shorts)}H', *gk_shorts)
    dp_raw = struct.pack(f'{E}{len(double_params)}d', *double_params) if double_params else b''
    ps_raw = struct.pack(f'{E}{len(pixel_scale)}d', *pixel_scale)
    tp_raw = struct.pack(f'{E}{len(tiepoint)}d', *tiepoint)

    tags = []
    tags.append((256, T_SHORT, False, width, None))
    tags.append((257, T_SHORT, False, height, None))
    tags.append((258, T_SHORT, False, bps, None))
    tags.append((259, T_SHORT, False, 1, None))
    tags.append((262, T_SHORT, False, 1, None))
    tags.append((273, T_LONG, False, 0, None))
    tags.append((277, T_SHORT, False, 1, None))
    tags.append((278, T_SHORT, False, height, None))
    tags.append((279, T_LONG, False, len(raster_data), None))
    tags.append((33550, T_DOUBLE, True, len(pixel_scale), ps_raw))
    tags.append((33922, T_DOUBLE, True, len(tiepoint), tp_raw))
    tags.append((34735, T_SHORT, True, len(gk_shorts), gk_raw))
    if dp_raw:
        tags.append((34736, T_DOUBLE, True, len(double_params), dp_raw))
    if ascii_bytes:
        tags.append((34737, T_ASCII, True, len(ascii_bytes), ascii_bytes))

    tags.sort(key=lambda t: t[0])

    n = len(tags)
    ifd_sz = 2 + n * 12 + 4
    data_start = 8 + ifd_sz
    ext = bytearray()

    def alloc(d):
        off = data_start + len(ext)
        ext.extend(d)
        if len(ext) % 2:
            ext.append(0)
        return off

    entries = []
    for tid, tt, is_ext, cov, ed in tags:
        if is_ext:
            off = alloc(ed)
            entries.append((tid, tt, cov, struct.pack(f'{E}I', off)))
        else:
            if tt == T_SHORT:
                entries.append((tid, tt, 1, struct.pack(f'{E}HH', cov, 0)))
            else:
                entries.append((tid, tt, 1, struct.pack(f'{E}I', cov)))

    img_off = alloc(raster_data)
    for i, (tid, tt, c, vb) in enumerate(entries):
        if tid == 273:
            entries[i] = (tid, tt, c, struct.pack(f'{E}I', img_off))

    out = bytearray()
    out.extend(b'II')
    out.extend(struct.pack(f'{E}H', 42))
    out.extend(struct.pack(f'{E}I', 8))
    out.extend(struct.pack(f'{E}H', n))
    for tid, tt, c, vb in entries:
        out.extend(struct.pack(f'{E}H', tid))
        out.extend(struct.pack(f'{E}H', tt))
        out.extend(struct.pack(f'{E}I', c))
        out.extend(vb[:4])
    out.extend(struct.pack(f'{E}I', 0))
    out.extend(ext)
    return bytes(out)


def fix_geographic(src_path, dst_path):
    """Fix geographic.tif: version, raster type, entry order."""
    r = CorruptedTiffReader(src_path)

    # Diagnose
    gk_shorts = r.read_shorts(34735)
    r.diag(f"GeoKey header: version={gk_shorts[0]}, rev={gk_shorts[1]}, minor={gk_shorts[2]}, nkeys={gk_shorts[3]}")
    if gk_shorts[0] != 1:
        r.diag(f"VIOLATION: KeyDirectoryVersion={gk_shorts[0]}, should be 1")
    entries = [(gk_shorts[4+i*4], gk_shorts[5+i*4], gk_shorts[6+i*4], gk_shorts[7+i*4])
               for i in range(gk_shorts[3])]
    ids = [e[0] for e in entries]
    if ids != sorted(ids):
        r.diag(f"VIOLATION: GeoKey entries not sorted: {ids}")
    for kid, _, _, val in entries:
        if kid == 1025 and val not in (1, 2):
            r.diag(f"VIOLATION: GTRasterTypeGeoKey={val}, reserved value")

    # Extract valid data
    ps = r.read_doubles(33550, override_count=3)
    tp = r.read_doubles(33922, override_count=6)
    raster = r.read_raster()
    w = r.read_short(256)
    h = r.read_short(257)

    # Rebuild
    data = build_clean_geotiff(
        w, h, 8,
        gk_header=(1, 1, 1, 3),
        gk_entries=[(1024, 0, 1, 2), (1025, 0, 1, 1), (2048, 0, 1, 4326)],
        double_params=[], ascii_bytes=None,
        pixel_scale=tuple(ps), tiepoint=tuple(tp),
        raster_data=raster,
    )
    with open(dst_path, 'wb') as f:
        f.write(data)
    r.diag(f"Fixed -> {dst_path} ({len(data)} bytes)")


def fix_projected(src_path, dst_path):
    """Fix projected.tif: IFD order, pixel scale count, minor revision."""
    r = CorruptedTiffReader(src_path)

    # Diagnose
    if r.tag_order != sorted(r.tag_order):
        r.diag(f"VIOLATION: IFD tags not sorted: {r.tag_order}")
    tag_33550 = r.tags.get(33550)
    if tag_33550 and tag_33550['count'] != 3:
        r.diag(f"VIOLATION: ModelPixelScaleTag count={tag_33550['count']}, should be 3")
    gk_shorts = r.read_shorts(34735)
    if gk_shorts[2] != 1:
        r.diag(f"VIOLATION: MinorRevision={gk_shorts[2]}, should be 1")

    # Extract (read 3 doubles from pixel scale data regardless of declared count)
    ps = r.read_doubles(33550, override_count=3)
    tp = r.read_doubles(33922, override_count=6)
    raster = r.read_raster()
    w = r.read_short(256)
    h = r.read_short(257)

    data = build_clean_geotiff(
        w, h, 8,
        gk_header=(1, 1, 1, 3),
        gk_entries=[(1024, 0, 1, 1), (1025, 0, 1, 1), (3072, 0, 1, 32617)],
        double_params=[], ascii_bytes=None,
        pixel_scale=tuple(ps), tiepoint=tuple(tp),
        raster_data=raster,
    )
    with open(dst_path, 'wb') as f:
        f.write(data)
    r.diag(f"Fixed -> {dst_path} ({len(data)} bytes)")


def fix_userdefined(src_path, dst_path):
    """Fix userdefined.tif: scale key type, ASCII encoding, double offset."""
    r = CorruptedTiffReader(src_path)

    # Diagnose
    gk_shorts = r.read_shorts(34735)
    nkeys = gk_shorts[3]
    entries = [(gk_shorts[4+i*4], gk_shorts[5+i*4], gk_shorts[6+i*4], gk_shorts[7+i*4])
               for i in range(nkeys)]

    for kid, tloc, cnt, voff in entries:
        if kid == 3092 and tloc == 0:
            r.diag(f"VIOLATION: ProjScaleAtNatOriginGeoKey stored as SHORT={voff}, should be DOUBLE")
        if kid == 3080 and tloc == 34736:
            doubles = r.read_doubles(34736)
            if doubles and voff < len(doubles):
                val = doubles[voff]
                if abs(val - (-75.0)) > 1.0:
                    r.diag(f"VIOLATION: ProjNatOriginLongGeoKey offset={voff} -> {val}, expected -75.0")

    if 34737 in r.tags:
        raw = r.data[r.tags[34737]['offset']:r.tags[34737]['offset'] + r.tags[34737]['count']]
        if b';' in raw:
            r.diag(f"VIOLATION: ASCII params use semicolons instead of pipes")
        if not raw.endswith(b'\x00'):
            r.diag(f"VIOLATION: ASCII params missing null terminator")

    ps = r.read_doubles(33550, override_count=3)
    tp = r.read_doubles(33922, override_count=6)
    raster = r.read_raster()
    w = r.read_short(256)
    h = r.read_short(257)

    ascii_data = b'Custom TM Zone|\x00'

    data = build_clean_geotiff(
        w, h, 8,
        gk_header=(1, 1, 1, 12),
        gk_entries=[
            (1024, 0, 1, 1), (1025, 0, 1, 2), (2048, 0, 1, 4326),
            (3072, 0, 1, 32767), (3073, 34737, 15, 0), (3075, 0, 1, 9807),
            (3076, 0, 1, 9001), (3080, 34736, 1, 0), (3081, 34736, 1, 1),
            (3082, 34736, 1, 2), (3083, 34736, 1, 3), (3092, 34736, 1, 4),
        ],
        double_params=[-75.0, 0.0, 500000.0, 0.0, 0.9996],
        ascii_bytes=ascii_data,
        pixel_scale=tuple(ps), tiepoint=tuple(tp),
        raster_data=raster,
    )
    with open(dst_path, 'wb') as f:
        f.write(data)
    r.diag(f"Fixed -> {dst_path} ({len(data)} bytes)")


def fix_compound(src_path, dst_path):
    """Fix compound.tif: key count, citation type, entry order."""
    r = CorruptedTiffReader(src_path)

    # Diagnose
    gk_shorts = r.read_shorts(34735)
    declared_nkeys = gk_shorts[3]
    total_shorts = len(gk_shorts)
    actual_entries = (total_shorts - 4) // 4
    if declared_nkeys != actual_entries:
        r.diag(f"VIOLATION: NumberOfKeys={declared_nkeys} but {actual_entries} entries exist")

    entries = [(gk_shorts[4+i*4], gk_shorts[5+i*4], gk_shorts[6+i*4], gk_shorts[7+i*4])
               for i in range(actual_entries)]
    ids = [e[0] for e in entries]
    if ids != sorted(ids):
        r.diag(f"VIOLATION: GeoKey entries not sorted: {ids}")

    for kid, tloc, cnt, voff in entries:
        if kid == 4097 and tloc == 0:
            r.diag(f"VIOLATION: VerticalCitationGeoKey stored as SHORT={voff}, should be ASCII")

    if 34737 in r.tags:
        raw = r.data[r.tags[34737]['offset']:r.tags[34737]['offset'] + r.tags[34737]['count']]
        r.diag(f"Found orphaned ASCII data in tag 34737: {raw!r}")

    ps = r.read_doubles(33550, override_count=3)
    tp = r.read_doubles(33922, override_count=6)
    raster = r.read_raster()
    w = r.read_short(256)
    h = r.read_short(257)

    ascii_data = b'EGM96 geoid height|\x00'

    data = build_clean_geotiff(
        w, h, 8,
        gk_header=(1, 1, 1, 7),
        gk_entries=[
            (1024, 0, 1, 1), (1025, 0, 1, 1), (3072, 0, 1, 32617),
            (4096, 0, 1, 5773), (4097, 34737, 19, 0), (4098, 0, 1, 5171),
            (4099, 0, 1, 9001),
        ],
        double_params=[],
        ascii_bytes=ascii_data,
        pixel_scale=tuple(ps), tiepoint=tuple(tp),
        raster_data=raster,
    )
    with open(dst_path, 'wb') as f:
        f.write(data)
    r.diag(f"Fixed -> {dst_path} ({len(data)} bytes)")


def main():
    os.makedirs('/app/fixed', exist_ok=True)

    fixes = [
        ('geographic.tif', fix_geographic),
        ('projected.tif', fix_projected),
        ('userdefined.tif', fix_userdefined),
        ('compound.tif', fix_compound),
    ]

    for name, fix_fn in fixes:
        src = f'/app/corrupted/{name}'
        dst = f'/app/fixed/{name}'
        print(f"Diagnosing and fixing {name}...", file=sys.stderr)
        fix_fn(src, dst)

    print("All files repaired.", file=sys.stderr)


if __name__ == '__main__':
    main()
