#!/usr/bin/env python3
"""FileGDB .gdbtable binary parser. Outputs JSON to stdout.

"""

import struct
import sys
import json
import os


FIELD_TYPE_NAMES = {
    0: "int16", 1: "int32", 2: "float32", 3: "float64",
    4: "string", 5: "datetime", 6: "objectid", 7: "geometry",
    8: "binary", 9: "raster", 10: "guid", 11: "globalid",
    12: "xml", 13: "int64",
}

GEOM_TYPE_NAMES = {
    0: "none", 1: "point", 2: "multipoint", 3: "polyline",
    4: "polygon", 5: "rectangle", 9: "multipatch",
}


class BinaryReader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def seek(self, pos):
        self.pos = pos

    def read(self, n):
        result = self.data[self.pos:self.pos + n]
        self.pos += n
        return result

    def read_ubyte(self):
        return struct.unpack('<B', self.read(1))[0]

    def read_int16(self):
        return struct.unpack('<h', self.read(2))[0]

    def read_uint16(self):
        return struct.unpack('<H', self.read(2))[0]

    def read_int32(self):
        return struct.unpack('<i', self.read(4))[0]

    def read_uint32(self):
        return struct.unpack('<I', self.read(4))[0]

    def read_int64(self):
        return struct.unpack('<q', self.read(8))[0]

    def read_float32(self):
        return struct.unpack('<f', self.read(4))[0]

    def read_float64(self):
        return struct.unpack('<d', self.read(8))[0]

    def read_utf16(self, num_chars):
        return self.read(num_chars * 2).decode('utf-16-le')

    def read_varuint(self):
        value = 0
        shift = 0
        while True:
            byte = self.read_ubyte()
            value |= (byte & 0x7F) << shift
            shift += 7
            if (byte & 0x80) == 0:
                break
        return value

    def read_varint(self):
        first = self.read_ubyte()
        sign = (first >> 6) & 1
        value = first & 0x3F
        shift = 6
        if first & 0x80:
            while True:
                byte = self.read_ubyte()
                value |= (byte & 0x7F) << shift
                shift += 7
                if (byte & 0x80) == 0:
                    break
        return -value if sign else value


def parse_header(reader):
    reader.seek(0)
    version = reader.read_int32()

    if version == 3:
        num_valid_rows = reader.read_int32()
    elif version == 4:
        reader.read_int32()  # has_deleted indicator
        num_valid_rows = None  # will read later

    reader.read_int32()  # max_size
    reader.read_int32()  # unknown (==5)
    reader.read(4)       # varying
    if version == 3:
        reader.read(4)   # zeros

    if version == 4:
        num_valid_rows = reader.read_int64()

    reader.seek(24)
    file_size = reader.read_int64()
    field_desc_offset = reader.read_int64()

    return {
        "version": version,
        "num_valid_rows": num_valid_rows,
        "file_size": file_size,
        "field_desc_offset": field_desc_offset,
    }


