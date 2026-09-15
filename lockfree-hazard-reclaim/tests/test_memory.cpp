//
// Memory reclamation test: verifies no nodes are leaked.
// Uses a Tracked wrapper type whose static counter tracks live instances.

#include <atomic>
#include <cassert>
#include <iostream>
#include <thread>
#include <vector>

struct Tracked {
    int value;
    inline static std::atomic<int> alive{0};

    Tracked() : value(0) { alive.fetch_add(1, std::memory_order_relaxed); }
    Tracked(int v) : value(v) { alive.fetch_add(1, std::memory_order_relaxed); }
    Tracked(const Tracked& o) : value(o.value) {
        alive.fetch_add(1, std::memory_order_relaxed);
    }
    Tracked(Tracked&& o) noexcept : value(o.value) {
        alive.fetch_add(1, std::memory_order_relaxed);
    }
    ~Tracked() { alive.fetch_sub(1, std::memory_order_relaxed); }
    Tracked& operator=(const Tracked&) = default;
    Tracked& operator=(Tracked&&) noexcept = default;
};

#include "lockfree_stack.hpp"

int main() {
    // Test 1: single-threaded — push N, pop N, destroy stack, check zero alive
    {
        assert(Tracked::alive.load() == 0);
        {
            LockFreeStack<Tracked> stack;
            const int N = 5000;
            for (int i = 0; i < N; i++) {
                stack.push(Tracked(i));
            }
            for (int i = 0; i < N; i++) {
                auto val = stack.try_pop();
                assert(val.has_value());
            }
            assert(stack.empty());
        }
        int leaked = Tracked::alive.load();
        if (leaked != 0) {
            std::cerr << "SINGLE_THREAD_LEAK: " << leaked
                      << " Tracked objects still alive" << std::endl;
            return 1;
        }
        std::cout << "SINGLE_THREAD_MEMORY_PASSED" << std::endl;
    }

    // Test 2: multi-threaded — push and pop from separate thread groups
    {
        Tracked::alive.store(0);
        {
            LockFreeStack<Tracked> stack;
            const int THREADS = 4;
            const int PER_THREAD = 2000;

            // Push phase
            {
                std::vector<std::thread> pushers;
                for (int t = 0; t < THREADS; t++) {
                    pushers.emplace_back([&stack, t]() {
                        for (int i = 0; i < PER_THREAD; i++) {
                            stack.push(Tracked(t * PER_THREAD + i));
                        }
                    });
                }
                for (auto& th : pushers) th.join();
            }

            // Pop phase
            {
                std::vector<std::thread> poppers;
                for (int t = 0; t < THREADS; t++) {
                    poppers.emplace_back([&stack]() {
                        while (true) {
                            auto val = stack.try_pop();
                            if (!val) break;
                        }
                    });
                }
                for (auto& th : poppers) th.join();
            }
        }
        int leaked = Tracked::alive.load();
        if (leaked != 0) {
            std::cerr << "MULTI_THREAD_LEAK: " << leaked
                      << " Tracked objects still alive" << std::endl;
            return 1;
        }
        std::cout << "MULTI_THREAD_MEMORY_PASSED" << std::endl;
    }

    std::cout << "MEMORY_TEST_PASSED" << std::endl;
    return 0;
}
