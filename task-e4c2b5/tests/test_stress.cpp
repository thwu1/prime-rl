
#include "bipartite_buf.hpp"
#include <thread>
#include <atomic>
#include <cstdio>
#include <cstdint>

static constexpr size_t BUF_SIZE = 4096;
static constexpr size_t NUM_BLOCKS = 100000;
static constexpr size_t MAX_BLOCK_SIZE = 200;

// Deterministic LCG PRNG
struct Rng {
    uint64_t state;
    explicit Rng(uint64_t seed) : state(seed) {}
    uint32_t next() {
        state = state * 6364136223846793005ULL + 1442695040888963407ULL;
        return static_cast<uint32_t>(state >> 33);
    }
};

int main() {
    lockfree::spsc::BipartiteBuf<uint8_t, BUF_SIZE> buf;
    std::atomic<bool> error{false};

    std::thread producer([&]() {
        Rng rng(42);
        for (size_t seq = 0; seq < NUM_BLOCKS && !error.load(std::memory_order_relaxed); seq++) {
            size_t block_size = 1 + (rng.next() % MAX_BLOCK_SIZE);
            uint8_t* ptr;
            while (!(ptr = buf.WriteAcquire(block_size))) {
                if (error.load(std::memory_order_relaxed)) return;
                std::this_thread::yield();
            }
            for (size_t i = 0; i < block_size; i++) {
                ptr[i] = static_cast<uint8_t>((seq ^ i) & 0xFF);
            }
            buf.WriteRelease(block_size);
        }
    });

    std::thread consumer([&]() {
        Rng rng(42); // Same seed — generates same block sizes
        size_t seq = 0;
        while (seq < NUM_BLOCKS && !error.load(std::memory_order_relaxed)) {
            auto [ptr, avail] = buf.ReadAcquire();
            if (!ptr || avail == 0) {
                std::this_thread::yield();
                continue;
            }

            size_t offset = 0;
            while (offset < avail && seq < NUM_BLOCKS) {
                Rng saved = rng;
                size_t block_size = 1 + (rng.next() % MAX_BLOCK_SIZE);
                if (offset + block_size > avail) {
                    rng = saved; // Restore RNG state — block not consumed
                    break;
                }

                for (size_t i = 0; i < block_size; i++) {
                    uint8_t expected = static_cast<uint8_t>((seq ^ i) & 0xFF);
                    if (ptr[offset + i] != expected) {
                        fprintf(stderr, "CORRUPTION: seq=%zu pos=%zu expected=%d got=%d\n",
                                seq, i, (int)expected, (int)ptr[offset + i]);
                        error.store(true, std::memory_order_relaxed);
                        buf.ReadRelease(avail);
                        return;
                    }
                }
                offset += block_size;
                seq++;
            }

            buf.ReadRelease(offset);
        }
    });

    producer.join();
    consumer.join();

    if (error.load()) {
        printf("FAIL: test_stress - data corruption\n");
        return 1;
    }
    printf("PASS: test_stress (%zu blocks transferred)\n", NUM_BLOCKS);
    return 0;
}
