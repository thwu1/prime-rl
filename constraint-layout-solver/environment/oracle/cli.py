#!/usr/bin/env python3
"""CLI wrapper for the layout reference oracle."""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from layout_solver.types import (
    Rect, Direction, Flex,
    Length, Percentage, Ratio, Fill, Min, Max,
)
from solver_ref import split


def parse_constraint(c):
    t = c["type"]
    if t == "Length":
        return Length(c["value"])
    elif t == "Percentage":
        return Percentage(c["value"])
    elif t == "Ratio":
        return Ratio(c["numerator"], c["denominator"])
    elif t == "Fill":
        return Fill(c.get("weight", 1))
    elif t == "Min":
        return Min(c["value"], parse_constraint(c["inner"]))
    elif t == "Max":
        return Max(c["value"], parse_constraint(c["inner"]))
    else:
        raise ValueError(f"Unknown constraint type: {t}")


HELP_TEXT = """\
Usage: layout-oracle [--help]

Reads a JSON layout query from stdin and writes the result as JSON to stdout.

Input format (JSON on stdin):
{
  "area": {"x": 0, "y": 0, "width": 100, "height": 50},
  "constraints": [
    {"type": "Length", "value": 30},
    {"type": "Fill", "weight": 1},
    {"type": "Percentage", "value": 25},
    {"type": "Ratio", "numerator": 1, "denominator": 3},
    {"type": "Min", "value": 20, "inner": {"type": "Fill", "weight": 1}},
    {"type": "Max", "value": 40, "inner": {"type": "Fill", "weight": 1}}
  ],
  "direction": "HORIZONTAL",
  "spacing": 0,
  "flex": "START"
}

Optional fields (with defaults):
  direction  HORIZONTAL | VERTICAL       (default: HORIZONTAL)
  spacing    integer >= 0                 (default: 0)
  flex       START | END | CENTER | SPACE_BETWEEN  (default: START)

Output: JSON array of rectangles, e.g.:
  [{"x": 0, "y": 0, "width": 30, "height": 50}, ...]
"""


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(HELP_TEXT)
        sys.exit(0)

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    area = Rect(
        data["area"]["x"],
        data["area"]["y"],
        data["area"]["width"],
        data["area"]["height"],
    )

    constraints = [parse_constraint(c) for c in data["constraints"]]
    direction = Direction[data.get("direction", "HORIZONTAL")]
    spacing = data.get("spacing", 0)
    flex = Flex[data.get("flex", "START")]

    result = split(area, constraints, direction, spacing, flex)

    output = [
        {"x": r.x, "y": r.y, "width": r.width, "height": r.height}
        for r in result
    ]

    print(json.dumps(output))


if __name__ == "__main__":
    main()
