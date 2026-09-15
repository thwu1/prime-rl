#!/usr/bin/env python3
"""Generate reference cases SQLite database."""
import json
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from layout_solver.types import (
    Rect, Direction, Flex,
    Length, Percentage, Ratio, Fill, Min, Max,
    Leaf, Container,
)
from solver_ref import split, compose


def rect_to_dict(r):
    return {"x": r.x, "y": r.y, "width": r.width, "height": r.height}


def constraint_to_dict(c):
    if isinstance(c, Length):
        return {"type": "Length", "value": c.value}
    elif isinstance(c, Percentage):
        return {"type": "Percentage", "value": c.value}
    elif isinstance(c, Ratio):
        return {"type": "Ratio", "numerator": c.numerator, "denominator": c.denominator}
    elif isinstance(c, Fill):
        return {"type": "Fill", "weight": c.weight}
    elif isinstance(c, Min):
        return {"type": "Min", "value": c.value, "inner": constraint_to_dict(c.inner)}
    elif isinstance(c, Max):
        return {"type": "Max", "value": c.value, "inner": constraint_to_dict(c.inner)}


def node_to_dict(node):
    if isinstance(node, Leaf):
        d = {"type": "leaf", "name": node.name}
        if node.intrinsic_width != 0:
            d["intrinsic_width"] = node.intrinsic_width
        if node.intrinsic_height != 0:
            d["intrinsic_height"] = node.intrinsic_height
        if node.sizing != "fixed":
            d["sizing"] = node.sizing
        return d
    elif isinstance(node, Container):
        d = {
            "type": "container",
            "direction": node.direction.name,
            "constraints": [constraint_to_dict(c) for c in node.constraints],
            "children": [node_to_dict(c) for c in node.children],
        }
        if node.spacing != 0:
            d["spacing"] = node.spacing
        if node.flex != Flex.START:
            d["flex"] = node.flex.name
        if node.sizing != "fixed":
            d["sizing"] = node.sizing
        return d


def make_split_input(area, constraints, direction=Direction.HORIZONTAL, spacing=0, flex=Flex.START):
    return {
        "area": rect_to_dict(area),
        "constraints": [constraint_to_dict(c) for c in constraints],
        "direction": direction.name,
        "spacing": spacing,
        "flex": flex.name,
    }


def run_split_case(area, constraints, direction=Direction.HORIZONTAL, spacing=0, flex=Flex.START):
    result = split(area, constraints, direction, spacing, flex)
    input_data = make_split_input(area, constraints, direction, spacing, flex)
    output_data = [rect_to_dict(r) for r in result]
    return input_data, output_data


def make_compose_input(area, tree):
    return {
        "mode": "compose",
        "area": rect_to_dict(area),
        "tree": node_to_dict(tree),
    }


def run_compose_case(area, tree):
    result = compose(area, tree)
    input_data = make_compose_input(area, tree)
    output_data = {name: rect_to_dict(r) for name, r in result.items()}
    return input_data, output_data


