#!/usr/bin/env python3
"""
Fix all bugs in the SPSC queue and latency sampler, and implement batch operations.

Bug 1 — index(): uses `seq & (capacity_ - 1)` (bitmask), only correct for pow2.
         Fix: seq % capacity_.

Bug 2 — push() head_.load(relaxed): missing acquire for cross-thread sync.
         Fix: memory_order_acquire.

Bug 3 — pop() tail_.load(relaxed): missing acquire for cross-thread sync.
         Fix: memory_order_acquire.

Bug 4 — False sharing: head_ and tail_ on same cache line.
         Fix: alignas(64) on each.

Bug 5 — push_batch/pop_batch are stubbed.
         Fix: implement with single-load/batch-copy/single-store pattern.

Bug 6 — latency_sampler.h: start_ns and end_ns are non-atomic, causing data races
         when slots are reused under concurrent writer/reader access.
         Fix: make them std::atomic<uint64_t>, use .store()/.load() with relaxed
         ordering (protected by release/acquire on the ready flag).

Bug 7 — latency_sampler.h: relaxed ordering on ready flag doesn't establish
         happens-before for the data fields.
         Fix: release on store, acquire on load.
"""

import subprocess
import sys

# ===================================================================
# Fix spsc_queue.h
# ===================================================================
with open('/app/spsc_queue.h', 'r') as f:
    src = f.read()

# Fix 1: index() — bitmask to modulo
src = src.replace(
    'return seq & (capacity_ - 1);',
    'return seq % capacity_;'
)

# Fix 2a: push() — head_.load needs acquire for cross-thread sync
src = src.replace(
    'if (tail - head_.load(std::memory_order_relaxed) >= capacity_)',
    'if (tail - head_.load(std::memory_order_acquire) >= capacity_)'
)

# Fix 2b: pop() — tail_.load needs acquire for cross-thread sync
src = src.replace(
    'if (head == tail_.load(std::memory_order_relaxed))',
    'if (head == tail_.load(std::memory_order_acquire))'
)

# Fix 3: false sharing — cache-line alignment on head_ and tail_
src = src.replace(
    '    std::atomic<size_t> head_;',
    '    alignas(64) std::atomic<size_t> head_;'
)
src = src.replace(
    '    std::atomic<size_t> tail_;',
    '    alignas(64) std::atomic<size_t> tail_;'
)

# Fix 4: implement push_batch
old_push_batch = """    size_t push_batch(const T* items, size_t count) {
        // TODO: implement efficient batch push that minimizes atomic operations
        (void)items; (void)count;
        return 0;
    }"""

new_push_batch = """    size_t push_batch(const T* items, size_t count) {
        const size_t tail = tail_.load(std::memory_order_relaxed);
        const size_t head = head_.load(std::memory_order_acquire);
        const size_t free_slots = capacity_ - (tail - head);
        const size_t n = (count < free_slots) ? count : free_slots;
        for (size_t i = 0; i < n; i++) {
            new (&buffer_[index(tail + i)]) T(items[i]);
        }
        if (n > 0) {
            tail_.store(tail + n, std::memory_order_release);
        }
        return n;
    }"""

if old_push_batch in src:
    src = src.replace(old_push_batch, new_push_batch)
else:
    import re
    pattern = r'(    size_t push_batch\(const T\* items, size_t count\) \{)[^}]*\}'
    src = re.sub(pattern, new_push_batch, src, flags=re.DOTALL)

# Fix 5: implement pop_batch
old_pop_batch = """    size_t pop_batch(T* out, size_t count) {
        // TODO: implement efficient batch pop that minimizes atomic operations
        (void)out; (void)count;
        return 0;
    }"""

new_pop_batch = """    size_t pop_batch(T* out, size_t count) {
        const size_t head = head_.load(std::memory_order_relaxed);
        const size_t tail = tail_.load(std::memory_order_acquire);
        const size_t available = tail - head;
        const size_t n = (count < available) ? count : available;
        for (size_t i = 0; i < n; i++) {
            size_t idx = index(head + i);
            out[i] = std::move(buffer_[idx]);
            buffer_[idx].~T();
        }
        if (n > 0) {
            head_.store(head + n, std::memory_order_release);
        }
        return n;
    }"""

if old_pop_batch in src:
    src = src.replace(old_pop_batch, new_pop_batch)
