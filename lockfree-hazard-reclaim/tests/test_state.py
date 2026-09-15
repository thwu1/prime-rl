
import subprocess
import os
import pytest

STACK_HEADER = "/app/lockfree_stack.hpp"
TEST_DIR = "/tests"
BUILD_DIR = "/tmp/test_build"


@pytest.fixture(autouse=True)
def setup_build_dir():
    os.makedirs(BUILD_DIR, exist_ok=True)


def compile_test(test_name, extra_flags=""):
    src = os.path.join(TEST_DIR, f"{test_name}.cpp")
    out = os.path.join(BUILD_DIR, test_name)
    cmd = f"g++ -std=c++20 -I/app -pthread {extra_flags} -o {out} {src}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"Compilation of {test_name} failed:\n{result.stderr}"
    return out


def run_binary(binary, timeout=120, env_extra=None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        binary, capture_output=True, text=True, timeout=timeout, env=env
    )
    return result


class TestCompilation:
    def test_compiles_cpp20(self):
        """The implementation must compile with C++20."""
        compile_test("test_basic")

    def test_compiles_optimized(self):
        """Must compile at -O2 without warnings-as-errors breaking things."""
        compile_test("test_basic", "-O2")


class TestBasicCorrectness:
    def test_push_pop_lifo(self):
        """Single-threaded push/pop with correct LIFO ordering."""
        binary = compile_test("test_basic")
        result = run_binary(binary)
        assert result.returncode == 0, f"Failed:\n{result.stdout}\n{result.stderr}"
        assert "BASIC_PUSH_POP_PASSED" in result.stdout

    def test_try_pop_empty(self):
        """try_pop on empty stack must return empty optional."""
        binary = compile_test("test_basic")
        result = run_binary(binary)
        assert result.returncode == 0, f"Failed:\n{result.stdout}\n{result.stderr}"
        assert "TRY_POP_EMPTY_PASSED" in result.stdout

    def test_try_pop_nonempty(self):
        """try_pop on non-empty stack returns the value."""
        binary = compile_test("test_basic")
        result = run_binary(binary)
        assert result.returncode == 0, f"Failed:\n{result.stdout}\n{result.stderr}"
        assert "TRY_POP_NONEMPTY_PASSED" in result.stdout

    def test_pop_empty_throws(self):
        """pop() on empty stack throws std::out_of_range."""
        binary = compile_test("test_basic")
        result = run_binary(binary)
        assert result.returncode == 0, f"Failed:\n{result.stdout}\n{result.stderr}"
        assert "POP_EMPTY_THROWS_PASSED" in result.stdout

    def test_large_sequential(self):
        """10K sequential push/pop operations."""
        binary = compile_test("test_basic")
        result = run_binary(binary)
        assert result.returncode == 0, f"Failed:\n{result.stdout}\n{result.stderr}"
        assert "LARGE_SEQUENTIAL_PASSED" in result.stdout

    def test_empty_method(self):
        """empty() reflects stack state."""
        binary = compile_test("test_basic")
        result = run_binary(binary)
        assert result.returncode == 0, f"Failed:\n{result.stdout}\n{result.stderr}"
        assert "EMPTY_METHOD_PASSED" in result.stdout


class TestConcurrency:
    def test_concurrent_value_accounting(self):
        """8-thread push/pop: all pushed values are popped exactly once."""
        binary = compile_test("test_concurrent", "-O2")
        result = run_binary(binary, timeout=120)
        assert result.returncode == 0, (
            f"Concurrent test failed:\n{result.stdout}\n{result.stderr}"
        )
        assert "CONCURRENT_TEST_PASSED" in result.stdout

    def test_stress_high_contention(self):
        """16 threads, 50K mixed push/pop ops each."""
        binary = compile_test("test_stress", "-O2")
        result = run_binary(binary, timeout=180)
        assert result.returncode == 0, (
            f"Stress test failed:\n{result.stdout}\n{result.stderr}"
        )
        assert "STRESS_TEST_PASSED" in result.stdout


class TestMemoryReclamation:
    def test_single_thread_no_leak(self):
        """Single-threaded: all nodes freed after stack destruction."""
        binary = compile_test("test_memory", "-O2")
        result = run_binary(binary, timeout=60)
        assert result.returncode == 0, (
            f"Memory test failed:\n{result.stdout}\n{result.stderr}"
        )
        assert "SINGLE_THREAD_MEMORY_PASSED" in result.stdout

    def test_multi_thread_no_leak(self):
        """Multi-threaded: all nodes freed after stack destruction."""
        binary = compile_test("test_memory", "-O2")
        result = run_binary(binary, timeout=120)
        assert result.returncode == 0, (
            f"Memory test failed:\n{result.stdout}\n{result.stderr}"
        )
        assert "MULTI_THREAD_MEMORY_PASSED" in result.stdout


class TestImplementationQuality:
    def test_uses_hazard_pointers(self):
        """Implementation must use hazard pointers for memory reclamation."""
        with open(STACK_HEADER) as f:
            code = f.read()
        code_lower = code.lower()
        has_hazard = (
            "hazard" in code_lower
            or "hp_" in code_lower
            or "hptr" in code_lower
        )
        assert has_hazard, (
            "Implementation must use hazard pointers for memory reclamation"
        )
        # Must not use the original no-reclamation approach
        assert "// KNOWN ISSUE" not in code, (
            "The original leaking implementation has not been modified"
        )

    def test_memory_ordering_optimized(self):
        """Must use acquire-release ordering, not all sequential consistency."""
        with open(STACK_HEADER) as f:
            code = f.read()
        has_relaxed_ordering = (
            "memory_order_acquire" in code
            or "memory_order_release" in code
            or "memory_order_acq_rel" in code
            or "memory_order_relaxed" in code
        )
        assert has_relaxed_ordering, (
            "Must optimize memory ordering — use acquire-release semantics "
            "where safe instead of default sequential consistency everywhere"
        )
