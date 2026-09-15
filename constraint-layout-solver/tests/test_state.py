"""
Tests for the constraint-based layout engine (split + compose).

"""
import sys
sys.path.insert(0, "/app")

import pytest
from layout_solver.types import (
    Rect, Direction, Flex,
    Length, Percentage, Ratio, Fill, Min, Max,
    Leaf, Container,
)
from layout_solver.solver import split, compose


# ===========================================================================
# split() tests — constraint-based 1D partitioning
# ===========================================================================

class TestBasicConstraints:
    def test_empty(self):
        result = split(Rect(0, 0, 100, 50), [])
        assert result == []

    def test_single_length(self):
        result = split(Rect(0, 0, 100, 50), [Length(100)])
        assert result == [Rect(0, 0, 100, 50)]

    def test_basic_lengths(self):
        result = split(
            Rect(0, 0, 60, 20),
            [Length(10), Length(20), Length(30)],
        )
        assert result == [
            Rect(0, 0, 10, 20),
            Rect(10, 0, 20, 20),
            Rect(30, 0, 30, 20),
        ]

    def test_percentages(self):
        result = split(
            Rect(0, 0, 200, 10),
            [Percentage(25), Percentage(75)],
        )
        assert result == [
            Rect(0, 0, 50, 10),
            Rect(50, 0, 150, 10),
        ]

    def test_ratio(self):
        result = split(
            Rect(0, 0, 90, 10),
            [Ratio(1, 3), Ratio(2, 3)],
        )
        assert result == [
            Rect(0, 0, 30, 10),
            Rect(30, 0, 60, 10),
        ]


class TestFillConstraints:
    def test_fill_equal(self):
        result = split(Rect(0, 0, 100, 10), [Fill(1), Fill(1)])
        assert result == [
            Rect(0, 0, 50, 10),
            Rect(50, 0, 50, 10),
        ]

    def test_fill_weighted(self):
        result = split(
            Rect(0, 0, 120, 10),
            [Fill(1), Fill(2), Fill(3)],
        )
        assert result == [
            Rect(0, 0, 20, 10),
            Rect(20, 0, 40, 10),
            Rect(60, 0, 60, 10),
        ]

    def test_fill_rounding(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Fill(1), Fill(1), Fill(1)],
        )
        assert result == [
            Rect(0, 0, 34, 10),
            Rect(34, 0, 33, 10),
            Rect(67, 0, 33, 10),
        ]

    def test_fill_rounding_weighted(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Fill(1), Fill(2), Fill(3)],
        )
        assert result == [
            Rect(0, 0, 17, 10),
            Rect(17, 0, 33, 10),
            Rect(50, 0, 50, 10),
        ]


class TestMixedConstraints:
    def test_length_and_fill(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Length(20), Fill(1), Length(30)],
        )
        assert result == [
            Rect(0, 0, 20, 10),
            Rect(20, 0, 50, 10),
            Rect(70, 0, 30, 10),
        ]

    def test_percentage_and_fill(self):
        result = split(
            Rect(0, 0, 200, 10),
            [Percentage(20), Fill(1), Percentage(30)],
        )
        assert result == [
            Rect(0, 0, 40, 10),
            Rect(40, 0, 100, 10),
            Rect(140, 0, 60, 10),
        ]

    def test_spacing(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Fill(1), Fill(1)],
            spacing=10,
        )
        assert result == [
            Rect(0, 0, 45, 10),
            Rect(55, 0, 45, 10),
        ]


