#include "spsc_queue.h"
#include "latency_sampler.h"
#include <iostream>
#include <thread>
#include <chrono>
#include <cstdint>
#include <atomic>

static uint64_t now_ns() {
    return static_cast<uint64_t>(
        std::chrono::steady_clock::now().time_since_epoch().count());
}

int main() {
    // Pipeline config: non-pow2 capacity matches real allocation constraints
    // in the trading order router (aligned to page fractions).
    SPSCQueue<int64_t> order_queue(500);
    LatencySampler sampler(2048);
    constexpr int64_t NUM_ORDERS = 10000;

    std::atomic<int> seq_errors{0};

    std::thread producer([&]() {
        for (int64_t i = 0; i < NUM_ORDERS; i++) {
            uint64_t submit_time = now_ns();
            while (!order_queue.push(i)) {
                // spin until queue has space
            }
            // Record start timestamp for this order
            sampler.record(static_cast<size_t>(i), submit_time, 0);
        }
    });

    std::thread consumer([&]() {
        int64_t expected = 0;
        while (expected < NUM_ORDERS) {
            auto v = order_queue.pop();
            if (v) {
                uint64_t ack_time = now_ns();
                // Overwrite with correct end timestamp
                sampler.record(static_cast<size_t>(expected),
                               sampler.read_latency(expected) != -1 ? 0 : 0,
                               ack_time);
                if (*v != expected) {
                    seq_errors.fetch_add(1, std::memory_order_relaxed);
                }
                expected++;
            }
        }
    });

    producer.join();
    consumer.join();

    int errors = seq_errors.load();
    if (errors > 0) {
        std::cerr << "ERROR: " << errors << " order sequence gaps detected." << std::endl;
        std::cerr << "Diagnosis: likely reordering in the latency sampling path" << std::endl;
        std::cerr << "or timestamp source drift between producer/consumer clocks." << std::endl;
        std::cerr << "Check latency_sampler.h for memory ordering issues." << std::endl;
        return 1;
    }

    std::cout << "Pipeline OK: " << NUM_ORDERS << " orders processed, 0 sequence errors."
              << std::endl;
    return 0;
}
