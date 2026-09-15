# Layout Constraint Solver — Specification

## Overview

The `split()` function partitions a rectangular terminal area into a sequence of
non-overlapping sub-rectangles according to an ordered list of **constraints**.
This is the core layout primitive in TUI frameworks: every widget placement,
panel split, and dashboard grid ultimately reduces to solving constraints over
one-dimensional intervals and mapping the results back to 2D rectangles.

## Constraint Types

| Type | Meaning |
|------|---------|
| `Length(n)` | Exactly `n` cells (fixed). |
| `Percentage(p)` | `floor(usable * p / 100)` cells. |
| `Ratio(n, d)` | `floor(usable * n / d)` cells. |
| `Fill(w)` | Proportional share of **remaining** space (after fixed, percentage, and ratio allocations). Weight `w` determines relative share among sibling Fills. |
| `Min(v, inner)` | Resolve `inner` first, then ensure the result is at least `v`. |
| `Max(v, inner)` | Resolve `inner` first, then ensure the result is at most `v`. |

`Min` and `Max` can be nested arbitrarily (e.g., `Min(10, Max(40, Fill(1)))`).

When `Min` and `Max` conflict (min > max), `Min` takes precedence: the effective
maximum is raised to equal the minimum.

## Algorithm

### Step 0 — Usable Space

```
n = len(constraints)
if direction == HORIZONTAL:
    usable = area.width - max(0, n - 1) * spacing
else:
    usable = area.height - max(0, n - 1) * spacing
usable = max(0, usable)
```

### Step 1 — Classify and Extract Bounds

For each constraint, peel off `Min`/`Max` wrappers to find the **base**
constraint and the cumulative bounds:

- Walk inward through `Min`/`Max` layers, accumulating `min_bound` (maximum of
  all `Min.value`) and `max_bound` (minimum of all `Max.value`).
- If `min_bound > max_bound`, set `max_bound = min_bound`.
- The innermost non-Min/Max constraint is the **base**.
- If the base is `Fill`, mark the element as **flexible**; otherwise **fixed**.

### Step 2 — Resolve Fixed Elements

For each fixed element, compute its initial size from the base constraint:

- `Length(n)` → `n`
- `Percentage(p)` → `floor(usable * p / 100)`
- `Ratio(n, d)` → `floor(usable * n / d)`

Then clamp to `[min_bound, max_bound]`.

Mark fixed elements as **resolved** (they will not participate in fill
redistribution).

### Step 3 — Iterative Fill Distribution

Repeat until stable (or a maximum of `n + 5` iterations):

1. **Remaining space**: `remaining = usable - sum(sizes of resolved elements)`.
   Clamp to 0 if negative.
2. **Unresolved fills**: the flexible elements not yet resolved.
3. **Distribute** `remaining` among unresolved fills proportionally by weight
   using the **largest-remainder method** (see Rounding below).
4. **Clamp** each newly computed fill size to its `[min_bound, max_bound]`.
   If clamping changes a size, mark that element as resolved (it exits the
   fill pool).
5. If no element was clamped in this iteration, the distribution is stable —
   stop.

### Step 4 — Over-constrained Handling

If `sum(sizes) > usable`, scale all sizes proportionally:

```
for each element i:
    new_size[i] = floor(usable * sizes[i] / total)
```

Distribute the rounding deficit using the largest-remainder method.

### Step 5 — Flex Distribution

If `sum(sizes) < usable`, there is leftover space. Distribute it based on `flex`:

| Flex | Behavior |
|------|----------|
| `START` | All leftover appears after the last element (default; elements are packed at the start). |
| `END` | All leftover appears before the first element. |
| `CENTER` | `floor(leftover / 2)` before the first element. |
| `SPACE_BETWEEN` | Leftover is divided equally among the `n - 1` gaps between elements. Remainder cells are distributed to the first gaps. With 1 element, behaves like `START`. |

### Step 6 — Position Calculation

Convert sizes to `Rect` objects. For `HORIZONTAL` direction, elements are laid
out left-to-right starting at `area.x`; their `y`, `height` come from `area`.
For `VERTICAL`, top-to-bottom starting at `area.y`; `x`, `width` come from
`area`. Spacing is added between adjacent elements. Flex offsets shift the
starting position as described above.

## Rounding: Largest-Remainder Method

When distributing `total` units among `k` recipients with weights `w_i`:

1. Compute exact share: `s_i = total * w_i / sum(w)`.
2. Take floor: `f_i = floor(s_i)`.
3. Compute remainder: `r_i = s_i - f_i`.
4. Deficit `= total - sum(f_i)`.
5. Sort recipients by `r_i` descending, breaking ties by **ascending index**.
6. Give `+1` to the top `deficit` recipients.

This ensures the sum is exactly `total` and the allocation is as fair as
possible.
