
#include "spsc_queue.h"
#include "latency_sampler.h"
#include <thread>
#include <iostream>
#include <cstring>
#include <cstdlib>
#include <atomic>
#include <algorithm>
#include <chrono>

// ================================================================
// Test: basic push/pop with power-of-2 capacities
// ================================================================
int test_basic() {
    size_t caps[] = {8, 16, 64, 256, 1024};
    for (size_t cap : caps) {
        SPSCQueue<int> q(cap);

        // Fill to capacity
        size_t count = 0;
        while (q.push(static_cast<int>(count))) {
            count++;
            if (count > cap + 10) {
                std::cerr << "basic: cap=" << cap << " queue never reported full" << std::endl;
                return 1;
            }
        }
        if (count != cap) {
            std::cerr << "basic: cap=" << cap << " stored " << count
                      << " items, expected " << cap << std::endl;
            return 1;
        }

        // Verify FIFO order
        for (size_t i = 0; i < count; i++) {
            auto v = q.pop();
            if (!v.has_value() || *v != static_cast<int>(i)) {
                std::cerr << "basic: cap=" << cap << " wrong value at " << i << std::endl;
                return 1;
            }
        }
        if (q.pop().has_value()) {
            std::cerr << "basic: cap=" << cap << " not empty after drain" << std::endl;
            return 1;
        }

        // Wraparound: push/pop many rounds with pow2 capacity
        int wp = 0, wc = 0;
        for (int round = 0; round < 2000; round++) {
            for (int i = 0; i < 5; i++) {
                if (q.push(wp)) wp++;
            }
            for (int i = 0; i < 5; i++) {
                auto v = q.pop();
                if (v.has_value()) {
                    if (*v != wc) {
                        std::cerr << "basic: cap=" << cap << " wraparound expected "
                                  << wc << " got " << *v << std::endl;
                        return 1;
                    }
                    wc++;
                }
            }
        }
        while (auto v = q.pop()) {
            if (*v != wc) {
                std::cerr << "basic: cap=" << cap << " drain expected "
                          << wc << " got " << *v << std::endl;
                return 1;
            }
            wc++;
        }
        if (wp != wc) {
            std::cerr << "basic: cap=" << cap << " pushed=" << wp
                      << " popped=" << wc << std::endl;
            return 1;
        }
    }
    return 0;
}

// ================================================================
// Test: push/pop with non-power-of-2 capacities + heavy wraparound
// ================================================================
int test_nonpow2() {
    size_t caps[] = {7, 10, 50, 100, 255, 500, 1000};
    for (size_t cap : caps) {
        SPSCQueue<int> q(cap);

        // Fill to capacity
        size_t count = 0;
        while (q.push(static_cast<int>(count))) {
            count++;
            if (count > cap + 10) {
                std::cerr << "nonpow2: cap=" << cap << " never full" << std::endl;
                return 1;
            }
        }
        if (count != cap) {
            std::cerr << "nonpow2: cap=" << cap << " stored " << count
                      << " expected " << cap << std::endl;
            return 1;
        }

        // Verify FIFO order
        for (size_t i = 0; i < count; i++) {
            auto v = q.pop();
            if (!v.has_value() || *v != static_cast<int>(i)) {
                std::cerr << "nonpow2: cap=" << cap << " wrong value at " << i
                          << (v.has_value() ? (std::string(" got ") + std::to_string(*v)) : " (empty)")
                          << std::endl;
                return 1;
            }
        }
        if (q.pop().has_value()) {
            std::cerr << "nonpow2: cap=" << cap << " not empty" << std::endl;
            return 1;
        }

        // Extensive wraparound test
        int wp = 0, wc = 0;
        for (int round = 0; round < 5000; round++) {
            for (int i = 0; i < 7; i++) {
                if (q.push(wp)) wp++;
            }
            for (int i = 0; i < 7; i++) {
                auto v = q.pop();
                if (v.has_value()) {
                    if (*v != wc) {
                        std::cerr << "nonpow2: cap=" << cap << " round=" << round
                                  << " expected " << wc << " got " << *v << std::endl;
                        return 1;
                    }
                    wc++;
                }
            }
        }
        // Drain
        while (auto v = q.pop()) {
            if (*v != wc) {
                std::cerr << "nonpow2: cap=" << cap << " drain expected "
                          << wc << " got " << *v << std::endl;
                return 1;
            }
            wc++;
        }
        if (wp != wc) {
            std::cerr << "nonpow2: cap=" << cap << " pushed=" << wp
                      << " popped=" << wc << std::endl;
            return 1;
        }
    }
    return 0;
}

