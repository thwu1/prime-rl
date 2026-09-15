"""Reference layout solver implementation (split + compose)."""
from typing import List, Tuple, Dict
from layout_solver.types import (
    Rect, Constraint, Direction, Flex,
    Length, Percentage, Ratio, Fill, Min, Max,
    Leaf, Container, LayoutNode,
)


def split(
    area: Rect,
    constraints: List[Constraint],
    direction: Direction = Direction.HORIZONTAL,
    spacing: int = 0,
    flex: Flex = Flex.START,
) -> List[Rect]:
    n = len(constraints)
    if n == 0:
        return []

    if direction == Direction.HORIZONTAL:
        total_space = area.width
    else:
        total_space = area.height

    usable = total_space - max(0, n - 1) * spacing
    usable = max(0, usable)

    sizes = _solve_sizes(usable, constraints)

    total_used = sum(sizes)
    leftover = max(0, usable - total_used)

    pos = _compute_positions(sizes, leftover, spacing, flex, n)

    rects = []
    for i in range(n):
        if direction == Direction.HORIZONTAL:
            rects.append(Rect(area.x + pos[i], area.y, sizes[i], area.height))
        else:
            rects.append(Rect(area.x, area.y + pos[i], area.width, sizes[i]))

    return rects


def compose(area: Rect, node: LayoutNode) -> Dict[str, Rect]:
    if isinstance(node, Leaf):
        return {node.name: area}

    n = len(node.children)
    if n == 0:
        return {}

    direction = node.direction
    flex = node.flex

    constraints = list(node.constraints)

    for i, child in enumerate(node.children):
        sizing = getattr(child, 'sizing', 'fixed')
        if sizing == 'auto':
            if direction == Direction.HORIZONTAL:
                intrinsic = _compute_intrinsic_width(child)
            else:
                intrinsic = _compute_intrinsic_height(child)
            if intrinsic > 0:
                constraints[i] = Min(intrinsic, constraints[i])

    sub_rects = split(area, constraints, direction, node.spacing, flex)

    result = {}
    for i, child in enumerate(node.children):
        if i < len(sub_rects):
            child_result = compose(sub_rects[i], child)
            result.update(child_result)

    return result


def _constraint_min_contribution(c: Constraint) -> int:
    """The minimum size a constraint can resolve to, regardless of available space."""
    if isinstance(c, Length):
        return c.value
    elif isinstance(c, Percentage):
        return 0
    elif isinstance(c, Ratio):
        return 0
    elif isinstance(c, Fill):
        return 0
    elif isinstance(c, Min):
        return max(c.value, _constraint_min_contribution(c.inner))
    elif isinstance(c, Max):
        return min(c.value, _constraint_min_contribution(c.inner))
    return 0


def _compute_intrinsic_width(node: LayoutNode) -> int:
    if isinstance(node, Leaf):
        return node.intrinsic_width

    n = len(node.children)
    if n == 0:
        return 0

    if node.direction == Direction.HORIZONTAL:
        total = 0
        for i, child in enumerate(node.children):
            child_intr = _compute_intrinsic_width(child)
            cons_min = _constraint_min_contribution(node.constraints[i]) if i < len(node.constraints) else 0
            total += max(child_intr, cons_min)
        if n > 1:
            total += (n - 1) * node.spacing
        return total
    else:
        return max((_compute_intrinsic_width(c) for c in node.children), default=0)


def _compute_intrinsic_height(node: LayoutNode) -> int:
    if isinstance(node, Leaf):
        return node.intrinsic_height

    n = len(node.children)
    if n == 0:
        return 0

    if node.direction == Direction.VERTICAL:
        total = 0
        for i, child in enumerate(node.children):
            child_intr = _compute_intrinsic_height(child)
            cons_min = _constraint_min_contribution(node.constraints[i]) if i < len(node.constraints) else 0
            total += max(child_intr, cons_min)
        if n > 1:
            total += (n - 1) * node.spacing
        return total
    else:
        return max((_compute_intrinsic_height(c) for c in node.children), default=0)


# ---- internal helpers for split ----