def parse_fields(reader, field_desc_offset):
    reader.seek(field_desc_offset)

    section_size = reader.read_int32()
    section_version = reader.read_int32()
    layer_flags = reader.read_uint32()
    num_fields = reader.read_int16()

    geom_type_code = layer_flags & 0xFF
    is_utf8 = bool(layer_flags & 0x100)
    has_z_layer = bool(layer_flags & (1 << 31))
    has_m_layer = bool(layer_flags & (1 << 30))

    fields = []
    for _ in range(num_fields):
        name_len = reader.read_ubyte()
        name = reader.read_utf16(name_len)
        alias_len = reader.read_ubyte()
        if alias_len > 0:
            reader.read_utf16(alias_len)

        field_type = reader.read_ubyte()
        finfo = {
            "name": name,
            "type": FIELD_TYPE_NAMES.get(field_type, f"unknown_{field_type}"),
            "_type_code": field_type,
        }

        if field_type == 6:  # objectid
            width = reader.read_ubyte()
            flag = reader.read_ubyte()
            finfo["nullable"] = bool(flag & 1)
            finfo["width"] = width

        elif field_type == 7:  # geometry
            reader.read_ubyte()  # unknown
            flag = reader.read_ubyte()
            finfo["nullable"] = bool(flag & 1)

            wkt_len = reader.read_int16()
            reader.read(wkt_len)  # WKT string

            geom_flags = reader.read_ubyte()
            has_z = bool(geom_flags & 2)
            has_m = bool(geom_flags & 4)

            xorigin = reader.read_float64()
            yorigin = reader.read_float64()
            xyscale = reader.read_float64()

            if has_m:
                reader.read_float64()  # morigin
                reader.read_float64()  # mscale
            if has_z:
                reader.read_float64()  # zorigin
                reader.read_float64()  # zscale

            reader.read_float64()  # xytolerance
            if has_m:
                reader.read_float64()  # mtolerance
            if has_z:
                reader.read_float64()  # ztolerance

            reader.read_float64()  # xmin
            reader.read_float64()  # ymin
            reader.read_float64()  # xmax
            reader.read_float64()  # ymax

            if has_z_layer:
                reader.read_float64()  # zmin
                reader.read_float64()  # zmax
            if has_m_layer:
                reader.read_float64()  # mmin
                reader.read_float64()  # mmax

            reader.read_ubyte()  # spatial index indicator
            num_grids = reader.read_uint32()
            for _ in range(num_grids):
                reader.read_float64()

            finfo["geometry_type"] = GEOM_TYPE_NAMES.get(geom_type_code, f"unknown_{geom_type_code}")
            finfo["_xorigin"] = xorigin
            finfo["_yorigin"] = yorigin
            finfo["_xyscale"] = xyscale
            finfo["_has_z"] = has_z
            finfo["_has_m"] = has_m

        elif field_type == 4:  # string
            max_length = reader.read_int32()
            flag = reader.read_ubyte()
            finfo["nullable"] = bool(flag & 1)
            finfo["max_length"] = max_length
            if flag & 4:
                ldf = reader.read_varuint()
                if ldf > 0:
                    reader.read(ldf)

        elif field_type in (0, 1, 2, 3, 5, 13):  # numeric types
            width = reader.read_ubyte()
            flag = reader.read_ubyte()
            finfo["nullable"] = bool(flag & 1)
            finfo["width"] = width
            if flag & 4:
                ldf = reader.read_ubyte()
                if ldf > 0:
                    reader.read(ldf)

        elif field_type in (10, 11):  # GUID / GlobalID
            width = reader.read_ubyte()
            flag = reader.read_ubyte()
            finfo["nullable"] = bool(flag & 1)

        elif field_type == 12:  # XML
            reader.read_ubyte()  # width
            flag = reader.read_ubyte()
            finfo["nullable"] = bool(flag & 1)

        elif field_type == 8:  # binary
            reader.read_ubyte()
            flag = reader.read_ubyte()
            finfo["nullable"] = bool(flag & 1)

        fields.append(finfo)

    return fields, is_utf8


def parse_gdbtablx(path):
    with open(path, 'rb') as f:
        data = f.read()

    reader = BinaryReader(data)
    version = reader.read_int32()
    n1024_blocks = reader.read_int32()

    if version == 3:
        num_rows = reader.read_int32()
    elif version == 4:
        reader.read_int32()
        num_rows = None

    size_offset = reader.read_int32()

    if version == 4:
        trailing_offset = 16 + size_offset * n1024_blocks * 1024
        reader.seek(trailing_offset)
        num_rows = reader.read_int64()

    offsets = []
    reader.seek(16)
    for _ in range(num_rows):
        if size_offset == 4:
            offset = reader.read_uint32()
        elif size_offset == 5:
            low = reader.read_uint32()
            high = reader.read_ubyte()
            offset = low | (high << 32)
        elif size_offset == 6:
            low = reader.read_uint32()
            high = reader.read_uint16()
            offset = low | (high << 32)
        else:
            raise ValueError(f"Unsupported size_offset: {size_offset}")
        offsets.append(offset)

    return offsets


def decode_point(reader, xorigin, yorigin, xyscale):
    x_raw = reader.read_varuint()
    if x_raw == 0:
        return {"type": "Point", "coordinates": []}
    x = (x_raw - 1) / xyscale + xorigin
    y_raw = reader.read_varuint()
    y = (y_raw - 1) / xyscale + yorigin
    return {"type": "Point", "coordinates": [x, y]}


def decode_polyline(reader, xorigin, yorigin, xyscale):
    total_points = reader.read_varuint()
    num_parts = reader.read_varuint()

    # Bounding box (read but not used for output)
    reader.read_varuint()  # xmin
    reader.read_varuint()  # ymin
    reader.read_varuint()  # xmax_delta
    reader.read_varuint()  # ymax_delta

    # Part sizes
    part_sizes = []
    if num_parts > 1:
        remaining = total_points
        for _ in range(num_parts - 1):
            ps = reader.read_varuint()
            part_sizes.append(ps)
            remaining -= ps
        part_sizes.append(remaining)
    else:
        part_sizes = [total_points]

    # Delta-encoded coordinates
    parts = []
    dx, dy = 0, 0
    for pi in range(num_parts):
        coords = []
        for _ in range(part_sizes[pi]):
            dx += reader.read_varint()
            dy += reader.read_varint()
            x = dx / xyscale + xorigin
            y = dy / xyscale + yorigin
            coords.append([x, y])
        parts.append(coords)

    return {"type": "MultiLineString", "coordinates": parts}


