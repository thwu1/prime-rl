
"""Tests for the DFG LUT generator output, visibility function evaluation,
and validation via compiled C diagnostic tools."""
import os
import struct
import json
import subprocess
import pytest

LUT_PATH = "/app/output/dfg_lut.bin"
ANALYSIS_PATH = "/app/output/analysis.json"
LUT_SIZE = 128
NUM_CHANNELS = 3
HEADER_SIZE = 16  # 4 (magic) + 4 (width) + 4 (height) + 4 (channels)
EXPECTED_DATA_SIZE = LUT_SIZE * LUT_SIZE * NUM_CHANNELS * 4  # float32 = 4 bytes


def read_lut():
    """Read and parse the DFG LUT binary file."""
    with open(LUT_PATH, "rb") as f:
        data = f.read()
    magic = data[0:4]
    width = struct.unpack("<I", data[4:8])[0]
    height = struct.unpack("<I", data[8:12])[0]
    channels = struct.unpack("<I", data[12:16])[0]
    pixel_data = data[HEADER_SIZE:]
    num_floats = width * height * channels
    values = struct.unpack(f"<{num_floats}f", pixel_data)
    return magic, width, height, channels, values


def get_pixel(values, x, y, width=LUT_SIZE, channels=NUM_CHANNELS):
    """Get the (R, G, B) values at pixel (x, y)."""
    idx = (y * width + x) * channels
    return values[idx], values[idx + 1], values[idx + 2]


# Pre-computed reference values at specific (x, y) coordinates.
# Computed using correct formulations with 1024 GGX / 4096 Charlie samples.
# Format: (x, y): (DFG1_multiscatter, DFG2_multiscatter, DFG_Charlie)
REFERENCE_VALUES = {
    (127, 127): (9.097455570007867e-13, 1.0000001198216515, 0.0),
    (0, 127): (0.9800521310862683, 0.9995194933842906, 18.25534944137473),
    (127, 0): (3.6911513124371877e-05, 0.3080455197109263, 0.14241477903932384),
    (0, 0): (0.044226492041975735, 0.9737363062762986, 0.6226707651834605),
    (64, 64): (0.021513447602297134, 0.8536398348906442, 0.22828964242800542),
    (32, 96): (0.19728208423685764, 0.9600647863657803, 0.3894398964763889),
    (96, 32): (0.0015653319790275132, 0.6283665669370296, 0.17207786507149175),
    (16, 112): (0.4832793890847841, 0.9895216998794625, 0.7095191511624427),
    (48, 48): (0.02627266663051907, 0.7691658853100233, 0.3266673943588144),
    (112, 16): (0.0003168481979002704, 0.46467036237058384, 0.15478333501566874),
}

# Diagnostic coordinates for visibility function evaluation
DIAG_COORDS = [(64, 64), (0, 0), (127, 127), (32, 96), (96, 32)]
DIAG_REF_DFG2 = {
    (64, 64): 0.8536398348906442,
    (0, 0): 0.9737363062762986,
    (127, 127): 1.0000001198216515,
    (32, 96): 0.9600647863657803,
    (96, 32): 0.6283665669370296,
}


class TestFileFormat:
    """Test that the output file has the correct format."""

    def test_file_exists(self):
        assert os.path.isfile(LUT_PATH), f"Output file not found at {LUT_PATH}"

    def test_file_size(self):
        size = os.path.getsize(LUT_PATH)
        expected = HEADER_SIZE + EXPECTED_DATA_SIZE
        assert size == expected, (
            f"File size {size} != expected {expected} "
            f"(header={HEADER_SIZE} + data={EXPECTED_DATA_SIZE})"
        )

    def test_header_magic(self):
        magic, _, _, _, _ = read_lut()
        assert magic == b"DFGL", f"Magic bytes {magic!r} != b'DFGL'"

    def test_header_dimensions(self):
        _, width, height, channels, _ = read_lut()
        assert width == LUT_SIZE, f"Width {width} != {LUT_SIZE}"
        assert height == LUT_SIZE, f"Height {height} != {LUT_SIZE}"
        assert channels == NUM_CHANNELS, f"Channels {channels} != {NUM_CHANNELS}"


