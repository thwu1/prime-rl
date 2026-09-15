
"""Tests for the BigTIFF LZW + floating-point predictor writer."""

import ast
import hashlib
import json
import os
import struct

import numpy as np
import pytest

INPUT_PATH = '/app/dataset.npy'
OUTPUT_PATH = '/app/output.tif'
BUILDER_PATH = '/app/lzw_tiff_writer.py'
REPORT_PATH = '/app/report.json'

# DNA digests — SHA-256 hashes of the correct report values, so the raw
# answers cannot be extracted by reading this source file.
_DNA_PREDICTOR_HASH = '988971bffc6ba6b5e7705ce377c9a6231140af84cb7f2d265a49ddebc1669c18'
_DNA_COMPRESSED_HASH = '15c787600c7b35baa87f203ec9d3ede82665d24de068728fb9567969a9c3722a'
_DNA_COMBINED_HASH = '8fb024f06e7228bcbe7e1dc36b0d3ef9a33355f0096a1a890833995d934545c2'


@pytest.fixture(scope='module')
def original_data():
    return np.load(INPUT_PATH)


@pytest.fixture(scope='module')
def tif():
    import tifffile
    with tifffile.TiffFile(OUTPUT_PATH) as t:
        yield t


@pytest.fixture(scope='module')
def report():
    with open(REPORT_PATH) as f:
        return json.load(f)


# ── Basic validity ──────────────────────────────────────────────────────────


def test_output_exists():
    """Output TIFF file must exist."""
    assert os.path.isfile(OUTPUT_PATH), f'{OUTPUT_PATH} not found'


def test_report_exists():
    """Report JSON file must exist."""
    assert os.path.isfile(REPORT_PATH), f'{REPORT_PATH} not found'


def test_bigtiff_header():
    """File must have a valid BigTIFF header."""
    with open(OUTPUT_PATH, 'rb') as f:
        header = f.read(16)
    assert len(header) == 16, 'File too short for BigTIFF header'
    byte_order = header[:2]
    assert byte_order == b'II', f'Expected little-endian (II), got {byte_order!r}'
    magic = struct.unpack('<H', header[2:4])[0]
    assert magic == 43, f'Expected BigTIFF magic 43, got {magic}'
    offset_size = struct.unpack('<H', header[4:6])[0]
    assert offset_size == 8, f'Expected offset size 8, got {offset_size}'


def test_no_disallowed_imports():
    """Builder script must not import disallowed TIFF/image/LZW libraries."""
    disallowed = {
        'tifffile', 'PIL', 'Pillow', 'imagecodecs', 'libtiff',
        'cv2', 'skimage', 'oiffile', 'czifile', 'lzw',
    }
    with open(BUILDER_PATH) as f:
        source = f.read()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split('.')[0])
    violations = imported & disallowed
    assert not violations, f'Disallowed imports found: {violations}'


# ── Structural checks ──────────────────────────────────────────────────────


def test_page_count(tif, original_data):
    """File must contain the correct number of main IFD pages (T*Z)."""
    T, Z, Y, X = original_data.shape
    expected = T * Z
    assert len(tif.pages) == expected, (
        f'Expected {expected} pages, got {len(tif.pages)}'
    )


def test_compression_tag(tif):
    """Every page must use LZW compression (tag 259 = 5)."""
    for i, page in enumerate(tif.pages):
        val = page.tags['Compression'].value
        assert val == 5, f'Page {i}: expected Compression=5 (LZW), got {val}'


def test_predictor_tag(tif):
    """Every page must use floating-point predictor (tag 317 = 3)."""
    for i, page in enumerate(tif.pages):
        val = page.tags['Predictor'].value
        assert val == 3, f'Page {i}: expected Predictor=3 (FloatingPoint), got {val}'


def test_sample_format_tag(tif):
    """Every page must declare IEEEFP sample format (tag 339 = 3)."""
    for i, page in enumerate(tif.pages):
        val = page.tags['SampleFormat'].value
        v = val[0] if isinstance(val, tuple) else val
        assert v == 3, f'Page {i}: expected SampleFormat=3 (IEEEFP), got {val}'


def test_bits_per_sample(tif):
    """Every page must have BitsPerSample = 32."""
    for i, page in enumerate(tif.pages):
        val = page.tags['BitsPerSample'].value
        v = val[0] if isinstance(val, tuple) else val
        assert v == 32, f'Page {i}: expected BitsPerSample=32, got {val}'


def test_samples_per_pixel(tif):
    """Every page must have SamplesPerPixel = 1."""
    for i, page in enumerate(tif.pages):
        val = page.tags['SamplesPerPixel'].value
        assert val == 1, f'Page {i}: expected SamplesPerPixel=1, got {val}'


