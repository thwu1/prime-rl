#!/usr/bin/env python3
"""
Generate lock-free SPSC queue and tournament-tree feed merger.

Design decisions:
  SPSC Queue:
    - Monotonically-increasing head/tail counters (no sentinel slot needed)
    - Internal buffer sized to next power-of-2 for bitwise-AND index masking
    - acquire on cross-thread loads, release on cross-thread stores,
      relaxed on own-thread loads
    - alignas(64) on head_ and tail_ for cache-line separation

  Feed Merger (Loser Tree):
    - K internal nodes (padded to power-of-2) in Eytzinger layout
    - Bottom-up build using temporary winner array
    - Replay walks from changed leaf to root swapping losers
    - Exhausted sources treated as sentinels that always lose
    - Stability via lower-index-wins tie-breaking
"""

import os


def generate_spsc_queue():
    """Return the C++ source for spsc_queue.hpp."""
    return r'''#pragma once
#include <atomic>
#include <cstddef>
#include <bit>

template <typename T>
class SPSCQueue {
public:
    explicit SPSCQueue(size_t requested_capacity)
        : buf_size_(std::bit_ceil(requested_capacity == 0 ? size_t(1) : requested_capacity))
        , mask_(buf_size_ - 1)
        , usable_cap_(requested_capacity)
        , buffer_(new T[buf_size_])
    {}

    ~SPSCQueue() { delete[] buffer_; }
    SPSCQueue(const SPSCQueue&) = delete;
    SPSCQueue& operator=(const SPSCQueue&) = delete;

    bool try_push(const T& item) {
        const size_t t = tail_.load(std::memory_order_relaxed);
        const size_t h = head_.load(std::memory_order_acquire);
        if (t - h >= usable_cap_) return false;
        buffer_[t & mask_] = item;
        tail_.store(t + 1, std::memory_order_release);
        return true;
    }

    bool try_pop(T& item) {
        const size_t h = head_.load(std::memory_order_relaxed);
        const size_t t = tail_.load(std::memory_order_acquire);
        if (h == t) return false;
        item = buffer_[h & mask_];
        head_.store(h + 1, std::memory_order_release);
        return true;
    }

    size_t capacity() const { return usable_cap_; }

    size_t size() const {
        const size_t t = tail_.load(std::memory_order_relaxed);
        const size_t h = head_.load(std::memory_order_relaxed);
        return t - h;
    }

private:
    const size_t buf_size_;
    const size_t mask_;
    const size_t usable_cap_;

    alignas(64) std::atomic<size_t> head_{0};
    alignas(64) std::atomic<size_t> tail_{0};

    T* buffer_;
};
'''


def generate_feed_merger():
    """Return the C++ source for feed_merger.hpp."""
    return r'''#pragma once
#include <vector>
#include <cstddef>
#include <utility>
#include "spsc_queue.hpp"

template <typename T, typename KeyFn>
class FeedMerger {
public:
    FeedMerger(std::vector<SPSCQueue<T>*> sources, KeyFn key_fn)
        : sources_(std::move(sources))
        , key_fn_(std::move(key_fn))
        , real_k_(sources_.size())
        , k_(round_up_pow2(real_k_ == 0 ? size_t(1) : real_k_))
        , tree_(k_, -1)
        , vals_(real_k_)
        , active_(real_k_, false)
    {
        for (size_t i = 0; i < real_k_; ++i)
            pull(static_cast<int>(i));
        build();
    }

    bool try_merge_one(T& out) {
        int w = tree_[0];
        if (w < 0 || w >= static_cast<int>(real_k_) || !active_[w])
            return false;
        out = vals_[w];
        pull(w);
        replay(w);
        return true;
    }

private:
    static size_t round_up_pow2(size_t n) {
        size_t p = 1;
        while (p < n) p <<= 1;
        return p;
    }

    void pull(int idx) {
        T item;
        if (sources_[idx]->try_pop(item)) {
            vals_[idx] = item;
            active_[idx] = true;
        } else {
            active_[idx] = false;
        }
    }

    bool is_dead(int idx) const {
        return idx < 0
            || idx >= static_cast<int>(real_k_)
            || !active_[idx];
    }

    // Returns true if source a loses to source b (b wins).
    bool a_loses(int a, int b) const {
        bool ad = is_dead(a);
        bool bd = is_dead(b);
        if (ad && bd) return true;   // both dead: a "loses" (arbitrary)
        if (ad) return true;          // a dead, b alive: a loses
        if (bd) return false;         // b dead, a alive: a wins
        auto ka = key_fn_(vals_[a]);
        auto kb = key_fn_(vals_[b]);
        if (ka > kb) return true;     // larger key loses
        if (ka < kb) return false;
        return a > b;                 // equal keys: higher index loses (stable)
    }

    // Bottom-up tournament tree construction.
    void build() {
        std::vector<int> winner(2 * k_, -1);

        // Leaves: real sources get their index, padding gets -1 (sentinel)
        for (size_t i = 0; i < k_; ++i) {
            winner[k_ + i] = (i < real_k_) ? static_cast<int>(i) : -1;
        }

        // Internal nodes from bottom to root
        for (int i = static_cast<int>(k_) - 1; i >= 1; --i) {
            int left  = winner[2 * i];
            int right = winner[2 * i + 1];
            if (a_loses(left, right)) {
                tree_[i] = left;      // left is the loser
                winner[i] = right;    // right wins, propagates up
            } else {
                tree_[i] = right;     // right is the loser
                winner[i] = left;     // left wins
            }
        }

        // Overall winner
        tree_[0] = winner[1];
    }

    // Replay after source changed: walk from leaf to root.
    void replay(int source) {
        int cur = source;
        int pos = (static_cast<int>(k_) + source) / 2;
        while (pos >= 1) {
            if (a_loses(cur, tree_[pos])) {
                std::swap(cur, tree_[pos]);
            }
            pos /= 2;
        }
        tree_[0] = cur;
    }

    std::vector<SPSCQueue<T>*> sources_;
    KeyFn key_fn_;
    size_t real_k_;
    size_t k_;              // real_k_ rounded up to power-of-2
    std::vector<int> tree_; // tree_[0]=winner, tree_[1..k-1]=losers
    std::vector<T> vals_;
    std::vector<bool> active_;
};
'''


def main():
    spsc_code = generate_spsc_queue()
    merger_code = generate_feed_merger()

    with open('/app/spsc_queue.hpp', 'w') as f:
        f.write(spsc_code)
    print("Wrote /app/spsc_queue.hpp")

    with open('/app/feed_merger.hpp', 'w') as f:
        f.write(merger_code)
    print("Wrote /app/feed_merger.hpp")


if __name__ == '__main__':
    main()
