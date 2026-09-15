
import subprocess
import os
import json
import pytest


def test_compilation():
    """Queue and backoff headers should compile without errors."""
    result = subprocess.run(
        ["g++", "-std=c++17", "-O2", "-pthread",
         "-o", "/tmp/stress_test", "/app/stress_test.cpp"],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"Compilation failed:\n{result.stderr}"


def test_correctness():
    """All enqueued items must be dequeued exactly once with correct values."""
    build = subprocess.run(
        ["g++", "-std=c++17", "-O2", "-pthread",
         "-o", "/tmp/stress_test_corr", "/app/stress_test.cpp"],
        capture_output=True, text=True, timeout=60
    )
    assert build.returncode == 0, f"Build failed:\n{build.stderr}"

    try:
        result = subprocess.run(
            ["/tmp/stress_test_corr"],
            capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Stress test timed out (possible deadlock or livelock)")

    assert "CORRECTNESS: PASS" in result.stdout, (
        f"Correctness test failed.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert result.returncode == 0


def test_tsan_clean():
    """No ThreadSanitizer errors when running with TSan instrumentation."""
    build = subprocess.run(
        ["g++", "-std=c++17", "-O1", "-g", "-fsanitize=thread", "-pthread",
         "-DITEMS_PER_PRODUCER=2000",
         "-o", "/tmp/stress_test_tsan", "/app/stress_test.cpp"],
        capture_output=True, text=True, timeout=60
    )
    assert build.returncode == 0, f"TSan build failed:\n{build.stderr}"

    env = os.environ.copy()
    env["TSAN_OPTIONS"] = "halt_on_error=1"

    try:
        result = subprocess.run(
            ["/tmp/stress_test_tsan"],
            capture_output=True, text=True, timeout=180,
            env=env
        )
    except subprocess.TimeoutExpired:
        pytest.fail("TSan stress test timed out")

    assert "ThreadSanitizer" not in result.stderr, (
        f"TSan detected data races:\n{result.stderr}"
    )
    assert result.returncode == 0, (
        f"TSan test failed (exit code {result.returncode}):\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_struct_layout():
    """Queue struct must use cache-line padding to avoid false sharing."""
    layout_src = "/tmp/layout_check.cpp"
    with open(layout_src, "w") as f:
        f.write(
            '#include "mpmc_queue.h"\n'
            '#include <cstdio>\n'
            'int main() {\n'
            '    size_t sz = sizeof(mpmc_bounded_queue<int>);\n'
            '    printf("sizeof(mpmc_bounded_queue<int>) = %zu\\n", sz);\n'
            '    if (sz < 192) {\n'
            '        printf("FAIL: struct too small (%zu bytes), "\n'
            '               "likely missing cache-line padding\\n", sz);\n'
            '        return 1;\n'
            '    }\n'
            '    printf("PASS: adequate padding (%zu bytes)\\n", sz);\n'
            '    return 0;\n'
            '}\n'
        )

    build = subprocess.run(
        ["g++", "-std=c++17", "-I/app", "-o", "/tmp/layout_check", layout_src],
        capture_output=True, text=True, timeout=30
    )
    assert build.returncode == 0, f"Layout check build failed:\n{build.stderr}"

    result = subprocess.run(
        ["/tmp/layout_check"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, (
        f"Cache-line padding check failed:\n{result.stdout}"
    )


def test_bulk_operations():
    """Bulk enqueue/dequeue must work correctly in single and multi-threaded use."""
    bulk_src = "/tmp/bulk_test.cpp"
    with open(bulk_src, "w") as f:
        f.write(
            '#include "mpmc_queue.h"\n'
            '#include <cstdio>\n'
            '#include <cassert>\n'
            '#include <thread>\n'
            '#include <vector>\n'
            '#include <atomic>\n'
            '\n'
            'int main() {\n'
            '    // Test 1: Single-threaded bulk enqueue and dequeue\n'
            '    {\n'
            '        mpmc_bounded_queue<int> q(256);\n'
            '        int items[10] = {0,1,2,3,4,5,6,7,8,9};\n'
            '        size_t enqueued = q.try_enqueue_bulk(items, 10);\n'
            '        assert(enqueued > 0 && enqueued <= 10);\n'
            '        printf("ST bulk enqueued: %zu\\n", enqueued);\n'
            '\n'
            '        int out[10] = {};\n'
            '        size_t dequeued = q.try_dequeue_bulk(out, enqueued);\n'
            '        assert(dequeued == enqueued);\n'
            '        for (size_t i = 0; i < dequeued; i++)\n'
            '            assert(out[i] == (int)i);\n'
            '        printf("ST bulk dequeue verified: %zu items\\n", dequeued);\n'
            '\n'
            '        // Bulk enqueue exceeding capacity\n'
            '        int big[512];\n'
            '        for (int i = 0; i < 512; i++) big[i] = i;\n'
            '        enqueued = q.try_enqueue_bulk(big, 512);\n'
            '        assert(enqueued <= 256);\n'
            '\n'
            '        int drain[256];\n'
            '        size_t total_drained = 0;\n'
            '        while (total_drained < enqueued) {\n'
            '            size_t n = q.try_dequeue_bulk(drain, 256);\n'
            '            total_drained += n;\n'
            '        }\n'
            '\n'
            '        // Bulk dequeue from empty queue\n'
            '        dequeued = q.try_dequeue_bulk(drain, 10);\n'
            '        assert(dequeued == 0);\n'
            '    }\n'
            '\n'
            '    // Test 2: Multi-threaded bulk operations\n'
            '    {\n'
            '        mpmc_bounded_queue<int> q(1024);\n'
            '        const int BATCH = 16;\n'
            '        const int ROUNDS = 250;\n'
            '        const int P = 2;\n'
            '        std::atomic<bool> start{false};\n'
            '        std::atomic<bool> stop{false};\n'
            '        std::atomic<int> total_dequeued{0};\n'
            '\n'
            '        std::vector<std::thread> producers;\n'
            '        for (int t = 0; t < P; t++) {\n'
            '            producers.emplace_back([&, t]() {\n'
            '                while (!start.load(std::memory_order_acquire))\n'
            '                    std::this_thread::yield();\n'
            '                int batch[BATCH];\n'
            '                for (int round = 0; round < ROUNDS; round++) {\n'
            '                    for (int i = 0; i < BATCH; i++)\n'
            '                        batch[i] = t * 1000000 + round * BATCH + i;\n'
            '                    size_t remaining = BATCH;\n'
            '                    size_t offset = 0;\n'
            '                    while (remaining > 0) {\n'
            '                        size_t n = q.try_enqueue_bulk(\n'
            '                            batch + offset, remaining);\n'
            '                        offset += n;\n'
            '                        remaining -= n;\n'
            '                        if (remaining > 0)\n'
            '                            std::this_thread::yield();\n'
            '                    }\n'
            '                }\n'
            '            });\n'
            '        }\n'
            '\n'
            '        std::vector<std::thread> consumers;\n'
            '        for (int t = 0; t < P; t++) {\n'
            '            consumers.emplace_back([&]() {\n'
            '                while (!start.load(std::memory_order_acquire))\n'
            '                    std::this_thread::yield();\n'
            '                int batch[BATCH];\n'
            '                while (true) {\n'
            '                    size_t n = q.try_dequeue_bulk(batch, BATCH);\n'
            '                    total_dequeued.fetch_add(n);\n'
            '                    if (n == 0) {\n'
            '                        if (stop.load(std::memory_order_acquire)) {\n'
            '                            while ((n = q.try_dequeue_bulk(\n'
            '                                       batch, BATCH)) > 0)\n'
            '                                total_dequeued.fetch_add(n);\n'
            '                            break;\n'
            '                        }\n'
            '                        std::this_thread::yield();\n'
            '                    }\n'
            '                }\n'
            '            });\n'
            '        }\n'
            '\n'
            '        start.store(true, std::memory_order_release);\n'
            '        for (auto& t : producers) t.join();\n'
            '        stop.store(true, std::memory_order_release);\n'
            '        for (auto& t : consumers) t.join();\n'
            '\n'
            '        int expected = P * ROUNDS * BATCH;\n'
            '        int got = total_dequeued.load();\n'
            '        printf("MT bulk: expected=%d got=%d\\n", expected, got);\n'
            '        assert(got == expected);\n'
            '    }\n'
            '\n'
            '    printf("BULK: PASS\\n");\n'
            '    return 0;\n'
            '}\n'
        )

    build = subprocess.run(
        ["g++", "-std=c++17", "-O2", "-pthread", "-I/app",
         "-o", "/tmp/bulk_test", bulk_src],
        capture_output=True, text=True, timeout=60
    )
    assert build.returncode == 0, f"Bulk test build failed:\n{build.stderr}"

    try:
        result = subprocess.run(
            ["/tmp/bulk_test"],
            capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Bulk test timed out (possible deadlock)")

    assert "BULK: PASS" in result.stdout, (
        f"Bulk test failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.returncode == 0


def test_backoff_integration():
    """Adaptive backoff must be implemented and integrated into the queue."""
    with open("/app/backoff.h") as f:
        backoff_src = f.read()

    assert "yield" in backoff_src.lower() or "sched_yield" in backoff_src, (
        "backoff.h must escalate to yielding under contention"
    )

    with open("/app/mpmc_queue.h") as f:
        queue_src = f.read()

    assert ".backoff()" in queue_src, (
        "mpmc_queue.h must call adaptive_backoff::backoff() in retry loops"
    )

    # Verify backoff compiles and runs
    test_src = "/tmp/backoff_test.cpp"
    with open(test_src, "w") as f:
        f.write(
            '#include "backoff.h"\n'
            '#include <cstdio>\n'
            'int main() {\n'
            '    adaptive_backoff bo;\n'
            '    for (int i = 0; i < 100; i++) bo.backoff();\n'
            '    bo.reset();\n'
            '    bo.backoff();\n'
            '    printf("BACKOFF: PASS\\n");\n'
            '    return 0;\n'
            '}\n'
        )

    build = subprocess.run(
        ["g++", "-std=c++17", "-O2", "-I/app", "-o", "/tmp/backoff_test", test_src],
        capture_output=True, text=True, timeout=30
    )
    assert build.returncode == 0, f"Backoff test build failed:\n{build.stderr}"

    result = subprocess.run(
        ["/tmp/backoff_test"],
        capture_output=True, text=True, timeout=10
    )
    assert "BACKOFF: PASS" in result.stdout, (
        f"Backoff test failed:\n{result.stdout}\n{result.stderr}"
    )


def test_ordering_analysis():
    """Analysis file must be well-formed with valid memory ordering evaluations."""
    analysis_path = "/app/ordering_analysis.json"
    assert os.path.exists(analysis_path), (
        "ordering_analysis.json not found at /app/ordering_analysis.json"
    )

    with open(analysis_path) as f:
        data = json.load(f)

    assert "operations" in data, "Missing 'operations' key"
    ops = data["operations"]
    assert isinstance(ops, list), "'operations' must be a list"
    assert len(ops) >= 6, f"Expected >= 6 operations, got {len(ops)}"

    valid_orderings = {
        "memory_order_relaxed", "memory_order_acquire", "memory_order_release",
        "memory_order_acq_rel", "memory_order_seq_cst",
        "relaxed", "acquire", "release", "acq_rel", "seq_cst",
        "std::memory_order_relaxed", "std::memory_order_acquire",
        "std::memory_order_release", "std::memory_order_acq_rel",
        "std::memory_order_seq_cst",
    }

    required_keys = {
        "location", "variable", "operation", "ordering",
        "justification", "weaker_ordering_bug"
    }

    locations = set()
    orderings_used = set()

    for i, op in enumerate(ops):
        for key in required_keys:
            assert key in op, f"Operation {i} missing key '{key}'"

        ordering = op["ordering"].replace("std::", "")
        assert ordering in valid_orderings, (
            f"Invalid ordering '{op['ordering']}' in operation {i}"
        )

        locations.add(op["location"].lower())
        orderings_used.add(ordering)

        assert len(op["justification"]) >= 20, (
            f"Justification too short for operation {i}"
        )
        assert len(op["weaker_ordering_bug"]) >= 20, (
            f"Bug description too short for operation {i}"
        )

    assert any("enqueue" in loc for loc in locations), (
        "No enqueue operations in analysis"
    )
    assert any("dequeue" in loc for loc in locations), (
        "No dequeue operations in analysis"
    )

    normalized = set()
    for o in orderings_used:
        normalized.add(o.replace("memory_order_", ""))
    assert "acquire" in normalized, "No acquire ordering found in analysis"
    assert "release" in normalized, "No release ordering found in analysis"


def test_high_contention():
    """Queue must work correctly with a tiny 4-slot buffer under high contention."""
    hc_src = "/tmp/high_contention_test.cpp"
    with open(hc_src, "w") as f:
        f.write(
            '#include "mpmc_queue.h"\n'
            '#include <thread>\n'
            '#include <vector>\n'
            '#include <atomic>\n'
            '#include <cstdio>\n'
            '\n'
            'int main() {\n'
            '    mpmc_bounded_queue<int> q(4);\n'
            '    const int N = 5000;\n'
            '    const int P = 4;\n'
            '\n'
            '    std::atomic<bool> start{false};\n'
            '    std::atomic<bool> stop{false};\n'
            '    std::atomic<int> consumed_total{0};\n'
            '\n'
            '    std::vector<std::thread> producers;\n'
            '    for (int t = 0; t < P; t++) {\n'
            '        producers.emplace_back([&, t]() {\n'
            '            while (!start.load(std::memory_order_acquire))\n'
            '                std::this_thread::yield();\n'
            '            for (int i = 0; i < N; i++) {\n'
            '                int val = t * N + i;\n'
            '                while (!q.enqueue(val))\n'
            '                    std::this_thread::yield();\n'
            '            }\n'
            '        });\n'
            '    }\n'
            '\n'
            '    std::vector<std::thread> consumers;\n'
            '    for (int t = 0; t < P; t++) {\n'
            '        consumers.emplace_back([&]() {\n'
            '            while (!start.load(std::memory_order_acquire))\n'
            '                std::this_thread::yield();\n'
            '            while (true) {\n'
            '                int val;\n'
            '                if (q.dequeue(val)) {\n'
            '                    consumed_total.fetch_add(1);\n'
            '                } else if (stop.load(std::memory_order_acquire)) {\n'
            '                    while (q.dequeue(val))\n'
            '                        consumed_total.fetch_add(1);\n'
            '                    break;\n'
            '                } else {\n'
            '                    std::this_thread::yield();\n'
            '                }\n'
            '            }\n'
            '        });\n'
            '    }\n'
            '\n'
            '    start.store(true, std::memory_order_release);\n'
            '    for (auto& t : producers) t.join();\n'
            '    stop.store(true, std::memory_order_release);\n'
            '    for (auto& t : consumers) t.join();\n'
            '\n'
            '    int expected = P * N;\n'
            '    int got = consumed_total.load();\n'
            '    printf("High contention: expected=%d got=%d\\n", expected, got);\n'
            '    if (got == expected) {\n'
            '        printf("CONTENTION: PASS\\n");\n'
            '    } else {\n'
            '        printf("CONTENTION: FAIL\\n");\n'
            '    }\n'
            '    return (got == expected) ? 0 : 1;\n'
            '}\n'
        )

    build = subprocess.run(
        ["g++", "-std=c++17", "-O2", "-pthread", "-I/app",
         "-o", "/tmp/hc_test", hc_src],
        capture_output=True, text=True, timeout=60
    )
    assert build.returncode == 0, f"High contention build failed:\n{build.stderr}"

    try:
        result = subprocess.run(
            ["/tmp/hc_test"],
            capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        pytest.fail("High contention test timed out")

    assert "CONTENTION: PASS" in result.stdout, (
        f"High contention test failed:\n{result.stdout}\n{result.stderr}"
    )
    assert result.returncode == 0
