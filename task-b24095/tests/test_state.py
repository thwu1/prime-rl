"""
Tests for the query plan optimizer.

"""
import json
import os
import sys
import pytest

sys.path.insert(0, "/app")
from plan_ir import PlanNode, Expr


OPTIMIZED_DIR = "/app/optimized"


def load_optimized(name: str) -> PlanNode:
    path = os.path.join(OPTIMIZED_DIR, name)
    assert os.path.exists(path), f"Optimized plan not found: {path}"
    with open(path) as f:
        return PlanNode.from_dict(json.load(f))


def find_nodes(plan: PlanNode, kind: str) -> list:
    """Recursively find all nodes of a given kind."""
    result = []
    if plan.kind == kind:
        result.append(plan)
    for c in plan.children:
        result.extend(find_nodes(c, kind))
    return result


def count_nodes(plan: PlanNode, kind: str) -> int:
    return len(find_nodes(plan, kind))


def has_node(plan: PlanNode, kind: str) -> bool:
    return count_nodes(plan, kind) > 0


def get_all_filter_predicates(plan: PlanNode) -> list:
    """Get all filter predicates in the plan tree."""
    preds = []
    if plan.kind == "filter" and plan.predicate:
        preds.append(plan.predicate)
    for c in plan.children:
        preds.extend(get_all_filter_predicates(c))
    return preds


# ==================== Plan 1: Filter push past projection ====================

class TestPlan01FilterPushPastProject:
    @pytest.fixture
    def plan(self):
        return load_optimized("01_filter_push_past_project.json")

    def test_filter_below_subquery_alias(self, plan):
        """Filter should be pushed below the subquery_alias or at least below projection."""
        # The top-level should NOT be a filter on score > 90 anymore (it should have been pushed down)
        # After optimization, the filter should be closer to the scan
        filters = find_nodes(plan, "filter")
        assert len(filters) > 0, "Filter should still exist somewhere in the plan"

        # Find the deepest filter - it should be near the scan
        scans = find_nodes(plan, "scan")
        assert len(scans) == 1
        # The filter should be an ancestor of the scan but below any projection
        # Check that there's a filter whose child chain leads to a scan
        for f in filters:
            scan_descendants = find_nodes(f, "scan")
            if scan_descendants:
                # This filter is above a scan - good
                # Check it's not above a project
                projects_between = find_nodes(f, "project")
                # The filter should have been pushed through the project
                # so the project should not be between filter and scan
                # (filter should be child of project, not parent)
                break

    def test_scan_still_exists(self, plan):
        assert has_node(plan, "scan"), "Scan node should still exist"


# ==================== Plan 2: Cross join -> inner join ====================

class TestPlan02CrossJoinToInner:
    @pytest.fixture
    def plan(self):
        return load_optimized("02_cross_join_to_inner.json")

    def test_no_cross_join(self, plan):
        """Cross join should have been converted to inner join."""
        joins = find_nodes(plan, "join")
        for j in joins:
            assert j.join_type != "cross", "Cross join should have been eliminated"

    def test_has_inner_join(self, plan):
        joins = find_nodes(plan, "join")
        inner_joins = [j for j in joins if j.join_type == "inner"]
        assert len(inner_joins) >= 1, "Should have at least one inner join"

    def test_join_has_condition(self, plan):
        joins = find_nodes(plan, "join")
        inner_joins = [j for j in joins if j.join_type == "inner"]
        for j in inner_joins:
            assert j.join_condition is not None, "Inner join must have a join condition"

    def test_equijoin_condition(self, plan):
        """The join condition should be an equality on customer_id = id."""
        joins = find_nodes(plan, "join")
        inner_joins = [j for j in joins if j.join_type == "inner"]
        assert len(inner_joins) >= 1
        cond = inner_joins[0].join_condition
        assert cond.kind == "binary" and cond.op == "=", "Join condition should be an equality"

    def test_residual_filter_exists(self, plan):
        """The non-join predicate (customers.active = true) should remain as a filter."""
        filters = find_nodes(plan, "filter")
        # There should be at least one remaining filter for the active = true predicate
        assert len(filters) >= 1, "Residual filter should exist for non-join predicates"


# ==================== Plan 3: Propagate empty relation ====================

class TestPlan03PropagateEmpty:
    @pytest.fixture
    def plan(self):
        return load_optimized("03_propagate_empty.json")

    def test_is_empty(self, plan):
        """The entire plan should collapse to an empty relation."""
        # The always-false filter creates empty, inner join with empty side = empty
        assert plan.kind == "empty_relation", \
            f"Plan should be empty_relation but is {plan.kind}"

    def test_not_produce_one_row(self, plan):
        assert not plan.produce_one_row


# ==================== Plan 4: Limit push through union ====================

