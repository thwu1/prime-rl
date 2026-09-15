#!/usr/bin/env python3

"""
SIF format parser and nonlinear optimization solver for CUTEst problems.

Parses the Standard Input Format (SIF) used by the CUTEst test collection,
builds callable objective/constraint functions from the compositional
element-group structure, and solves using scipy.optimize.

Handles: VARIABLES (with DO loops), GROUPS (N/G/L/E types, SCALE),
CONSTANTS, BOUNDS, START POINT, ELEMENT TYPE (EV/IV), ELEMENT USES,
GROUP TYPE, GROUP USES, ELEMENTS section (R/F cards), GROUPS section (F cards).
"""

import json
import os
import re
import sys
import math
import numpy as np
from scipy.optimize import minimize


# ---------------------------------------------------------------------------
# SIF Parser
# ---------------------------------------------------------------------------

def parse_sif(filepath):
    """Parse a complete SIF file into a structured problem dict."""
    with open(filepath) as f:
        content = f.read()

    # Split into ENDATA-delimited sections
    raw_parts = content.split("ENDATA")

    prob = {
        "name": "",
        "int_params": {},
        "variables": [],
        "groups": {},
        "constants": {},
        "bounds_lo": {},
        "bounds_up": {},
        "default_lo": -1e20,
        "default_up": 1e20,
        "start": {},
        "elem_types": {},
        "elem_uses": {},
        "group_types": {},
        "group_type_map": {},
        "default_group_type": None,
        "elem_funcs": {},
        "group_funcs": {},
    }

    _parse_data(raw_parts[0], prob)

    for part in raw_parts[1:]:
        stripped = part.strip()
        if not stripped:
            continue
        if re.search(r"^ELEMENTS\s", stripped, re.MULTILINE):
            _parse_elem_defs(stripped, prob)
        elif re.search(r"^GROUPS\s", stripped, re.MULTILINE):
            _parse_group_defs(stripped, prob)

    return prob


def _fields(line):
    return line.split()


def _resolve_int(s, prob):
    try:
        return int(s)
    except ValueError:
        return prob["int_params"].get(s, 0)


def _expand(name, prob):
    m = re.match(r"(\w+)\((\w+)\)", name)
    if m:
        return f"{m.group(1)}{prob['int_params'].get(m.group(2), m.group(2))}"
    return name


def _parse_data(text, prob):
    lines = text.split("\n")
    section = None
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue

        # Section indicators
        if stripped.startswith("NAME"):
            parts = stripped.split()
            if len(parts) >= 2:
                prob["name"] = parts[1]
            continue
        if stripped == "VARIABLES":
            section = "VARIABLES"; continue
        if stripped == "GROUPS":
            section = "GROUPS"; continue
        if stripped == "CONSTANTS":
            section = "CONSTANTS"; continue
        if stripped.startswith("BOUNDS"):
            section = "BOUNDS"; continue
        if stripped.startswith("START POINT"):
            section = "START"; continue
        if stripped == "ELEMENT TYPE":
            section = "ETYPE"; continue
        if stripped == "ELEMENT USES":
            section = "EUSES"; continue
        if stripped == "GROUP TYPE":
            section = "GTYPE"; continue
        if stripped == "GROUP USES":
            section = "GUSES"; continue
        if stripped.startswith("OBJECT BOUND"):
            section = "OBJBOUND"; continue

        f = _fields(line)
        if not f:
            continue

        # Parameter cards
        if f[0] == "IE":
            prob["int_params"][f[1]] = int(f[2])
            continue
        if f[0] == "IM":
            prob["int_params"][f[1]] = prob["int_params"][f[2]] * int(f[3])
            continue
        if f[0] == "IA":
            prob["int_params"][f[1]] = prob["int_params"].get(f[2], int(f[2])) + int(f[3])
            continue
        if f[0] == "RE":
            continue

        # DO loops
        if f[0] == "DO":
            var = f[1]
            start_v = _resolve_int(f[2], prob)
            end_v = _resolve_int(f[3], prob)
            body = []
            depth = 1
            while i < len(lines):
                ll = lines[i].strip()
                if ll == "ND":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                elif ll.startswith("DO "):
                    depth += 1
                body.append(lines[i])
                i += 1
            for val in range(start_v, end_v + 1):
                prob["int_params"][var] = val
                for bl in body:
                    _process_line(bl, section, prob)
            continue

        _process_line(line, section, prob)


