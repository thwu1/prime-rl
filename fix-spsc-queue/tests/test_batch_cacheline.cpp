
// Verifies that SPSCBatchQueue head_ and tail_ atomics are on
// separate cache lines, preventing false sharing.

#include "spsc_batch_queue.hpp"
#include <cstddef>
#include <cstdlib>
#include <iostream>

int main() {
    std::size_t queue_size = sizeof(SPSCBatchQueue<int>);
    std::cout << "sizeof(SPSCBatchQueue<int>) = " << queue_size << " bytes\n";

    // Without false-sharing mitigation: ~32-40 bytes
    // With alignas(64) on head_ and tail_: >= 192 bytes typically
    // Threshold of 128 catches all reasonable cache-line separation schemes
    if (queue_size < 128) {
        std::cerr << "FAIL: sizeof(SPSCBatchQueue<int>) = " << queue_size
                  << " bytes, expected >= 128 for cache-line separation\n";
        return 1;
    }

    // Sanity: batch operations still work
    SPSCBatchQueue<int> q(8);
    int items[8];
    for (int i = 0; i < 8; ++i) items[i] = i;
    if (!q.push_batch(items, 8)) {
        std::cerr << "FAIL: push_batch failed\n";
        return 1;
    }
    int idx = 0;
    std::size_t consumed = q.consume_batch([&](int val) {
        if (val != idx) {
            std::cerr << "FAIL: expected " << idx << " got " << val << "\n";
            std::exit(1);
        }
        ++idx;
    }, 8);
    if (consumed != 8) {
        std::cerr << "FAIL: consumed " << consumed << " expected 8\n";
        return 1;
    }

    std::cout << "PASS: batch cache-line separation (queue size = "
              << queue_size << " bytes)\n";
    return 0;
}
