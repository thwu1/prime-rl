
import subprocess
import pytest


def run_go_tests():
    """Run Go tests and return (exit_code, stdout, stderr)."""
    result = subprocess.run(
        ["go", "test", "./tscodec/", "-count=1", "-v"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


class TestGoTestsPassing:
    """Verify that all Go tests in the tscodec package pass."""

    def test_go_tests_exit_code(self):
        """All Go tests must pass (exit code 0)."""
        rc, stdout, stderr = run_go_tests()
        output = stdout + "\n" + stderr
        assert rc == 0, f"Go tests failed with exit code {rc}:\n{output}"

    def test_varint_tests_pass(self):
        """VarInt encoding/decoding tests must pass."""
        rc, stdout, stderr = run_go_tests()
        output = stdout + stderr
        for name in ["TestVarIntRoundTrip", "TestVarUintRoundTrip",
                      "TestVarIntByteOutput", "TestVarInt64sRoundTrip"]:
            assert f"--- PASS: {name}" in output, \
                f"{name} did not pass. Output:\n{output}"

    def test_nearest_delta_tests_pass(self):
        """NearestDelta encoding tests must pass."""
        rc, stdout, stderr = run_go_tests()
        output = stdout + stderr
        for name in ["TestNearestDeltaByteExact", "TestNearestDeltaRoundTrip",
                      "TestNearestDeltaPrecisionRoundTrip"]:
            assert f"--- PASS: {name}" in output, \
                f"{name} did not pass. Output:\n{output}"

    def test_nearest_delta2_tests_pass(self):
        """NearestDelta2 encoding tests must pass."""
        rc, stdout, stderr = run_go_tests()
        output = stdout + stderr
        for name in ["TestNearestDelta2ByteExact", "TestNearestDelta2ByteExactQuadratic",
                      "TestNearestDelta2UnmarshalKnown", "TestNearestDelta2RoundTrip"]:
            assert f"--- PASS: {name}" in output, \
                f"{name} did not pass. Output:\n{output}"

    def test_encoding_strategy_tests_pass(self):
        """Encoding strategy selection tests must pass."""
        rc, stdout, stderr = run_go_tests()
        output = stdout + stderr
        for name in ["TestIsConst", "TestIsDeltaConst", "TestIsGauge",
                      "TestMarshalValuesConst", "TestMarshalValuesDeltaConst",
                      "TestMarshalValuesGauge", "TestMarshalValuesCounter",
                      "TestMarshalUnmarshalValuesRoundTrip"]:
            assert f"--- PASS: {name}" in output, \
                f"{name} did not pass. Output:\n{output}"

    def test_dedup_tests_pass(self):
        """Deduplication tests must pass."""
        rc, stdout, stderr = run_go_tests()
        output = stdout + stderr
        for name in ["TestDeduplicateSamplesBasic",
                      "TestDeduplicateIdenticalTimestamps",
                      "TestDeduplicateStaleNaN"]:
            assert f"--- PASS: {name}" in output, \
                f"{name} did not pass. Output:\n{output}"

    def test_block_header_tests_pass(self):
        """Block header serialization tests must pass."""
        rc, stdout, stderr = run_go_tests()
        output = stdout + stderr
        for name in ["TestBlockHeaderRoundTrip", "TestBlockHeaderMultiple"]:
            assert f"--- PASS: {name}" in output, \
                f"{name} did not pass. Output:\n{output}"

    def test_pipeline_tests_pass(self):
        """Full pipeline tests must pass."""
        rc, stdout, stderr = run_go_tests()
        output = stdout + stderr
        for name in ["TestFullPipeline", "TestFullPipelineWithDedup"]:
            assert f"--- PASS: {name}" in output, \
                f"{name} did not pass. Output:\n{output}"
