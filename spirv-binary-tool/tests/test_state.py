
"""Tests for SPIR-V binary tool: analyze, strip-dead, compact, merge."""

import json
import os
import re
import struct
import subprocess
import tempfile

import pytest


def run_tool(*args, check=True):
    """Run spirv_tool.py with given arguments."""
    result = subprocess.run(
        ["python3", "/app/spirv_tool.py"] + list(args),
        capture_output=True, text=True
    )
    if check:
        assert result.returncode == 0, (
            f"spirv_tool.py {' '.join(args)} failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def validate_spv(path):
    """Run spirv-val and assert success."""
    result = subprocess.run(["spirv-val", path], capture_output=True, text=True)
    assert result.returncode == 0, (
        f"spirv-val failed on {path}:\n{result.stdout}\n{result.stderr}"
    )


def disassemble(path):
    """Run spirv-dis and return stdout."""
    result = subprocess.run(
        ["spirv-dis", path], capture_output=True, text=True
    )
    assert result.returncode == 0, f"spirv-dis failed on {path}"
    return result.stdout


def read_bound(path):
    """Read the ID bound from a SPIR-V binary header."""
    with open(path, "rb") as f:
        header = struct.unpack("<5I", f.read(20))
    return header[3]


class TestAnalyze:
    """Tests for the 'analyze' subcommand."""

    def test_analyze_compute_header(self):
        result = run_tool("analyze", "/app/modules/compute.spv")
        data = json.loads(result.stdout)

        assert data["header"]["magic"] == 0x07230203
        assert data["header"]["bound"] > 0
        assert data["header"]["schema"] == 0
        assert "version" in data["header"]

    def test_analyze_compute_functions(self):
        result = run_tool("analyze", "/app/modules/compute.spv")
        data = json.loads(result.stdout)

        func_names = sorted([f["name"] for f in data["functions"]])
        assert func_names == ["dead_fn", "dead_fn2", "helper", "main"], (
            f"Expected 4 functions, got: {func_names}"
        )

    def test_analyze_compute_entry_points(self):
        result = run_tool("analyze", "/app/modules/compute.spv")
        data = json.loads(result.stdout)

        ep_names = [ep["name"] for ep in data["entry_points"]]
        assert ep_names == ["main"]
        assert data["entry_points"][0]["execution_model"] == "GLCompute"

    def test_analyze_compute_capabilities(self):
        result = run_tool("analyze", "/app/modules/compute.spv")
        data = json.loads(result.stdout)
        assert "Shader" in data["capabilities"]

    def test_analyze_multi_entry(self):
        result = run_tool("analyze", "/app/modules/multi_entry.spv")
        data = json.loads(result.stdout)

        func_names = sorted([f["name"] for f in data["functions"]])
        assert func_names == [
            "inner_helper", "main1", "main2", "orphan", "shared_helper"
        ]

        ep_names = sorted([ep["name"] for ep in data["entry_points"]])
        assert ep_names == ["main1", "main2"]


class TestStripDead:
    """Tests for the 'strip-dead' subcommand."""

    def test_strip_dead_compute(self, tmp_path):
        out = str(tmp_path / "stripped.spv")
        run_tool("strip-dead", "/app/modules/compute.spv", out)

        validate_spv(out)

        dis = disassemble(out)
        # Exactly 2 functions should remain: main and helper
        assert dis.count("OpFunctionEnd") == 2, (
            f"Expected 2 functions, got {dis.count('OpFunctionEnd')}"
        )
        # Dead function names must not appear in any OpName
        assert '"dead_fn"' not in dis
        assert '"dead_fn2"' not in dis
        # Live functions must still be named
        assert '"main"' in dis
        assert '"helper"' in dis

    def test_strip_dead_multi_entry(self, tmp_path):
        out = str(tmp_path / "stripped_multi.spv")
        run_tool("strip-dead", "/app/modules/multi_entry.spv", out)

        validate_spv(out)

        dis = disassemble(out)
        # 4 functions remain: main1, main2, shared_helper, inner_helper
        assert dis.count("OpFunctionEnd") == 4, (
            f"Expected 4 functions, got {dis.count('OpFunctionEnd')}"
        )
        assert '"orphan"' not in dis
        assert '"main1"' in dis
        assert '"main2"' in dis
        assert '"shared_helper"' in dis
        assert '"inner_helper"' in dis


class TestCompact:
    """Tests for the 'compact' subcommand."""

    def test_compact_reduces_bound(self, tmp_path):
        stripped = str(tmp_path / "stripped.spv")
        compacted = str(tmp_path / "compacted.spv")

        # strip-dead creates ID gaps (dead_fn is defined before main)
        run_tool("strip-dead", "/app/modules/compute.spv", stripped)
        run_tool("compact", stripped, compacted)

        validate_spv(compacted)

        strip_bound = read_bound(stripped)
        compact_bound = read_bound(compacted)
        assert compact_bound < strip_bound, (
            f"compact should reduce bound: {compact_bound} >= {strip_bound}"
        )

    def test_compact_preserves_structure(self, tmp_path):
        stripped = str(tmp_path / "stripped.spv")
        compacted = str(tmp_path / "compacted.spv")

        run_tool("strip-dead", "/app/modules/compute.spv", stripped)
        run_tool("compact", stripped, compacted)

        dis = disassemble(compacted)
        assert dis.count("OpFunctionEnd") == 2
        assert '"main"' in dis
        assert '"helper"' in dis


class TestMerge:
    """Tests for the 'merge' subcommand."""

    def test_merge_validates(self, tmp_path):
        out = str(tmp_path / "merged.spv")
        run_tool(
            "merge",
            "/app/modules/merge_a.spv",
            "/app/modules/merge_b.spv",
            out,
        )
        validate_spv(out)

    def test_merge_has_both_entry_points(self, tmp_path):
        out = str(tmp_path / "merged.spv")
        run_tool(
            "merge",
            "/app/modules/merge_a.spv",
            "/app/modules/merge_b.spv",
            out,
        )

        dis = disassemble(out)
        assert '"kernel_a"' in dis, "Missing entry point kernel_a"
        assert '"kernel_b"' in dis, "Missing entry point kernel_b"
        assert dis.count("OpEntryPoint") == 2
        assert dis.count("OpFunctionEnd") == 2

    def test_merge_correct_bound(self, tmp_path):
        out = str(tmp_path / "merged.spv")
        run_tool(
            "merge",
            "/app/modules/merge_a.spv",
            "/app/modules/merge_b.spv",
            out,
        )

        bound_a = read_bound("/app/modules/merge_a.spv")
        bound_b = read_bound("/app/modules/merge_b.spv")
        merged_bound = read_bound(out)

        # Merged bound should accommodate all IDs from both modules
        assert merged_bound >= bound_a
        assert merged_bound >= bound_b
