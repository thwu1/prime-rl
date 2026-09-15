import json
import os
import subprocess



def _ensure_test_results():
    """Run the TypeScript marble tests if results don't exist yet."""
    result_file = '/app/test-results.json'
    if not os.path.exists(result_file):
        subprocess.run(
            ['bash', '-c', 'cd /app && npm install --quiet 2>/dev/null && npx tsx test/run-tests.ts'],
            capture_output=True,
            timeout=120,
        )
    return result_file


def test_results_file_exists():
    """Test results JSON must be produced by the marble test runner."""
    result_file = _ensure_test_results()
    assert os.path.exists(result_file), (
        "test-results.json not found. "
        "Run: cd /app && npm install && npx tsx test/run-tests.ts"
    )


def test_basic_interval_buffering():
    """Buffers emitted at regular intervals with remaining flush on complete."""
    _check_test('should emit buffers at intervals')


def test_overlapping_creation_interval():
    """Overlapping buffers via creationInterval; values in multiple buffers."""
    _check_test('should handle overlapping buffers with creation interval')


def test_max_buffer_size_early_emission():
    """Buffer emits early when maxBufferSize is reached."""
    _check_test('should emit buffers at intervals or when buffer is full')


def test_error_propagation():
    """Source error is forwarded; buffers are discarded."""
    _check_test('should forward source errors and discard buffers')


def test_empty_source():
    """Empty source emits an empty buffer array then completes."""
    _check_test('should handle empty source')


def test_combined_interval_and_maxsize():
    """Overlapping buffers with maxBufferSize interact correctly."""
    _check_test('should combine creation interval with maxBufferSize')


def test_completion_flush():
    """Source completing before timer flushes remaining buffer."""
    _check_test('should flush remaining buffer on source completion')


def test_early_unsubscription():
    """Unsubscription cleans up source subscription and timers."""
    _check_test('should clean up on early unsubscription')


def test_no_rxjs_operators_import():
    """Implementation must not import the real bufferTime from rxjs."""
    source_file = '/app/src/bufferTime.ts'
    assert os.path.exists(source_file), "Source file /app/src/bufferTime.ts not found"

    with open(source_file) as f:
        content = f.read()

    assert 'rxjs/operators' not in content, (
        "Implementation must not import from rxjs/operators"
    )
    assert 'rxjs/internal' not in content, (
        "Implementation must not import from rxjs/internal"
    )


# ---- helpers ----------------------------------------------------------------

def _check_test(test_name: str):
    result_file = _ensure_test_results()
    with open(result_file) as f:
        results = json.load(f)

    matching = [r for r in results if r['name'] == test_name]
    assert len(matching) == 1, f"Test '{test_name}' not found in results"
    r = matching[0]
    assert r['passed'], f"Test '{test_name}' failed: {r.get('error', 'unknown')}"
