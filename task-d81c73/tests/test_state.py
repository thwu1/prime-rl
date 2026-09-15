
import subprocess
import os
import pytest


def compile_harness(flags, output_name):
    """Compile the C++ test harness with given flags."""
    cmd = ['g++', '-std=c++17'] + flags + [
        '-I/app', '-pthread',
        '-o', f'/tmp/{output_name}',
        '/tests/test_harness.cpp'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result


def run_test_mode(binary, mode, timeout=60, env_extra=None):
    """Run the test harness binary with a specific test mode."""
    run_env = dict(os.environ)
    if env_extra:
        run_env.update(env_extra)
    result = subprocess.run(
        [binary, mode],
        capture_output=True, text=True,
        timeout=timeout, env=run_env
    )
    return result


@pytest.fixture(scope='module')
def normal_binary():
    """Compile with -O2 for correctness and performance tests."""
    result = compile_harness(['-O2', '-Wall'], 'test_normal')
    assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"
    return '/tmp/test_normal'


@pytest.fixture(scope='module')
def tsan_binary():
    """Compile with ThreadSanitizer for data race detection."""
    result = compile_harness(['-O1', '-g', '-fsanitize=thread'], 'test_tsan')
    assert result.returncode == 0, f"TSan compilation failed:\n{result.stderr}"
    return '/tmp/test_tsan'


def test_basic_pow2(normal_binary):
    """Push/pop correctness with power-of-2 capacities including wraparound."""
    r = run_test_mode(normal_binary, 'basic')
    assert r.returncode == 0, f"Basic pow2 test failed:\n{r.stdout}\n{r.stderr}"


def test_nonpow2_correctness(normal_binary):
    """Push/pop correctness with non-power-of-2 capacities and heavy wraparound."""
    r = run_test_mode(normal_binary, 'nonpow2')
    assert r.returncode == 0, f"Non-pow2 test failed:\n{r.stdout}\n{r.stderr}"


def test_concurrent_correctness(normal_binary):
    """500K items through concurrent producer/consumer with non-pow2 capacity."""
    r = run_test_mode(normal_binary, 'concurrent', timeout=120)
    assert r.returncode == 0, f"Concurrent test failed:\n{r.stdout}\n{r.stderr}"


def test_queue_no_data_races(tsan_binary):
    """ThreadSanitizer detects no data races in the queue under concurrent use."""
    r = run_test_mode(tsan_binary, 'concurrent_small', timeout=180,
                      env_extra={'TSAN_OPTIONS': 'halt_on_error=1'})
    assert r.returncode == 0, \
        f"ThreadSanitizer detected data races in queue:\n{r.stderr}"


def test_no_false_sharing(normal_binary):
    """head_ and tail_ must be on separate cache lines (struct size >= 128)."""
    r = run_test_mode(normal_binary, 'layout')
    assert r.returncode == 0, f"False sharing check failed:\n{r.stdout}\n{r.stderr}"


def test_batch_single_threaded(normal_binary):
    """Batch push/pop operations work correctly in single-threaded context."""
    r = run_test_mode(normal_binary, 'batch_basic')
    assert r.returncode == 0, f"Batch basic test failed:\n{r.stdout}\n{r.stderr}"


def test_batch_wraparound(normal_binary):
    """Batch operations correctly wrap around the ring buffer boundary."""
    r = run_test_mode(normal_binary, 'batch_wrap')
    assert r.returncode == 0, f"Batch wrap test failed:\n{r.stdout}\n{r.stderr}"


def test_batch_concurrent(normal_binary):
    """Batch push/pop operations work correctly under concurrency."""
    r = run_test_mode(normal_binary, 'batch_concurrent', timeout=120)
    assert r.returncode == 0, f"Batch concurrent test failed:\n{r.stdout}\n{r.stderr}"


def test_sampler_no_data_races(tsan_binary):
    """ThreadSanitizer detects no data races in the latency sampler."""
    r = run_test_mode(tsan_binary, 'sampler_concurrent', timeout=180,
                      env_extra={'TSAN_OPTIONS': 'halt_on_error=1'})
    assert r.returncode == 0, \
        f"ThreadSanitizer detected data races in sampler:\n{r.stderr}"
