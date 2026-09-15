#!/usr/bin/env python3
"""
Implement the complete lock-free bounded MPMC queue system:
1. mpmc_queue.h  — full queue with single and bulk operations
2. backoff.h     — adaptive contention backoff
3. ordering_analysis.json — memory ordering evaluation
"""

import json

# ============================================================
# 1. Adaptive backoff strategy
# ============================================================
BACKOFF_H = r'''#ifndef BACKOFF_H
#define BACKOFF_H

#include <thread>

// Adaptive backoff strategy for lock-free CAS retry loops.
// Starts with architecture-specific spin hints, escalates to
// OS-level yields under sustained contention.

class adaptive_backoff
{
public:
    adaptive_backoff() : count_(0) {}

    void backoff()
    {
        if (count_ < YIELD_THRESHOLD) {
            unsigned spins = 1u << count_;
            for (unsigned i = 0; i < spins; ++i) {
#if defined(__x86_64__) || defined(__i386__)
                __asm__ __volatile__("pause");
#elif defined(__aarch64__)
                __asm__ __volatile__("yield");
#else
                volatile int sink = 0;
                (void)sink;
#endif
            }
        } else {
            std::this_thread::yield();
        }
        if (count_ < MAX_COUNT)
            ++count_;
    }

    void reset()
    {
        count_ = 0;
    }

private:
    static constexpr unsigned YIELD_THRESHOLD = 4;
    static constexpr unsigned MAX_COUNT = 8;
    unsigned count_;
};

#endif // BACKOFF_H
'''

# ============================================================
# 2. Lock-free bounded MPMC queue
# ============================================================
MPMC_QUEUE_H = r'''#ifndef MPMC_QUEUE_H
#define MPMC_QUEUE_H

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
        adaptive_backoff bo;
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
            {
                pos = enqueue_pos_.load(std::memory_order_relaxed);
                bo.backoff();
            }
        }
        cell->data_ = data;
        cell->sequence_.store(pos + 1, std::memory_order_release);
        return true;
    }

    bool dequeue(T& data)
    {
        cell_t* cell;
        size_t pos = dequeue_pos_.load(std::memory_order_relaxed);
        adaptive_backoff bo;
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
            {
                pos = dequeue_pos_.load(std::memory_order_relaxed);
                bo.backoff();
            }
        }
        data = cell->data_;
        cell->sequence_.store(pos + buffer_mask_ + 1, std::memory_order_release);
        return true;
    }

    size_t try_enqueue_bulk(T const* items, size_t count)
    {
        if (count == 0) return 0;
        count = std::min(count, buffer_mask_ + 1);

        size_t pos = enqueue_pos_.load(std::memory_order_relaxed);
        adaptive_backoff bo;
        for (;;)
        {
            // Check first slot availability
            cell_t* first = &buffer_[pos & buffer_mask_];
            size_t seq = first->sequence_.load(std::memory_order_acquire);
            intptr_t dif = (intptr_t)seq - (intptr_t)pos;

            if (dif < 0)
                return 0;  // queue full

            if (dif > 0) {
                // Another producer advanced past us — reload position
                pos = enqueue_pos_.load(std::memory_order_relaxed);
                bo.backoff();
                continue;
            }

            // First slot is free. Scan for consecutive free slots.
            size_t n = 1;
            for (size_t i = 1; i < count; ++i)
            {
                cell_t* c = &buffer_[(pos + i) & buffer_mask_];
                size_t s = c->sequence_.load(std::memory_order_acquire);
                intptr_t d = (intptr_t)s - (intptr_t)(pos + i);
                if (d != 0) break;
                ++n;
            }

            // Reserve n positions with a single CAS
            if (enqueue_pos_.compare_exchange_weak(
                    pos, pos + n, std::memory_order_relaxed))
            {
                // Fill all reserved slots
                for (size_t i = 0; i < n; ++i)
                {
                    cell_t* c = &buffer_[(pos + i) & buffer_mask_];
                    c->data_ = items[i];
                    c->sequence_.store(pos + i + 1,
                                       std::memory_order_release);
                }
                return n;
            }
            // CAS failed — pos updated by CAS, retry scan
            bo.backoff();
        }
    }

    size_t try_dequeue_bulk(T* items, size_t max_count)
    {
        if (max_count == 0) return 0;
        max_count = std::min(max_count, buffer_mask_ + 1);

        size_t pos = dequeue_pos_.load(std::memory_order_relaxed);
        adaptive_backoff bo;
        for (;;)
        {
            // Check first slot
            cell_t* first = &buffer_[pos & buffer_mask_];
            size_t seq = first->sequence_.load(std::memory_order_acquire);
            intptr_t dif = (intptr_t)seq - (intptr_t)(pos + 1);

            if (dif < 0)
                return 0;  // queue empty

            if (dif > 0) {
                pos = dequeue_pos_.load(std::memory_order_relaxed);
                bo.backoff();
                continue;
            }

            // Scan for consecutive ready slots
            size_t n = 1;
            for (size_t i = 1; i < max_count; ++i)
            {
                cell_t* c = &buffer_[(pos + i) & buffer_mask_];
                size_t s = c->sequence_.load(std::memory_order_acquire);
                intptr_t d = (intptr_t)s - (intptr_t)(pos + i + 1);
                if (d != 0) break;
                ++n;
            }

            // Reserve n positions with a single CAS
            if (dequeue_pos_.compare_exchange_weak(
                    pos, pos + n, std::memory_order_relaxed))
            {
                // Read all reserved slots and recycle them
                for (size_t i = 0; i < n; ++i)
                {
                    cell_t* c = &buffer_[(pos + i) & buffer_mask_];
                    items[i] = c->data_;
                    c->sequence_.store(pos + i + buffer_mask_ + 1,
                                       std::memory_order_release);
                }
                return n;
            }
            bo.backoff();
        }
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
    void operator=(mpmc_bounded_queue const&) = delete;
};

#endif // MPMC_QUEUE_H
'''

