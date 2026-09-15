
#include "bipartite_buf.hpp"
#include <cstring>
#include <cassert>
#include <cstdio>
#include <cstdint>

using namespace lockfree::spsc;

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { \
        fprintf(stderr, "FAIL: %s - %s (line %d)\n", __func__, msg, __LINE__); \
        failures++; \
        return; \
    } \
} while(0)

// Test 1: Basic write and read
void test_basic_write_read() {
    BipartiteBuf<uint8_t, 256> buf;

    auto* wp = buf.WriteAcquire(10);
    CHECK(wp != nullptr, "WriteAcquire returned nullptr");
    for (int i = 0; i < 10; i++) wp[i] = static_cast<uint8_t>(i);
    buf.WriteRelease(10);

    auto [rp, count] = buf.ReadAcquire();
    CHECK(rp != nullptr, "ReadAcquire returned nullptr");
    CHECK(count == 10, "Expected 10 elements");
    for (int i = 0; i < 10; i++)
        CHECK(rp[i] == i, "Data mismatch");
    buf.ReadRelease(10);

    auto [rp2, count2] = buf.ReadAcquire();
    CHECK(rp2 == nullptr && count2 == 0, "Buffer should be empty");

    printf("PASS: test_basic_write_read\n");
}

// Test 2: Fill buffer to full capacity
void test_fill_capacity() {
    BipartiteBuf<uint8_t, 64> buf;

    auto* wp = buf.WriteAcquire(64);
    CHECK(wp != nullptr, "WriteAcquire(64) should succeed on empty 64-element buffer");
    for (int i = 0; i < 64; i++) wp[i] = static_cast<uint8_t>(i);
    buf.WriteRelease(64);

    auto* wp2 = buf.WriteAcquire(1);
    CHECK(wp2 == nullptr, "Buffer should be full");

    auto [rp, count] = buf.ReadAcquire();
    CHECK(rp != nullptr && count == 64, "Should read all 64 elements");
    for (int i = 0; i < 64; i++)
        CHECK(rp[i] == i, "Data mismatch");
    buf.ReadRelease(64);

    auto [rp2, c2] = buf.ReadAcquire();
    CHECK(rp2 == nullptr && c2 == 0, "Buffer should be empty after full read");

    printf("PASS: test_fill_capacity\n");
}

// Test 3: Wrap-around with invalidation
void test_wrap_around() {
    BipartiteBuf<uint8_t, 100> buf;

    // Write 70 bytes
    auto* wp = buf.WriteAcquire(70);
    CHECK(wp != nullptr, "WriteAcquire(70) failed");
    for (int i = 0; i < 70; i++) wp[i] = static_cast<uint8_t>(i);
    buf.WriteRelease(70);

    // Read and release 50 bytes (r moves to 50)
    auto [rp, count] = buf.ReadAcquire();
    CHECK(count == 70, "Expected 70 elements");
    buf.ReadRelease(50);

    // Tail space = 30, head space = 50. Write 40 → must wrap.
    auto* wp2 = buf.WriteAcquire(40);
    CHECK(wp2 != nullptr, "WriteAcquire(40) should wrap to head");
    for (int i = 0; i < 40; i++) wp2[i] = static_cast<uint8_t>(100 + i);
    buf.WriteRelease(40);

    // Read tail data [50, 70) = 20 bytes
    auto [rp2, c2] = buf.ReadAcquire();
    CHECK(rp2 != nullptr, "ReadAcquire should return tail data");
    CHECK(c2 == 20, "Expected 20 tail bytes");
    for (int i = 0; i < 20; i++)
        CHECK(rp2[i] == static_cast<uint8_t>(50 + i), "Tail data mismatch");
    buf.ReadRelease(20);

    // Read head data [0, 40) after invalidation wrap
    auto [rp3, c3] = buf.ReadAcquire();
    CHECK(rp3 != nullptr, "ReadAcquire should return head data after wrap");
    CHECK(c3 == 40, "Expected 40 head bytes");
    for (int i = 0; i < 40; i++)
        CHECK(rp3[i] == static_cast<uint8_t>(100 + i), "Head data mismatch");
    buf.ReadRelease(40);

    // Buffer should be empty
    auto [rp4, c4] = buf.ReadAcquire();
    CHECK(rp4 == nullptr && c4 == 0, "Buffer should be empty");

    printf("PASS: test_wrap_around\n");
}

