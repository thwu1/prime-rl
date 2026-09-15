
#include "/app/concurrent_map.h"
#include <cstdio>
#include <cstdlib>

#define CHECK(cond) do { \
    if (!(cond)) { \
        fprintf(stderr, "FAIL: %s  (line %d)\n", #cond, __LINE__); \
        return 1; \
    } \
} while (0)

int main() {
    ConcurrentMap map(64);
    auto ctx = map.registerThread();

    // --- Insert and retrieve ---
    CHECK(map.assign(100, 42) == 0);   // new key
    CHECK(map.get(100) == 42);

    // --- Update existing key ---
    CHECK(map.assign(100, 99) == 42);  // old value was 42
    CHECK(map.get(100) == 99);

    // --- Get non-existent key ---
    CHECK(map.get(200) == 0);

    // --- Erase ---
    CHECK(map.erase(100) == 99);       // returns old value
    CHECK(map.get(100) == 0);          // now absent

    // --- Erase non-existent ---
    CHECK(map.erase(300) == 0);

    // --- Re-insert after erase ---
    CHECK(map.assign(100, 7) == 0);    // treated as new
    CHECK(map.get(100) == 7);

    // --- Erase and re-insert with different value ---
    CHECK(map.erase(100) == 7);
    CHECK(map.assign(100, 55) == 0);
    CHECK(map.get(100) == 55);

    // --- Multiple keys ---
    for (uint64_t i = 2; i <= 48; i++) {
        CHECK(map.assign(i, i * 10) == 0);
    }
    for (uint64_t i = 2; i <= 48; i++) {
        CHECK(map.get(i) == i * 10);
    }

    // --- Update some, erase others ---
    for (uint64_t i = 2; i <= 48; i += 2) {
        CHECK(map.assign(i, i * 100) == i * 10);
    }
    for (uint64_t i = 3; i <= 48; i += 2) {
        CHECK(map.erase(i) == i * 10);
    }
    // Verify
    for (uint64_t i = 2; i <= 48; i++) {
        if (i % 2 == 0) {
            CHECK(map.get(i) == i * 100);
        } else {
            CHECK(map.get(i) == 0);
        }
    }

    // --- Large batch to test basic capacity ---
    for (uint64_t i = 1000; i < 1200; i++) {
        map.assign(i, i + 5);
    }
    for (uint64_t i = 1000; i < 1200; i++) {
        CHECK(map.get(i) == i + 5);
    }

    map.quiescent(ctx);
    map.unregisterThread(ctx);

    printf("PASS\n");
    return 0;
}
