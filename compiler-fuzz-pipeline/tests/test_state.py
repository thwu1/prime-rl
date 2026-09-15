
import subprocess
import json
import os
import tempfile


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def write_tmp_c(code: str) -> str:
    """Write code to a temporary .c file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".c", dir="/tmp")
    with os.fdopen(fd, "w") as f:
        f.write(code)
    return path


# ---------------------------------------------------------------------------
# 1. Csmith build
# ---------------------------------------------------------------------------

def test_csmith_binary_exists():
    """Csmith binary must exist and generate valid C code."""
    csmith = "/app/csmith-src/build/src/csmith"
    assert os.path.isfile(csmith), f"Csmith binary not found at {csmith}"
    result = subprocess.run(
        [csmith, "--seed", "42"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"Csmith exited with {result.returncode}"
    assert "main" in result.stdout, "Generated code does not contain main"


# ---------------------------------------------------------------------------
# 2. fuzz.sh existence
# ---------------------------------------------------------------------------

def test_fuzz_sh_exists():
    fuzz = "/app/pipeline/fuzz.sh"
    assert os.path.isfile(fuzz), f"{fuzz} not found"
    assert os.access(fuzz, os.X_OK), f"{fuzz} is not executable"


# ---------------------------------------------------------------------------
# 3. fuzz.sh --seed mode produces valid JSON
# ---------------------------------------------------------------------------

def test_fuzz_seed_mode():
    result = subprocess.run(
        ["/app/pipeline/fuzz.sh", "--seed", "42"],
        capture_output=True, text=True, timeout=120,
    )
    stdout = result.stdout.strip()
    assert stdout, "fuzz.sh --seed 42 produced no stdout"
    data = json.loads(stdout)
    assert "status" in data, "Missing 'status' field"
    valid = {"pass", "mismatch", "crash", "timeout", "compile_error", "ub"}
    assert data["status"] in valid, f"Unknown status: {data['status']}"


# ---------------------------------------------------------------------------
# 4. fuzz.sh --file with a valid, deterministic program => pass
# ---------------------------------------------------------------------------

def test_fuzz_file_pass():
    path = write_tmp_c('#include <stdio.h>\nint main(void) { printf("hello\\n"); return 0; }\n')
    try:
        result = subprocess.run(
            ["/app/pipeline/fuzz.sh", "--file", path],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout.strip())
        assert data["status"] == "pass", f"Expected pass, got {data['status']}"
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# 5. fuzz.sh --file with infinite loop => timeout
# ---------------------------------------------------------------------------

def test_fuzz_file_timeout():
    path = write_tmp_c("int main(void) { volatile unsigned x=0; while(1){x++;} return 0; }\n")
    try:
        result = subprocess.run(
            ["/app/pipeline/fuzz.sh", "--file", path],
            capture_output=True, text=True, timeout=120,
        )
        data = json.loads(result.stdout.strip())
        assert data["status"] == "timeout", f"Expected timeout, got {data['status']}"
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# 6. fuzz.sh --file with abort() => crash
# ---------------------------------------------------------------------------

def test_fuzz_file_crash():
    path = write_tmp_c("#include <stdlib.h>\nint main(void) { abort(); return 0; }\n")
    try:
        result = subprocess.run(
            ["/app/pipeline/fuzz.sh", "--file", path],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout.strip())
        assert data["status"] == "crash", f"Expected crash, got {data['status']}"
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# 7. fuzz.sh --file with syntax error => compile_error
# ---------------------------------------------------------------------------

def test_fuzz_file_compile_error():
    path = write_tmp_c("int main( { return\n")
    try:
        result = subprocess.run(
            ["/app/pipeline/fuzz.sh", "--file", path],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout.strip())
        assert data["status"] == "compile_error", (
            f"Expected compile_error, got {data['status']}"
        )
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# 8. fuzz.sh --file with __OPTIMIZE__ => mismatch
# ---------------------------------------------------------------------------

def test_fuzz_file_mismatch():
    code = (
        '#include <stdio.h>\n'
        'int main(void) {\n'
        '#ifdef __OPTIMIZE__\n'
        '    printf("opt\\n");\n'
        '#else\n'
        '    printf("noopt\\n");\n'
        '#endif\n'
        '    return 0;\n'
        '}\n'
    )
    path = write_tmp_c(code)
    try:
        result = subprocess.run(
            ["/app/pipeline/fuzz.sh", "--file", path],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(result.stdout.strip())
        assert data["status"] == "mismatch", (
            f"Expected mismatch, got {data['status']}"
        )
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# 9. interestingness.sh exists
# ---------------------------------------------------------------------------

def test_interestingness_exists():
    s = "/app/pipeline/interestingness.sh"
    assert os.path.isfile(s), f"{s} not found"
    assert os.access(s, os.X_OK), f"{s} not executable"


# ---------------------------------------------------------------------------
# 10. interestingness.sh accepts UB-free divergent program
# ---------------------------------------------------------------------------

def test_interestingness_accepts_divergent():
    code = (
        '#include <stdio.h>\n'
        'int main(void) {\n'
        '#ifdef __OPTIMIZE__\n'
        '    printf("optimized\\n");\n'
        '#else\n'
        '    printf("baseline\\n");\n'
        '#endif\n'
        '    return 0;\n'
        '}\n'
    )
    path = write_tmp_c(code)
    try:
        result = subprocess.run(
            ["/app/pipeline/interestingness.sh", path],
            capture_output=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"interestingness.sh should accept divergent file, "
            f"got rc={result.returncode}, "
            f"stderr={result.stderr[:500]}"
        )
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# 11. interestingness.sh rejects program with UB
# ---------------------------------------------------------------------------

def test_interestingness_rejects_ub():
    code = (
        '#include <stdio.h>\n'
        '#include <limits.h>\n'
        'int main(void) {\n'
        '    volatile int x = INT_MAX;\n'
        '    int y = x + 1;\n'
        '    printf("%d\\n", y);\n'
        '    return 0;\n'
        '}\n'
    )
    path = write_tmp_c(code)
    try:
        result = subprocess.run(
            ["/app/pipeline/interestingness.sh", path],
            capture_output=True, timeout=60,
        )
        assert result.returncode != 0, (
            "interestingness.sh should reject program with UB"
        )
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# 12. interestingness.sh rejects program with identical output
# ---------------------------------------------------------------------------

def test_interestingness_rejects_same_output():
    path = write_tmp_c('#include <stdio.h>\nint main(void) { printf("same\\n"); return 0; }\n')
    try:
        result = subprocess.run(
            ["/app/pipeline/interestingness.sh", path],
            capture_output=True, timeout=60,
        )
        assert result.returncode != 0, (
            "interestingness.sh should reject program with identical output"
        )
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# 13. batch.sh exists
# ---------------------------------------------------------------------------

def test_batch_sh_exists():
    b = "/app/pipeline/batch.sh"
    assert os.path.isfile(b), f"{b} not found"
    assert os.access(b, os.X_OK), f"{b} not executable"


# ---------------------------------------------------------------------------
# 14. report.json structure
# ---------------------------------------------------------------------------

def test_report_json_structure():
    rpath = "/app/pipeline/report.json"
    assert os.path.isfile(rpath), f"{rpath} not found"
    with open(rpath) as f:
        data = json.load(f)

    assert data["total"] == 20, f"Expected total=20, got {data['total']}"
    assert isinstance(data["results"], list), "'results' should be a list"
    assert len(data["results"]) == 20, f"Expected 20 results, got {len(data['results'])}"

    for key in ("pass", "mismatch", "crash", "timeout", "compile_error", "ub"):
        assert key in data, f"Missing count key '{key}'"
        assert isinstance(data[key], int), f"'{key}' should be int"

    count_sum = sum(data[k] for k in ("pass", "mismatch", "crash", "timeout", "compile_error", "ub"))
    assert count_sum == data["total"], (
        f"Status counts ({count_sum}) should equal total ({data['total']})"
    )


# ---------------------------------------------------------------------------
# 15. Reduced file
# ---------------------------------------------------------------------------

def test_reduced_file():
    rpath = "/app/pipeline/example_reduced.c"
    assert os.path.isfile(rpath), f"{rpath} not found"

    with open(rpath) as f:
        lines = f.readlines()
    assert len(lines) < 50, (
        f"Reduced file has {len(lines)} lines; expected < 50"
    )

    # Compile -O0
    r0 = subprocess.run(
        ["gcc", "-O0", "-w", "-o", "/tmp/reduced_O0", rpath],
        capture_output=True, timeout=30,
    )
    assert r0.returncode == 0, "Reduced file must compile with gcc -O0"

    # Compile -O2
    r2 = subprocess.run(
        ["gcc", "-O2", "-w", "-o", "/tmp/reduced_O2", rpath],
        capture_output=True, timeout=30,
    )
    assert r2.returncode == 0, "Reduced file must compile with gcc -O2"

    # Run both
    out0 = subprocess.run(
        ["/tmp/reduced_O0"], capture_output=True, text=True, timeout=5,
    )
    out2 = subprocess.run(
        ["/tmp/reduced_O2"], capture_output=True, text=True, timeout=5,
    )
    assert out0.stdout != out2.stdout, (
        "Reduced file must produce different output at -O0 vs -O2"
    )

    # UBSan check
    ru = subprocess.run(
        ["gcc", "-fsanitize=undefined", "-O0", "-w",
         "-o", "/tmp/reduced_ubsan", rpath],
        capture_output=True, timeout=30,
    )
    if ru.returncode == 0:
        ub_run = subprocess.run(
            ["/tmp/reduced_ubsan"],
            capture_output=True, text=True, timeout=5,
        )
        assert "runtime error" not in ub_run.stderr, (
            "Reduced file must not contain undefined behavior"
        )
