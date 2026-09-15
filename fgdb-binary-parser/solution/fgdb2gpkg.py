#!/usr/bin/env python3
"""FileGDB .gdbtable to GeoPackage (.gpkg) converter.

"""

import struct
import sys
import os
import sqlite3


# --- Constants ---

FGDB_TO_GPKG_GEOM = {
    1: "POINT",
    3: "MULTILINESTRING",
    4: "MULTIPOLYGON",
}

WGS84_WKT = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563,'
    'AUTHORITY["EPSG","7030"]],'
    'AUTHORITY["EPSG","6326"]],'
    'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433,'
    'AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4326"]]'
)


# --- Binary Reader ---

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

    def read_int32(self):
        return struct.unpack('<i', self.read(4))[0]

    def read_uint32(self):
        return struct.unpack('<I', self.read(4))[0]

    def read_int64(self):
        return struct.unpack('<q', self.read(8))[0]

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


# --- FGDB Parsing ---

def parse_header(reader):
    reader.seek(0)
    version = reader.read_int32()
    num_valid_rows = reader.read_int32()
    reader.read_int32()  # max_size
    reader.read_int32()  # unknown (==5)
    reader.read(4)       # varying
    reader.read(4)       # zeros
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
            "_type_code": field_type,
        }

        if field_type == 6:  # objectid
            width = reader.read_ubyte()
            flag = reader.read_ubyte()
            finfo["nullable"] = bool(flag & 1)

        elif field_type == 7:  # geometry
            reader.read_ubyte()  # unknown
            flag = reader.read_ubyte()
            finfo["nullable"] = bool(flag & 1)

            wkt_len = reader.read_int16()
            reader.read(wkt_len)  # WKT

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

            xmin = reader.read_float64()
            ymin = reader.read_float64()
            xmax = reader.read_float64()
            ymax = reader.read_float64()

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

            finfo["_xorigin"] = xorigin
            finfo["_yorigin"] = yorigin
            finfo["_xyscale"] = xyscale
            finfo["_extent"] = (xmin, ymin, xmax, ymax)

        elif field_type == 4:  # string
            max_length = reader.read_int32()
            flag = reader.read_ubyte()
            finfo["nullable"] = bool(flag & 1)
            if flag & 4:
                ldf = reader.read_varuint()
                if ldf > 0:
                    reader.read(ldf)

        elif field_type in (0, 1, 2, 3, 5):  # numeric types
            width = reader.read_ubyte()
            flag = reader.read_ubyte()
            finfo["nullable"] = bool(flag & 1)
            if flag & 4:
                ldf = reader.read_ubyte()
                if ldf > 0:
                    reader.read(ldf)

        fields.append(finfo)

    return fields, is_utf8, geom_type_code


def parse_gdbtablx(path):
    with open(path, 'rb') as f:
        data = f.read()
    reader = BinaryReader(data)
    version = reader.read_int32()
    n1024_blocks = reader.read_int32()
    num_rows = reader.read_int32()
    size_offset = reader.read_int32()

    offsets = []
    reader.seek(16)
    for _ in range(num_rows):
        if size_offset == 4:
            offset = reader.read_uint32()
        elif size_offset == 5:
            low = reader.read_uint32()
            high = reader.read_ubyte()
            offset = low | (high << 32)
        else:
            raise ValueError(f"Unsupported size_offset: {size_offset}")
        offsets.append(offset)
    return offsets


def decode_point(reader, xorigin, yorigin, xyscale):
    x_raw = reader.read_varuint()
    if x_raw == 0:
        return None
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

    # Identify nullable fields
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

        if tc == 6:  # objectid - implicit
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
                geom = None

            reader.seek(geom_start + geom_blob_len)
            row[field["name"]] = geom

        elif tc == 4:  # string
            str_len = reader.read_varuint()
            if is_utf8:
                s = reader.read(str_len).decode('utf-8')
            else:
                s = reader.read(str_len).decode('utf-16-le')
            row[field["name"]] = s

        elif tc == 1:  # int32
            row[field["name"]] = reader.read_int32()
        elif tc == 3:  # float64
            row[field["name"]] = reader.read_float64()

    reader.seek(blob_end)
    return row


