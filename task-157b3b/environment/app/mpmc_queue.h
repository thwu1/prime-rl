#ifndef MPMC_QUEUE_H
#define MPMC_QUEUE_H


// Lock-free bounded multi-producer multi-consumer queue.
// Buffer size must be a power of 2, >= 2.
// Non-blocking: returns false on overflow/underflow.

#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <algorithm>

#include "backoff.h"

template<typename T>
class mpmc_bounded_queue
{
public:
    explicit mpmc_bounded_queue(size_t buffer_size)
    {
        (void)buffer_size;
    }

    ~mpmc_bounded_queue()
    {
    }

    bool enqueue(T const& data)
    {
        (void)data;
        return false;
    }

    bool dequeue(T& data)
    {
        (void)data;
        return false;
    }

    size_t try_enqueue_bulk(T const* items, size_t count)
    {
        (void)items; (void)count;
        return 0;
    }

    size_t try_dequeue_bulk(T* items, size_t max_count)
    {
        (void)items; (void)max_count;
        return 0;
    }

private:
    mpmc_bounded_queue(mpmc_bounded_queue const&) = delete;
    void operator=(mpmc_bounded_queue const&) = delete;
};

#endif // MPMC_QUEUE_H
