
import subprocess
import pytest


def run_compose_test(test_name: str) -> None:
    """Run a specific test case from the Node.js test suite."""
    result = subprocess.run(
        ["node", "/tests/test_compose.js", test_name],
        capture_output=True,
        timeout=30,
        cwd="/app",
    )
    stdout = result.stdout.decode()
    stderr = result.stderr.decode()
    assert result.returncode == 0, (
        f"Test '{test_name}' failed (exit {result.returncode}):\n"
        f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    )


class TestStreamCompose:
    """Verify the composeStreams function handles all stream lifecycle concerns."""

    def test_simple_composition(self):
        """Two transforms chained: data flows through and end fires."""
        run_compose_test("simple_composition")

    def test_object_mode_propagation(self):
        """Composed stream inherits objectMode from head and tail."""
        run_compose_test("object_mode")

    def test_backpressure(self):
        """Drain callback is properly invoked under backpressure."""
        run_compose_test("backpressure")

    def test_error_propagation(self):
        """Error in a middle stage surfaces on the composed stream."""
        run_compose_test("error_propagation")

    def test_end_forwarding(self):
        """Composed stream emits 'end' when pipeline completes."""
        run_compose_test("end_forwarding")

    def test_final_waits_for_drain(self):
        """'finish' fires only after all data has been processed."""
        run_compose_test("final_waits")

    def test_destroy_cleanup(self):
        """Destroying composed stream destroys all internal stages."""
        run_compose_test("destroy_cleanup")

    def test_three_stage_composition(self):
        """Three transforms chained produce correct output."""
        run_compose_test("three_stage")

    def test_async_generator_stage(self):
        """Async generator function works as a pipeline stage with objects."""
        run_compose_test("async_generator_stage")

    def test_generator_error(self):
        """Error thrown inside async generator surfaces on composed stream."""
        run_compose_test("generator_error")

    def test_mixed_pipeline(self):
        """Mix of Transform streams and async generators in a pipeline."""
        run_compose_test("mixed_pipeline")

    def test_hwm_inheritance(self):
        """Composed stream inherits highWaterMark from head and tail."""
        run_compose_test("hwm_inheritance")


class TestStreamOperators:
    """Verify stream operator functions: batch, scan, splitLines, flatMap, deduplicate."""

    def test_batch_full(self):
        """batch(3) with 6 items produces 2 full arrays."""
        run_compose_test("batch_full")

    def test_batch_partial_flush(self):
        """batch(3) with 5 items flushes partial batch on end."""
        run_compose_test("batch_partial_flush")

    def test_scan_accumulation(self):
        """scan(sum, 0) via composeStreams produces running totals."""
        run_compose_test("scan_accumulation")

    def test_split_lines_basic(self):
        """splitLines emits string lines in readableObjectMode."""
        run_compose_test("split_lines_basic")

    def test_split_lines_boundary(self):
        """splitLines assembles lines spanning chunk boundaries."""
        run_compose_test("split_lines_boundary")

    def test_composed_pipeline(self):
        """splitLines->batch(2)->scan integrated pipeline produces [2,4,5]."""
        run_compose_test("composed_pipeline")

    def test_flatmap_expand(self):
        """flatMap expands each item into multiple sequential outputs."""
        run_compose_test("flatmap_expand")

    def test_flatmap_ordering(self):
        """flatMap processes inputs sequentially, no interleaving."""
        run_compose_test("flatmap_ordering")

    def test_flatmap_error(self):
        """Error in flatMap async iterable propagates to stream."""
        run_compose_test("flatmap_error")

    def test_deduplicate_basic(self):
        """deduplicate removes duplicate objects within window."""
        run_compose_test("deduplicate_basic")

    def test_deduplicate_window(self):
        """deduplicate window eviction allows previously-seen keys to pass."""
        run_compose_test("deduplicate_window")

    def test_advanced_pipeline(self):
        """flatMap->batch through composeStreams produces correct batches."""
        run_compose_test("advanced_pipeline")
