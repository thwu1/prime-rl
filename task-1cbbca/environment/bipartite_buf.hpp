#ifndef BIPARTITE_BUF_HPP
#define BIPARTITE_BUF_HPP


#include <atomic>
#include <cstddef>
#include <utility>

/**
 * Lock-free single-producer single-consumer bipartite buffer.
 *
 * A ring buffer variant that guarantees contiguous memory regions for both
 * reads and writes.  Unlike a standard ring buffer where data may wrap around
 * the end, this buffer ensures every acquired region is a single contiguous
 * span of memory.  When a write cannot fit in the remaining tail space, the
 * writer wraps to position 0 and the skipped tail becomes an "invalidation
 * region" that the reader must recognize and skip past.
 *
 * Template parameters:
 *   T - Element type (must be trivially copyable).
 *   N - Total buffer capacity in elements.  Usable capacity is N-1; one slot
 *       is reserved as a sentinel so that write_idx advancing to exactly
 *       read_idx can always be interpreted as "empty," never "full."
 *       (If write_idx could reach read_idx from behind, the full and empty
 *       states become indistinguishable.)
 *
 * Thread safety (SPSC model):
 *   - Exactly ONE producer thread calls WriteAcquire / WriteRelease.
 *   - Exactly ONE consumer thread calls ReadAcquire / ReadRelease.
 *   - No external synchronization is needed between the two threads.
 *   - Use std::memory_order on atomic loads/stores to ensure the consumer
 *     observes the producer's writes (and vice versa) without data races.
 *     The producer reads _read_idx with acquire and writes _write_idx with
 *     release; the consumer does the converse.
 *
 * State variables:
 *   _write_idx      - Position where the producer will next write [0, N).
 *                     Shared: read by consumer (acquire), written by producer (release).
 *   _read_idx       - Position where the consumer will next read [0, N).
 *                     Shared: read by producer (acquire), written by consumer (release).
 *   _invalidate_idx - Upper boundary of valid data before a wrap gap.
 *                     When the producer wraps a write to position 0, it stores
 *                     the old write position here so the reader knows where
 *                     valid data ends.  Value N means "no invalidation region
 *                     is active."  The consumer resets it to N after crossing
 *                     the boundary.
 *   _write_acquired_sz - Producer-local: size of the current acquired write.
 *   _write_wrapped     - Producer-local: whether the current write wraps
 *                        to position 0 (affects how WriteRelease calculates
 *                        the new write index).
 *   _read_acquired_sz  - Consumer-local: size of the current acquired read.
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

    size_t _write_acquired_sz{0};
    bool _write_wrapped{false};

    size_t _read_acquired_sz{0};

public:
    /**
     * Acquire a contiguous region of @p count elements for writing.
     *
     * @param count Number of elements requested (0 < count).
     * @return Pointer to the first writable element, or nullptr if that
     *         many contiguous elements cannot be allocated right now.
     *
     * On success, the caller fills the returned region and then calls
     * WriteRelease().  Only one acquire may be outstanding at a time.
     */
    T* WriteAcquire(size_t count) {
        // TODO: Implement
        (void)count;
        return nullptr;
    }

    /**
     * Commit @p count elements from a prior WriteAcquire.
     *
     * @param count Elements to commit (<= the previously acquired size).
     *
     * Makes the written data visible to the consumer by advancing _write_idx.
     */
    void WriteRelease(size_t count) {
        // TODO: Implement
        (void)count;
    }

    /**
     * Acquire the next contiguous region of readable data.
     *
     * @return {pointer, count} of the available contiguous readable region,
     *         or {nullptr, 0} if the buffer is empty.
     *
     * On success, the caller processes the data and calls ReadRelease().
     * Only one acquire may be outstanding at a time.
     */
    std::pair<T*, size_t> ReadAcquire() {
        // TODO: Implement
        return {nullptr, 0};
    }

    /**
     * Release (consume) @p count elements from a prior ReadAcquire.
     *
     * @param count Elements to release (<= the previously acquired size).
     */
    void ReadRelease(size_t count) {
        // TODO: Implement
        (void)count;
    }
};

#endif // BIPARTITE_BUF_HPP
