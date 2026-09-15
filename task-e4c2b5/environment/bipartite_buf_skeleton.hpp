#ifndef BIPARTITE_BUF_HPP
#define BIPARTITE_BUF_HPP


#include <atomic>
#include <cstddef>
#include <utility>
#include <type_traits>

namespace lockfree {
namespace spsc {

/**
 * Lock-free single-producer single-consumer bipartite buffer.
 *
 * Provides contiguous memory regions for both writes and reads,
 * enabling zero-copy producer-consumer communication.
 *
 * See /app/spec.md for the full algorithm specification.
 *
 * @tparam T Element type (must be trivial)
 * @tparam N Buffer capacity in elements
 */
template <typename T, size_t N>
class BipartiteBuf {
    static_assert(N > 0, "Buffer capacity must be positive");
    static_assert(std::is_trivial<T>::value, "T must be a trivial type");

    // TODO: Add atomic indices (write, read, invalidation) with proper alignment
    // TODO: Add acquire/release tracking state

    T _data[N];

public:
    BipartiteBuf() = default;
    BipartiteBuf(const BipartiteBuf&) = delete;
    BipartiteBuf& operator=(const BipartiteBuf&) = delete;

    /**
     * Acquire a contiguous region for writing.
     * @param n Number of elements requested
     * @return Pointer to contiguous writable region, or nullptr
     */
    T* WriteAcquire(size_t n) {
        // TODO: Implement according to spec.md
        (void)n;
        return nullptr;
    }

    /**
     * Commit written elements to the buffer.
     * @param n Number of elements to commit (<= acquired count)
     */
    void WriteRelease(size_t n) {
        // TODO: Implement according to spec.md
        (void)n;
    }

    /**
     * Acquire available contiguous data for reading.
     * @return {pointer, count} of readable data, or {nullptr, 0}
     */
    std::pair<T*, size_t> ReadAcquire() {
        // TODO: Implement according to spec.md
        return {nullptr, 0};
    }

    /**
     * Release consumed elements.
     * @param n Number of elements to release (<= acquired count)
     */
    void ReadRelease(size_t n) {
        // TODO: Implement according to spec.md
        (void)n;
    }
};

} // namespace spsc
} // namespace lockfree

#endif // BIPARTITE_BUF_HPP
