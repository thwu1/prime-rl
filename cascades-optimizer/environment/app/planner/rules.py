"""Transformation and implementation rules for the Volcano optimizer.

Transformation rules rewrite logical plans into equivalent alternatives
(e.g. projection push-down, join reorder).  Implementation rules map a
logical plan node to one or more physical plan builders that produce
concrete PhysicalPlan instances with cost estimates.
"""

from .types import (
    LPScan, LPProject, LPJoin, LPFilter, FieldID,
    Cost, Estimations, PhysicalPlan,
)


# ═══════════════════════════════════════════════════════════════════════════
# Transformation Rules
# ═══════════════════════════════════════════════════════════════════════════

class TransformationRule:
    """Base class for logical → logical transformation rules."""
    def match(self, expression, ctx):
        raise NotImplementedError
    def transform(self, expression, ctx):
        raise NotImplementedError


class ProjectionPushDown(TransformationRule):
    """Push column projections through joins down into scan nodes.

    This reduces the amount of data scanned and carried through the
    plan tree by limiting each table scan to only the columns needed
    by upstream projections and join conditions.
    """

    def _is_scan_join_tree(self, plan):
        """Return True if plan contains only Scan and Join nodes."""
        if isinstance(plan, LPScan):
            return True
        if isinstance(plan, LPJoin):
            return self._is_scan_join_tree(plan.left) and \
                   self._is_scan_join_tree(plan.right)
        return False

    def match(self, expression, ctx):
        plan = expression.plan
        return isinstance(plan, LPProject) and self._is_scan_join_tree(plan.child)

    # ── helpers ──────────────────────────────────────────────────────────
    def _extract_needed_fields(self, plan, buf):
        if isinstance(plan, LPProject):
            buf.extend(plan.fields)
            self._extract_needed_fields(plan.child, buf)
        elif isinstance(plan, LPJoin):
            for lf, rf in plan.on:
                buf.append(lf)
                buf.append(rf)
            self._extract_needed_fields(plan.left, buf)
            self._extract_needed_fields(plan.right, buf)

    def _push_down(self, needed, plan):
        if isinstance(plan, LPScan):
            table_fields = [f.name for f in needed if f.table == plan.table]
            if '*' in table_fields:
                return LPScan(plan.table, [])
            proj = list(dict.fromkeys(plan.projection + table_fields))
            return LPScan(plan.table, proj)
        elif isinstance(plan, LPJoin):
            return LPJoin(
                self._push_down(needed, plan.left),
                self._push_down(needed, plan.right),
                plan.on,
            )
        raise RuntimeError("Unexpected node in _push_down")

    def transform(self, expression, ctx):
        plan = expression.plan  # LPProject
        needed = []
        self._extract_needed_fields(plan, needed)
        unique = list(dict.fromkeys(needed))
        new_plan = LPProject(plan.fields, self._push_down(unique, plan.child))
        return ctx.memo.get_or_create_expression(new_plan)


class JoinReorderBySize(TransformationRule):
    """Reorder a 3-table join tree so that the smallest tables are joined first.

    Matches only when all three tables participate in an interchangeable
    join-condition chain (i.e. A.k = B.k = C.k).
    """

    def _extract(self, plan, scans, conds):
        if isinstance(plan, LPScan):
            scans.append(plan)
            return True
        if isinstance(plan, LPJoin):
            conds.extend(plan.on)
            return self._extract(plan.left, scans, conds) and \
                   self._extract(plan.right, scans, conds)
        return False

    @staticmethod
    def _interchangeable(conditions):
        groups = []
        for lf, rf in conditions:
            target = None
            for g in groups:
                if lf in g or rf in g:
                    target = g
                    break
            if target is None:
                target = set()
                groups.append(target)
            target.add(lf)
            target.add(rf)
        return [list(g) for g in groups]

    def _get_join_cond(self, left, right, interchangeable):
        result = []
        for group in interchangeable:
            lf = [f for f in group if f.table == left.table]
            rf = [f for f in group if f.table == right.table]
            if lf and rf:
                result.extend(zip(lf, rf))
        return result

    def match(self, expression, ctx):
        plan = expression.plan
        if not isinstance(plan, LPJoin):
            return False
        scans, conds = [], []
        if not self._extract(plan, scans, conds):
            return False
        if len(scans) != 3:
            return False
        inter = self._interchangeable(conds)
        return all(len(g) == 3 for g in inter)

    def transform(self, expression, ctx):
        plan = expression.plan
        scans, conds = [], []
        self._extract(plan, scans, conds)
        inter = self._interchangeable(conds)

        # Sort tables to join smallest first.
        # NOTE: sorting by estimated_row_count is INCORRECT — the correct
        # metric is estimated_table_size (row_count * avg_row_size) because
        # it reflects actual data volume, which determines hash-table memory
        # and I/O cost.
        sorted_scans = sorted(
            scans,
            key=lambda s: ctx.stats_provider(s.table.name).estimated_row_count,
        )

        inner_cond = self._get_join_cond(sorted_scans[1], sorted_scans[2], inter)
        outer_cond = self._get_join_cond(sorted_scans[0], sorted_scans[1], inter)

        new_plan = LPJoin(
            sorted_scans[0],
            LPJoin(sorted_scans[1], sorted_scans[2], inner_cond),
            outer_cond,
        )
        return ctx.memo.get_or_create_expression(new_plan)