# --- WKB Encoding ---

def encode_wkb_point(x, y):
    """Encode a Point as OGC WKB (little-endian)."""
    return struct.pack('<BIdd', 1, 1, x, y)


def encode_wkb_multilinestring(parts):
    """Encode a MultiLineString as OGC WKB (little-endian)."""
    data = struct.pack('<BI', 1, 5)  # byte_order=LE, type=MultiLineString
    data += struct.pack('<I', len(parts))
    for part in parts:
        data += struct.pack('<BI', 1, 2)  # byte_order=LE, type=LineString
        data += struct.pack('<I', len(part))
        for coord in part:
            data += struct.pack('<dd', coord[0], coord[1])
    return data


# --- GeoPackage Binary ---

def encode_gpkg_geom(geom_dict, srs_id):
    """Encode a geometry dict as GeoPackage Standard Binary."""
    if geom_dict is None:
        return None

    gtype = geom_dict["type"]
    coords = geom_dict["coordinates"]

    if gtype == "Point":
        wkb = encode_wkb_point(coords[0], coords[1])
        minx = maxx = coords[0]
        miny = maxy = coords[1]
    elif gtype == "MultiLineString":
        wkb = encode_wkb_multilinestring(coords)
        all_x = [p[0] for part in coords for p in part]
        all_y = [p[1] for part in coords for p in part]
        minx, maxx = min(all_x), max(all_x)
        miny, maxy = min(all_y), max(all_y)
    else:
        return None

    # GP header: magic(2) + version(1) + flags(1) + srs_id(4)
    # flags: bit0=1 (LE), bits1-3=001 (envelope type 1) => 0x03
    flags = 0x03
    header = b'GP' + struct.pack('<BBI', 0, flags, srs_id)
    # Envelope: minx, maxx, miny, maxy
    envelope = struct.pack('<dddd', minx, maxx, miny, maxy)

    return header + envelope + wkb


# --- GeoPackage Creation ---

