//
// Production readiness suite for SPSC shared-memory queue.
// All tests must pass before deployment.

#include "spsc_queue.h"
#include "shm_protocol.h"
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <thread>
#include <atomic>

static int g_failures = 0;
static int g_total = 0;

#define TEST_ASSERT(cond, fmt, ...) do { \
    if (!(cond)) { \
        printf("  ASSERTION FAILED: " fmt "\n", ##__VA_ARGS__); \
        g_failures++; \
        return; \
    } \
} while(0)

// Sends variable-length messages through the queue in a single thread,
// including messages that force position reuse near buffer capacity.
void test_data_integrity() {
    g_total++;
    printf("[1/4] data_integrity: ");

    const size_t cap = 1024;
    const size_t sentinel_sz = 256;
    char* mem = new char[cap + sentinel_sz];
    std::memset(mem + cap, 0xFE, sentinel_sz);

    auto* hdr = new spsc::QueueHeader();
    spsc::Producer prod(hdr, mem, cap);
    spsc::Consumer cons(hdr, mem, cap);

    // Fill buffer close to capacity: 11 * (80 + 4) = 924 bytes
    for (int i = 0; i < 11; i++) {
        uint8_t payload[80];
        for (int j = 0; j < 80; j++)
            payload[j] = (uint8_t)((i * 31 + j) & 0xFF);
        TEST_ASSERT(prod.write(payload, 80), "write stalled at msg %d", i);
    }
    prod.flush();

    for (int i = 0; i < 11; i++) {
        uint8_t out[128];
        uint32_t sz = cons.read(out, sizeof(out));
        TEST_ASSERT(sz == 80, "msg %d: expected 80 bytes, got %u", i, sz);
        for (int j = 0; j < 80; j++) {
            uint8_t exp = (uint8_t)((i * 31 + j) & 0xFF);
            TEST_ASSERT(out[j] == exp,
                        "msg %d byte %d: 0x%02X != 0x%02X", i, j, out[j], exp);
        }
    }

    // Write a message that exceeds remaining linear space.
    // Write offset = 924, message needs 120+4 = 124 bytes, 924+124 = 1048 > 1024.
    uint8_t big[120];
    for (int j = 0; j < 120; j++) big[j] = (uint8_t)(j ^ 0xCC);
    TEST_ASSERT(prod.write(big, 120), "large write failed");
    prod.flush();

    // Verify sentinel zone untouched
    for (size_t i = 0; i < sentinel_sz; i++) {
        TEST_ASSERT((uint8_t)mem[cap + i] == 0xFE,
                     "memory written past buffer end at offset +%zu", i);
    }

    // Read back and verify the large message
    uint8_t out[256];
    uint32_t sz = cons.read(out, sizeof(out));
    TEST_ASSERT(sz == 120, "large msg: expected 120 bytes, got %u", sz);
    for (int j = 0; j < 120; j++) {
        uint8_t exp = (uint8_t)(j ^ 0xCC);
        TEST_ASSERT(out[j] == exp,
                    "large msg byte %d: 0x%02X != 0x%02X", j, out[j], exp);
    }

    printf("PASS\n");
    delete[] mem;
    delete hdr;
}

// Concurrent producer/consumer exchanging 50K ordered messages.
void test_concurrent_exchange() {
    g_total++;
    printf("[2/4] concurrent_exchange: ");

    const size_t cap = 1 << 20;
    auto* hdr = new spsc::QueueHeader();
    char* buf = new char[cap]();
    spsc::Producer prod(hdr, buf, cap);
    spsc::Consumer cons(hdr, buf, cap);

    const int N = 50000;
    std::atomic<bool> done{false};

    std::thread producer([&]() {
        for (int i = 0; i < N; i++) {
            uint32_t val = static_cast<uint32_t>(i);
            while (!prod.write(&val, sizeof(val))) {}
            if ((i & 0x3FF) == 0x3FF) prod.flush();
        }
        prod.flush();
        done.store(true, std::memory_order_release);
    });

    int received = 0;
    long spins = 0;
    bool ok = true;

    while (received < N) {
        uint32_t val;
        uint32_t sz = cons.read(&val, sizeof(val));
        if (sz == sizeof(uint32_t)) {
            if (val != static_cast<uint32_t>(received)) {
                printf("FAIL (msg %d: got %u)\n", received, val);
                ok = false;
                break;
            }
            received++;
            spins = 0;
        } else {
            spins++;
            if (spins > 200000000L &&
                done.load(std::memory_order_acquire)) {
                printf("FAIL (stalled at %d/%d)\n", received, N);
                ok = false;
                break;
            }
        }
    }

    producer.join();
    if (ok) printf("PASS (%d msgs)\n", received);
    else g_failures++;

    delete[] buf;
    delete hdr;
}

// Verifies protocol handshake: create must establish identity,
// open must reject tampered segments.
void test_protocol_lifecycle() {
    g_total++;
    printf("[3/4] protocol_lifecycle: ");

    const char* path = "/tmp/_stress_proto.dat";
    const size_t cap = 4096;

    void* ptr = spsc::ShmManager::create(path, cap);
    auto* h = spsc::ShmManager::get_header(ptr);

    TEST_ASSERT(h->magic == spsc::kProtocolMagic,
                "identity field not initialized");
    TEST_ASSERT(h->major_version == spsc::kMajorVersion,
                "version field not initialized");
    TEST_ASSERT(h->queue_capacity == cap,
                "capacity field incorrect");

    // Tamper with the segment and verify rejection on open
    h->magic = 0xBADF00D;
    bool rejected = false;
    try { spsc::ShmManager::open(path); }
    catch (...) { rejected = true; }
    TEST_ASSERT(rejected, "tampered segment accepted");

    spsc::ShmManager::destroy(path, ptr,
                              sizeof(spsc::ProtocolHeader) + cap);
    printf("PASS\n");
}

// Writes many messages without flush; consumer should not see all of
// them until flush is called.
void test_deferred_visibility() {
    g_total++;
    printf("[4/4] deferred_visibility: ");

    const size_t cap = 1 << 20;
    auto* hdr = new spsc::QueueHeader();
    auto* buf = new char[cap]();
    spsc::Producer prod(hdr, buf, cap);
    spsc::Consumer cons(hdr, buf, cap);

    // 700 messages * (100 payload + 4 prefix) = 72 800 bytes
    const int msg_count = 700;
    uint8_t payload[100];
    for (int i = 0; i < msg_count; i++) {
        for (int j = 0; j < 100; j++)
            payload[j] = (uint8_t)(i + j);
        prod.write(payload, 100);
    }
    // No flush yet

    int visible = 0;
    uint8_t tmp[256];
    while (cons.read(tmp, sizeof(tmp)) > 0) visible++;
    int pre_flush = visible;

    TEST_ASSERT(visible < msg_count,
                "all %d messages visible before flush (saw %d)",
                msg_count, visible);

    prod.flush();
    while (cons.read(tmp, sizeof(tmp)) > 0) visible++;

    TEST_ASSERT(visible == msg_count,
                "after flush expected %d messages, got %d",
                msg_count, visible);

    printf("PASS (%d/%d visible before flush)\n", pre_flush, msg_count);
    delete[] buf;
    delete hdr;
}

int main() {
    printf("=== SPSC Queue Production Readiness Suite ===\n\n");
    test_data_integrity();
    test_concurrent_exchange();
    test_protocol_lifecycle();
    test_deferred_visibility();
    printf("\n=== %d/%d passed ===\n", g_total - g_failures, g_total);
    return g_failures > 0 ? 1 : 0;
}
