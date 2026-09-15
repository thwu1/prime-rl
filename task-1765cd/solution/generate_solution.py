#!/usr/bin/env python3
"""
Generate a lock-free SPSC bounded queue implementation.

Derives the solution by constructing the C++ source through programmatic
assembly of components: memory ordering semantics, cache line alignment,
and ring buffer index management.
"""

import os
import sys

# Memory ordering constants used in the implementation
MEMORY_ORDERS = {
    "relaxed": "std::memory_order_relaxed",
    "acquire": "std::memory_order_acquire",
    "release": "std::memory_order_release",
}

# Cache line size for false sharing prevention
CACHE_LINE_BYTES = 64


def build_includes():
    """Construct the include directives."""
    headers = ["atomic", "cstddef", "cstdint", "new", "memory"]
    lines = ["#pragma once", ""]
    for h in headers:
        lines.append(f"#include <{h}>")
    lines.append("")
    return lines


def build_class_open():
    """Construct class declaration and constructor."""
    return [
        "template <typename T>",
        "class SPSCQueue {",
        "public:",
        "    explicit SPSCQueue(std::size_t capacity)",
        "        : capacity_(capacity + 1)",
        "        , buffer_(static_cast<T*>(::operator new(sizeof(T) * capacity_)))",
        "    {",
        f"        head_.store(0, {MEMORY_ORDERS['relaxed']});",
        f"        tail_.store(0, {MEMORY_ORDERS['relaxed']});",
        "    }",
        "",
    ]


def build_destructor():
    """Construct destructor that drains remaining elements."""
    mo = MEMORY_ORDERS["relaxed"]
    return [
        "    ~SPSCQueue() {",
        f"        std::size_t h = head_.load({mo});",
        f"        std::size_t t = tail_.load({mo});",
        "        while (h != t) {",
        "            std::destroy_at(&buffer_[h]);",
        "            h = (h + 1) % capacity_;",
        "        }",
        "        ::operator delete(buffer_);",
        "    }",
        "",
        "    SPSCQueue(const SPSCQueue&) = delete;",
        "    SPSCQueue& operator=(const SPSCQueue&) = delete;",
        "",
    ]


def build_push():
    """
    Construct push() with correct memory ordering:
    - Relaxed load of tail (only producer writes tail, no cross-thread sync needed)
    - Acquire load of head (consumer writes head; acquire ensures we see
      the consumer's prior destruction of buffer elements)
    - Release store of tail (ensures buffer write is visible to consumer
      before the tail index update)
    """
    mo_r = MEMORY_ORDERS["relaxed"]
    mo_a = MEMORY_ORDERS["acquire"]
    mo_rel = MEMORY_ORDERS["release"]

    return [
        "    bool push(const T& item) {",
        f"        std::size_t curr_tail = tail_.load({mo_r});",
        "        std::size_t next_tail = (curr_tail + 1) % capacity_;",
        f"        if (next_tail == head_.load({mo_a})) return false;",
        "        std::construct_at(&buffer_[curr_tail], item);",
        f"        tail_.store(next_tail, {mo_rel});",
        "        return true;",
        "    }",
        "",
    ]


def build_consume():
    """
    Construct consume_one() with correct memory ordering:
    - Relaxed load of head (only consumer writes head)
    - Acquire load of tail (producer writes tail; acquire ensures we see
      the fully constructed element before reading it)
    - Release store of head (ensures element destruction is visible to
      producer before the head index update)
    """
    mo_r = MEMORY_ORDERS["relaxed"]
    mo_a = MEMORY_ORDERS["acquire"]
    mo_rel = MEMORY_ORDERS["release"]

    return [
        "    template <typename Func>",
        "    bool consume_one(Func&& func) {",
        f"        std::size_t curr_head = head_.load({mo_r});",
        f"        if (curr_head == tail_.load({mo_a})) return false;",
        "        func(buffer_[curr_head]);",
        "        std::destroy_at(&buffer_[curr_head]);",
        f"        head_.store((curr_head + 1) % capacity_, {mo_rel});",
        "        return true;",
        "    }",
        "",
    ]


def build_capacity():
    """Construct capacity accessor."""
    return [
        "    std::size_t capacity() const { return capacity_ - 1; }",
        "",
    ]


def build_private_members():
    """
    Construct private members with cache line separation.
    head_ and tail_ are placed on separate cache lines using alignas()
    to prevent false sharing between producer and consumer threads.
    """
    cl = CACHE_LINE_BYTES
    return [
        "private:",
        "    const std::size_t capacity_;",
        "    T* const buffer_;",
        "",
        f"    alignas({cl}) std::atomic<std::size_t> head_;",
        f"    alignas({cl}) std::atomic<std::size_t> tail_;",
        "};",
        "",
    ]


def generate():
    """Assemble all components into the complete implementation."""
    sections = [
        build_includes(),
        build_class_open(),
        build_destructor(),
        build_push(),
        build_consume(),
        build_capacity(),
        build_private_members(),
    ]

    lines = []
    for section in sections:
        lines.extend(section)

    return "\n".join(lines)


def main():
    output_path = "/app/include/spsc_queue.hpp"
    content = generate()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(content)

    # Verify key properties of the generated code
    checks = {
        "atomic": "std::atomic" in content,
        "acquire": MEMORY_ORDERS["acquire"] in content,
        "release": MEMORY_ORDERS["release"] in content,
        "alignas": f"alignas({CACHE_LINE_BYTES})" in content,
        "no_mutex": "mutex" not in content.lower(),
    }

    print(f"Generated lock-free SPSC queue at {output_path}")
    for name, passed in checks.items():
        status = "OK" if passed else "FAIL"
        print(f"  {name}: {status}")

    if not all(checks.values()):
        print("ERROR: Generated code failed verification", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