def _unwrap_bounds(
    constraint: Constraint, usable: int
) -> Tuple[int, int, Constraint]:
    min_bound = 0
    max_bound = usable
    c = constraint
    while isinstance(c, (Min, Max)):
        if isinstance(c, Min):
            min_bound = max(min_bound, c.value)
            c = c.inner
        else:
            max_bound = min(max_bound, c.value)
            c = c.inner
    if min_bound > max_bound:
        max_bound = min_bound
    return min_bound, max_bound, c


def _resolve_base(constraint: Constraint, usable: int) -> int:
    if isinstance(constraint, Length):
        return constraint.value
    elif isinstance(constraint, Percentage):
        return usable * constraint.value // 100
    elif isinstance(constraint, Ratio):
        if constraint.denominator == 0:
            return 0
        return usable * constraint.numerator // constraint.denominator
    return 0


def _largest_remainder_distribute(total: int, weights: List[int]) -> List[int]:
    k = len(weights)
    if k == 0:
        return []
    total_weight = sum(weights)
    if total_weight == 0:
        each = total // k
        lefto = total - each * k
        return [each + (1 if i < lefto else 0) for i in range(k)]

    exact = [total * w / total_weight for w in weights]
    floored = [int(e) for e in exact]
    remainders = [(exact[i] - floored[i], i) for i in range(k)]
    deficit = total - sum(floored)

    remainders.sort(key=lambda x: (-x[0], x[1]))
    bonus = set()
    for j in range(deficit):
        if j < len(remainders):
            bonus.add(remainders[j][1])

    return [floored[i] + (1 if i in bonus else 0) for i in range(k)]


def _solve_sizes(usable: int, constraints: List[Constraint]) -> List[int]:
    n = len(constraints)
    sizes = [0] * n
    min_bounds = [0] * n
    max_bounds = [usable] * n
    is_fill = [False] * n
    fill_weights = [0] * n

    for i, c in enumerate(constraints):
        mn, mx, base = _unwrap_bounds(c, usable)
        min_bounds[i] = mn
        max_bounds[i] = mx
        if isinstance(base, Fill):
            is_fill[i] = True
            fill_weights[i] = max(0, base.weight)
        else:
            raw = _resolve_base(base, usable)
            sizes[i] = max(mn, min(mx, raw))

    resolved = [not is_fill[i] for i in range(n)]

    for _ in range(n + 5):
        used_by_resolved = sum(sizes[i] for i in range(n) if resolved[i])
        remaining = max(0, usable - used_by_resolved)

        unresolved = [i for i in range(n) if not resolved[i]]
        if not unresolved:
            break

        weights = [fill_weights[i] for i in unresolved]
        alloc = _largest_remainder_distribute(remaining, weights)

        for j, i in enumerate(unresolved):
            sizes[i] = alloc[j]

        changed = False
        for i in unresolved:
            clamped = max(min_bounds[i], min(max_bounds[i], sizes[i]))
            if clamped != sizes[i]:
                sizes[i] = clamped
                resolved[i] = True
                changed = True

        if not changed:
            break

    total = sum(sizes)
    if total > usable and total > 0:
        alloc = _largest_remainder_distribute(usable, sizes)
        sizes = [max(0, a) for a in alloc]

    sizes = [max(0, s) for s in sizes]

    return sizes


def _compute_positions(
    sizes: List[int],
    leftover: int,
    spacing: int,
    flex: Flex,
    n: int,
) -> List[int]:
    if n == 0:
        return []

    positions = [0] * n

    if flex == Flex.START or leftover <= 0:
        pos = 0
        for i in range(n):
            positions[i] = pos
            pos += sizes[i] + (spacing if i < n - 1 else 0)

    elif flex == Flex.END:
        pos = leftover
        for i in range(n):
            positions[i] = pos
            pos += sizes[i] + (spacing if i < n - 1 else 0)

    elif flex == Flex.CENTER:
        pos = leftover // 2
        for i in range(n):
            positions[i] = pos
            pos += sizes[i] + (spacing if i < n - 1 else 0)

    elif flex == Flex.SPACE_BETWEEN:
        if n == 1:
            positions[0] = 0
        else:
            gap_each = leftover // (n - 1)
            gap_extra = leftover % (n - 1)
            pos = 0
            for i in range(n):
                positions[i] = pos
                if i < n - 1:
                    extra = 1 if i < gap_extra else 0
                    pos += sizes[i] + spacing + gap_each + extra

    return positions
