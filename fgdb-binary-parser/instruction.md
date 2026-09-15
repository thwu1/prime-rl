Build `/app/fgdb2gpkg.py` — a Python CLI that reads ESRI FileGDB `.gdbtable` binary tables and produces valid OGC GeoPackage (`.gpkg`) files.

**Invocation:** `python3 /app/fgdb2gpkg.py <input.gdbtable> <output.gpkg>`

The companion `.gdbtablx` index shares the same directory and base name. A reverse-engineered format specification is at `/app/fgdb_spec.txt`.

**FGDB parsing scope:**
- Version 3 `.gdbtable`/`.gdbtablx` (32-bit OBJECTID)
- Field types: objectid (6), string (4), int32 (1), float64 (3), geometry (7)
- 2D point and polyline geometries (multi-part)
- Nullable field bitmaps; varuint/varint variable-length integer encodings per the spec
- Deleted rows (offset 0 in `.gdbtablx`) excluded; OBJECTID = 1-based index position

**GeoPackage output:**

The output must be a valid SQLite database per OGC GeoPackage 1.4. Set `application_id` to `0x47504B47`.

*Metadata tables:*
- `gpkg_spatial_ref_sys`: at least EPSG:4326 (`srs_id=4326`, `organization="EPSG"`, `organization_coordsys_id=4326`, WKT1 definition for WGS 84), undefined Cartesian (`srs_id=-1`), undefined geographic (`srs_id=0`)
- `gpkg_contents`: one entry per table — `data_type="features"` for spatial layers (with `srs_id=4326` and layer extent from the geometry field description), `data_type="attributes"` for non-spatial tables
- `gpkg_geometry_columns`: one entry per spatial layer — `column_name="geom"`, `geometry_type_name` of `"POINT"` or `"MULTILINESTRING"`, `srs_id=4326`, `z=0`, `m=0`

*Feature/attribute table:*
- Named from the input base filename (without extension)
- `fid` INTEGER PRIMARY KEY (set to OBJECTID value)
- `geom` BLOB column for spatial layers (geometry column)
- Attribute columns: string→TEXT, int32→INTEGER, float64→REAL
- Null field values → SQL NULL; deleted rows omitted; null geometries → SQL NULL

*Geometry encoding:*
GeoPackage Standard Binary: magic `0x47 0x50`, version `0`, flags byte `0x03` (little-endian + envelope type 1 for 2D), `srs_id` as int32 LE, 2D envelope (minx, maxx, miny, maxy as four float64 LE), then OGC WKB payload in little-endian byte order. WKB type codes: Point=1, LineString=2, MultiLineString=5.

*Validation:*
`ogrinfo <output.gpkg>` must list the layer. `ogrinfo -al <output.gpkg>` must show all features with correct field values and geometry coordinates.
