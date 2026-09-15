
#pragma once

#include <mutex>
#include <cstddef>
#include <new>
#include <memory>

// Bounded single-producer single-consumer queue.
// Thread-safe for concurrent use by one producer and one consumer thread.
template <typename T>
class SPSCQueue {
public:
    explicit SPSCQueue(std::size_t capacity)
        : capacity_(capacity + 1)
        , buffer_(static_cast<T*>(::operator new(sizeof(T) * capacity_)))
        , head_(0)
        , tail_(0)
    {}

    ~SPSCQueue() {
        while (head_ != tail_) {
            std::destroy_at(&buffer_[head_]);
            head_ = (head_ + 1) % capacity_;
        }
        ::operator delete(buffer_);
    }

    SPSCQueue(const SPSCQueue&) = delete;
    SPSCQueue& operator=(const SPSCQueue&) = delete;

    // Enqueue an item. Returns false if the queue is full.
    bool push(const T& item) {
        std::lock_guard<std::mutex> lock(mtx_);
        std::size_t next_tail = (tail_ + 1) % capacity_;
        if (next_tail == head_) return false;
        std::construct_at(&buffer_[tail_], item);
        tail_ = next_tail;
        return true;
    }

    // Dequeue and process an item via the callback. Returns false if empty.
    template <typename Func>
    bool consume_one(Func&& func) {
        std::lock_guard<std::mutex> lock(mtx_);
        if (head_ == tail_) return false;
        func(buffer_[head_]);
        std::destroy_at(&buffer_[head_]);
        head_ = (head_ + 1) % capacity_;
        return true;
    }

    std::size_t capacity() const { return capacity_ - 1; }

private:
    std::size_t capacity_;
    T* buffer_;
    std::size_t head_;
    std::size_t tail_;
    std::mutex mtx_;
};
