
import json
import sys
import os
import math
import importlib
import subprocess

sys.path.insert(0, "/app")


# ── File existence ──────────────────────────────────────────────────────

class TestFilesExist:
    def test_c_pipeline_exists(self):
        assert os.path.isfile("/app/c_pipeline.py"), "c_pipeline.py not found"

    def test_rust_pipeline_exists(self):
        assert os.path.isfile("/app/rust_pipeline.py"), "rust_pipeline.py not found"

    def test_analyzer_exists(self):
        assert os.path.isfile("/app/analyzer.py"), "analyzer.py not found"

    def test_report_exists(self):
        assert os.path.isfile("/app/divergence_report.json"), "divergence_report.json not found"


# ── C Verification Harness ─────────────────────────────────────────────

class TestCHarness:
    def test_harness_binary_exists(self):
        assert os.path.isfile("/app/c_harness"), (
            "Compiled C harness not found at /app/c_harness"
        )

    def test_harness_runs_successfully(self):
        result = subprocess.run(
            ["/app/c_harness"], capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"C harness exited with code {result.returncode}: {result.stderr}"
        )

    def test_harness_output_valid_json(self):
        result = subprocess.run(
            ["/app/c_harness"], capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        assert "wave_table" in data, "C harness output missing 'wave_table'"
        assert "hsv_tests" in data, "C harness output missing 'hsv_tests'"
        assert isinstance(data["wave_table"], list)
        assert isinstance(data["hsv_tests"], list)
        assert len(data["hsv_tests"]) >= 8, (
            f"C harness should test at least 8 HSV inputs, got {len(data['hsv_tests'])}"
        )

    def test_harness_wave_table_matches_pipeline(self):
        result = subprocess.run(
            ["/app/c_harness"], capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        from c_pipeline import generate_wave_table
        pipeline_table = generate_wave_table()
        assert data["wave_table"] == pipeline_table, (
            "C harness wave_table does not match c_pipeline.generate_wave_table(). "
            f"Harness first 10: {data['wave_table'][:10]}, "
            f"Pipeline first 10: {pipeline_table[:10]}"
        )

    def test_harness_hsv_matches_pipeline(self):
        result = subprocess.run(
            ["/app/c_harness"], capture_output=True, text=True, timeout=10
        )
        data = json.loads(result.stdout)
        from c_pipeline import process_hsv
        for test in data["hsv_tests"]:
            expected = process_hsv(test["h"], test["s"], test["v"])
            actual = (test["r"], test["g"], test["b"])
            assert actual == expected, (
                f"C harness HSV({test['h']},{test['s']},{test['v']})={actual} "
                f"but c_pipeline.process_hsv={expected}"
            )


# ── Pipeline importability ──────────────────────────────────────────────

class TestPipelineImports:
    def test_c_pipeline_importable(self):
        mod = importlib.import_module("c_pipeline")
        assert callable(getattr(mod, "process_hsv", None)), "c_pipeline.process_hsv missing"
        assert callable(getattr(mod, "generate_wave_table", None)), "c_pipeline.generate_wave_table missing"
        assert callable(getattr(mod, "compute_pattern_timing", None)), "c_pipeline.compute_pattern_timing missing"

    def test_rust_pipeline_importable(self):
        mod = importlib.import_module("rust_pipeline")
        assert callable(getattr(mod, "process_hsv", None)), "rust_pipeline.process_hsv missing"
        assert callable(getattr(mod, "generate_wave_table", None)), "rust_pipeline.generate_wave_table missing"
        assert callable(getattr(mod, "compute_pattern_timing", None)), "rust_pipeline.compute_pattern_timing missing"


# ── C wave table ────────────────────────────────────────────────────────

class TestCWaveTable:
    EXPECTED = [
        0, 16, 31, 47, 63, 78, 93, 108, 122, 136, 149, 162, 174,
        185, 196, 206, 215, 223, 230, 237, 242, 246, 250, 252, 254, 255,
        254, 252, 250, 246, 242, 237, 230, 223, 215, 206, 196, 185, 174,
        162, 149, 136, 122, 108, 93, 78, 63, 47, 31, 16, 0
    ]

    def test_c_wave_table_length(self):
        from c_pipeline import generate_wave_table
        table = generate_wave_table()
        assert len(table) == 51, f"C wave table should have 51 entries, got {len(table)}"

    def test_c_wave_table_values(self):
        from c_pipeline import generate_wave_table
        table = generate_wave_table()
        assert table == self.EXPECTED, (
            f"C wave table values don't match hardcoded values from C source. "
            f"First 10: got {table[:10]}, expected {self.EXPECTED[:10]}"
        )


# ── Rust wave table ────────────────────────────────────────────────────

class TestRustWaveTable:
    def test_rust_wave_table_length(self):
        from rust_pipeline import generate_wave_table
        table = generate_wave_table()
        assert len(table) == 70, f"Rust wave table should have 70 entries, got {len(table)}"

    def test_rust_wave_table_formula(self):
        """Each entry must match the formula from the Rust source."""
        from rust_pipeline import generate_wave_table
        table = generate_wave_table()
        for i in range(69):  # Exclude last entry (special-cased)
            expected = math.trunc(
                255.0 / 2.0 * (1.0 + math.cos(
                    math.pi * (2.0 * i - 70.0) / 70.0
                ))
            )
            assert table[i] == expected, (
                f"Rust wave table mismatch at index {i}: got {table[i]}, "
                f"expected {expected} from formula"
            )

    def test_rust_wave_table_last_entry_zero(self):
        from rust_pipeline import generate_wave_table
        table = generate_wave_table()
        assert table[69] == 0, "Last entry must be forced to 0 per Rust source"

    def test_rust_wave_table_starts_zero(self):
        from rust_pipeline import generate_wave_table
        table = generate_wave_table()
        assert table[0] == 0, "First entry should be 0"

    def test_rust_wave_table_peak(self):
        from rust_pipeline import generate_wave_table
        table = generate_wave_table()
        assert table[35] == 255, "Peak at index 35 should be 255"


# ── Rust HSV-to-RGB ────────────────────────────────────────────────────

class TestRustHSV:
    def test_pure_red(self):
        from rust_pipeline import process_hsv
        assert process_hsv(0.0, 1.0, 1.0) == (255, 0, 0)

    def test_pure_green(self):
        from rust_pipeline import process_hsv
        assert process_hsv(120.0, 1.0, 1.0) == (0, 255, 0)

    def test_pure_blue(self):
        from rust_pipeline import process_hsv
        assert process_hsv(240.0, 1.0, 1.0) == (0, 0, 255)

    def test_white(self):
        from rust_pipeline import process_hsv
        assert process_hsv(0.0, 0.0, 1.0) == (255, 255, 255)

    def test_black(self):
        from rust_pipeline import process_hsv
        assert process_hsv(0.0, 0.0, 0.0) == (0, 0, 0)

    def test_negative_hue_minus60(self):
        from rust_pipeline import process_hsv
        assert process_hsv(-60.0, 1.0, 1.0) == (255, 0, 255)

    def test_negative_hue_overflow_produces_black(self):
        """h=-400 -> 360+(-400)=-40, out of all valid ranges"""
        from rust_pipeline import process_hsv
        assert process_hsv(-400.0, 1.0, 1.0) == (0, 0, 0)

    def test_hue_exceeding_360(self):
        """h=720 -> wrapped to 0 -> red"""
        from rust_pipeline import process_hsv
        assert process_hsv(720.0, 1.0, 1.0) == (255, 0, 0)


# ── C HSV-to-RGB ───────────────────────────────────────────────────────

class TestCHSV:
    def test_pure_red(self):
        from c_pipeline import process_hsv
        r, g, b = process_hsv(0.0, 1.0, 1.0)
        assert (r, g, b) == (255, 0, 0), f"Expected red, got ({r},{g},{b})"

    def test_pure_green(self):
        from c_pipeline import process_hsv
        r, g, b = process_hsv(120.0, 1.0, 1.0)
        assert (r, g, b) == (0, 255, 0), f"Expected green, got ({r},{g},{b})"


# ── Precision divergence ───────────────────────────────────────────────

class TestPrecisionDivergence:
    def test_pipelines_differ_at_half_saturation(self):
        """C and Rust produce different RGB for the same HSV input
        due to different color preprocessing approaches."""
        from c_pipeline import process_hsv as c_hsv
        from rust_pipeline import process_hsv as r_hsv
        c_rgb = c_hsv(0.0, 0.5, 1.0)
        r_rgb = r_hsv(0.0, 0.5, 1.0)
        assert c_rgb != r_rgb, (
            f"C and Rust should produce different RGB for h=0,s=0.5,v=1.0. "
            f"C={c_rgb}, Rust={r_rgb}"
        )
        assert c_rgb == (255, 128, 128), f"C expected (255,128,128), got {c_rgb}"
        assert r_rgb == (255, 127, 127), f"Rust expected (255,127,127), got {r_rgb}"


# ── Divergence report structure ────────────────────────────────────────

class TestReportStructure:
    def _load_report(self):
        with open("/app/divergence_report.json") as f:
            return json.load(f)

    def test_report_valid_json(self):
        data = self._load_report()
        assert "divergences" in data
        assert isinstance(data["divergences"], list)

    def test_minimum_divergence_count(self):
        data = self._load_report()
        assert len(data["divergences"]) >= 5, (
            f"Expected at least 5 divergences, found {len(data['divergences'])}"
        )

    def test_required_fields(self):
        data = self._load_report()
        required = {"id", "category", "description", "c_behavior", "rust_behavior"}
        valid_cats = {"color_conversion", "wave_table", "pattern_timing",
                      "input_validation", "bug"}
        for d in data["divergences"]:
            for field in required:
                assert field in d, f"Missing '{field}' in divergence '{d.get('id', '?')}'"
            assert d["category"] in valid_cats, (
                f"Invalid category '{d['category']}' in '{d['id']}'. "
                f"Must be one of: {valid_cats}"
            )


# ── Divergence report content ──────────────────────────────────────────

class TestReportContent:
    def _load_report(self):
        with open("/app/divergence_report.json") as f:
            return json.load(f)

    def test_wave_table_divergence_identified(self):
        data = self._load_report()
        wave_divs = [d for d in data["divergences"] if d["category"] == "wave_table"]
        assert len(wave_divs) >= 1, "Should identify at least one wave_table divergence"
        all_desc = " ".join(d["description"].lower() for d in wave_divs)
        has_size = any(
            x in all_desc
            for x in ["51", "70", "length", "size", "entries", "elements", "count"]
        )
        assert has_size, (
            "Wave table divergence should mention size/length difference"
        )

    def test_color_divergence_identified(self):
        data = self._load_report()
        color_divs = [d for d in data["divergences"] if d["category"] == "color_conversion"]
        assert len(color_divs) >= 1, "Should identify at least one color_conversion divergence"

    def test_timing_divergence_identified(self):
        data = self._load_report()
        timing_divs = [d for d in data["divergences"] if d["category"] == "pattern_timing"]
        assert len(timing_divs) >= 1, "Should identify at least one pattern_timing divergence"

    def test_bug_identified(self):
        """A bug in either implementation must be identified."""
        data = self._load_report()
        all_text = " ".join(
            (d.get("description", "") + " " + d.get("c_behavior", "")).lower()
            for d in data["divergences"]
        )
        bug_terms = [
            "off-by-one", "off by one", "out-of-bound", "out of bound",
            "oob", "buffer over", "past the", "beyond the", "index 51",
            "i > wave_len", "> wave_len", "bounds",
        ]
        found = any(term in all_text for term in bug_terms)
        assert found, (
            "Should identify a bug involving array bounds in one of the implementations"
        )

    def test_multiple_categories_covered(self):
        data = self._load_report()
        categories = {d["category"] for d in data["divergences"]}
        assert len(categories) >= 3, (
            f"Report should cover at least 3 divergence categories, "
            f"found {len(categories)}: {categories}"
        )
