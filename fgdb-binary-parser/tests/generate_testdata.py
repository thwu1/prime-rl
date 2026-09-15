#!/usr/bin/env python3
"""Generate test FileGDB .gdbtable/.gdbtablx binary files for parser testing.

"""

import struct
import os


def encode_varuint(value):
    """Encode an unsigned integer as FileGDB varuint."""
    assert value >= 0
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value > 0:
            byte |= 0x80
        result.append(byte)
        if value == 0:
            break
    return bytes(result)


def encode_varint(value):
    """Encode a signed integer as FileGDB varint."""
    result = bytearray()
    sign = 1 if value < 0 else 0
    abs_val = abs(value)
    first_byte = (abs_val & 0x3F) | (sign << 6)
    abs_val >>= 6
    if abs_val > 0:
        first_byte |= 0x80
    result.append(first_byte)
    while abs_val > 0:
        byte = abs_val & 0x7F
        abs_val >>= 7
        if abs_val > 0:
            byte |= 0x80
        result.append(byte)
    return bytes(result)


def encode_utf16le(s):
    return s.encode('utf-16-le')


def make_gdbtablx(version, row_offsets, size_offset=4):
    """Create a .gdbtablx file (version 3 only)."""
    num_rows = len(row_offsets)
    n1024_blocks = max(1, (num_rows + 1023) // 1024)

    data = bytearray()
    # Header (16 bytes)
    data += struct.pack('<i', version)
    data += struct.pack('<i', n1024_blocks)
    data += struct.pack('<i', num_rows)
    data += struct.pack('<i', size_offset)

    # Offset section: padded to n1024_blocks * 1024 entries
    total_entries = n1024_blocks * 1024
    for i in range(total_entries):
        offset = row_offsets[i] if i < num_rows else 0
        if size_offset == 4:
            data += struct.pack('<I', offset)
        elif size_offset == 5:
            data += struct.pack('<I', offset & 0xFFFFFFFF)
            data += struct.pack('<B', (offset >> 32) & 0xFF)

    # Trailing section (16 bytes for version 3)
    data += struct.pack('<i', 0)       # nBitmapInt32Words (no bitmap)
    data += struct.pack('<i', n1024_blocks)  # n1024BlocksTotal
    data += struct.pack('<i', n1024_blocks)  # n1024BlocksPresentBis
    data += struct.pack('<i', 0)       # nUsefulBitmapIn32Words

    return bytes(data)


def build_field_objectid():
    data = bytearray()
    name = "OBJECTID"
    data += struct.pack('<B', len(name))
    data += encode_utf16le(name)
    data += struct.pack('<B', 0)   # alias length
    data += struct.pack('<B', 6)   # field type: objectid
    data += struct.pack('<B', 4)   # width
    data += struct.pack('<B', 2)   # flag: required only
    return bytes(data)


def build_field_string(name, max_length, nullable=True):
    data = bytearray()
    data += struct.pack('<B', len(name))
    data += encode_utf16le(name)
    data += struct.pack('<B', 0)
    data += struct.pack('<B', 4)   # field type: string
    data += struct.pack('<i', max_length)
    flag = 5 if nullable else 4
    data += struct.pack('<B', flag)
    if flag & 4:
        data += encode_varuint(0)  # no default value
    return bytes(data)


def build_field_int32(name, nullable=True):
    data = bytearray()
    data += struct.pack('<B', len(name))
    data += encode_utf16le(name)
    data += struct.pack('<B', 0)
    data += struct.pack('<B', 1)   # field type: int32
    data += struct.pack('<B', 4)   # width
    flag = 5 if nullable else 4
    data += struct.pack('<B', flag)
    if flag & 4:
        data += struct.pack('<B', 0)  # no default (ubyte for non-string)
    return bytes(data)


def build_field_float64(name, nullable=True):
    data = bytearray()
    data += struct.pack('<B', len(name))
    data += encode_utf16le(name)
    data += struct.pack('<B', 0)
    data += struct.pack('<B', 3)   # field type: float64
    data += struct.pack('<B', 8)   # width
    flag = 5 if nullable else 4
    data += struct.pack('<B', flag)
    if flag & 4:
        data += struct.pack('<B', 0)
    return bytes(data)


def build_field_geometry(name, wkt, xorigin, yorigin, xyscale,
                         xmin, ymin, xmax, ymax,
                         grid_sizes, nullable=True):
    data = bytearray()
    data += struct.pack('<B', len(name))
    data += encode_utf16le(name)
    data += struct.pack('<B', 0)
    data += struct.pack('<B', 7)   # field type: geometry
    data += struct.pack('<B', 0)   # unknown = 0
    flag = 7 if nullable else 6
    data += struct.pack('<B', flag)

    wkt_bytes = wkt.encode('utf-8')
    data += struct.pack('<h', len(wkt_bytes))
    data += wkt_bytes

    geom_flags = 1  # base flag, no Z, no M
    data += struct.pack('<B', geom_flags)

    data += struct.pack('<d', xorigin)
    data += struct.pack('<d', yorigin)
    data += struct.pack('<d', xyscale)
    # no M origin/scale (has_m = False)
    # no Z origin/scale (has_z = False)
    data += struct.pack('<d', 0.001)  # xytolerance
    # no M tolerance, no Z tolerance

    data += struct.pack('<d', xmin)
    data += struct.pack('<d', ymin)
    data += struct.pack('<d', xmax)
    data += struct.pack('<d', ymax)
    # no Z extent, no M extent (layer flags bits 30,31 not set)

    data += struct.pack('<B', 0)   # spatial index indicator
    data += struct.pack('<I', len(grid_sizes))
    for gs in grid_sizes:
        data += struct.pack('<d', gs)

    return bytes(data)


def encode_point_geometry(x, y, xorigin, yorigin, xyscale):
    inner = bytearray()
    inner += encode_varuint(1)  # geometry_type = 1 (2D point)
    x_raw = round((x - xorigin) * xyscale) + 1
    y_raw = round((y - yorigin) * xyscale) + 1
    inner += encode_varuint(x_raw)
    inner += encode_varuint(y_raw)

    geom_data = bytearray()
    geom_data += encode_varuint(len(inner))
    geom_data += inner
    return bytes(geom_data)


def encode_polyline_geometry(parts, xorigin, yorigin, xyscale):
    """parts: list of lists of (x, y) tuples"""
    total_points = sum(len(p) for p in parts)
    num_parts = len(parts)

    all_x = [pt[0] for part in parts for pt in part]
    all_y = [pt[1] for part in parts for pt in part]
    bb_xmin, bb_xmax = min(all_x), max(all_x)
    bb_ymin, bb_ymax = min(all_y), max(all_y)

    inner = bytearray()
    inner += encode_varuint(3)  # geometry_type = 3 (2D polyline)
    inner += encode_varuint(total_points)
    inner += encode_varuint(num_parts)

    xmin_raw = round((bb_xmin - xorigin) * xyscale)
    ymin_raw = round((bb_ymin - yorigin) * xyscale)
    xmax_delta = round((bb_xmax - bb_xmin) * xyscale)
    ymax_delta = round((bb_ymax - bb_ymin) * xyscale)

    inner += encode_varuint(xmin_raw)
    inner += encode_varuint(ymin_raw)
    inner += encode_varuint(xmax_delta)
    inner += encode_varuint(ymax_delta)

    # Part point counts (omit last; its count is inferred)
    if num_parts > 1:
        for i in range(num_parts - 1):
            inner += encode_varuint(len(parts[i]))

    # Coordinate deltas
    dx_accum = 0
    dy_accum = 0
    for part in parts:
        for (x, y) in part:
            x_scaled = round((x - xorigin) * xyscale)
            y_scaled = round((y - yorigin) * xyscale)
            inner += encode_varint(x_scaled - dx_accum)
            inner += encode_varint(y_scaled - dy_accum)
            dx_accum = x_scaled
            dy_accum = y_scaled

    geom_data = bytearray()
    geom_data += encode_varuint(len(inner))
    geom_data += inner
    return bytes(geom_data)


def build_row(nullable_field_indices, num_nullable, field_values):
    """Build a row blob.
    nullable_field_indices: dict {position_in_field_values: position_in_null_bitmap}
    num_nullable: total nullable fields
    field_values: list of (field_type_str, value) excluding OBJECTID
    """
    row_data = bytearray()

    # Null flags
    if num_nullable > 0:
        flag_bytes_count = (num_nullable + 7) // 8
        flag_bits = [1] * (flag_bytes_count * 8)  # spare bits default to 1

        for i, (_, value) in enumerate(field_values):
            if i in nullable_field_indices:
                null_pos = nullable_field_indices[i]
                if value is not None:
                    flag_bits[null_pos] = 0  # present

        for byte_idx in range(flag_bytes_count):
            byte_val = 0
            for bit_idx in range(8):
                pos = byte_idx * 8 + bit_idx
                if pos < len(flag_bits):
                    byte_val |= (flag_bits[pos] << bit_idx)
            row_data.append(byte_val)

    # Field data (only non-null fields)
    for _, (ftype, value) in enumerate(field_values):
        if value is None:
            continue
        if ftype == 'geometry':
            row_data += value
        elif ftype == 'string':
            encoded = value.encode('utf-8')
            row_data += encode_varuint(len(encoded))
            row_data += encoded
        elif ftype == 'int32':
            row_data += struct.pack('<i', value)
        elif ftype == 'float64':
            row_data += struct.pack('<d', value)

    result = struct.pack('<i', len(row_data)) + row_data
    return bytes(result)


def build_gdbtable(version, num_valid_rows, layer_flags, num_fields,
                   field_descs_bytes, row_blobs):
    """Assemble a complete .gdbtable file."""
    field_desc_offset = 40

    # Field description section
    inner = bytearray()
    inner += struct.pack('<i', 4)           # section version (FGDB 10.X)
    inner += struct.pack('<I', layer_flags)
    inner += struct.pack('<h', num_fields)
    inner += field_descs_bytes

    field_section = struct.pack('<i', len(inner)) + bytes(inner)
    field_section_end = field_desc_offset + len(field_section)

    # DEADBEEF separator
    separator = b'\xDE\xAD\xBE\xEF'
    rows_start = field_section_end + len(separator)

    # Compute row offsets
    row_offsets = []
    current_offset = rows_start
    for blob in row_blobs:
        if blob is None:
            row_offsets.append(0)  # deleted row
        else:
            row_offsets.append(current_offset)
            current_offset += len(blob)

    rows_data = b''.join(b for b in row_blobs if b is not None)
    file_size = rows_start + len(rows_data)

    max_row_blob = max((len(b) - 4 for b in row_blobs if b is not None), default=0)
    max_size = max(len(inner), max_row_blob)

    # Header (40 bytes)
    header = bytearray()
    header += struct.pack('<i', version)
    header += struct.pack('<i', num_valid_rows)
    header += struct.pack('<i', max_size)
    header += struct.pack('<i', 5)
    header += b'\x00' * 4
    header += b'\x00' * 4
    header += struct.pack('<q', file_size)
    header += struct.pack('<q', field_desc_offset)

    gdbtable = bytes(header) + field_section + separator + rows_data
    assert len(gdbtable) == file_size, f"Expected {file_size}, got {len(gdbtable)}"

    return gdbtable, row_offsets


def generate_test1(output_dir):
    """Non-spatial table: OBJECTID + Name (string) + Score (int32).
    4 rows in gdbtablx, row 2 deleted. 3 valid rows."""
    field_descs = bytearray()
    field_descs += build_field_objectid()
    field_descs += build_field_string("Name", 50, nullable=True)
    field_descs += build_field_int32("Score", nullable=True)

    # Nullable positions: Name=0, Score=1
    ni = {0: 0, 1: 1}
    nn = 2

    row1 = build_row(ni, nn, [('string', "Alice"), ('int32', 95)])
    row2 = None  # deleted
    row3 = build_row(ni, nn, [('string', "Bob"), ('int32', None)])
    row4 = build_row(ni, nn, [('string', None), ('int32', 42)])

    # layer_flags: geometry_type=0 (none), bit 8 set (UTF-8)
    gdbtable, offsets = build_gdbtable(
        version=3, num_valid_rows=3,
        layer_flags=0x100, num_fields=3,
        field_descs_bytes=bytes(field_descs),
        row_blobs=[row1, row2, row3, row4]
    )

    with open(os.path.join(output_dir, 'test1.gdbtable'), 'wb') as f:
        f.write(gdbtable)
    gdbtablx = make_gdbtablx(3, offsets)
    with open(os.path.join(output_dir, 'test1.gdbtablx'), 'wb') as f:
        f.write(gdbtablx)


def generate_test2(output_dir):
    """Point geometry table: OBJECTID + Shape (point) + Label (string).
    2 valid rows, no deleted rows."""
    xorigin, yorigin, xyscale = 0.0, 0.0, 1000.0
    wkt = 'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'

    field_descs = bytearray()
    field_descs += build_field_objectid()
    field_descs += build_field_geometry(
        "Shape", wkt, xorigin, yorigin, xyscale,
        xmin=0.0, ymin=0.0, xmax=100.0, ymax=100.0,
        grid_sizes=[10.0], nullable=True
    )
    field_descs += build_field_string("Label", 100, nullable=True)

    geom1 = encode_point_geometry(10.0, 20.0, xorigin, yorigin, xyscale)
    geom2 = encode_point_geometry(50.5, 75.25, xorigin, yorigin, xyscale)

    ni = {0: 0, 1: 1}  # Shape=0, Label=1
    nn = 2

    row1 = build_row(ni, nn, [('geometry', geom1), ('string', "CityA")])
    row2 = build_row(ni, nn, [('geometry', geom2), ('string', "CityB")])

    # layer_flags: geometry_type=1 (point), bit 8 (UTF-8)
    gdbtable, offsets = build_gdbtable(
        version=3, num_valid_rows=2,
        layer_flags=0x101, num_fields=3,
        field_descs_bytes=bytes(field_descs),
        row_blobs=[row1, row2]
    )

    with open(os.path.join(output_dir, 'test2.gdbtable'), 'wb') as f:
        f.write(gdbtable)
    gdbtablx = make_gdbtablx(3, offsets)
    with open(os.path.join(output_dir, 'test2.gdbtablx'), 'wb') as f:
        f.write(gdbtablx)


def generate_test3(output_dir):
    """Polyline geometry: OBJECTID + Shape (polyline) + Route (string) + Distance (float64).
    2 valid rows. Row 2 has Route=null."""
    xorigin, yorigin, xyscale = 0.0, 0.0, 1000.0
    wkt = 'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'

    field_descs = bytearray()
    field_descs += build_field_objectid()
    field_descs += build_field_geometry(
        "Shape", wkt, xorigin, yorigin, xyscale,
        xmin=0.0, ymin=0.0, xmax=100.0, ymax=100.0,
        grid_sizes=[5.0], nullable=True
    )
    field_descs += build_field_string("Route", 20, nullable=True)
    field_descs += build_field_float64("Distance", nullable=True)

    parts1 = [
        [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)],
        [(10.0, 20.0), (30.0, 40.0)],
    ]
    geom1 = encode_polyline_geometry(parts1, xorigin, yorigin, xyscale)

    parts2 = [
        [(50.0, 50.0), (60.0, 70.0), (80.0, 90.0), (95.0, 95.0)],
    ]
    geom2 = encode_polyline_geometry(parts2, xorigin, yorigin, xyscale)

    ni = {0: 0, 1: 1, 2: 2}  # Shape=0, Route=1, Distance=2
    nn = 3

    row1 = build_row(ni, nn, [('geometry', geom1), ('string', "Route-A"), ('float64', 123.456)])
    row2 = build_row(ni, nn, [('geometry', geom2), ('string', None), ('float64', 789.012)])

    # layer_flags: geometry_type=3 (polyline), bit 8 (UTF-8)
    gdbtable, offsets = build_gdbtable(
        version=3, num_valid_rows=2,
        layer_flags=0x103, num_fields=4,
        field_descs_bytes=bytes(field_descs),
        row_blobs=[row1, row2]
    )

    with open(os.path.join(output_dir, 'test3.gdbtable'), 'wb') as f:
        f.write(gdbtable)
    gdbtablx = make_gdbtablx(3, offsets)
    with open(os.path.join(output_dir, 'test3.gdbtablx'), 'wb') as f:
        f.write(gdbtablx)


if __name__ == '__main__':
    out = '/app/testdata'
    os.makedirs(out, exist_ok=True)
    generate_test1(out)
    generate_test2(out)
    generate_test3(out)
    print("Test data generated successfully")
