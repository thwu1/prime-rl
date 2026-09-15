#!/usr/bin/env python3
"""
Two-phase flow boiling analysis engine — reference solution.

Uses CalebBell/fluids and CalebBell/ht libraries for all VDI Heat Atlas
correlations (Friedel, Gronnerud, Chisholm, Chen-Bennett, Gorenflo, etc.).
"""
import json

from fluids.two_phase import Friedel, Gronnerud, Chisholm
from fluids.two_phase_voidage import (
    homogeneous,
    Thom,
    Lockhart_Martinelli_Xtt,
)
from ht.boiling_flow import Chen_Bennett
from ht.boiling_nucleic import Gorenflo


def process_case(case):
    """Dispatch a single case to the appropriate correlation."""
    case_type = case["type"]
    method = case.get("method", "")
    params = case["params"]

    if case_type == "pressure_drop":
        fn_map = {
            "Friedel": Friedel,
            "Gronnerud": Gronnerud,
            "Chisholm": Chisholm,
        }
        if method not in fn_map:
            raise ValueError(f"Unknown pressure drop method: {method}")
        return {"dP": fn_map[method](**params)}

    elif case_type == "void_fraction":
        x = params["x"]
        rhol = params["rhol"]
        rhog = params["rhog"]
        mul = params["mul"]
        mug = params["mug"]
        return {
            "homogeneous": homogeneous(x, rhol, rhog),
            "thom": Thom(x, rhol, rhog, mul, mug),
            "xtt": Lockhart_Martinelli_Xtt(x, rhol, rhog, mul, mug),
        }

    elif case_type == "flow_boiling":
        if method == "Chen_Bennett":
            return {"h": Chen_Bennett(**params)}
        raise ValueError(f"Unknown flow boiling method: {method}")

    elif case_type == "pool_boiling":
        if method == "Gorenflo":
            gorenflo_params = {k: v for k, v in params.items() if k != "cas"}
            gorenflo_params["CASRN"] = params["cas"]
            return {"h": Gorenflo(**gorenflo_params)}
        raise ValueError(f"Unknown pool boiling method: {method}")

    else:
        raise ValueError(f"Unknown case type: {case_type}")


def main():
    with open("/app/conditions.json") as f:
        cases = json.load(f)

    results = {}
    for case in cases:
        results[case["id"]] = process_case(case)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