class TestPlan04LimitPushUnion:
    @pytest.fixture
    def plan(self):
        return load_optimized("04_limit_push_union.json")

    def test_top_level_limit(self, plan):
        """Top-level limit should still exist."""
        assert plan.kind == "limit", f"Top should be limit, got {plan.kind}"
        assert plan.fetch == 10

    def test_limits_pushed_into_union_branches(self, plan):
        """Each union branch should have a limit pushed into it."""
        unions = find_nodes(plan, "union")
        assert len(unions) >= 1, "Union should still exist"
        union = unions[0]
        for i, branch in enumerate(union.children):
            # Each branch should have a limit node
            branch_limits = find_nodes(branch, "limit")
            assert len(branch_limits) >= 1, \
                f"Union branch {i} should have a limit pushed into it"


# ==================== Plan 5: Eliminate always-true filter ====================

class TestPlan05EliminateTrueFilter:
    @pytest.fixture
    def plan(self):
        return load_optimized("05_eliminate_true_filter.json")

    def test_no_filter_with_tautology(self, plan):
        """The 1=1 filter should be completely removed."""
        filters = find_nodes(plan, "filter")
        for f in filters:
            if f.predicate and f.predicate.is_always_true():
                pytest.fail("Always-true filter should have been eliminated")

    def test_structure_preserved(self, plan):
        """Project and scan should remain."""
        assert has_node(plan, "scan")


# ==================== Plan 6: Eliminate always-false filter ====================

class TestPlan06EliminateFalseFilter:
    @pytest.fixture
    def plan(self):
        return load_optimized("06_eliminate_false_filter.json")

    def test_is_empty(self, plan):
        """Always-false filter should produce empty relation."""
        assert plan.kind == "empty_relation", \
            f"Plan should be empty_relation, got {plan.kind}"


# ==================== Plan 7: Filter push through inner join ====================

class TestPlan07FilterPushJoin:
    @pytest.fixture
    def plan(self):
        return load_optimized("07_filter_push_join.json")

    def test_no_filter_above_join(self, plan):
        """Both filter predicates should be pushed below the join."""
        # The top should not be a filter with both conditions
        if plan.kind == "filter":
            # If there's a filter on top, it should not contain both A.x > 5 and B.y < 10
            preds = []
            from plan_ir import split_conjunction
            preds = split_conjunction(plan.predicate)
            tables = set()
            for p in preds:
                tables |= p.tables_referenced()
            assert not ({"A", "B"}.issubset(tables)), \
                "Filters referencing only one side should be pushed below the join"

    def test_filters_pushed_to_sides(self, plan):
        """Filters should be pushed to the respective join sides."""
        joins = find_nodes(plan, "join")
        assert len(joins) >= 1
        join = joins[0]
        # Check left child has a filter for A.x > 5
        left_filters = find_nodes(join.children[0], "filter") if join.children else []
        right_filters = find_nodes(join.children[1], "filter") if len(join.children) > 1 else []
        assert len(left_filters) >= 1 or len(right_filters) >= 1, \
            "At least one filter should be pushed below the join"


# ==================== Plan 8: Multi-way cross join ====================

class TestPlan08MultiwayCrossJoin:
    @pytest.fixture
    def plan(self):
        return load_optimized("08_multiway_cross_join.json")

    def test_no_cross_joins(self, plan):
        joins = find_nodes(plan, "join")
        for j in joins:
            assert j.join_type != "cross", \
                "All cross joins should be converted to inner joins"

    def test_has_inner_joins(self, plan):
        joins = find_nodes(plan, "join")
        inner_joins = [j for j in joins if j.join_type == "inner"]
        assert len(inner_joins) >= 2, \
            "Should have at least 2 inner joins for 3-way join"

    def test_all_joins_have_conditions(self, plan):
        joins = find_nodes(plan, "join")
        for j in joins:
            if j.join_type == "inner":
                assert j.join_condition is not None, \
                    "Every inner join must have a join condition"


# ==================== Plan 9: Left join filter semantics ====================

class TestPlan09LeftJoinFilter:
    @pytest.fixture
    def plan(self):
        return load_optimized("09_left_join_filter.json")

    def test_left_filter_pushed(self, plan):
        """A.x > 5 should be pushed to the left child of the left join."""
        joins = find_nodes(plan, "join")
        assert len(joins) >= 1
        join = joins[0]
        if join.children:
            left_filters = find_nodes(join.children[0], "filter")
            # A.x > 5 should be pushed to left side
            assert len(left_filters) >= 1, \
                "Left-side filter should be pushed below the left join"

    def test_right_filter_not_pushed_below_join(self, plan):
        """B.y < 10 should NOT be pushed below the right side of a left join."""
        joins = find_nodes(plan, "join")
        assert len(joins) >= 1
        join = joins[0]
        if len(join.children) > 1:
            right_filters = find_nodes(join.children[1], "filter")
            # B.y < 10 should NOT appear as a filter in the right child
            for rf in right_filters:
                if rf.predicate:
                    tables = rf.predicate.tables_referenced()
                    assert "B" not in tables or "A" in tables, \
                        "Right-only filter should NOT be pushed below left join's right child"