class TestMinMaxConstraints:
    def test_min_on_percentage(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Min(30, Percentage(10)), Fill(1)],
        )
        assert result == [
            Rect(0, 0, 30, 10),
            Rect(30, 0, 70, 10),
        ]

    def test_max_on_percentage(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Max(20, Percentage(50)), Fill(1)],
        )
        assert result == [
            Rect(0, 0, 20, 10),
            Rect(20, 0, 80, 10),
        ]

    def test_min_no_effect(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Min(5, Percentage(30)), Fill(1)],
        )
        assert result == [
            Rect(0, 0, 30, 10),
            Rect(30, 0, 70, 10),
        ]

    def test_nested_min_max_fill(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Min(10, Max(40, Fill(1))), Fill(1)],
        )
        assert result == [
            Rect(0, 0, 40, 10),
            Rect(40, 0, 60, 10),
        ]

    def test_min_max_conflict(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Min(60, Max(40, Fill(1))), Fill(1)],
        )
        assert result == [
            Rect(0, 0, 60, 10),
            Rect(60, 0, 40, 10),
        ]


class TestBoundedFillInteraction:
    def test_cascading_bounds(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Max(25, Fill(1)), Max(35, Fill(2)), Fill(1)],
        )
        assert result == [
            Rect(0, 0, 25, 10),
            Rect(25, 0, 35, 10),
            Rect(60, 0, 40, 10),
        ]

    def test_complex_mixed(self):
        result = split(
            Rect(0, 0, 200, 10),
            [Length(40), Min(20, Max(60, Fill(2))), Max(50, Fill(3)), Fill(1)],
        )
        assert result == [
            Rect(0, 0, 40, 10),
            Rect(40, 0, 60, 10),
            Rect(100, 0, 50, 10),
            Rect(150, 0, 50, 10),
        ]


class TestDirectionAndEdgeCases:
    def test_vertical_direction(self):
        result = split(
            Rect(5, 10, 80, 60),
            [Length(20), Fill(1), Length(10)],
            direction=Direction.VERTICAL,
        )
        assert result == [
            Rect(5, 10, 80, 20),
            Rect(5, 30, 80, 30),
            Rect(5, 60, 80, 10),
        ]

    def test_offset_area(self):
        result = split(
            Rect(10, 20, 60, 40),
            [Length(30), Fill(1)],
        )
        assert result == [
            Rect(10, 20, 30, 40),
            Rect(40, 20, 30, 40),
        ]

    def test_overconstrained_lengths(self):
        result = split(
            Rect(0, 0, 30, 10),
            [Length(20), Length(20), Length(20)],
        )
        assert result == [
            Rect(0, 0, 10, 10),
            Rect(10, 0, 10, 10),
            Rect(20, 0, 10, 10),
        ]


class TestFlexModes:
    def test_flex_start(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Length(20), Length(30)],
            flex=Flex.START,
        )
        assert result == [
            Rect(0, 0, 20, 10),
            Rect(20, 0, 30, 10),
        ]

    def test_flex_end(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Length(30)],
            flex=Flex.END,
        )
        assert result == [Rect(70, 0, 30, 10)]

    def test_flex_center(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Length(20), Length(30)],
            flex=Flex.CENTER,
        )
        assert result == [
            Rect(25, 0, 20, 10),
            Rect(45, 0, 30, 10),
        ]

    def test_flex_space_between(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Length(20), Length(20), Length(20)],
            flex=Flex.SPACE_BETWEEN,
        )
        assert result == [
            Rect(0, 0, 20, 10),
            Rect(40, 0, 20, 10),
            Rect(80, 0, 20, 10),
        ]

    def test_flex_space_between_single(self):
        result = split(
            Rect(0, 0, 100, 10),
            [Length(40)],
            flex=Flex.SPACE_BETWEEN,
        )
        assert result == [Rect(0, 0, 40, 10)]


