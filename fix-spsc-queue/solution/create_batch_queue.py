#!/usr/bin/env python3
"""
Create the SPSCBatchQueue implementation at /app/include/spsc_batch_queue.hpp.

This is a batched variant of the SPSC queue with:
- push_batch: atomically publish multiple items (single release store on tail)
- consume_batch: consume up to N items (single release store on head)
- Same correctness properties: sentinel slot, acquire/release ordering,
  cache-line separation, non-default-constructible type support
"""

BATCH_QUEUE_FILE = "/app/include/spsc_batch_queue.hpp"

content = """\

#pragma once

#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdlib>
#include <memory>
#include <new>

#ifdef __cpp_lib_hardware_interference_size
inline constexpr std::size_t kBatchQueueCacheLineSize = std::hardware_destructive_interference_size;
#else
inline constexpr std::size_t kBatchQueueCacheLineSize = 64;
#endif

// Lock-free Single Producer Single Consumer bounded queue with batch operations.
// Extends the SPSC queue pattern with push_batch and consume_batch for
// amortizing atomic overhead across multiple items.
template <typename T>
class SPSCBatchQueue {
public:
    explicit SPSCBatchQueue(std::size_t capacity)
        : capacity_{capacity + 1}  // +1 sentinel slot for full/empty disambiguation
    {
        buffer_ = static_cast<Slot*>(
            std::aligned_alloc(alignof(Slot), capacity_ * sizeof(Slot)));
        assert(buffer_ != nullptr);
    }

    // Push a single item. Returns false if queue is full.
    bool push(const T& item) {
        std::size_t curr_tail = tail_.load(std::memory_order_relaxed);
        std::size_t next_tail = (curr_tail + 1) % capacity_;
        if (next_tail == head_.load(std::memory_order_acquire))
            return false;
        std::construct_at(reinterpret_cast<T*>(&buffer_[curr_tail]), item);
        tail_.store(next_tail, std::memory_order_release);
        return true;
    }

    // Atomically publish count items. Returns false without side effects
    // if there is insufficient space for the entire batch.
    bool push_batch(const T* items, std::size_t count) {
        if (count == 0) return true;
        std::size_t curr_tail = tail_.load(std::memory_order_relaxed);
        std::size_t curr_head = head_.load(std::memory_order_acquire);

        // Calculate available space (capacity_ - 1 usable slots minus occupied)
        std::size_t used = (curr_tail + capacity_ - curr_head) % capacity_;
        std::size_t available = capacity_ - 1 - used;

        if (count > available) return false;

        // Construct all items in the ring buffer
        for (std::size_t i = 0; i < count; ++i) {
            std::size_t idx = (curr_tail + i) % capacity_;
            std::construct_at(reinterpret_cast<T*>(&buffer_[idx]), items[i]);
        }

        // Single release store makes all items visible at once
        std::size_t new_tail = (curr_tail + count) % capacity_;
        tail_.store(new_tail, std::memory_order_release);
        return true;
    }

    // Consume a single item by calling func with it. Returns false if empty.
    bool consume_one(auto&& func) {
        std::size_t curr_head = head_.load(std::memory_order_relaxed);
        if (curr_head == tail_.load(std::memory_order_acquire))
            return false;
        T& elem = *reinterpret_cast<T*>(&buffer_[curr_head]);
        func(elem);
        std::destroy_at(&elem);
        head_.store((curr_head + 1) % capacity_, std::memory_order_release);
        return true;
    }

    // Consume up to max_count items, calling func for each.
    // Returns the number of items actually consumed.
    std::size_t consume_batch(auto&& func, std::size_t max_count) {
        if (max_count == 0) return 0;
        std::size_t curr_head = head_.load(std::memory_order_relaxed);
        std::size_t curr_tail = tail_.load(std::memory_order_acquire);

        if (curr_head == curr_tail) return 0;

        // Calculate how many items are available
        std::size_t available = (curr_tail + capacity_ - curr_head) % capacity_;
        std::size_t to_consume = (max_count < available) ? max_count : available;

        for (std::size_t i = 0; i < to_consume; ++i) {
            std::size_t idx = (curr_head + i) % capacity_;
            T& elem = *reinterpret_cast<T*>(&buffer_[idx]);
            func(elem);
            std::destroy_at(&elem);
        }

        // Single release store frees all consumed slots at once
        std::size_t new_head = (curr_head + to_consume) % capacity_;
        head_.store(new_head, std::memory_order_release);
        return to_consume;
    }

    ~SPSCBatchQueue() {
        auto noop = [](T&) {};
        while (consume_one(noop));
        std::free(buffer_);
    }

    SPSCBatchQueue(const SPSCBatchQueue&) = delete;
    SPSCBatchQueue& operator=(const SPSCBatchQueue&) = delete;

private:
    struct Slot {
        alignas(T) std::byte storage[sizeof(T)];
    };

    std::size_t const capacity_;
    alignas(kBatchQueueCacheLineSize) std::atomic<std::size_t> head_{0};
    alignas(kBatchQueueCacheLineSize) std::atomic<std::size_t> tail_{0};
    Slot* buffer_;
};
"""

with open(BATCH_QUEUE_FILE, "w") as f:
    f.write(content)

print(f"Created {BATCH_QUEUE_FILE}")
