"""Tests for biometric evaluation framework with quality track extension.

Verifies that both the 1:1 verification and quality assessment tracks
build, run, and validate correctly through the unified pipeline.
"""

import subprocess
import os
import pytest

WORKDIR = "/app"


@pytest.fixture(scope="session", autouse=True)
def clean_and_run():
    """Clean all build artifacts and run the full unified validation pipeline."""
    for d in ["build", "build_quality", "bin", "validation", "templates",
              "src/impl/build", "src/impl_quality/build"]:
        subprocess.run(["rm", "-rf", os.path.join(WORKDIR, d)])
    for f in os.listdir(WORKDIR):
        if f.endswith(".tar.gz"):
            os.remove(os.path.join(WORKDIR, f))
    subprocess.run(["rm", "-rf", os.path.join(WORKDIR, "lib")])
    os.makedirs(os.path.join(WORKDIR, "lib"), exist_ok=True)
    for d in ["validation", "templates", "bin"]:
        os.makedirs(os.path.join(WORKDIR, d), exist_ok=True)

    result = subprocess.run(
        ["bash", "run_validate.sh"],
        cwd=WORKDIR,
        capture_output=True,
        text=True,
        timeout=180,
    )
    yield result


def test_unified_validation_exit_code(clean_and_run):
    """Full unified validation pipeline must exit with code 0."""
    assert clean_and_run.returncode == 0, (
        f"run_validate.sh failed (exit {clean_and_run.returncode}):\n"
        f"STDOUT:\n{clean_and_run.stdout[-3000:]}\n"
        f"STDERR:\n{clean_and_run.stderr[-3000:]}"
    )


def test_11_library_exists():
    """1:1 implementation shared library must exist in lib/."""
    lib_dir = os.path.join(WORKDIR, "lib")
    libs = [f for f in os.listdir(lib_dir)
            if f.startswith("libeval_11_") and f.endswith(".so")]
    assert len(libs) == 1, f"Expected exactly 1 libeval_11_*.so, found: {libs}"


def test_quality_library_exists():
    """Quality implementation shared library must exist in lib/."""
    lib_dir = os.path.join(WORKDIR, "lib")
    libs = [f for f in os.listdir(lib_dir)
            if f.startswith("libeval_quality_") and f.endswith(".so")]
    assert len(libs) >= 1, (
        f"Expected libeval_quality_*.so in lib/, found: {os.listdir(lib_dir)}"
    )


def test_11_binary_exists():
    """1:1 test driver binary must have been built."""
    assert os.path.isfile(os.path.join(WORKDIR, "bin", "validate")), \
        "bin/validate not found"


def test_quality_binary_exists():
    """Quality test driver binary must have been built."""
    assert os.path.isfile(os.path.join(WORKDIR, "bin", "validate_quality")), \
        "bin/validate_quality not found"


def test_11_log_files_exist():
    """All 1:1 output log files must be present."""
    for name in ["enroll", "verif", "match"]:
        path = os.path.join(WORKDIR, "validation", f"{name}.log")
        assert os.path.isfile(path), f"Missing 1:1 log file: {path}"


def test_quality_log_exists():
    """Quality output log file must be present."""
    path = os.path.join(WORKDIR, "validation", "quality.log")
    assert os.path.isfile(path), "Missing quality log: validation/quality.log"


def test_11_log_line_counts():
    """1:1 log data line counts must match input line counts."""
    for name in ["enroll", "verif", "match"]:
        input_path = os.path.join(WORKDIR, "input", f"{name}.txt")
        log_path = os.path.join(WORKDIR, "validation", f"{name}.log")

        with open(input_path) as f:
            input_lines = sum(1 for line in f if line.strip())
        with open(log_path) as f:
            all_lines = [l for l in f.readlines() if l.strip()]
            log_data_lines = len(all_lines) - 1

        assert input_lines == log_data_lines, (
            f"{name}: {input_lines} input lines vs {log_data_lines} log data lines"
        )


def test_quality_log_line_count():
    """Quality log data line count must match quality.txt input lines."""
    input_path = os.path.join(WORKDIR, "input", "quality.txt")
    log_path = os.path.join(WORKDIR, "validation", "quality.log")

    with open(input_path) as f:
        input_lines = sum(1 for line in f if line.strip())
    with open(log_path) as f:
        all_lines = [l for l in f.readlines() if l.strip()]
        log_data_lines = len(all_lines) - 1

    assert input_lines == log_data_lines, (
        f"quality: {input_lines} input lines vs {log_data_lines} log data lines"
    )


def test_match_scores_nonnegative():
    """All 1:1 match scores must be >= 0."""
    log_path = os.path.join(WORKDIR, "validation", "match.log")
    with open(log_path) as f:
        lines = f.readlines()

    for i, line in enumerate(lines[1:], start=2):
        parts = line.strip().split()
        assert len(parts) >= 4, f"match.log line {i} too few columns"
        score = float(parts[2])
        assert score >= 0, f"Negative score {score} on line {i}"


