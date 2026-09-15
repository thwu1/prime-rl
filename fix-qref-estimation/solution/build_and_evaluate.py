#!/usr/bin/env python3
"""Build two QREF v1 specifications for eigenvalue transformation variants,
compile, evaluate, compare, and find crossover points."""

import json

from bartiq import compile_routine, evaluate
from qref import SchemaV1


def build_qref(variant):
    """Build a complete QREF v1 JSON dict for variant A or B.

    The only difference is the select subroutine's resource expressions:
    - A: T_gates = 2*K*n (linear in both K and n), rotations = K
    - B: T_gates = 4*n*n + K (quadratic in n, linear in K), rotations = n
    """
    if variant == "A":
        select_resources = [
            {"name": "T_gates", "type": "additive", "value": "2*K*n"},
            {"name": "rotations", "type": "additive", "value": "K"},
        ]
    else:
        select_resources = [
            {"name": "T_gates", "type": "additive", "value": "4*n*n + K"},
            {"name": "rotations", "type": "additive", "value": "n"},
        ]

    return {
        "version": "v1",
        "program": {
            "name": "eigenvalue_transform",
            "type": None,
            "input_params": ["N", "K"],
            "local_variables": {
                "n": "ceiling(log2(N))",
                "k": "ceiling(log2(K))"
            },
            "children": [
                {
                    "name": "state_prep",
                    "type": None,
                    "input_params": ["N"],
                    "local_variables": {"n": "ceiling(log2(N))"},
                    "ports": [
                        {"name": "in_sys", "direction": "input", "size": "N"},
                        {"name": "out_sys", "direction": "output", "size": "N"}
                    ],
                    "resources": [
                        {"name": "T_gates", "type": "additive", "value": "4*n + 4*(N - 1)"},
                        {"name": "rotations", "type": "additive", "value": "2*n"}
                    ]
                },
                {
                    "name": "block_encoding",
                    "type": None,
                    "input_params": ["N", "K"],
                    "local_variables": {
                        "n": "ceiling(log2(N))",
                        "k": "ceiling(log2(K))"
                    },
                    "children": [
                        {
                            "name": "prepare",
                            "type": None,
                            "input_params": ["K"],
                            "local_variables": {"k": "ceiling(log2(K))"},
                            "ports": [
                                {"name": "in_0", "direction": "input", "size": "k"},
                                {"name": "out_0", "direction": "output", "size": "k"}
                            ],
                            "resources": [
                                {"name": "T_gates", "type": "additive", "value": "4*(k - 1)"},
                                {"name": "rotations", "type": "additive", "value": "k"}
                            ]
                        },
                        {
                            "name": "select",
                            "type": None,
                            "input_params": ["N", "K"],
                            "local_variables": {
                                "n": "ceiling(log2(N))",
                                "k": "ceiling(log2(K))"
                            },
                            "ports": [
                                {"name": "in_ctrl", "direction": "input", "size": "k"},
                                {"name": "in_sys", "direction": "input", "size": "N"},
                                {"name": "out_ctrl", "direction": "output", "size": "k"},
                                {"name": "out_sys", "direction": "output", "size": "N"}
                            ],
                            "resources": select_resources
                        },
                        {
                            "name": "unprepare",
                            "type": None,
                            "input_params": ["K"],
                            "local_variables": {"k": "ceiling(log2(K))"},
                            "ports": [
                                {"name": "in_0", "direction": "input", "size": "k"},
                                {"name": "out_0", "direction": "output", "size": "k"}
                            ],
                            "resources": [
                                {"name": "T_gates", "type": "additive", "value": "4*(k - 1)"},
                                {"name": "rotations", "type": "additive", "value": "k"}
                            ]
                        }
                    ],
                    "ports": [
                        {"name": "in_sys", "direction": "input", "size": "N"},
                        {"name": "in_anc", "direction": "input", "size": "k"},
                        {"name": "out_sys", "direction": "output", "size": None},
                        {"name": "out_anc", "direction": "output", "size": None}
                    ],
                    "connections": [
                        {"source": "in_anc", "target": "prepare.in_0"},
                        {"source": "prepare.out_0", "target": "select.in_ctrl"},
                        {"source": "in_sys", "target": "select.in_sys"},
                        {"source": "select.out_ctrl", "target": "unprepare.in_0"},
                        {"source": "select.out_sys", "target": "out_sys"},
                        {"source": "unprepare.out_0", "target": "out_anc"}
                    ],
                    "linked_params": [
                        {"source": "N", "targets": ["select.N"]},
                        {"source": "K", "targets": ["prepare.K", "select.K", "unprepare.K"]}
                    ]
                },
                {
                    "name": "signal_processing",
                    "type": None,
                    "input_params": ["N", "K"],
                    "local_variables": {
                        "n": "ceiling(log2(N))",
                        "k": "ceiling(log2(K))"
                    },
                    "ports": [
                        {"name": "in_sys", "direction": "input", "size": "N"},
                        {"name": "in_anc", "direction": "input", "size": "k"},
                        {"name": "out_sys", "direction": "output", "size": "N"},
                        {"name": "out_anc", "direction": "output", "size": "k"}
                    ],
                    "resources": [
                        {"name": "T_gates", "type": "additive", "value": "2*K*n"},
                        {"name": "rotations", "type": "additive", "value": "K + 1"}
                    ]
                }
            ],
            "ports": [
                {"name": "in_sys", "direction": "input", "size": "N"},
                {"name": "in_anc", "direction": "input", "size": "k"},
                {"name": "out_sys", "direction": "output", "size": None},
                {"name": "out_anc", "direction": "output", "size": None}
            ],
            "connections": [
                {"source": "in_sys", "target": "state_prep.in_sys"},
                {"source": "state_prep.out_sys", "target": "block_encoding.in_sys"},
                {"source": "in_anc", "target": "block_encoding.in_anc"},
                {"source": "block_encoding.out_sys", "target": "signal_processing.in_sys"},
                {"source": "block_encoding.out_anc", "target": "signal_processing.in_anc"},
                {"source": "signal_processing.out_sys", "target": "out_sys"},
                {"source": "signal_processing.out_anc", "target": "out_anc"}
            ],
            "linked_params": [
                {"source": "N", "targets": ["state_prep.N", "block_encoding.N", "signal_processing.N"]},
                {"source": "K", "targets": ["block_encoding.K", "signal_processing.K"]}
            ]
        }
    }