def parse_row(reader, fields, is_utf8):
    blob_len = reader.read_int32()
    blob_end = reader.pos + blob_len

    # Identify nullable fields (by index in the fields list)
    nullable_fields = []
    for i, f in enumerate(fields):
        if f.get("nullable", False):
            nullable_fields.append(i)
    num_nullable = len(nullable_fields)

    # Read null flags bitmap
    null_flags = {}
    if num_nullable > 0:
        flag_bytes_count = (num_nullable + 7) // 8
        flag_bytes = reader.read(flag_bytes_count)
        for null_idx, field_idx in enumerate(nullable_fields):
            byte_idx = null_idx // 8
            bit_idx = null_idx % 8
            is_null = bool(flag_bytes[byte_idx] & (1 << bit_idx))
            null_flags[field_idx] = is_null

    row = {}
    for i, field in enumerate(fields):
        tc = field["_type_code"]

        if tc == 6:  # objectid - implicit, no data
            continue

        if null_flags.get(i, False):
            row[field["name"]] = None
            continue

        if tc == 7:  # geometry
            geom_blob_len = reader.read_varuint()
            geom_start = reader.pos
            geom_type = reader.read_varuint()

            xorigin = field.get("_xorigin", 0)
            yorigin = field.get("_yorigin", 0)
            xyscale = field.get("_xyscale", 1)

            base_type = geom_type & 0xFF
            if base_type in (1, 9, 21, 11):
                geom = decode_point(reader, xorigin, yorigin, xyscale)
            elif base_type in (3, 10, 23, 13):
                geom = decode_polyline(reader, xorigin, yorigin, xyscale)
            else:
                geom = {"type": "Unknown", "geometry_type_code": geom_type}

            reader.seek(geom_start + geom_blob_len)
            row[field["name"]] = geom

        elif tc == 4:  # string
            str_len = reader.read_varuint()
            if is_utf8:
                s = reader.read(str_len).decode('utf-8')
            else:
                s = reader.read(str_len).decode('utf-16-le')
            row[field["name"]] = s

        elif tc == 0:  # int16
            row[field["name"]] = reader.read_int16()
        elif tc == 1:  # int32
            row[field["name"]] = reader.read_int32()
        elif tc == 2:  # float32
            row[field["name"]] = round(reader.read_float32(), 6)
        elif tc == 3:  # float64
            row[field["name"]] = reader.read_float64()
        elif tc == 5:  # datetime
            row[field["name"]] = reader.read_float64()
        elif tc == 13:  # int64
            row[field["name"]] = reader.read_int64()
        elif tc == 12:  # XML
            xml_len = reader.read_varuint()
            row[field["name"]] = reader.read(xml_len).decode('utf-8', errors='replace')
        elif tc == 8:  # binary
            bin_len = reader.read_varuint()
            row[field["name"]] = reader.read(bin_len).hex()
        elif tc in (10, 11):  # UUID/GlobalID
            b = reader.read(16)
            uuid_str = "{%02X%02X%02X%02X-%02X%02X-%02X%02X-%02X%02X-%02X%02X%02X%02X%02X%02X}" % (
                b[3], b[2], b[1], b[0], b[5], b[4], b[7], b[6],
                b[8], b[9], b[10], b[11], b[12], b[13], b[14], b[15])
            row[field["name"]] = uuid_str

    reader.seek(blob_end)
    return row


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 fgdb_parse.py <path_to_gdbtable>", file=sys.stderr)
        sys.exit(1)

    gdbtable_path = sys.argv[1]
    gdbtablx_path = os.path.splitext(gdbtable_path)[0] + '.gdbtablx'

    with open(gdbtable_path, 'rb') as f:
        table_data = f.read()

    reader = BinaryReader(table_data)
    header = parse_header(reader)
    fields, is_utf8 = parse_fields(reader, header["field_desc_offset"])

    row_offsets = parse_gdbtablx(gdbtablx_path)

    rows = []
    for idx, offset in enumerate(row_offsets):
        objectid = idx + 1
        if offset == 0:
            continue
        reader.seek(offset)
        row = parse_row(reader, fields, is_utf8)
        row["OBJECTID"] = objectid
        rows.append(row)

    # Build clean field output (strip internal keys)
    field_output = []
    for f in fields:
        fo = {"name": f["name"], "type": f["type"], "nullable": f.get("nullable", False)}
        if "max_length" in f:
            fo["max_length"] = f["max_length"]
        if "width" in f:
            fo["width"] = f["width"]
        if "geometry_type" in f:
            fo["geometry_type"] = f["geometry_type"]
        field_output.append(fo)

    output = {
        "header": header,
        "fields": field_output,
        "rows": rows,
    }
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
