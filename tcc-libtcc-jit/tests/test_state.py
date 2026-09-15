
import glob
import json
import math
import os
import shutil
import subprocess


def parse_output(path="/app/output.txt"):
    """Parse the output file into a dict of name -> value."""
    results = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                results[parts[0]] = float(parts[1])
    return results


def test_executable_exists():
    """The series evaluator binary must exist at /app/series_jit."""
    assert os.path.isfile("/app/series_jit"), "/app/series_jit not found"


def test_executable_is_runnable():
    """The binary must have execute permission."""
    assert os.access("/app/series_jit", os.X_OK), "/app/series_jit is not executable"


def test_output_file_exists():
    """Output file must have been generated at /app/output.txt."""
    assert os.path.isfile("/app/output.txt"), "/app/output.txt not found"


def test_all_series_present():
    """All 5 series from input.json must appear in the output."""
    results = parse_output()
    expected = {"leibniz_pi4", "basel_pi2_6", "euler_e", "machin_pi4", "catalan_G"}
    missing = expected - set(results.keys())
    assert not missing, f"Missing series in output: {missing}"


def test_leibniz_pi4():
    """Leibniz series (10M terms) should approximate pi/4 within 1e-6."""
    val = parse_output()["leibniz_pi4"]
    true_val = math.pi / 4
    diff = abs(val - true_val)
    assert diff < 1e-6, f"leibniz_pi4={val}, expected ~{true_val}, diff={diff}"


def test_basel_pi2_6():
    """Basel series (10M terms) should approximate pi^2/6 within 1e-5."""
    val = parse_output()["basel_pi2_6"]
    true_val = math.pi ** 2 / 6
    diff = abs(val - true_val)
    assert diff < 1e-5, f"basel_pi2_6={val}, expected ~{true_val}, diff={diff}"


def test_euler_e():
    """Taylor series for e (25 terms) should match to machine precision."""
    val = parse_output()["euler_e"]
    true_val = math.e
    diff = abs(val - true_val)
    assert diff < 1e-14, f"euler_e={val}, expected ~{true_val}, diff={diff}"


def test_machin_pi4():
    """Machin's formula (30 terms) should match pi/4 to machine precision."""
    val = parse_output()["machin_pi4"]
    true_val = math.pi / 4
    diff = abs(val - true_val)
    assert diff < 1e-14, f"machin_pi4={val}, expected ~{true_val}, diff={diff}"


def test_catalan_G():
    """Catalan's constant series (1M terms) should approximate G within 1e-10."""
    val = parse_output()["catalan_G"]
    true_val = 0.9159655941772190
    diff = abs(val - true_val)
    assert diff < 1e-10, f"catalan_G={val}, expected ~{true_val}, diff={diff}"


def test_source_uses_dynamic_compilation():
    """The solution must use libtcc's tcc_compile_string and tcc_get_symbol."""
    c_files = glob.glob("/app/**/*.c", recursive=True)
    found = False
    for cf in c_files:
        if "/tcc-src/" in cf or "/tcc-inst/" in cf:
            continue
        try:
            with open(cf) as fh:
                content = fh.read()
                if "tcc_compile_string" in content and "tcc_get_symbol" in content:
                    found = True
                    break
        except (IOError, OSError):
            pass
    assert found, (
        "No user C source in /app/ (outside tcc-src/tcc-inst/) calls "
        "tcc_compile_string and tcc_get_symbol -- the solution must "
        "dynamically compile the function bodies via libtcc"
    )


def test_rerun_deterministic():
    """Re-running the executable must produce byte-identical output."""
    if not os.path.isfile("/app/series_jit") or not os.path.isfile("/app/output.txt"):
        assert False, "Executable or output missing, cannot test determinism"
    shutil.copy2("/app/output.txt", "/tmp/output_original.txt")
    result = subprocess.run(["/app/series_jit"], capture_output=True, timeout=180)
    assert result.returncode == 0, (
        f"Re-run failed with code {result.returncode}: "
        f"{result.stderr.decode(errors='replace')[:500]}"
    )
    with open("/tmp/output_original.txt") as f:
        original = f.read()
    with open("/app/output.txt") as f:
        rerun = f.read()
    assert original == rerun, "Output differs between runs -- not deterministic"


def test_reads_from_input_json():
    """Program must read from input.json at runtime, not hardcode series data."""
    if not os.path.isfile("/app/series_jit"):
        assert False, "Executable missing, cannot test dynamic input"

    # Save originals
    with open("/app/input.json") as f:
        original_json = f.read()
    original_output = ""
    if os.path.isfile("/app/output.txt"):
        with open("/app/output.txt") as f:
            original_output = f.read()

    try:
        data = json.loads(original_json)
        data["series"].append({
            "name": "test_constant",
            "term_body": "return 42.0;",
            "num_terms": 1
        })
        with open("/app/input.json", "w") as f:
            json.dump(data, f)

        result = subprocess.run(["/app/series_jit"], capture_output=True, timeout=180)
        assert result.returncode == 0, (
            f"Re-run with modified input.json failed: "
            f"{result.stderr.decode(errors='replace')[:500]}"
        )

        results = parse_output()
        assert "test_constant" in results, (
            "Program did not include new series from modified input.json -- "
            "it must read series definitions from the file at runtime"
        )
        assert abs(results["test_constant"] - 42.0) < 1e-10, (
            f"test_constant value wrong: {results['test_constant']}"
        )
    finally:
        # Restore originals
        with open("/app/input.json", "w") as f:
            f.write(original_json)
        if original_output:
            with open("/app/output.txt", "w") as f:
                f.write(original_output)
