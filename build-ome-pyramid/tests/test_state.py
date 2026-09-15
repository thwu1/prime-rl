"""Tests for microscopy binary forensics and OME-TIFF assembly.

"""

import json
import os

import numpy as np
import pytest
import tifffile

OUTPUT = '/app/output.ome.tif'
ANALYSIS = '/app/analysis.json'
ACQ_DIR = '/app/acquisition'

T, Z, Y, X = 2, 4, 384, 512
N_CHANNELS = 4
CHANNEL_NAMES = ['DAPI', 'GFP', 'mCherry', 'TdTomato']


def _find_header_end(filepath):
    """Locate pixel data offset past END_HEADER marker, 64-byte aligned."""
    with open(filepath, 'rb') as f:
        content = f.read()
    marker = b'END_HEADER\n'
    pos = content.find(marker)
    if pos == -1:
        return 0
    end = pos + len(marker)
    return ((end + 63) // 64) * 64


def _unpack_12bit(data_bytes, n_values):
    """Unpack MSB-first 12-bit packed pairs from 3-byte groups."""
    packed = np.frombuffer(data_bytes, dtype=np.uint8)
    b0 = packed[0::3].astype(np.uint16)
    b1 = packed[1::3].astype(np.uint16)
    b2 = packed[2::3].astype(np.uint16)
    a = (b0 << 4) | (b1 >> 4)
    b = ((b1 & 0x0F) << 8) | b2
    result = np.empty(n_values, dtype=np.uint16)
    result[0::2] = a[:n_values // 2]
    result[1::2] = b[:n_values // 2]
    return result


def _apply_correction(data, dy, dx, fill_value=0):
    """Integer-pixel translation with zero-fill."""
    h, w = data.shape[-2], data.shape[-1]
    out = np.full_like(data, fill_value)
    dy_s, dy_e = max(0, dy), min(h, h + dy)
    dx_s, dx_e = max(0, dx), min(w, w + dx)
    if dy_e > dy_s and dx_e > dx_s:
        out[..., dy_s:dy_e, dx_s:dx_e] = \
            data[..., dy_s - dy:dy_e - dy, dx_s - dx:dx_e - dx]
    return out


# ── File existence ────────────────────────────────────────────────

class TestOutputExists:
    def test_tiff_exists(self):
        assert os.path.isfile(OUTPUT), 'output.ome.tif not found'

    def test_analysis_exists(self):
        assert os.path.isfile(ANALYSIS), 'analysis.json not found'


# ── File format ───────────────────────────────────────────────────

class TestFileFormat:
    def test_is_bigtiff(self):
        with tifffile.TiffFile(OUTPUT) as tif:
            assert tif.is_bigtiff, 'Output must be BigTIFF'

    def test_is_ome(self):
        with tifffile.TiffFile(OUTPUT) as tif:
            assert tif.is_ome, 'Output must be OME-TIFF'

    def test_compression_deflate(self):
        with tifffile.TiffFile(OUTPUT) as tif:
            name = tif.pages[0].compression.name.upper()
            assert 'DEFLATE' in name or 'ZLIB' in name, \
                f'Expected deflate, got {name}'

    def test_tiles_256(self):
        with tifffile.TiffFile(OUTPUT) as tif:
            p = tif.pages[0]
            assert p.is_tiled, 'Pages must be tiled'
            assert p.tilewidth == 256, f'Tile width {p.tilewidth} != 256'
            assert p.tilelength == 256, f'Tile height {p.tilelength} != 256'


# ── Pyramid structure ─────────────────────────────────────────────

class TestPyramidStructure:
    def test_base_shape(self):
        with tifffile.TiffFile(OUTPUT) as tif:
            s = tif.series[0]
            expected = (T, N_CHANNELS, Z, Y, X)
            assert s.shape == expected, \
                f'Base shape {s.shape} != {expected}'

    def test_base_axes(self):
        with tifffile.TiffFile(OUTPUT) as tif:
            assert tif.series[0].axes == 'TCZYX'

    def test_three_pyramid_levels(self):
        with tifffile.TiffFile(OUTPUT) as tif:
            assert len(tif.series[0].levels) == 3, \
                f'Expected 3 levels, got {len(tif.series[0].levels)}'

    def test_level1_spatial_dims(self):
        with tifffile.TiffFile(OUTPUT) as tif:
            shape = tif.series[0].levels[1].shape
            assert shape[-2:] == (Y // 2, X // 2), \
                f'Level 1 spatial {shape[-2:]} != {(Y // 2, X // 2)}'

    def test_level2_spatial_dims(self):
        with tifffile.TiffFile(OUTPUT) as tif:
            shape = tif.series[0].levels[2].shape
            assert shape[-2:] == (Y // 4, X // 4), \
                f'Level 2 spatial {shape[-2:]} != {(Y // 4, X // 4)}'


# ── OME-XML metadata ─────────────────────────────────────────────

class TestOMEMetadata:
    def test_channel_names_in_xml(self):
        with tifffile.TiffFile(OUTPUT) as tif:
            desc = tif.pages[0].description
            for name in CHANNEL_NAMES:
                assert name in desc, f'{name} not in OME-XML'

    def test_physical_sizes_in_xml(self):
        with tifffile.TiffFile(OUTPUT) as tif:
            desc = tif.pages[0].description
            assert 'PhysicalSizeX' in desc
            assert 'PhysicalSizeY' in desc
            assert '0.325' in desc, 'Pixel size 0.325 not in OME-XML'


# ── Per-channel data integrity ────────────────────────────────────

class TestDataIntegrity:
    def test_dapi_big_endian_uint16(self):
        """Ch0: big-endian uint16 read correctly."""
        expected = np.fromfile(
            f'{ACQ_DIR}/dapi.bin', dtype='>u2'
        ).reshape(T, Z, Y, X).astype(np.uint16)
        with tifffile.TiffFile(OUTPUT) as tif:
            actual = tif.series[0].asarray()[:, 0]
        np.testing.assert_array_equal(actual, expected)

    def test_gfp_header_skip_and_rescale(self):
        """Ch1: float32 behind ASCII header, rescaled to uint16."""
        offset = _find_header_end(f'{ACQ_DIR}/gfp.bin')
        assert offset > 0, 'GFP header not detected'
        with open(f'{ACQ_DIR}/gfp.bin', 'rb') as f:
            f.seek(offset)
            raw = np.frombuffer(f.read(), dtype='<f4').reshape(T, Z, Y, X)
        expected = np.clip(
            raw.astype(np.float64) * 65535.0, 0, 65535
        ).round().astype(np.uint16)
        with tifffile.TiffFile(OUTPUT) as tif:
            actual = tif.series[0].asarray()[:, 1]
        np.testing.assert_allclose(
            actual.astype(np.float64), expected.astype(np.float64), atol=1.0,
        )

    def test_mcherry_transpose_and_drift(self):
        """Ch2: TZXY -> TZYX transpose + spatial drift correction."""
        raw = np.fromfile(
            f'{ACQ_DIR}/mcherry.bin', dtype='<u2'
        ).reshape(T, Z, X, Y)  # stored as TZXY
        data = raw.transpose(0, 1, 3, 2)  # -> TZYX
        expected = _apply_correction(data, dy=3, dx=-5, fill_value=0)
        with tifffile.TiffFile(OUTPUT) as tif:
            actual = tif.series[0].asarray()[:, 2]
        np.testing.assert_array_equal(actual, expected)

    def test_tdtomato_12bit_unpack_and_shift(self):
        """Ch3: 12-bit packed -> unpack -> left-shift 4 to uint16."""
        with open(f'{ACQ_DIR}/tdtomato.bin', 'rb') as f:
            packed = f.read()
        n_values = T * Z * Y * X
        unpacked = _unpack_12bit(packed, n_values).reshape(T, Z, Y, X)
        expected = (unpacked.astype(np.uint16) << 4)
        with tifffile.TiffFile(OUTPUT) as tif:
            actual = tif.series[0].asarray()[:, 3]
        np.testing.assert_array_equal(actual, expected)


# ── Pyramid consistency ───────────────────────────────────────────

class TestPyramidConsistency:
    def test_mean_intensity_preserved(self):
        """Area averaging preserves global mean within rounding."""
        with tifffile.TiffFile(OUTPUT) as tif:
            s = tif.series[0]
            base_mean = s.levels[0].asarray().astype(np.float64).mean()
            for i in range(1, len(s.levels)):
                lvl_mean = s.levels[i].asarray().astype(np.float64).mean()
                rel_err = abs(base_mean - lvl_mean) / max(base_mean, 1.0)
                assert rel_err < 0.02, \
                    f'Level {i} mean {lvl_mean:.1f} vs base {base_mean:.1f}'


# ── Thumbnail ─────────────────────────────────────────────────────

class TestThumbnail:
    def test_thumbnail_series_present(self):
        with tifffile.TiffFile(OUTPUT) as tif:
            assert len(tif.series) >= 2, 'Thumbnail series missing'


# ── analysis.json ─────────────────────────────────────────────────

class TestAnalysisJSON:
    @pytest.fixture
    def analysis(self):
        with open(ANALYSIS) as f:
            return json.load(f)

    def test_dimensions(self, analysis):
        assert analysis['dimensions'] == {
            'T': T, 'C': N_CHANNELS, 'Z': Z, 'Y': Y, 'X': X,
        }

    def test_channel_count(self, analysis):
        assert len(analysis['channels']) == N_CHANNELS

    def test_channel_names(self, analysis):
        names = {c['name'] for c in analysis['channels']}
        assert names == set(CHANNEL_NAMES)

    def test_channel_stats_range(self, analysis):
        for ch in analysis['channels']:
            assert 0 <= ch['min'] <= 65535
            assert 0 <= ch['max'] <= 65535
            assert ch['min'] <= ch['mean'] <= ch['max']
            assert ch['std'] >= 0

    def test_pyramid_levels(self, analysis):
        levels = analysis['pyramid_levels']
        assert len(levels) == 3
        expected = [
            {'level': 0, 'shape': [T, N_CHANNELS, Z, Y, X],
             'downsample_factor': 1},
            {'level': 1, 'shape': [T, N_CHANNELS, Z, Y // 2, X // 2],
             'downsample_factor': 2},
            {'level': 2, 'shape': [T, N_CHANNELS, Z, Y // 4, X // 4],
             'downsample_factor': 4},
        ]
        for i, lvl in enumerate(levels):
            assert lvl['level'] == expected[i]['level']
            assert lvl['shape'] == expected[i]['shape'], \
                f"Level {i} shape {lvl['shape']} != {expected[i]['shape']}"
            assert lvl['downsample_factor'] == expected[i]['downsample_factor']

    def test_format_info(self, analysis):
        fmt = analysis['format']
        assert fmt['type'] == 'BigTIFF'
        assert fmt['compression'] == 'deflate'
        assert fmt['tile_size'] == [256, 256]
