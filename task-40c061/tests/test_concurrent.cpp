
#include "/app/spsc_queue.hpp"
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <thread>
#include <vector>

int main() {
    constexpr size_t QUEUE_CAP = 4096;
    constexpr size_t NUM_ITEMS = 200000;

    SPSCQueue<uint64_t> q(QUEUE_CAP);
    std::vector<uint64_t> received;
    received.reserve(NUM_ITEMS);

    std::atomic<bool> producer_done{false};

    // Consumer thread
    std::thread consumer([&]() {
        while (true) {
            bool got = q.consume_one([&](uint64_t& val) {
                received.push_back(val);
            });
            if (!got) {
                if (producer_done.load(std::memory_order_acquire)) {
                    // Final drain
                    while (q.consume_one([&](uint64_t& val) {
                        received.push_back(val);
                    }));
                    break;
                }
                std::this_thread::yield();
            }
        }
    });

    // Producer thread (main)
    for (uint64_t i = 0; i < NUM_ITEMS; ++i) {
        while (!q.push(i)) {
            std::this_thread::yield();
        }
    }
    producer_done.store(true, std::memory_order_release);

    consumer.join();

    // Verify all items received
    if (received.size() != NUM_ITEMS) {
        printf("FAIL: received %zu items, expected %zu\n", received.size(), NUM_ITEMS);
        return 1;
    }

    // Verify FIFO ordering — every item must match its expected sequence
    for (uint64_t i = 0; i < NUM_ITEMS; ++i) {
        if (received[i] != i) {
            printf("FAIL: at index %lu expected %lu got %lu\n",
                   (unsigned long)i, (unsigned long)i, (unsigned long)received[i]);
            return 1;
        }
    }

    printf("PASS\n");
    return 0;
}
