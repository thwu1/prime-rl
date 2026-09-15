//
// Tests SPSC queue: exact capacity, FIFO ordering, wrap-around, interleaved ops.

#include "/app/spsc_queue.hpp"
#include <cstdio>
#include <cassert>
#include <cstddef>

static void test_exact_capacity(size_t cap) {
    SPSCQueue<int> q(cap);
    assert(q.capacity() == cap);

    // Fill to capacity
    for (size_t i = 0; i < cap; ++i) {
        bool ok = q.try_push(static_cast<int>(i));
        if (!ok) {
            fprintf(stderr, "FAIL: push %zu of %zu failed\n", i, cap);
            assert(false);
        }
    }

    // One more should fail
    bool ok = q.try_push(999);
    if (ok) {
        fprintf(stderr, "FAIL: push beyond capacity %zu succeeded\n", cap);
        assert(false);
    }

    // Drain and verify FIFO
    for (size_t i = 0; i < cap; ++i) {
        int val;
        bool got = q.try_pop(val);
        assert(got);
        if (val != static_cast<int>(i)) {
            fprintf(stderr, "FAIL: expected %d, got %d (cap=%zu, idx=%zu)\n",
                    static_cast<int>(i), val, cap, i);
            assert(false);
        }
    }

    // Should be empty
    int dummy;
    assert(!q.try_pop(dummy));
}

static void test_wrap_around(size_t cap) {
    SPSCQueue<int> q(cap);

    // Push half, pop half, repeat to force wrap-around
    int push_val = 0;
    int pop_val = 0;

    for (int round = 0; round < 5; ++round) {
        size_t half = cap / 2;
        if (half == 0) half = 1;
        for (size_t i = 0; i < half; ++i) {
            assert(q.try_push(push_val++));
        }
        for (size_t i = 0; i < half; ++i) {
            int v;
            assert(q.try_pop(v));
            if (v != pop_val) {
                fprintf(stderr, "FAIL wrap: expected %d got %d (cap=%zu round=%d)\n",
                        pop_val, v, cap, round);
                assert(false);
            }
            ++pop_val;
        }
    }
}

static void test_interleaved(size_t cap) {
    SPSCQueue<int> q(cap);
    int push_val = 0;
    int pop_val = 0;

    // Push 1, pop 1, repeat many times
    for (int i = 0; i < 10000; ++i) {
        assert(q.try_push(push_val++));
        int v;
        assert(q.try_pop(v));
        if (v != pop_val) {
            fprintf(stderr, "FAIL interleaved: expected %d got %d (cap=%zu)\n",
                    pop_val, v, cap);
            assert(false);
        }
        ++pop_val;
    }
}

static void test_fill_drain_cycles(size_t cap) {
    SPSCQueue<int> q(cap);

    // Multiple full fill/drain cycles
    for (int cycle = 0; cycle < 3; ++cycle) {
        for (size_t i = 0; i < cap; ++i) {
            assert(q.try_push(static_cast<int>(cycle * 1000 + i)));
        }
        assert(!q.try_push(0));  // must be full

        for (size_t i = 0; i < cap; ++i) {
            int v;
            assert(q.try_pop(v));
            assert(v == static_cast<int>(cycle * 1000 + i));
        }
        int dummy;
        assert(!q.try_pop(dummy));  // must be empty
    }
}

int main() {
    // Test many capacities including non-power-of-2 values
    size_t caps[] = {1, 2, 3, 7, 8, 10, 15, 16, 31, 32, 64,
                     100, 127, 128, 255, 256, 1000, 1024};

    for (size_t cap : caps) {
        test_exact_capacity(cap);
        test_wrap_around(cap);
        test_interleaved(cap);
        test_fill_drain_cycles(cap);
    }

    printf("PASS\n");
    return 0;
}
