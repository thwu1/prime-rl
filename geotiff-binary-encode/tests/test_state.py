
"""
Verification tests for fixed GeoTIFF files.
Parses output TIFF files at the binary level and validates GeoKey encoding,
TIFF structure, and CRS metadata against OGC 19-008r4 requirements.
"""

import struct
import os
import math
import pytest


# DOUBLE-type GeoKeys per OGC 19-008r4 (stored in GeoDoubleParamsTag 34736)
DOUBLE_GEOKEYS = {
    2053, 2055, 2057, 2058, 2059, 2061,
    3077, 3078, 3079, 3080, 3081, 3082, 3083, 3084, 3085,
    3086, 3087, 3088, 3089, 3090, 3091, 3092, 3093, 3094, 3095,
    5120,
}

# ASCII-type GeoKeys (stored in GeoAsciiParamsTag 34737)
ASCII_GEOKEYS = {1026, 2049, 3073, 4097}


class TiffParser:
    """Minimal TIFF 6.0 binary parser for extracting GeoTIFF tags."""

    TYPE_SIZES = {
        1: 1, 2: 1, 3: 2, 4: 4, 5: 8,
        6: 1, 7: 1, 8: 2, 9: 4, 10: 8,
        11: 4, 12: 8,
    }

    def __init__(self, filepath):
        with open(filepath, 'rb') as f:
            self.data = f.read()
        self._parse_header()
        self._parse_ifd()

    def _parse_header(self):
        bo = self.data[0:2]
        if bo == b'II':
            self.endian = '<'
        elif bo == b'MM':
            self.endian = '>'
        else:
            raise ValueError(f"Invalid TIFF byte order: {bo!r}")
        magic = struct.unpack_from(self.endian + 'H', self.data, 2)[0]
        if magic != 42:
            raise ValueError(f"Invalid TIFF magic: {magic}")
        self.ifd_offset = struct.unpack_from(self.endian + 'I', self.data, 4)[0]

    def _parse_ifd(self):
        offset = self.ifd_offset
        num = struct.unpack_from(self.endian + 'H', self.data, offset)[0]
        offset += 2
        self.tags = {}
        self.tag_order = []
        for _ in range(num):
            tid = struct.unpack_from(self.endian + 'H', self.data, offset)[0]
            ttype = struct.unpack_from(self.endian + 'H', self.data, offset + 2)[0]
            count = struct.unpack_from(self.endian + 'I', self.data, offset + 4)[0]
            ts = self.TYPE_SIZES.get(ttype, 1)
            total = count * ts
            if total <= 4:
                doff = offset + 8
            else:
                doff = struct.unpack_from(self.endian + 'I', self.data, offset + 8)[0]
            self.tags[tid] = {'type': ttype, 'count': count, 'data_offset': doff}
            self.tag_order.append(tid)
            offset += 12

    def get_shorts(self, tag_id):
        tag = self.tags.get(tag_id)
        if tag is None:
            return None
        return list(struct.unpack_from(
            self.endian + f'{tag["count"]}H', self.data, tag['data_offset']
        ))

    def get_doubles(self, tag_id):
        tag = self.tags.get(tag_id)
        if tag is None:
            return None
        return list(struct.unpack_from(
            self.endian + f'{tag["count"]}d', self.data, tag['data_offset']
        ))

    def get_ascii_raw(self, tag_id):
        tag = self.tags.get(tag_id)
        if tag is None:
            return None
        return self.data[tag['data_offset']:tag['data_offset'] + tag['count']]

    def get_tag_value(self, tag_id):
        tag = self.tags.get(tag_id)
        if tag is None:
            return None
        if tag['type'] == 3:
            return struct.unpack_from(self.endian + 'H', self.data, tag['data_offset'])[0]
        elif tag['type'] == 4:
            return struct.unpack_from(self.endian + 'I', self.data, tag['data_offset'])[0]
        return None

    def get_geokey_raw_entries(self):
        """Return (header_tuple, list_of_entry_tuples) from GeoKeyDirectoryTag."""
        shorts = self.get_shorts(34735)
        if shorts is None:
            return None, None
        header = tuple(shorts[:4])
        entries = []
        for i in range(header[3]):
            base = 4 + i * 4
            entries.append(tuple(shorts[base:base + 4]))
        return header, entries

    def decode_geokeys(self):
        """Parse GeoKeyDirectoryTag into {key_id: decoded_value}."""
        shorts = self.get_shorts(34735)
        if shorts is None:
            return None
        version, revision, minor, num_keys = shorts[:4]
        doubles = self.get_doubles(34736)
        ascii_raw = self.get_ascii_raw(34737)

        result = {
            '_header': {
                'version': version, 'revision': revision,
                'minor_revision': minor, 'num_keys': num_keys,
            }
        }

        for i in range(num_keys):
            base = 4 + i * 4
            key_id = shorts[base]
            tiff_tag_loc = shorts[base + 1]
            count = shorts[base + 2]
            val_offset = shorts[base + 3]

            if tiff_tag_loc == 0:
                result[key_id] = val_offset
            elif tiff_tag_loc == 34736:
                if doubles is not None and count == 1:
                    result[key_id] = doubles[val_offset]
                elif doubles is not None:
                    result[key_id] = doubles[val_offset:val_offset + count]
            elif tiff_tag_loc == 34737:
                if ascii_raw is not None:
                    raw = ascii_raw[val_offset:val_offset + count]
                    text = raw.decode('ascii', errors='replace').rstrip('|')
                    result[key_id] = text

        return result


