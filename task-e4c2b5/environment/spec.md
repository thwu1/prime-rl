# Lock-Free SPSC Bipartite Buffer Specification

## Overview

A **bipartite buffer** is a variant of a circular buffer that guarantees **contiguous (linear) memory regions** for both writes and reads. Unlike a standard ring buffer where data may wrap around the buffer boundary and require two-part copies, a bipartite buffer ensures that each write allocation returns a single contiguous pointer, and each read returns contiguous data.

This property is critical for zero-copy operations such as DMA transfers, network packet processing, and serialization where the consumer needs contiguous access to data without intermediate copies.

## Algorithm Concept

The buffer maintains three indices:

- **write index (`w`)**: Points to the next write position. Modified only by the producer thread.
- **read index (`r`)**: Points to the next read position. Modified only by the consumer thread.
- **invalidation index (`i`)**: Marks the boundary where valid tail data ends when the write has wrapped to the beginning of the buffer.

### Invalidation Mechanism

When a write request cannot fit in the contiguous space remaining at the tail of the buffer, but there is sufficient space at the beginning (before the read index), the buffer:

1. Records the current write position as the **invalidation index** — marking the end of valid data in the tail region.
2. Wraps the write to position 0, returning a pointer to the buffer's beginning.

The consumer uses the invalidation index to know where to stop reading in the tail. When the consumer's read position reaches the invalidation index, it wraps its read position to 0 and clears the invalidation.

### Buffer States

- **Linear**: `w >= r`, no invalidation active. Data occupies `[r, w)`.
- **Wrapped**: `w < r`, invalidation is active. Data occupies `[r, i)` (tail) and `[0, w)` (head).
- **Empty**: `w == r` with no invalidation.
- **Full**: All space consumed — no room for new writes.

## API

```cpp
namespace lockfree {
namespace spsc {

template <typename T, size_t N>
class BipartiteBuf {
public:
    BipartiteBuf();

    // Producer API — call only from a single producer thread
    T* WriteAcquire(size_t n);
    void WriteRelease(size_t n);

    // Consumer API — call only from a single consumer thread
    std::pair<T*, size_t> ReadAcquire();
    void ReadRelease(size_t n);
};

} // namespace spsc
} // namespace lockfree
```

### `T* WriteAcquire(size_t n)`

Requests a contiguous region of at least `n` elements for writing.

**Returns**: Pointer to the start of the writable region, or `nullptr` if insufficient contiguous space is available.

**Behavior**:
- If enough space exists at the tail (after the write index), returns a pointer there.
- If insufficient tail space but enough space at the beginning (before the read index), prepares to wrap and returns a pointer to position 0.
- Returns `nullptr` for `n == 0` or `n > N`.
- Must not be called again before the matching `WriteRelease`.

### `void WriteRelease(size_t n)`

Commits `n` elements to the buffer, making them visible to the consumer.

**Precondition**: `WriteAcquire` returned non-null. `n <= ` the count passed to `WriteAcquire`.

**Behavior**:
- If the write wrapped to the beginning, sets the invalidation index at the old write position and updates the write index to `n`.
- If the write did not wrap, advances the write index by `n`.
- `n == 0` cancels the acquire without committing data.

### `std::pair<T*, size_t> ReadAcquire()`

Acquires all available contiguous data for reading.

**Returns**: `{pointer, count}` of the contiguous readable region, or `{nullptr, 0}` if no data is available.

**Behavior**:
- If the read index has reached the invalidation point, wraps the read index to 0 and clears the invalidation before checking for data.
- In linear state, returns data from the read index up to the write index.
- In wrapped state, returns tail data from the read index up to the invalidation index.
- Must not be called again before the matching `ReadRelease`.

### `void ReadRelease(size_t n)`

Releases `n` consumed elements, freeing space for the producer.

**Precondition**: `ReadAcquire` returned non-null. `n <= ` the count returned by `ReadAcquire`.

**Behavior**:
- Advances the read index by `n`.
- `n == 0` cancels the acquire without consuming data.

## Memory Ordering Requirements

The buffer must be **lock-free**, using only `std::atomic` operations with appropriate memory orderings:

- **Release semantics** when updating an index that makes data or space visible to the other thread (e.g., advancing the write index after writing data, advancing the read index after consuming data).
- **Acquire semantics** when loading an index written by the other thread (e.g., loading the write index to see new data, loading the read index to see freed space).
- **Relaxed** is acceptable for loading an index that only the current thread modifies, or for stores that are ordered by a subsequent release store on a different variable.

## Constraints

- `T` must be a [trivial type](https://en.cppreference.com/w/cpp/language/classes#Trivial_class).
- `N` must be greater than 0.
- Exactly one producer thread and one consumer thread may use the buffer concurrently.
- Cacheline alignment (`alignas(64)`) of atomic indices is recommended to prevent [false sharing](https://en.wikipedia.org/wiki/False_sharing).
- The buffer uses no dynamic allocation.
