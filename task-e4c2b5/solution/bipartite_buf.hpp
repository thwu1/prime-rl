#ifndef BIPARTITE_BUF_HPP
#define BIPARTITE_BUF_HPP


#include <atomic>
#include <cstddef>
#include <utility>
#include <type_traits>

namespace lockfree {
namespace spsc {

template <typename T, size_t N>
class BipartiteBuf {
    static_assert(N > 0, "Buffer capacity must be positive");
    static_assert(std::is_trivial<T>::value, "T must be a trivial type");

    static constexpr size_t kNoInvalidation = static_cast<size_t>(-1);

    alignas(64) std::atomic<size_t> _w{0};
    alignas(64) std::atomic<size_t> _r{0};
    alignas(64) std::atomic<size_t> _i{kNoInvalidation};

    T _data[N];

    // Producer-local state (only accessed by producer thread)
    bool _write_in_progress{false};
    bool _write_wrapped{false};

    // Consumer-local state (only accessed by consumer thread)
    bool _read_in_progress{false};

public:
    BipartiteBuf() = default;
    BipartiteBuf(const BipartiteBuf&) = delete;
    BipartiteBuf& operator=(const BipartiteBuf&) = delete;

    T* WriteAcquire(size_t n) {
        if (n == 0 || n > N || _write_in_progress) return nullptr;

        const size_t w = _w.load(std::memory_order_relaxed);
        const size_t r = _r.load(std::memory_order_acquire);

        if (w >= r) {
            // Detect wrapped-full state: w caught up to r with invalidation active
            if (w == r && _i.load(std::memory_order_relaxed) != kNoInvalidation) {
                return nullptr;
            }
            // Try tail region [w, N)
            if (N - w >= n) {
                _write_in_progress = true;
                _write_wrapped = false;
                return &_data[w];
            }
            // Try head region [0, r) via wrap
            if (r > 0 && n <= r) {
                _write_in_progress = true;
                _write_wrapped = true;
                return &_data[0];
            }
        } else {
            // Wrapped state: available space is [w, r)
            if (r - w >= n) {
                _write_in_progress = true;
                _write_wrapped = false;
                return &_data[w];
            }
        }
        return nullptr;
    }

    void WriteRelease(size_t n) {
        if (!_write_in_progress) return;
        if (n > 0) {
            const size_t w = _w.load(std::memory_order_relaxed);
            if (_write_wrapped) {
                // Update write index FIRST so that the _i release
                // carries the new _w into the consumer's acquire chain.
                _w.store(n, std::memory_order_release);
                _i.store(w, std::memory_order_release);
            } else {
                _w.store(w + n, std::memory_order_release);
            }
        }
        _write_in_progress = false;
        _write_wrapped = false;
    }

    std::pair<T*, size_t> ReadAcquire() {
        if (_read_in_progress) return {nullptr, 0};

        size_t r = _r.load(std::memory_order_relaxed);
        // Load _i FIRST (acquire): if we see a new invalidation value,
        // the synchronization guarantees the preceding _w store is visible.
        size_t i = _i.load(std::memory_order_acquire);
        const size_t w = _w.load(std::memory_order_acquire);

        // At invalidation boundary: wrap read to beginning
        if (i != kNoInvalidation && r == i) {
            _i.store(kNoInvalidation, std::memory_order_release);
            _r.store(0, std::memory_order_release);
            r = 0;
            i = kNoInvalidation;
        }

        // Linear data ahead
        if (w > r) {
            _read_in_progress = true;
            return {&_data[r], w - r};
        }

        // Tail data before invalidation point
        if (i != kNoInvalidation && i > r) {
            _read_in_progress = true;
            return {&_data[r], i - r};
        }

        return {nullptr, 0};
    }

    void ReadRelease(size_t n) {
        if (!_read_in_progress) return;
        if (n > 0) {
            const size_t r = _r.load(std::memory_order_relaxed);
            _r.store(r + n, std::memory_order_release);
        }
        _read_in_progress = false;
    }
};

} // namespace spsc
} // namespace lockfree

#endif // BIPARTITE_BUF_HPP
