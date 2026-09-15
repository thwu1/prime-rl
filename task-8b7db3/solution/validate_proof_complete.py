#!/usr/bin/env python3
"""
Proof structure validation CLI - Complete Implementation.

"""

import argparse
import json
import sys

from proof_engine.engine import (
    build_proof_tree,
    validate_decomposition,
    compute_schedule,
    generate_obligations,
    compute_cone_of_influence,
    check_compositional_soundness,
)
from proof_engine.models import ValidationError, CyclicDependencyError


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a JSON proof structure file"
    )
    parser.add_argument("file", help="Path to JSON proof structure file")
    parser.add_argument("--output", "-o", help="Write report to file instead of stdout")
    parser.add_argument("--format", choices=["json", "dot", "obligations"], default="json",
                        help="Output format: json (validation report), dot (dependency graph), or obligations (proof analysis)")
    args = parser.parse_args()

    with open(args.file) as f:
        spec = json.load(f)

    if args.format == "dot":
        _output_dot(spec, args.file, args.output)
    elif args.format == "obligations":
        _output_obligations(spec, args.file, args.output)
    else:
        _output_json(spec, args.file, args.output)


def _output_dot(spec: dict, filepath: str, output_path: str | None) -> None:
    """Generate Graphviz DOT dependency graph."""
    try:
        tree = build_proof_tree(spec)
    except ValidationError as e:
        lines = [
            "digraph proof_dependencies {",
            f'  label="Error: {e}";',
            "}",
        ]
        _write_text("\n".join(lines), output_path)
        return

    lines = [
        "digraph proof_dependencies {",
        "  rankdir=TB;",
        '  node [fontname="Helvetica"];',
        "",
    ]

    for pname, prop in tree.properties.items():
        expr_escaped = prop.expression.replace('"', '\\"')
        lines.append(
            f'  "{pname}" [shape=box, label="{pname}\\n{expr_escaped}"];'
        )

    lines.append("")

    for decomp in tree.decompositions:
        strategy = decomp.strategy.value

        if strategy == "assume_guarantee":
            sub_props = decomp.params.get("sub_properties", {})
            for sp_name in sub_props:
                lines.append(
                    f'  "{sp_name}" [shape=ellipse, label="{sp_name}"];'
                )
            for sp_name, sp_data in sub_props.items():
                for assumed in sp_data.get("assumes", []):
                    lines.append(
                        f'  "{sp_name}" -> "{assumed}" [label="assumes"];'
                    )

        elif strategy == "helper_invariant":
            target = decomp.params.get("target", decomp.target)
            for helper in decomp.params.get("helpers", []):
                lines.append(
                    f'  "{target}" -> "{helper}" [label="depends"];'
                )

        elif strategy == "case_split":
            for case in decomp.params.get("cases", []):
                cname = case["name"]
                lines.append(
                    f'  "{cname}" [shape=diamond, label="{cname}"];'
                )
                lines.append(
                    f'  "{decomp.target}" -> "{cname}" [label="case"];'
                )

        elif strategy == "partition":
            for part in decomp.params.get("partitions", []):
                pname = part["name"]
                lines.append(
                    f'  "{pname}" [shape=trapezium, label="{pname}"];'
                )
                lines.append(
                    f'  "{decomp.target}" -> "{pname}" [label="partition"];'
                )

        elif strategy == "stopat":
            depth = decomp.params.get("depth_limit", 0)
            node_name = f"{decomp.target}_stopat"
            lines.append(
                f'  "{node_name}" [shape=octagon, label="stopat@{depth}"];'
            )
            lines.append(
                f'  "{decomp.target}" -> "{node_name}" [label="stopat"];'
            )

    lines.append("}")
    _write_text("\n".join(lines), output_path)


def _output_json(spec: dict, filepath: str, output_path: str | None) -> None:
    """Generate JSON validation report."""
    report: dict = {
        "file": filepath,
        "valid": True,
        "decompositions": [],
        "schedule": None,
        "schedule_error": None,
    }

    try:
        tree = build_proof_tree(spec)
    except ValidationError as e:
        report["valid"] = False
        report["schedule_error"] = str(e)
        _write_text(json.dumps(report, indent=2, default=_serialize), output_path)
        return

    for i, decomp in enumerate(tree.decompositions):
        result = validate_decomposition(tree, i)
        entry = {
            "index": i,
            "target": decomp.target,
            "strategy": decomp.strategy.value,
            "valid": result.is_valid,
            "errors": result.errors,
            "details": result.details,
        }
        report["decompositions"].append(entry)
        if not result.is_valid:
            report["valid"] = False

    try:
        schedule = compute_schedule(tree)
        report["schedule"] = schedule
    except CyclicDependencyError as e:
        report["valid"] = False
        report["schedule"] = None
        report["schedule_error"] = str(e)

    _write_text(json.dumps(report, indent=2, default=_serialize), output_path)


def _output_obligations(spec: dict, filepath: str, output_path: str | None) -> None:
    """Generate proof obligations analysis report."""
    try:
        tree = build_proof_tree(spec)
    except ValidationError as e:
        report = {
            "file": filepath,
            "error": str(e),
            "decompositions": [],
            "cone_of_influence": {},
            "soundness": {
                "is_sound": False,
                "issues": [{
                    "severity": "error",
                    "description": str(e),
                    "affected_properties": [],
                }],
            },
        }
        _write_text(json.dumps(report, indent=2, default=_serialize), output_path)
        return

    decomps_output = []
    for i, decomp in enumerate(tree.decompositions):
        obls = generate_obligations(tree, i)
        decomps_output.append({
            "index": i,
            "strategy": decomp.strategy.value,
            "obligations": [
                {
                    "name": o.name,
                    "expression": o.expression,
                    "environment": o.environment,
                    "assumptions": o.assumptions,
                    "source_strategy": o.source_strategy,
                }
                for o in obls
            ],
        })

    coi_output = {}
    for pname in tree.properties:
        cone = compute_cone_of_influence(tree, pname)
        coi_output[pname] = {
            "structural_cone": cone.structural_cone,
            "sequential_depth": cone.sequential_depth,
            "boundary_signals": cone.boundary_signals,
        }

    soundness = check_compositional_soundness(tree)
    soundness_output = {
        "is_sound": soundness.is_sound,
        "issues": [
            {
                "severity": issue.severity,
                "description": issue.description,
                "affected_properties": issue.affected_properties,
            }
            for issue in soundness.issues
        ],
    }

    report = {
        "file": filepath,
        "decompositions": decomps_output,
        "cone_of_influence": coi_output,
        "soundness": soundness_output,
    }

    _write_text(json.dumps(report, indent=2, default=_serialize), output_path)


def _write_text(text: str, output_path: str | None) -> None:
    if output_path:
        with open(output_path, "w") as f:
            f.write(text + "\n")
    else:
        print(text)


def _serialize(obj: object) -> object:
    if isinstance(obj, set):
        return sorted(obj)
    return str(obj)


if __name__ == "__main__":
    main()
