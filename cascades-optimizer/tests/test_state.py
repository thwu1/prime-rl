"""Tests for the Volcano/Cascades cost-based query optimizer.

Each test targets a specific optimizer component.  All tests must pass
for the optimiser to be considered correct.
"""

import sys
sys.path.insert(0, "/app")

import pytest
from planner.types import (
    TableID, FieldID, FilterCondition,
    LPScan, LPProject, LPJoin, LPFilter,
    TableStats, TableCatalog,
    Cost, Estimations, PhysicalPlan,
)
from planner.parser import parse_sql
from planner.memo import Memo
from planner.cost import CostModel
from planner.rules import (
    JoinReorderBySize, FilterPushDown, HashJoinBuilder,
)
from planner.optimizer import VolcanoOptimizer, OptimizerContext


# ═════════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═════════════════════════════════════════════════════════════════════════════

CATALOGS = {
    "orders": TableCatalog(
        [("id", "int"), ("item_id", "int"), ("amount", "float"), ("status", "str")],
    ),
    "products": TableCatalog(
        [("item_id", "int"), ("name", "str"), ("price", "float"), ("desc", "str")],
        metadata={"sorted": "true"},
    ),
    "categories": TableCatalog(
        [("item_id", "int"), ("cat_name", "str")],
        metadata={"sorted": "true"},
    ),
    "small_tbl": TableCatalog(
        [("id", "int"), ("val", "str")],
        metadata={"sorted": "true"},
    ),
    "large_tbl": TableCatalog(
        [("id", "int"), ("data", "str"), ("extra", "str")],
    ),
}

STATS = {
    # orders: 200 rows × 56 B/row → table_size = 11 200
    "orders": TableStats(200, {"id": 8, "item_id": 8, "amount": 8, "status": 32}),
    # products: 100 rows × 400 B/row → table_size = 40 000
    "products": TableStats(100, {"item_id": 8, "name": 64, "price": 8, "desc": 320}),
    # categories: 500 rows × 20 B/row → table_size = 10 000
    "categories": TableStats(500, {"item_id": 8, "cat_name": 12}),
    # small_tbl: 50 rows × 20 B/row → table_size = 1 000
    "small_tbl": TableStats(50, {"id": 8, "val": 12}),
    # large_tbl: 10 000 rows × 208 B/row → table_size = 2 080 000
    "large_tbl": TableStats(10000, {"id": 8, "data": 100, "extra": 100}),
}


def _ctx():
    return OptimizerContext(
        catalog_provider=lambda t: CATALOGS[t],
        stats_provider=lambda t: STATS[t],
    )


def _leaf_names(plan):
    """Collect SCAN table names in left-to-right DFS order."""
    if plan.plan_type.startswith("SCAN("):
        return [plan.plan_type.split("(")[1].rstrip(")")]
    out = []
    for c in plan.children():
        out.extend(_leaf_names(c))
    return out


def _plan_types(plan):
    """Collect plan-type strings in DFS pre-order."""
    out = [plan.plan_type]
    for c in plan.children():
        out.extend(_plan_types(c))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# 1. Cost model
# ═════════════════════════════════════════════════════════════════════════════

