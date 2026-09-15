
#pragma once

#include <cstddef>
#include <cstdint>
#include <atomic>

// Ring-buffer based latency sampler for pipeline monitoring.
// One thread records completed samples, another reads latencies.
class LatencySampler {
public:
    explicit LatencySampler(size_t num_slots)
        : num_slots_(num_slots)
        , entries_(new Entry[num_slots]())
    {}

    ~LatencySampler() {
        delete[] entries_;
    }

    LatencySampler(const LatencySampler&) = delete;
    LatencySampler& operator=(const LatencySampler&) = delete;

    // Record a completed latency sample. Called from the writer thread.
    void record(size_t msg_id, uint64_t start_ns, uint64_t end_ns) {
        size_t idx = msg_id % num_slots_;
        entries_[idx].start_ns = start_ns;
        entries_[idx].end_ns = end_ns;
        entries_[idx].ready.store(true, std::memory_order_relaxed);
    }

    // Read a latency sample. Returns nanoseconds, or -1 if not ready.
    // Called from the reader/monitor thread.
    int64_t read_latency(size_t msg_id) const {
        size_t idx = msg_id % num_slots_;
        if (!entries_[idx].ready.load(std::memory_order_relaxed)) {
            return -1;
        }
        return static_cast<int64_t>(entries_[idx].end_ns - entries_[idx].start_ns);
    }

private:
    struct Entry {
        uint64_t start_ns = 0;
        uint64_t end_ns = 0;
        std::atomic<bool> ready{false};
    };

    size_t num_slots_;
    Entry* entries_;
};