# ─── Shared validation helpers ────────────────────────────────────

def assert_ifd_sorted(tiff):
    assert tiff.tag_order == sorted(tiff.tag_order), \
        f"IFD entries not sorted by tag ID: {tiff.tag_order}"


def assert_geokey_header(tiff):
    hdr, _ = tiff.get_geokey_raw_entries()
    assert hdr is not None, "GeoKeyDirectoryTag (34735) not found"
    assert hdr[0] == 1, f"KeyDirectoryVersion={hdr[0]}, expected 1"
    assert hdr[1] == 1, f"KeyRevision={hdr[1]}, expected 1"
    assert hdr[2] == 1, f"MinorRevision={hdr[2]}, expected 1 (GeoTIFF 1.1)"


def assert_geokey_sorted(tiff):
    _, entries = tiff.get_geokey_raw_entries()
    key_ids = [e[0] for e in entries]
    assert key_ids == sorted(key_ids), \
        f"GeoKey entries not sorted by KeyID: {key_ids}"


def assert_geokey_count_consistent(tiff):
    hdr, entries = tiff.get_geokey_raw_entries()
    assert hdr[3] == len(entries), \
        f"NumberOfKeys={hdr[3]} but found {len(entries)} entries in shorts"
    # Also verify total shorts match
    shorts = tiff.get_shorts(34735)
    expected_shorts = 4 + hdr[3] * 4
    assert len(shorts) >= expected_shorts, \
        f"GeoKeyDirectoryTag has {len(shorts)} shorts, need at least {expected_shorts}"


def assert_double_key_types(tiff, expected_double_keys):
    """Verify that DOUBLE-type GeoKeys are stored via tag 34736."""
    _, entries = tiff.get_geokey_raw_entries()
    for key_id, tag_loc, count, val_off in entries:
        if key_id in expected_double_keys:
            assert tag_loc == 34736, \
                f"GeoKey {key_id} should be DOUBLE (tag_loc=34736), got tag_loc={tag_loc}"
            assert count == 1, \
                f"GeoKey {key_id} DOUBLE count should be 1, got {count}"


def assert_ascii_key_types(tiff, expected_ascii_keys):
    """Verify that ASCII-type GeoKeys are stored via tag 34737."""
    _, entries = tiff.get_geokey_raw_entries()
    for key_id, tag_loc, count, val_off in entries:
        if key_id in expected_ascii_keys:
            assert tag_loc == 34737, \
                f"GeoKey {key_id} should be ASCII (tag_loc=34737), got tag_loc={tag_loc}"