def generate_split_cases():
    cases = []

    inp, out = run_split_case(Rect(0, 0, 100, 20), [Length(50)])
    cases.append(("single_length", inp, out))
    inp, out = run_split_case(Rect(0, 0, 200, 10), [Percentage(40)])
    cases.append(("single_percentage", inp, out))
    inp, out = run_split_case(Rect(0, 0, 200, 10), [Ratio(1, 4)])
    cases.append(("single_ratio", inp, out))
    inp, out = run_split_case(Rect(0, 0, 80, 15), [Fill(1)])
    cases.append(("single_fill", inp, out))

    inp, out = run_split_case(Rect(0, 0, 80, 10), [Length(25), Length(35)])
    cases.append(("two_lengths", inp, out))
    inp, out = run_split_case(Rect(0, 0, 80, 10), [Length(20)] * 4)
    cases.append(("four_equal_lengths", inp, out))
    inp, out = run_split_case(Rect(0, 0, 50, 10), [Length(30), Length(40)])
    cases.append(("lengths_overflow", inp, out))
    inp, out = run_split_case(Rect(0, 0, 120, 10), [Percentage(30), Percentage(50)])
    cases.append(("two_percentages", inp, out))
    inp, out = run_split_case(Rect(0, 0, 200, 10), [Ratio(1, 4), Ratio(1, 4), Ratio(2, 4)])
    cases.append(("three_ratios", inp, out))

    inp, out = run_split_case(Rect(0, 0, 80, 10), [Fill(1), Fill(1)])
    cases.append(("two_equal_fills", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10), [Fill(1), Fill(1), Fill(1)])
    cases.append(("three_equal_fills_rounding", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10), [Fill(1)] * 4)
    cases.append(("four_equal_fills", inp, out))

    inp, out = run_split_case(Rect(0, 0, 200, 10), [Fill(1), Fill(3)])
    cases.append(("fills_1_3", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10), [Fill(2), Fill(3)])
    cases.append(("fills_2_3", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10), [Fill(1), Fill(2), Fill(7)])
    cases.append(("fills_1_2_7", inp, out))
    inp, out = run_split_case(Rect(0, 0, 103, 10), [Fill(1)] * 5)
    cases.append(("five_fills_rounding", inp, out))
    inp, out = run_split_case(Rect(0, 0, 99, 10), [Fill(3), Fill(7)])
    cases.append(("fills_3_7_rounding", inp, out))

    inp, out = run_split_case(Rect(0, 0, 100, 10), [Length(15), Fill(1), Length(25)])
    cases.append(("length_fill_length", inp, out))
    inp, out = run_split_case(Rect(0, 0, 200, 10), [Percentage(10), Fill(1), Percentage(40)])
    cases.append(("pct_fill_pct", inp, out))
    inp, out = run_split_case(Rect(0, 0, 200, 10), [Length(10), Percentage(20), Fill(1), Ratio(1, 5)])
    cases.append(("mixed_all_types", inp, out))
    inp, out = run_split_case(Rect(0, 0, 150, 10), [Fill(1), Length(50), Fill(2)])
    cases.append(("fill_length_fill", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10), [Length(10), Length(20), Fill(1), Fill(2)])
    cases.append(("two_lengths_two_fills", inp, out))

    inp, out = run_split_case(Rect(0, 0, 100, 10), [Min(25, Length(10)), Fill(1)])
    cases.append(("min_raises_length", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10), [Max(15, Length(30)), Fill(1)])
    cases.append(("max_caps_length", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10), [Min(5, Length(20)), Fill(1)])
    cases.append(("min_no_effect_on_length", inp, out))
    inp, out = run_split_case(Rect(0, 0, 150, 10), [Min(40, Percentage(20)), Fill(1)])
    cases.append(("min_raises_percentage", inp, out))
    inp, out = run_split_case(Rect(0, 0, 150, 10), [Max(20, Percentage(50)), Fill(1)])
    cases.append(("max_caps_percentage", inp, out))

    inp, out = run_split_case(Rect(0, 0, 100, 10), [Max(30, Fill(1)), Fill(1)])
    cases.append(("max_on_fill", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10), [Min(60, Fill(1)), Fill(1)])
    cases.append(("min_on_fill", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10), [Min(10, Max(40, Fill(1))), Fill(1)])
    cases.append(("nested_min_max_fill", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10), [Min(50, Max(30, Fill(1))), Fill(1)])
    cases.append(("min_max_conflict", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10),
                              [Min(20, Max(80, Fill(1))), Min(10, Max(40, Fill(1)))])
    cases.append(("two_nested_fills", inp, out))
    inp, out = run_split_case(Rect(0, 0, 90, 10),
                              [Min(5, Max(15, Fill(1))), Fill(1), Fill(1)])
    cases.append(("nested_with_plain_fills", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10),
                              [Min(10, Min(20, Max(50, Fill(1)))), Fill(1)])
    cases.append(("double_min_nested", inp, out))

    inp, out = run_split_case(Rect(0, 0, 100, 10),
                              [Max(20, Fill(1)), Max(30, Fill(2)), Fill(1)])
    cases.append(("two_iter_bounded", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10),
                              [Max(15, Fill(1)), Max(25, Fill(1)), Max(35, Fill(1)), Fill(1)])
    cases.append(("three_iter_bounded", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10),
                              [Min(40, Fill(1)), Min(35, Fill(1)), Fill(1)])
    cases.append(("min_bounded_interaction", inp, out))
    inp, out = run_split_case(Rect(0, 0, 200, 10),
                              [Max(10, Fill(1)), Max(20, Fill(1)), Max(30, Fill(1)), Fill(1), Fill(1)])
    cases.append(("five_fills_three_capped", inp, out))

    inp, out = run_split_case(Rect(5, 10, 40, 60), [Length(15), Fill(1)],
                              direction=Direction.VERTICAL)
    cases.append(("vertical_basic", inp, out))
    inp, out = run_split_case(Rect(20, 30, 80, 40), [Length(30), Fill(1)])
    cases.append(("offset_area", inp, out))
    inp, out = run_split_case(Rect(10, 5, 50, 80), [Length(20), Fill(1)],
                              direction=Direction.VERTICAL, spacing=5)
    cases.append(("vertical_offset_spacing", inp, out))

    inp, out = run_split_case(Rect(0, 0, 100, 10), [Fill(1), Fill(1), Fill(1)], spacing=5)
    cases.append(("three_fills_spacing", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10), [Length(20), Fill(1), Length(20)], spacing=10)
    cases.append(("length_fill_length_spacing", inp, out))

    inp, out = run_split_case(Rect(0, 0, 120, 10), [Length(20), Length(30)], flex=Flex.END)
    cases.append(("flex_end", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10), [Length(40)], flex=Flex.CENTER)
    cases.append(("flex_center_single", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10),
                              [Length(10), Length(10), Length(10), Length(10)],
                              flex=Flex.SPACE_BETWEEN)
    cases.append(("flex_space_between_four", inp, out))
    inp, out = run_split_case(Rect(10, 5, 100, 30), [Length(20), Length(20)],
                              flex=Flex.SPACE_BETWEEN)
    cases.append(("flex_space_between_offset", inp, out))
    inp, out = run_split_case(Rect(0, 0, 100, 10), [Length(20), Length(30)], flex=Flex.CENTER)
    cases.append(("flex_center_two", inp, out))

    inp, out = run_split_case(Rect(0, 0, 30, 10), [Length(50), Length(50), Length(50)])
    cases.append(("overconstrained_3x", inp, out))
    inp, out = run_split_case(Rect(0, 0, 0, 10), [Length(10)])
    cases.append(("zero_width_area", inp, out))
    inp, out = run_split_case(Rect(0, 0, 97, 10), [Fill(1)] * 10)
    cases.append(("ten_fills_rounding", inp, out))
    inp, out = run_split_case(Rect(0, 0, 10000, 10), [Fill(1), Fill(2), Fill(3)])
    cases.append(("large_area_fills", inp, out))
    inp, out = run_split_case(Rect(0, 0, 7, 10), [Fill(1), Fill(1), Fill(1)])
    cases.append(("small_area_three_fills", inp, out))

    return cases


