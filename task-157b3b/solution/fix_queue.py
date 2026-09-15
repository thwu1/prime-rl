#!/usr/bin/env python3
"""
Fix all 5 bugs in the lock-free bounded MPMC queue.

Bug 1: Enqueue sequence store uses memory_order_relaxed instead of release.
Bug 2: Dequeue sequence load uses memory_order_relaxed instead of acquire.
Bug 3: Dequeue sequence store uses memory_order_relaxed instead of release.
Bug 4: No cache-line padding between struct members (false sharing).
Bug 5: Off-by-one in dequeue sequence reset: pos+buffer_mask_ should be
        pos+buffer_mask_+1.
"""

CORRECT_QUEUE = r'''#ifndef MPMC_QUEUE_H
#define MPMC_QUEUE_H

// Lock-free bounded multi-producer multi-consumer queue.
// Uses per-slot sequence numbers for coordination.
// Array-based, fails on overflow, does not require GC.
// Cost: 1 CAS per enqueue/dequeue operation.

#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>

template<typename T>
class mpmc_bounded_queue
{
public:
    mpmc_bounded_queue(size_t buffer_size)
        : buffer_(new cell_t[buffer_size])
        , buffer_mask_(buffer_size - 1)
    {
        assert((buffer_size >= 2) &&
            ((buffer_size & (buffer_size - 1)) == 0));
        for (size_t i = 0; i != buffer_size; i += 1)
            buffer_[i].sequence_.store(i, std::memory_order_relaxed);
        enqueue_pos_.store(0, std::memory_order_relaxed);
        dequeue_pos_.store(0, std::memory_order_relaxed);
    }

    ~mpmc_bounded_queue()
    {
        delete[] buffer_;
    }

    bool enqueue(T const& data)
    {
        cell_t* cell;
        size_t pos = enqueue_pos_.load(std::memory_order_relaxed);
        for (;;)
        {
            cell = &buffer_[pos & buffer_mask_];
            size_t seq =
                cell->sequence_.load(std::memory_order_acquire);
            intptr_t dif = (intptr_t)seq - (intptr_t)pos;
            if (dif == 0)
            {
                if (enqueue_pos_.compare_exchange_weak(
                        pos, pos + 1, std::memory_order_relaxed))
                    break;
            }
            else if (dif < 0)
                return false;
            else
                pos = enqueue_pos_.load(std::memory_order_relaxed);
        }
        cell->data_ = data;
        cell->sequence_.store(pos + 1, std::memory_order_release);
        return true;
    }

    bool dequeue(T& data)
    {
        cell_t* cell;
        size_t pos = dequeue_pos_.load(std::memory_order_relaxed);
        for (;;)
        {
            cell = &buffer_[pos & buffer_mask_];
            size_t seq =
                cell->sequence_.load(std::memory_order_acquire);
            intptr_t dif = (intptr_t)seq - (intptr_t)(pos + 1);
            if (dif == 0)
            {
                if (dequeue_pos_.compare_exchange_weak(
                        pos, pos + 1, std::memory_order_relaxed))
                    break;
            }
            else if (dif < 0)
                return false;
            else
                pos = dequeue_pos_.load(std::memory_order_relaxed);
        }
        data = cell->data_;
        cell->sequence_.store(pos + buffer_mask_ + 1, std::memory_order_release);
        return true;
    }

private:
    struct cell_t
    {
        std::atomic<size_t>     sequence_;
        T                       data_;
    };

    static size_t const         cacheline_size = 64;
    typedef char                cacheline_pad_t[cacheline_size];

    cacheline_pad_t             pad0_;
    cell_t* const               buffer_;
    size_t const                buffer_mask_;
    cacheline_pad_t             pad1_;
    std::atomic<size_t>         enqueue_pos_;
    cacheline_pad_t             pad2_;
    std::atomic<size_t>         dequeue_pos_;
    cacheline_pad_t             pad3_;

    mpmc_bounded_queue(mpmc_bounded_queue const&) = delete;
    void operator = (mpmc_bounded_queue const&) = delete;
};

#endif // MPMC_QUEUE_H
'''

with open('/app/mpmc_queue.h', 'w') as f:
    f.write(CORRECT_QUEUE)

print("Fixed all 5 bugs in /app/mpmc_queue.h:")
print("  1. Enqueue sequence store: relaxed -> release")
print("  2. Dequeue sequence load: relaxed -> acquire")
print("  3. Dequeue sequence store: relaxed -> release")
print("  4. Added cache-line padding between struct members")
print("  5. Fixed off-by-one: pos + buffer_mask_ -> pos + buffer_mask_ + 1")