class FilterPushDown(TransformationRule):
    """Push filter predicates below joins when possible.

    When a Filter sits directly above a Join and all of its conditions
    reference columns from only ONE side of the join, the Filter can be
    pushed below the Join so it runs against fewer rows.
    """

    def match(self, expression, ctx):
        plan = expression.plan
        return isinstance(plan, LPFilter) and isinstance(plan.child, LPJoin)

    def transform(self, expression, ctx):
        """Push the filter below the join.

        Given:  Filter(conditions, Join(left, right, on))
        If all condition columns come from left's tables →
                Join(Filter(conditions, left), right, on)
        If all condition columns come from right's tables →
                Join(left, Filter(conditions, right), on)
        Otherwise the filter cannot be pushed — return the original.
        """
        raise NotImplementedError("FilterPushDown.transform not yet implemented")


# Transformation rule batches, applied in order during exploration.
TRANSFORMATION_RULE_BATCHES = [
    [ProjectionPushDown()],
    [JoinReorderBySize()],
    [FilterPushDown()],
]


# ═══════════════════════════════════════════════════════════════════════════
# Implementation / Physical Plan Builders
# ═══════════════════════════════════════════════════════════════════════════

class PhysicalPlanBuilder:
    """Base class for physical-plan builders."""
    def build(self, children):
        """Return a PhysicalPlan or None if this builder is inapplicable."""
        raise NotImplementedError


class ScanBuilder(PhysicalPlanBuilder):
    """Build a physical sequential-scan plan."""
    def __init__(self, table_name, catalog, stats, projection):
        self.table_name = table_name
        self.catalog = catalog
        self.stats = stats
        self.projection = projection

    def build(self, children):
        full = not self.projection or self.projection == ['*']
        if full:
            cpu_mod = mem_mod = 1.0
        else:
            cpu_mod = len(self.projection) / max(len(self.stats.avg_column_sizes), 1)
            proj_sz = sum(self.stats.avg_column_sizes.get(c, 0) for c in self.projection)
            mem_mod = proj_sz / self.stats.avg_row_size if self.stats.avg_row_size else 1.0

        cost = Cost(
            cpu=cpu_mod * self.stats.estimated_row_count,
            memory=mem_mod * self.stats.avg_row_size,
            time=float(self.stats.estimated_row_count),
        )
        est = Estimations(
            loop_iterations=self.stats.estimated_row_count,
            row_size=self.stats.avg_row_size,
        )
        traits = set()
        if self.catalog.metadata.get('sorted') == 'true':
            traits.add('SORTED')
        return PhysicalPlan(f"SCAN({self.table_name})", cost, est, traits)


class ProjectionBuilder(PhysicalPlanBuilder):
    """Build a physical projection plan (pass-through with field selection)."""
    def __init__(self, fields):
        self.fields = fields

    def build(self, children):
        child = children[0]
        # Projection has negligible self-cost; just propagate child cost.
        cost = Cost(cpu=child.cost().cpu, memory=child.cost().memory,
                    time=child.cost().time)
        est = Estimations(
            loop_iterations=child.estimations().loop_iterations,
            row_size=child.estimations().row_size,
        )
        return PhysicalPlan("PROJECT", cost, est, child.traits(), [child])


