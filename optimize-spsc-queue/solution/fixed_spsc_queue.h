#pragma once

#include "config.h"

#include <atomic>
#include <algorithm>
#include <cstdint>
#include <cstring>

namespace spsc {

namespace detail {

inline void write_wrap(char* buf, size_t cap, size_t offset,
                       const void* src, size_t n) {
    size_t first = std::min(n, cap - offset);
    std::memcpy(buf + offset, src, first);
    if (first < n)
        std::memcpy(buf, static_cast<const char*>(src) + first, n - first);
}

inline void read_wrap(const char* buf, size_t cap, size_t offset,
                      void* dst, size_t n) {
    size_t first = std::min(n, cap - offset);
    std::memcpy(dst, buf + offset, first);
    if (first < n)
        std::memcpy(static_cast<char*>(dst) + first, buf, n - first);
}

}  // namespace detail

// Queue header residing in shared memory.
// Each atomic is placed on its own cache line to avoid false sharing.
struct QueueHeader {
    alignas(kCacheLineSize) std::atomic<uint64_t> write_pos_{0};
    alignas(kCacheLineSize) std::atomic<uint64_t> read_pos_{0};
};

// ---------------------------------------------------------------------------
// Producer – writes variable-length messages into a circular byte buffer.
// Uses write-position reservation: the published write_pos_ is only updated
// when the current reservation chunk (kReservationSize bytes) is exhausted
// or when flush() is called explicitly.
// ---------------------------------------------------------------------------
class Producer {
public:
    Producer(QueueHeader* header, char* buffer, size_t capacity)
        : header_(header), buffer_(buffer), capacity_(capacity),
          current_pos_(0), reserved_end_(0) {}

    bool write(const void* data, uint32_t size) {
        uint32_t total = static_cast<uint32_t>(sizeof(uint32_t)) + size;
        if (total > capacity_ / 2) return false;

        uint64_t wp = current_pos_;

        // Write-position reservation: batch atomic stores.
        if (wp + total > reserved_end_) {
            header_->write_pos_.store(wp, std::memory_order_release);
            reserved_end_ = wp + kReservationSize;
        }

        size_t offset = wp % capacity_;

        // Encode length prefix (handles wraparound).
        detail::write_wrap(buffer_, capacity_, offset, &size, sizeof(uint32_t));
        offset = (offset + sizeof(uint32_t)) % capacity_;

        // Copy payload (handles wraparound).
        detail::write_wrap(buffer_, capacity_, offset, data, size);

        current_pos_ = wp + total;
        return true;
    }

    void flush() {
        header_->write_pos_.store(current_pos_, std::memory_order_release);
    }

private:
    QueueHeader* header_;
    char* buffer_;
    size_t capacity_;
    uint64_t current_pos_;
    uint64_t reserved_end_;
};

// ---------------------------------------------------------------------------
// Consumer – reads variable-length messages from the circular byte buffer.
// Caches the write position locally to reduce atomic loads.
// ---------------------------------------------------------------------------
class Consumer {
public:
    Consumer(const QueueHeader* header, const char* buffer, size_t capacity)
        : header_(header), buffer_(buffer), capacity_(capacity),
          local_pos_(0), cached_write_pos_(0) {}

    uint32_t read(void* out, uint32_t max_size) {
        // Read-side caching: only reload the atomic when the cache says no data.
        if (local_pos_ >= cached_write_pos_) {
            cached_write_pos_ = header_->write_pos_.load(std::memory_order_acquire);
            if (local_pos_ >= cached_write_pos_) return 0;
        }

        size_t offset = local_pos_ % capacity_;

        uint32_t msg_size;
        detail::read_wrap(buffer_, capacity_, offset, &msg_size, sizeof(uint32_t));
        offset = (offset + sizeof(uint32_t)) % capacity_;

        if (msg_size > max_size) return 0;

        detail::read_wrap(buffer_, capacity_, offset, out, msg_size);

        local_pos_ += sizeof(uint32_t) + msg_size;
        return msg_size;
    }

    uint64_t position() const { return local_pos_; }

private:
    const QueueHeader* header_;
    const char* buffer_;
    size_t capacity_;
    uint64_t local_pos_;
    uint64_t cached_write_pos_;
};

}  // namespace spsc
