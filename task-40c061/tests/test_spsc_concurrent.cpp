//
// Tests SPSC queue concurrent correctness: producer pushes 500K sequential
// values, consumer verifies they arrive in exact order.

#include "/app/spsc_queue.hpp"
#include <thread>
#include <cstdio>
#include <cstdint>
#include <cassert>
#include <atomic>

int main() {
    constexpr size_t N = 500000;
    constexpr size_t CAP = 1024;

    SPSCQueue<uint64_t> q(CAP);
    std::atomic<bool> error{false};

    // Producer: push 0, 1, 2, ..., N-1
    std::thread producer([&]() {
        for (uint64_t i = 0; i < N; ++i) {
            while (!q.try_push(i)) {
                // spin-wait
            }
        }
    });

    // Consumer: verify sequential order
    std::thread consumer([&]() {
        for (uint64_t expected = 0; expected < N; ++expected) {
            uint64_t val;
            while (!q.try_pop(val)) {
                // spin-wait
            }
            if (val != expected) {
                fprintf(stderr, "FAIL: expected %lu, got %lu\n",
                        (unsigned long)expected, (unsigned long)val);
                error.store(true);
                return;
            }
        }
    });

    producer.join();
    consumer.join();

    if (error.load()) {
        printf("FAIL\n");
        return 1;
    }

    printf("PASS\n");
    return 0;
}
