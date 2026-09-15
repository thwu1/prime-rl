
"""
Tests for raylib build config reverse-engineering and image pipeline task.
Verifies:
  1. Configuration analysis report is correct
  2. Pipeline binary exists and is executable
  3. Output image exists with correct dimensions
  4. Pixel report contains expected values
"""

import json
import os
import struct
import zlib
import subprocess
import re

# ---------- Expected configuration flags ----------
# The target library was built with these disabled:
#   Modules: RTEXT, RMODELS, RAUDIO (entire .o not compiled)
#   Features: CAMERA_SYSTEM, GESTURES_SYSTEM (unique public symbols absent)
#   Features: RPRAND_GENERATOR (rprand.h internals absent; public API still exists as stdlib fallback)
#   Features: COMPRESSION_API (sdefl/sinfl internals absent; public API still exists as stub)
# These remain enabled:
#   SCREEN_CAPTURE, AUTOMATION_EVENTS (public API symbols always present regardless of flag;
#   no reliable internal symbols to distinguish — kept enabled for deterministic detection)
EXPECTED_CONFIG = {
    "SUPPORT_MODULE_RSHAPES": True,
    "SUPPORT_MODULE_RTEXTURES": True,
    "SUPPORT_MODULE_RTEXT": False,
    "SUPPORT_MODULE_RMODELS": False,
    "SUPPORT_MODULE_RAUDIO": False,
    "SUPPORT_CAMERA_SYSTEM": False,
    "SUPPORT_GESTURES_SYSTEM": False,
    "SUPPORT_RPRAND_GENERATOR": False,
    "SUPPORT_SCREEN_CAPTURE": True,
    "SUPPORT_AUTOMATION_EVENTS": True,
    "SUPPORT_COMPRESSION_API": False,
    "SUPPORT_IMAGE_EXPORT": True,
    "SUPPORT_IMAGE_GENERATION": True,
}

# ---------- Expected pixel values (after full pipeline) ----------
# Input: 200x200 with quadrants: TL=Red(255,0,0), TR=Green(0,255,0),
#   BL=Blue(0,0,255), BR=Yellow(255,255,0)
#
# After grayscale (BT.601: 0.299R + 0.587G + 0.114B):
#   Red->~76, Green->~150, Blue->~29, Yellow->~226
#
# After Gaussian blur (3x3 normalized): interior pixels unchanged
#
# After crop center 100x100 (50,50,100,100):
#   Cropped (25,25) -> Original (75,75) -> TL (gray ~76)
#   Cropped (75,25) -> Original (125,75) -> TR (gray ~150)
#   Cropped (25,75) -> Original (75,125) -> BL (gray ~29)
#   Cropped (75,75) -> Original (125,125) -> BR (gray ~226)
#
# After vertical flip (y -> 99-y):
#   (25,25) gets value from (25,74) which was BL -> gray ~29
#   (75,25) gets value from (75,74) which was BR -> gray ~226
#   (25,75) gets value from (25,24) which was TL -> gray ~76
#   (75,75) gets value from (75,24) which was TR -> gray ~150
#
# After brightness +40:
#   (25,25): 29+40 = 69
#   (75,25): 226+40 = 266 -> clamped to 255
#   (25,75): 76+40 = 116
#   (75,75): 150+40 = 190

EXPECTED_PIXELS = {
    (25, 25): 69,   # Blue quadrant, flipped, +40
    (75, 25): 255,  # Yellow quadrant, flipped, +40, clamped
    (25, 75): 116,  # Red quadrant, flipped, +40
    (75, 75): 190,  # Green quadrant, flipped, +40
}

PIXEL_TOLERANCE = 8  # Allow some variance in grayscale conversion rounding


def _read_png_info(filepath):
    """Read basic PNG info (width, height) without external dependencies."""
    with open(filepath, "rb") as f:
        sig = f.read(8)
        assert sig == b'\x89PNG\r\n\x1a\n', "Not a valid PNG file"
        # Read IHDR chunk
        length = struct.unpack(">I", f.read(4))[0]
        chunk_type = f.read(4)
        assert chunk_type == b'IHDR', "First chunk must be IHDR"
        ihdr_data = f.read(length)
        width, height = struct.unpack(">II", ihdr_data[:8])
        return width, height


