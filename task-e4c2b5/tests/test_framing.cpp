
#include "bipartite_buf.hpp"
#include <thread>
#include <atomic>
#include <cstdio>
#include <cstdint>
#include <cstring>

static constexpr size_t BUF_SIZE = 8192;
static constexpr size_t NUM_MESSAGES = 50000;
static constexpr size_t MAX_PAYLOAD = 500;

struct MsgHeader {
    uint32_t length;   // payload length in bytes
    uint32_t seq_num;  // sequence number
};

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

    // Producer: write framed messages [header][payload]
    std::thread producer([&]() {
        Rng rng(12345);
        for (size_t seq = 0; seq < NUM_MESSAGES && !error.load(std::memory_order_relaxed); seq++) {
            uint32_t payload_len = 1 + (rng.next() % MAX_PAYLOAD);
            size_t total = sizeof(MsgHeader) + payload_len;

            uint8_t* ptr;
            while (!(ptr = buf.WriteAcquire(total))) {
                if (error.load(std::memory_order_relaxed)) return;
                std::this_thread::yield();
            }

            // Write header
            MsgHeader hdr;
            hdr.length = payload_len;
            hdr.seq_num = static_cast<uint32_t>(seq);
            std::memcpy(ptr, &hdr, sizeof(hdr));

            // Write payload: each byte = (seq * 31 + byte_index) & 0xFF
            for (uint32_t i = 0; i < payload_len; i++) {
                ptr[sizeof(MsgHeader) + i] = static_cast<uint8_t>((seq * 31 + i) & 0xFF);
            }

            buf.WriteRelease(total);
        }
    });

    // Consumer: read and verify framed messages
    std::thread consumer([&]() {
        Rng rng(12345); // Same seed
        size_t seq = 0;
        while (seq < NUM_MESSAGES && !error.load(std::memory_order_relaxed)) {
            auto [ptr, avail] = buf.ReadAcquire();
            if (!ptr || avail == 0) {
                std::this_thread::yield();
                continue;
            }

            size_t offset = 0;
            while (offset < avail && seq < NUM_MESSAGES) {
                Rng saved = rng;
                uint32_t expected_payload = 1 + (rng.next() % MAX_PAYLOAD);
                size_t total = sizeof(MsgHeader) + expected_payload;

                if (offset + total > avail) {
                    rng = saved; // Restore RNG state — message not consumed
                    break;
                }

                // Parse header
                MsgHeader hdr;
                std::memcpy(&hdr, ptr + offset, sizeof(hdr));

                if (hdr.length != expected_payload) {
                    fprintf(stderr, "HEADER MISMATCH: seq=%zu expected_len=%u got_len=%u\n",
                            seq, expected_payload, hdr.length);
                    error.store(true, std::memory_order_relaxed);
                    buf.ReadRelease(avail);
                    return;
                }
                if (hdr.seq_num != static_cast<uint32_t>(seq)) {
                    fprintf(stderr, "SEQ MISMATCH: expected=%zu got=%u\n",
                            seq, hdr.seq_num);
                    error.store(true, std::memory_order_relaxed);
                    buf.ReadRelease(avail);
                    return;
                }

                // Verify payload
                for (uint32_t i = 0; i < hdr.length; i++) {
                    uint8_t expected = static_cast<uint8_t>((seq * 31 + i) & 0xFF);
                    uint8_t actual = ptr[offset + sizeof(MsgHeader) + i];
                    if (actual != expected) {
                        fprintf(stderr, "PAYLOAD MISMATCH: seq=%zu pos=%u expected=%d got=%d\n",
                                seq, i, (int)expected, (int)actual);
                        error.store(true, std::memory_order_relaxed);
                        buf.ReadRelease(avail);
                        return;
                    }
                }

                offset += total;
                seq++;
            }

            buf.ReadRelease(offset);
        }
    });

    producer.join();
    consumer.join();

    if (error.load()) {
        printf("FAIL: test_framing - message integrity violation\n");
        return 1;
    }
    printf("PASS: test_framing (%zu messages transferred)\n", NUM_MESSAGES);
    return 0;
}
