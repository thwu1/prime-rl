// mutex_queue.hpp — Mutex-based SPSC queue (REFERENCE IMPLEMENTATION)
//
// This shows the required public API for SPSCQueue<T>.
// Your lock-free implementation in spsc_queue.hpp must provide the same
// public interface: SPSCQueue<T>(capacity), try_push, try_pop, capacity, size.
//
// This implementation is CORRECT but SLOW (uses a mutex on every operation).
// Do NOT copy this file — create a lock-free version from scratch.
#pragma once
#include <mutex>
#include <vector>
#include <cstddef>

template <typename T>
class SPSCQueue {
public:
    explicit SPSCQueue(size_t capacity)
        : cap_(capacity), buffer_(capacity) {}

    // Attempt to enqueue an item. Returns false if the queue is full.
    bool try_push(const T& item) {
        std::lock_guard<std::mutex> lk(mtx_);
        if (count_ >= cap_) return false;
        buffer_[(head_ + count_) % cap_] = item;
        ++count_;
        return true;
    }

    // Attempt to dequeue an item. Returns false if the queue is empty.
    bool try_pop(T& item) {
        std::lock_guard<std::mutex> lk(mtx_);
        if (count_ == 0) return false;
        item = buffer_[head_];
        head_ = (head_ + 1) % cap_;
        --count_;
        return true;
    }

    // Returns the maximum number of elements the queue can hold.
    size_t capacity() const { return cap_; }

    // Returns the current number of elements (approximate is acceptable
    // for lock-free implementations).
    size_t size() const {
        std::lock_guard<std::mutex> lk(mtx_);
        return count_;
    }

private:
    size_t cap_;
    std::vector<T> buffer_;
    size_t head_ = 0;
    size_t count_ = 0;
    mutable std::mutex mtx_;
};
