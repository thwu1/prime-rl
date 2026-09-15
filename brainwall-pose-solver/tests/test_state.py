"""
Nanobot trace simulation pipeline verification tests.

"""
import json
import os
import subprocess
import pytest

SIMULATOR = "/app/simulator/run.sh"
CASES_DIR = "/app/cases"


def run_simulator(case_num):
    """Run the simulator pipeline on a test case and return parsed JSON."""
    model_path = os.path.join(CASES_DIR, f"case{case_num}", "target.mdl")
    trace_path = os.path.join(CASES_DIR, f"case{case_num}", "trace.nbt")
    result = subprocess.run(
        [SIMULATOR, model_path, trace_path],
        capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        f"Pipeline exited with code {result.returncode}. "
        f"stderr: {result.stderr[:500]}"
    )
    out = result.stdout.strip()
    assert out, "Pipeline produced no output"
    return json.loads(out)


# ── Tool chain verification ────────────────────────────────────────────


def test_tools_are_compiled_binaries():
    """Verify tools/mdl2json and tools/nbt2json are compiled ELF binaries."""
    for tool in ["mdl2json", "nbt2json"]:
        path = f"/app/tools/{tool}"
        assert os.path.exists(path), f"Tool not found: {path}"
        with open(path, 'rb') as f:
            magic = f.read(4)
        assert magic == b'\x7fELF', (
            f"{path} is not a compiled ELF binary (magic: {magic!r})"
        )


def test_mdl2json_produces_valid_json():
    """Verify mdl2json parses a .mdl file to valid JSON with correct structure."""
    model_path = os.path.join(CASES_DIR, "case1", "target.mdl")
    result = subprocess.run(
        ["/app/tools/mdl2json", model_path],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, f"mdl2json failed: {result.stderr}"
    data = json.loads(result.stdout)
    assert "resolution" in data, "Missing 'resolution' field"
    assert "filled" in data, "Missing 'filled' field"
    assert isinstance(data["resolution"], int)
    assert isinstance(data["filled"], list)
    # Case 1 model: R=3, single voxel at (1,0,1)
    assert data["resolution"] == 3
    filled = sorted([tuple(c) for c in data["filled"]])
    assert filled == [(1, 0, 1)], f"Expected [(1,0,1)], got {filled}"


def test_nbt2json_produces_valid_json():
    """Verify nbt2json decodes a .nbt file to valid JSON command array."""
    trace_path = os.path.join(CASES_DIR, "case1", "trace.nbt")
    result = subprocess.run(
        ["/app/tools/nbt2json", trace_path],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, f"nbt2json failed: {result.stderr}"
    data = json.loads(result.stdout)
    assert isinstance(data, list), "Expected JSON array"
    assert len(data) == 6, f"Expected 6 commands, got {len(data)}"
    assert all("cmd" in cmd for cmd in data), "All entries must have 'cmd'"
    # Verify exact decoded command sequence for case 1
    assert data[0] == {"cmd": "Flip"}
    assert data[1] == {"cmd": "SMove", "lld": [0, 0, 1]}
    assert data[2] == {"cmd": "Fill", "nd": [1, 0, 0]}
    assert data[3] == {"cmd": "SMove", "lld": [0, 0, -1]}
    assert data[4] == {"cmd": "Flip"}
    assert data[5] == {"cmd": "Halt"}


# ── Pipeline entry point ──────────────────────────────────────────────


def test_simulator_exists():
    """Verify the pipeline entry point exists and is executable."""
    assert os.path.exists(SIMULATOR), f"Not found: {SIMULATOR}"
    assert os.access(SIMULATOR, os.X_OK), f"Not executable: {SIMULATOR}"


# ── End-to-end simulation tests ───────────────────────────────────────


def test_case1_single_bot_assembly():
    """Case 1: R=3, single voxel, single bot. Valid assembly."""
    out = run_simulator(1)
    assert out["valid"] is True, f"Expected valid=True, got {out}"
    assert out["energy"] == 3538, (
        f"Expected energy=3538, got {out['energy']}"
    )
    assert out["steps"] == 6, (
        f"Expected steps=6, got {out['steps']}"
    )
    assert out["model_match"] is True, (
        f"Expected model_match=True, got {out}"
    )
    assert out["error"] is None, (
        f"Expected error=None, got {out['error']}"
    )


def test_case2_multibot_fission_fusion():
    """Case 2: R=4, two voxels, fission+fusion with 2 bots."""
    out = run_simulator(2)
    assert out["valid"] is True, f"Expected valid=True, got {out}"
    assert out["energy"] == 14144, (
        f"Expected energy=14144, got {out['energy']}"
    )
    assert out["steps"] == 9, (
        f"Expected steps=9, got {out['steps']}"
    )
    assert out["model_match"] is True, (
        f"Expected model_match=True, got {out}"
    )
    assert out["error"] is None, (
        f"Expected error=None, got {out['error']}"
    )


def test_case3_invalid_trace():
    """Case 3: R=3, movement through filled voxel. Execution error."""
    out = run_simulator(3)
    assert out["valid"] is False, f"Expected valid=False, got {out}"
    assert out["energy"] == 1775, (
        f"Expected energy=1775, got {out['energy']}"
    )
    assert out["steps"] == 3, (
        f"Expected steps=3, got {out['steps']}"
    )
    assert out["model_match"] is False, (
        f"Expected model_match=False, got {out}"
    )
    assert out["error"] is not None, "Expected a non-null error message"
    assert len(out["error"]) > 0, "Expected a non-empty error message"
