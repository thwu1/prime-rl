"""Tests for FileGDB-to-GeoPackage converter.

"""

import struct
import subprocess
import os
import sqlite3
import pytest


TESTDATA = "/app/testdata"
CONVERTER = "/app/fgdb2gpkg.py"


# ===== Helpers =====

def run_converter(gdbtable_name):
    """Run the converter and return the output gpkg path."""
    base = os.path.splitext(gdbtable_name)[0]
    input_path = os.path.join(TESTDATA, gdbtable_name)
    output_path = os.path.join(TESTDATA, f"{base}.gpkg")
    result = subprocess.run(
        ["python3", CONVERTER, input_path, output_path],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"Converter failed for {gdbtable_name}: {result.stderr}"
    return output_path


def parse_gpkg_blob(blob):
    """Parse a GeoPackage Standard Binary geometry blob."""
    assert blob[:2] == b'GP', f"Invalid GP magic: {blob[:2]!r}"
    version = blob[2]
    flags = blob[3]
    byte_order = flags & 1
    envelope_type = (flags >> 1) & 0x07
    srs_id = struct.unpack('<i', blob[4:8])[0]

    offset = 8
    envelope = None
    if envelope_type == 1:
        envelope = struct.unpack('<dddd', blob[offset:offset + 32])
        offset += 32
    elif envelope_type == 2:
        envelope = struct.unpack('<6d', blob[offset:offset + 48])
        offset += 48

    wkb = blob[offset:]
    return {
        "version": version,
        "flags": flags,
        "byte_order": byte_order,
        "envelope_type": envelope_type,
        "srs_id": srs_id,
        "envelope": envelope,
        "wkb": wkb,
    }


def parse_wkb_point(wkb):
    """Parse WKB Point and return (x, y)."""
    bo = wkb[0]
    wtype = struct.unpack('<I', wkb[1:5])[0]
    assert wtype == 1, f"Expected WKB Point type (1), got {wtype}"
    x, y = struct.unpack('<dd', wkb[5:21])
    return x, y


def parse_wkb_multilinestring(wkb):
    """Parse WKB MultiLineString and return list of parts."""
    bo = wkb[0]
    wtype = struct.unpack('<I', wkb[1:5])[0]
    assert wtype == 5, f"Expected WKB MultiLineString type (5), got {wtype}"
    num_geoms = struct.unpack('<I', wkb[5:9])[0]
    offset = 9
    parts = []
    for _ in range(num_geoms):
        offset += 1  # byte_order
        wtype2 = struct.unpack('<I', wkb[offset:offset + 4])[0]
        offset += 4
        assert wtype2 == 2, f"Expected WKB LineString type (2), got {wtype2}"
        npts = struct.unpack('<I', wkb[offset:offset + 4])[0]
        offset += 4
        coords = []
        for _ in range(npts):
            x, y = struct.unpack('<dd', wkb[offset:offset + 16])
            offset += 16
            coords.append((x, y))
        parts.append(coords)
    return parts


def run_ogrinfo(gpkg_path, all_layers=False):
    """Run ogrinfo and return the result."""
    cmd = ["ogrinfo"]
    if all_layers:
        cmd.append("-al")
    cmd.append(gpkg_path)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result


# ===== Module-level fixture: run converters =====

@pytest.fixture(scope="module", autouse=True)
def convert_all():
    """Run the converter on all test .gdbtable files."""
    for name in ["test1.gdbtable", "test2.gdbtable", "test3.gdbtable"]:
        run_converter(name)


# ===== Test 1: Non-spatial table =====

class TestNonSpatialGpkg:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.conn = sqlite3.connect(os.path.join(TESTDATA, "test1.gpkg"))
        yield
        self.conn.close()

    def test_application_id(self):
        row = self.conn.execute("PRAGMA application_id").fetchone()
        assert row[0] == 0x47504B47, f"application_id should be 0x47504B47, got {hex(row[0])}"

    def test_srs_entries_exist(self):
        rows = self.conn.execute(
            "SELECT srs_id FROM gpkg_spatial_ref_sys ORDER BY srs_id"
        ).fetchall()
        srs_ids = [r[0] for r in rows]
        assert -1 in srs_ids, "Missing undefined Cartesian SRS (srs_id=-1)"
        assert 0 in srs_ids, "Missing undefined geographic SRS (srs_id=0)"
        assert 4326 in srs_ids, "Missing EPSG:4326 SRS"

    def test_srs_4326_organization(self):
        row = self.conn.execute(
            "SELECT organization, organization_coordsys_id FROM gpkg_spatial_ref_sys WHERE srs_id=4326"
        ).fetchone()
        assert row is not None
        assert row[0] == "EPSG"
        assert row[1] == 4326

    def test_contents_entry(self):
        row = self.conn.execute(
            "SELECT data_type FROM gpkg_contents WHERE table_name='test1'"
        ).fetchone()
        assert row is not None, "No gpkg_contents entry for test1"
        assert row[0] == "attributes", f"Expected data_type='attributes', got '{row[0]}'"

    def test_no_geometry_columns_entry(self):
        row = self.conn.execute(
            "SELECT COUNT(*) FROM gpkg_geometry_columns WHERE table_name='test1'"
        ).fetchone()
        assert row[0] == 0, "Non-spatial table should have no gpkg_geometry_columns entry"

    def test_row_count(self):
        row = self.conn.execute("SELECT COUNT(*) FROM test1").fetchone()
        assert row[0] == 3, f"Expected 3 rows (deleted row excluded), got {row[0]}"

    def test_fid_values(self):
        rows = self.conn.execute("SELECT fid FROM test1 ORDER BY fid").fetchall()
        fids = [r[0] for r in rows]
        assert fids == [1, 3, 4], f"Expected fids [1, 3, 4], got {fids}"

    def test_row1_values(self):
        row = self.conn.execute(
            "SELECT fid, Name, Score FROM test1 WHERE fid=1"
        ).fetchone()
        assert row[0] == 1
        assert row[1] == "Alice"
        assert row[2] == 95

    def test_row3_null_score(self):
        row = self.conn.execute(
            "SELECT Name, Score FROM test1 WHERE fid=3"
        ).fetchone()
        assert row[0] == "Bob"
        assert row[1] is None, "Score should be NULL for fid=3"

    def test_row4_null_name(self):
        row = self.conn.execute(
            "SELECT Name, Score FROM test1 WHERE fid=4"
        ).fetchone()
        assert row[0] is None, "Name should be NULL for fid=4"
        assert row[1] == 42


# ===== Test 2: Point geometry =====

class TestPointGpkg:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.conn = sqlite3.connect(os.path.join(TESTDATA, "test2.gpkg"))
        yield
        self.conn.close()

    def test_contents_features(self):
        row = self.conn.execute(
            "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name='test2'"
        ).fetchone()
        assert row is not None
        assert row[0] == "features"
        assert row[1] == 4326

    def test_contents_extent(self):
        row = self.conn.execute(
            "SELECT min_x, min_y, max_x, max_y FROM gpkg_contents WHERE table_name='test2'"
        ).fetchone()
        assert row is not None
        assert row[0] is not None, "min_x should be set"
        assert row[1] is not None, "min_y should be set"

    def test_geometry_columns_entry(self):
        row = self.conn.execute(
            "SELECT column_name, geometry_type_name, srs_id, z, m "
            "FROM gpkg_geometry_columns WHERE table_name='test2'"
        ).fetchone()
        assert row is not None, "No gpkg_geometry_columns entry for test2"
        assert row[0] == "geom"
        assert row[1] == "POINT"
        assert row[2] == 4326
        assert row[3] == 0
        assert row[4] == 0

    def test_row_count(self):
        row = self.conn.execute("SELECT COUNT(*) FROM test2").fetchone()
        assert row[0] == 2

    def test_fid_values(self):
        rows = self.conn.execute("SELECT fid FROM test2 ORDER BY fid").fetchall()
        assert [r[0] for r in rows] == [1, 2]

    def test_label_values(self):
        rows = self.conn.execute(
            "SELECT fid, Label FROM test2 ORDER BY fid"
        ).fetchall()
        assert rows[0][1] == "CityA"
        assert rows[1][1] == "CityB"

    def test_point1_gpkg_binary_header(self):
        row = self.conn.execute("SELECT geom FROM test2 WHERE fid=1").fetchone()
        blob = row[0]
        gpkg = parse_gpkg_blob(blob)
        assert gpkg["version"] == 0
        assert gpkg["byte_order"] == 1, "Expected little-endian"
        assert gpkg["envelope_type"] == 1, "Expected envelope type 1 (2D)"
        assert gpkg["srs_id"] == 4326

    def test_point1_wkb(self):
        row = self.conn.execute("SELECT geom FROM test2 WHERE fid=1").fetchone()
        gpkg = parse_gpkg_blob(row[0])
        x, y = parse_wkb_point(gpkg["wkb"])
        assert abs(x - 10.0) < 1e-6, f"Expected x=10.0, got {x}"
        assert abs(y - 20.0) < 1e-6, f"Expected y=20.0, got {y}"

    def test_point1_envelope(self):
        row = self.conn.execute("SELECT geom FROM test2 WHERE fid=1").fetchone()
        gpkg = parse_gpkg_blob(row[0])
        minx, maxx, miny, maxy = gpkg["envelope"]
        assert abs(minx - 10.0) < 1e-6
        assert abs(maxx - 10.0) < 1e-6
        assert abs(miny - 20.0) < 1e-6
        assert abs(maxy - 20.0) < 1e-6

    def test_point2_wkb(self):
        row = self.conn.execute("SELECT geom FROM test2 WHERE fid=2").fetchone()
        gpkg = parse_gpkg_blob(row[0])
        x, y = parse_wkb_point(gpkg["wkb"])
        assert abs(x - 50.5) < 1e-6, f"Expected x=50.5, got {x}"
        assert abs(y - 75.25) < 1e-6, f"Expected y=75.25, got {y}"

    def test_point2_envelope(self):
        row = self.conn.execute("SELECT geom FROM test2 WHERE fid=2").fetchone()
        gpkg = parse_gpkg_blob(row[0])
        minx, maxx, miny, maxy = gpkg["envelope"]
        assert abs(minx - 50.5) < 1e-6
        assert abs(maxx - 50.5) < 1e-6
        assert abs(miny - 75.25) < 1e-6
        assert abs(maxy - 75.25) < 1e-6

    def test_ogrinfo_lists_layer(self):
        result = run_ogrinfo(os.path.join(TESTDATA, "test2.gpkg"))
        assert result.returncode == 0, f"ogrinfo failed: {result.stderr}"
        assert "GPKG" in result.stdout, "ogrinfo should detect GPKG driver"
        assert "test2" in result.stdout, "ogrinfo should list test2 layer"

    def test_ogrinfo_shows_features(self):
        result = run_ogrinfo(os.path.join(TESTDATA, "test2.gpkg"), all_layers=True)
        assert result.returncode == 0, f"ogrinfo -al failed: {result.stderr}"
        assert "CityA" in result.stdout, "ogrinfo should show CityA"
        assert "CityB" in result.stdout, "ogrinfo should show CityB"


# ===== Test 3: Polyline geometry =====

class TestPolylineGpkg:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.conn = sqlite3.connect(os.path.join(TESTDATA, "test3.gpkg"))
        yield
        self.conn.close()

    def test_geometry_columns_entry(self):
        row = self.conn.execute(
            "SELECT column_name, geometry_type_name, srs_id, z, m "
            "FROM gpkg_geometry_columns WHERE table_name='test3'"
        ).fetchone()
        assert row is not None
        assert row[0] == "geom"
        assert row[1] == "MULTILINESTRING"
        assert row[2] == 4326
        assert row[3] == 0
        assert row[4] == 0

    def test_contents_features(self):
        row = self.conn.execute(
            "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name='test3'"
        ).fetchone()
        assert row[0] == "features"
        assert row[1] == 4326

    def test_row_count(self):
        row = self.conn.execute("SELECT COUNT(*) FROM test3").fetchone()
        assert row[0] == 2

    def test_fid_values(self):
        rows = self.conn.execute("SELECT fid FROM test3 ORDER BY fid").fetchall()
        assert [r[0] for r in rows] == [1, 2]

    def test_polyline1_route(self):
        row = self.conn.execute("SELECT Route FROM test3 WHERE fid=1").fetchone()
        assert row[0] == "Route-A"

    def test_polyline1_distance(self):
        row = self.conn.execute("SELECT Distance FROM test3 WHERE fid=1").fetchone()
        assert abs(row[0] - 123.456) < 1e-9

    def test_polyline2_null_route(self):
        row = self.conn.execute("SELECT Route FROM test3 WHERE fid=2").fetchone()
        assert row[0] is None, "Route should be NULL for fid=2"

    def test_polyline2_distance(self):
        row = self.conn.execute("SELECT Distance FROM test3 WHERE fid=2").fetchone()
        assert abs(row[0] - 789.012) < 1e-9

    def test_polyline1_gpkg_binary_header(self):
        row = self.conn.execute("SELECT geom FROM test3 WHERE fid=1").fetchone()
        gpkg = parse_gpkg_blob(row[0])
        assert gpkg["version"] == 0
        assert gpkg["byte_order"] == 1
        assert gpkg["envelope_type"] == 1
        assert gpkg["srs_id"] == 4326

    def test_polyline1_wkb_structure(self):
        row = self.conn.execute("SELECT geom FROM test3 WHERE fid=1").fetchone()
        gpkg = parse_gpkg_blob(row[0])
        parts = parse_wkb_multilinestring(gpkg["wkb"])
        assert len(parts) == 2, f"Expected 2 parts, got {len(parts)}"

    def test_polyline1_part1_coords(self):
        """Part 1: (1,2) -> (3,4) -> (5,6)"""
        row = self.conn.execute("SELECT geom FROM test3 WHERE fid=1").fetchone()
        gpkg = parse_gpkg_blob(row[0])
        parts = parse_wkb_multilinestring(gpkg["wkb"])
        part = parts[0]
        assert len(part) == 3
        assert abs(part[0][0] - 1.0) < 1e-6
        assert abs(part[0][1] - 2.0) < 1e-6
        assert abs(part[1][0] - 3.0) < 1e-6
        assert abs(part[1][1] - 4.0) < 1e-6
        assert abs(part[2][0] - 5.0) < 1e-6
        assert abs(part[2][1] - 6.0) < 1e-6

    def test_polyline1_part2_coords(self):
        """Part 2: (10,20) -> (30,40)"""
        row = self.conn.execute("SELECT geom FROM test3 WHERE fid=1").fetchone()
        gpkg = parse_gpkg_blob(row[0])
        parts = parse_wkb_multilinestring(gpkg["wkb"])
        part = parts[1]
        assert len(part) == 2
        assert abs(part[0][0] - 10.0) < 1e-6
        assert abs(part[0][1] - 20.0) < 1e-6
        assert abs(part[1][0] - 30.0) < 1e-6
        assert abs(part[1][1] - 40.0) < 1e-6

    def test_polyline1_envelope(self):
        row = self.conn.execute("SELECT geom FROM test3 WHERE fid=1").fetchone()
        gpkg = parse_gpkg_blob(row[0])
        minx, maxx, miny, maxy = gpkg["envelope"]
        assert abs(minx - 1.0) < 1e-6
        assert abs(maxx - 30.0) < 1e-6
        assert abs(miny - 2.0) < 1e-6
        assert abs(maxy - 40.0) < 1e-6

    def test_polyline2_single_part(self):
        row = self.conn.execute("SELECT geom FROM test3 WHERE fid=2").fetchone()
        gpkg = parse_gpkg_blob(row[0])
        parts = parse_wkb_multilinestring(gpkg["wkb"])
        assert len(parts) == 1

    def test_polyline2_coords(self):
        """Single part: (50,50) -> (60,70) -> (80,90) -> (95,95)"""
        row = self.conn.execute("SELECT geom FROM test3 WHERE fid=2").fetchone()
        gpkg = parse_gpkg_blob(row[0])
        parts = parse_wkb_multilinestring(gpkg["wkb"])
        part = parts[0]
        assert len(part) == 4
        assert abs(part[0][0] - 50.0) < 1e-6
        assert abs(part[0][1] - 50.0) < 1e-6
        assert abs(part[1][0] - 60.0) < 1e-6
        assert abs(part[1][1] - 70.0) < 1e-6
        assert abs(part[2][0] - 80.0) < 1e-6
        assert abs(part[2][1] - 90.0) < 1e-6
        assert abs(part[3][0] - 95.0) < 1e-6
        assert abs(part[3][1] - 95.0) < 1e-6

    def test_polyline2_envelope(self):
        row = self.conn.execute("SELECT geom FROM test3 WHERE fid=2").fetchone()
        gpkg = parse_gpkg_blob(row[0])
        minx, maxx, miny, maxy = gpkg["envelope"]
        assert abs(minx - 50.0) < 1e-6
        assert abs(maxx - 95.0) < 1e-6
        assert abs(miny - 50.0) < 1e-6
        assert abs(maxy - 95.0) < 1e-6

    def test_ogrinfo_lists_layer(self):
        result = run_ogrinfo(os.path.join(TESTDATA, "test3.gpkg"))
        assert result.returncode == 0, f"ogrinfo failed: {result.stderr}"
        assert "GPKG" in result.stdout
        assert "test3" in result.stdout

    def test_ogrinfo_shows_features(self):
        result = run_ogrinfo(os.path.join(TESTDATA, "test3.gpkg"), all_layers=True)
        assert result.returncode == 0, f"ogrinfo -al failed: {result.stderr}"
        assert "Route-A" in result.stdout
        assert "Feature Count: 2" in result.stdout
