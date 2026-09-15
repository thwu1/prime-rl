"""
Adaptive merge sort with C-accelerated scheduling.

"""

import ctypes
import os
import sys

sys.setrecursionlimit(10000)

MIN_RUN = 32

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "csort", "libschedule.so")
_schedule_lib = None


def _load_lib():
    global _schedule_lib
    if _schedule_lib is None:
        _schedule_lib = ctypes.CDLL(_lib_path)
        _schedule_lib.compute_merge_schedule.restype = ctypes.c_longlong
        _schedule_lib.compute_merge_schedule.argtypes = [
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
    return _schedule_lib


def binary_insertion_sort(arr, lo, hi, start):
    """Sort arr[lo:hi] in-place. arr[lo:start] is already sorted."""
    for i in range(max(start, lo + 1), hi):
        pivot = arr[i]
        left, right = lo, i
        while left < right:
            mid = (left + right) // 2
            if arr[mid] > pivot:
                right = mid
            else:
                left = mid + 1
        for j in range(i, left, -1):
            arr[j] = arr[j - 1]
        arr[left] = pivot


def detect_runs(arr):
    """Detect and prepare sorted runs in the array.
    Returns list of (start, length) tuples covering the entire array.
    Each run region must be sorted ascending after this function returns.
    """
    n = len(arr)
    if n == 0:
        return []
    if n == 1:
        return [(0, 1)]

    runs = []
    i = 0
    while i < n:
        start = i
        if i + 1 >= n:
            run_len = 1
            i += 1
        elif arr[i] > arr[i + 1]:
            # Strictly descending
            while i + 1 < n and arr[i] > arr[i + 1]:
                i += 1
            i += 1
            run_len = i - start
        else:
            # Non-strictly ascending
            while i + 1 < n and arr[i] <= arr[i + 1]:
                i += 1
            i += 1
            run_len = i - start

        if run_len < MIN_RUN:
            force = min(MIN_RUN, n - start)
            binary_insertion_sort(arr, start, start + force, start + run_len)
            run_len = force
            i = start + force

        runs.append((start, run_len))

    return runs


def compute_optimal_merge_cost(run_lengths):
    """Compute minimum-cost merge schedule via C library.
    Returns (cost, merge_tree) where merge_tree is a nested tuple structure.
    """
    n = len(run_lengths)
    if n == 0:
        return (0, None)
    if n == 1:
        return (0, 0)

    lib = _load_lib()

    c_runs = (ctypes.c_int * n)(*run_lengths)
    c_splits = (ctypes.c_int * (n * n))()

    cost = lib.compute_merge_schedule(c_runs, n, c_splits)

    def build_tree(i, j):
        if i == j:
            return i
        k = c_splits[i * n + j]
        return (build_tree(i, k), build_tree(k + 1, j))

    tree = build_tree(0, n - 1)
    return (int(cost), tree)


def merge_runs(arr, lo, mid, hi, aux):
    """Merge sorted runs arr[lo:mid] and arr[mid:hi] using aux buffer."""
    if lo >= mid or mid >= hi:
        return
    if arr[mid - 1] <= arr[mid]:
        return

    left_len = mid - lo
    right_len = hi - mid

    if left_len <= right_len:
        aux[:left_len] = arr[lo:mid]
        ca, cr, dest = 0, mid, lo
        while ca < left_len and cr < hi:
            if aux[ca] < arr[cr]:
                arr[dest] = aux[ca]
                ca += 1
            else:
                arr[dest] = arr[cr]
                cr += 1
            dest += 1
        while ca < left_len:
            arr[dest] = aux[ca]
            ca += 1
            dest += 1
    else:
        aux[:right_len] = arr[mid:hi]
        ca, cl, dest = right_len - 1, mid - 1, hi - 1
        while ca >= 0 and cl >= lo:
            if aux[ca] > arr[cl]:
                arr[dest] = aux[ca]
                ca -= 1
            else:
                arr[dest] = arr[cl]
                cl -= 1
            dest -= 1
        while ca >= 0:
            arr[dest] = aux[ca]
            ca -= 1
            dest -= 1


def _execute_merge_tree(arr, runs, tree, aux):
    """Recursively execute merges described by the merge tree."""
    if isinstance(tree, int):
        return runs[tree]
    left_tree, right_tree = tree
    left_start, left_len = _execute_merge_tree(arr, runs, left_tree, aux)
    right_start, right_len = _execute_merge_tree(arr, runs, right_tree, aux)
    lo = left_start
    mid_pt = left_start + left_len
    hi_pt = right_start + right_len
    merge_runs(arr, lo, mid_pt, hi_pt, aux)
    return (lo, hi_pt - lo)


def adaptive_sort(arr):
    """Sort arr in-place using adaptive merge sort with optimal scheduling."""
    n = len(arr)
    if n <= 1:
        return
    runs = detect_runs(arr)
    if len(runs) <= 1:
        return
    run_lengths = [length for _, length in runs]
    _, tree = compute_optimal_merge_cost(run_lengths)
    aux = [None] * n
    _execute_merge_tree(arr, runs, tree, aux)
