
import subprocess
import re
import pytest


def compile_cpp(source_path, binary_path, extra_flags=None):
    """Compile a C++20 source file, return (success, stderr)."""
    cmd = ["g++", "-std=c++20", "-O2", "-pthread", "-o", binary_path, source_path]
    if extra_flags:
        cmd.extend(extra_flags)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.returncode == 0, result.stderr


def run_binary(binary_path, timeout=120):
    """Run a compiled binary, return (success, stdout+stderr)."""
    result = subprocess.run(
        [binary_path], capture_output=True, text=True, timeout=timeout
    )
    return result.returncode == 0, result.stdout + result.stderr


class TestSPSCQueue:
    def test_compilation(self):
        """SPSC queue header compiles with C++20."""
        src = "/tmp/test_compile_spsc.cpp"
        with open(src, "w") as f:
            f.write('#include "/app/spsc_queue.hpp"\n')
            f.write("int main() { SPSCQueue<int> q(10); return 0; }\n")
        ok, err = compile_cpp(src, "/tmp/test_compile_spsc")
        assert ok, f"Compilation failed:\n{err}"

    def test_capacity_and_fifo(self):
        """Queue capacity exact, FIFO ordering, wrap-around for many sizes."""
        ok, err = compile_cpp(
            "/tests/test_spsc_basic.cpp", "/tmp/test_spsc_basic"
        )
        assert ok, f"Compilation failed:\n{err}"
        ok, output = run_binary("/tmp/test_spsc_basic")
        assert ok, f"SPSC basic test failed:\n{output}"
        assert "PASS" in output, f"SPSC basic test did not pass:\n{output}"

    def test_concurrent_integrity(self):
        """Multi-threaded producer/consumer maintains sequential order."""
        ok, err = compile_cpp(
            "/tests/test_spsc_concurrent.cpp", "/tmp/test_spsc_concurrent"
        )
        assert ok, f"Compilation failed:\n{err}"
        ok, output = run_binary("/tmp/test_spsc_concurrent", timeout=180)
        assert ok, f"Concurrent test failed:\n{output}"
        assert "PASS" in output, f"Concurrent test did not pass:\n{output}"

    def test_memory_ordering_semantics(self):
        """Source uses acquire/release memory ordering (not all relaxed)."""
        with open("/app/spsc_queue.hpp", "r") as f:
            source = f.read()
        has_acquire = bool(
            re.search(r"memory_order[_:]+(acquire|acq_rel|seq_cst)", source)
        )
        has_release = bool(
            re.search(r"memory_order[_:]+(release|acq_rel|seq_cst)", source)
        )
        assert has_acquire, (
            "No acquire memory ordering found in spsc_queue.hpp. "
            "Cross-thread loads need acquire semantics."
        )
        assert has_release, (
            "No release memory ordering found in spsc_queue.hpp. "
            "Cross-thread stores need release semantics."
        )

    def test_false_sharing_mitigation(self):
        """Head and tail atomics are on separate cache lines."""
        src = "/tmp/test_sizeof_spsc.cpp"
        with open(src, "w") as f:
            f.write('#include "/app/spsc_queue.hpp"\n')
            f.write("#include <cstdio>\n")
            f.write(
                "int main() {"
                ' printf("%zu\\n", sizeof(SPSCQueue<int>));'
                " return 0; }\n"
            )
        ok, err = compile_cpp(src, "/tmp/test_sizeof_spsc")
        assert ok, f"sizeof probe compilation failed:\n{err}"
        ok, output = run_binary("/tmp/test_sizeof_spsc", timeout=10)
        assert ok, f"sizeof probe failed:\n{output}"
        size = int(output.strip())
        assert size >= 128, (
            f"sizeof(SPSCQueue<int>) = {size}. Expected >= 128 indicating "
            f"cache-line separation between producer and consumer variables."
        )

    def test_no_mutex_in_queue(self):
        """Lock-free queue must not use std::mutex or lock_guard."""
        with open("/app/spsc_queue.hpp", "r") as f:
            source = f.read()
        has_mutex = bool(
            re.search(
                r"std::mutex|std::lock_guard|std::unique_lock|std::scoped_lock",
                source,
            )
        )
        assert not has_mutex, (
            "spsc_queue.hpp uses mutex/lock_guard. "
            "Implementation must be lock-free using std::atomic."
        )


class TestFeedMerger:
    def test_compilation(self):
        """Feed merger header compiles with C++20."""
        src = "/tmp/test_compile_merger.cpp"
        with open(src, "w") as f:
            f.write('#include "/app/spsc_queue.hpp"\n')
            f.write('#include "/app/feed_merger.hpp"\n')
            f.write("struct X { int k; };\n")
            f.write("int main() {\n")
            f.write("  SPSCQueue<X> q(10);\n")
            f.write("  std::vector<SPSCQueue<X>*> v = {&q};\n")
            f.write("  auto kf = [](const X& x){ return x.k; };\n")
            f.write("  FeedMerger<X, decltype(kf)> m(v, kf);\n")
            f.write("  return 0;\n")
            f.write("}\n")
        ok, err = compile_cpp(src, "/tmp/test_compile_merger")
        assert ok, f"Compilation failed:\n{err}"

    def test_correctness(self):
        """Merger sorts, handles edge cases, preserves stability."""
        ok, err = compile_cpp(
            "/tests/test_merger_correctness.cpp", "/tmp/test_merger_correctness"
        )
        assert ok, f"Compilation failed:\n{err}"
        ok, output = run_binary("/tmp/test_merger_correctness", timeout=60)
        assert ok, f"Merger correctness test failed:\n{output}"
        assert "PASS" in output, (
            f"Merger correctness test did not pass:\n{output}"
        )

    def test_logarithmic_merge_structure(self):
        """Merger uses a tree-based structure for O(log K) merge."""
        with open("/app/feed_merger.hpp", "r") as f:
            source = f.read()
        # O(log K) merge requires a tree, heap, or priority queue — not
        # a linear scan of all sources on every merge step.
        indicators = [
            r"\btree\b",
            r"\bloser\b",
            r"\bwinner\b",
            r"\btournament\b",
            r"\bheap\b",
            r"priority_queue",
            r">>\s*1\b",
            r"/\s*2\b",
            r"\bparent\b",
        ]
        found = any(
            re.search(pat, source, re.IGNORECASE) for pat in indicators
        )
        assert found, (
            "feed_merger.hpp doesn't appear to use a tree-based merge. "
            "O(log K) per-element merge requires a tournament tree, loser "
            "tree, binary heap, or priority queue — not a linear scan."
        )


class TestIntegration:
    def test_trading_sim(self):
        """Full pipeline: SPSC queues + merger in trading simulation."""
        ok, err = compile_cpp(
            "/app/trading_sim.cpp",
            "/tmp/trading_sim",
            extra_flags=["-I/app"],
        )
        assert ok, f"Trading sim compilation failed:\n{err}"
        ok, output = run_binary("/tmp/trading_sim", timeout=60)
        assert ok, f"Trading sim failed:\n{output}"
        assert "PASS" in output, f"Trading sim did not pass:\n{output}"
