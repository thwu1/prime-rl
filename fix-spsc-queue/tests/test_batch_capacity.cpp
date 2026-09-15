
// Tests batch queue capacity: push_batch atomicity, single push,
// capacity limits, and edge cases.

#include "spsc_batch_queue.hpp"
#include <cstdlib>
#include <iostream>

int main() {
    // Test 1: push_batch of exactly N items into queue of size N
    {
        SPSCBatchQueue<int> q(10);
        int items[10];
        for (int i = 0; i < 10; ++i) items[i] = i;

        if (!q.push_batch(items, 10)) {
            std::cerr << "FAIL: push_batch of 10 items into size-10 queue failed\n";
            return 1;
        }

        // Queue should be full
        if (q.push(99)) {
            std::cerr << "FAIL: push should fail on full queue\n";
            return 1;
        }

        // Drain and verify order
        for (int expected = 0; expected < 10; ++expected) {
            bool ok = q.consume_one([&](int val) {
                if (val != expected) {
                    std::cerr << "FAIL: expected " << expected << " got " << val << "\n";
                    std::exit(1);
                }
            });
            if (!ok) {
                std::cerr << "FAIL: consume_one false at position " << expected << "\n";
                return 1;
            }
        }
    }

    // Test 2: push_batch fails atomically when insufficient space
    {
        SPSCBatchQueue<int> q(5);
        int items3[3] = {10, 20, 30};
        int items4[4] = {40, 50, 60, 70};

        if (!q.push_batch(items3, 3)) {
            std::cerr << "FAIL: push_batch of 3 into size-5 should succeed\n";
            return 1;
        }

        // Only 2 slots left — batch of 4 must fail without side effects
        if (q.push_batch(items4, 4)) {
            std::cerr << "FAIL: push_batch of 4 into queue with 2 free slots should fail\n";
            return 1;
        }

        // Queue should still have exactly the original 3 items
        int count = 0;
        while (q.consume_one([&](int val) {
            if (val != items3[count]) {
                std::cerr << "FAIL: after failed batch, item " << count
                          << " is " << val << " expected " << items3[count] << "\n";
                std::exit(1);
            }
        })) {
            ++count;
        }
        if (count != 3) {
            std::cerr << "FAIL: expected 3 items after failed batch, got " << count << "\n";
            return 1;
        }
    }

    // Test 3: single push works correctly
    {
        SPSCBatchQueue<int> q(1);
        if (!q.push(42)) {
            std::cerr << "FAIL: single push to size-1 queue failed\n";
            return 1;
        }
        if (q.push(43)) {
            std::cerr << "FAIL: 2nd push to size-1 queue should fail\n";
            return 1;
        }
        q.consume_one([](int val) {
            if (val != 42) {
                std::cerr << "FAIL: expected 42, got " << val << "\n";
                std::exit(1);
            }
        });
    }

    // Test 4: empty batch push succeeds
    {
        SPSCBatchQueue<int> q(5);
        if (!q.push_batch(nullptr, 0)) {
            std::cerr << "FAIL: empty push_batch should succeed\n";
            return 1;
        }
    }

    // Test 5: fill and drain multiple rounds
    {
        SPSCBatchQueue<int> q(100);
        for (int round = 0; round < 3; ++round) {
            int items[100];
            for (int i = 0; i < 100; ++i) items[i] = round * 100 + i;

            if (!q.push_batch(items, 100)) {
                std::cerr << "FAIL: push_batch failed at round " << round << "\n";
                return 1;
            }
            if (q.push(999)) {
                std::cerr << "FAIL: push after full batch should fail (round "
                          << round << ")\n";
                return 1;
            }

            for (int i = 0; i < 100; ++i) {
                int expected = round * 100 + i;
                q.consume_one([&](int val) {
                    if (val != expected) {
                        std::cerr << "FAIL: round " << round << " expected "
                                  << expected << " got " << val << "\n";
                        std::exit(1);
                    }
                });
            }
        }
    }

    std::cout << "PASS: batch capacity tests\n";
    return 0;
}
