#!/usr/bin/env python3
"""
Fix three bugs in the SPSC lock-free queue implementation.

Analysis of /app/spsc_queue.h:

Bug 1 - Wrapping: advance() uses (idx + 1) & (capacity_ - 1), which is a
bit-masking trick that only produces correct wraparound when capacity_ is a
power of 2. For non-power-of-2 capacities, the bitwise AND truncates bits
incorrectly, causing the index to jump to wrong positions. For example, with
capacity_=100: advance(3) = 4 & 99 = 0, making the queue appear full after
only 3 items instead of 99.
Fix: use modulo: (idx + 1) % capacity_.

Bug 2 - Memory ordering: all atomic loads and stores use memory_order_relaxed,
providing no inter-thread synchronization. The C++ memory model requires
acquire/release pairs to establish happens-before relationships between the
producer's buffer write and the consumer's buffer read. Without this, the
consumer could read from the buffer before the producer's write is visible
(a data race per the standard, caught by ThreadSanitizer even on x86/TSO).
Fix: producer reads head_ with acquire, stores tail_ with release;
consumer reads tail_ with acquire, stores head_ with release;
own-index reads (producer reading tail_, consumer reading head_) stay relaxed.

Bug 3 - False sharing: head_ and tail_ are adjacent struct members with no
alignment padding, placing them on the same 64-byte cache line. When the
producer updates tail_ and the consumer updates head_, the cache coherence
protocol bounces the cache line between cores, degrading throughput.
Fix: add alignas(64) to both head_ and tail_.
"""

import re

with open('/app/spsc_queue.h', 'r') as f:
    src = f.read()

# Verify we have the expected buggy file
assert 'SPSCQueue' in src, "Expected SPSCQueue class in /app/spsc_queue.h"
assert 'memory_order_relaxed' in src, "Expected relaxed memory ordering"
assert '& (capacity_ - 1)' in src, "Expected bitwise AND in advance()"

# --- Fix 1: Replace bitwise AND wrapping with modulo ---
src = src.replace(
    '(idx + 1) & (capacity_ - 1)',
    '(idx + 1) % capacity_'
)

# --- Fix 2: Correct memory ordering ---
# In push(): head_.load needs acquire (cross-thread synchronization)
# In push(): tail_.store needs release
# In pop(): tail_.load needs acquire
# In pop(): head_.store needs release
# Own-index reads (tail_.load in push, head_.load in pop) can stay relaxed,
# but changing them to acquire is harmless and simpler to apply globally.

src = src.replace(
    'head_.load(std::memory_order_relaxed)',
    'head_.load(std::memory_order_acquire)',
)
src = src.replace(
    'tail_.load(std::memory_order_relaxed)',
    'tail_.load(std::memory_order_acquire)',
)
src = src.replace(
    'tail_.store(next_tail, std::memory_order_relaxed)',
    'tail_.store(next_tail, std::memory_order_release)',
)
src = src.replace(
    'head_.store(advance(head), std::memory_order_relaxed)',
    'head_.store(advance(head), std::memory_order_release)',
)

# --- Fix 3: Cache line alignment to prevent false sharing ---
src = src.replace(
    '    std::atomic<size_t> head_;',
    '    alignas(64) std::atomic<size_t> head_;',
)
src = src.replace(
    '    std::atomic<size_t> tail_;',
    '    alignas(64) std::atomic<size_t> tail_;',
)

with open('/app/spsc_queue.h', 'w') as f:
    f.write(src)

# Verify the fix compiles
import subprocess
compile_check = subprocess.run(
    ['g++', '-std=c++17', '-O2', '-Wall', '-fsyntax-only',
     '-I/app', '-x', 'c++', '-'],
    input='#include "spsc_queue.h"\nint main() { SPSCQueue<int> q(100); return 0; }',
    capture_output=True, text=True, timeout=30
)
if compile_check.returncode != 0:
    print(f"ERROR: Fixed queue does not compile: {compile_check.stderr}")
    raise SystemExit(1)

print("Fixed 3 bugs: wrapping (modulo), memory ordering (acquire/release), "
      "false sharing (alignas)")