def _process_line(line, section, prob):
    f = _fields(line)
    if not f or f[0].startswith("*"):
        return

    # Parameter cards inside loops
    if f[0] == "IE":
        prob["int_params"][f[1]] = int(f[2]); return
    if f[0] == "IM":
        prob["int_params"][f[1]] = prob["int_params"][f[2]] * int(f[3]); return
    if f[0] == "IA":
        prob["int_params"][f[1]] = prob["int_params"].get(f[2], int(f[2])) + int(f[3]); return

    if section == "VARIABLES":
        if f[0] in ("X", "XT"):
            name = _expand(f[1], prob)
        elif len(f) == 1 and f[0] not in ("DO", "ND"):
            name = _expand(f[0], prob)
        else:
            return
        if name not in prob["variables"]:
            prob["variables"].append(name)

    elif section == "GROUPS":
        _parse_group_line(f, prob)

    elif section == "CONSTANTS":
        if len(f) >= 3:
            if f[0] == "X":
                grp, val = f[2], float(f[3])
            else:
                grp, val = f[1], float(f[2])
            prob["constants"][grp] = val

    elif section == "BOUNDS":
        _parse_bound_line(f, prob)

    elif section == "START":
        if len(f) >= 3:
            if f[0] in ("XV", "X"):
                var = _expand(f[2], prob)
                val = float(f[3])
            else:
                var = _expand(f[1], prob)
                val = float(f[2])
            prob["start"][var] = val

    elif section == "ETYPE":
        _parse_etype_line(f, prob)

    elif section == "EUSES":
        _parse_euses_line(f, prob)

    elif section == "GTYPE":
        if f[0] == "GV":
            prob["group_types"][f[1]] = {"gvar": f[2]}

    elif section == "GUSES":
        _parse_guses_line(f, prob)


def _parse_group_line(f, prob):
    gtype = f[0]
    if gtype not in ("N", "G", "L", "E", "XN", "ZN", "XG", "ZG", "XL", "ZL", "XE", "ZE"):
        return
    ctype = gtype[-1]
    name = _expand(f[1], prob)

    if name not in prob["groups"]:
        prob["groups"][name] = {
            "type": ctype, "linear": {}, "scale": 1.0, "elements": []
        }

    j = 2
    while j < len(f):
        if f[j] == "'SCALE'":
            if j + 1 < len(f):
                try:
                    prob["groups"][name]["scale"] = float(f[j + 1])
                except ValueError:
                    pass
            j += 2
        elif j + 1 < len(f):
            var = _expand(f[j], prob)
            try:
                coeff = float(f[j + 1])
            except ValueError:
                j += 1
                continue
            prob["groups"][name]["linear"][var] = \
                prob["groups"][name]["linear"].get(var, 0.0) + coeff
            j += 2
        else:
            j += 1


def _parse_bound_line(f, prob):
    bt = f[0]
    if bt == "FR":
        var = f[2] if len(f) > 2 else None
        if var == "'DEFAULT'":
            prob["default_lo"] = -1e20
            prob["default_up"] = 1e20
        elif var:
            v = _expand(var, prob)
            prob["bounds_lo"][v] = -1e20
            prob["bounds_up"][v] = 1e20
    elif bt == "LO":
        var = f[2] if len(f) > 2 else None
        val = float(f[3]) if len(f) > 3 else 0.0
        if var == "'DEFAULT'":
            prob["default_lo"] = val
        elif var:
            prob["bounds_lo"][_expand(var, prob)] = val
    elif bt == "UP":
        var = f[2] if len(f) > 2 else None
        val = float(f[3]) if len(f) > 3 else 0.0
        if var == "'DEFAULT'":
            prob["default_up"] = val
        elif var:
            prob["bounds_up"][_expand(var, prob)] = val
    elif bt in ("FX", "XX"):
        if len(f) > 3:
            v = _expand(f[2], prob)
            val = float(f[3])
            prob["bounds_lo"][v] = val
            prob["bounds_up"][v] = val