class TestConfigReport:
    """Test Part 1: Configuration analysis report."""

    def test_config_report_exists(self):
        assert os.path.isfile("/app/analysis/config_report.json"), \
            "config_report.json not found at /app/analysis/config_report.json"

    def test_config_report_valid_json(self):
        with open("/app/analysis/config_report.json", "r") as f:
            data = json.load(f)
        assert isinstance(data, dict), "config_report.json must contain a JSON object"

    def test_config_flags_correct(self):
        with open("/app/analysis/config_report.json", "r") as f:
            data = json.load(f)

        # Normalize keys: strip whitespace, accept with or without "SUPPORT_" prefix
        normalized = {}
        for k, v in data.items():
            key = k.strip().upper()
            # Convert various truthy/falsy representations
            if isinstance(v, bool):
                val = v
            elif isinstance(v, (int, float)):
                val = bool(v)
            elif isinstance(v, str):
                val = v.strip().lower() in ("true", "1", "yes", "enabled")
            else:
                val = bool(v)
            normalized[key] = val

        errors = []
        for flag, expected in EXPECTED_CONFIG.items():
            if flag not in normalized:
                errors.append(f"Missing flag: {flag}")
            elif normalized[flag] != expected:
                errors.append(
                    f"Flag {flag}: expected {expected}, got {normalized[flag]}"
                )

        assert len(errors) == 0, (
            f"Config report has {len(errors)} error(s):\n" +
            "\n".join(f"  - {e}" for e in errors)
        )


class TestPipelineBinary:
    """Test Part 2a: Pipeline binary exists."""

    def test_pipeline_binary_exists(self):
        assert os.path.isfile("/app/pipeline"), \
            "Pipeline binary not found at /app/pipeline"

    def test_pipeline_binary_executable(self):
        assert os.access("/app/pipeline", os.X_OK), \
            "Pipeline binary at /app/pipeline is not executable"


class TestOutputImage:
    """Test Part 2b: Output image correctness."""

    def test_output_image_exists(self):
        assert os.path.isfile("/app/output/result.png"), \
            "Output image not found at /app/output/result.png"

    def test_output_image_valid_png(self):
        with open("/app/output/result.png", "rb") as f:
            sig = f.read(8)
        assert sig == b'\x89PNG\r\n\x1a\n', \
            "Output file is not a valid PNG"

    def test_output_image_dimensions(self):
        w, h = _read_png_info("/app/output/result.png")
        assert w == 100 and h == 100, \
            f"Expected 100x100 output image, got {w}x{h}"


class TestPixelReport:
    """Test Part 2c: Pixel values from the report."""

    def test_report_exists(self):
        assert os.path.isfile("/app/output/report.txt"), \
            "Pixel report not found at /app/output/report.txt"

    def test_report_dimensions(self):
        with open("/app/output/report.txt", "r") as f:
            content = f.read()

        # Find DIMENSIONS line
        dim_match = re.search(r'DIMENSIONS:\s*(\d+)\s+(\d+)', content)
        assert dim_match is not None, \
            "Could not find DIMENSIONS line in report.txt"

        w, h = int(dim_match.group(1)), int(dim_match.group(2))
        assert w == 100 and h == 100, \
            f"Report dimensions: expected 100 100, got {w} {h}"

    def test_report_pixel_values(self):
        with open("/app/output/report.txt", "r") as f:
            content = f.read()

        errors = []
        for (px, py), expected_gray in EXPECTED_PIXELS.items():
            # Match "PIXEL X Y: R G B A" pattern
            pattern = rf'PIXEL\s+{px}\s+{py}\s*:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)'
            match = re.search(pattern, content)
            if match is None:
                errors.append(f"Missing pixel ({px},{py}) in report")
                continue

            r, g, b, a = (int(match.group(i)) for i in range(1, 5))

            # For grayscale images, R==G==B. Check the red channel as representative.
            if abs(r - expected_gray) > PIXEL_TOLERANCE:
                errors.append(
                    f"Pixel ({px},{py}): expected gray ~{expected_gray} "
                    f"(+/-{PIXEL_TOLERANCE}), got R={r} G={g} B={b} A={a}"
                )

            # Alpha should be 255
            if a != 255:
                errors.append(
                    f"Pixel ({px},{py}): expected alpha=255, got {a}"
                )

        assert len(errors) == 0, (
            f"Pixel report has {len(errors)} error(s):\n" +
            "\n".join(f"  - {e}" for e in errors)
        )
