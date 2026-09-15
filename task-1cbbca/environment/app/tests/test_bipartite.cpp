
#include "bipartite_buf.hpp"

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <thread>
#include <utility>

static int g_failures = 0;
static int g_passes = 0;

#define TEST_CHECK(cond, name)                                       \
    do {                                                             \
        if (!(cond)) {                                               \
            std::printf("FAIL: %s (line %d)\n", (name), __LINE__);  \
            g_failures++;                                            \
        } else {                                                     \
            std::printf("PASS: %s\n", (name));                      \
            g_passes++;                                              \
        }                                                            \
    } while (0)

// ---------------------------------------------------------------------------
// Test 1 -- Sanity: basic single-threaded push / pop
// ---------------------------------------------------------------------------
static void test_basic() {
    BipartiteBuf<int, 32> buf;

    int* wp = buf.WriteAcquire(5);
    TEST_CHECK(wp != nullptr, "basic_write_acquire");
    if (!wp) return;

    for (int i = 0; i < 5; i++) wp[i] = (i + 1) * 10;
    buf.WriteRelease(5);

    auto result = buf.ReadAcquire();
    TEST_CHECK(result.first != nullptr, "basic_read_acquire");
    TEST_CHECK(result.second == 5, "basic_read_count");
    if (result.first) {
        bool ok = true;
        for (int i = 0; i < 5; i++) {
            if (result.first[i] != (i + 1) * 10) ok = false;
        }
        TEST_CHECK(ok, "basic_read_data");
    }
    buf.ReadRelease(result.second);

    auto empty = buf.ReadAcquire();
    TEST_CHECK(empty.first == nullptr && empty.second == 0,
               "basic_empty_after_drain");
}

// ---------------------------------------------------------------------------
// Test 2 -- Capacity: must not fill all N slots from empty (full == empty)
// ---------------------------------------------------------------------------
static void test_capacity() {
    constexpr size_t SZ = 8;
    BipartiteBuf<int, SZ> buf;

    // Writing exactly SZ elements from empty should be rejected, because
    // write_idx would advance to N which is congruent to read_idx == 0.
    int* wp = buf.WriteAcquire(SZ);
    TEST_CHECK(wp == nullptr, "capacity_reject_full");

    // SZ-1 should succeed.
    wp = buf.WriteAcquire(SZ - 1);
    TEST_CHECK(wp != nullptr, "capacity_accept_max");
    if (wp) {
        for (size_t i = 0; i < SZ - 1; i++) wp[i] = static_cast<int>(i + 1);
        buf.WriteRelease(SZ - 1);
    }

    auto result = buf.ReadAcquire();
    TEST_CHECK(result.first != nullptr, "capacity_read_nonempty");
    TEST_CHECK(result.second == SZ - 1, "capacity_read_count");
    if (result.first) {
        bool ok = true;
        for (size_t i = 0; i < result.second; i++) {
            if (result.first[i] != static_cast<int>(i + 1)) ok = false;
        }
        TEST_CHECK(ok, "capacity_read_data");
    }
    buf.ReadRelease(result.second);
}

// ---------------------------------------------------------------------------
// Test 3 -- Wrap-around write: data written at position 0 after wrapping
//           must be readable with correct values.
// ---------------------------------------------------------------------------
static void test_wrap_write() {
    BipartiteBuf<int, 16> buf;

    // Phase 1: advance both indices to position 12.
    int* wp = buf.WriteAcquire(12);
    TEST_CHECK(wp != nullptr, "wrap_phase1_write");
    if (!wp) return;
    for (int i = 0; i < 12; i++) wp[i] = i;
    buf.WriteRelease(12);

    auto r1 = buf.ReadAcquire();
    TEST_CHECK(r1.second == 12, "wrap_phase1_read_count");
    buf.ReadRelease(12);   // write_idx == read_idx == 12

    // Phase 2: write 10 elements -- tail space is only 4, so the buffer
    //          must wrap to position 0.
    wp = buf.WriteAcquire(10);
    TEST_CHECK(wp != nullptr, "wrap_phase2_write");
    if (!wp) return;
    for (int i = 0; i < 10; i++) wp[i] = 100 + i;
    buf.WriteRelease(10);

    // Read back and verify the 10 elements.
    auto r2 = buf.ReadAcquire();
    TEST_CHECK(r2.first != nullptr, "wrap_phase2_read");
    TEST_CHECK(r2.second == 10, "wrap_phase2_read_count");
    if (r2.first) {
        bool ok = true;
        for (size_t i = 0; i < r2.second && i < 10; i++) {
            if (r2.first[i] != 100 + static_cast<int>(i)) ok = false;
        }
        TEST_CHECK(ok, "wrap_phase2_read_data");
    }
    buf.ReadRelease(r2.second);
}