def _parse_etype_line(f, prob):
    if f[0] == "EV":
        t = f[1]
        if t not in prob["elem_types"]:
            prob["elem_types"][t] = {"ev": [], "iv": [], "params": []}
        for v in f[2:]:
            if v and v not in prob["elem_types"][t]["ev"]:
                prob["elem_types"][t]["ev"].append(v)
    elif f[0] == "IV":
        t = f[1]
        if t not in prob["elem_types"]:
            prob["elem_types"][t] = {"ev": [], "iv": [], "params": []}
        for v in f[2:]:
            if v and v not in prob["elem_types"][t]["iv"]:
                prob["elem_types"][t]["iv"].append(v)
    elif f[0] == "EP":
        t = f[1]
        if t not in prob["elem_types"]:
            prob["elem_types"][t] = {"ev": [], "iv": [], "params": []}
        for v in f[2:]:
            if v and v not in prob["elem_types"][t]["params"]:
                prob["elem_types"][t]["params"].append(v)


def _parse_euses_line(f, prob):
    if f[0] in ("T", "XT"):
        ename = _expand(f[1], prob)
        prob["elem_uses"][ename] = {"type": f[2], "var_map": {}, "params": {}}
    elif f[0] in ("V", "ZV"):
        ename = _expand(f[1], prob)
        tvar = f[2]
        pvar = _expand(f[3], prob)
        if ename in prob["elem_uses"]:
            prob["elem_uses"][ename]["var_map"][tvar] = pvar
    elif f[0] in ("P", "ZP"):
        ename = _expand(f[1], prob)
        pname = f[2]
        try:
            val = float(f[3])
        except (ValueError, IndexError):
            val = 0.0
        if ename in prob["elem_uses"]:
            prob["elem_uses"][ename]["params"][pname] = val


def _parse_guses_line(f, prob):
    if f[0] in ("T", "XT"):
        gname = _expand(f[1], prob)
        tname = f[2]
        if gname == "'DEFAULT'":
            prob["default_group_type"] = tname
        else:
            prob["group_type_map"][gname] = tname
    elif f[0] in ("E", "XE", "ZE"):
        gname = _expand(f[1], prob)
        if gname not in prob["groups"]:
            return
        j = 2
        while j < len(f):
            ename = _expand(f[j], prob)
            coeff = 1.0
            if j + 1 < len(f):
                try:
                    coeff = float(f[j + 1])
                    j += 2
                except ValueError:
                    j += 1
            else:
                j += 1
            prob["groups"][gname]["elements"].append((ename, coeff))


# --- ELEMENTS and GROUPS definition sections ---

def _parse_elem_defs(text, prob):
    cur_type = None
    transforms = {}
    func_expr = None
    for line in text.split("\n"):
        s = line.strip()
        if not s or s.startswith("*") or s.startswith("ELEMENTS") or s == "INDIVIDUALS":
            continue
        if s.startswith("TEMPORARIES"):
            continue
        f = _fields(line)
        if not f:
            continue
        if f[0] == "T":
            if cur_type and func_expr:
                prob["elem_funcs"][cur_type] = {
                    "transforms": dict(transforms), "expr": func_expr
                }
            cur_type = f[1]
            transforms = {}
            func_expr = None
        elif f[0] == "R":
            iv = f[1]
            if iv not in transforms:
                transforms[iv] = {}
            j = 2
            while j + 1 < len(f):
                ev = f[j]
                coeff = float(f[j + 1])
                transforms[iv][ev] = transforms[iv].get(ev, 0.0) + coeff
                j += 2
        elif f[0] == "F":
            func_expr = " ".join(f[1:])
        elif f[0] in ("A", "M", "G", "H"):
            pass  # temporaries, externals, gradient, hessian - skip
    if cur_type and func_expr:
        prob["elem_funcs"][cur_type] = {
            "transforms": dict(transforms), "expr": func_expr
        }


