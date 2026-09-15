#pragma once

#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdlib>
#include <memory>


// Single-Producer Single-Consumer lock-free bounded queue
// for low-latency market data distribution in trading systems.
//
// Ring buffer design with atomic head/tail indices.
// Producer (feed handler) writes market ticks; consumer (strategy) reads them.
// Both threads are expected to run on dedicated cores, spin-waiting for data.

template <typename T>
class SPSCQueue {
public:
    explicit SPSCQueue(size_t capacity)
        : capacity_{capacity}
    {
        buffer_ = static_cast<Element*>(std::malloc(capacity_ * sizeof(Element)));
        assert(buffer_ != nullptr);
    }

    SPSCQueue(const SPSCQueue&) = delete;
    SPSCQueue& operator=(const SPSCQueue&) = delete;

    bool push(const T& item)
    {
        std::size_t const currTail = tail_.load(std::memory_order_relaxed);
        std::size_t const nextTail = increment(currTail);
        if (nextTail == head_.load(std::memory_order_relaxed))
            return false;

        std::construct_at(reinterpret_cast<T*>(&buffer_[currTail]), item);
        tail_.store(nextTail, std::memory_order_relaxed);
        return true;
    }

    bool consume_one(auto&& func)
    {
        std::size_t const currHead = head_.load(std::memory_order_relaxed);
        std::size_t const currTail = tail_.load(std::memory_order_relaxed);
        if (currHead == currTail)
            return false;

        T& elem = *reinterpret_cast<T*>(&buffer_[currTail]);
        func(elem);
        std::destroy_at(&elem);

        head_.store(increment(currHead), std::memory_order_relaxed);
        return true;
    }

    ~SPSCQueue()
    {
        auto noop = [](T&) {};
        while (consume_one(noop));
        std::free(buffer_);
    }

private:
    struct Element {
        alignas(T) std::byte storage[sizeof(T)];
    };

    std::size_t increment(std::size_t index) const
    {
        return (index + 1) % capacity_;
    }

    std::size_t const capacity_;
    std::atomic<std::size_t> head_{0};
    std::atomic<std::size_t> tail_{0};
    Element* buffer_;
};
