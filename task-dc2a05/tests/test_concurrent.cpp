//
// Multi-threaded correctness tests for ConcurrentHashMap.

#include "concurrent_hashmap.h"
#include <thread>
#include <vector>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <iostream>

#define CHECK(cond) do { \
    if (!(cond)) { \
        fprintf(stderr, "FAIL: %s  [%s:%d]\n", #cond, __FILE__, __LINE__); \
        exit(1); \
    } \
} while (0)

#define CHECK_EQ(a, b) do { \
    auto _a = (a); auto _b = (b); \
    if (_a != _b) { \
        fprintf(stderr, "FAIL: %s == %s  (%lu != %lu)  [%s:%d]\n", \
                #a, #b, (unsigned long)_a, (unsigned long)_b, __FILE__, __LINE__); \
        exit(1); \
    } \
} while (0)

static constexpr int NUM_THREADS = 4;
static constexpr int ITEMS_PER_THREAD = 10000;

// === Test 1: Concurrent inserts with disjoint key ranges ===
static void test_disjoint_inserts() {
    ConcurrentHashMap map(64);
    std::vector<std::thread> threads;

    for (int t = 0; t < NUM_THREADS; t++) {
        threads.emplace_back([&map, t]() {
            auto ctx = map.registerThread();
            uint64_t base = static_cast<uint64_t>(t) * ITEMS_PER_THREAD + 1;
            for (uint64_t i = 0; i < ITEMS_PER_THREAD; i++) {
                uint64_t key = base + i;
                map.insert(key, key * 10);
                if (i % 1000 == 0) map.quiescent(ctx);
            }
            map.quiescent(ctx);
            map.unregisterThread(ctx);
        });
    }
    for (auto& t : threads) t.join();

    // Verify all items are present
    auto ctx = map.registerThread();
    for (int t = 0; t < NUM_THREADS; t++) {
        uint64_t base = static_cast<uint64_t>(t) * ITEMS_PER_THREAD + 1;
        for (uint64_t i = 0; i < ITEMS_PER_THREAD; i++) {
            uint64_t key = base + i;
            uint64_t val = map.get(key);
            CHECK_EQ(val, key * 10);
        }
    }
    map.quiescent(ctx);
    map.unregisterThread(ctx);
    fprintf(stderr, "  disjoint inserts: OK\n");
}

// === Test 2: Concurrent inserts with overlapping keys ===
static void test_overlapping_inserts() {
    ConcurrentHashMap map(64);
    std::atomic<int> ready{0};
    std::vector<std::thread> threads;

    for (int t = 0; t < NUM_THREADS; t++) {
        threads.emplace_back([&map, t, &ready]() {
            auto ctx = map.registerThread();
            ready.fetch_add(1, std::memory_order_relaxed);
            while (ready.load(std::memory_order_relaxed) < NUM_THREADS) {}

            for (uint64_t i = 1; i <= 1000; i++) {
                // Values are >= 2 to avoid NullValue(0) and Redirect(1)
                map.insert(i, i * 10 + static_cast<uint64_t>(t) + 2);
                if (i % 200 == 0) map.quiescent(ctx);
            }
            map.quiescent(ctx);
            map.unregisterThread(ctx);
        });
    }
    for (auto& t : threads) t.join();

    // Each key must hold a value written by one of the threads
    auto ctx = map.registerThread();
    for (uint64_t i = 1; i <= 1000; i++) {
        uint64_t val = map.get(i);
        CHECK(val != 0);
        bool valid = false;
        for (int t = 0; t < NUM_THREADS; t++) {
            if (val == i * 10 + static_cast<uint64_t>(t) + 2) {
                valid = true;
                break;
            }
        }
        CHECK(valid);
    }
    map.quiescent(ctx);
    map.unregisterThread(ctx);
    fprintf(stderr, "  overlapping inserts: OK\n");
}

// === Test 3: Concurrent erase ===
static void test_concurrent_erase() {
    ConcurrentHashMap map(64);

    // First, insert items from a single thread
    {
        auto ctx = map.registerThread();
        for (uint64_t i = 1; i <= static_cast<uint64_t>(NUM_THREADS) * 2000; i++) {
            map.insert(i, i * 5);
            if (i % 500 == 0) map.quiescent(ctx);
        }
        map.quiescent(ctx);
        map.unregisterThread(ctx);
    }

    // Erase in parallel (disjoint ranges)
    std::vector<std::thread> threads;
    for (int t = 0; t < NUM_THREADS; t++) {
        threads.emplace_back([&map, t]() {
            auto ctx = map.registerThread();
            uint64_t base = static_cast<uint64_t>(t) * 2000 + 1;
            for (uint64_t i = 0; i < 2000; i++) {
                uint64_t key = base + i;
                uint64_t old = map.erase(key);
                CHECK_EQ(old, key * 5);
                if (i % 500 == 0) map.quiescent(ctx);
            }
            map.quiescent(ctx);
            map.unregisterThread(ctx);
        });
    }
    for (auto& t : threads) t.join();

    // Verify all erased
    auto ctx = map.registerThread();
    for (uint64_t i = 1; i <= static_cast<uint64_t>(NUM_THREADS) * 2000; i++) {
        CHECK_EQ(map.get(i), 0UL);
    }
    map.quiescent(ctx);
    map.unregisterThread(ctx);
    fprintf(stderr, "  concurrent erase: OK\n");
}

int main() {
    test_disjoint_inserts();
    test_overlapping_inserts();
    test_concurrent_erase();

    std::cout << "PASS" << std::endl;
    return 0;
}
