#include "lockfree_stack.hpp"
#include <thread>
#include <vector>
#include <set>
#include <mutex>
#include <cassert>
#include <iostream>
#include <algorithm>
#include <atomic>

static constexpr int NUM_THREADS = 8;
static constexpr int OPS_PER_THREAD = 5000;

void test_basic_correctness() {
    LockFreeStack<int> stack;

    stack.push(42);
    stack.push(17);
    stack.push(99);

    assert(stack.topAndPop() == 99);
    assert(stack.topAndPop() == 17);
    assert(stack.topAndPop() == 42);

    bool threw = false;
    try { stack.topAndPop(); }
    catch (const std::out_of_range&) { threw = true; }
    assert(threw);

    std::cout << "PASS: basic_correctness" << std::endl;
}

void test_concurrent_push_pop() {
    LockFreeStack<int> stack;
    std::vector<std::thread> threads;

    for (int t = 0; t < NUM_THREADS; ++t) {
        threads.emplace_back([&stack, t]() {
            for (int i = 0; i < OPS_PER_THREAD; ++i) {
                stack.push(t * OPS_PER_THREAD + i);
            }
        });
    }
    for (auto& th : threads) th.join();
    threads.clear();

    std::mutex mtx;
    std::vector<int> results;
    results.reserve(NUM_THREADS * OPS_PER_THREAD);
    std::atomic<int> pop_success{0};
    std::atomic<int> pop_fail{0};

    for (int t = 0; t < NUM_THREADS; ++t) {
        threads.emplace_back([&]() {
            for (int i = 0; i < OPS_PER_THREAD; ++i) {
                try {
                    int val = stack.topAndPop();
                    pop_success.fetch_add(1);
                    std::lock_guard<std::mutex> lk(mtx);
                    results.push_back(val);
                } catch (const std::out_of_range&) {
                    pop_fail.fetch_add(1);
                }
            }
        });
    }
    for (auto& th : threads) th.join();
    threads.clear();

    assert(pop_success.load() == NUM_THREADS * OPS_PER_THREAD);
    assert(pop_fail.load() == 0);

    std::sort(results.begin(), results.end());
    for (int i = 0; i < NUM_THREADS * OPS_PER_THREAD; ++i) {
        assert(results[i] == i);
    }

    std::cout << "PASS: concurrent_push_pop" << std::endl;
}

void test_mixed_concurrent() {
    LockFreeStack<int> stack;
    std::atomic<int> total_pushed{0};
    std::atomic<int> total_popped{0};
    std::mutex mtx;
    std::vector<int> all_pushed;
    std::vector<int> all_popped;
    std::vector<std::thread> threads;

    for (int t = 0; t < NUM_THREADS; ++t) {
        threads.emplace_back([&, t]() {
            std::vector<int> local_pushed;
            std::vector<int> local_popped;
            for (int i = 0; i < OPS_PER_THREAD; ++i) {
                int val = t * OPS_PER_THREAD + i;
                stack.push(val);
                local_pushed.push_back(val);
                total_pushed.fetch_add(1);

                try {
                    int popped = stack.topAndPop();
                    local_popped.push_back(popped);
                    total_popped.fetch_add(1);
                } catch (const std::out_of_range&) {}
            }
            std::lock_guard<std::mutex> lk(mtx);
            all_pushed.insert(all_pushed.end(), local_pushed.begin(), local_pushed.end());
            all_popped.insert(all_popped.end(), local_popped.begin(), local_popped.end());
        });
    }
    for (auto& th : threads) th.join();

    while (true) {
        try {
            int val = stack.topAndPop();
            all_popped.push_back(val);
            total_popped.fetch_add(1);
        } catch (const std::out_of_range&) {
            break;
        }
    }

    assert(total_pushed.load() == total_popped.load());

    std::sort(all_popped.begin(), all_popped.end());
    for (size_t i = 1; i < all_popped.size(); ++i) {
        assert(all_popped[i] != all_popped[i - 1]);
    }

    std::sort(all_pushed.begin(), all_pushed.end());
    for (int val : all_popped) {
        assert(std::binary_search(all_pushed.begin(), all_pushed.end(), val));
    }

    std::cout << "PASS: mixed_concurrent" << std::endl;
}

int main() {
    test_basic_correctness();
    test_concurrent_push_pop();
    test_mixed_concurrent();

    std::cout << "ALL_TESTS_PASSED" << std::endl;
    return 0;
}