def _parse_group_defs(text, prob):
    cur_type = None
    func_expr = None
    for line in text.split("\n"):
        s = line.strip()
        if not s or s.startswith("*") or s.startswith("GROUPS") or s == "INDIVIDUALS":
            continue
        f = _fields(line)
        if not f:
            continue
        if f[0] == "T":
            if cur_type and func_expr:
                prob["group_funcs"][cur_type] = func_expr
            cur_type = f[1]
            func_expr = None
        elif f[0] == "F":
            func_expr = " ".join(f[1:])
    if cur_type and func_expr:
        prob["group_funcs"][cur_type] = func_expr


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

def _eval_expr(expr, variables):
    """Evaluate a simple SIF mathematical expression."""
    safe = {"__builtins__": {}, "math": math}
    safe.update(variables)
    return float(eval(expr, safe))


def eval_element(prob, ename, x_dict):
    """Evaluate a single element instance."""
    eu = prob["elem_uses"][ename]
    etype = eu["type"]
    finfo = prob["elem_funcs"].get(etype)
    if not finfo:
        return 0.0

    # Map problem vars -> elemental vars
    ev_vals = {}
    for tvar, pvar in eu["var_map"].items():
        ev_vals[tvar] = x_dict.get(pvar, 0.0)

    # Apply internal variable transforms if any
    transforms = finfo.get("transforms", {})
    if transforms:
        iv_vals = {}
        for iv, mapping in transforms.items():
            iv_vals[iv] = sum(c * ev_vals.get(ev, 0.0) for ev, c in mapping.items())
        eval_vars = iv_vals
    else:
        eval_vars = ev_vals

    # Add parameters
    for pn, pv in eu.get("params", {}).items():
        eval_vars[pn] = pv

    return _eval_expr(finfo["expr"], eval_vars)


def eval_group(prob, gname, x_dict):
    """Evaluate a single group (objective term or constraint)."""
    grp = prob["groups"][gname]

    # Group argument = linear terms + element terms - constant
    g = 0.0
    for var, coeff in grp["linear"].items():
        g += coeff * x_dict.get(var, 0.0)
    for ename, coeff in grp["elements"]:
        g += coeff * eval_element(prob, ename, x_dict)
    g -= prob["constants"].get(gname, 0.0)

    # Apply group type function
    gt = prob["group_type_map"].get(gname, prob.get("default_group_type"))
    if gt and gt in prob["group_funcs"]:
        gvar = prob["group_types"][gt]["gvar"]
        g = _eval_expr(prob["group_funcs"][gt], {gvar: g})

    # Apply scale (SIF scale divides the group argument before applying the function,
    # but for L2-type groups the equivalent is dividing the result)
    scale = grp.get("scale", 1.0)
    if scale != 1.0:
        g /= scale

    return g


def _x_dict(prob, x):
    return {var: x[i] for i, var in enumerate(prob["variables"])}


def objective(prob, x):
    xd = _x_dict(prob, x)
    return sum(
        eval_group(prob, gn, xd)
        for gn, gi in prob["groups"].items()
        if gi["type"] == "N"
    )