class TestAdvancedCases:
    def test_deeply_nested_bounds(self):
        """Min(15, Max(80, Min(10, Max(45, Fill(1))))) with a plain Fill"""
        result = split(
            Rect(0, 0, 100, 10),
            [Min(15, Max(80, Min(10, Max(45, Fill(1))))), Fill(1)],
        )
        assert result == [
            Rect(0, 0, 45, 10),
            Rect(45, 0, 55, 10),
        ]

    def test_vertical_spacing_flex_end(self):
        """Vertical direction with spacing and flex END"""
        result = split(
            Rect(5, 10, 40, 100),
            [Length(20), Length(20)],
            direction=Direction.VERTICAL,
            spacing=5,
            flex=Flex.END,
        )
        assert result == [
            Rect(5, 65, 40, 20),
            Rect(5, 90, 40, 20),
        ]

    def test_overconstrained_with_flex(self):
        """Overconstrained + flex CENTER: no leftover so flex is irrelevant"""
        result = split(
            Rect(0, 0, 50, 10),
            [Length(30), Length(30), Length(30)],
            flex=Flex.CENTER,
        )
        assert result == [
            Rect(0, 0, 17, 10),
            Rect(17, 0, 17, 10),
            Rect(34, 0, 16, 10),
        ]

    def test_all_fills_capped_redistribution(self):
        """All bounded fills hit max in sequence, remainder goes to uncapped"""
        result = split(
            Rect(0, 0, 200, 10),
            [Max(10, Fill(1)), Max(20, Fill(1)), Max(30, Fill(1)), Fill(1)],
        )
        assert result == [
            Rect(0, 0, 10, 10),
            Rect(10, 0, 20, 10),
            Rect(30, 0, 30, 10),
            Rect(60, 0, 140, 10),
        ]

    def test_weighted_bounded_fills_cascade(self):
        """Weighted fills with bounds causing multi-iteration clamping"""
        result = split(
            Rect(0, 0, 100, 10),
            [Max(15, Fill(1)), Max(25, Fill(3)), Fill(2)],
        )
        assert result == [
            Rect(0, 0, 15, 10),
            Rect(15, 0, 25, 10),
            Rect(40, 0, 60, 10),
        ]


# ===========================================================================
# compose() tests — recursive tree layout
# ===========================================================================

class TestComposeBasic:
    def test_leaf(self):
        result = compose(Rect(0, 0, 100, 50), Leaf("root"))
        assert result == {"root": Rect(0, 0, 100, 50)}

    def test_horizontal_container(self):
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Length(30), Fill(1)),
            children=(Leaf("left"), Leaf("right")),
        )
        result = compose(Rect(0, 0, 100, 50), tree)
        assert result == {
            "left": Rect(0, 0, 30, 50),
            "right": Rect(30, 0, 70, 50),
        }

    def test_vertical_container(self):
        tree = Container(
            direction=Direction.VERTICAL,
            constraints=(Length(20), Fill(1)),
            children=(Leaf("top"), Leaf("bottom")),
        )
        result = compose(Rect(0, 0, 80, 60), tree)
        assert result == {
            "top": Rect(0, 0, 80, 20),
            "bottom": Rect(0, 20, 80, 40),
        }

    def test_three_way_split(self):
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Length(20), Fill(1), Length(20)),
            children=(Leaf("a"), Leaf("b"), Leaf("c")),
        )
        result = compose(Rect(0, 0, 100, 30), tree)
        assert result == {
            "a": Rect(0, 0, 20, 30),
            "b": Rect(20, 0, 60, 30),
            "c": Rect(80, 0, 20, 30),
        }


