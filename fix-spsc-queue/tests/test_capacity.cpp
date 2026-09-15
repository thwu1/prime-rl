
// Verifies that SPSCQueue<T>(N) can hold exactly N items,
// not N-1 (the classic sentinel-slot off-by-one).

#include "spsc_queue.hpp"
#include <cstdlib>
#include <iostream>

int main() {
    // --- Test 1: capacity 1 ---
    {
        SPSCQueue<int> q(1);
        if (!q.push(42)) {
            std::cerr << "FAIL: push to capacity-1 queue failed\n";
            return 1;
        }
        if (q.push(99)) {
            std::cerr << "FAIL: 2nd push to capacity-1 queue should fail\n";
            return 1;
        }
        bool consumed = q.consume_one([](int val) {
            if (val != 42) {
                std::cerr << "FAIL: expected 42 from capacity-1 queue, got "
                          << val << "\n";
                std::exit(1);
            }
        });
        if (!consumed) {
            std::cerr << "FAIL: consume_one returned false on non-empty queue\n";
            return 1;
        }
        if (q.consume_one([](int) {})) {
            std::cerr << "FAIL: queue should be empty after draining\n";
            return 1;
        }
    }

    // --- Test 2: capacity 10, push exactly 10 items ---
    {
        SPSCQueue<int> q(10);
        for (int i = 0; i < 10; ++i) {
            if (!q.push(i)) {
                std::cerr << "FAIL: push(" << i
                          << ") returned false for capacity-10 queue\n";
                return 1;
            }
        }
        // 11th push must fail
        if (q.push(10)) {
            std::cerr << "FAIL: 11th push should fail (queue full)\n";
            return 1;
        }
        // Pop all and verify FIFO order
        for (int expected = 0; expected < 10; ++expected) {
            bool ok = q.consume_one([&](int val) {
                if (val != expected) {
                    std::cerr << "FAIL: expected " << expected << " got "
                              << val << "\n";
                    std::exit(1);
                }
            });
            if (!ok) {
                std::cerr << "FAIL: consume_one false at position " << expected
                          << "\n";
                return 1;
            }
        }
        if (q.consume_one([](int) {})) {
            std::cerr << "FAIL: queue should be empty\n";
            return 1;
        }
    }

    // --- Test 3: capacity 1000, fill and drain 3 rounds ---
    {
        SPSCQueue<int> q(1000);
        for (int round = 0; round < 3; ++round) {
            for (int i = 0; i < 1000; ++i) {
                int val = i + round * 1000;
                if (!q.push(val)) {
                    std::cerr << "FAIL: push failed at round " << round
                              << " item " << i << "\n";
                    return 1;
                }
            }
            if (q.push(-1)) {
                std::cerr << "FAIL: push should fail when full (round "
                          << round << ")\n";
                return 1;
            }
            for (int i = 0; i < 1000; ++i) {
                int expected = i + round * 1000;
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

    std::cout << "PASS: all capacity tests\n";
    return 0;
}
