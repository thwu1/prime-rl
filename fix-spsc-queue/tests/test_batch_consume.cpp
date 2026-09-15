
// Tests consume_batch edge cases: partial drain, empty queue,
// max_count=0, and multi-round push_batch + consume_batch.

#include "spsc_batch_queue.hpp"
#include <cstdlib>
#include <iostream>

int main() {
    // Test 1: consume_batch returns 0 on empty queue
    {
        SPSCBatchQueue<int> q(10);
        std::size_t consumed = q.consume_batch([](int) {}, 5);
        if (consumed != 0) {
            std::cerr << "FAIL: consume_batch on empty queue returned "
                      << consumed << "\n";
            return 1;
        }
    }

    // Test 2: consume_batch returns min(available, max_count)
    {
        SPSCBatchQueue<int> q(10);
        for (int i = 0; i < 7; ++i) q.push(i);

        // Consume at most 5 (should get exactly 5)
        int idx = 0;
        std::size_t consumed = q.consume_batch([&](int val) {
            if (val != idx) {
                std::cerr << "FAIL: expected " << idx << " got " << val << "\n";
                std::exit(1);
            }
            ++idx;
        }, 5);

        if (consumed != 5) {
            std::cerr << "FAIL: expected 5 consumed, got " << consumed << "\n";
            return 1;
        }

        // 2 remaining — ask for 10, should get 2
        consumed = q.consume_batch([&](int val) {
            if (val != idx) {
                std::cerr << "FAIL: expected " << idx << " got " << val << "\n";
                std::exit(1);
            }
            ++idx;
        }, 10);

        if (consumed != 2) {
            std::cerr << "FAIL: expected 2 consumed, got " << consumed << "\n";
            return 1;
        }
    }

    // Test 3: consume_batch with max_count=0 returns 0 without consuming
    {
        SPSCBatchQueue<int> q(10);
        q.push(42);
        std::size_t consumed = q.consume_batch([](int) {}, 0);
        if (consumed != 0) {
            std::cerr << "FAIL: consume_batch(0) returned " << consumed << "\n";
            return 1;
        }
        // Item should still be there
        bool ok = q.consume_one([](int val) {
            if (val != 42) {
                std::cerr << "FAIL: item should still be 42, got " << val << "\n";
                std::exit(1);
            }
        });
        if (!ok) {
            std::cerr << "FAIL: item should still be in queue\n";
            return 1;
        }
    }

    // Test 4: push_batch + consume_batch roundtrip over multiple rounds
    {
        SPSCBatchQueue<int> q(100);
        for (int round = 0; round < 5; ++round) {
            int items[20];
            for (int i = 0; i < 20; ++i) items[i] = round * 20 + i;

            if (!q.push_batch(items, 20)) {
                std::cerr << "FAIL: push_batch failed at round " << round << "\n";
                return 1;
            }

            int idx = 0;
            std::size_t consumed = q.consume_batch([&](int val) {
                int expected = round * 20 + idx;
                if (val != expected) {
                    std::cerr << "FAIL: round " << round << " idx " << idx
                              << " expected " << expected << " got " << val << "\n";
                    std::exit(1);
                }
                ++idx;
            }, 20);

            if (consumed != 20) {
                std::cerr << "FAIL: round " << round << " consumed " << consumed
                          << " expected 20\n";
                return 1;
            }
        }
    }

    // Test 5: interleaved push and consume_batch
    {
        SPSCBatchQueue<int> q(10);
        // Push 3 items individually
        q.push(100);
        q.push(200);
        q.push(300);

        // Batch push 4 more
        int batch[4] = {400, 500, 600, 700};
        if (!q.push_batch(batch, 4)) {
            std::cerr << "FAIL: push_batch after individual pushes failed\n";
            return 1;
        }

        // Consume all 7 in one batch
        int expected_vals[] = {100, 200, 300, 400, 500, 600, 700};
        int idx = 0;
        std::size_t consumed = q.consume_batch([&](int val) {
            if (val != expected_vals[idx]) {
                std::cerr << "FAIL: interleaved test idx " << idx
                          << " expected " << expected_vals[idx]
                          << " got " << val << "\n";
                std::exit(1);
            }
            ++idx;
        }, 10);

        if (consumed != 7) {
            std::cerr << "FAIL: expected 7 consumed in interleaved test, got "
                      << consumed << "\n";
            return 1;
        }
    }

    std::cout << "PASS: consume_batch tests\n";
    return 0;
}