class TestComposeNested:
    def test_two_level(self):
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Length(40), Fill(1)),
            children=(
                Container(
                    direction=Direction.VERTICAL,
                    constraints=(Length(20), Fill(1)),
                    children=(Leaf("top_left"), Leaf("bottom_left")),
                ),
                Leaf("right"),
            ),
        )
        result = compose(Rect(0, 0, 100, 60), tree)
        assert result == {
            "top_left": Rect(0, 0, 40, 20),
            "bottom_left": Rect(0, 20, 40, 40),
            "right": Rect(40, 0, 60, 60),
        }

    def test_dashboard_layout(self):
        """Three-column layout with center split vertically"""
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Length(30), Fill(1), Length(30)),
            children=(
                Leaf("sidebar_l"),
                Container(
                    direction=Direction.VERTICAL,
                    constraints=(Length(10), Fill(1), Length(10)),
                    children=(Leaf("header"), Leaf("main"), Leaf("footer")),
                ),
                Leaf("sidebar_r"),
            ),
        )
        result = compose(Rect(0, 0, 160, 80), tree)
        assert result == {
            "sidebar_l": Rect(0, 0, 30, 80),
            "header": Rect(30, 0, 100, 10),
            "main": Rect(30, 10, 100, 60),
            "footer": Rect(30, 70, 100, 10),
            "sidebar_r": Rect(130, 0, 30, 80),
        }

    def test_three_levels_deep(self):
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Fill(1), Fill(1)),
            children=(
                Container(
                    direction=Direction.VERTICAL,
                    constraints=(Fill(1), Fill(1)),
                    children=(
                        Container(
                            direction=Direction.HORIZONTAL,
                            constraints=(Length(15), Fill(1)),
                            children=(Leaf("a"), Leaf("b")),
                        ),
                        Leaf("c"),
                    ),
                ),
                Leaf("d"),
            ),
        )
        result = compose(Rect(0, 0, 120, 80), tree)
        assert result == {
            "a": Rect(0, 0, 15, 40),
            "b": Rect(15, 0, 45, 40),
            "c": Rect(0, 40, 60, 40),
            "d": Rect(60, 0, 60, 80),
        }

    def test_spacing_in_container(self):
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Fill(1), Fill(1), Fill(1)),
            children=(Leaf("a"), Leaf("b"), Leaf("c")),
            spacing=10,
        )
        result = compose(Rect(0, 0, 110, 20), tree)
        assert result == {
            "a": Rect(0, 0, 30, 20),
            "b": Rect(40, 0, 30, 20),
            "c": Rect(80, 0, 30, 20),
        }

    def test_offset_root(self):
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Fill(1), Fill(1)),
            children=(Leaf("left"), Leaf("right")),
        )
        result = compose(Rect(10, 20, 80, 40), tree)
        assert result == {
            "left": Rect(10, 20, 40, 40),
            "right": Rect(50, 20, 40, 40),
        }

    def test_flex_end_in_compose(self):
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Length(30),),
            children=(Leaf("panel"),),
            flex=Flex.END,
        )
        result = compose(Rect(0, 0, 100, 50), tree)
        assert result == {"panel": Rect(70, 0, 30, 50)}


