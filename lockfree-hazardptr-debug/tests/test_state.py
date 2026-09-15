
import subprocess
import pytest
import os


def run(cmd, timeout=120, cwd="/app"):
    return subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        timeout=timeout, cwd=cwd
    )


class TestLockFreeStack:

    def test_compiles_without_errors(self):
        """The code must compile cleanly with g++ C++20"""
        r = run("g++ -std=c++20 -pthread -O1 -Wall -o /tmp/test_compile test_concurrent.cpp")
        assert r.returncode == 0, f"Compilation failed:\n{r.stderr}"

    def test_basic_single_thread(self):
        """Basic single-threaded LIFO correctness"""
        r = run("g++ -std=c++20 -pthread -O1 -o /tmp/test_basic test_concurrent.cpp")
        assert r.returncode == 0, f"Compilation failed:\n{r.stderr}"
        r = run("/tmp/test_basic", timeout=60)
        assert r.returncode == 0, f"Test crashed:\n{r.stderr}"
        assert "PASS: basic_correctness" in r.stdout

    def test_concurrent_correctness(self):
        """All pushed values must be retrievable without loss or duplication"""
        r = run("g++ -std=c++20 -pthread -O1 -o /tmp/test_cc test_concurrent.cpp")
        assert r.returncode == 0
        r = run("/tmp/test_cc", timeout=120)
        assert r.returncode == 0, f"Concurrent test failed:\n{r.stdout}\n{r.stderr}"
        assert "ALL_TESTS_PASSED" in r.stdout

    def test_address_sanitizer(self):
        """No use-after-free, double-free, or buffer overflow under ASAN"""
        r = run(
            "g++ -std=c++20 -pthread -O1 -fsanitize=address "
            "-fno-omit-frame-pointer -static-libasan "
            "-o /tmp/test_asan test_concurrent.cpp"
        )
        assert r.returncode == 0, f"ASAN compilation failed:\n{r.stderr}"
        r = run("ASAN_OPTIONS=detect_leaks=0 /tmp/test_asan", timeout=180)
        assert r.returncode == 0, f"ASAN detected errors:\n{r.stderr}"
        assert "ALL_TESTS_PASSED" in r.stdout

    def test_stress_repeated(self):
        """Run the stress test 3 times to catch intermittent race conditions"""
        r = run("g++ -std=c++20 -pthread -O2 -o /tmp/test_stress test_concurrent.cpp")
        assert r.returncode == 0
        for i in range(3):
            r = run("/tmp/test_stress", timeout=60)
            assert r.returncode == 0, f"Stress run {i} crashed:\n{r.stderr}"
            assert "ALL_TESTS_PASSED" in r.stdout, f"Stress run {i} failed:\n{r.stdout}"

    def test_memory_reclamation_header_exists(self):
        """memory_reclamation.hpp must exist with hazard pointer infrastructure"""
        assert os.path.exists("/app/memory_reclamation.hpp"), \
            "Must create /app/memory_reclamation.hpp with the hazard pointer system"
        with open("/app/memory_reclamation.hpp") as f:
            code = f.read()
        code_lower = code.lower()
        assert "atomic" in code, \
            "memory_reclamation.hpp must use std::atomic for lock-free operations"
        assert "retire" in code_lower, \
            "memory_reclamation.hpp must implement a retire list for deferred reclamation"

    def test_no_mutex_anywhere(self):
        """The implementation must be lock-free — no mutexes in stack or reclamation code"""
        for fname in ["/app/lockfree_stack.hpp", "/app/memory_reclamation.hpp"]:
            if os.path.exists(fname):
                with open(fname) as f:
                    code = f.read()
                assert "std::mutex" not in code, f"{fname} must not use std::mutex"
                assert "std::lock_guard" not in code, f"{fname} must not use std::lock_guard"
                assert "std::unique_lock" not in code, f"{fname} must not use std::unique_lock"
                assert "pthread_mutex" not in code, f"{fname} must not use pthread_mutex"

    def test_uses_explicit_memory_ordering(self):
        """Must use explicit memory ordering, not just sequential consistency defaults"""
        assert os.path.exists("/app/memory_reclamation.hpp"), \
            "Must create /app/memory_reclamation.hpp"
        all_code = ""
        for fname in ["/app/memory_reclamation.hpp", "/app/lockfree_stack.hpp"]:
            if os.path.exists(fname):
                with open(fname) as f:
                    all_code += f.read()
        has_explicit = (
            "memory_order_acquire" in all_code or
            "memory_order_release" in all_code or
            "memory_order_acq_rel" in all_code or
            "memory_order_relaxed" in all_code
        )
        assert has_explicit, \
            "Must use explicit memory ordering annotations (acquire/release/relaxed)"

    def test_integration_include(self):
        """lockfree_stack.hpp must include memory_reclamation.hpp"""
        with open("/app/lockfree_stack.hpp") as f:
            code = f.read()
        assert "memory_reclamation" in code, \
            "lockfree_stack.hpp must include memory_reclamation.hpp"

    def test_memory_reclamation_works(self):
        """Nodes must actually be reclaimed, not leaked indefinitely"""
        cpp_code = r'''
#include <cstdlib>
#include <cstdio>
#include <new>
#include <atomic>
#include <stdexcept>

static std::atomic<long> g_allocs{0};
static std::atomic<long> g_frees{0};

void* operator new(std::size_t sz) {
    g_allocs.fetch_add(1, std::memory_order_relaxed);
    void* p = std::malloc(sz);
    if (!p) throw std::bad_alloc();
    return p;
}

void operator delete(void* p) noexcept {
    if (p) { g_frees.fetch_add(1, std::memory_order_relaxed); std::free(p); }
}

void operator delete(void* p, std::size_t) noexcept {
    if (p) { g_frees.fetch_add(1, std::memory_order_relaxed); std::free(p); }
}

#include "/app/lockfree_stack.hpp"

int main() {
    long baseline_allocs = g_allocs.load();
    long baseline_frees = g_frees.load();

    {
        LockFreeStack<int> stack;
        const int N = 10000;
        for (int i = 0; i < N; ++i) stack.push(i);
        for (int i = 0; i < N; ++i) {
            try { stack.topAndPop(); } catch (...) { break; }
        }
    } // Stack destructor cleans up any remaining nodes on the stack

    long total_allocs = g_allocs.load() - baseline_allocs;
    long total_frees = g_frees.load() - baseline_frees;
    long leaked = total_allocs - total_frees;

    std::printf("allocs=%ld frees=%ld leaked=%ld\n", total_allocs, total_frees, leaked);

    // Without reclamation: ~10000 nodes leaked (one per pop, never freed)
    // With reclamation: most freed, maybe a few dozen in retire list residuals
    if (leaked > 500) {
        std::printf("RECLAMATION_FAIL: %ld outstanding allocations\n", leaked);
        return 1;
    }
    std::printf("RECLAMATION_PASS\n");
    return 0;
}
'''
        with open("/tmp/reclamation_test.cpp", "w") as f:
            f.write(cpp_code)
        r = run(
            "g++ -std=c++20 -pthread -O1 -o /tmp/reclamation_test /tmp/reclamation_test.cpp",
            cwd="/tmp"
        )
        assert r.returncode == 0, f"Reclamation test compilation failed:\n{r.stderr}"
        r = run("/tmp/reclamation_test", timeout=60, cwd="/tmp")
        assert r.returncode == 0, f"Memory reclamation verification failed:\n{r.stdout}\n{r.stderr}"
        assert "RECLAMATION_PASS" in r.stdout

    def test_embedded_concurrent_asan(self):
        """Independent embedded concurrent test with ASAN"""
        cpp_code = r'''
#include "/app/lockfree_stack.hpp"
#include <thread>
#include <vector>
#include <set>
#include <mutex>
#include <cassert>
#include <iostream>

int main() {
    // LIFO order
    {
        LockFreeStack<int> s;
        s.push(10); s.push(20); s.push(30);
        assert(s.topAndPop() == 30);
        assert(s.topAndPop() == 20);
        assert(s.topAndPop() == 10);
    }

    // Concurrent push then pop with full value integrity
    {
        LockFreeStack<int> s;
        constexpr int T = 4, N = 2000;
        std::vector<std::thread> threads;
        for (int t = 0; t < T; ++t)
            threads.emplace_back([&s, t]() {
                for (int i = 0; i < N; ++i) s.push(t * N + i);
            });
        for (auto& th : threads) th.join();
        threads.clear();

        std::mutex mtx;
        std::set<int> results;
        for (int t = 0; t < T; ++t)
            threads.emplace_back([&s, &results, &mtx]() {
                for (int i = 0; i < N; ++i) {
                    int v = s.topAndPop();
                    std::lock_guard<std::mutex> lk(mtx);
                    results.insert(v);
                }
            });
        for (auto& th : threads) th.join();

        assert((int)results.size() == T * N);
        for (int i = 0; i < T * N; ++i) assert(results.count(i) == 1);
    }

    std::cout << "EMBEDDED_PASS" << std::endl;
    return 0;
}
'''
        with open("/tmp/embedded_test.cpp", "w") as f:
            f.write(cpp_code)
        r = run(
            "g++ -std=c++20 -pthread -O1 -fsanitize=address "
            "-fno-omit-frame-pointer -static-libasan "
            "-o /tmp/embedded_test /tmp/embedded_test.cpp",
            cwd="/tmp",
        )
        assert r.returncode == 0, f"Embedded compilation failed:\n{r.stderr}"
        r = run("ASAN_OPTIONS=detect_leaks=0 /tmp/embedded_test", timeout=120, cwd="/tmp")
        assert r.returncode == 0, f"Embedded test failed:\n{r.stderr}"
        assert "EMBEDDED_PASS" in r.stdout