// ================================================================
// Test: concurrent producer/consumer, non-pow2 capacity
// ================================================================
int test_concurrent() {
    constexpr int64_t N = 500000;
    SPSCQueue<int64_t> q(500);  // non-pow2
    std::atomic<int64_t> errors{0};
    std::atomic<int64_t> received{0};
    std::atomic<bool> producer_done{false};

    std::thread producer([&]() {
        for (int64_t i = 0; i < N; i++) {
            while (!q.push(i)) {}
        }
        producer_done.store(true, std::memory_order_release);
    });

    std::thread consumer([&]() {
        int64_t expected = 0;
        while (true) {
            auto v = q.pop();
            if (v.has_value()) {
                if (*v != expected) {
                    errors.fetch_add(1, std::memory_order_relaxed);
                }
                expected++;
                received.store(expected, std::memory_order_relaxed);
            } else if (producer_done.load(std::memory_order_acquire)) {
                // Drain remaining
                while (auto v2 = q.pop()) {
                    if (*v2 != expected) {
                        errors.fetch_add(1, std::memory_order_relaxed);
                    }
                    expected++;
                    received.store(expected, std::memory_order_relaxed);
                }
                break;
            }
        }
    });

    producer.join();
    consumer.join();

    if (errors.load() > 0) {
        std::cerr << "concurrent: " << errors.load() << " value errors" << std::endl;
        return 1;
    }
    if (received.load() != N) {
        std::cerr << "concurrent: expected " << N << " items, got "
                  << received.load() << std::endl;
        return 1;
    }
    return 0;
}

// ================================================================
// Test: concurrent (small N for ThreadSanitizer), pow2 capacity
// ================================================================
int test_concurrent_small() {
    constexpr int64_t N = 20000;
    SPSCQueue<int64_t> q(128);  // pow2 so index bug doesn't interfere
    std::atomic<int64_t> errors{0};
    std::atomic<bool> done{false};

    std::thread producer([&]() {
        for (int64_t i = 0; i < N; i++) {
            while (!q.push(i)) {}
        }
        done.store(true, std::memory_order_release);
    });

    std::thread consumer([&]() {
        int64_t expected = 0;
        while (true) {
            auto v = q.pop();
            if (v.has_value()) {
                if (*v != expected) errors.fetch_add(1);
                expected++;
            } else if (done.load(std::memory_order_acquire)) {
                while (auto v2 = q.pop()) {
                    if (*v2 != expected) errors.fetch_add(1);
                    expected++;
                }
                break;
            }
        }
    });

    producer.join();
    consumer.join();

    if (errors.load() > 0) {
        std::cerr << "concurrent_small: " << errors.load() << " errors" << std::endl;
        return 1;
    }
    return 0;
}

// ================================================================
// Test: struct layout — false sharing prevention
// ================================================================
int test_layout() {
    // Without cache-line padding, SPSCQueue<int> is compact (~32 bytes).
    // With alignas(64) on head_ and tail_, it must grow to >= 128 bytes
    // to place each atomic on its own cache line.
    size_t sz = sizeof(SPSCQueue<int>);
    if (sz < 128) {
        std::cerr << "layout: sizeof(SPSCQueue<int>) = " << sz
                  << ", expected >= 128 (head_ and tail_ must be on"
                  << " separate cache lines)" << std::endl;
        return 1;
    }
    return 0;
}