# ============================================================
# 3. Memory ordering analysis
# ============================================================
ordering_analysis = {
    "operations": [
        {
            "location": "enqueue",
            "variable": "sequence_",
            "operation": "load",
            "ordering": "memory_order_acquire",
            "justification": (
                "Must synchronize with the release store performed by dequeue "
                "when it marks this slot as recycled (sequence = pos + buffer_size). "
                "The acquire ensures that the consumer's read of data_ from the "
                "previous cycle is complete before the producer overwrites data_."
            ),
            "weaker_ordering_bug": (
                "With relaxed on ARM64: Consumer thread stores sequence_ with "
                "release after reading data_. Producer loads sequence_ with relaxed "
                "and sees the recycled value, but without acquire the consumer's "
                "data_ read may not have completed — the producer overwrites data_ "
                "while the consumer is still reading it, causing a torn read."
            )
        },
        {
            "location": "enqueue",
            "variable": "enqueue_pos_",
            "operation": "compare_exchange_weak",
            "ordering": "memory_order_relaxed",
            "justification": (
                "The CAS only needs atomicity to claim a unique position. "
                "Ordering is provided by the preceding acquire load of sequence_ "
                "(ensures slot is truly free) and the subsequent release store of "
                "sequence_ (publishes data to consumers). The CAS itself does not "
                "need to establish any happens-before relationship."
            ),
            "weaker_ordering_bug": (
                "Relaxed is the weakest standard memory ordering for atomic RMW. "
                "No weaker ordering exists that maintains atomicity. The CAS "
                "correctness relies on the acquire/release pair on sequence_, "
                "not on the CAS ordering itself."
            )
        },
        {
            "location": "enqueue",
            "variable": "sequence_",
            "operation": "store",
            "ordering": "memory_order_release",
            "justification": (
                "Must publish the preceding non-atomic write to data_ so that "
                "a consumer performing an acquire load of sequence_ and observing "
                "this value (pos + 1) is guaranteed to see the data_ write. This "
                "is the classic publish pattern: write payload, then release-store "
                "the flag."
            ),
            "weaker_ordering_bug": (
                "With relaxed on ARM64: Producer writes data_ = 42 then stores "
                "sequence_ = pos+1 with relaxed. Consumer loads sequence_ with "
                "acquire and sees pos+1, but the ARM64 store buffer may not have "
                "flushed data_ yet. Consumer reads uninitialized or stale data_ — "
                "silent data corruption that passes on x86 (TSO) but fails on ARM."
            )
        },
        {
            "location": "dequeue",
            "variable": "sequence_",
            "operation": "load",
            "ordering": "memory_order_acquire",
            "justification": (
                "Must synchronize with the release store in enqueue that published "
                "data into this slot (sequence_ = pos + 1). The acquire load "
                "ensures the consumer sees the producer's data_ write, completing "
                "the acquire/release handshake that makes the publication visible."
            ),
            "weaker_ordering_bug": (
                "With relaxed on ARM64: Producer writes data_ and release-stores "
                "sequence_. Consumer relaxed-loads sequence_ and sees the updated "
                "value, but ARM64 may satisfy the load from a cache line that was "
                "invalidated and refetched with the new sequence_ but an old data_. "
                "Without acquire, the data_ load can be reordered before the "
                "sequence_ load, reading stale payload."
            )
        },
        {
            "location": "dequeue",
            "variable": "dequeue_pos_",
            "operation": "compare_exchange_weak",
            "ordering": "memory_order_relaxed",
            "justification": (
                "Same rationale as enqueue CAS: atomicity suffices to claim the "
                "dequeue position. The acquire load on sequence_ before the CAS "
                "ensures data_ is visible, and the release store on sequence_ "
                "after reading data_ ensures the slot is safely recycled."
            ),
            "weaker_ordering_bug": (
                "Relaxed is already the weakest standard ordering for atomic RMW "
                "operations. No weaker ordering exists that preserves atomicity. "
                "Correctness is ensured by the sequence_ acquire/release pair."
            )
        },
        {
            "location": "dequeue",
            "variable": "sequence_",
            "operation": "store",
            "ordering": "memory_order_release",
            "justification": (
                "Must ensure the consumer's read of data_ completes before the "
                "slot is marked as available for the next enqueue cycle. Without "
                "release, a future producer could observe the recycled sequence "
                "number and begin writing new data_ while the current consumer "
                "is still reading the old data_."
            ),
            "weaker_ordering_bug": (
                "With relaxed on ARM64: Consumer reads data_ then relaxed-stores "
                "sequence_ = pos + buffer_size. Producer acquire-loads sequence_ "
                "and sees the recycled value, then writes new data_. On ARM64, "
                "the consumer's data_ read may be reordered after the relaxed "
                "sequence_ store, so the consumer reads the producer's NEW data_ "
                "instead of the original — or a partially-written torn value."
            )
        },
        {
            "location": "enqueue",
            "variable": "enqueue_pos_",
            "operation": "load",
            "ordering": "memory_order_relaxed",
            "justification": (
                "Speculative hint for the CAS loop starting point. If the loaded "
                "value is stale, the subsequent CAS will simply fail and update "
                "pos to the current value. No ordering guarantee is needed because "
                "this load does not guard any data access — it only selects which "
                "slot to check next."
            ),
            "weaker_ordering_bug": (
                "Relaxed is the weakest memory ordering. A stale value causes a "
                "harmless CAS failure which self-corrects. No weaker alternative "
                "exists in the C++ memory model."
            )
        },
        {
            "location": "dequeue",
            "variable": "dequeue_pos_",
            "operation": "load",
            "ordering": "memory_order_relaxed",
            "justification": (
                "Same as enqueue_pos_ initial load: a speculative hint for the "
                "CAS loop. Staleness causes a harmless CAS failure and automatic "
                "position correction. No data access depends on this load's value "
                "being current."
            ),
            "weaker_ordering_bug": (
                "Relaxed is the weakest memory ordering. No weaker alternative "
                "exists. A stale dequeue_pos_ only causes an extra CAS retry "
                "iteration with no correctness impact."
            )
        }
    ]
}

# ============================================================
# Write all files
# ============================================================

with open('/app/backoff.h', 'w') as f:
    f.write(BACKOFF_H)
print("Wrote /app/backoff.h")

with open('/app/mpmc_queue.h', 'w') as f:
    f.write(MPMC_QUEUE_H)
print("Wrote /app/mpmc_queue.h")

with open('/app/ordering_analysis.json', 'w') as f:
    json.dump(ordering_analysis, f, indent=2)
print("Wrote /app/ordering_analysis.json")

print("\nImplemented:")
print("  - Lock-free bounded MPMC queue with sequence-number coordination")
print("  - Single enqueue/dequeue with CAS + acquire/release ordering")
print("  - Bulk enqueue/dequeue with single-CAS multi-slot reservation")
print("  - Cache-line padding between atomic variables")
print("  - Adaptive backoff: exponential spin + yield escalation")
print("  - Memory ordering analysis for all 8 atomic operations")
