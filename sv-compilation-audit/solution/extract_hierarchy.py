#!/usr/bin/env python3
"""Extract module hierarchy from slang --ast-json output.

Traverses the AST JSON tree produced by slang and collects module
definitions with their ports and parameters into a structured report.
"""

import json
import sys


def extract_modules(node, seen=None):
    """Recursively extract module definitions from AST JSON."""
    if seen is None:
        seen = {}

    if not isinstance(node, dict):
        return seen

    kind = node.get("kind", "")

    # InstanceBody is the module definition inside an Instance
    if kind == "InstanceBody":
        name = node.get("name", "")
        if name and name not in seen:
            ports = []
            params = []
            for member in node.get("members", []):
                mk = member.get("kind", "")
                if mk == "Port":
                    ports.append({
                        "name": member.get("name", ""),
                        "direction": member.get("direction", ""),
                    })
                elif mk == "Parameter":
                    # Parameter value may be an int, string, or nested object
                    val = member.get("value", member.get("defaultValue", ""))
                    if isinstance(val, dict):
                        val = str(val.get("value", val))
                    params.append({
                        "name": member.get("name", ""),
                        "value": str(val),
                    })
            seen[name] = {
                "name": name,
                "ports": ports,
                "parameters": params,
            }

    # Recurse into children
    if "body" in node:
        extract_modules(node["body"], seen)
    for member in node.get("members", []):
        extract_modules(member, seen)

    return seen


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <ast_json_input> <report_output>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    with open(input_path) as f:
        ast = json.load(f)

    # The AST JSON has a top-level "design" key
    design = ast.get("design", ast)
    modules = extract_modules(design)

    report = {"modules": list(modules.values())}

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Extracted {len(modules)} modules: {list(modules.keys())}")


if __name__ == "__main__":
    main()