class TestCostModel:
    """The cost model must use weighted total cost to compare plans."""

    def test_is_better_prefers_cheaper(self):
        model = CostModel()
        cheap = Cost(cpu=100, memory=50, time=100)
        expensive = Cost(cpu=500, memory=200, time=500)
        assert model.is_better(expensive, cheap), (
            "is_better should return True when candidate "
            f"(total={model.total_cost(cheap):.0f}) is cheaper than "
            f"current_best (total={model.total_cost(expensive):.0f})"
        )

    def test_is_better_rejects_costlier(self):
        model = CostModel()
        cheap = Cost(cpu=100, memory=50, time=100)
        expensive = Cost(cpu=500, memory=200, time=500)
        assert not model.is_better(cheap, expensive), (
            "is_better should return False when candidate is more expensive"
        )

    def test_memory_dimension_matters(self):
        model = CostModel()
        low_cpu_high_mem = Cost(cpu=50, memory=10000, time=100)
        high_cpu_low_mem = Cost(cpu=200, memory=100, time=100)
        # totals: 50+5000+80 = 5130  vs  200+50+80 = 330
        assert model.is_better(low_cpu_high_mem, high_cpu_low_mem), (
            "Plan with high memory cost should NOT be preferred just "
            "because it has low CPU cost"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 2. Hash-join build-side selection
# ═════════════════════════════════════════════════════════════════════════════

class TestHashJoinBuildSide:
    """Hash join must use the smaller input as the build side."""

    def _small(self):
        return PhysicalPlan(
            "SCAN(small_tbl)",
            Cost(cpu=50, memory=20, time=50),
            Estimations(loop_iterations=50, row_size=20),
            {"SORTED"},
        )

    def _large(self):
        return PhysicalPlan(
            "SCAN(large_tbl)",
            Cost(cpu=10000, memory=208, time=10000),
            Estimations(loop_iterations=10000, row_size=208),
        )

    def test_memory_cost_small_first(self):
        """When small child comes first, memory should still use build (small) side."""
        builder = HashJoinBuilder(["small_tbl.id"], ["large_tbl.id"])
        result = builder.build([self._small(), self._large()])
        # view(small) = 50×20 = 1 000;  view(large) = 10 000×208 = 2 080 000
        assert result.cost().memory < 100_000, (
            f"Hash-join memory = {result.cost().memory:.0f} — should reflect "
            "build (smaller) side view size (~1 000), not probe side"
        )

    def test_memory_cost_large_first(self):
        """When large child comes first, builder must reorder so small is build side."""
        builder = HashJoinBuilder(["large_tbl.id"], ["small_tbl.id"])
        result = builder.build([self._large(), self._small()])
        assert result.cost().memory < 100_000, (
            f"Hash-join memory = {result.cost().memory:.0f} — builder must "
            "reorder children so smaller input is the build side"
        )

    def test_cpu_cost_uses_build_side(self):
        """CPU cost (hashing) should correspond to the build (smaller) side."""
        builder = HashJoinBuilder(["large_tbl.id"], ["small_tbl.id"])
        result = builder.build([self._large(), self._small()])
        # With reorder: cpu_self = small.iters = 50;  total ≈ 50+10000+50 = 10 100
        # Without:      cpu_self = large.iters = 10000; total ≈ 10000+10000+50 = 20 050
        assert result.cost().cpu < 15_000, (
            f"Hash-join CPU = {result.cost().cpu:.0f} — build-side hashing cost "
            "should reflect the smaller input"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 3. Join reorder
# ═════════════════════════════════════════════════════════════════════════════

class TestJoinReorder:
    """The 3-table join reorder rule must sort by estimated_table_size."""

    def test_reorders_by_table_size_not_row_count(self):
        ctx = _ctx()
        # orders: rows=200, table_size=11 200
        # products: rows=100, table_size=40 000
        # categories: rows=500, table_size=10 000
        # row-count order:  products < orders < categories  (100, 200, 500)
        # table-size order: categories < orders < products  (10K, 11.2K, 40K)
        o = LPScan(TableID("orders"))
        p = LPScan(TableID("products"))
        c = LPScan(TableID("categories"))

        # Original tree: (orders JOIN categories) JOIN products
        # With the FROM clause "FROM orders JOIN categories ... JOIN products ..."
        inner = LPJoin(o, c, [
            (FieldID(TableID("orders"), "item_id"),
             FieldID(TableID("categories"), "item_id")),
        ])
        outer = LPJoin(inner, p, [
            (FieldID(TableID("categories"), "item_id"),
             FieldID(TableID("products"), "item_id")),
        ])

        group = ctx.memo.get_or_create_group(outer)
        expr = list(group.equivalents)[0]

        rule = JoinReorderBySize()
        assert rule.match(expr, ctx), "Rule should match 3-table join"
        transformed = rule.transform(expr, ctx)

        # Collect table names from the reordered plan
        scans = []
        def _collect(plan):
            if isinstance(plan, LPScan):
                scans.append(plan.table.name)
            for ch in plan.children():
                _collect(ch)
        _collect(transformed.plan)

        assert scans[0] == "categories", (
            f"Smallest table_size table (categories=10 000) should be "
            f"outermost (first leaf), but got order {scans}"
        )
        assert scans[-1] == "products", (
            f"Largest table_size table (products=40 000) should be "
            f"innermost (last leaf), but got order {scans}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 4. Filter push-down
# ═════════════════════════════════════════════════════════════════════════════

class TestFilterPushDown:
    """Filter predicates must be pushed below joins when possible."""

    def test_pushes_left_side_filter(self):
        """Filter on left-side columns should be pushed to the left child."""
        ctx = _ctx()
        left = LPScan(TableID("small_tbl"))
        right = LPScan(TableID("large_tbl"))
        join = LPJoin(left, right, [
            (FieldID(TableID("small_tbl"), "id"),
             FieldID(TableID("large_tbl"), "id")),
        ])
        filt = LPFilter(
            [FilterCondition(FieldID(TableID("small_tbl"), "val"), ">", 5)],
            join,
        )

        group = ctx.memo.get_or_create_group(filt)
        expr = list(group.equivalents)[0]

        rule = FilterPushDown()
        assert rule.match(expr, ctx)
        transformed = rule.transform(expr, ctx)
        result = transformed.plan

        assert isinstance(result, LPJoin), (
            f"After push-down, root should be Join, got {type(result).__name__}"
        )
        left_is_filter = isinstance(result.left, LPFilter)
        right_is_filter = isinstance(result.right, LPFilter)
        assert left_is_filter or right_is_filter, (
            "Filter should appear as a child of the Join after push-down"
        )
        filt_side = result.left if left_is_filter else result.right
        assert isinstance(filt_side.child, LPScan), (
            "Pushed-down filter should sit directly above the scan"
        )
        assert filt_side.child.table.name == "small_tbl", (
            f"Filter references small_tbl columns — should be pushed to "
            f"small_tbl side, not {filt_side.child.table.name}"
        )

    def test_pushes_right_side_filter(self):
        """Filter on right-side columns should be pushed to the right child."""
        ctx = _ctx()
        left = LPScan(TableID("small_tbl"))
        right = LPScan(TableID("large_tbl"))
        join = LPJoin(left, right, [
            (FieldID(TableID("small_tbl"), "id"),
             FieldID(TableID("large_tbl"), "id")),
        ])
        filt = LPFilter(
            [FilterCondition(FieldID(TableID("large_tbl"), "data"), "=", "x")],
            join,
        )

        group = ctx.memo.get_or_create_group(filt)
        expr = list(group.equivalents)[0]

        rule = FilterPushDown()
        assert rule.match(expr, ctx)
        transformed = rule.transform(expr, ctx)
        result = transformed.plan

        assert isinstance(result, LPJoin)
        left_is_filter = isinstance(result.left, LPFilter)
        right_is_filter = isinstance(result.right, LPFilter)
        assert left_is_filter or right_is_filter
        filt_side = result.left if left_is_filter else result.right
        assert filt_side.child.table.name == "large_tbl", (
            f"Filter references large_tbl — should push to large_tbl side"
        )

    def test_no_pushdown_when_both_sides(self):
        """Filter referencing both sides of the join should not be pushed."""
        ctx = _ctx()
        left = LPScan(TableID("small_tbl"))
        right = LPScan(TableID("large_tbl"))
        join = LPJoin(left, right, [
            (FieldID(TableID("small_tbl"), "id"),
             FieldID(TableID("large_tbl"), "id")),
        ])
        filt = LPFilter(
            [
                FilterCondition(FieldID(TableID("small_tbl"), "val"), ">", 5),
                FilterCondition(FieldID(TableID("large_tbl"), "data"), "=", "x"),
            ],
            join,
        )
        group = ctx.memo.get_or_create_group(filt)
        expr = list(group.equivalents)[0]

        rule = FilterPushDown()
        assert rule.match(expr, ctx)
        transformed = rule.transform(expr, ctx)
        # When conditions span both sides, the original expression should be
        # returned unchanged (cannot push down).
        assert isinstance(transformed.plan, LPFilter), (
            "Filter spanning both sides should stay above the Join"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 5. End-to-end integration
# ═════════════════════════════════════════════════════════════════════════════

class TestEndToEnd:
    """Full optimizer pipeline must produce a correct, low-cost plan."""

    def test_three_table_join_cost(self):
        ctx = _ctx()
        sql = (
            "SELECT orders.id, products.name, categories.cat_name "
            "FROM orders "
            "JOIN categories ON orders.item_id = categories.item_id "
            "JOIN products ON categories.item_id = products.item_id"
        )
        physical = VolcanoOptimizer().optimize(parse_sql(sql), ctx)
        total = ctx.cost_model.total_cost(physical.cost())
        assert total < 500_000, (
            f"Optimal plan total weighted cost = {total:.0f}; "
            "should be well under 500 000 with correct cost model, "
            "hash-join build-side, and join ordering"
        )

    def test_three_table_join_order(self):
        ctx = _ctx()
        sql = (
            "SELECT orders.id, products.name, categories.cat_name "
            "FROM orders "
            "JOIN categories ON orders.item_id = categories.item_id "
            "JOIN products ON categories.item_id = products.item_id"
        )
        physical = VolcanoOptimizer().optimize(parse_sql(sql), ctx)
        leaves = _leaf_names(physical)
        # table-size order: categories(10K) < orders(11.2K) < products(40K)
        assert leaves[0] == "categories", (
            f"Smallest-table-size table should be outermost; got {leaves}"
        )

    def test_filter_query_end_to_end(self):
        """Query with WHERE should run without error and include FILTER."""
        ctx = _ctx()
        sql = (
            "SELECT small_tbl.id, large_tbl.data "
            "FROM small_tbl "
            "JOIN large_tbl ON small_tbl.id = large_tbl.id "
            "WHERE small_tbl.val > 5"
        )
        physical = VolcanoOptimizer().optimize(parse_sql(sql), ctx)
        types = _plan_types(physical)
        assert "FILTER" in types, (
            f"Optimized plan should contain a FILTER node; got {types}"
        )
        # FILTER should be below JOIN (pushed down)
        join_types = [t for t in types if "JOIN" in t]
        if join_types:
            join_idx = types.index(join_types[0])
            filter_idx = types.index("FILTER")
            assert filter_idx > join_idx, (
                "FILTER should appear below (after) JOIN in the plan tree "
                f"when pushed down; plan order = {types}"
            )

    def test_plan_structure_sanity(self):
        ctx = _ctx()
        sql = (
            "SELECT orders.id, products.name, categories.cat_name "
            "FROM orders "
            "JOIN categories ON orders.item_id = categories.item_id "
            "JOIN products ON categories.item_id = products.item_id"
        )
        physical = VolcanoOptimizer().optimize(parse_sql(sql), ctx)
        types = _plan_types(physical)
        assert types[0] == "PROJECT"
        join_count = sum(1 for t in types if "JOIN" in t)
        scan_count = sum(1 for t in types if t.startswith("SCAN"))
        assert join_count == 2, f"3-table query needs 2 joins; got {join_count}"
        assert scan_count == 3, f"3-table query needs 3 scans; got {scan_count}"
