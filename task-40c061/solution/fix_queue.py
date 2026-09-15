#!/usr/bin/env python3
"""
Fix all four bugs in the SPSC queue implementation.

Bug 1: Ring buffer capacity off-by-one (needs capacity + 1 for sentinel slot)
Bug 2: consume_one reads from tail position instead of head position
Bug 3: All memory orderings are relaxed; cross-thread loads need acquire,
       cross-thread stores need release
Bug 4: head_ and tail_ atomics share a cache line (false sharing)
"""


import sys

QUEUE_PATH = "/app/spsc_queue.hpp"

with open(QUEUE_PATH, "r") as f:
    content = f.read()

original = content

# --- Fix 1: Capacity off-by-one ---
# Ring buffer uses one slot as sentinel to distinguish full from empty.
# A queue advertising capacity N needs N+1 internal slots.
content = content.replace(
    ": capacity_{capacity}",
    ": capacity_{capacity + 1}"
)

# --- Fix 2: Wrong index in consume_one ---
# consume_one reads buffer_[currTail] (the next WRITE position, which is
# either uninitialized or stale). Must read buffer_[currHead] (the oldest
# unconsumed element).
content = content.replace(
    "T& elem = *reinterpret_cast<T*>(&buffer_[currTail]);",
    "T& elem = *reinterpret_cast<T*>(&buffer_[currHead]);"
)

# --- Fix 3: Memory ordering ---
# Cross-thread loads need acquire; cross-thread stores need release.
# Own-thread loads (tail_ in push, head_ in consume_one) stay relaxed.

# 3a: In push(), head_.load is a cross-thread read (consumer writes head_)
content = content.replace(
    "nextTail == head_.load(std::memory_order_relaxed))",
    "nextTail == head_.load(std::memory_order_acquire))"
)

# 3b: In consume_one(), tail_.load is a cross-thread read (producer writes tail_)
# Use multi-line context to avoid changing the push() tail_.load (own-thread)
content = content.replace(
    "currTail = tail_.load(std::memory_order_relaxed);\n        if (currHead == currTail)",
    "currTail = tail_.load(std::memory_order_acquire);\n        if (currHead == currTail)"
)

# 3c: In push(), tail_.store is a cross-thread write (consumer reads tail_)
content = content.replace(
    "tail_.store(nextTail, std::memory_order_relaxed)",
    "tail_.store(nextTail, std::memory_order_release)"
)

# 3d: In consume_one(), head_.store is a cross-thread write (producer reads head_)
content = content.replace(
    "head_.store(increment(currHead), std::memory_order_relaxed)",
    "head_.store(increment(currHead), std::memory_order_release)"
)

# --- Fix 4: False sharing ---
# head_ (written by consumer) and tail_ (written by producer) must be on
# separate cache lines. alignas(64) ensures each starts at a 64-byte boundary.
content = content.replace(
    "    std::atomic<std::size_t> head_{0};\n    std::atomic<std::size_t> tail_{0};",
    "    alignas(64) std::atomic<std::size_t> head_{0};\n    alignas(64) std::atomic<std::size_t> tail_{0};"
)

if content == original:
    print("ERROR: No replacements matched — file may have been modified", file=sys.stderr)
    sys.exit(1)

with open(QUEUE_PATH, "w") as f:
    f.write(content)

print("All 4 bugs fixed in", QUEUE_PATH)
