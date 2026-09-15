
import subprocess
import os
import tempfile
import pytest

COMPILE_CMD = ["g++", "-std=c++20", "-I", "/app/include", "-O2"]

COMMON_PREAMBLE = r"""
#include "coro/task.hpp"
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <coroutine>
"""

# Helper to drive a lazy task without needing sync_wait
RUN_TASK = r"""
template<typename T>
T run_task(coro::task<T> t) {
    auto h = t.handle();
    h.resume();
    return std::move(h.promise()).result();
}

inline void run_task(coro::task<void> t) {
    auto h = t.handle();
    h.resume();
    h.promise().result();
}
"""


def _compile_and_run(source: str, timeout: int = 30) -> tuple:
    """Compile source string with g++ and run. Returns (exit_code_or_str, stdout)."""
    fd, src = tempfile.mkstemp(suffix=".cpp", dir="/tmp")
    exe = src.replace(".cpp", "")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(source)
        comp = subprocess.run(
            COMPILE_CMD + ["-o", exe, src],
            capture_output=True, text=True, timeout=120,
        )
        if comp.returncode != 0:
            return ("compile_error", comp.stderr)
        run = subprocess.run(
            [exe], capture_output=True, text=True, timeout=timeout,
        )
        return (run.returncode, run.stdout.strip())
    except subprocess.TimeoutExpired:
        return ("timeout", "")
    finally:
        for p in (src, exe):
            try:
                os.unlink(p)
            except OSError:
                pass


# ═══════════════════════════════════════════════════════════════════════
# Task tests
# ═══════════════════════════════════════════════════════════════════════

def test_task_value_chain():
    """Values propagate correctly through nested co_await chains."""
    src = COMMON_PREAMBLE + RUN_TASK + r"""
coro::task<int> add(int a, int b) { co_return a + b; }

coro::task<int> chain() {
    int x = co_await add(1, 2);    // 3
    int y = co_await add(x, 10);   // 13
    int z = co_await add(y, 7);    // 20
    co_return z;
}

int main() {
    int result = run_task(chain());
    if (result == 20) { printf("PASS\n"); return 0; }
    printf("FAIL: %d\n", result);
    return 1;
}
"""
    rc, out = _compile_and_run(src)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"


def test_task_exception_propagation():
    """Exception type and message preserved through co_await relay."""
    src = COMMON_PREAMBLE + RUN_TASK + r"""
coro::task<int> thrower() {
    throw std::runtime_error("specific_error");
    co_return 0;
}

coro::task<int> relay() {
    co_return co_await thrower();
}

int main() {
    auto t = relay();
    auto h = t.handle();
    h.resume();
    try {
        std::move(h.promise()).result();
        printf("FAIL: no exception\n");
        return 1;
    } catch (const std::runtime_error& e) {
        if (std::string(e.what()) == "specific_error") {
            printf("PASS\n");
            return 0;
        }
        printf("FAIL: wrong msg: %s\n", e.what());
        return 1;
    } catch (const std::exception& e) {
        printf("FAIL: wrong type: %s\n", e.what());
        return 1;
    }
}
"""
    rc, out = _compile_and_run(src)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"


def test_task_exception_catch_in_coroutine():
    """A coroutine catches a specific exception from a co_awaited task."""
    src = COMMON_PREAMBLE + RUN_TASK + r"""
coro::task<int> thrower() {
    throw std::runtime_error("catch_me");
    co_return 0;
}

coro::task<int> catcher() {
    try {
        co_return co_await thrower();
    } catch (const std::runtime_error&) {
        co_return -1;
    }
}

int main() {
    int result = run_task(catcher());
    if (result == -1) { printf("PASS\n"); return 0; }
    printf("FAIL: %d\n", result);
    return 1;
}
"""
    rc, out = _compile_and_run(src)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"


def test_task_loop_no_overflow():
    """co_await in a 1M-iteration loop must not overflow the stack."""
    src = COMMON_PREAMBLE + RUN_TASK + r"""
coro::task<int> trivial() { co_return 42; }

coro::task<int> loop_test(int count) {
    int sum = 0;
    for (int i = 0; i < count; ++i) {
        sum += co_await trivial();
    }
    co_return sum;
}

int main() {
    int result = run_task(loop_test(1000000));
    if (result == 42000000) { printf("PASS\n"); return 0; }
    printf("FAIL: %d\n", result);
    return 1;
}
"""
    rc, out = _compile_and_run(src, timeout=60)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"


