#!/usr/bin/env python3
"""
Implement the four core methods of the lock-free SPSC bipartite buffer.

This writes the complete correct implementation into the skeleton header.
"""

HEADER = r'''#ifndef BIPARTITE_BUF_HPP
#define BIPARTITE_BUF_HPP

#include <atomic>
#include <cstddef>
#include <utility>

template <typename T, size_t N>
class BipartiteBuf {
    static_assert(N > 1, "Buffer size must be greater than 1");
    static_assert(std::is_trivially_copyable<T>::value,
                  "T must be trivially copyable");

    T _data[N]{};

    alignas(64) std::atomic<size_t> _write_idx{0};
    alignas(64) std::atomic<size_t> _read_idx{0};
    alignas(64) std::atomic<size_t> _invalidate_idx{N};

    size_t _write_acquired_sz{0};
    bool _write_wrapped{false};
    size_t _read_acquired_sz{0};

public:
    T* WriteAcquire(size_t count) {
        if (count == 0 || count > N) return nullptr;

        const size_t w = _write_idx.load(std::memory_order_relaxed);
        const size_t r = _read_idx.load(std::memory_order_acquire);

        if (w >= r) {
            size_t end_space = N - w;
            // When r == 0, one tail slot must stay empty as a sentinel
            // to distinguish full from empty.
            if (r == 0 && end_space > 0) end_space--;

            if (count <= end_space) {
                _write_acquired_sz = count;
                _write_wrapped = false;
                return &_data[w];
            }

            // Tail is too small; try wrapping to position 0.
            // Space at the beginning is [0, r-1).
            if (r > 0 && count <= r - 1) {
                _invalidate_idx.store(w, std::memory_order_release);
                _write_acquired_sz = count;
                _write_wrapped = true;
                return &_data[0];
            }

            return nullptr;
        } else {
            // w < r: writer has previously wrapped, reader hasn't caught up.
            size_t space = r - w - 1;
            if (count <= space) {
                _write_acquired_sz = count;
                _write_wrapped = false;
                return &_data[w];
            }
            return nullptr;
        }
    }

    void WriteRelease(size_t count) {
        if (count == 0) return;
        if (count > _write_acquired_sz) count = _write_acquired_sz;

        if (_write_wrapped) {
            // After a wrap, write started at position 0, so new index is count.
            _write_idx.store(count, std::memory_order_release);
            _write_wrapped = false;
        } else {
            const size_t w = _write_idx.load(std::memory_order_relaxed);
            _write_idx.store(w + count, std::memory_order_release);
        }
        _write_acquired_sz = 0;
    }

    std::pair<T*, size_t> ReadAcquire() {
        const size_t r = _read_idx.load(std::memory_order_relaxed);
        const size_t w = _write_idx.load(std::memory_order_acquire);

        if (r == w) return {nullptr, 0};

        if (w > r) {
            // Normal case: readable region is [r, w).
            _read_acquired_sz = w - r;
            return {&_data[r], _read_acquired_sz};
        } else {
            // w <= r: writer has wrapped around.
            const size_t inv = _invalidate_idx.load(std::memory_order_acquire);
            size_t readable = inv - r;

            if (readable == 0) {
                // Reader reached the invalidation boundary; wrap to position 0.
                _read_idx.store(0, std::memory_order_release);
                _invalidate_idx.store(N, std::memory_order_release);
                if (w == 0) return {nullptr, 0};
                _read_acquired_sz = w;
                return {&_data[0], _read_acquired_sz};
            }

            _read_acquired_sz = readable;
            return {&_data[r], _read_acquired_sz};
        }
    }

    void ReadRelease(size_t count) {
        if (count == 0) return;
        if (count > _read_acquired_sz) count = _read_acquired_sz;

        const size_t r = _read_idx.load(std::memory_order_relaxed);
        _read_idx.store(r + count, std::memory_order_release);
        _read_acquired_sz = 0;
    }
};

#endif // BIPARTITE_BUF_HPP
'''

with open("/app/include/bipartite_buf.hpp", "w") as f:
    f.write(HEADER)

print("Bipartite buffer implementation written successfully.")
