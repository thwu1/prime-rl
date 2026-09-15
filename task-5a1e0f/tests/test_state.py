"""
Tests for the Jepsen history analyzer pipeline.
Verifies linearizability verdicts, DOT/SVG visualizations, and dynamic re-runnability.
"""

import json
import os
import subprocess
import shutil
import pytest


EXPECTED_RESULTS = {
    "h01_simple_linear.edn": True,
    "h02_stale_read.edn": False,
    "h03_concurrent_writes.edn": True,
    "h04_impossible_value.edn": False,
    "h05_info_linearizable.edn": True,
    "h06_cas_conflict.edn": False,
    "h07_cas_with_fail.edn": True,
    "h08_complex_nonlinear.edn": False,
    "h09_cas_chain.edn": True,
    "h10_info_contradiction.edn": False,
    "h11_stress.edn": True,
    "h12_floating_info.edn": True,
}

NON_LINEARIZABLE = [k for k, v in EXPECTED_RESULTS.items() if not v]


def _load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def test_results_file_exists():
    """Check that the results file was created."""
    assert os.path.exists("/app/results.json"), "results.json not found at /app/results.json"


@pytest.mark.parametrize("filename,expected", list(EXPECTED_RESULTS.items()))
def test_history_result(filename, expected):
    """Verify each history has the correct linearizability verdict."""
    results = _load_results()
    assert filename in results, f"Missing result for {filename}"
    actual = results[filename]
    assert actual == expected, (
        f"{filename}: expected {'linearizable' if expected else 'NOT linearizable'}, "
        f"got {'linearizable' if actual else 'NOT linearizable'}"
    )


@pytest.mark.parametrize("filename", NON_LINEARIZABLE)
def test_dot_exists_for_nonlinearizable(filename):
    """Verify DOT file exists for each non-linearizable history."""
    name = filename.replace(".edn", "")
    dot_path = f"/app/viz/{name}.dot"
    assert os.path.exists(dot_path), f"Missing DOT file: {dot_path}"


@pytest.mark.parametrize("filename", NON_LINEARIZABLE)
def test_svg_exists_for_nonlinearizable(filename):
    """Verify SVG visualization exists for each non-linearizable history."""
    name = filename.replace(".edn", "")
    svg_path = f"/app/viz/{name}.svg"
    assert os.path.exists(svg_path), f"Missing SVG visualization: {svg_path}"


@pytest.mark.parametrize("filename", NON_LINEARIZABLE)
def test_svg_is_valid(filename):
    """Verify SVG files contain valid SVG content."""
    name = filename.replace(".edn", "")
    svg_path = f"/app/viz/{name}.svg"
    if not os.path.exists(svg_path):
        pytest.skip(f"SVG not found: {svg_path}")
    with open(svg_path) as f:
        content = f.read()
    assert "<svg" in content, f"SVG file doesn't contain <svg tag: {svg_path}"
    assert len(content) > 100, f"SVG file suspiciously small: {svg_path}"


@pytest.mark.parametrize("filename", NON_LINEARIZABLE)
def test_dot_contains_operations(filename):
    """Verify DOT files contain labeled operation nodes."""
    name = filename.replace(".edn", "")
    dot_path = f"/app/viz/{name}.dot"
    if not os.path.exists(dot_path):
        pytest.skip(f"DOT not found: {dot_path}")
    with open(dot_path) as f:
        content = f.read()
    assert "digraph" in content, f"DOT file missing digraph declaration: {dot_path}"
    assert "->" in content or "label" in content, (
        f"DOT file missing edges or labels: {dot_path}"
    )


def _to_edn_value(val):
    """Convert a Python value to EDN string."""
    if val is None:
        return "nil"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        return str(val)
    if isinstance(val, list):
        return "[" + " ".join(_to_edn_value(v) for v in val) + "]"
    if isinstance(val, str):
        return '"' + val + '"'
    return str(val)


def _to_edn_event(event):
    """Convert a Python event dict to an EDN map string."""
    parts = [
        f":index {event['index']}",
        f":process {event['process']}",
        f":type :{event['type']}",
        f":f :{event['f']}",
        f":value {_to_edn_value(event.get('value'))}",
    ]
    return "{" + " ".join(parts) + "}"


def _history_to_edn(history):
    """Convert a Python history list to EDN vector string."""
    events = [_to_edn_event(e) for e in history]
    return "[" + "\n ".join(events) + "]"