def create_gpkg(output_path, table_name, fields, rows, geom_type_code, geom_extent):
    """Create a valid OGC GeoPackage from parsed FGDB data."""
    if os.path.exists(output_path):
        os.remove(output_path)

    conn = sqlite3.connect(output_path)
    c = conn.cursor()

    # Set GeoPackage identification pragmas
    c.execute("PRAGMA application_id = 0x47504B47")
    c.execute("PRAGMA user_version = 10400")

    # --- gpkg_spatial_ref_sys ---
    c.execute("""CREATE TABLE gpkg_spatial_ref_sys (
        srs_name TEXT NOT NULL,
        srs_id INTEGER NOT NULL PRIMARY KEY,
        organization TEXT NOT NULL,
        organization_coordsys_id INTEGER NOT NULL,
        definition TEXT NOT NULL,
        description TEXT
    )""")
    c.execute("INSERT INTO gpkg_spatial_ref_sys VALUES (?, ?, ?, ?, ?, ?)",
              ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", None))
    c.execute("INSERT INTO gpkg_spatial_ref_sys VALUES (?, ?, ?, ?, ?, ?)",
              ("Undefined geographic SRS", 0, "NONE", 0, "undefined", None))
    c.execute("INSERT INTO gpkg_spatial_ref_sys VALUES (?, ?, ?, ?, ?, ?)",
              ("WGS 84 geodetic", 4326, "EPSG", 4326, WGS84_WKT, None))

    # --- gpkg_contents ---
    c.execute("""CREATE TABLE gpkg_contents (
        table_name TEXT NOT NULL PRIMARY KEY,
        data_type TEXT NOT NULL DEFAULT '',
        identifier TEXT UNIQUE,
        description TEXT DEFAULT '',
        last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        min_x DOUBLE,
        min_y DOUBLE,
        max_x DOUBLE,
        max_y DOUBLE,
        srs_id INTEGER,
        CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
    )""")

    has_geom = geom_type_code != 0

    # --- gpkg_geometry_columns ---
    c.execute("""CREATE TABLE gpkg_geometry_columns (
        table_name TEXT NOT NULL,
        column_name TEXT NOT NULL,
        geometry_type_name TEXT NOT NULL,
        srs_id INTEGER NOT NULL,
        z TINYINT NOT NULL,
        m TINYINT NOT NULL,
        CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
        CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
        CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
    )""")

    if has_geom and geom_extent is not None:
        gpkg_geom_type = FGDB_TO_GPKG_GEOM.get(geom_type_code, "GEOMETRY")
        c.execute(
            "INSERT INTO gpkg_contents "
            "(table_name, data_type, identifier, srs_id, min_x, min_y, max_x, max_y) "
            "VALUES (?, 'features', ?, 4326, ?, ?, ?, ?)",
            (table_name, table_name,
             geom_extent[0], geom_extent[1], geom_extent[2], geom_extent[3]))
        c.execute(
            "INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, 4326, 0, 0)",
            (table_name, gpkg_geom_type))
    else:
        c.execute(
            "INSERT INTO gpkg_contents "
            "(table_name, data_type, identifier) "
            "VALUES (?, 'attributes', ?)",
            (table_name, table_name))

    # --- Build feature table ---
    col_defs = ['"fid" INTEGER PRIMARY KEY']
    col_names = ["fid"]

    geom_field_name = None
    if has_geom:
        col_defs.append('"geom" BLOB')
        col_names.append("geom")

    attr_fields = []
    for f in fields:
        tc = f["_type_code"]
        if tc == 6:  # objectid - becomes fid
            continue
        if tc == 7:  # geometry - becomes geom
            geom_field_name = f["name"]
            continue
        name = f["name"]
        if tc == 4:  # string
            col_defs.append(f'"{name}" TEXT')
        elif tc == 1:  # int32
            col_defs.append(f'"{name}" INTEGER')
        elif tc == 3:  # float64
            col_defs.append(f'"{name}" REAL')
        else:
            continue
        col_names.append(name)
        attr_fields.append(f)

    create_sql = f'CREATE TABLE "{table_name}" ({", ".join(col_defs)})'
    c.execute(create_sql)

    # --- Insert rows ---
    placeholders = ", ".join(["?"] * len(col_names))
    quoted_cols = ", ".join([f'"{cn}"' for cn in col_names])
    insert_sql = f'INSERT INTO "{table_name}" ({quoted_cols}) VALUES ({placeholders})'

    for row_data in rows:
        values = [row_data["_objectid"]]

        if has_geom:
            geom_dict = row_data.get("_geom")
            gpkg_blob = encode_gpkg_geom(geom_dict, 4326)
            values.append(gpkg_blob)

        for f in attr_fields:
            values.append(row_data.get(f["name"]))

        c.execute(insert_sql, values)

    conn.commit()
    conn.close()


# --- Main ---

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 fgdb2gpkg.py <input.gdbtable> <output.gpkg>",
              file=sys.stderr)
        sys.exit(1)

    gdbtable_path = sys.argv[1]
    output_path = sys.argv[2]
    gdbtablx_path = os.path.splitext(gdbtable_path)[0] + '.gdbtablx'
    table_name = os.path.splitext(os.path.basename(gdbtable_path))[0]

    with open(gdbtable_path, 'rb') as f:
        table_data = f.read()

    reader = BinaryReader(table_data)
    header = parse_header(reader)
    fields, is_utf8, geom_type_code = parse_fields(reader, header["field_desc_offset"])

    row_offsets = parse_gdbtablx(gdbtablx_path)

    # Find geometry field info
    geom_extent = None
    geom_field_name = None
    for f in fields:
        if f["_type_code"] == 7:
            geom_extent = f.get("_extent")
            geom_field_name = f["name"]
            break

    # Parse all rows
    rows = []
    for idx, offset in enumerate(row_offsets):
        objectid = idx + 1
        if offset == 0:
            continue
        reader.seek(offset)
        row = parse_row(reader, fields, is_utf8)
        row["_objectid"] = objectid
        if geom_field_name and geom_field_name in row:
            row["_geom"] = row.pop(geom_field_name)
        rows.append(row)

    create_gpkg(output_path, table_name, fields, rows, geom_type_code, geom_extent)


if __name__ == '__main__':
    main()