def test_task_deep_exception_chain():
    """Exception propagates correctly through a 5-level task chain."""
    src = COMMON_PREAMBLE + RUN_TASK + r"""
coro::task<int> bottom() {
    throw std::logic_error("deep_chain");
    co_return 0;
}

coro::task<int> level4() { co_return co_await bottom(); }
coro::task<int> level3() { co_return co_await level4(); }
coro::task<int> level2() { co_return co_await level3(); }
coro::task<int> level1() { co_return co_await level2(); }

int main() {
    try {
        run_task(level1());
        printf("FAIL: no exception\n");
        return 1;
    } catch (const std::logic_error& e) {
        if (std::string(e.what()) == "deep_chain") {
            printf("PASS\n");
            return 0;
        }
        printf("FAIL: wrong msg: %s\n", e.what());
        return 1;
    } catch (const std::exception& e) {
        printf("FAIL: wrong type: %s\n", e.what());
        return 1;
    }
}
"""
    rc, out = _compile_and_run(src)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"


# ═══════════════════════════════════════════════════════════════════════
# Generator tests
# ═══════════════════════════════════════════════════════════════════════

def test_generator_basic():
    """Generator yields values in correct order starting from begin()."""
    src = COMMON_PREAMBLE + r"""
#include "coro/generator.hpp"
#include <vector>

coro::generator<int> iota(int n) {
    for (int i = 0; i < n; ++i) {
        co_yield i;
    }
}

int main() {
    std::vector<int> v;
    for (int x : iota(5)) {
        v.push_back(x);
    }
    if (v.size() == 5 && v[0] == 0 && v[1] == 1 && v[2] == 2
        && v[3] == 3 && v[4] == 4) {
        printf("PASS\n");
        return 0;
    }
    printf("FAIL: size=%zu", v.size());
    for (int x : v) printf(" %d", x);
    printf("\n");
    return 1;
}
"""
    rc, out = _compile_and_run(src)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"


def test_generator_exception():
    """Exception from generator body propagates through the iterator."""
    src = COMMON_PREAMBLE + r"""
#include "coro/generator.hpp"

coro::generator<int> throwing_gen() {
    co_yield 1;
    co_yield 2;
    throw std::runtime_error("gen_error");
    co_yield 3;
}

int main() {
    auto g = throwing_gen();
    int count = 0;
    try {
        for (int x : g) {
            count++;
            (void)x;
            if (count > 10) { printf("FAIL: runaway\n"); return 1; }
        }
        printf("FAIL: no exception, count=%d\n", count);
        return 1;
    } catch (const std::runtime_error& e) {
        if (count == 2 && std::string(e.what()) == "gen_error") {
            printf("PASS\n");
            return 0;
        }
        printf("FAIL: count=%d msg=%s\n", count, e.what());
        return 1;
    }
}
"""
    rc, out = _compile_and_run(src)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"


def test_generator_early_destroy():
    """Destroying a generator mid-iteration must not crash or leak."""
    src = COMMON_PREAMBLE + r"""
#include "coro/generator.hpp"

coro::generator<int> infinite() {
    int i = 0;
    while (true) {
        co_yield i++;
    }
}

int main() {
    int sum = 0;
    {
        auto g = infinite();
        int count = 0;
        for (int x : g) {
            sum += x;
            if (++count == 10) break;
        }
    }  // generator destroyed here while coroutine is suspended at co_yield
    if (sum == 45) {
        printf("PASS\n");
        return 0;
    }
    printf("FAIL: %d\n", sum);
    return 1;
}
"""
    rc, out = _compile_and_run(src)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"


# ═══════════════════════════════════════════════════════════════════════
# sync_wait tests
# ═══════════════════════════════════════════════════════════════════════

def test_sync_wait_int():
    """sync_wait drives a task<int> to completion and returns the value."""
    src = COMMON_PREAMBLE + r"""
#include "coro/sync_wait.hpp"

coro::task<int> compute() {
    co_return 42;
}

coro::task<int> nested() {
    int a = co_await compute();
    co_return a * 2;
}

int main() {
    int r = coro::sync_wait(nested());
    if (r == 84) { printf("PASS\n"); return 0; }
    printf("FAIL: %d\n", r);
    return 1;
}
"""
    rc, out = _compile_and_run(src)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"