def generate_compose_cases():
    cases = []

    # Basic leaf
    tree = Leaf("root")
    inp, out = run_compose_case(Rect(0, 0, 100, 50), tree)
    cases.append(("compose_leaf", inp, out))

    # Simple horizontal container
    tree = Container(
        direction=Direction.HORIZONTAL,
        constraints=(Length(30), Fill(1)),
        children=(Leaf("left"), Leaf("right")),
    )
    inp, out = run_compose_case(Rect(0, 0, 100, 50), tree)
    cases.append(("compose_h_basic", inp, out))

    # Simple vertical container
    tree = Container(
        direction=Direction.VERTICAL,
        constraints=(Length(20), Fill(1)),
        children=(Leaf("top"), Leaf("bottom")),
    )
    inp, out = run_compose_case(Rect(0, 0, 80, 60), tree)
    cases.append(("compose_v_basic", inp, out))

    # Nested containers (2 levels)
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
    inp, out = run_compose_case(Rect(0, 0, 100, 60), tree)
    cases.append(("compose_nested_2level", inp, out))

    # Three-way split with nested
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
    inp, out = run_compose_case(Rect(0, 0, 160, 80), tree)
    cases.append(("compose_dashboard", inp, out))

    # Container with spacing and flex
    tree = Container(
        direction=Direction.HORIZONTAL,
        constraints=(Fill(1), Fill(1), Fill(1)),
        children=(Leaf("a"), Leaf("b"), Leaf("c")),
        spacing=10,
    )
    inp, out = run_compose_case(Rect(0, 0, 110, 20), tree)
    cases.append(("compose_spacing", inp, out))

    # Three levels deep
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
    inp, out = run_compose_case(Rect(0, 0, 120, 80), tree)
    cases.append(("compose_3level_deep", inp, out))

    # --- Auto-sizing cases (deliberately sparse) ---

    # Auto-sized leaf squeezes sibling
    tree = Container(
        direction=Direction.HORIZONTAL,
        constraints=(Fill(1), Fill(1)),
        children=(
            Leaf("a", intrinsic_width=70, sizing="auto"),
            Leaf("b"),
        ),
    )
    inp, out = run_compose_case(Rect(0, 0, 100, 50), tree)
    cases.append(("compose_auto_leaf", inp, out))

    # Auto-sized container (intrinsic from children)
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
    inp, out = run_compose_case(Rect(0, 0, 100, 50), tree)
    cases.append(("compose_auto_container", inp, out))

    # Auto-sized container with spacing
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
    inp, out = run_compose_case(Rect(0, 0, 80, 40), tree)
    cases.append(("compose_auto_spacing", inp, out))

    # Auto vertical container in horizontal parent
    tree = Container(
        direction=Direction.HORIZONTAL,
        constraints=(Fill(1), Fill(1)),
        children=(
            Container(
                direction=Direction.VERTICAL,
                constraints=(Length(20), Length(30)),
                children=(
                    Leaf("a", intrinsic_width=60),
                    Leaf("b", intrinsic_width=40),
                ),
                sizing="auto",
            ),
            Leaf("c"),
        ),
    )
    inp, out = run_compose_case(Rect(0, 0, 100, 80), tree)
    cases.append(("compose_auto_cross_axis", inp, out))

    return cases


def main():
    db_path = sys.argv[1]
    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS split_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            input_json TEXT NOT NULL,
            output_json TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS compose_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            input_json TEXT NOT NULL,
            output_json TEXT NOT NULL
        )
    """)

    split_cases = generate_split_cases()
    for desc, inp, out in split_cases:
        conn.execute(
            "INSERT INTO split_cases (description, input_json, output_json) VALUES (?, ?, ?)",
            (desc, json.dumps(inp), json.dumps(out))
        )

    compose_cases = generate_compose_cases()
    for desc, inp, out in compose_cases:
        conn.execute(
            "INSERT INTO compose_cases (description, input_json, output_json) VALUES (?, ?, ?)",
            (desc, json.dumps(inp), json.dumps(out))
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
