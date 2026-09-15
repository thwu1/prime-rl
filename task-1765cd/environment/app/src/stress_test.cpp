
#include <thread>
#include <iostream>
#include <vector>
#include <cstdlib>
#include <cstdint>

#include "spsc_queue.hpp"

int main(int argc, char* argv[]) {
    const int64_t NUM_OPS = (argc > 1) ? std::atoll(argv[1]) : 10'000'000;
    const int QUEUE_SIZE = 8192;

    SPSCQueue<int64_t> q(QUEUE_SIZE);

    std::vector<int64_t> received;
    received.reserve(NUM_OPS);

    std::thread producer([&]() {
        for (int64_t i = 0; i < NUM_OPS; ++i) {
            while (!q.push(i)) { /* spin */ }
        }
    });

    std::thread consumer([&]() {
        int64_t count = 0;
        while (count < NUM_OPS) {
            q.consume_one([&](int64_t val) {
                received.push_back(val);
                ++count;
            });
        }
    });

    producer.join();
    consumer.join();

    // Verify all values received in order
    if (static_cast<int64_t>(received.size()) != NUM_OPS) {
        std::cerr << "FAIL: Expected " << NUM_OPS
                  << " elements, got " << received.size() << std::endl;
        return 1;
    }

    for (int64_t i = 0; i < NUM_OPS; ++i) {
        if (received[i] != i) {
            std::cerr << "FAIL: Expected " << i << " at index " << i
                      << ", got " << received[i] << std::endl;
            return 1;
        }
    }

    std::cout << "STRESS_TEST_PASSED" << std::endl;
    return 0;
}
