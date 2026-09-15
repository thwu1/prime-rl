"""
"""
import json
import os
import re
import subprocess

import pytest

EXPECTED_OUTPUT_LINES = [
    "RECORDS: 6",
    "SUM: 195.0000",
    "MEAN: 32.5000",
    "MAX: 100.0000",
    "MIN: 3.5000",
    "FILTERED_SUM(type>2): 171.2500 (4 records)",
    "FLAGGED: humidity windspeed bearing",
]

V2_REQUIRED_SYMBOLS = [
    "proc_init",
    "proc_load",
    "proc_compute",
    "proc_format",
    "proc_cleanup",
]


class TestShimLibrary:
    """Verify the compatibility shim library exists and has correct properties."""

    def test_shim_file_exists(self):
        assert os.path.isfile("/app/libprocessor.so.2"), (
            "libprocessor.so.2 not found in /app/"
        )

    def test_shim_is_shared_library(self):
        result = subprocess.run(
            ["file", "/app/libprocessor.so.2"],
            capture_output=True, text=True
        )
        assert "ELF" in result.stdout and "shared object" in result.stdout, (
            f"libprocessor.so.2 is not an ELF shared library: {result.stdout}"
        )

    def test_shim_soname(self):
        result = subprocess.run(
            ["readelf", "-d", "/app/libprocessor.so.2"],
            capture_output=True, text=True
        )
        soname_found = False
        for line in result.stdout.split("\n"):
            if "SONAME" in line and "libprocessor.so.2" in line:
                soname_found = True
                break
        assert soname_found, (
            "SONAME libprocessor.so.2 not found in dynamic section. "
            f"readelf output: {result.stdout[:500]}"
        )

    def test_shim_exports_v2_symbols(self):
        result = subprocess.run(
            ["nm", "-D", "/app/libprocessor.so.2"],
            capture_output=True, text=True
        )
        exported = set()
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[-2] == "T":
                exported.add(parts[-1])
        missing = [s for s in V2_REQUIRED_SYMBOLS if s not in exported]
        assert not missing, (
            f"Shim library missing exported symbols: {missing}. "
            f"Found: {exported & set(V2_REQUIRED_SYMBOLS)}"
        )


class TestLegacyAppExecution:
    """Verify legacy_app runs correctly with the shim."""

    def test_legacy_app_runs(self):
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = "/app:" + env.get("LD_LIBRARY_PATH", "")
        result = subprocess.run(
            ["/app/legacy_app"],
            capture_output=True, text=True,
            cwd="/app", env=env, timeout=30
        )
        assert result.returncode == 0, (
            f"legacy_app failed with return code {result.returncode}. "
            f"stderr: {result.stderr[:500]}"
        )

    def test_output_file_exists(self):
        assert os.path.isfile("/app/output.txt"), (
            "output.txt not found in /app/ after running legacy_app"
        )

    def test_output_content_correct(self):
        if not os.path.isfile("/app/output.txt"):
            pytest.skip("output.txt does not exist")

        with open("/app/output.txt") as f:
            actual_lines = [line.strip() for line in f if line.strip()]

        for expected_line in EXPECTED_OUTPUT_LINES:
            found = False
            for actual_line in actual_lines:
                if actual_line == expected_line:
                    found = True
                    break
            assert found, (
                f"Expected line not found in output.txt: '{expected_line}'. "
                f"Actual lines: {actual_lines}"
            )

    def test_output_line_count(self):
        if not os.path.isfile("/app/output.txt"):
            pytest.skip("output.txt does not exist")

        with open("/app/output.txt") as f:
            actual_lines = [line.strip() for line in f if line.strip()]
        assert len(actual_lines) == len(EXPECTED_OUTPUT_LINES), (
            f"Expected {len(EXPECTED_OUTPUT_LINES)} lines, "
            f"got {len(actual_lines)}: {actual_lines}"
        )


class TestCompatibilityAssessment:
    """Verify the compatibility assessment JSON is complete and well-structured."""

    def _load_assessment(self):
        path = "/app/compatibility_assessment.json"
        if not os.path.isfile(path):
            pytest.fail("compatibility_assessment.json not found in /app/")
        with open(path) as f:
            return json.load(f)

    def test_assessment_is_valid_json(self):
        self._load_assessment()

    def test_assessment_has_mappings(self):
        data = self._load_assessment()
        assert "mappings" in data, "Assessment missing 'mappings' key"
        mappings = data["mappings"]
        assert isinstance(mappings, list), "'mappings' must be a list"
        assert len(mappings) >= 5, (
            f"Expected >= 5 function mappings, got {len(mappings)}"
        )

    def test_assessment_covers_all_v2_functions(self):
        data = self._load_assessment()
        mappings = data.get("mappings", [])
        mapped_v2 = set()
        for m in mappings:
            v2_name = m.get("v2_function", "")
            if not v2_name:
                for key in ("function", "v2", "name", "source"):
                    if key in m and isinstance(m[key], str):
                        v2_name = m[key]
                        break
            mapped_v2.add(v2_name)
        missing = [s for s in V2_REQUIRED_SYMBOLS if s not in mapped_v2]
        assert not missing, (
            f"Assessment missing mappings for v2 functions: {missing}. "
            f"Found: {mapped_v2}"
        )

    def test_assessment_has_struct_changes(self):
        data = self._load_assessment()
        assert "struct_changes" in data, "Assessment missing 'struct_changes' key"
        changes = data["struct_changes"]
        assert isinstance(changes, list), "'struct_changes' must be a list"
        assert len(changes) >= 2, (
            f"Expected >= 2 struct change entries (at minimum: field reorder "
            f"and label size change), got {len(changes)}"
        )

    def test_assessment_has_risk(self):
        data = self._load_assessment()
        has_risk = False
        for key in ("overall_risk", "risk", "risk_assessment",
                     "overall_assessment", "risk_level"):
            if key in data:
                has_risk = True
                break
        assert has_risk, (
            "Assessment must include an overall risk or assessment field"
        )
