#!/usr/bin/env python3
"""Fix the PBT library's shrinking engine.

Applies three fixes:
1. bin_search_down: Add missing boundary check for f(lo).
2. Block zeroing: Implement the block zeroing pass.
3. Range sorting: Implement the range sorting pass.
4. Pair redistribution: Implement the pair redistribution pass.

"""

with open('/app/pbt.py', 'r') as f:
    source = f.read()

# ── Fix 1: bin_search_down ──────────────────────────────────────────
# The function's docstring says "Will return lo if f(lo) is True" but
# the implementation is missing this check, causing it to return lo+1
# instead of lo when f(lo) is True.

old_bsd = """\
    while lo + 1 < hi:
        mid = lo + (hi - lo) // 2
        if f(mid):
            hi = mid
        else:
            lo = mid
    return hi"""

new_bsd = """\
    if f(lo):
        return lo
    while lo + 1 < hi:
        mid = lo + (hi - lo) // 2
        if f(mid):
            hi = mid
        else:
            lo = mid
    return hi"""

source = source.replace(old_bsd, new_bsd)

# ── Fix 2: Block zeroing ───────────────────────────────────────────
old_block = """\
            # Pass 2: Block zeroing
            # Try replacing contiguous blocks of k choices with 0,
            # for k from 8 down to 2 (k=1 handled by pass 3).
            # TODO: Implement block zeroing."""

new_block = """\
            # Pass 2: Block zeroing
            k = 8
            while k > 1:
                i = len(self.result) - k
                while i >= 0:
                    if replace({j: 0 for j in range(i, i + k)}):
                        i -= k
                    else:
                        i -= 1
                k -= 1"""

source = source.replace(old_block, new_block)

# ── Fix 3: Range sorting ───────────────────────────────────────────
old_sort = """\
            # Pass 4: Range sorting
            # Try sorting sub-ranges of the choice sequence. Since
            # sorted(x) <= x in shortlex order, this is always a
            # valid reduction.
            # TODO: Implement range sorting."""

new_sort = """\
            # Pass 4: Range sorting
            k = 8
            while k > 1:
                for i in range(len(self.result) - k - 1, -1, -1):
                    consider(
                        self.result[:i]
                        + array("Q", sorted(self.result[i : i + k]))
                        + self.result[i + k :]
                    )
                k -= 1"""

source = source.replace(old_sort, new_sort)

# ── Fix 4: Pair redistribution ─────────────────────────────────────
old_redist = """\
            # Pass 5: Pair redistribution
            # Try redistributing values between nearby pairs of choices
            # to minimize earlier values. This handles properties that
            # depend on sums of generated values.
            # TODO: Implement pair redistribution."""

new_redist = """\
            # Pass 5: Pair redistribution
            for k in [2, 1]:
                for i in range(len(self.result) - 1 - k, -1, -1):
                    j = i + k
                    if j < len(self.result):
                        if self.result[i] > self.result[j]:
                            replace({j: self.result[i], i: self.result[j]})
                        if j < len(self.result) and self.result[i] > 0:
                            previous_i = self.result[i]
                            previous_j = self.result[j]
                            bin_search_down(
                                0,
                                previous_i,
                                lambda v: replace(
                                    {i: v, j: previous_j + (previous_i - v)}
                                ),
                            )"""

source = source.replace(old_redist, new_redist)

with open('/app/pbt.py', 'w') as f:
    f.write(source)

print("All fixes applied to /app/pbt.py")
