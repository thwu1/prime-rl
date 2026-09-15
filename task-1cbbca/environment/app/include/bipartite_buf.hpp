#ifndef BIPARTITE_BUF_HPP
#define BIPARTITE_BUF_HPP


#include <atomic>
#include <cstddef>
#include <cstring>
#include <utility>

/**
 * Lock-free single-producer single-consumer bipartite buffer.
 *
 * A ring buffer variant that guarantees contiguous memory regions for both
 * reads and writes. When a write cannot fit at the end of the buffer, it
 * wraps to the beginning and marks the unused tail as an "invalidation region"
 * that the reader must skip.
 *
 * T must be a trivially copyable type. N is the buffer capacity in elements.
 *
 * Producer thread API: WriteAcquire / WriteRelease
 * Consumer thread API: ReadAcquire / ReadRelease
 *
 * Invariants:
 *   - write_idx == read_idx implies the buffer is empty.
 *   - _invalidate_idx marks the end of valid data before a wrap gap;
 *     default value N means "no active invalidation region."
 */
template <typename T, size_t N>
class BipartiteBuf {
    static_assert(N > 1, "Buffer size must be greater than 1");
    static_assert(std::is_trivially_copyable<T>::value,
                  "T must be trivially copyable");

    T _data[N]{};

    alignas(64) std::atomic<size_t> _write_idx{0};
    alignas(64) std::atomic<size_t> _read_idx{0};
    alignas(64) std::atomic<size_t> _invalidate_idx{N};

    // Producer-local bookkeeping (not shared across threads)
    size_t _write_acquired_sz{0};
    bool _write_wrapped{false};

    // Consumer-local bookkeeping
    size_t _read_acquired_sz{0};

public:
    /**
     * Acquire a contiguous region of exactly @p count elements for writing.
     * Returns a pointer to the first element, or nullptr if insufficient
     * contiguous space is available. Must be paired with WriteRelease().
     */
    T* WriteAcquire(size_t count) {
        if (count == 0 || count > N) return nullptr;

        const size_t w = _write_idx.load(std::memory_order_relaxed);
        const size_t r = _read_idx.load(std::memory_order_acquire);

        if (w >= r) {
            // Write pointer is at or ahead of read pointer.
            // Available contiguous space at the tail of the buffer:
            size_t end_space = N - w;

            if (count <= end_space) {
                _write_acquired_sz = count;
                _write_wrapped = false;
                return &_data[w];
            }

            // Not enough room at the tail -- try wrapping to the beginning.
            // Space at the beginning is [0, r-1) (one slot reserved to
            // distinguish full from empty).
            if (r > 0 && count <= r - 1) {
                _invalidate_idx.store(w, std::memory_order_release);
                _write_acquired_sz = count;
                _write_wrapped = true;
                return &_data[0];
            }

            return nullptr;
        } else {
            // w < r: write pointer has wrapped previously, read hasn't caught up.
            size_t space = r - w - 1;
            if (count <= space) {
                _write_acquired_sz = count;
                _write_wrapped = false;
                return &_data[w];
            }
            return nullptr;
        }
    }

    /**
     * Commit @p count written elements (count <= previously acquired size).
     * Advances the write index so the consumer can see the new data.
     */
    void WriteRelease(size_t count) {
        if (count == 0) return;
        if (count > _write_acquired_sz) count = _write_acquired_sz;

        if (_write_wrapped) {
            const size_t w = _write_idx.load(std::memory_order_relaxed);
            _write_idx.store(w + count, std::memory_order_release);
            _write_wrapped = false;
        } else {
            const size_t w = _write_idx.load(std::memory_order_relaxed);
            _write_idx.store(w + count, std::memory_order_release);
        }
        _write_acquired_sz = 0;
    }

    /**
     * Acquire a contiguous region of readable data.
     * Returns {pointer, element_count} or {nullptr, 0} if the buffer is empty.
     * Must be paired with ReadRelease().
     */
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
            // Readable region extends from r up to the invalidation boundary.
            const size_t inv = _invalidate_idx.load(std::memory_order_acquire);
            size_t readable = N - r;

            if (readable == 0) {
                return {nullptr, 0};
            }

            _read_acquired_sz = readable;
            return {&_data[r], _read_acquired_sz};
        }
    }

    /**
     * Release (consume) @p count elements that were previously read.
     * Advances the read index.
     */
    void ReadRelease(size_t count) {
        if (count == 0) return;
        if (count > _read_acquired_sz) count = _read_acquired_sz;

        const size_t r = _read_idx.load(std::memory_order_relaxed);
        _read_idx.store(r + count, std::memory_order_release);
        _read_acquired_sz = 0;
    }
};

#endif // BIPARTITE_BUF_HPP
