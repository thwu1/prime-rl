"""Naive top-down merge sort for baseline comparison."""


def naive_mergesort(arr):
    """Sort arr in-place using standard merge sort. Returns total merge cost.

    Merge cost is defined as the sum of (hi - lo) for each merge operation,
    i.e., the total number of elements written during all merges.
    """
    cost = [0]

    def merge(a, lo, mid, hi):
        left = a[lo:mid]
        right = a[mid:hi]
        i = j = 0
        k = lo
        while i < len(left) and j < len(right):
            if left[i] <= right[j]:
                a[k] = left[i]
                i += 1
            else:
                a[k] = right[j]
                j += 1
            k += 1
        while i < len(left):
            a[k] = left[i]
            i += 1
            k += 1
        while j < len(right):
            a[k] = right[j]
            j += 1
            k += 1
        cost[0] += hi - lo

    def msort(a, lo, hi):
        if hi - lo <= 1:
            return
        mid = (lo + hi) // 2
        msort(a, lo, mid)
        msort(a, mid, hi)
        merge(a, lo, mid, hi)

    msort(arr, 0, len(arr))
    return cost[0]
