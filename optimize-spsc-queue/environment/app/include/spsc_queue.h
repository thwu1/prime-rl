#pragma once

#include "config.h"

#include <atomic>
#include <algorithm>
#include <cstdint>
#include <cstring>

namespace spsc {

// Queue header residing in shared memory.
// Contains the two position counters used for producer-consumer coordination.
struct QueueHeader {
    std::atomic<uint64_t> write_pos_{0};  // Published write position (consumers read)
    std::atomic<uint64_t> read_pos_{0};   // Informational read watermark
};

// ---------------------------------------------------------------------------
// Producer – writes variable-length messages into a circular byte buffer.
// ---------------------------------------------------------------------------
class Producer {
public:
    Producer(QueueHeader* header, char* buffer, size_t capacity)
        : header_(header), buffer_(buffer), capacity_(capacity),
          current_pos_(0), reserved_end_(0) {}

    // Write a variable-length message.  Returns true on success.
    bool write(const void* data, uint32_t size) {
        uint32_t total = static_cast<uint32_t>(sizeof(uint32_t)) + size;
        if (total > capacity_ / 2) return false;

        uint64_t wp = current_pos_;
        size_t offset = wp % capacity_;

        // Encode length prefix
        std::memcpy(buffer_ + offset, &size, sizeof(uint32_t));
        offset += sizeof(uint32_t);
        if (offset >= capacity_) offset -= capacity_;

        // Copy payload
        std::memcpy(buffer_ + offset, data, size);

        current_pos_ = wp + total;

        // Publish position on every message
        header_->write_pos_.store(current_pos_, std::memory_order_seq_cst);

        return true;
    }

    // Make all written data visible to consumers.
    void flush() {
        header_->write_pos_.store(current_pos_, std::memory_order_seq_cst);
    }

private:
    QueueHeader* header_;
    char* buffer_;
    size_t capacity_;
    uint64_t current_pos_;
    uint64_t reserved_end_;   // Currently unused
};

// ---------------------------------------------------------------------------
// Consumer – reads variable-length messages from the circular byte buffer.
// ---------------------------------------------------------------------------
class Consumer {
public:
    Consumer(const QueueHeader* header, const char* buffer, size_t capacity)
        : header_(header), buffer_(buffer), capacity_(capacity),
          local_pos_(0), cached_write_pos_(0) {}

    // Read the next message into `out`.  Returns payload size, or 0 when
    // no data is available.
    uint32_t read(void* out, uint32_t max_size) {
        // Load the published write position on every call
        uint64_t wp = header_->write_pos_.load(std::memory_order_seq_cst);

        if (local_pos_ >= wp) return 0;

        size_t offset = local_pos_ % capacity_;

        // Decode length prefix
        uint32_t msg_size;
        std::memcpy(&msg_size, buffer_ + offset, sizeof(uint32_t));
        offset += sizeof(uint32_t);
        if (offset >= capacity_) offset -= capacity_;

        if (msg_size > max_size) return 0;

        // Copy payload
        std::memcpy(out, buffer_ + offset, msg_size);

        local_pos_ += sizeof(uint32_t) + msg_size;

        return msg_size;
    }

    uint64_t position() const { return local_pos_; }

private:
    const QueueHeader* header_;
    const char* buffer_;
    size_t capacity_;
    uint64_t local_pos_;
    uint64_t cached_write_pos_;  // Currently unused
};

}  // namespace spsc