else:
    import re
    pattern = r'(    size_t pop_batch\(T\* out, size_t count\) \{)[^}]*\}'
    src = re.sub(pattern, new_pop_batch, src, flags=re.DOTALL)

with open('/app/spsc_queue.h', 'w') as f:
    f.write(src)

# ===================================================================
# Fix latency_sampler.h
# ===================================================================
with open('/app/latency_sampler.h', 'r') as f:
    sampler = f.read()

# Fix 6a: Make Entry data fields atomic to prevent data races on slot reuse.
# When num_slots < total records, the writer overwrites slots that the reader
# may be concurrently reading. Non-atomic fields cause undefined behavior.
sampler = sampler.replace(
    'uint64_t start_ns = 0;',
    'std::atomic<uint64_t> start_ns{0};'
)
sampler = sampler.replace(
    'uint64_t end_ns = 0;',
    'std::atomic<uint64_t> end_ns{0};'
)

# Fix 6b: record() — use atomic store for data fields
sampler = sampler.replace(
    'entries_[idx].start_ns = start_ns;',
    'entries_[idx].version.fetch_add(1, std::memory_order_acq_rel);\n'
    '        entries_[idx].start_ns.store(start_ns, std::memory_order_relaxed);'
)
sampler = sampler.replace(
    'entries_[idx].end_ns = end_ns;',
    'entries_[idx].end_ns.store(end_ns, std::memory_order_relaxed);'
)

# Fix 7a: record() ready flag needs release ordering
sampler = sampler.replace(
    'entries_[idx].ready.store(true, std::memory_order_relaxed);',
    'entries_[idx].ready.store(true, std::memory_order_release);\n'
    '        entries_[idx].version.fetch_add(1, std::memory_order_release);'
)

# Fix 7b: read_latency() ready flag needs acquire ordering
sampler = sampler.replace(
    'entries_[idx].ready.load(std::memory_order_relaxed)',
    'entries_[idx].ready.load(std::memory_order_acquire)'
)

# Fix 6c: read_latency() — use a sequence lock so a reader never combines the
# start timestamp from one ring-buffer generation with the end timestamp from
# another. Atomic fields alone prevent a C++ data race but not a torn pair.
sampler = sampler.replace(
    '''if (!entries_[idx].ready.load(std::memory_order_acquire)) {
            return -1;
        }
        return static_cast<int64_t>(entries_[idx].end_ns - entries_[idx].start_ns);''',
    '''const Entry& entry = entries_[idx];
        for (int attempt = 0; attempt < 3; ++attempt) {
            const uint64_t before = entry.version.load(std::memory_order_acquire);
            if (before == 0 || (before & 1U) != 0) {
                return -1;
            }
            const uint64_t start = entry.start_ns.load(std::memory_order_relaxed);
            const uint64_t end = entry.end_ns.load(std::memory_order_relaxed);
            const uint64_t after = entry.version.load(std::memory_order_acquire);
            if (before == after && (after & 1U) == 0) {
                return end >= start ? static_cast<int64_t>(end - start) : -1;
            }
        }
        return -1;'''
)

sampler = sampler.replace(
    'std::atomic<bool> ready{false};',
    'std::atomic<bool> ready{false};\n'
    '        std::atomic<uint64_t> version{0};'
)

with open('/app/latency_sampler.h', 'w') as f:
    f.write(sampler)

# ===================================================================
# Verify compilation
# ===================================================================
result = subprocess.run(
    ['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-pthread',
     '-fsyntax-only', '/app/main.cpp', '-I/app'],
    capture_output=True, text=True, timeout=30
)
if result.returncode != 0:
    print(f"ERROR: Fixed code does not compile:\n{result.stderr}", file=sys.stderr)
    sys.exit(1)

print("All fixes applied successfully:")
print("  1. index(): bitmask -> modulo (arbitrary capacity support)")
print("  2. push() head_.load: relaxed -> acquire")
print("  3. pop() tail_.load: relaxed -> acquire")
print("  4. alignas(64) on head_ and tail_ (false sharing elimination)")
print("  5. push_batch() implemented (single-load, batch-copy, single-store)")
print("  6. pop_batch() implemented (single-load, batch-move, single-store)")
print("  7. latency_sampler: start_ns/end_ns -> std::atomic<uint64_t>")
print("  8. latency_sampler: relaxed -> release/acquire on ready flag")
