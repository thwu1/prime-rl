# Layout Engine — Behavioral Reference

## Purpose

This layout engine provides two core operations for terminal UI frameworks:

1. **`split()`** — Partitions a rectangular terminal area into a sequence of
   non-overlapping sub-rectangles according to an ordered list of constraints.
2. **`compose()`** — Resolves a hierarchical layout tree into a flat mapping of
   named leaf regions to their computed rectangles.

Together, these operations enable building complex terminal dashboards with
nested panels, sidebars, headers, and content areas.

---

## Part 1: The `split()` Function

### Constraint Types

| Type | Meaning |
|------|---------|
| `Length(n)` | Exactly `n` cells. |
| `Percentage(p)` | A percentage of the total available space. |
| `Ratio(n, d)` | A fraction `n/d` of the total available space. |
| `Fill(w)` | Proportional share of space remaining after fixed-size allocations. Weight `w` determines relative share among sibling Fill constraints. |
| `Min(v, inner)` | Resolves `inner`, then ensures the result is at least `v`. |
| `Max(v, inner)` | Resolves `inner`, then ensures the result is at most `v`. |

`Min` and `Max` can be nested arbitrarily (e.g., `Min(10, Max(40, Fill(1)))`).
When `min > max`, `min` takes precedence: the effective maximum is raised to
equal the minimum.

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `area` | (required) | The `Rect` to partition. |
| `constraints` | (required) | Ordered list of constraints. |
| `direction` | `HORIZONTAL` | Axis along which to split: HORIZONTAL varies x/width, VERTICAL varies y/height. |
| `spacing` | `0` | Gap in cells between adjacent elements. |
| `flex` | `START` | How to distribute leftover space (see below). |

### Flex Modes

| Mode | Behavior |
|------|----------|
| `START` | Elements packed at the beginning of the area. |
| `END` | Elements packed at the end. |
| `CENTER` | Elements centered within the area. |
| `SPACE_BETWEEN` | Leftover space distributed evenly between elements. With one element, behaves like START. |

### Behavioral Invariants

1. Returns exactly one `Rect` per constraint.
2. Rects are laid out sequentially (non-overlapping) along the specified direction.
3. All sizes are non-negative integers.
4. The sum of element sizes equals the usable space when constraints can be fully satisfied.
5. Usable space = dimension along the split axis minus total spacing between elements.
6. The cross-axis dimension and position are inherited from the input area.
7. Fill weights distribute space fairly — each Fill receives a share proportional
   to its weight relative to total Fill weight.
8. Integer rounding preserves the exact total.
9. When total constraint sizes exceed available space, sizes are reduced to fit.
10. Min/Max bounds interact with Fill constraint distribution.

---

## Part 2: The `compose()` Function

### Tree Structure

The layout tree consists of two node types:

**Leaf** — A terminal node representing a named region.
- `name`: string identifier for the region
- `intrinsic_width`: the leaf's declared intrinsic width (default 0)
- `intrinsic_height`: the leaf's declared intrinsic height (default 0)
- `sizing`: `"fixed"` (default) or `"auto"`

**Container** — An internal node that splits its area among children.
- `direction`: `HORIZONTAL` or `VERTICAL`
- `constraints`: one constraint per child (same types as `split()`)
- `children`: ordered list of child nodes (Leaf or Container)
- `spacing`: gap between children (default 0)
- `flex`: leftover space distribution (default `START`)
- `sizing`: `"fixed"` (default) or `"auto"`

### Basic Behavior

`compose(area, node)` recursively processes the tree:
- For a **Leaf**, returns `{name: area}` — the leaf occupies its entire allocated rectangle.
- For a **Container**, uses `split()` to partition the area according to the
  container's direction, constraints, spacing, and flex. Then recursively
  composes each child within its allocated sub-rectangle.

The result is a flat dictionary mapping every leaf name to its computed `Rect`.

### Auto-Sizing

When a child node has `sizing="auto"`, the parent container takes the child's
**intrinsic size** into account during constraint resolution. This creates a
content-aware layout where regions expand to accommodate their content.

Intrinsic size computation:
- For a **Leaf**: the declared `intrinsic_width` or `intrinsic_height` (depending on the parent's split direction).
- For a **Container**: computed recursively from the container's children and spacing.

The precise algorithm for how intrinsic sizes propagate through the tree and
influence parent constraint resolution is not fully specified here. Use the
oracle and reference cases to determine the exact behavior.

### Behavioral Invariants for `compose()`

1. Every leaf in the tree appears exactly once in the output dictionary.
2. Leaf rectangles are determined by recursive application of `split()`.
3. Auto-sizing only affects the main-axis dimension of the parent's split.
4. Auto-sizing with `intrinsic=0` has no effect (behaves like `"fixed"`).
5. The cross-axis dimension is always inherited from the parent.
6. Nested auto-sizing propagates through the tree.