def test_tile_dimensions(tif):
    """Pages must use 64x64 tiled storage."""
    page = tif.pages[0]
    assert page.is_tiled, 'Expected tiled storage'
    tw = page.tags['TileWidth'].value
    tl = page.tags['TileLength'].value
    assert tw == 64, f'Expected TileWidth=64, got {tw}'
    assert tl == 64, f'Expected TileLength=64, got {tl}'


def test_image_dimensions(tif, original_data):
    """Page dimensions must match input spatial size."""
    T, Z, Y, X = original_data.shape
    page = tif.pages[0]
    assert page.imagewidth == X, f'Expected width={X}, got {page.imagewidth}'
    assert page.imagelength == Y, f'Expected length={Y}, got {page.imagelength}'


# ── Pixel data integrity ───────────────────────────────────────────────────


def test_data_integrity(tif, original_data):
    """Decoded pixel data for each page must match the original input array."""
    T, Z, Y, X = original_data.shape
    for t in range(T):
        for z in range(Z):
            page_idx = t * Z + z
            page_data = tif.pages[page_idx].asarray()
            expected = original_data[t, z]
            np.testing.assert_array_equal(
                page_data, expected,
                err_msg=f'Page {page_idx} (T={t}, Z={z}) pixel data mismatch',
            )


def test_dtype_float32(tif):
    """Decoded data must be float32."""
    page_data = tif.pages[0].asarray()
    assert page_data.dtype == np.float32, (
        f'Expected float32, got {page_data.dtype}'
    )


def test_data_range(tif, original_data):
    """Sanity check: decoded data range must match input data range."""
    page_data = tif.pages[0].asarray()
    orig_page = original_data[0, 0]
    assert abs(page_data.min() - orig_page.min()) < 1e-3, 'Min value mismatch'
    assert abs(page_data.max() - orig_page.max()) < 1e-3, 'Max value mismatch'


# ── DNA: Metrics report verification ────────────────────────────────────────
# Expected values are stored as SHA-256 hashes so they cannot be extracted
# by reading this source file.  The agent must compute correct values through
# a genuine from-scratch implementation of the predictor and LZW encoder.


def test_dna_predictor_output_hash(report):
    """The SHA-256 of all concatenated predictor output must be correct.

    Verifies floating-point predictor byte-plane reorder + horizontal
    differencing is implemented correctly across every tile and page.
    The expected digest is stored as a hash-of-hash to prevent extraction."""
    actual = report.get('predicted_data_sha256', '')
    actual_hashed = hashlib.sha256(actual.encode()).hexdigest()
    assert actual_hashed == _DNA_PREDICTOR_HASH, (
        f'predicted_data_sha256 digest mismatch (hashed check failed)'
    )


def test_dna_per_page_compressed_bytes(report):
    """Per-page compressed byte counts must be correct.

    Verifies the TIFF-variant LZW encoder produces exact output for each
    page.  Expected values stored as hash to prevent extraction."""
    actual = report.get('per_page_compressed_bytes', [])
    assert isinstance(actual, list) and len(actual) == 6, (
        f'per_page_compressed_bytes must be a list of 6 integers, got {type(actual).__name__} len={len(actual) if isinstance(actual, list) else "N/A"}'
    )
    actual_str = json.dumps(actual, separators=(',', ':'))
    actual_hashed = hashlib.sha256(actual_str.encode()).hexdigest()
    assert actual_hashed == _DNA_COMPRESSED_HASH, (
        f'per_page_compressed_bytes digest mismatch (hashed check failed)'
    )


def test_dna_total_compressed_bytes(report):
    """Total compressed bytes must equal the sum of per-page values and
    be consistent with the combined report digest."""
    per_page = report.get('per_page_compressed_bytes', [])
    total = report.get('total_compressed_bytes', 0)
    assert isinstance(per_page, list) and len(per_page) == 6
    assert sum(per_page) == total, (
        f'Sum of per_page ({sum(per_page)}) != total ({total})'
    )


def test_dna_combined_report_integrity(report):
    """All three report fields must be jointly correct — combined hash
    prevents any single field from being independently guessed."""
    sha_val = report.get('predicted_data_sha256', '')
    per_page = report.get('per_page_compressed_bytes', [])
    total = report.get('total_compressed_bytes', 0)
    combined = (
        sha_val + '|'
        + json.dumps(per_page, separators=(',', ':')) + '|'
        + str(total)
    )
    combined_hashed = hashlib.sha256(combined.encode()).hexdigest()
    assert combined_hashed == _DNA_COMBINED_HASH, (
        f'Combined report digest mismatch — all three fields must be jointly correct'
    )