class TestMathematicalProperties:
    """Test mathematical properties that must hold for a correct DFG LUT."""

    @pytest.fixture(autouse=True)
    def setup(self):
        _, _, _, _, self.values = read_lut()

    def test_dfg2_geq_dfg1(self):
        """DFG2 (total) must be >= DFG1 (Fc-weighted) at every pixel."""
        violations = []
        for y in range(LUT_SIZE):
            for x in range(LUT_SIZE):
                dfg1, dfg2, _ = get_pixel(self.values, x, y)
                if dfg2 < dfg1 - 1e-6:
                    violations.append((x, y, dfg1, dfg2))
        assert len(violations) == 0, (
            f"DFG2 < DFG1 at {len(violations)} pixels. "
            f"First 5: {violations[:5]}"
        )

    def test_dfg_values_bounded(self):
        """DFG1 and DFG2 must be in [0, 1] (within tolerance)."""
        violations = []
        for y in range(LUT_SIZE):
            for x in range(LUT_SIZE):
                dfg1, dfg2, _ = get_pixel(self.values, x, y)
                if dfg1 < -1e-4 or dfg1 > 1.001:
                    violations.append((x, y, "DFG1", dfg1))
                if dfg2 < -1e-4 or dfg2 > 1.001:
                    violations.append((x, y, "DFG2", dfg2))
        assert len(violations) == 0, (
            f"Out-of-bounds values at {len(violations)} pixels. "
            f"First 5: {violations[:5]}"
        )

    def test_charlie_non_negative(self):
        """Cloth sheen DFG must be non-negative."""
        violations = []
        for y in range(LUT_SIZE):
            for x in range(LUT_SIZE):
                _, _, charlie = get_pixel(self.values, x, y)
                if charlie < -1e-4:
                    violations.append((x, y, charlie))
        assert len(violations) == 0, (
            f"Negative Charlie at {len(violations)} pixels. "
            f"First 5: {violations[:5]}"
        )

    def test_normal_incidence_smooth_surface(self):
        """At NoV ~ 1.0 and roughness ~ 0, DFG2 should be ~ 1.0 and DFG1 ~ 0."""
        dfg1, dfg2, _ = get_pixel(self.values, 127, 127)
        assert abs(dfg2 - 1.0) < 0.005, (
            f"DFG2 at NoV~1, alpha~0 should be ~1.0, got {dfg2}"
        )
        assert dfg1 < 0.005, (
            f"DFG1 at NoV~1, alpha~0 should be ~0, got {dfg1}"
        )

    def test_interior_smoothness(self):
        """Adjacent pixels in the interior should not differ drastically.

        A correct LUT has smooth gradients. Fabricated data or wrong
        implementations will show discontinuities.
        """
        for y in range(10, 118):
            for x in range(10, 117):
                d1a, d2a, _ = get_pixel(self.values, x, y)
                d1b, d2b, _ = get_pixel(self.values, x + 1, y)
                assert abs(d1a - d1b) < 0.1, (
                    f"DFG1 step too large at ({x},{y})->({x+1},{y}): "
                    f"{d1a:.6f} vs {d1b:.6f}, diff={abs(d1a - d1b):.4f}"
                )
                assert abs(d2a - d2b) < 0.1, (
                    f"DFG2 step too large at ({x},{y})->({x+1},{y}): "
                    f"{d2a:.6f} vs {d2b:.6f}, diff={abs(d2a - d2b):.4f}"
                )


class TestReferenceValues:
    """Test specific pixel values against pre-computed reference."""

    @pytest.fixture(autouse=True)
    def setup(self):
        _, _, _, _, self.values = read_lut()

    @pytest.mark.parametrize("xy,ref", list(REFERENCE_VALUES.items()))
    def test_pixel_value(self, xy, ref):
        x, y = xy
        actual = get_pixel(self.values, x, y)
        ref_dfg1, ref_dfg2, ref_charlie = ref
        act_dfg1, act_dfg2, act_charlie = actual

        tol_dfg = 2e-4

        assert abs(act_dfg1 - ref_dfg1) < tol_dfg, (
            f"DFG1 at ({x},{y}): expected {ref_dfg1:.8f}, got {act_dfg1:.8f}, "
            f"diff={abs(act_dfg1 - ref_dfg1):.2e}"
        )
        assert abs(act_dfg2 - ref_dfg2) < tol_dfg, (
            f"DFG2 at ({x},{y}): expected {ref_dfg2:.8f}, got {act_dfg2:.8f}, "
            f"diff={abs(act_dfg2 - ref_dfg2):.2e}"
        )

        tol_charlie = max(5e-3, abs(ref_charlie) * 0.01)
        assert abs(act_charlie - ref_charlie) < tol_charlie, (
            f"Charlie at ({x},{y}): expected {ref_charlie:.8f}, got {act_charlie:.8f}, "
            f"diff={abs(act_charlie - ref_charlie):.2e}, tol={tol_charlie:.2e}"
        )


