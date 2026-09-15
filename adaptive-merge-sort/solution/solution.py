"""
Complete solution for adaptive merge sort with optimal scheduling.

"""

MIN_RUN = 32
MIN_GALLOP = 7


# ---------------------------------------------------------------------------
# Binary insertion sort
# ---------------------------------------------------------------------------

def binary_insertion_sort(arr, lo, hi, start):
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


# ---------------------------------------------------------------------------
# Run detection
# ---------------------------------------------------------------------------

def detect_runs(arr):
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
            # Strictly descending run
            while i + 1 < n and arr[i] > arr[i + 1]:
                i += 1
            i += 1
            run_len = i - start
            # Reverse in-place
            lo_idx, hi_idx = start, start + run_len - 1
            while lo_idx < hi_idx:
                arr[lo_idx], arr[hi_idx] = arr[hi_idx], arr[lo_idx]
                lo_idx += 1
                hi_idx -= 1
        else:
            # Non-strictly ascending run
            while i + 1 < n and arr[i] <= arr[i + 1]:
                i += 1
            i += 1
            run_len = i - start

        # Extend short runs
        if run_len < MIN_RUN:
            force = min(MIN_RUN, n - start)
            binary_insertion_sort(arr, start, start + force, start + run_len)
            run_len = force
            i = start + force

        runs.append((start, run_len))

    return runs


# ---------------------------------------------------------------------------
# Optimal merge schedule (DP with Knuth optimization)
# ---------------------------------------------------------------------------

def compute_optimal_merge_cost(run_lengths):
    n = len(run_lengths)
    if n == 0:
        return (0, None)
    if n == 1:
        return (0, 0)

    # Prefix sums for O(1) range sum queries
    prefix = [0] * (n + 1)
    for i in range(n):
        prefix[i + 1] = prefix[i] + run_lengths[i]

    INF = float("inf")
    dp = [[0] * n for _ in range(n)]
    opt = [[0] * n for _ in range(n)]

    # Base case: single runs have zero cost
    for i in range(n):
        opt[i][i] = i

    # Fill DP table by increasing chain length
    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            total = prefix[j + 1] - prefix[i]

            # Knuth's optimization: optimal split is monotone
            lo_k = opt[i][j - 1]
            hi_k = opt[i + 1][j] if i + 1 <= j else j - 1
            hi_k = min(hi_k, j - 1)

            best = INF
            best_k = lo_k
            for k in range(lo_k, hi_k + 1):
                cost = dp[i][k] + dp[k + 1][j] + total
                if cost < best:
                    best = cost
                    best_k = k

            dp[i][j] = best
            opt[i][j] = best_k

    # Reconstruct merge tree from split points
    def build_tree(i, j):
        if i == j:
            return i
        k = opt[i][j]
        return (build_tree(i, k), build_tree(k + 1, j))

    return (dp[0][n - 1], build_tree(0, n - 1))


# ---------------------------------------------------------------------------
# Exponential search (galloping)
# ---------------------------------------------------------------------------

def gallop_right(key, arr, lo, hi):
    if lo >= hi:
        return lo

    if key < arr[lo]:
        return lo

    ofs = 1
    last_ofs = 0
    max_ofs = hi - lo

    while ofs < max_ofs and arr[lo + ofs] <= key:
        last_ofs = ofs
        ofs = (ofs << 1) + 1
        if ofs < 0:
            ofs = max_ofs
    ofs = min(ofs, max_ofs)

    left = lo + last_ofs + 1
    right = lo + ofs
    while left < right:
        mid = (left + right) // 2
        if arr[mid] <= key:
            left = mid + 1
        else:
            right = mid
    return left


def gallop_left(key, arr, lo, hi):
    if lo >= hi:
        return lo

    if key <= arr[lo]:
        return lo

    ofs = 1
    last_ofs = 0
    max_ofs = hi - lo

    while ofs < max_ofs and arr[lo + ofs] < key:
        last_ofs = ofs
        ofs = (ofs << 1) + 1
        if ofs < 0:
            ofs = max_ofs
    ofs = min(ofs, max_ofs)

    left = lo + last_ofs + 1
    right = lo + ofs
    while left < right:
        mid = (left + right) // 2
        if arr[mid] < key:
            left = mid + 1
        else:
            right = mid
    return left


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def merge_runs(arr, lo, mid, hi, aux):
    if lo >= mid or mid >= hi:
        return
    if arr[mid - 1] <= arr[mid]:
        return

    left_len = mid - lo
    right_len = hi - mid

    if left_len <= right_len:
        _merge_lo(arr, lo, mid, hi, aux)
    else:
        _merge_hi(arr, lo, mid, hi, aux)


def _merge_lo(arr, lo, mid, hi, aux):
    """Merge when left run is smaller or equal. Copy left to aux."""
    left_len = mid - lo
    aux[:left_len] = arr[lo:mid]

    ca = 0       # cursor into aux (left run copy)
    cr = mid     # cursor into arr (right run, in-place)
    dest = lo

    min_gallop = MIN_GALLOP

    while ca < left_len and cr < hi:
        a_count = 0
        b_count = 0

        # ---- linear merge mode ----
        while ca < left_len and cr < hi:
            if aux[ca] <= arr[cr]:
                arr[dest] = aux[ca]
                ca += 1
                dest += 1
                a_count += 1
                b_count = 0
                if a_count >= min_gallop:
                    break
            else:
                arr[dest] = arr[cr]
                cr += 1
                dest += 1
                b_count += 1
                a_count = 0
                if b_count >= min_gallop:
                    break

        if ca >= left_len or cr >= hi:
            break

        # ---- galloping mode ----
        while ca < left_len and cr < hi:
            # gallop in aux for position of arr[cr]
            k = gallop_right(arr[cr], aux, ca, left_len)
            n_a = k - ca
            if n_a > 0:
                arr[dest:dest + n_a] = aux[ca:k]
                dest += n_a
                ca = k
                if ca >= left_len:
                    break

            arr[dest] = arr[cr]
            dest += 1
            cr += 1
            if cr >= hi:
                break

            # gallop in arr (right run) for position of aux[ca]
            k = gallop_left(aux[ca], arr, cr, hi)
            n_b = k - cr
            if n_b > 0:
                arr[dest:dest + n_b] = arr[cr:k]
                dest += n_b
                cr = k
                if cr >= hi:
                    break

            arr[dest] = aux[ca]
            dest += 1
            ca += 1

            if n_a < MIN_GALLOP and n_b < MIN_GALLOP:
                break

    # flush remaining left-run elements from aux
    if ca < left_len:
        remaining = left_len - ca
        arr[dest:dest + remaining] = aux[ca:ca + remaining]


def _merge_hi(arr, lo, mid, hi, aux):
    """Merge when right run is smaller. Copy right to aux, merge right-to-left."""
    right_len = hi - mid
    aux[:right_len] = arr[mid:hi]

    ca = right_len - 1   # cursor into aux (right run copy), from end
    cl = mid - 1          # cursor into arr (left run), from end
    dest = hi - 1

    while cl >= lo and ca >= 0:
        if aux[ca] >= arr[cl]:
            arr[dest] = aux[ca]
            ca -= 1
        else:
            arr[dest] = arr[cl]
            cl -= 1
        dest -= 1

    # flush remaining right-run elements from aux
    if ca >= 0:
        arr[dest - ca:dest + 1] = aux[0:ca + 1]


# ---------------------------------------------------------------------------
# Merge-tree execution
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def adaptive_sort(arr):
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
