# SPSC Queue Diagnostic Analysis

## 1. Buffer Boundary Overflow (Critical — Data Corruption)

**Symptom:** `test_data_integrity` reports memory written past buffer boundary and data corruption for messages near capacity.

**Root Cause:** `Producer::write()` performs `memcpy(buffer_ + offset, data, size)` without checking whether `offset + size` exceeds `capacity_`. When a message straddles the circular buffer boundary (e.g., write offset 924, message size 124, buffer capacity 1024), the memcpy writes 24 bytes past the allocated region. The identical issue exists in `Consumer::read()`.

**Fix:** Implemented `detail::write_wrap()` and `detail::read_wrap()` helper functions that split the memcpy into two parts when data crosses the buffer boundary:

```cpp
inline void write_wrap(char* buf, size_t cap, size_t offset,
                       const void* src, size_t n) {
    size_t first = std::min(n, cap - offset);
    std::memcpy(buf + offset, src, first);
    if (first < n)
        std::memcpy(buf, static_cast<const char*>(src) + first, n - first);
}
```

Both the length prefix and payload use these wrappers to handle the case where either straddles the boundary.

**Evidence:** Compiled with `-fsanitize=address`:
```
==PID==: ERROR: AddressSanitizer: heap-buffer-overflow on address 0x...
WRITE of size 120 at 0x...
    #0 __asan_memcpy
    #1 spsc::Producer::write(void const*, unsigned int)
```

## 2. False Sharing Between Position Counters (Performance)

**Symptom:** Under concurrent producer/consumer load, throughput is lower than expected due to excessive cache coherency traffic. No correctness failure observed.

**Root Cause:** `QueueHeader` places `write_pos_` (offset 0) and `read_pos_` (offset 8) in adjacent memory within the same 64-byte cache line. Every producer store to `write_pos_` invalidates the consumer's cached copy of the entire line containing `read_pos_`, and vice versa.

**Fix:** Applied `alignas(kCacheLineSize)` (64 bytes from config.h) to each atomic member, forcing them onto separate cache lines:

```cpp
struct QueueHeader {
    alignas(kCacheLineSize) std::atomic<uint64_t> write_pos_{0};
    alignas(kCacheLineSize) std::atomic<uint64_t> read_pos_{0};
};
```

**Evidence:** Verified with `offsetof()` test program:
- Before: `&read_pos_ - &write_pos_ = 8 bytes` (same cache line)
- After: `&read_pos_ - &write_pos_ = 64 bytes` (separate cache lines)

## 3. Excessive Memory Ordering Strength (Performance)

**Symptom:** All atomic operations use `memory_order_seq_cst`, generating unnecessarily expensive instructions on x86-64.

**Root Cause:** An SPSC queue only needs release semantics for producer stores (writes are ordered before the position update) and acquire semantics for consumer loads (position check is ordered before data reads). Sequential consistency is strictly stronger than needed and forces `XCHG` or `MOV+MFENCE` instructions instead of plain `MOV`.

**Fix:** Changed producer stores to `memory_order_release` and consumer loads to `memory_order_acquire`.

**Evidence:** Disassembly comparison via `objdump -d`:
- Before (seq_cst store): `xchg %rax, (%rdx)` — implicit lock prefix, full memory barrier
- After (release store): `mov %rax, (%rdx)` — plain store, sufficient on x86-64 TSO architecture

## 4. Missing Write-Position Reservation (Performance / Semantic Defect)

**Symptom:** `test_deferred_visibility` fails — all 700 messages are visible to the consumer before `flush()` is called, making `flush()` semantically meaningless.

**Root Cause:** `Producer::write()` unconditionally stores `current_pos_` to the atomic `write_pos_` on every message, making all writes immediately visible. The `reserved_end_` field exists in the class but is never used.

**Fix:** Implemented write-position reservation using `kReservationSize` (64 KB from config.h). The producer only publishes `write_pos_` when the accumulated writes exceed the current reservation chunk:

```cpp
if (wp + total > reserved_end_) {
    header_->write_pos_.store(wp, std::memory_order_release);
    reserved_end_ = wp + kReservationSize;
}
```

`flush()` publishes the final position unconditionally.

**Evidence:** After fix, the deferred visibility test shows 630/700 messages visible before flush — confirming that only one reservation boundary at 65536 bytes is crossed, with the remaining messages deferred until explicit flush.

## 5. Missing Read-Side Caching (Performance)

**Symptom:** Consumer performs an atomic load of `write_pos_` on every `read()` call, even when the previously loaded value indicates more messages are available.

**Root Cause:** `Consumer::read()` unconditionally loads from the atomic at the start of every call, ignoring the `cached_write_pos_` member variable which exists but is never utilized.

**Fix:** The consumer now checks `cached_write_pos_` first. Only when `local_pos_ >= cached_write_pos_` does it reload from the atomic:

```cpp
if (local_pos_ >= cached_write_pos_) {
    cached_write_pos_ = header_->write_pos_.load(std::memory_order_acquire);
    if (local_pos_ >= cached_write_pos_) return 0;
}
```

This eliminates the majority of atomic loads during burst reads, reducing cache-line contention.

## 6. Uninitialized Protocol Header (Correctness)

**Symptom:** `test_protocol_lifecycle` fails — identity field reads as zero after `ShmManager::create()`.

**Root Cause:** `ShmManager::create()` zeroes the `ProtocolHeader` region with `memset` but never assigns the magic number, version, queue offset, or capacity fields. A consumer opening this segment cannot distinguish it from an arbitrary file.

**Fix:** Explicitly initialize all fields after mapping:

```cpp
header->magic          = kProtocolMagic;
header->major_version  = kMajorVersion;
header->minor_version  = kMinorVersion;
header->queue_offset   = sizeof(ProtocolHeader);
header->queue_capacity = queue_capacity;
header->total_size     = total_size;
```

## 7. Missing Protocol Validation on Open (Correctness)

**Symptom:** `test_protocol_lifecycle` fails — tampered segment is accepted without error, allowing silent data corruption from incompatible files.

**Root Cause:** `ShmManager::open()` maps the file and returns a pointer without verifying the magic number or checking for compatible protocol versions.

**Fix:** Added validation after mmap in `open()`:

```cpp
if (header->magic != kProtocolMagic)
    throw std::runtime_error("invalid magic number");
if (header->major_version != kMajorVersion)
    throw std::runtime_error("incompatible major version");
```

**Evidence:** After fix, `open()` correctly throws `std::runtime_error` when presented with a segment whose magic has been tampered to `0xBADF00D`.