class TestAnalysis:
    """Test the visibility function evaluation analysis."""

    def test_analysis_file_exists(self):
        assert os.path.isfile(ANALYSIS_PATH), (
            f"Analysis file not found at {ANALYSIS_PATH}"
        )

    def test_analysis_valid_json(self):
        with open(ANALYSIS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict), "Analysis must be a JSON object"

    def test_chosen_visibility(self):
        with open(ANALYSIS_PATH) as f:
            data = json.load(f)
        assert data.get("chosen_visibility") == "height_correlated", (
            f"Expected 'height_correlated', got '{data.get('chosen_visibility')}'"
        )

    def test_comparison_data_structure(self):
        with open(ANALYSIS_PATH) as f:
            data = json.load(f)
        comp = data.get("comparison_data", [])
        assert len(comp) >= 5, (
            f"Expected at least 5 comparison entries, got {len(comp)}"
        )
        for entry in comp:
            assert "x" in entry and "y" in entry, (
                f"Entry missing x/y coordinates: {entry}"
            )
            assert "height_correlated" in entry, (
                f"Entry missing height_correlated data: {entry}"
            )
            assert "separable" in entry, (
                f"Entry missing separable data: {entry}"
            )
            hc = entry["height_correlated"]
            sep = entry["separable"]
            assert "dfg1" in hc and "dfg2" in hc, (
                f"height_correlated missing dfg1/dfg2: {hc}"
            )
            assert "dfg1" in sep and "dfg2" in sep, (
                f"separable missing dfg1/dfg2: {sep}"
            )

    def test_comparison_data_accuracy(self):
        """Height-correlated DFG2 values must match known reference."""
        with open(ANALYSIS_PATH) as f:
            data = json.load(f)
        comp = data.get("comparison_data", [])
        matched = 0
        for entry in comp:
            xy = (entry["x"], entry["y"])
            if xy in DIAG_REF_DFG2:
                hc_dfg2 = entry["height_correlated"]["dfg2"]
                ref_dfg2 = DIAG_REF_DFG2[xy]
                assert abs(hc_dfg2 - ref_dfg2) < 5e-4, (
                    f"HC DFG2 at {xy}: expected {ref_dfg2:.6f}, got {hc_dfg2:.6f}, "
                    f"diff={abs(hc_dfg2 - ref_dfg2):.2e}"
                )
                matched += 1
        assert matched >= 3, (
            f"Expected at least 3 diagnostic coordinate matches, got {matched}"
        )

    def test_both_functions_evaluated(self):
        """Separable values should differ from height-correlated at non-trivial points.

        This verifies that the agent genuinely implemented and ran both visibility
        functions rather than copying the same values.
        """
        with open(ANALYSIS_PATH) as f:
            data = json.load(f)
        comp = data.get("comparison_data", [])
        diffs_found = 0
        for entry in comp:
            hc_dfg2 = entry["height_correlated"]["dfg2"]
            sep_dfg2 = entry["separable"]["dfg2"]
            if abs(hc_dfg2 - sep_dfg2) > 0.001:
                diffs_found += 1
        assert diffs_found >= 3, (
            f"Expected at least 3 coordinates with different visibility results "
            f"(proving both were computed), got {diffs_found}"
        )


class TestCToolValidation:
    """Validate output using the compiled C reference comparison tool.

    This compiles lut_compare from source and uses it to independently verify
    every pixel in the generated LUT against double-precision reference values.
    """

    def test_compile_lut_compare(self):
        """The C comparison tool must compile successfully from source."""
        result = subprocess.run(
            ["make", "lut_compare"],
            cwd="/app/tools",
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"Failed to compile lut_compare:\n{result.stderr}"
        )
        assert os.path.isfile("/app/tools/lut_compare"), (
            "lut_compare binary not found after compilation"
        )

    def test_lut_compare_passes(self):
        """All pixels must pass the C reference tool's tolerance check."""
        # Ensure tool is compiled
        subprocess.run(
            ["make", "lut_compare"],
            cwd="/app/tools",
            capture_output=True, text=True
        )
        if not os.path.isfile("/app/tools/lut_compare"):
            pytest.skip("lut_compare not available")
        if not os.path.isfile(LUT_PATH):
            pytest.skip("LUT output not found")

        result = subprocess.run(
            ["/app/tools/lut_compare", LUT_PATH, "--verbose"],
            capture_output=True, text=True,
            timeout=120
        )
        assert result.returncode == 0, (
            f"lut_compare validation FAILED (exit {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
        assert "PASS" in result.stdout, (
            f"lut_compare did not report PASS:\n{result.stdout}"
        )
