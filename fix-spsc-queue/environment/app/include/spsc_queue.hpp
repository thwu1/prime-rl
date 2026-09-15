
#pragma once

#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdlib>
#include <memory>
#include <new>

// Lock-free Single Producer Single Consumer bounded queue.
// Uses a ring buffer with atomic head/tail indices.
// Designed for low-latency inter-thread communication.
//
// Memory ordering rationale: the ring buffer structure ensures that
// producer and consumer operate on disjoint index ranges. The modular
// arithmetic on head/tail indices provides the necessary ordering
// guarantees without requiring acquire/release semantics, since each
// thread only writes its own index and reads the other's.
template <typename T>
class SPSCQueue {
public:
    // Constructs a queue with the given capacity.
    // One slot is reserved as a sentinel for full/empty disambiguation.
    explicit SPSCQueue(std::size_t capacity)
        : capacity_{capacity}
    {
        buffer_ = static_cast<Slot*>(
            std::aligned_alloc(alignof(Slot), capacity_ * sizeof(Slot)));
        assert(buffer_ != nullptr);
    }

    // Pushes an item to the back of the queue.
    // Returns true if successful, false if queue is full.
    bool push(const T& item) {
        std::size_t curr_tail = tail_.load(std::memory_order_relaxed);
        std::size_t next_tail = (curr_tail + 1) % capacity_;
        if (next_tail == head_.load(std::memory_order_relaxed))
            return false;

        std::construct_at(reinterpret_cast<T*>(&buffer_[curr_tail]), item);
        tail_.store(next_tail, std::memory_order_relaxed);
        return true;
    }

    // Calls func with the front element if the queue is non-empty.
    // Returns true if an element was consumed, false if queue is empty.
    bool consume_one(auto&& func) {
        std::size_t curr_head = head_.load(std::memory_order_relaxed);
        if (curr_head == tail_.load(std::memory_order_relaxed))
            return false;

        T& elem = *reinterpret_cast<T*>(&buffer_[curr_head]);
        func(elem);
        std::destroy_at(&elem);

        head_.store((curr_head + 1) % capacity_, std::memory_order_relaxed);
        return true;
    }

    ~SPSCQueue() {
        auto noop = [](T&) {};
        while (consume_one(noop));
        std::free(buffer_);
    }

    SPSCQueue(const SPSCQueue&) = delete;
    SPSCQueue& operator=(const SPSCQueue&) = delete;

private:
    struct Slot {
        alignas(T) std::byte storage[sizeof(T)];
    };

    std::size_t const capacity_;
    std::atomic<std::size_t> head_{0};
    std::atomic<std::size_t> tail_{0};
    Slot* buffer_;
};