def assert_ascii_params_format(tiff):
    """Verify GeoAsciiParamsTag is pipe-delimited and null-terminated."""
    raw = tiff.get_ascii_raw(34737)
    assert raw is not None, "Missing GeoAsciiParamsTag (34737)"
    assert raw[-1:] == b'\x00', \
        f"GeoAsciiParamsTag must end with null byte, got {raw[-1:]!r}"
    text = raw[:-1]  # strip null
    # Every ASCII value must be pipe-terminated
    assert text.endswith(b'|'), \
        f"ASCII values must be pipe-terminated before null, got ...{text[-5:]!r}"
    # No embedded nulls
    assert b'\x00' not in text, "Embedded null in GeoAsciiParamsTag content"
    # No semicolons as delimiters
    assert b';' not in text, \
        f"Semicolons found in GeoAsciiParamsTag — must use pipe '|' delimiters"


def assert_pixel_scale(tiff, expected):
    tag = tiff.tags.get(33550)
    assert tag is not None, "Missing ModelPixelScaleTag (33550)"
    assert tag['count'] == 3, \
        f"ModelPixelScaleTag count={tag['count']}, must be 3"
    vals = tiff.get_doubles(33550)
    for i, (exp, act) in enumerate(zip(expected, vals)):
        assert math.isclose(act, exp, rel_tol=1e-9, abs_tol=1e-9), \
            f"ModelPixelScaleTag[{i}]: got {act}, expected {exp}"


def assert_tiepoint(tiff, expected):
    vals = tiff.get_doubles(33922)
    assert vals is not None, "Missing ModelTiepointTag (33922)"
    assert len(vals) == 6, f"ModelTiepointTag count={len(vals)}, expected 6"
    for i, (exp, act) in enumerate(zip(expected, vals)):
        assert math.isclose(act, exp, rel_tol=1e-9, abs_tol=1e-9), \
            f"ModelTiepointTag[{i}]: got {act}, expected {exp}"


def assert_required_tiff_tags(tiff):
    required = [256, 257, 258, 259, 273, 277, 278, 279]
    for tid in required:
        assert tid in tiff.tags, f"Missing required TIFF tag {tid}"


# ─── Test classes per file ────────────────────────────────────────