def test_match_return_codes():
    """All 1:1 match return codes must be 0."""
    log_path = os.path.join(WORKDIR, "validation", "match.log")
    with open(log_path) as f:
        lines = f.readlines()

    for i, line in enumerate(lines[1:], start=2):
        parts = line.strip().split()
        if len(parts) >= 4:
            rc = int(parts[3])
            assert rc == 0, f"Non-zero return code {rc} on line {i}"


def test_quality_scores_in_range():
    """All quality scalar scores must be in [0, 100]."""
    log_path = os.path.join(WORKDIR, "validation", "quality.log")
    with open(log_path) as f:
        lines = f.readlines()

    for i, line in enumerate(lines[1:], start=2):
        parts = line.strip().split()
        assert len(parts) >= 7, f"quality.log line {i} too few columns: {line.strip()}"
        score = float(parts[1])
        assert 0 <= score <= 100, (
            f"Quality score {score} out of range [0,100] on line {i}"
        )


def test_quality_return_codes():
    """All quality return codes must be 0."""
    log_path = os.path.join(WORKDIR, "validation", "quality.log")
    with open(log_path) as f:
        lines = f.readlines()

    for i, line in enumerate(lines[1:], start=2):
        parts = line.strip().split()
        if len(parts) >= 3:
            rc = int(parts[2])
            assert rc == 0, (
                f"Non-zero quality return code {rc} on line {i}: {line.strip()}"
            )


def test_quality_attribute_values_in_range():
    """All quality attribute values must be in [0, 100]."""
    log_path = os.path.join(WORKDIR, "validation", "quality.log")
    with open(log_path) as f:
        lines = f.readlines()

    attr_names = ["sharpness", "exposure", "uniformBg", "grayscale"]
    for i, line in enumerate(lines[1:], start=2):
        parts = line.strip().split()
        assert len(parts) >= 7, f"quality.log line {i} too few columns"
        for j, attr in enumerate(attr_names):
            val = float(parts[3 + j])
            assert 0 <= val <= 100, (
                f"{attr} value {val} out of range [0,100] on line {i}"
            )


def test_quality_header_uses_double():
    """QualityAttribute.value must be double per framework convention."""
    header_path = os.path.join(WORKDIR, "src", "include", "eval_quality.h")
    with open(header_path) as f:
        content = f.read()
    assert "float value" not in content, (
        "QualityAttribute.value should be double, not float, "
        "to match the framework's floating-point convention (see eval_11.h)"
    )


def test_quality_header_shared_ptr_factory():
    """Quality factory must return shared_ptr per framework convention."""
    header_path = os.path.join(WORKDIR, "src", "include", "eval_quality.h")
    with open(header_path) as f:
        content = f.read()
    lines = content.split('\n')
    found_shared_ptr_factory = False
    for idx, line in enumerate(lines):
        if 'getImplementation' in line:
            context = '\n'.join(lines[max(0, idx-2):idx+1])
            if 'shared_ptr' in context:
                found_shared_ptr_factory = True
                break
    assert found_shared_ptr_factory, (
        "Quality getImplementation() must return shared_ptr<Interface> "
        "per framework convention (see eval_11.h)"
    )


def test_quality_header_version_linkage():
    """Quality version variables must use conditional extern uint16_t pattern."""
    header_path = os.path.join(WORKDIR, "src", "include", "eval_quality.h")
    with open(header_path) as f:
        content = f.read()
    assert "static const" not in content, (
        "Quality header must not use 'static const' for version variables. "
        "Use the conditional extern uint16_t pattern from eval_structs.h and eval_11.h"
    )
    lines = content.split('\n')
    found_extern_version = False
    for line in lines:
        if 'extern' in line and 'QUALITY_API_MAJOR_VERSION' in line:
            found_extern_version = True
            break
    assert found_extern_version, (
        "Quality version variables must use conditional extern uint16_t pattern "
        "matching eval_structs.h and eval_11.h "
        "(e.g., '#ifdef NIST_EXTERN_... / extern uint16_t QUALITY_API_MAJOR_VERSION;')"
    )
    assert "uint16_t" in content and "QUALITY_API_MAJOR_VERSION" in content, (
        "Quality version variables must use uint16_t type "
        "to match framework convention in eval_structs.h"
    )


def test_quality_driver_unmodified():
    """validate_quality.cpp must not be modified (upstream reference code)."""
    path = os.path.join(WORKDIR, "src", "testdriver", "validate_quality.cpp")
    with open(path) as f:
        content = f.read()
    assert "doQualityAssessment" in content, \
        "validate_quality.cpp appears modified — must not change upstream reference code"
    assert "shared_ptr<Interface>" in content, \
        "validate_quality.cpp appears modified — must not change upstream reference code"


def test_submission_archive_exists():
    """Submission tar.gz archive must have been created."""
    archives = [f for f in os.listdir(WORKDIR)
                if f.startswith("libeval_11_") and f.endswith(".tar.gz")]
    assert len(archives) >= 1, "No submission archive (.tar.gz) found in /app/"
