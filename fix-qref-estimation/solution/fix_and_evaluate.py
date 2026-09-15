#!/usr/bin/env python3
"""Fix the six bugs in algorithm.json, compile, evaluate, and write analysis."""

import json
from bartiq import compile_routine, evaluate
from qref import SchemaV1


def find_child(node, name):
    """Find a child by name in a QREF program node."""
    for child in node.get("children", []):
        if child["name"] == name:
            return child
    return None


def find_linked_param(linked_params, source):
    """Find a linked_params entry by source name."""
    for lp in linked_params:
        if lp["source"] == source:
            return lp
    return None


def main():
    with open("/app/algorithm.json") as f:
        spec = json.load(f)

    bugs = []
    prog = spec["program"]
    walk = find_child(prog, "walk_operator")
    coin_flip = find_child(walk, "coin_flip")
    shift = find_child(walk, "shift")
    reflection = find_child(walk, "reflection")
    init = find_child(prog, "init_superposition")

    # Bug 1: coin_flip.in_coin port direction is "output" but should be "input"
    for port in coin_flip["ports"]:
        if port["name"] == "in_coin":
            port["direction"] = "input"
            break
    bugs.append({
        "description": "coin_flip.in_coin port direction was 'output' instead of 'input', causing topology verification failure",
        "location": "program.children[walk_operator].children[coin_flip].ports[in_coin].direction",
        "fix": "Changed direction from 'output' to 'input'"
    })

    # Bug 2: Root connections missing walk_operator.out_coin -> out_coin
    prog["connections"].append({
        "source": "walk_operator.out_coin",
        "target": "out_coin"
    })
    bugs.append({
        "description": "Missing root-level connection from walk_operator.out_coin to out_coin, leaving root output port dangling",
        "location": "program.connections",
        "fix": "Added connection {'source': 'walk_operator.out_coin', 'target': 'out_coin'}"
    })

    # Bug 3: init_superposition local variable n uses log2(N) instead of ceiling(log2(N))
    init["local_variables"]["n"] = "ceiling(log2(N))"
    bugs.append({
        "description": "init_superposition local variable 'n' was 'log2(N)' instead of 'ceiling(log2(N))', producing non-integer resource values for non-power-of-2 N",
        "location": "program.children[init_superposition].local_variables.n",
        "fix": "Changed from 'log2(N)' to 'ceiling(log2(N))'"
    })

    # Bug 4: reflection T_gates resource type is "other" instead of "additive"
    for res in reflection["resources"]:
        if res["name"] == "T_gates":
            res["type"] = "additive"
            break
    bugs.append({
        "description": "reflection T_gates resource type was 'other' instead of 'additive', preventing it from aggregating into parent routine's total T_gates count",
        "location": "program.children[walk_operator].children[reflection].resources[T_gates].type",
        "fix": "Changed type from 'other' to 'additive'"
    })

    # Bug 5: shift T_gates expression is "4*N + s" instead of "4*N*s"
    for res in shift["resources"]:
        if res["name"] == "T_gates":
            res["value"] = "4*N*s"
            break
    bugs.append({
        "description": "shift T_gates expression was '4*N + s' (addition) instead of '4*N*s' (multiplication), producing incorrect resource counts",
        "location": "program.children[walk_operator].children[shift].resources[T_gates].value",
        "fix": "Changed from '4*N + s' to '4*N*s'"
    })

    # Bug 6: walk_operator linked_params for S is missing shift.S target
    lp_s = find_linked_param(walk["linked_params"], "S")
    lp_s["targets"].append("shift.S")
    bugs.append({
        "description": "walk_operator linked_params for parameter S was missing 'shift.S' target, preventing S from propagating to the shift subroutine during compilation",
        "location": "program.children[walk_operator].linked_params[S].targets",
        "fix": "Added 'shift.S' to the targets list"
    })

    # Save fixed specification
    with open("/app/algorithm.json", "w") as f:
        json.dump(spec, f, indent=2)
    print("Fixed algorithm.json written")

    # Compile
    schema = SchemaV1(**spec)
    compiled = compile_routine(schema)
    print(f"Compiled T_gates: {compiled.routine.resources['T_gates'].value}")
    print(f"Compiled rotations: {compiled.routine.resources['rotations'].value}")

    # Evaluate for all parameter sets
    param_sets = [(16, 4), (24, 6), (48, 10), (100, 7), (200, 20), (500, 30)]
    evaluations = {}
    resource_product_sum = 0

    for N, S in param_sets:
        result = evaluate(compiled.routine, {"N": N, "S": S})
        t = int(result.routine.resources["T_gates"].value)
        r = int(result.routine.resources["rotations"].value)
        key = f"{N}_{S}"
        evaluations[key] = {"t_gates": t, "rotations": r}
        resource_product_sum += t * r
        print(f"N={N}, S={S}: T_gates={t}, rotations={r}")

    print(f"resource_product_sum = {resource_product_sum}")

    # Write analysis
    analysis = {
        "bugs": bugs,
        "evaluations": evaluations,
        "resource_product_sum": resource_product_sum,
    }
    with open("/app/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    print("analysis.json written")


if __name__ == "__main__":
    main()
