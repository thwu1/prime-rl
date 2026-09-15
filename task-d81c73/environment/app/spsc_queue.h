
#pragma once

#include <atomic>
#include <cstddef>
#include <new>
#include <optional>

// Lock-free bounded SPSC (single-producer, single-consumer) queue.
// Uses monotonically increasing sequence counters for head/tail
// to simplify full/empty detection.
template <typename T>
class SPSCQueue {
public:
    explicit SPSCQueue(size_t capacity)
        : capacity_(capacity)
        , buffer_(static_cast<T*>(::operator new(sizeof(T) * capacity)))
        , head_(0)
        , tail_(0)
    {}

    ~SPSCQueue() {
        // Drain remaining items so their destructors run
        while (pop().has_value()) {}
        ::operator delete(buffer_);
    }

    SPSCQueue(const SPSCQueue&) = delete;
    SPSCQueue& operator=(const SPSCQueue&) = delete;

    bool push(const T& item) {
        const size_t tail = tail_.load(std::memory_order_relaxed);
        if (tail - head_.load(std::memory_order_relaxed) >= capacity_) {
            return false;  // full
        }
        new (&buffer_[index(tail)]) T(item);
        // Release: ensure the placement-new is visible before tail advances
        tail_.store(tail + 1, std::memory_order_release);
        return true;
    }

    std::optional<T> pop() {
        const size_t head = head_.load(std::memory_order_relaxed);
        if (head == tail_.load(std::memory_order_relaxed)) {
            return std::nullopt;  // empty
        }
        T item = std::move(buffer_[index(head)]);
        buffer_[index(head)].~T();
        // Release: ensure the destructor completes before head advances
        head_.store(head + 1, std::memory_order_release);
        return item;
    }

    // Batch operations for market data burst handling.
    // Push up to `count` items from `items` array into the queue.
    // Returns the number of items actually pushed (may be less if queue fills).
    size_t push_batch(const T* items, size_t count) {
        // TODO: implement efficient batch push that minimizes atomic operations
        (void)items; (void)count;
        return 0;
    }

    // Pop up to `count` items from the queue into `out` array.
    // Returns the number of items actually popped (may be less if queue empties).
    size_t pop_batch(T* out, size_t count) {
        // TODO: implement efficient batch pop that minimizes atomic operations
        (void)out; (void)count;
        return 0;
    }

private:
    // Map monotonic sequence number to buffer position
    size_t index(size_t seq) const {
        return seq & (capacity_ - 1);
    }

    size_t capacity_;
    T* buffer_;
    std::atomic<size_t> head_;
    std::atomic<size_t> tail_;
};
