
// Concurrent correctness test: a producer pushes 100K integers 0..N-1,
// a consumer verifies they arrive in strict FIFO order.
// Also used by ThreadSanitizer to detect memory-ordering data races.

#include "spsc_queue.hpp"
#include <atomic>
#include <iostream>
#include <thread>

int main() {
    constexpr int NUM_ITEMS = 100'000;
    constexpr int BUFFER_SIZE = 1024;

    SPSCQueue<int> q(BUFFER_SIZE);
    std::atomic<bool> error{false};
    std::atomic<int> consumed_count{0};

    // Producer thread
    std::thread producer([&]() {
        for (int i = 0; i < NUM_ITEMS; ++i) {
            while (!q.push(i)) {
                // spin
            }
        }
    });

    // Consumer thread
    std::thread consumer([&]() {
        int expected = 0;
        while (expected < NUM_ITEMS) {
            q.consume_one([&](int val) {
                if (val != expected) {
                    if (!error.exchange(true)) {
                        std::cerr << "FAIL: expected " << expected
                                  << " but got " << val << "\n";
                    }
                }
                ++expected;
                consumed_count.fetch_add(1, std::memory_order_relaxed);
            });
        }
    });

    producer.join();
    consumer.join();

    if (error.load()) {
        std::cerr << "FAIL: ordering errors detected\n";
        return 1;
    }
    if (consumed_count.load() != NUM_ITEMS) {
        std::cerr << "FAIL: consumed " << consumed_count.load()
                  << " items, expected " << NUM_ITEMS << "\n";
        return 1;
    }

    std::cout << "PASS: concurrent correctness (" << NUM_ITEMS << " items)\n";
    return 0;
}