def get_constraint_groups(prob):
    return [(gn, gi) for gn, gi in prob["groups"].items() if gi["type"] in ("G", "L", "E")]


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def solve_problem(prob):
    n = len(prob["variables"])

    # Starting point
    x0 = np.array([prob["start"].get(v, 0.0) for v in prob["variables"]])

    # Bounds
    bounds = [
        (prob["bounds_lo"].get(v, prob["default_lo"]),
         prob["bounds_up"].get(v, prob["default_up"]))
        for v in prob["variables"]
    ]

    obj_fn = lambda x: objective(prob, x)

    # Constraints
    con_groups = get_constraint_groups(prob)
    scipy_cons = []
    for gn, gi in con_groups:
        if gi["type"] == "G":
            scipy_cons.append({
                "type": "ineq",
                "fun": (lambda x, _gn=gn: eval_group(prob, _gn, _x_dict(prob, x)))
            })
        elif gi["type"] == "L":
            scipy_cons.append({
                "type": "ineq",
                "fun": (lambda x, _gn=gn: -eval_group(prob, _gn, _x_dict(prob, x)))
            })
        elif gi["type"] == "E":
            scipy_cons.append({
                "type": "eq",
                "fun": (lambda x, _gn=gn: eval_group(prob, _gn, _x_dict(prob, x)))
            })

    if scipy_cons:
        res = minimize(obj_fn, x0, method="SLSQP",
                       bounds=bounds, constraints=scipy_cons,
                       options={"maxiter": 2000, "ftol": 1e-12})
        # Retry with midpoint start if first attempt failed
        if not res.success or np.isnan(res.fun):
            x0_alt = np.array([
                0.5 * (b[0] + b[1]) if b[0] > -1e19 and b[1] < 1e19 else 0.0
                for b in bounds
            ])
            res2 = minimize(obj_fn, x0_alt, method="SLSQP",
                            bounds=bounds, constraints=scipy_cons,
                            options={"maxiter": 2000, "ftol": 1e-12})
            if res2.success and (np.isnan(res.fun) or res2.fun < res.fun):
                res = res2
    else:
        all_free = all(b[0] <= -1e19 and b[1] >= 1e19 for b in bounds)
        if all_free:
            res = minimize(obj_fn, x0, method="BFGS",
                           options={"maxiter": 5000, "gtol": 1e-10})
            res2 = minimize(obj_fn, x0, method="Nelder-Mead",
                            options={"maxiter": 20000, "xatol": 1e-10, "fatol": 1e-14})
            if res2.fun < res.fun:
                res = res2
        else:
            res = minimize(obj_fn, x0, method="L-BFGS-B",
                           bounds=bounds,
                           options={"maxiter": 5000, "ftol": 1e-14})

    return {
        "name": prob["name"],
        "optimal_value": float(res.fun),
        "solution": res.x.tolist(),
        "n_vars": n,
        "n_constraints": len(con_groups),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Try /data/problems first (safe location), then /app/problems as fallback
    problems_dir = "/data/problems"
    if not os.path.isdir(problems_dir) or not any(
        f.endswith(".SIF") for f in os.listdir(problems_dir)
    ):
        problems_dir = "/app/problems"

    if not os.path.isdir(problems_dir):
        print(f"ERROR: Problems directory not found: {problems_dir}", file=sys.stderr)
        sys.exit(1)

    sif_files = sorted(f for f in os.listdir(problems_dir) if f.endswith(".SIF"))
    if not sif_files:
        print(f"ERROR: No .SIF files found in {problems_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(sif_files)} SIF files in {problems_dir}", flush=True)

    results = {"problems": []}
    for sif_file in sif_files:
        path = os.path.join(problems_dir, sif_file)
        print(f"Parsing {sif_file}...", flush=True)
        prob = parse_sif(path)
        print(f"  Name: {prob['name']}, vars: {len(prob['variables'])}, "
              f"constraints: {len(get_constraint_groups(prob))}", flush=True)
        print(f"Solving {prob['name']}...", flush=True)
        result = solve_problem(prob)
        print(f"  Optimal value: {result['optimal_value']:.8f}", flush=True)
        print(f"  Solution: {result['solution']}", flush=True)
        results["problems"].append(result)

    out_path = "/app/results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {out_path}", flush=True)


if __name__ == "__main__":
    main()
