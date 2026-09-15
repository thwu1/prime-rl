
import subprocess
import json
import os
import pytest


@pytest.fixture(scope="session")
def benchmark_result():
    """Build the project and run the benchmark program once."""
    subprocess.run(["make", "-C", "/app", "clean"], capture_output=True, text=True)
    build = subprocess.run(
        ["make", "-C", "/app", "all"],
        capture_output=True, text=True, timeout=120
    )
    if build.returncode != 0:
        pytest.fail(f"Build failed:\n{build.stderr}")

    run = subprocess.run(
        ["/app/benchmark"],
        capture_output=True, text=True, timeout=60
    )
    return run


@pytest.fixture(scope="session")
def analysis():
    """Load and return analysis.json."""
    path = "/app/analysis.json"
    if not os.path.exists(path):
        pytest.fail("analysis.json not found at /app/analysis.json")
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Correctness tests: the optimized kernels must produce numerically correct
# output identical (within tolerance) to the reference computation in main.cpp.
# ---------------------------------------------------------------------------

class TestCorrectness:
    def test_program_exits_zero(self, benchmark_result):
        assert benchmark_result.returncode == 0, (
            f"benchmark returned non-zero.\n"
            f"stdout:\n{benchmark_result.stdout}\n"
            f"stderr:\n{benchmark_result.stderr}"
        )

    def test_scale_array_pass(self, benchmark_result):
        assert "scale_array: PASS" in benchmark_result.stdout, (
            f"scale_array did not PASS.\nstdout:\n{benchmark_result.stdout}"
        )

    def test_column_sums_pass(self, benchmark_result):
        assert "column_sums: PASS" in benchmark_result.stdout, (
            f"column_sums did not PASS.\nstdout:\n{benchmark_result.stdout}"
        )

    def test_dot_product_pass(self, benchmark_result):
        assert "dot_product: PASS" in benchmark_result.stdout, (
            f"dot_product did not PASS.\nstdout:\n{benchmark_result.stdout}"
        )

    def test_apply_transform_pass(self, benchmark_result):
        assert "apply_transform: PASS" in benchmark_result.stdout, (
            f"apply_transform did not PASS.\nstdout:\n{benchmark_result.stdout}"
        )


# ---------------------------------------------------------------------------
# Analysis tests: the agent must correctly identify each kernel's bottleneck.
# ---------------------------------------------------------------------------

class TestAnalysis:
    def test_json_has_all_kernels(self, analysis):
        for name in ("scale_array", "column_sums", "dot_product", "apply_transform"):
            assert name in analysis, f"Missing kernel '{name}' in analysis.json"

    def test_json_has_required_fields(self, analysis):
        for name in ("scale_array", "column_sums", "dot_product", "apply_transform"):
            entry = analysis[name]
            assert "bottleneck" in entry, f"Missing 'bottleneck' for '{name}'"
            assert "explanation" in entry, f"Missing 'explanation' for '{name}'"
            assert isinstance(entry["explanation"], str) and len(entry["explanation"]) > 20, (
                f"Explanation for '{name}' is missing or too short"
            )

    def test_scale_array_bottleneck(self, analysis):
        assert analysis["scale_array"]["bottleneck"] == "pointer_aliasing", (
            f"Expected 'pointer_aliasing', got '{analysis['scale_array']['bottleneck']}'"
        )

    def test_column_sums_bottleneck(self, analysis):
        assert analysis["column_sums"]["bottleneck"] == "non_unit_stride", (
            f"Expected 'non_unit_stride', got '{analysis['column_sums']['bottleneck']}'"
        )

    def test_dot_product_bottleneck(self, analysis):
        assert analysis["dot_product"]["bottleneck"] == "dependency_chain", (
            f"Expected 'dependency_chain', got '{analysis['dot_product']['bottleneck']}'"
        )

    def test_apply_transform_bottleneck(self, analysis):
        assert analysis["apply_transform"]["bottleneck"] == "function_call", (
            f"Expected 'function_call', got '{analysis['apply_transform']['bottleneck']}'"
        )


# ---------------------------------------------------------------------------
# llvm-mca tests: the agent must produce valid llvm-mca analysis output.
# ---------------------------------------------------------------------------

class TestLlvmMca:
    def test_output_file_exists(self):
        assert os.path.exists("/app/llvm_mca_analysis.txt"), (
            "llvm_mca_analysis.txt not found at /app/llvm_mca_analysis.txt"
        )

    def test_output_has_sufficient_content(self):
        with open("/app/llvm_mca_analysis.txt") as f:
            content = f.read()
        assert len(content) > 200, (
            f"llvm-mca output is too short ({len(content)} chars). "
            "Expected substantive analysis output."
        )

    def test_output_contains_mca_keywords(self):
        with open("/app/llvm_mca_analysis.txt") as f:
            content = f.read()
        keywords = [
            "Iterations", "Block RThroughput", "Resource pressure",
            "Instruction Info", "Timeline", "uOps",
        ]
        found = [kw for kw in keywords if kw in content]
        assert len(found) >= 2, (
            f"llvm-mca output only matched {len(found)}/6 expected keywords "
            f"({found}). File may not contain valid llvm-mca output."
        )
