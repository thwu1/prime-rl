"""
Shrinking strategies for property-based testing.
Port of the Rust quickcheck crate's shrinking logic.
"""


def shrink_int(x):
    """Shrink a signed integer toward 0."""
    if x == 0:
        return
    i = x // 2
    yield 0
    if i < 0:
        yield abs(x)
    while i != 0:
        yield x - i
        i = i // 2


def shrink_nonneg(x):
    """Shrink a non-negative integer toward 0."""
    if x == 0:
        return
    yield 0
    i = x // 2
    while i > 0:
        yield x - i
        i //= 2


def shrink_bool(x):
    """Shrink a boolean. True -> [False], False -> []."""
    if x:
        yield False


def shrink_list(xs, element_shrinker):
    """Shrink a list by removing chunks and shrinking elements."""
    if not xs:
        return

    seed = list(xs)
    n = len(seed)

    # Create first element's shrinker eagerly
    elem_iter = iter(element_shrinker(seed[0]))
    _sentinel = object()

    # Phase 0: yield empty list
    yield []

    # Phase 1: chunk removal
    size = n // 2
    offset = size
    while size > 0:
        yield seed[:offset - size] + seed[offset:]
        offset += size
        if offset >= n:
            size //= 2
            offset = size

    # Phase 2: element shrinking
    pos = 1

    def next_shrunk():
        nonlocal elem_iter, pos
        while True:
            val = next(elem_iter, _sentinel)
            if val is not _sentinel:
                return val
            if pos >= n:
                return _sentinel
            elem_iter = iter(element_shrinker(seed[pos]))
            pos += 1

    while True:
        e = next_shrunk()
        if e is _sentinel:
            return
        yield seed[:pos - 1] + [e] + seed[pos:]


def shrink_tuple(t, component_shrinkers):
    """Shrink a tuple by trying each component's shrinker in order."""
    for i, shrinker in enumerate(component_shrinkers):
        for shrunk_val in shrinker(t[i]):
            result = list(t)
            result[i] = shrunk_val
            yield tuple(result)