// ---------------------------------------------------------------------------
// Test 4 -- Invalidation boundary: after a wrap write, the reader must
//           first see the pre-invalidation data, then the post-wrap data.
// ---------------------------------------------------------------------------
static void test_invalidation_read() {
    BipartiteBuf<int, 16> buf;

    // Write 12 elements, read only 8 -> read_idx=8, write_idx=12.
    int* wp = buf.WriteAcquire(12);
    if (!wp) { TEST_CHECK(false, "inv_setup_write"); return; }
    for (int i = 0; i < 12; i++) wp[i] = i;
    buf.WriteRelease(12);

    auto r1 = buf.ReadAcquire();
    TEST_CHECK(r1.second == 12, "inv_setup_read_count");
    buf.ReadRelease(8);   // read_idx == 8, write_idx == 12

    // Write 7 elements that must wrap to [0..7).
    // Tail space = 16-12 = 4 (too small).  Head space = 8-1 = 7 (fits).
    wp = buf.WriteAcquire(7);
    TEST_CHECK(wp != nullptr, "inv_wrap_write");
    if (!wp) return;
    for (int i = 0; i < 7; i++) wp[i] = 200 + i;
    buf.WriteRelease(7);
    // Expected state: write_idx=7, invalidate_idx=12

    // --- Pre-invalidation read: elements 8..11 (values 8,9,10,11) ---
    auto r2 = buf.ReadAcquire();
    TEST_CHECK(r2.first != nullptr, "inv_pre_boundary_read");
    TEST_CHECK(r2.second == 4, "inv_pre_boundary_count");
    if (r2.first) {
        bool ok = true;
        for (size_t i = 0; i < r2.second && i < 4; i++) {
            if (r2.first[i] != 8 + static_cast<int>(i)) ok = false;
        }
        TEST_CHECK(ok, "inv_pre_boundary_data");
    }
    buf.ReadRelease(r2.second);
    // After releasing 4 elements, read_idx should reach the invalidation
    // boundary at 12 and wrap to 0.

    // --- Post-invalidation read: elements 0..6 (values 200..206) ---
    auto r3 = buf.ReadAcquire();
    TEST_CHECK(r3.first != nullptr, "inv_post_boundary_read");
    TEST_CHECK(r3.second == 7, "inv_post_boundary_count");
    if (r3.first) {
        bool ok = true;
        for (size_t i = 0; i < r3.second && i < 7; i++) {
            if (r3.first[i] != 200 + static_cast<int>(i)) ok = false;
        }
        TEST_CHECK(ok, "inv_post_boundary_data");
    }
    buf.ReadRelease(r3.second);
}

// ---------------------------------------------------------------------------
// Test 5 -- Single-threaded stress: sequential counter through many cycles
// ---------------------------------------------------------------------------
static void test_stress() {
    constexpr size_t BUF_SIZE = 64;
    BipartiteBuf<uint32_t, BUF_SIZE> buf;
    uint32_t write_seq = 0;
    uint32_t read_seq = 0;
    bool data_ok = true;

    for (int cycle = 0; cycle < 5000 && data_ok; cycle++) {
        size_t batch = static_cast<size_t>((cycle % 13) + 1);
        if (batch >= BUF_SIZE) batch = BUF_SIZE - 1;

        uint32_t* wp = buf.WriteAcquire(batch);
        if (wp) {
            for (size_t i = 0; i < batch; i++) wp[i] = write_seq++;
            buf.WriteRelease(batch);
        }

        auto [rp, rn] = buf.ReadAcquire();
        if (rp && rn > 0) {
            for (size_t i = 0; i < rn; i++) {
                if (rp[i] != read_seq) {
                    std::printf("FAIL: stress_data_integrity "
                                "at read_seq=%u got=%u cycle=%d\n",
                                read_seq, rp[i], cycle);
                    data_ok = false;
                    g_failures++;
                    break;
                }
                read_seq++;
            }
            buf.ReadRelease(rn);
        }
    }

    // Drain remaining elements.
    int drain_limit = 100000;
    while (data_ok && drain_limit-- > 0) {
        auto [rp, rn] = buf.ReadAcquire();
        if (!rp || rn == 0) break;
        for (size_t i = 0; i < rn; i++) {
            if (rp[i] != read_seq) {
                std::printf("FAIL: stress_drain at read_seq=%u got=%u\n",
                            read_seq, rp[i]);
                data_ok = false;
                g_failures++;
                break;
            }
            read_seq++;
        }
        buf.ReadRelease(rn);
    }

    if (data_ok) {
        TEST_CHECK(write_seq == read_seq, "stress_complete_transfer");
        std::printf("  (transferred %u elements through %zu-slot buffer)\n",
                    read_seq, BUF_SIZE);
    }
}