class TestGeographic:
    """Verify fixed geographic.tif — Geographic 2D CRS, WGS 84 (EPSG:4326)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tiff = TiffParser('/app/fixed/geographic.tif')

    def test_valid_tiff_header(self):
        assert self.tiff.data[:2] in (b'II', b'MM')
        bo = '<' if self.tiff.data[:2] == b'II' else '>'
        assert struct.unpack(bo + 'H', self.tiff.data[2:4])[0] == 42

    def test_required_tiff_tags(self):
        assert_required_tiff_tags(self.tiff)

    def test_ifd_sorted(self):
        assert_ifd_sorted(self.tiff)

    def test_geokey_header(self):
        assert_geokey_header(self.tiff)

    def test_geokey_count(self):
        hdr, entries = self.tiff.get_geokey_raw_entries()
        assert hdr[3] == 3, f"NumberOfKeys={hdr[3]}, expected 3"

    def test_geokey_sorted(self):
        assert_geokey_sorted(self.tiff)

    def test_geokey_values(self):
        gk = self.tiff.decode_geokeys()
        assert gk[1024] == 2, f"GTModelTypeGeoKey={gk[1024]}, expected 2"
        assert gk[1025] == 1, f"GTRasterTypeGeoKey={gk[1025]}, expected 1"
        assert gk[2048] == 4326, f"GeodeticCRSGeoKey={gk[2048]}, expected 4326"

    def test_raster_type_not_reserved(self):
        gk = self.tiff.decode_geokeys()
        assert gk[1025] in (1, 2), \
            f"GTRasterTypeGeoKey={gk[1025]} is reserved (must be 1 or 2)"

    def test_pixel_scale(self):
        assert_pixel_scale(self.tiff, (1.0, 1.0, 0.0))

    def test_tiepoint(self):
        assert_tiepoint(self.tiff, (0.0, 0.0, 0.0, -180.0, 90.0, 0.0))

    def test_no_double_params(self):
        assert 34736 not in self.tiff.tags, \
            "Unexpected GeoDoubleParamsTag for SHORT-only spec"

    def test_no_ascii_params(self):
        assert 34737 not in self.tiff.tags, \
            "Unexpected GeoAsciiParamsTag for SHORT-only spec"


class TestProjected:
    """Verify fixed projected.tif — Projected CRS, UTM 17N (EPSG:32617)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tiff = TiffParser('/app/fixed/projected.tif')

    def test_valid_tiff_header(self):
        assert self.tiff.data[:2] in (b'II', b'MM')

    def test_required_tiff_tags(self):
        assert_required_tiff_tags(self.tiff)

    def test_ifd_sorted(self):
        assert_ifd_sorted(self.tiff)

    def test_geokey_header(self):
        assert_geokey_header(self.tiff)

    def test_geokey_count(self):
        hdr, _ = self.tiff.get_geokey_raw_entries()
        assert hdr[3] == 3

    def test_geokey_sorted(self):
        assert_geokey_sorted(self.tiff)

    def test_geokey_values(self):
        gk = self.tiff.decode_geokeys()
        assert gk[1024] == 1, f"GTModelTypeGeoKey={gk[1024]}, expected 1"
        assert gk[1025] == 1, f"GTRasterTypeGeoKey={gk[1025]}, expected 1"
        assert gk[3072] == 32617, f"ProjectedCRSGeoKey={gk[3072]}, expected 32617"

    def test_pixel_scale_count(self):
        """ModelPixelScaleTag must have exactly 3 values."""
        tag = self.tiff.tags.get(33550)
        assert tag is not None, "Missing ModelPixelScaleTag (33550)"
        assert tag['count'] == 3, \
            f"ModelPixelScaleTag count={tag['count']}, must be 3 per OGC 19-008r4"

    def test_pixel_scale_values(self):
        assert_pixel_scale(self.tiff, (500.0, 500.0, 0.0))

    def test_tiepoint(self):
        assert_tiepoint(self.tiff, (0.0, 0.0, 0.0, 500000.0, 4649776.22, 0.0))

    def test_minor_revision_is_1(self):
        """GeoTIFF 1.1 requires MinorRevision = 1."""
        hdr, _ = self.tiff.get_geokey_raw_entries()
        assert hdr[2] == 1, \
            f"MinorRevision={hdr[2]}, must be 1 for GeoTIFF 1.1"