class HashJoinBuilder(PhysicalPlanBuilder):
    """Build a hash-join physical plan.

    A hash join works by building a hash table on the *build* side
    (the smaller input) and probing it with each row of the *probe*
    side (the larger input).  Memory cost is dominated by the hash
    table, so it should equal the view-size of the build side.
    """
    def __init__(self, left_fields, right_fields):
        self.left_fields = left_fields
        self.right_fields = right_fields

    @staticmethod
    def _view_size(plan):
        return plan.estimations().loop_iterations * plan.estimations().row_size

    def build(self, children):
        # Use children in the order they arrive — no reordering.
        left_child, right_child = children[0], children[1]

        est_loop = max(left_child.estimations().loop_iterations,
                       right_child.estimations().loop_iterations)
        est_row = left_child.estimations().row_size + right_child.estimations().row_size

        # Self-cost of the hash join operation.
        cpu_cost = left_child.estimations().loop_iterations
        memory_cost = self._view_size(right_child)  # hash-table memory
        time_cost = right_child.estimations().loop_iterations

        total_cpu = cpu_cost + left_child.cost().cpu + right_child.cost().cpu
        total_mem = memory_cost + left_child.cost().memory + right_child.cost().memory
        total_time = time_cost + left_child.cost().time + right_child.cost().time

        cost = Cost(cpu=total_cpu, memory=total_mem, time=total_time)
        est = Estimations(loop_iterations=est_loop, row_size=est_row)
        return PhysicalPlan("HASH_JOIN", cost, est, set(), [left_child, right_child])


class MergeJoinBuilder(PhysicalPlanBuilder):
    """Build a merge-join physical plan.  Requires SORTED inputs."""
    def __init__(self, left_fields, right_fields):
        self.left_fields = left_fields
        self.right_fields = right_fields

    def build(self, children):
        left, right = children[0], children[1]
        if 'SORTED' not in left.traits() or 'SORTED' not in right.traits():
            return None  # merge join requires sorted inputs

        total_rows = (left.estimations().loop_iterations
                      + right.estimations().loop_iterations)
        est_loop = max(left.estimations().loop_iterations,
                       right.estimations().loop_iterations)
        est_row = left.estimations().row_size + right.estimations().row_size

        total_cpu = left.cost().cpu + right.cost().cpu
        total_mem = left.cost().memory + right.cost().memory
        total_time = total_rows + left.cost().time + right.cost().time

        cost = Cost(cpu=total_cpu, memory=total_mem, time=total_time)
        est = Estimations(loop_iterations=est_loop, row_size=est_row)
        traits = left.traits() | right.traits()
        return PhysicalPlan("MERGE_JOIN", cost, est, traits, [left, right])


class FilterBuilder(PhysicalPlanBuilder):
    """Build a physical filter plan with a fixed selectivity estimate."""
    SELECTIVITY = 0.3

    def __init__(self, conditions):
        self.conditions = conditions

    def build(self, children):
        child = children[0]
        filtered = max(1, int(child.estimations().loop_iterations * self.SELECTIVITY))
        cost = Cost(
            cpu=child.cost().cpu + child.estimations().loop_iterations,
            memory=child.cost().memory,
            time=child.cost().time,
        )
        est = Estimations(loop_iterations=filtered, row_size=child.estimations().row_size)
        return PhysicalPlan("FILTER", cost, est, child.traits(), [child])


# ─── Dispatcher ──────────────────────────────────────────────────────────────

def get_physical_plan_builders(expression, ctx):
    """Return applicable PhysicalPlanBuilders for a GroupExpression."""
    plan = expression.plan

    if isinstance(plan, LPScan):
        name = plan.table.name
        return [ScanBuilder(name,
                            ctx.catalog_provider(name),
                            ctx.stats_provider(name),
                            plan.projection)]

    if isinstance(plan, LPProject):
        return [ProjectionBuilder(plan.fields)]

    if isinstance(plan, LPJoin):
        lf = [f"{l.table.name}.{l.name}" for l, _ in plan.on]
        rf = [f"{r.table.name}.{r.name}" for _, r in plan.on]
        return [HashJoinBuilder(lf, rf), MergeJoinBuilder(lf, rf)]

    if isinstance(plan, LPFilter):
        return [FilterBuilder(plan.conditions)]

    return []