// Test 4: Partial release
void test_partial_release() {
    BipartiteBuf<uint32_t, 32> buf;

    auto* wp = buf.WriteAcquire(20);
    CHECK(wp != nullptr, "WriteAcquire(20) failed");
    for (int i = 0; i < 20; i++) wp[i] = static_cast<uint32_t>(i);
    buf.WriteRelease(20);

    // Read 20 but release only 10
    auto [rp, count] = buf.ReadAcquire();
    CHECK(count == 20, "Expected 20 elements");
    buf.ReadRelease(10);

    // Read remaining 10
    auto [rp2, c2] = buf.ReadAcquire();
    CHECK(c2 == 10, "Expected 10 remaining elements");
    for (size_t i = 0; i < 10; i++)
        CHECK(rp2[i] == 10u + i, "Remaining data mismatch");
    buf.ReadRelease(10);

    printf("PASS: test_partial_release\n");
}

// Test 5: Write less than acquired
void test_write_less_than_acquired() {
    BipartiteBuf<uint8_t, 64> buf;

    auto* wp = buf.WriteAcquire(32);
    CHECK(wp != nullptr, "WriteAcquire(32) failed");
    for (int i = 0; i < 16; i++) wp[i] = static_cast<uint8_t>(i);
    buf.WriteRelease(16); // Commit only 16

    auto [rp, count] = buf.ReadAcquire();
    CHECK(count == 16, "Expected 16 committed elements");
    for (int i = 0; i < 16; i++)
        CHECK(rp[i] == i, "Data mismatch");
    buf.ReadRelease(16);

    printf("PASS: test_write_less_than_acquired\n");
}

// Test 6: Double acquire should fail
void test_double_acquire() {
    BipartiteBuf<uint8_t, 64> buf;

    auto* wp = buf.WriteAcquire(10);
    CHECK(wp != nullptr, "First WriteAcquire failed");
    auto* wp2 = buf.WriteAcquire(10);
    CHECK(wp2 == nullptr, "Second WriteAcquire should return nullptr");
    buf.WriteRelease(10);

    auto [rp, count] = buf.ReadAcquire();
    CHECK(count == 10, "Expected 10 elements");
    auto [rp2, c2] = buf.ReadAcquire();
    CHECK(rp2 == nullptr && c2 == 0, "Second ReadAcquire should return nullptr");
    buf.ReadRelease(10);

    printf("PASS: test_double_acquire\n");
}

// Test 7: Zero-length and oversized requests
void test_edge_requests() {
    BipartiteBuf<uint8_t, 64> buf;

    CHECK(buf.WriteAcquire(0) == nullptr, "WriteAcquire(0) should return nullptr");
    CHECK(buf.WriteAcquire(65) == nullptr, "WriteAcquire(65) should return nullptr for 64-element buffer");

    auto [rp, count] = buf.ReadAcquire();
    CHECK(rp == nullptr && count == 0, "ReadAcquire on empty buffer");

    printf("PASS: test_edge_requests\n");
}

// Test 8: Multiple wrap-around cycles
void test_multiple_wraps() {
    BipartiteBuf<uint8_t, 32> buf;

    for (int round = 0; round < 20; round++) {
        auto* wp = buf.WriteAcquire(20);
        CHECK(wp != nullptr, "WriteAcquire failed in multi-wrap");
        for (int i = 0; i < 20; i++)
            wp[i] = static_cast<uint8_t>(round * 20 + i);
        buf.WriteRelease(20);

        auto [rp, count] = buf.ReadAcquire();
        CHECK(rp != nullptr && count == 20, "ReadAcquire failed in multi-wrap");
        for (int i = 0; i < 20; i++)
            CHECK(rp[i] == static_cast<uint8_t>(round * 20 + i), "Data mismatch in multi-wrap");
        buf.ReadRelease(20);
    }

    printf("PASS: test_multiple_wraps\n");
}