// ---------------------------------------------------------------------------
// Test 6 -- Concurrent: producer and consumer in separate threads
// ---------------------------------------------------------------------------
static void test_concurrent() {
    constexpr size_t BUF_SIZE = 256;
    constexpr uint32_t TOTAL = 100000;
    BipartiteBuf<uint32_t, BUF_SIZE> buf;
    std::atomic<bool> error_flag{false};

    auto start_time = std::chrono::steady_clock::now();

    std::thread producer([&]() {
        uint32_t seq = 0;
        while (seq < TOTAL && !error_flag.load(std::memory_order_relaxed)) {
            auto now = std::chrono::steady_clock::now();
            if (now - start_time > std::chrono::seconds(30)) {
                std::printf("FAIL: concurrent_timeout (producer stuck at %u)\n",
                            seq);
                error_flag.store(true);
                return;
            }
            size_t batch = static_cast<size_t>((seq % 17) + 1);
            if (batch > TOTAL - seq) batch = TOTAL - seq;
            if (batch >= BUF_SIZE) batch = BUF_SIZE - 1;

            uint32_t* wp = buf.WriteAcquire(batch);
            if (wp) {
                for (size_t i = 0; i < batch; i++) wp[i] = seq++;
                buf.WriteRelease(batch);
            }
        }
    });

    std::thread consumer([&]() {
        uint32_t expected = 0;
        while (expected < TOTAL &&
               !error_flag.load(std::memory_order_relaxed)) {
            auto now = std::chrono::steady_clock::now();
            if (now - start_time > std::chrono::seconds(30)) {
                std::printf("FAIL: concurrent_timeout "
                            "(consumer stuck at %u)\n", expected);
                error_flag.store(true);
                return;
            }
            auto [rp, rn] = buf.ReadAcquire();
            if (rp && rn > 0) {
                for (size_t i = 0; i < rn; i++) {
                    if (rp[i] != expected) {
                        std::printf("FAIL: concurrent_data "
                                    "at seq %u got %u\n",
                                    expected, rp[i]);
                        error_flag.store(true);
                        buf.ReadRelease(rn);
                        return;
                    }
                    expected++;
                }
                buf.ReadRelease(rn);
            }
        }
    });

    producer.join();
    consumer.join();

    TEST_CHECK(!error_flag.load(), "concurrent_data_integrity");
}

// ---------------------------------------------------------------------------
int main() {
    std::printf("=== BipartiteBuf Correctness Tests ===\n\n");

    std::printf("--- Basic Push/Pop ---\n");
    test_basic();

    std::printf("\n--- Capacity Limits ---\n");
    test_capacity();

    std::printf("\n--- Write Wrapping ---\n");
    test_wrap_write();

    std::printf("\n--- Invalidation Boundary ---\n");
    test_invalidation_read();

    std::printf("\n--- Single-Thread Stress ---\n");
    test_stress();

    std::printf("\n--- Concurrent Stress ---\n");
    test_concurrent();

    std::printf("\n=== SUMMARY ===\n");
    std::printf("Passed: %d\n", g_passes);
    std::printf("Failed: %d\n", g_failures);

    if (g_failures == 0) {
        std::printf("ALL TESTS PASSED\n");
        return 0;
    } else {
        std::printf("TESTS FAILED\n");
        return 1;
    }
}
