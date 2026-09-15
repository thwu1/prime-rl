
import os
import bisect


def _compute_reference():
    """Compute reference answers using binary-search-optimized algorithm."""
    with open('/app/input.txt') as f:
        parts = f.readline().split()
        n, m, k = int(parts[0]), int(parts[1]), int(parts[2])
        a = list(map(int, f.readline().split()))

    present = set(a)
    num_w = n - k + 1

    # Precompute sorted windows with sums
    window_data = []
    for i in range(num_w):
        w = a[i:i + k]
        s = sum(w)
        sw = sorted(w)
        window_data.append((sw, s, sw[0], sw[-1]))

    results = []
    for x in range(1, m + 1):
        if x in present:
            results.append(0.0)
            continue

        best = float('inf')
        for sw, s, wmin, wmax in window_data:
            if x < wmin or x > wmax:
                continue

            mu = s / k

            # Exact rational check: x == mu iff k*x == s
            if k * x == s:
                if 1.0 < best:
                    best = 1.0
                continue

            if x > mu:
                # Find smallest element strictly greater than x
                idx = bisect.bisect_right(sw, x)
                if idx < k:
                    aj = sw[idx]
                    t = (aj - x) / (aj - mu)
                    if t < best:
                        best = t
            else:
                # Find largest element strictly less than x
                idx = bisect.bisect_left(sw, x) - 1
                if idx >= 0:
                    aj = sw[idx]
                    t = (x - aj) / (mu - aj)
                    if t < best:
                        best = t

        if best == float('inf'):
            results.append(None)
        else:
            results.append(best)

    return results, m


def _brute_force_single(a, n, k, x):
    """Brute-force reference for a single target (used for cross-validation)."""
    best = float('inf')
    for i in range(n - k + 1):
        w = a[i:i + k]
        s = sum(w)
        mu = s / k
        lo, hi = min(w), max(w)
        if x < lo or x > hi:
            continue
        for aj in w:
            d = mu - aj
            if abs(d) < 1e-15:
                continue
            t = (x - aj) / d
            if 0 < t <= 1.0 + 1e-12:
                t = min(1.0, max(0.0, t))
                if t < best:
                    best = t
    return best if best < float('inf') else None


def test_output_exists():
    """Output file must exist."""
    assert os.path.isfile('/app/output.txt'), "/app/output.txt not found"


def test_output_line_count():
    """Output must have exactly m lines."""
    with open('/app/input.txt') as f:
        parts = f.readline().split()
        m = int(parts[1])
    with open('/app/output.txt') as f:
        lines = f.read().strip().split('\n')
    assert len(lines) == m, f"Expected {m} lines, got {len(lines)}"


def test_output_correct():
    """All m target values must match the reference within tolerance."""
    ref, m = _compute_reference()

    with open('/app/output.txt') as f:
        lines = f.read().strip().split('\n')

    assert len(lines) == m, f"Expected {m} lines, got {len(lines)}"

    tol = 1e-8
    errors = []
    for i in range(m):
        r = ref[i]
        line = lines[i].strip()
        target = i + 1

        if r is None:
            if line != '-1':
                errors.append(f"Target {target}: expected -1, got '{line}'")
        elif r == 0.0:
            try:
                v = float(line)
            except ValueError:
                errors.append(f"Target {target}: expected 0, got non-numeric '{line}'")
                continue
            if abs(v) > tol:
                errors.append(f"Target {target}: expected 0, got {v}")
        else:
            try:
                v = float(line)
            except ValueError:
                errors.append(f"Target {target}: expected {r:.12f}, got non-numeric '{line}'")
                continue
            if abs(v - r) > tol:
                errors.append(f"Target {target}: expected {r:.12f}, got {v}")

    if errors:
        msg = f"{len(errors)} targets incorrect out of {m}. First errors:\n"
        msg += '\n'.join(errors[:20])
        assert False, msg


def test_cross_validate_subset():
    """Cross-validate binary-search reference against brute-force on a small subset."""
    with open('/app/input.txt') as f:
        parts = f.readline().split()
        n, m, k = int(parts[0]), int(parts[1]), int(parts[2])
        a = list(map(int, f.readline().split()))

    present = set(a)
    ref, _ = _compute_reference()

    # Check 20 evenly-spaced non-trivial targets
    step = max(1, m // 20)
    check_targets = [x for x in range(1, m + 1, step) if x not in present][:20]

    for x in check_targets:
        bf = _brute_force_single(a, n, k, x)
        bs = ref[x - 1]
        if bf is None and bs is None:
            continue
        if bf is None or bs is None:
            assert False, f"Target {x}: brute-force={bf}, binary-search={bs} (mismatch)"
        assert abs(bf - bs) < 1e-10, \
            f"Target {x}: brute-force={bf:.15f}, binary-search={bs:.15f}"