// Test 9: Wrapped-full state (w == r with invalidation active)
void test_wrapped_full() {
    BipartiteBuf<uint8_t, 100> buf;

    // Write 70 bytes at [0, 70)
    auto* wp = buf.WriteAcquire(70);
    CHECK(wp != nullptr, "WriteAcquire(70) failed");
    for (int i = 0; i < 70; i++) wp[i] = static_cast<uint8_t>(i);
    buf.WriteRelease(70);

    // Read and release 40 bytes → r=40
    auto [rp, c] = buf.ReadAcquire();
    CHECK(c == 70, "Expected 70");
    buf.ReadRelease(40);

    // Tail=30, head=40. Write 35 → wraps to head.
    auto* wp2 = buf.WriteAcquire(35);
    CHECK(wp2 != nullptr, "Wrap write failed");
    for (int i = 0; i < 35; i++) wp2[i] = static_cast<uint8_t>(200 + i);
    buf.WriteRelease(35);
    // State: r=40, w=35, i=70

    // Fill remaining head space: [35, 40) = 5 bytes
    auto* wp3 = buf.WriteAcquire(5);
    CHECK(wp3 != nullptr, "Fill remaining failed");
    for (int i = 0; i < 5; i++) wp3[i] = static_cast<uint8_t>(150 + i);
    buf.WriteRelease(5);
    // State: r=40, w=40, i=70 → FULL

    // Writing 1 more should fail
    auto* wp4 = buf.WriteAcquire(1);
    CHECK(wp4 == nullptr, "Write should fail when buffer is full (wrapped-full)");

    // Read tail [40, 70) = 30 bytes
    auto [rp2, c2] = buf.ReadAcquire();
    CHECK(c2 == 30, "Expected 30 tail bytes");
    for (int i = 0; i < 30; i++)
        CHECK(rp2[i] == static_cast<uint8_t>(40 + i), "Tail data mismatch in wrapped-full");
    buf.ReadRelease(30);

    // Read head [0, 40) after invalidation wrap
    auto [rp3, c3] = buf.ReadAcquire();
    CHECK(c3 == 40, "Expected 40 head bytes after wrap");
    // First 35 bytes: 200..234, next 5 bytes: 150..154
    for (int i = 0; i < 35; i++)
        CHECK(rp3[i] == static_cast<uint8_t>(200 + i), "Head data mismatch (first part)");
    for (int i = 0; i < 5; i++)
        CHECK(rp3[35 + i] == static_cast<uint8_t>(150 + i), "Head data mismatch (second part)");
    buf.ReadRelease(40);

    // Should be empty
    auto [rp4, c4] = buf.ReadAcquire();
    CHECK(rp4 == nullptr && c4 == 0, "Buffer should be empty after full drain");

    printf("PASS: test_wrapped_full\n");
}

// Test 10: Cancel acquire with zero release
void test_cancel_acquire() {
    BipartiteBuf<uint8_t, 64> buf;

    auto* wp = buf.WriteAcquire(10);
    CHECK(wp != nullptr, "WriteAcquire failed");
    buf.WriteRelease(0); // Cancel - commit nothing

    auto [rp, count] = buf.ReadAcquire();
    CHECK(rp == nullptr && count == 0, "Buffer should be empty after cancelled write");

    // Should be able to write again
    auto* wp2 = buf.WriteAcquire(10);
    CHECK(wp2 != nullptr, "WriteAcquire after cancel should succeed");
    for (int i = 0; i < 10; i++) wp2[i] = static_cast<uint8_t>(i);
    buf.WriteRelease(10);

    auto [rp2, c2] = buf.ReadAcquire();
    CHECK(c2 == 10, "Expected 10 elements after re-write");
    buf.ReadRelease(0); // Cancel read

    // Data should still be there
    auto [rp3, c3] = buf.ReadAcquire();
    CHECK(c3 == 10, "Data should remain after cancelled read");
    buf.ReadRelease(10);

    printf("PASS: test_cancel_acquire\n");
}

int main() {
    test_basic_write_read();
    test_fill_capacity();
    test_wrap_around();
    test_partial_release();
    test_write_less_than_acquired();
    test_double_acquire();
    test_edge_requests();
    test_multiple_wraps();
    test_wrapped_full();
    test_cancel_acquire();

    if (failures > 0) {
        printf("\n%d test(s) FAILED\n", failures);
        return 1;
    }
    printf("\nAll basic tests passed!\n");
    return 0;
}
