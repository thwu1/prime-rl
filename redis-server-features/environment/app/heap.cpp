#include "heap.h"

// TODO: Implement the min-heap update operation.
// After the value of a[pos] is changed, this function must restore
// the min-heap property by sifting up or down as needed.
//
// IMPORTANT: Each HeapItem has a `ref` pointer to a size_t that stores
// the item's current index in the heap array. Whenever an item is moved
// to a new position during sift-up or sift-down, you MUST update *ref
// to reflect the new position. This enables O(log N) deletion and update
// of arbitrary items by their owners.
void heap_update(HeapItem *a, size_t pos, size_t len) {
    (void)a;
    (void)pos;
    (void)len;
    // STUB: not implemented
}