def test_sync_wait_void_exception():
    """sync_wait with void task propagates exceptions."""
    src = COMMON_PREAMBLE + r"""
#include "coro/sync_wait.hpp"

coro::task<void> ok_task() {
    co_return;
}

coro::task<void> throwing_task() {
    throw std::runtime_error("void_err");
    co_return;
}

int main() {
    coro::sync_wait(ok_task());

    try {
        coro::sync_wait(throwing_task());
        printf("FAIL: no exception\n");
        return 1;
    } catch (const std::runtime_error& e) {
        if (std::string(e.what()) == "void_err") {
            printf("PASS\n");
            return 0;
        }
        printf("FAIL: wrong msg\n");
        return 1;
    } catch (...) {
        printf("FAIL: wrong exception type\n");
        return 1;
    }
}
"""
    rc, out = _compile_and_run(src)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"


def test_sync_wait_loop():
    """sync_wait driving a loop of 1M co_awaits must not overflow."""
    src = COMMON_PREAMBLE + r"""
#include "coro/sync_wait.hpp"

coro::task<long long> unit() { co_return 1; }

coro::task<long long> big_loop(int n) {
    long long sum = 0;
    for (int i = 0; i < n; ++i) {
        sum += co_await unit();
    }
    co_return sum;
}

int main() {
    long long r = coro::sync_wait(big_loop(1000000));
    if (r == 1000000LL) { printf("PASS\n"); return 0; }
    printf("FAIL: %lld\n", r);
    return 1;
}
"""
    rc, out = _compile_and_run(src, timeout=60)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"


# ═══════════════════════════════════════════════════════════════════════
# when_all tests
# ═══════════════════════════════════════════════════════════════════════

def test_when_all_basic():
    """when_all composes heterogeneous tasks and returns a tuple of results."""
    src = COMMON_PREAMBLE + RUN_TASK + r"""
#include "coro/when_all.hpp"
#include <tuple>
#include <string>

coro::task<int> get_int() { co_return 42; }
coro::task<std::string> get_str() { co_return std::string("hello"); }

coro::task<bool> test() {
    auto [i, s] = co_await coro::when_all(get_int(), get_str());
    co_return i == 42 && s == "hello";
}

int main() {
    bool ok = run_task(test());
    if (ok) { printf("PASS\n"); return 0; }
    printf("FAIL\n");
    return 1;
}
"""
    rc, out = _compile_and_run(src)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"


def test_when_all_exception():
    """when_all propagates exception from a failing task."""
    src = COMMON_PREAMBLE + RUN_TASK + r"""
#include "coro/when_all.hpp"
#include <tuple>

coro::task<int> ok_task() { co_return 10; }
coro::task<int> failing_task() {
    throw std::runtime_error("when_all_err");
    co_return 0;
}

coro::task<int> test() {
    try {
        auto [a, b] = co_await coro::when_all(ok_task(), failing_task());
        (void)a; (void)b;
        co_return -1;  // should not reach
    } catch (const std::runtime_error& e) {
        if (std::string(e.what()) == "when_all_err") co_return 1;
        co_return -2;
    }
}

int main() {
    int r = run_task(test());
    if (r == 1) { printf("PASS\n"); return 0; }
    printf("FAIL: %d\n", r);
    return 1;
}
"""
    rc, out = _compile_and_run(src)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"


def test_when_all_three_tasks():
    """when_all handles three tasks with matching result types."""
    src = COMMON_PREAMBLE + RUN_TASK + r"""
#include "coro/when_all.hpp"
#include <tuple>

coro::task<int> f1() { co_return 10; }
coro::task<int> f2() { co_return 20; }
coro::task<int> f3() { co_return 30; }

coro::task<int> test() {
    auto [a, b, c] = co_await coro::when_all(f1(), f2(), f3());
    co_return a + b + c;
}

int main() {
    int r = run_task(test());
    if (r == 60) { printf("PASS\n"); return 0; }
    printf("FAIL: %d\n", r);
    return 1;
}
"""
    rc, out = _compile_and_run(src)
    assert rc == 0 and "PASS" in out, f"rc={rc} out={out}"
