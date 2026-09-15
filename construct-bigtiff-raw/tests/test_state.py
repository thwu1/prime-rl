
"""Tests for BigTIFF forensic repair task.

Verifies the repaired file is a valid BigTIFF with 3 correct pages,
pixel-accurate data, and preserved ImageDescription metadata.
"""

import struct
import os

import numpy as np
import pytest
import tifffile

REPAIRED = '/app/repaired.tif'
CORRUPTED = '/app/corrupted.tif'


class TestFileIntegrity:
    """Repaired file must exist and be a valid BigTIFF."""

    def test_repaired_file_exists(self):
        assert os.path.isfile(REPAIRED), f"{REPAIRED} does not exist"

    def test_repaired_file_not_empty(self):
        assert os.path.getsize(REPAIRED) > 0, "Repaired file is empty"

    def test_bigtiff_header_byte_order(self):
        with open(REPAIRED, 'rb') as f:
            bom = f.read(2)
        assert bom == b'II', f"Byte order must be little-endian 'II', got {bom!r}"

    def test_bigtiff_header_version(self):
        with open(REPAIRED, 'rb') as f:
            f.seek(2)
            version = struct.unpack('<H', f.read(2))[0]
        assert version == 43, f"BigTIFF version must be 43, got {version}"

    def test_bigtiff_header_offset_size(self):
        with open(REPAIRED, 'rb') as f:
            f.seek(4)
            offset_size = struct.unpack('<H', f.read(2))[0]
        assert offset_size == 8, f"Offset size must be 8, got {offset_size}"

    def test_is_bigtiff(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            assert tif.is_bigtiff, "File must be recognized as BigTIFF"

    def test_page_count(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            assert len(tif.pages) == 3, \
                f"Expected 3 pages, got {len(tif.pages)}"


class TestPage0Structure:
    """Page 0: 512x512 uint16 grayscale."""

    def test_shape(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            assert tif.pages[0].shape == (512, 512), \
                f"Expected (512, 512), got {tif.pages[0].shape}"

    def test_dtype(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            assert tif.pages[0].dtype == np.uint16, \
                f"Expected uint16, got {tif.pages[0].dtype}"

    def test_samples_per_pixel(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            assert tif.pages[0].samplesperpixel == 1


class TestPage0Data:
    """Verify Page 0 pixel data matches expected gradient."""

    def test_pixel_data_exact(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            data = tif.pages[0].asarray()
        y, x = np.mgrid[0:512, 0:512]
        expected = (
            (y.astype(np.int64) * 512 + x.astype(np.int64)) % 65536
        ).astype(np.uint16)
        np.testing.assert_array_equal(data, expected,
            err_msg="Page 0 pixel data mismatch")

    def test_spot_checks(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            data = tif.pages[0].asarray()
        assert data[0, 0] == 0
        assert data[0, 256] == 256
        assert data[256, 0] == (256 * 512) % 65536
        assert data[511, 511] == (511 * 512 + 511) % 65536

    def test_quadrant_top_right(self):
        """Specifically verify top-right quadrant (corruption-sensitive)."""
        with tifffile.TiffFile(REPAIRED) as tif:
            data = tif.pages[0].asarray()
        quadrant = data[0:256, 256:512]
        y, x = np.mgrid[0:256, 256:512]
        expected = ((y.astype(np.int64) * 512 + x.astype(np.int64)) % 65536).astype(np.uint16)
        np.testing.assert_array_equal(quadrant, expected,
            err_msg="Top-right quadrant mismatch in page 0")

    def test_quadrant_bottom_left(self):
        """Specifically verify bottom-left quadrant (corruption-sensitive)."""
        with tifffile.TiffFile(REPAIRED) as tif:
            data = tif.pages[0].asarray()
        quadrant = data[256:512, 0:256]
        y, x = np.mgrid[256:512, 0:256]
        expected = ((y.astype(np.int64) * 512 + x.astype(np.int64)) % 65536).astype(np.uint16)
        np.testing.assert_array_equal(quadrant, expected,
            err_msg="Bottom-left quadrant mismatch in page 0")


class TestPage1Structure:
    """Page 1: 256x256 uint8 RGB."""

    def test_shape(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            assert tif.pages[1].shape == (256, 256, 3), \
                f"Expected (256, 256, 3), got {tif.pages[1].shape}"

    def test_dtype(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            assert tif.pages[1].dtype == np.uint8

    def test_samples_per_pixel(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            assert tif.pages[1].samplesperpixel == 3


class TestPage1Data:
    """Verify Page 1 pixel data matches expected RGB pattern."""

    def test_pixel_data_exact(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            data = tif.pages[1].asarray()
        y, x = np.mgrid[0:256, 0:256]
        expected = np.stack([
            (y % 256).astype(np.uint8),
            (x % 256).astype(np.uint8),
            ((y + x) % 256).astype(np.uint8),
        ], axis=-1)
        np.testing.assert_array_equal(data, expected,
            err_msg="Page 1 pixel data mismatch")

    def test_spot_checks(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            data = tif.pages[1].asarray()
        np.testing.assert_array_equal(data[0, 0], [0, 0, 0])
        np.testing.assert_array_equal(data[0, 255], [0, 255, 255])
        np.testing.assert_array_equal(data[255, 0], [255, 0, 255])
        np.testing.assert_array_equal(data[255, 255], [255, 255, 254])
        np.testing.assert_array_equal(data[128, 64], [128, 64, 192])


class TestPage2Structure:
    """Page 2: 384x384 uint16 grayscale."""

    def test_shape(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            assert tif.pages[2].shape == (384, 384), \
                f"Expected (384, 384), got {tif.pages[2].shape}"

    def test_dtype(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            assert tif.pages[2].dtype == np.uint16

    def test_samples_per_pixel(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            assert tif.pages[2].samplesperpixel == 1


class TestPage2Data:
    """Verify Page 2 pixel data matches expected pattern."""

    def test_pixel_data_exact(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            data = tif.pages[2].asarray()
        y, x = np.mgrid[0:384, 0:384]
        expected = (
            (y.astype(np.int64) * 3 + x.astype(np.int64) * 7 + 42) % 65536
        ).astype(np.uint16)
        np.testing.assert_array_equal(data, expected,
            err_msg="Page 2 pixel data mismatch")

    def test_spot_checks(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            data = tif.pages[2].asarray()
        assert data[0, 0] == 42
        assert data[0, 1] == 49
        assert data[1, 0] == 45
        assert data[383, 383] == (383 * 3 + 383 * 7 + 42) % 65536


class TestMetadataPreservation:
    """ImageDescription tags must be preserved from the corrupted file."""

    def test_page0_description(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            desc = tif.pages[0].description
        assert desc == 'CAL:7A3F-512G:T=2024-03-15T08:42:11Z', \
            f"Page 0 description mismatch: {desc!r}"

    def test_page1_description(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            desc = tif.pages[1].description
        assert desc == 'REF:B92C-256RGB:T=2024-03-15T09:15:33Z', \
            f"Page 1 description mismatch: {desc!r}"

    def test_page2_description(self):
        with tifffile.TiffFile(REPAIRED) as tif:
            desc = tif.pages[2].description
        assert desc == 'BKG:E51D-384G:T=2024-03-15T10:03:47Z', \
            f"Page 2 description mismatch: {desc!r}"


class TestCorruptedFileUnchanged:
    """Corrupted input file must not be modified."""

    def test_corrupted_still_exists(self):
        assert os.path.isfile(CORRUPTED), "Corrupted file must not be removed"

    def test_corrupted_still_shows_issues(self):
        """Verify the corrupted file still has problems (solver didn't
        just fix it in-place and copy)."""
        with tifffile.TiffFile(CORRUPTED) as tif:
            # Should only show 2 pages (IFD chain broken)
            assert len(tif.pages) == 2, \
                "Corrupted file should still show only 2 pages"