// ================================================================
// Test: batch push/pop — single-threaded correctness
// ================================================================
int test_batch_basic() {
    // --- Test with non-pow2 capacity ---
    {
        SPSCQueue<int> q(100);

        // push_batch: push 20 items
        int items[20];
        for (int i = 0; i < 20; i++) items[i] = i;
        size_t pushed = q.push_batch(items, 20);
        if (pushed != 20) {
            std::cerr << "batch_basic: push_batch(20) returned " << pushed << std::endl;
            return 1;
        }

        // Pop individually and verify order
        for (int i = 0; i < 20; i++) {
            auto v = q.pop();
            if (!v.has_value() || *v != i) {
                std::cerr << "batch_basic: after push_batch, pop wrong at " << i << std::endl;
                return 1;
            }
        }

        // Push individually, pop_batch
        for (int i = 0; i < 30; i++) {
            if (!q.push(i + 100)) {
                std::cerr << "batch_basic: individual push failed at " << i << std::endl;
                return 1;
            }
        }
        int out[30];
        size_t popped = q.pop_batch(out, 30);
        if (popped != 30) {
            std::cerr << "batch_basic: pop_batch(30) returned " << popped << std::endl;
            return 1;
        }
        for (int i = 0; i < 30; i++) {
            if (out[i] != i + 100) {
                std::cerr << "batch_basic: pop_batch wrong at " << i << std::endl;
                return 1;
            }
        }

        // Partial push_batch (more than capacity)
        int big[200];
        for (int i = 0; i < 200; i++) big[i] = i;
        pushed = q.push_batch(big, 200);
        if (pushed != 100) {
            std::cerr << "batch_basic: partial push expected 100, got " << pushed << std::endl;
            return 1;
        }

        // Pop all
        int out2[200];
        popped = q.pop_batch(out2, 200);
        if (popped != 100) {
            std::cerr << "batch_basic: pop expected 100, got " << popped << std::endl;
            return 1;
        }
        for (size_t i = 0; i < popped; i++) {
            if (out2[i] != static_cast<int>(i)) {
                std::cerr << "batch_basic: partial pop wrong at " << i << std::endl;
                return 1;
            }
        }

        // Pop from empty
        popped = q.pop_batch(out2, 10);
        if (popped != 0) {
            std::cerr << "batch_basic: pop from empty returned " << popped << std::endl;
            return 1;
        }

        // Push zero items
        pushed = q.push_batch(big, 0);
        if (pushed != 0) {
            std::cerr << "batch_basic: push_batch(0) returned " << pushed << std::endl;
            return 1;
        }
    }

    // --- Test with pow2 capacity ---
    {
        SPSCQueue<int> q(64);

        int items[40];
        for (int i = 0; i < 40; i++) items[i] = i + 1000;
        size_t pushed = q.push_batch(items, 40);
        if (pushed != 40) {
            std::cerr << "batch_basic pow2: push_batch(40) returned " << pushed << std::endl;
            return 1;
        }

        int out[40];
        size_t popped = q.pop_batch(out, 40);
        if (popped != 40) {
            std::cerr << "batch_basic pow2: pop_batch(40) returned " << popped << std::endl;
            return 1;
        }
        for (int i = 0; i < 40; i++) {
            if (out[i] != i + 1000) {
                std::cerr << "batch_basic pow2: wrong value at " << i << std::endl;
                return 1;
            }
        }
    }

    return 0;
}

// ================================================================
// Test: batch operations wrapping around the ring buffer boundary
// ================================================================
int test_batch_wrap() {
    SPSCQueue<int> q(10);  // small non-pow2

    // Advance head and tail to position 7
    for (int i = 0; i < 7; i++) {
        if (!q.push(i)) {
            std::cerr << "batch_wrap: prep push failed" << std::endl;
            return 1;
        }
    }
    for (int i = 0; i < 7; i++) {
        auto v = q.pop();
        if (!v.has_value() || *v != i) {
            std::cerr << "batch_wrap: prep pop failed at " << i << std::endl;
            return 1;
        }
    }

    // push_batch of 8 items: wraps from position 7 through 0 to position 4
    int items[8];
    for (int i = 0; i < 8; i++) items[i] = 100 + i;
    size_t pushed = q.push_batch(items, 8);
    if (pushed != 8) {
        std::cerr << "batch_wrap: push_batch(8) returned " << pushed << std::endl;
        return 1;
    }

    // pop_batch also wraps
    int out[8];
    size_t popped = q.pop_batch(out, 8);
    if (popped != 8) {
        std::cerr << "batch_wrap: pop_batch(8) returned " << popped << std::endl;
        return 1;
    }
    for (int i = 0; i < 8; i++) {
        if (out[i] != 100 + i) {
            std::cerr << "batch_wrap: wrong value at " << i
                      << " expected " << (100 + i) << " got " << out[i] << std::endl;
            return 1;
        }
    }

    // Extended: many rounds of batch push + pop with wrapping
    for (int round = 0; round < 1000; round++) {
        int batch[6];
        for (int i = 0; i < 6; i++) batch[i] = round * 6 + i;

        size_t p = q.push_batch(batch, 6);
        if (p != 6) {
            std::cerr << "batch_wrap: round " << round << " push returned " << p << std::endl;
            return 1;
        }

        int bout[6];
        size_t pp = q.pop_batch(bout, 6);
        if (pp != 6) {
            std::cerr << "batch_wrap: round " << round << " pop returned " << pp << std::endl;
            return 1;
        }
        for (int i = 0; i < 6; i++) {
            if (bout[i] != round * 6 + i) {
                std::cerr << "batch_wrap: round " << round << " wrong at " << i
                          << " expected " << (round * 6 + i) << " got " << bout[i] << std::endl;
                return 1;
            }
        }
    }

    return 0;
}

