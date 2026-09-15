//
// High-contention stress test: 16 threads, 50K mixed push/pop ops each.

#include "lockfree_stack.hpp"
#include <atomic>
#include <iostream>
#include <thread>
#include <vector>

int main() {
    const int NUM_THREADS = 16;
    const int OPS_PER_THREAD = 50000;

    LockFreeStack<int> stack;
    std::atomic<bool> start{false};
    std::vector<std::thread> threads;

    for (int t = 0; t < NUM_THREADS; t++) {
        threads.emplace_back([&stack, &start, t]() {
            while (!start.load(std::memory_order_acquire))
                ;

            for (int i = 0; i < OPS_PER_THREAD; i++) {
                if (i % 2 == 0) {
                    stack.push(t * OPS_PER_THREAD + i);
                } else {
                    stack.try_pop();
                }
            }
        });
    }

    // Release all threads simultaneously for maximum contention
    start.store(true, std::memory_order_release);

    for (auto& th : threads) th.join();

    // Drain remaining elements
    while (stack.try_pop())
        ;

    std::cout << "STRESS_TEST_PASSED" << std::endl;
    return 0;
}
