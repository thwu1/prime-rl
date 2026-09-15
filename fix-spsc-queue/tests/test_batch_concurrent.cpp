
// Concurrent correctness test for SPSCBatchQueue:
// Producer uses push_batch, consumer alternates between
// consume_batch and consume_one. Verifies strict FIFO ordering.

#include "spsc_batch_queue.hpp"
#include <atomic>
#include <iostream>
#include <thread>

int main() {
    constexpr int NUM_ITEMS = 100'000;
    constexpr int BATCH_SIZE = 16;
    constexpr int BUFFER_SIZE = 1024;

    SPSCBatchQueue<int> q(BUFFER_SIZE);
    std::atomic<bool> error{false};
    std::atomic<int> total_consumed{0};

    // Producer: push in batches
    std::thread producer([&]() {
        int items[BATCH_SIZE];
        for (int i = 0; i < NUM_ITEMS; ) {
            int batch = (BATCH_SIZE < NUM_ITEMS - i) ? BATCH_SIZE : (NUM_ITEMS - i);
            for (int j = 0; j < batch; ++j)
                items[j] = i + j;

            while (!q.push_batch(items, batch)) {
                // spin — queue full
            }
            i += batch;
        }
    });

    // Consumer: alternate between batch and single consume
    std::thread consumer([&]() {
        int expected = 0;
        while (expected < NUM_ITEMS) {
            if (expected % 64 < 48) {
                // Batch consume
                std::size_t consumed = q.consume_batch([&](int val) {
                    if (val != expected) {
                        if (!error.exchange(true)) {
                            std::cerr << "FAIL: expected " << expected
                                      << " but got " << val << "\n";
                        }
                    }
                    ++expected;
                }, 8);
                total_consumed.fetch_add(static_cast<int>(consumed),
                                         std::memory_order_relaxed);
            } else {
                // Single consume
                if (q.consume_one([&](int val) {
                    if (val != expected) {
                        if (!error.exchange(true)) {
                            std::cerr << "FAIL: expected " << expected
                                      << " but got " << val << "\n";
                        }
                    }
                    ++expected;
                })) {
                    total_consumed.fetch_add(1, std::memory_order_relaxed);
                }
            }
        }
    });

    producer.join();
    consumer.join();

    if (error.load()) {
        std::cerr << "FAIL: ordering errors detected\n";
        return 1;
    }

    std::cout << "PASS: batch concurrent correctness (" << NUM_ITEMS << " items)\n";
    return 0;
}