// ================================================================
// Test: batch operations under concurrency
// ================================================================
int test_batch_concurrent() {
    constexpr int64_t N = 100000;
    SPSCQueue<int64_t> q(200);  // non-pow2
    std::atomic<int64_t> errors{0};
    std::atomic<bool> done{false};

    std::thread producer([&]() {
        int64_t seq = 0;
        while (seq < N) {
            int64_t batch[8];
            int64_t remaining = N - seq;
            size_t bsz = remaining < 8 ? static_cast<size_t>(remaining) : 8;
            for (size_t i = 0; i < bsz; i++) batch[i] = seq + static_cast<int64_t>(i);
            size_t pushed = q.push_batch(batch, bsz);
            if (pushed > 0) {
                seq += static_cast<int64_t>(pushed);
            } else {
                // Fallback to single push
                while (seq < N && !q.push(seq)) {}
                if (seq < N) seq++;
            }
        }
        done.store(true, std::memory_order_release);
    });

    std::thread consumer([&]() {
        int64_t expected = 0;
        while (true) {
            int64_t out[8];
            size_t got = q.pop_batch(out, 8);
            for (size_t i = 0; i < got; i++) {
                if (out[i] != expected) {
                    errors.fetch_add(1, std::memory_order_relaxed);
                }
                expected++;
            }
            if (got == 0) {
                auto v = q.pop();
                if (v.has_value()) {
                    if (*v != expected) errors.fetch_add(1, std::memory_order_relaxed);
                    expected++;
                } else if (done.load(std::memory_order_acquire)) {
                    // Final drain
                    while (true) {
                        got = q.pop_batch(out, 8);
                        for (size_t i = 0; i < got; i++) {
                            if (out[i] != expected) errors.fetch_add(1, std::memory_order_relaxed);
                            expected++;
                        }
                        if (got == 0) break;
                    }
                    while (auto v2 = q.pop()) {
                        if (*v2 != expected) errors.fetch_add(1, std::memory_order_relaxed);
                        expected++;
                    }
                    break;
                }
            }
        }
    });

    producer.join();
    consumer.join();

    if (errors.load() > 0) {
        std::cerr << "batch_concurrent: " << errors.load() << " value errors" << std::endl;
        return 1;
    }
    return 0;
}

// ================================================================
// Test: latency sampler under concurrent writer/reader (for TSan)
// ================================================================
int test_sampler_concurrent() {
    LatencySampler sampler(1024);
    constexpr int N = 5000;
    std::atomic<bool> writer_done{false};
    std::atomic<int64_t> negative_count{0};

    // Writer thread: records latency samples
    std::thread writer([&]() {
        for (int i = 0; i < N; i++) {
            uint64_t start = 1000000ULL + static_cast<uint64_t>(i) * 100;
            uint64_t end = start + 50 + (static_cast<uint64_t>(i) % 37);
            sampler.record(static_cast<size_t>(i), start, end);
        }
        writer_done.store(true, std::memory_order_release);
    });

    // Reader thread: reads latencies concurrently
    std::thread reader([&]() {
        while (!writer_done.load(std::memory_order_acquire)) {
            for (int i = 0; i < N; i++) {
                int64_t lat = sampler.read_latency(static_cast<size_t>(i));
                if (lat != -1 && lat < 0) {
                    negative_count.fetch_add(1, std::memory_order_relaxed);
                }
            }
        }
        // Final check after writer is done
        for (int i = 0; i < N; i++) {
            int64_t lat = sampler.read_latency(static_cast<size_t>(i));
            if (lat != -1 && lat < 0) {
                negative_count.fetch_add(1, std::memory_order_relaxed);
            }
        }
    });

    writer.join();
    reader.join();

    if (negative_count.load() > 0) {
        std::cerr << "sampler: " << negative_count.load() << " negative latencies" << std::endl;
        return 1;
    }
    return 0;
}

// ================================================================
// Main dispatcher
// ================================================================
int main(int argc, char* argv[]) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <test_name>" << std::endl;
        std::cerr << "Tests: basic, nonpow2, concurrent, concurrent_small," << std::endl;
        std::cerr << "       layout, batch_basic, batch_wrap, batch_concurrent," << std::endl;
        std::cerr << "       sampler_concurrent" << std::endl;
        return 1;
    }

    std::string test = argv[1];
    int result = -1;

    if (test == "basic")                result = test_basic();
    else if (test == "nonpow2")         result = test_nonpow2();
    else if (test == "concurrent")      result = test_concurrent();
    else if (test == "concurrent_small") result = test_concurrent_small();
    else if (test == "layout")          result = test_layout();
    else if (test == "batch_basic")     result = test_batch_basic();
    else if (test == "batch_wrap")      result = test_batch_wrap();
    else if (test == "batch_concurrent") result = test_batch_concurrent();
    else if (test == "sampler_concurrent") result = test_sampler_concurrent();
    else {
        std::cerr << "Unknown test: " << test << std::endl;
        return 1;
    }

    if (result == 0)
        std::cout << "PASS" << std::endl;
    else
        std::cout << "FAIL" << std::endl;

    return result;
}