# ==================== Plan 10: Limit merge ====================

class TestPlan10LimitMerge:
    @pytest.fixture
    def plan(self):
        return load_optimized("10_limit_merge.json")

    def test_single_limit(self, plan):
        """Nested limits should be merged into one."""
        limits = find_nodes(plan, "limit")
        assert len(limits) == 1, f"Should have exactly 1 limit, got {len(limits)}"

    def test_correct_fetch(self, plan):
        """LIMIT 5 over LIMIT 20 -> fetch = min(5, 20) = 5."""
        limits = find_nodes(plan, "limit")
        assert limits[0].fetch == 5


# ==================== Plan 11: Limit with skip merge ====================

class TestPlan11LimitSkipMerge:
    @pytest.fixture
    def plan(self):
        return load_optimized("11_limit_skip_merge.json")

    def test_single_limit(self, plan):
        limits = find_nodes(plan, "limit")
        assert len(limits) == 1, f"Should have exactly 1 limit, got {len(limits)}"

    def test_correct_skip(self, plan):
        """SKIP 2 FETCH 3 over SKIP 5 FETCH 10 -> skip = 5+2 = 7."""
        limits = find_nodes(plan, "limit")
        assert limits[0].skip == 7, f"Expected skip=7, got {limits[0].skip}"

    def test_correct_fetch(self, plan):
        """SKIP 2 FETCH 3 over SKIP 5 FETCH 10 -> fetch = min(3, 10-2) = 3."""
        limits = find_nodes(plan, "limit")
        assert limits[0].fetch == 3, f"Expected fetch=3, got {limits[0].fetch}"


# ==================== Plan 12: Empty left join (left empty) ====================

class TestPlan12EmptyLeftJoin:
    @pytest.fixture
    def plan(self):
        return load_optimized("12_empty_left_join.json")

    def test_is_empty(self, plan):
        """Left join with empty left side should be empty."""
        assert plan.kind == "empty_relation", \
            f"Expected empty_relation, got {plan.kind}"


# ==================== Plan 13: Full join with one empty side ====================

class TestPlan13EmptyFullJoin:
    @pytest.fixture
    def plan(self):
        return load_optimized("13_empty_full_join.json")

    def test_not_fully_collapsed(self, plan):
        """Full join with only one side empty should NOT collapse to empty."""
        # Full outer join with empty left still returns right rows with NULL left cols
        assert plan.kind != "empty_relation", \
            "Full join with only one empty side should NOT be empty"

    def test_still_has_data_source(self, plan):
        """The right side data should still be accessible."""
        scans = find_nodes(plan, "scan")
        assert len(scans) >= 1 or has_node(plan, "join"), \
            "Data source should still be present"


# ==================== Plan 14: Complex combined ====================

class TestPlan14CombinedComplex:
    @pytest.fixture
    def plan(self):
        return load_optimized("14_combined_complex.json")

    def test_no_tautology_filter(self, plan):
        """The 1=1 filter should be eliminated."""
        filters = find_nodes(plan, "filter")
        for f in filters:
            if f.predicate and f.predicate.is_always_true():
                pytest.fail("Tautological filter should be eliminated")

    def test_no_cross_join(self, plan):
        """Cross join should be converted to inner join."""
        joins = find_nodes(plan, "join")
        for j in joins:
            assert j.join_type != "cross", "Cross join should be eliminated"

    def test_has_limit(self, plan):
        """Limit should still exist."""
        assert has_node(plan, "limit")

    def test_has_sort(self, plan):
        """Sort should still exist."""
        assert has_node(plan, "sort")


# ==================== Plan 15: Filter push through aggregate ====================

class TestPlan15FilterPushAggregate:
    @pytest.fixture
    def plan(self):
        return load_optimized("15_filter_push_aggregate.json")

    def test_filter_pushed_below_aggregate(self, plan):
        """Filter on group-by column should be pushed below the aggregate."""
        aggs = find_nodes(plan, "aggregate")
        assert len(aggs) >= 1
        agg = aggs[0]
        # Check for filters below the aggregate
        filters_below = find_nodes(agg, "filter")
        assert len(filters_below) >= 1, \
            "Filter on group-by column should be pushed below aggregate"


# ==================== Plan 16: Empty through sort ====================

class TestPlan16EmptyThroughSort:
    @pytest.fixture
    def plan(self):
        return load_optimized("16_empty_through_sort.json")

    def test_is_empty(self, plan):
        """Sort(Project(Empty)) should collapse to Empty."""
        assert plan.kind == "empty_relation", \
            f"Expected empty_relation, got {plan.kind}"


# ==================== Plan 17: Right join with empty right ====================

class TestPlan17EmptyRightJoin:
    @pytest.fixture
    def plan(self):
        return load_optimized("17_empty_right_join.json")

    def test_is_empty(self, plan):
        """Right join with empty right side should produce empty."""
        assert plan.kind == "empty_relation", \
            f"Expected empty_relation, got {plan.kind}"
