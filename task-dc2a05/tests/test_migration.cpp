//
// Table migration and QSBR tests for ConcurrentHashMap.

#include "concurrent_hashmap.h"
#include <thread>
#include <vector>
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

// === Test 1: Single-threaded migration (small initial table) ===
static void test_single_thread_migration() {
    ConcurrentHashMap map(16);
    auto ctx = map.registerThread();

    // Insert 200 items into a table of capacity 16.
    // This should trigger migrations: 16 -> 32 -> 64 -> 128 -> 256
    for (uint64_t i = 1; i <= 200; i++) {
        map.insert(i, i * 100);
        if (i % 30 == 0) map.quiescent(ctx);
    }

    // Verify all items survived the migrations
    for (uint64_t i = 1; i <= 200; i++) {
        CHECK_EQ(map.get(i), i * 100);
    }

    // Verify table has grown appropriately
    size_t cap = map.getRoot()->sizeMask + 1;
    CHECK(cap >= 256);

    map.quiescent(ctx);
    map.unregisterThread(ctx);
    fprintf(stderr, "  single-thread migration: OK\n");
}

// === Test 2: Concurrent inserts causing migration ===
static void test_concurrent_migration() {
    ConcurrentHashMap map(16);
    const int N = 4;
    const int M = 5000;

    std::vector<std::thread> threads;
    for (int t = 0; t < N; t++) {
        threads.emplace_back([&map, t]() {
            auto ctx = map.registerThread();
            uint64_t base = static_cast<uint64_t>(t) * M + 1;
            for (uint64_t i = 0; i < static_cast<uint64_t>(M); i++) {
                map.insert(base + i, (base + i) * 10);
                if (i % 200 == 0) map.quiescent(ctx);
            }
            map.quiescent(ctx);
            map.unregisterThread(ctx);
        });
    }
    for (auto& t : threads) t.join();

    // Verify ALL items from all threads
    auto ctx = map.registerThread();
    for (int t = 0; t < N; t++) {
        uint64_t base = static_cast<uint64_t>(t) * M + 1;
        for (uint64_t i = 0; i < static_cast<uint64_t>(M); i++) {
            uint64_t key = base + i;
            uint64_t val = map.get(key);
            CHECK_EQ(val, key * 10);
        }
    }

    // Table should be large enough
    size_t cap = map.getRoot()->sizeMask + 1;
    CHECK(cap >= static_cast<size_t>(N * M));

    map.quiescent(ctx);
    map.unregisterThread(ctx);
    fprintf(stderr, "  concurrent migration: OK\n");
}

// === Test 3: Insert + erase + re-insert cycles with migration ===
static void test_insert_erase_cycles() {
    ConcurrentHashMap map(16);
    auto ctx = map.registerThread();

    for (int round = 0; round < 5; round++) {
        // Insert 50 items
        for (uint64_t i = 1; i <= 50; i++) {
            uint64_t val = i * static_cast<uint64_t>(round + 1) * 100;
            // Ensure value >= 2 (never 0 or 1)
            if (val < 2) val = 2;
            map.insert(i, val);
        }
        map.quiescent(ctx);

        // Verify all present
        for (uint64_t i = 1; i <= 50; i++) {
            uint64_t expected = i * static_cast<uint64_t>(round + 1) * 100;
            if (expected < 2) expected = 2;
            CHECK_EQ(map.get(i), expected);
        }

        // Erase first 25
        for (uint64_t i = 1; i <= 25; i++) {
            uint64_t old = map.erase(i);
            CHECK(old != 0);
        }
        map.quiescent(ctx);

        // Verify erased
        for (uint64_t i = 1; i <= 25; i++) {
            CHECK_EQ(map.get(i), 0UL);
        }
        // Verify remaining
        for (uint64_t i = 26; i <= 50; i++) {
            CHECK(map.get(i) != 0);
        }
    }

    map.unregisterThread(ctx);
    fprintf(stderr, "  insert/erase cycles: OK\n");
}

// === Test 4: Verify table capacity growth is roughly correct ===
static void test_capacity_growth() {
    ConcurrentHashMap map(16);
    auto ctx = map.registerThread();

    // Insert just over 75% of 16 = 12 items
    for (uint64_t i = 1; i <= 13; i++) {
        map.insert(i, i + 100);
    }
    map.quiescent(ctx);

    size_t cap = map.getRoot()->sizeMask + 1;
    CHECK(cap >= 32);  // Must have migrated at least once

    // Verify all items intact
    for (uint64_t i = 1; i <= 13; i++) {
        CHECK_EQ(map.get(i), i + 100);
    }

    map.unregisterThread(ctx);
    fprintf(stderr, "  capacity growth: OK\n");
}

int main() {
    test_single_thread_migration();
    test_concurrent_migration();
    test_insert_erase_cycles();
    test_capacity_growth();

    std::cout << "PASS" << std::endl;
    return 0;
}
