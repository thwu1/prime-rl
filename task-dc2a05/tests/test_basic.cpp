//
// Single-threaded correctness tests for ConcurrentHashMap.

#include "concurrent_hashmap.h"
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

int main() {
    // === Test 1: Insert and get ===
    {
        ConcurrentHashMap map(16);
        auto ctx = map.registerThread();

        for (uint64_t i = 1; i <= 10; i++) {
            uint64_t old = map.insert(i, i * 100);
            CHECK_EQ(old, 0UL);
        }
        for (uint64_t i = 1; i <= 10; i++) {
            CHECK_EQ(map.get(i), i * 100);
        }
        // Non-existent key
        CHECK_EQ(map.get(999), 0UL);

        map.quiescent(ctx);
        map.unregisterThread(ctx);
    }

    // === Test 2: Update existing keys ===
    {
        ConcurrentHashMap map(16);
        auto ctx = map.registerThread();

        for (uint64_t i = 1; i <= 10; i++) {
            map.insert(i, i * 100);
        }
        for (uint64_t i = 1; i <= 10; i++) {
            uint64_t old = map.insert(i, i * 200);
            CHECK_EQ(old, i * 100);
        }
        for (uint64_t i = 1; i <= 10; i++) {
            CHECK_EQ(map.get(i), i * 200);
        }

        map.quiescent(ctx);
        map.unregisterThread(ctx);
    }

    // === Test 3: Erase ===
    {
        ConcurrentHashMap map(32);
        auto ctx = map.registerThread();

        for (uint64_t i = 1; i <= 20; i++) {
            map.insert(i, i * 50);
        }

        // Erase first half
        for (uint64_t i = 1; i <= 10; i++) {
            uint64_t old = map.erase(i);
            CHECK_EQ(old, i * 50);
        }
        // Verify erased
        for (uint64_t i = 1; i <= 10; i++) {
            CHECK_EQ(map.get(i), 0UL);
        }
        // Verify remaining
        for (uint64_t i = 11; i <= 20; i++) {
            CHECK_EQ(map.get(i), i * 50);
        }
        // Erase non-existent
        CHECK_EQ(map.erase(999), 0UL);

        map.quiescent(ctx);
        map.unregisterThread(ctx);
    }

    // === Test 4: Re-insert after erase ===
    {
        ConcurrentHashMap map(16);
        auto ctx = map.registerThread();

        for (uint64_t i = 1; i <= 5; i++) {
            map.insert(i, i * 100);
        }
        for (uint64_t i = 1; i <= 5; i++) {
            map.erase(i);
        }
        for (uint64_t i = 1; i <= 5; i++) {
            CHECK_EQ(map.get(i), 0UL);
        }
        // Re-insert with different values
        for (uint64_t i = 1; i <= 5; i++) {
            uint64_t old = map.insert(i, i * 300);
            CHECK_EQ(old, 0UL);
        }
        for (uint64_t i = 1; i <= 5; i++) {
            CHECK_EQ(map.get(i), i * 300);
        }

        map.quiescent(ctx);
        map.unregisterThread(ctx);
    }

    // === Test 5: Many inserts (triggers migration in small table) ===
    {
        ConcurrentHashMap map(16);
        auto ctx = map.registerThread();

        for (uint64_t i = 1; i <= 100; i++) {
            map.insert(i, i * 7);
            if (i % 20 == 0) map.quiescent(ctx);
        }
        for (uint64_t i = 1; i <= 100; i++) {
            CHECK_EQ(map.get(i), i * 7);
        }
        // Table should have grown
        size_t cap = map.getRoot()->sizeMask + 1;
        CHECK(cap >= 128);

        map.quiescent(ctx);
        map.unregisterThread(ctx);
    }

    std::cout << "PASS" << std::endl;
    return 0;
}