def test_analyzer_handles_new_edn_inputs():
    """Verify the analyzer works on previously unseen EDN histories.

    This ensures the pipeline is a working multi-tool analyzer, not hardcoded.
    """
    assert os.path.exists("/app/analyze.sh"), "analyze.sh not found at /app/analyze.sh"

    # Save original results if present
    if os.path.exists("/app/results.json"):
        shutil.copy("/app/results.json", "/tmp/results_backup.json")

    dynamic_cases = {
        "zz_dynamic_linear.edn": {
            "history": [
                {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 42},
                {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 42},
                {"index": 2, "process": 1, "type": "invoke", "f": "read", "value": None},
                {"index": 3, "process": 1, "type": "ok", "f": "read", "value": 42},
            ],
            "expected": True,
        },
        "zz_dynamic_nonlinear.edn": {
            "history": [
                {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 1},
                {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 1},
                {"index": 2, "process": 1, "type": "invoke", "f": "read", "value": None},
                {"index": 3, "process": 1, "type": "ok", "f": "read", "value": 999},
            ],
            "expected": False,
        },
        "zz_dynamic_cas_ok.edn": {
            "history": [
                {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 0},
                {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 0},
                {"index": 2, "process": 1, "type": "invoke", "f": "cas", "value": [0, 10]},
                {"index": 3, "process": 1, "type": "ok", "f": "cas", "value": [0, 10]},
                {"index": 4, "process": 2, "type": "invoke", "f": "read", "value": None},
                {"index": 5, "process": 2, "type": "ok", "f": "read", "value": 10},
            ],
            "expected": True,
        },
        "zz_dynamic_cas_conflict.edn": {
            "history": [
                {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 0},
                {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 0},
                {"index": 2, "process": 1, "type": "invoke", "f": "cas", "value": [0, 1]},
                {"index": 3, "process": 2, "type": "invoke", "f": "cas", "value": [0, 2]},
                {"index": 4, "process": 1, "type": "ok", "f": "cas", "value": [0, 1]},
                {"index": 5, "process": 2, "type": "ok", "f": "cas", "value": [0, 2]},
                {"index": 6, "process": 3, "type": "invoke", "f": "read", "value": None},
                {"index": 7, "process": 3, "type": "ok", "f": "read", "value": 2},
            ],
            "expected": False,
        },
        "zz_dynamic_info_write.edn": {
            "history": [
                {"index": 0, "process": 0, "type": "invoke", "f": "write", "value": 0},
                {"index": 1, "process": 0, "type": "ok", "f": "write", "value": 0},
                {"index": 2, "process": 1, "type": "invoke", "f": "write", "value": 99},
                {"index": 3, "process": 1, "type": "info", "f": "write", "value": 99},
                {"index": 4, "process": 2, "type": "invoke", "f": "read", "value": None},
                {"index": 5, "process": 2, "type": "ok", "f": "read", "value": 99},
            ],
            "expected": True,
        },
    }

    try:
        # Write dynamic EDN histories
        os.makedirs("/app/histories", exist_ok=True)
        for fn, data in dynamic_cases.items():
            edn_str = _history_to_edn(data["history"])
            with open(f"/app/histories/{fn}", "w") as f:
                f.write(edn_str)

        # Run the full pipeline
        result = subprocess.run(
            ["bash", "/app/analyze.sh"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, (
            f"analyze.sh failed with exit code {result.returncode}.\n"
            f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )

        # Load and verify new results
        with open("/app/results.json") as f:
            results = json.load(f)

        # Verify dynamic results
        for fn, data in dynamic_cases.items():
            assert fn in results, f"Analyzer didn't produce result for {fn}"
            assert results[fn] == data["expected"], (
                f"{fn}: expected {data['expected']}, got {results[fn]}"
            )

        # Verify SVG generated for non-linearizable dynamic cases
        for fn, data in dynamic_cases.items():
            if not data["expected"]:
                name = fn.replace(".edn", "")
                svg_path = f"/app/viz/{name}.svg"
                assert os.path.exists(svg_path), (
                    f"Missing SVG for dynamic non-linearizable case: {svg_path}"
                )

        # Original results must still be correct after re-run
        for fn, expected in EXPECTED_RESULTS.items():
            assert fn in results, f"Missing original result for {fn} after re-run"
            assert results[fn] == expected, (
                f"After re-run, {fn}: expected {expected}, got {results[fn]}"
            )
    finally:
        # Clean up dynamic files and restore original results
        for fn in dynamic_cases:
            path = f"/app/histories/{fn}"
            if os.path.exists(path):
                os.remove(path)
            name = fn.replace(".edn", "")
            for ext in [".svg", ".dot"]:
                p = f"/app/viz/{name}{ext}"
                if os.path.exists(p):
                    os.remove(p)
        if os.path.exists("/tmp/results_backup.json"):
            shutil.copy("/tmp/results_backup.json", "/app/results.json")