class TestUserDefined:
    """Verify fixed userdefined.tif — User-defined TM on WGS 84."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tiff = TiffParser('/app/fixed/userdefined.tif')

    def test_valid_tiff_header(self):
        assert self.tiff.data[:2] in (b'II', b'MM')

    def test_required_tiff_tags(self):
        assert_required_tiff_tags(self.tiff)

    def test_ifd_sorted(self):
        assert_ifd_sorted(self.tiff)

    def test_geokey_header(self):
        assert_geokey_header(self.tiff)

    def test_geokey_count(self):
        hdr, _ = self.tiff.get_geokey_raw_entries()
        assert hdr[3] == 12

    def test_geokey_sorted(self):
        assert_geokey_sorted(self.tiff)

    def test_short_geokey_values(self):
        gk = self.tiff.decode_geokeys()
        assert gk[1024] == 1
        assert gk[1025] == 2
        assert gk[2048] == 4326
        assert gk[3072] == 32767
        assert gk[3075] == 9807
        assert gk[3076] == 9001

    def test_double_key_storage_types(self):
        """DOUBLE-type projection parameter keys must use tag 34736."""
        assert_double_key_types(self.tiff, {3080, 3081, 3082, 3083, 3092})

    def test_proj_scale_is_double(self):
        """ProjScaleAtNatOriginGeoKey must be stored as DOUBLE, not SHORT."""
        _, entries = self.tiff.get_geokey_raw_entries()
        for key_id, tag_loc, count, val_off in entries:
            if key_id == 3092:
                assert tag_loc == 34736, \
                    f"ProjScaleAtNatOriginGeoKey tag_loc={tag_loc}, must be 34736 (DOUBLE)"
                break
        else:
            pytest.fail("ProjScaleAtNatOriginGeoKey (3092) not found in GeoKey entries")

    def test_proj_scale_value(self):
        gk = self.tiff.decode_geokeys()
        assert 3092 in gk, "Missing ProjScaleAtNatOriginGeoKey (3092)"
        assert isinstance(gk[3092], float), \
            f"ProjScaleAtNatOriginGeoKey should be float, got {type(gk[3092])}"
        assert math.isclose(gk[3092], 0.9996, rel_tol=1e-9), \
            f"ProjScaleAtNatOriginGeoKey={gk[3092]}, expected 0.9996"

    def test_proj_nat_origin_long(self):
        gk = self.tiff.decode_geokeys()
        assert 3080 in gk, "Missing ProjNatOriginLongGeoKey (3080)"
        assert math.isclose(gk[3080], -75.0, rel_tol=1e-9), \
            f"ProjNatOriginLongGeoKey={gk[3080]}, expected -75.0"

    def test_proj_nat_origin_lat(self):
        gk = self.tiff.decode_geokeys()
        assert math.isclose(gk[3081], 0.0, abs_tol=1e-12)

    def test_proj_false_easting(self):
        gk = self.tiff.decode_geokeys()
        assert math.isclose(gk[3082], 500000.0, rel_tol=1e-9)

    def test_proj_false_northing(self):
        gk = self.tiff.decode_geokeys()
        assert math.isclose(gk[3083], 0.0, abs_tol=1e-12)

    def test_ascii_citation_key_type(self):
        """ProjectedCitationGeoKey must be stored as ASCII via tag 34737."""
        assert_ascii_key_types(self.tiff, {3073})

    def test_ascii_citation_value(self):
        gk = self.tiff.decode_geokeys()
        assert gk[3073] == "Custom TM Zone", \
            f"ProjectedCitationGeoKey='{gk[3073]}', expected 'Custom TM Zone'"

    def test_ascii_params_format(self):
        assert_ascii_params_format(self.tiff)

    def test_double_params_present(self):
        assert 34736 in self.tiff.tags, "Missing GeoDoubleParamsTag (34736)"
        doubles = self.tiff.get_doubles(34736)
        assert len(doubles) >= 5, f"Expected >= 5 double params, got {len(doubles)}"

    def test_pixel_scale(self):
        assert_pixel_scale(self.tiff, (500.0, 500.0, 0.0))

    def test_tiepoint(self):
        assert_tiepoint(self.tiff, (0.0, 0.0, 0.0, 500000.0, 4649776.22, 0.0))


class TestCompound:
    """Verify fixed compound.tif — UTM 17N + EGM96 vertical compound CRS."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tiff = TiffParser('/app/fixed/compound.tif')

    def test_valid_tiff_header(self):
        assert self.tiff.data[:2] in (b'II', b'MM')

    def test_required_tiff_tags(self):
        assert_required_tiff_tags(self.tiff)

    def test_ifd_sorted(self):
        assert_ifd_sorted(self.tiff)

    def test_geokey_header(self):
        assert_geokey_header(self.tiff)

    def test_geokey_count(self):
        """NumberOfKeys must be 7 (all keys visible)."""
        hdr, entries = self.tiff.get_geokey_raw_entries()
        assert hdr[3] == 7, f"NumberOfKeys={hdr[3]}, expected 7"
        assert len(entries) == 7, \
            f"Actual entry count={len(entries)}, expected 7"

    def test_geokey_sorted(self):
        assert_geokey_sorted(self.tiff)

    def test_horizontal_crs_values(self):
        gk = self.tiff.decode_geokeys()
        assert gk[1024] == 1
        assert gk[1025] == 1
        assert gk[3072] == 32617

    def test_vertical_keys_present(self):
        gk = self.tiff.decode_geokeys()
        assert 4096 in gk, "Missing VerticalGeoKey (4096)"
        assert gk[4096] == 5773, f"VerticalGeoKey={gk[4096]}, expected 5773"
        assert 4098 in gk, "Missing VerticalDatumGeoKey (4098)"
        assert gk[4098] == 5171, f"VerticalDatumGeoKey={gk[4098]}, expected 5171"
        assert 4099 in gk, "Missing VerticalUnitsGeoKey (4099)"
        assert gk[4099] == 9001, f"VerticalUnitsGeoKey={gk[4099]}, expected 9001"

    def test_vertical_citation_is_ascii(self):
        """VerticalCitationGeoKey must be stored as ASCII via tag 34737."""
        assert_ascii_key_types(self.tiff, {4097})

    def test_vertical_citation_value(self):
        gk = self.tiff.decode_geokeys()
        assert 4097 in gk, "Missing VerticalCitationGeoKey (4097)"
        assert gk[4097] == "EGM96 geoid height", \
            f"VerticalCitationGeoKey='{gk.get(4097)}', expected 'EGM96 geoid height'"

    def test_ascii_params_format(self):
        assert_ascii_params_format(self.tiff)

    def test_pixel_scale(self):
        assert_pixel_scale(self.tiff, (1000.0, 1000.0, 1.0))

    def test_tiepoint(self):
        assert_tiepoint(self.tiff, (0.0, 0.0, 0.0, 500000.0, 4649776.22, 100.0))

    def test_3d_tiepoint_z(self):
        tp = self.tiff.get_doubles(33922)
        assert math.isclose(tp[5], 100.0, rel_tol=1e-9), \
            f"ModelTiepointTag Z={tp[5]}, expected 100.0"

    def test_3d_pixel_scale_z(self):
        ps = self.tiff.get_doubles(33550)
        assert math.isclose(ps[2], 1.0, rel_tol=1e-9), \
            f"ModelPixelScaleTag Z={ps[2]}, expected 1.0"


