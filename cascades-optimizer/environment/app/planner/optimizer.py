"""Volcano/Cascades query optimizer.

Implements the three-phase optimization pipeline:
    1. Initialize — convert logical plan into the memo structure.
    2. Explore   — apply transformation rules to enumerate equivalent plans.
    3. Implement — select the cheapest physical plan for every memo group.
"""

from .memo import Memo, GroupImplementation
from .cost import CostModel
from .rules import TRANSFORMATION_RULE_BATCHES, get_physical_plan_builders


class OptimizerContext:
    """Shared context passed through every phase of optimisation."""
    def __init__(self, catalog_provider, stats_provider, cost_model=None):
        self.catalog_provider = catalog_provider   # str -> TableCatalog
        self.stats_provider = stats_provider       # str -> TableStats
        self.cost_model = cost_model or CostModel()
        self.memo = Memo()
        self.root_group = None


class VolcanoOptimizer:
    """Cost-based query optimizer following the Volcano/Cascades framework."""

    def optimize(self, logical_plan, ctx):
        """Run the full pipeline and return the best PhysicalPlan."""
        self._initialize(logical_plan, ctx)
        self._explore(ctx)
        self._implement(ctx)
        if ctx.root_group.implementation is None:
            raise RuntimeError("No implementation found")
        return ctx.root_group.implementation.physical_plan

    # ── Phase 1: Initialize ─────────────────────────────────────────────
    def _initialize(self, plan, ctx):
        ctx.root_group = ctx.memo.get_or_create_group(plan)
        for g in ctx.memo.groups.values():
            g.exploration_mark.mark_explored(0)
        for e in ctx.memo.expressions.values():
            e.exploration_mark.mark_explored(0)

    # ── Phase 2: Explore ────────────────────────────────────────────────
    def _explore(self, ctx):
        for rnd, batch in enumerate(TRANSFORMATION_RULE_BATCHES, 1):
            self._explore_group(ctx.root_group, batch, rnd, ctx)

    def _explore_group(self, group, rules, rnd, ctx):
        while not group.exploration_mark.is_explored(rnd):
            group.exploration_mark.mark_explored(rnd)

            for equiv in list(group.equivalents):
                if not equiv.exploration_mark.is_explored(rnd):
                    equiv.exploration_mark.mark_explored(rnd)
                    for child in equiv.children:
                        self._explore_group(child, rules, rnd, ctx)
                        if not child.exploration_mark.is_explored(rnd):
                            equiv.exploration_mark.mark_unexplored(rnd)
                            group.exploration_mark.mark_unexplored(rnd)

                # fire rules
                for rule in rules:
                    name = rule.__class__.__name__
                    if name in equiv.applied_transformations:
                        continue
                    if not rule.match(equiv, ctx):
                        continue
                    try:
                        transformed = rule.transform(equiv, ctx)
                    except NotImplementedError:
                        continue
                    equiv.applied_transformations.add(name)
                    if transformed not in group.equivalents:
                        group.equivalents.add(transformed)
                        transformed.exploration_mark.mark_unexplored(rnd)
                        group.exploration_mark.mark_unexplored(rnd)

                if not equiv.exploration_mark.is_explored(rnd):
                    group.exploration_mark.mark_unexplored(rnd)

    # ── Phase 3: Implement ──────────────────────────────────────────────
    def _implement(self, ctx):
        ctx.root_group.implementation = self._implement_group(
            ctx.root_group, ctx)

    def _implement_group(self, group, ctx):
        if group.implementation is not None:
            return group.implementation

        best = None
        for equiv in group.equivalents:
            builders = get_physical_plan_builders(equiv, ctx)
            child_plans = []
            for child_group in equiv.children:
                ci = self._implement_group(child_group, ctx)
                child_group.implementation = ci
                child_plans.append(ci.physical_plan)

            for builder in builders:
                pp = builder.build(child_plans)
                if pp is None:
                    continue
                c = pp.cost()
                if best is None or ctx.cost_model.is_better(best.cost, c):
                    best = GroupImplementation(pp, c, equiv)

        if best is None:
            raise RuntimeError(f"No physical plan for group {group.id}")
        return best