class TestComposeAutoSizing:
    def test_auto_leaf_squeezes_sibling(self):
        """Auto-sized leaf with intrinsic_width=70 in Fill(1) gets at least 70"""
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Fill(1), Fill(1)),
            children=(
                Leaf("a", intrinsic_width=70, sizing="auto"),
                Leaf("b"),
            ),
        )
        result = compose(Rect(0, 0, 100, 50), tree)
        # Fill(1),Fill(1) => 50,50 normally
        # Auto: Min(70, Fill(1)) => 70 (clamped), remaining 30 for b
        assert result == {
            "a": Rect(0, 0, 70, 50),
            "b": Rect(70, 0, 30, 50),
        }

    def test_auto_container_intrinsic(self):
        """Auto-sized container with children Length(30)+Length(40) => intrinsic 70"""
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Fill(1), Fill(1)),
            children=(
                Container(
                    direction=Direction.HORIZONTAL,
                    constraints=(Length(30), Length(40)),
                    children=(Leaf("a"), Leaf("b")),
                    sizing="auto",
                ),
                Leaf("c"),
            ),
        )
        result = compose(Rect(0, 0, 100, 50), tree)
        # Auto container intrinsic_width = 30+40 = 70
        # Effective: [Min(70, Fill(1)), Fill(1)]
        # Fill(1),Fill(1) => 50,50; first clamped to 70, remaining 30 for c
        assert result == {
            "a": Rect(0, 0, 30, 50),
            "b": Rect(30, 0, 40, 50),
            "c": Rect(70, 0, 30, 50),
        }

    def test_auto_container_with_spacing(self):
        """Auto container intrinsic includes spacing: 20+20+10(spacing)=50"""
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Fill(1), Fill(1)),
            children=(
                Container(
                    direction=Direction.HORIZONTAL,
                    constraints=(Length(20), Length(20)),
                    children=(Leaf("a"), Leaf("b")),
                    spacing=10,
                    sizing="auto",
                ),
                Leaf("c"),
            ),
        )
        result = compose(Rect(0, 0, 80, 40), tree)
        # Intrinsic = 20+20+10 = 50
        # Effective: [Min(50, Fill(1)), Fill(1)]
        # Fill(1),Fill(1) in 80 => 40,40; first clamped to 50, remaining 30
        # Inner: split 50 with spacing=10 => usable=40, [Length(20), Length(20)]
        assert result == {
            "a": Rect(0, 0, 20, 40),
            "b": Rect(30, 0, 20, 40),
            "c": Rect(50, 0, 30, 40),
        }

    def test_auto_cross_axis_vertical_in_horizontal(self):
        """V-container in H-parent: intrinsic_width = max of children's widths"""
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Fill(1), Fill(1)),
            children=(
                Container(
                    direction=Direction.VERTICAL,
                    constraints=(Length(30), Length(20)),
                    children=(
                        Leaf("a", intrinsic_width=60),
                        Leaf("b", intrinsic_width=40),
                    ),
                    sizing="auto",
                ),
                Leaf("c"),
            ),
        )
        result = compose(Rect(0, 0, 100, 80), tree)
        # V-container in H-parent: intrinsic_width = max(60, 40) = 60
        # Effective: [Min(60, Fill(1)), Fill(1)]
        # 50,50 => first clamped to 60, remaining 40
        assert result == {
            "a": Rect(0, 0, 60, 30),
            "b": Rect(0, 30, 60, 20),
            "c": Rect(60, 0, 40, 80),
        }

    def test_auto_overconstrained(self):
        """Two auto-sized children that together exceed available space"""
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Fill(1), Fill(1)),
            children=(
                Leaf("a", intrinsic_width=50, sizing="auto"),
                Leaf("b", intrinsic_width=50, sizing="auto"),
            ),
        )
        result = compose(Rect(0, 0, 60, 30), tree)
        # Effective: [Min(50, Fill(1)), Min(50, Fill(1))]
        # Fill(1),Fill(1) => 30,30; both clamped to 50
        # Total = 100 > 60 => overconstrained proportional: [30, 30]
        assert result == {
            "a": Rect(0, 0, 30, 30),
            "b": Rect(30, 0, 30, 30),
        }

    def test_auto_with_max_conflict(self):
        """Auto-sizing wraps Min around a Max-bounded Fill => min/max conflict"""
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Max(60, Fill(1)), Fill(1)),
            children=(
                Container(
                    direction=Direction.HORIZONTAL,
                    constraints=(Length(30), Length(40)),
                    children=(Leaf("a"), Leaf("b")),
                    sizing="auto",
                ),
                Leaf("c"),
            ),
        )
        result = compose(Rect(0, 0, 200, 50), tree)
        # Auto intrinsic = 70. Constraint becomes Min(70, Max(60, Fill(1)))
        # Bounds: min=70, max=60, conflict => max raised to 70
        # Effective bounds [70, 70] => locked at 70
        # Remaining 130 for c
        assert result == {
            "a": Rect(0, 0, 30, 50),
            "b": Rect(30, 0, 40, 50),
            "c": Rect(70, 0, 130, 50),
        }

    def test_auto_vertical_sizing(self):
        """Auto-sizing in vertical split direction uses intrinsic_height"""
        tree = Container(
            direction=Direction.VERTICAL,
            constraints=(Fill(1), Fill(1)),
            children=(
                Container(
                    direction=Direction.VERTICAL,
                    constraints=(Length(20), Length(30)),
                    children=(Leaf("top"), Leaf("mid")),
                    sizing="auto",
                ),
                Leaf("bot"),
            ),
        )
        result = compose(Rect(0, 0, 80, 100), tree)
        # V-container intrinsic_height = 20+30 = 50
        # Effective: [Min(50, Fill(1)), Fill(1)]
        # 50,50 => 50 >= 50, no clamping, both get 50
        assert result == {
            "top": Rect(0, 0, 80, 20),
            "mid": Rect(0, 20, 80, 30),
            "bot": Rect(0, 50, 80, 50),
        }

    def test_auto_nested_propagation(self):
        """Nested auto containers propagate intrinsic sizes up the tree"""
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Fill(1), Fill(1)),
            children=(
                Container(
                    direction=Direction.HORIZONTAL,
                    constraints=(Fill(1), Fill(1)),
                    children=(
                        Container(
                            direction=Direction.HORIZONTAL,
                            constraints=(Length(25), Length(15)),
                            children=(Leaf("a"), Leaf("b")),
                            sizing="auto",
                        ),
                        Leaf("c", intrinsic_width=20, sizing="auto"),
                    ),
                    sizing="auto",
                ),
                Leaf("d"),
            ),
        )
        result = compose(Rect(0, 0, 200, 50), tree)
        # Inner container intrinsic_width = 25+15 = 40
        # Leaf c intrinsic_width = 20
        # Middle container intrinsic_width = 40 + 20 = 60
        # Outer: [Min(60, Fill(1)), Fill(1)] in 200
        # Fill(1),Fill(1) => 100,100; 100 >= 60, no clamping
        # Middle: [Min(40, Fill(1)), Min(20, Fill(1))] in 100
        # Fill(1),Fill(1) => 50,50; 50 >= 40, 50 >= 20, no clamping => 50,50
        # Inner: [Length(25), Length(15)] in 50 => 25, 15
        assert result == {
            "a": Rect(0, 0, 25, 50),
            "b": Rect(25, 0, 15, 50),
            "c": Rect(50, 0, 50, 50),
            "d": Rect(100, 0, 100, 50),
        }

    def test_auto_three_siblings(self):
        """Three children with varying auto intrinsics compete for space"""
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Fill(1), Fill(1), Fill(1)),
            children=(
                Leaf("a", intrinsic_width=50, sizing="auto"),
                Leaf("b", intrinsic_width=40, sizing="auto"),
                Leaf("c"),
            ),
        )
        result = compose(Rect(0, 0, 100, 50), tree)
        # Effective: [Min(50, Fill(1)), Min(40, Fill(1)), Fill(1)]
        # Fill(1),Fill(1),Fill(1) => 34,33,33 (largest remainder)
        # a: min=50, 34 < 50 => clamped to 50, resolved
        # b: min=40, 33 < 40 => clamped to 40, resolved
        # remaining = 100 - 50 - 40 = 10 => c gets 10
        assert result == {
            "a": Rect(0, 0, 50, 50),
            "b": Rect(50, 0, 40, 50),
            "c": Rect(90, 0, 10, 50),
        }

    def test_auto_no_effect_when_intrinsic_zero(self):
        """Auto-sizing with intrinsic=0 has no effect"""
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Fill(1), Fill(1)),
            children=(
                Leaf("a", intrinsic_width=0, sizing="auto"),
                Leaf("b"),
            ),
        )
        result = compose(Rect(0, 0, 100, 50), tree)
        assert result == {
            "a": Rect(0, 0, 50, 50),
            "b": Rect(50, 0, 50, 50),
        }

    def test_auto_sufficient_space(self):
        """Auto-sizing doesn't increase allocation when enough space exists"""
        tree = Container(
            direction=Direction.HORIZONTAL,
            constraints=(Fill(1), Fill(1)),
            children=(
                Container(
                    direction=Direction.HORIZONTAL,
                    constraints=(Length(10), Length(10)),
                    children=(Leaf("a"), Leaf("b")),
                    sizing="auto",
                ),
                Leaf("c"),
            ),
        )
        result = compose(Rect(0, 0, 200, 50), tree)
        # Intrinsic = 20. Fill(1) allocates 100 each. 100 >= 20, no clamping.
        assert result == {
            "a": Rect(0, 0, 10, 50),
            "b": Rect(10, 0, 10, 50),
            "c": Rect(100, 0, 100, 50),
        }
