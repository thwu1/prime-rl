
// Verifies that head_ and tail_ atomics are on separate cache lines.
// Without alignas/padding, SPSCQueue<int> is ~32 bytes.
// With proper cache-line separation (>=64B between atomics),
// sizeof(SPSCQueue<int>) must be >= 128 bytes.

#include "spsc_queue.hpp"
#include <cstddef>
#include <iostream>

int main() {
    std::size_t queue_size = sizeof(SPSCQueue<int>);
    std::cout << "sizeof(SPSCQueue<int>) = " << queue_size << " bytes\n";

    // Without false-sharing fix: ~32-40 bytes (capacity + 2 atomics + ptr)
    // With alignas(64) on head_ and tail_: >= 192 bytes typically
    // Threshold of 128 catches all reasonable cache-line separation schemes
    if (queue_size < 128) {
        std::cerr << "FAIL: sizeof(SPSCQueue<int>) = " << queue_size
                  << " bytes, expected >= 128 for cache-line separation "
                  << "between head and tail atomics\n";
        return 1;
    }

    // Sanity: the queue still works
    SPSCQueue<int> q(8);
    for (int i = 0; i < 8; ++i) {
        if (!q.push(i)) {
            std::cerr << "FAIL: push failed at " << i << "\n";
            return 1;
        }
    }
    for (int i = 0; i < 8; ++i) {
        q.consume_one([&](int val) {
            if (val != i) {
                std::cerr << "FAIL: expected " << i << " got " << val << "\n";
                std::exit(1);
            }
        });
    }

    std::cout << "PASS: cache-line separation (queue size = "
              << queue_size << " bytes)\n";
    return 0;
}