def main():
    # Build both variant specifications
    variant_a = build_qref("A")
    variant_b = build_qref("B")

    # Write QREF JSON files
    with open("/app/variant_a.json", "w") as f:
        json.dump(variant_a, f, indent=2)
    with open("/app/variant_b.json", "w") as f:
        json.dump(variant_b, f, indent=2)

    # Compile both variants
    schema_a = SchemaV1(**variant_a)
    schema_b = SchemaV1(**variant_b)
    compiled_a = compile_routine(schema_a)
    compiled_b = compile_routine(schema_b)

    print(f"Compiled A T_gates expression: {compiled_a.routine.resources['T_gates'].value}")
    print(f"Compiled B T_gates expression: {compiled_b.routine.resources['T_gates'].value}")

    # Evaluate for all parameter sets
    param_sets = [
        (8, 5), (8, 8), (8, 15),
        (32, 10), (32, 12), (32, 20),
        (64, 13), (64, 14), (64, 25),
    ]

    results = {"variant_a": {}, "variant_b": {}, "better_variant": {}, "crossover_k": {}}

    for N, K in param_sets:
        key = f"{N}_{K}"
        eval_a = evaluate(compiled_a.routine, {"N": N, "K": K})
        eval_b = evaluate(compiled_b.routine, {"N": N, "K": K})

        ta = int(eval_a.routine.resources["T_gates"].value)
        ra = int(eval_a.routine.resources["rotations"].value)
        tb = int(eval_b.routine.resources["T_gates"].value)
        rb = int(eval_b.routine.resources["rotations"].value)

        results["variant_a"][key] = {"t_gates": ta, "rotations": ra}
        results["variant_b"][key] = {"t_gates": tb, "rotations": rb}
        results["better_variant"][key] = "A" if ta < tb else "B"

        print(f"N={N}, K={K}: A(T={ta}, R={ra}) vs B(T={tb}, R={rb}) -> {results['better_variant'][key]}")

    # Find crossover K for each N
    for N in [8, 32, 64]:
        for K in range(2, 200):
            eval_a = evaluate(compiled_a.routine, {"N": N, "K": K})
            eval_b = evaluate(compiled_b.routine, {"N": N, "K": K})
            ta = int(eval_a.routine.resources["T_gates"].value)
            tb = int(eval_b.routine.resources["T_gates"].value)
            if tb < ta:
                results["crossover_k"][str(N)] = K
                print(f"Crossover for N={N}: K={K} (A_T={ta}, B_T={tb})")
                break

    # Write results
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("All output files written to /app/")


if __name__ == "__main__":
    main()
