#pragma once

#include <stddef.h>
#include <stdint.h>


struct HeapItem {
    uint64_t val = 0;   // the priority value (e.g., expiry timestamp)
    size_t *ref = NULL; // pointer to the owner's index field; must be updated on move
};

// Restore heap property at position `pos` in array `a` of length `len`.
// If a[pos] is smaller than its parent, sift up; otherwise sift down.
// Must update *ref for every item that moves.
void heap_update(HeapItem *a, size_t pos, size_t len);