class TestGlobalConstraints:
    """Cross-cutting validation across all fixed files."""

    FILES = ['geographic.tif', 'projected.tif', 'userdefined.tif', 'compound.tif']

    def test_all_files_exist(self):
        for name in self.FILES:
            path = f'/app/fixed/{name}'
            assert os.path.isfile(path), f"Missing fixed file: {path}"

    def test_all_files_valid_tiff(self):
        for name in self.FILES:
            path = f'/app/fixed/{name}'
            with open(path, 'rb') as f:
                header = f.read(8)
            assert len(header) == 8, f"{name}: too small for TIFF header"
            assert header[:2] in (b'II', b'MM'), \
                f"{name}: invalid byte order {header[:2]!r}"
            bo = '<' if header[:2] == b'II' else '>'
            magic = struct.unpack(bo + 'H', header[2:4])[0]
            assert magic == 42, f"{name}: TIFF magic={magic}, expected 42"

    def test_all_ifd_sorted(self):
        for name in self.FILES:
            tiff = TiffParser(f'/app/fixed/{name}')
            assert tiff.tag_order == sorted(tiff.tag_order), \
                f"{name}: IFD not sorted: {tiff.tag_order}"

    def test_all_geokey_headers(self):
        for name in self.FILES:
            tiff = TiffParser(f'/app/fixed/{name}')
            hdr, _ = tiff.get_geokey_raw_entries()
            assert hdr[0] == 1 and hdr[1] == 1 and hdr[2] == 1, \
                f"{name}: GeoKey header {hdr}, expected (1, 1, 1, ...)"

    def test_all_geokeys_sorted(self):
        for name in self.FILES:
            tiff = TiffParser(f'/app/fixed/{name}')
            _, entries = tiff.get_geokey_raw_entries()
            ids = [e[0] for e in entries]
            assert ids == sorted(ids), \
                f"{name}: GeoKey entries not sorted: {ids}"

    def test_all_pixel_scale_count(self):
        """Every file must have ModelPixelScaleTag with count=3."""
        for name in self.FILES:
            tiff = TiffParser(f'/app/fixed/{name}')
            tag = tiff.tags.get(33550)
            assert tag is not None, f"{name}: missing ModelPixelScaleTag"
            assert tag['count'] == 3, \
                f"{name}: ModelPixelScaleTag count={tag['count']}, must be 3"
