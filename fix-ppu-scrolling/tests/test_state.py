"""
Tests for NES PPU rendering pipeline, scroll register state machine,
and cross-renderer validation (Python + C).
Verifies pixel-accurate rendering output, correct register behavior,
and cross-language output consistency.
"""


import json
import hashlib
import zlib
import os
import sys

import pytest

sys.path.insert(0, '/app')

FRAME_PATH = '/app/output/frame.bin'
C_FRAME_PATH = '/app/output/frame_0.bin'
REF_PATH = '/app/reference.json'


@pytest.fixture(scope="session")
def reference():
    assert os.path.isfile(REF_PATH), f"Reference file {REF_PATH} not found"
    with open(REF_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def framebuffer():
    assert os.path.isfile(FRAME_PATH), f"Output file {FRAME_PATH} not found"
    with open(FRAME_PATH, 'rb') as f:
        return f.read()


# ---- Rendering output tests ----

class TestFrameStructure:
    """Verify basic output file properties."""

    def test_output_exists(self):
        assert os.path.isfile(FRAME_PATH), \
            f"Expected output at {FRAME_PATH}"

    def test_frame_size(self, framebuffer, reference):
        expected = reference['frame_size']
        assert len(framebuffer) == expected, \
            f"Frame size: got {len(framebuffer)}, expected {expected}"

    def test_all_pixels_valid_palette_index(self, framebuffer):
        """Every pixel must be a valid NES palette index (0x00-0x3F)."""
        for i, b in enumerate(framebuffer):
            if b > 0x3F:
                x, y = i % 256, i // 256
                pytest.fail(
                    f"Invalid palette index {b:#04x} at pixel ({x},{y})")

    def test_nontrivial_output(self, framebuffer):
        """Rendering should produce substantial non-backdrop content."""
        backdrop = 0x0F
        non_backdrop = sum(1 for b in framebuffer if b != backdrop)
        total = len(framebuffer)
        ratio = non_backdrop / total
        assert ratio > 0.3, \
            f"Only {ratio:.1%} non-backdrop pixels; rendering likely broken"


class TestFrameChecksum:
    """Verify overall frame correctness via SHA-256."""

    def test_sha256(self, framebuffer, reference):
        actual = hashlib.sha256(framebuffer).hexdigest()
        expected = reference['frame_sha256']
        assert actual == expected, \
            "Frame SHA-256 mismatch — rendered output differs from reference"


class TestScanlineCRC:
    """Verify individual scanlines via CRC-32 to pinpoint divergence."""

    @pytest.mark.parametrize("scanline", [
        0, 1, 39, 40, 78, 79,
        80, 81, 119, 120, 158, 159,
        160, 161, 183, 196, 206, 207,
        208, 209, 215, 216, 223, 224,
        230, 238, 239,
    ])
    def test_scanline(self, framebuffer, reference, scanline):
        row = framebuffer[scanline * 256:(scanline + 1) * 256]
        actual = zlib.crc32(row) & 0xFFFFFFFF
        expected = reference['scanline_crc32'][str(scanline)]
        assert actual == expected, \
            f"Scanline {scanline}: CRC-32 {actual:#010x} != {expected:#010x}"


class TestSpotPixels:
    """Verify specific pixel values at key coordinates."""

    def test_pixel_values(self, framebuffer, reference):
        failures = []
        for check in reference['spot_checks']:
            x, y, expected = check['x'], check['y'], check['value']
            actual = framebuffer[y * 256 + x]
            if actual != expected:
                failures.append(
                    f"  ({x},{y}): got {actual:#04x}, expected {expected:#04x}")
        if failures:
            msg = f"{len(failures)} pixel(s) wrong:\n" + "\n".join(failures)
            pytest.fail(msg)


class TestRegionTransitions:
    """Verify that scroll region boundaries render correctly."""

    def test_region1_to_region2(self, framebuffer, reference):
        """Scanlines 79-80 cross the first scroll region boundary."""
        for sl in [79, 80]:
            row = framebuffer[sl * 256:(sl + 1) * 256]
            actual = zlib.crc32(row) & 0xFFFFFFFF
            expected = reference['scanline_crc32'][str(sl)]
            assert actual == expected, \
                f"Region boundary scanline {sl} CRC mismatch"

    def test_region3_to_region4(self, framebuffer, reference):
        """Scanlines 207-208 cross the third scroll region boundary."""
        for sl in [207, 208]:
            row = framebuffer[sl * 256:(sl + 1) * 256]
            actual = zlib.crc32(row) & 0xFFFFFFFF
            expected = reference['scanline_crc32'][str(sl)]
            assert actual == expected, \
                f"Region boundary scanline {sl} CRC mismatch"

    def test_region4_y_wrap(self, framebuffer, reference):
        """Scanlines 223-224 cross the coarseY=29 wrap boundary."""
        for sl in [223, 224]:
            key = str(sl)
            if key in reference['scanline_crc32']:
                row = framebuffer[sl * 256:(sl + 1) * 256]
                actual = zlib.crc32(row) & 0xFFFFFFFF
                expected = reference['scanline_crc32'][key]
                assert actual == expected, \
                    f"Y-wrap scanline {sl} CRC mismatch"


# ---- PPU state machine unit tests ----

class TestPPUStateMachine:
    """Verify PPU scroll register state machine correctness."""

    @pytest.fixture(autouse=True)
    def setup_ppu(self):
        from ppu_scroll import PPUScrollState
        self.PPUScrollState = PPUScrollState

    def test_increment_y_wraps_at_29_toggles_vertical_nt(self):
        """When coarseY=29 and fineY overflows, bit 11 (nt_v) must toggle."""
        ppu = self.PPUScrollState()
        ppu.set_state(v=(7 << 12) | (29 << 5))
        ppu.increment_y()
        assert (ppu.v >> 12) & 7 == 0, "fineY should be 0"
        assert (ppu.v >> 5) & 0x1F == 0, "coarseY should wrap to 0"
        assert (ppu.v >> 11) & 1 == 1, \
            "nt_v (bit 11) should toggle to 1"
        assert (ppu.v >> 10) & 1 == 0, \
            "nt_h (bit 10) should be unchanged"

    def test_increment_y_wraps_at_31_no_toggle(self):
        """When coarseY=31 and fineY overflows, wrap without toggle."""
        ppu = self.PPUScrollState()
        ppu.set_state(v=(7 << 12) | (31 << 5) | (1 << 11))
        ppu.increment_y()
        assert (ppu.v >> 5) & 0x1F == 0, "coarseY should wrap to 0"
        assert (ppu.v >> 11) & 1 == 1, "nt_v should NOT toggle"

    def test_ppuaddr_first_write_clears_bit14(self):
        """$2006 first write must clear bit 14 of t."""
        ppu = self.PPUScrollState()
        ppu.set_state(t=(7 << 12) | (15 << 5) | 10, w=0)
        ppu.write_ppuaddr(0x20)
        assert (ppu.t >> 14) & 1 == 0, "bit 14 of t must be cleared"
        assert ((ppu.t >> 8) & 0x3F) == 0x20, "high byte should be set"

    def test_ppuscroll_second_clears_fine_y(self):
        """$2005 second write must clear fine Y (bits 14-12) before set."""
        ppu = self.PPUScrollState()
        ppu.set_state(t=(7 << 12) | (3 << 5) | 5, w=1)
        ppu.write_ppuscroll(16)
        assert (ppu.t >> 12) & 7 == 0, \
            "fineY should be 0 (data=16: 16&7=0)"
        assert (ppu.t >> 5) & 0x1F == 2, \
            "coarseY should be 2 (data=16: 16>>3=2)"

    def test_copy_horizontal_includes_nt_h(self):
        """copy_horizontal must transfer nt_h (bit 10) from t to v."""
        ppu = self.PPUScrollState()
        ppu.set_state(v=0x0000, t=(1 << 10) | 20)
        ppu.copy_horizontal()
        assert ppu.v & 0x1F == 20, "coarseX should be copied"
        assert (ppu.v >> 10) & 1 == 1, \
            "nt_h (bit 10) should be copied from t"

    def test_copy_horizontal_clears_stale_nt_h(self):
        """copy_horizontal must overwrite v's nt_h with t's value."""
        ppu = self.PPUScrollState()
        ppu.set_state(v=(1 << 10) | 31, t=5)
        ppu.copy_horizontal()
        assert (ppu.v >> 10) & 1 == 0, \
            "v's nt_h should be overwritten by t's (0)"
        assert ppu.v & 0x1F == 5, "coarseX should come from t"

    def test_get_attribute_address_correct_shifts(self):
        """get_attribute_address must use correct bit extraction."""
        ppu = self.PPUScrollState()
        ppu.set_state(v=(20 << 5) | 12)
        addr = ppu.get_attribute_address()
        expected = 0x23C0 | ((20 >> 2) << 3) | (12 >> 2)
        assert addr == expected, f"Expected {expected:#06x}, got {addr:#06x}"

    def test_get_attribute_address_with_nametable(self):
        """get_attribute_address must include nametable bits."""
        ppu = self.PPUScrollState()
        ppu.set_state(v=(1 << 10) | (8 << 5) | 16)
        addr = ppu.get_attribute_address()
        expected = 0x23C0 | 0x0400 | ((8 >> 2) << 3) | (16 >> 2)
        assert addr == expected, f"Expected {expected:#06x}, got {addr:#06x}"

    def test_simulate_full_scroll_setup(self):
        """Full scroll setup via $2005/$2000 produces correct t and x."""
        from ppu_scroll import simulate_register_writes
        ppu = simulate_register_writes([
            ('ppustatus',),
            ('ppuscroll', 125),
            ('ppuscroll', 13),
            ('ppuctrl', 0),
        ])
        assert ppu.x == 5, "fine X should be 5"
        assert ppu.t & 0x1F == 15, "coarseX in t should be 15"
        assert (ppu.t >> 12) & 7 == 5, "fineY in t should be 5"
        assert (ppu.t >> 5) & 0x1F == 1, "coarseY in t should be 1"
        assert (ppu.t >> 10) & 3 == 0, "nametable in t should be 00"

    def test_ppuaddr_sets_v_on_second_write(self):
        """$2006 second write must copy t to v."""
        from ppu_scroll import simulate_register_writes
        ppu = simulate_register_writes([
            ('ppustatus',),
            ('ppuaddr', 0x21),
            ('ppuaddr', 0x08),
        ])
        assert ppu.v == ppu.t, "v should equal t after $2006 second write"
        expected_t = (0x21 << 8) | 0x08
        assert ppu.t == expected_t, \
            f"t should be {expected_t:#06x}, got {ppu.t:#06x}"


# ---- C renderer cross-validation tests ----

class TestCRenderer:
    """Verify C renderer output matches reference and Python renderer."""

    def test_c_output_exists(self):
        assert os.path.isfile(C_FRAME_PATH), \
            f"C renderer output not found at {C_FRAME_PATH}"

    def test_c_output_size(self, reference):
        with open(C_FRAME_PATH, 'rb') as f:
            data = f.read()
        expected = reference['frame_size']
        assert len(data) == expected, \
            f"C frame size: got {len(data)}, expected {expected}"

    def test_c_output_sha256(self, reference):
        with open(C_FRAME_PATH, 'rb') as f:
            data = f.read()
        actual = hashlib.sha256(data).hexdigest()
        expected = reference['frame_sha256']
        assert actual == expected, \
            "C renderer SHA-256 mismatch — output differs from reference"

    def test_c_matches_python(self, framebuffer):
        with open(C_FRAME_PATH, 'rb') as f:
            c_data = f.read()
        assert c_data == framebuffer, \
            "C and Python renderers must produce identical framebuffer output"
