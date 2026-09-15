
#include "/app/concurrent_map.h"
#include <thread>
#include <vector>
#include <atomic>
#include <cstdio>

static const int NUM_THREADS = 4;
static const int KEYS_PER_THREAD = 2500;

int main() {
    // Very small initial capacity to force many resizes
    ConcurrentMap map(16);
    std::atomic<int> errors{0};

    // ---- Concurrent inserts with periodic verification ----
    {
        std::vector<std::thread> threads;
        for (int t = 0; t < NUM_THREADS; t++) {
            threads.emplace_back([&map, &errors, t]() {
                auto ctx = map.registerThread();
                uint64_t base = (uint64_t)(t + 1) * 1000000;
                for (int i = 0; i < KEYS_PER_THREAD; i++) {
                    uint64_t key = base + (uint64_t)i;
                    uint64_t val = (uint64_t)i + 10;
                    map.assign(key, val);

                    // Periodic verification: read back recent keys
                    if (i > 0 && i % 500 == 0) {
                        for (int j = i - 100; j <= i; j++) {
                            uint64_t k = base + (uint64_t)j;
                            uint64_t v = map.get(k);
                            uint64_t expected = (uint64_t)j + 10;
                            if (v != expected) {
                                errors.fetch_add(1, std::memory_order_relaxed);
                            }
                        }
                        map.quiescent(ctx);
                    }
                }
                map.quiescent(ctx);
                map.unregisterThread(ctx);
            });
        }
        for (auto& th : threads) th.join();
    }

    if (errors.load() > 0) {
        fprintf(stderr, "FAIL: %d errors during concurrent insertion/verification\n",
                errors.load());
        return 1;
    }

    // ---- Final verification: all keys must be present ----
    {
        auto ctx = map.registerThread();
        for (int t = 0; t < NUM_THREADS; t++) {
            uint64_t base = (uint64_t)(t + 1) * 1000000;
            for (int i = 0; i < KEYS_PER_THREAD; i++) {
                uint64_t key = base + (uint64_t)i;
                uint64_t expected = (uint64_t)i + 10;
                uint64_t got = map.get(key);
                if (got != expected) {
                    errors.fetch_add(1, std::memory_order_relaxed);
                    if (errors.load() <= 10) {
                        fprintf(stderr,
                            "  key=%lu expected=%lu got=%lu\n",
                            (unsigned long)key,
                            (unsigned long)expected,
                            (unsigned long)got);
                    }
                }
            }
        }
        map.quiescent(ctx);
        map.unregisterThread(ctx);
    }

    if (errors.load() > 0) {
        fprintf(stderr, "FAIL: %d keys have wrong value after resize stress\n",
                errors.load());
        return 1;
    }

    printf("PASS\n");
    return 0;
}
