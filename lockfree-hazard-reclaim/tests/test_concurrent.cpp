//
// Multi-threaded correctness: all pushed values are popped exactly once.

#include "lockfree_stack.hpp"
#include <atomic>
#include <cassert>
#include <iostream>
#include <mutex>
#include <set>
#include <thread>
#include <vector>

int main() {
    const int NUM_THREADS = 8;
    const int OPS_PER_THREAD = 5000;

    LockFreeStack<int> stack;
    std::vector<std::thread> threads;
    std::mutex result_mutex;
    std::set<int> all_popped;
    std::atomic<int> pop_count{0};

    // Phase 1: each thread pushes unique values
    for (int t = 0; t < NUM_THREADS; t++) {
        threads.emplace_back([&stack, t]() {
            for (int i = 0; i < OPS_PER_THREAD; i++) {
                stack.push(t * OPS_PER_THREAD + i);
            }
        });
    }
    for (auto& th : threads) th.join();
    threads.clear();

    // Phase 2: all threads pop until empty
    for (int t = 0; t < NUM_THREADS; t++) {
        threads.emplace_back([&stack, &result_mutex, &all_popped, &pop_count]() {
            while (true) {
                auto val = stack.try_pop();
                if (!val) break;
                std::lock_guard<std::mutex> lock(result_mutex);
                all_popped.insert(*val);
                pop_count.fetch_add(1, std::memory_order_relaxed);
            }
        });
    }
    for (auto& th : threads) th.join();

    // Verify: exact set equality
    int expected = NUM_THREADS * OPS_PER_THREAD;
    assert(static_cast<int>(all_popped.size()) == expected);
    assert(pop_count.load() == expected);
    for (int i = 0; i < expected; i++) {
        assert(all_popped.count(i) == 1);
    }

    std::cout << "CONCURRENT_TEST_PASSED" << std::endl;
    return 0;
}
