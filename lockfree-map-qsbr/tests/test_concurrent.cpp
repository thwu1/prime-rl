
#include "/app/concurrent_map.h"
#include <thread>
#include <vector>
#include <atomic>
#include <cstdio>

static const int NUM_THREADS = 4;
static const int KEYS_PER_THREAD = 10000;

int main() {
    ConcurrentMap map(64);
    std::atomic<int> errors{0};

    // ---- Phase 1: concurrent inserts with disjoint key ranges ----
    {
        std::vector<std::thread> threads;
        for (int t = 0; t < NUM_THREADS; t++) {
            threads.emplace_back([&map, &errors, t]() {
                auto ctx = map.registerThread();
                uint64_t base = (uint64_t)(t + 1) * 100000;
                for (int i = 0; i < KEYS_PER_THREAD; i++) {
                    uint64_t key = base + (uint64_t)i;
                    uint64_t val = key + 10;  // values >= 100010
                    uint64_t prev = map.assign(key, val);
                    if (prev != 0) {
                        errors.fetch_add(1, std::memory_order_relaxed);
                    }
                    if (i % 2000 == 0) map.quiescent(ctx);
                }
                map.quiescent(ctx);
                map.unregisterThread(ctx);
            });
        }
        for (auto& th : threads) th.join();
    }

    if (errors.load() > 0) {
        fprintf(stderr, "FAIL: %d unexpected non-zero returns from assign in phase 1\n",
                errors.load());
        return 1;
    }

    // ---- Verify phase 1 ----
    {
        auto ctx = map.registerThread();
        for (int t = 0; t < NUM_THREADS; t++) {
            uint64_t base = (uint64_t)(t + 1) * 100000;
            for (int i = 0; i < KEYS_PER_THREAD; i++) {
                uint64_t key = base + (uint64_t)i;
                uint64_t expected = key + 10;
                uint64_t got = map.get(key);
                if (got != expected) {
                    errors.fetch_add(1, std::memory_order_relaxed);
                }
            }
        }
        map.quiescent(ctx);
        map.unregisterThread(ctx);
    }

    if (errors.load() > 0) {
        fprintf(stderr, "FAIL: %d verification errors after phase 1\n",
                errors.load());
        return 1;
    }

    // ---- Phase 2: concurrent erase of even-indexed keys ----
    {
        std::vector<std::thread> threads;
        for (int t = 0; t < NUM_THREADS; t++) {
            threads.emplace_back([&map, &errors, t]() {
                auto ctx = map.registerThread();
                uint64_t base = (uint64_t)(t + 1) * 100000;
                for (int i = 0; i < KEYS_PER_THREAD; i += 2) {
                    uint64_t key = base + (uint64_t)i;
                    uint64_t expected_val = key + 10;
                    uint64_t prev = map.erase(key);
                    if (prev != expected_val) {
                        errors.fetch_add(1, std::memory_order_relaxed);
                    }
                    if (i % 2000 == 0) map.quiescent(ctx);
                }
                map.quiescent(ctx);
                map.unregisterThread(ctx);
            });
        }
        for (auto& th : threads) th.join();
    }

    if (errors.load() > 0) {
        fprintf(stderr, "FAIL: %d errors in phase 2 erase\n", errors.load());
        return 1;
    }

    // ---- Verify phase 2 ----
    {
        auto ctx = map.registerThread();
        for (int t = 0; t < NUM_THREADS; t++) {
            uint64_t base = (uint64_t)(t + 1) * 100000;
            for (int i = 0; i < KEYS_PER_THREAD; i++) {
                uint64_t key = base + (uint64_t)i;
                uint64_t got = map.get(key);
                if (i % 2 == 0) {
                    // Should be erased
                    if (got != 0) {
                        errors.fetch_add(1, std::memory_order_relaxed);
                    }
                } else {
                    // Should still exist
                    uint64_t expected = key + 10;
                    if (got != expected) {
                        errors.fetch_add(1, std::memory_order_relaxed);
                    }
                }
            }
        }
        map.quiescent(ctx);
        map.unregisterThread(ctx);
    }

    if (errors.load() > 0) {
        fprintf(stderr, "FAIL: %d verification errors after phase 2\n",
                errors.load());
        return 1;
    }

    printf("PASS\n");
    return 0;
}
