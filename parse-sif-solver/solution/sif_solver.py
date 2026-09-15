#!/usr/bin/env python3

"""
SIF Format Parser and Numerical Optimization Solver.

Parses CUTEst Standard Input Format files, extracts the mathematical
optimization problem (objective, constraints, bounds, start point),
and solves using scipy.optimize.minimize with SLSQP.
"""

import glob
import json
import math
import os
import sys

import numpy as np
from scipy.optimize import minimize

# Namespace for evaluating SIF Fortran-like arithmetic expressions
EVAL_GLOBALS = {
    "__builtins__": {},
    "exp": math.exp, "EXP": math.exp,
    "sin": math.sin, "SIN": math.sin,
    "cos": math.cos, "COS": math.cos,
    "sqrt": math.sqrt, "SQRT": math.sqrt,
    "abs": abs, "ABS": abs,
    "log": math.log, "LOG": math.log,
}

# Known section headers in the data section of a SIF file
DATA_SECTIONS = {
    "VARIABLES", "GROUPS", "CONSTANTS", "BOUNDS", "START POINT",
    "ELEMENT TYPE", "ELEMENT USES", "GROUP TYPE", "GROUP USES",
    "OBJECT BOUND", "RANGES",
}


# ============================================================
# Field extraction from column-based SIF cards
# ============================================================

def extract_fields(line):
    """Extract indicator and six data fields from a SIF card.

    SIF uses fixed columns:
      indicator : cols 0-2
      field1    : cols 4-13
      field2    : cols 14-23
      field3    : cols 24-35
      field4    : cols 39-48
      field5    : cols 49-60
      field6    : cols 64-74
    """
    p = line.ljust(75)
    return (
        p[0:3].strip(),   # indicator
        p[4:14].strip(),  # field1
        p[14:24].strip(), # field2
        p[24:36].strip(), # field3
        p[39:49].strip(), # field4
        p[49:61].strip(), # field5
        p[64:75].strip(), # field6
    )


def extract_expr(line):
    """Extract arithmetic expression from cols 24+ of an F/G/H card."""
    return line[24:].strip() if len(line) > 24 else ""


# ============================================================
# Data structures
# ============================================================

class ElementType:
    """Blueprint for a nonlinear element function."""
    def __init__(self, name):
        self.name = name
        self.elemental_vars = []   # EV-declared variable names
        self.internal_vars = []    # IV-declared variable names
        self.r_matrix = {}         # {internal_var: {elemental_var: coeff}}
        self.f_expr = None         # Python-evaluatable expression string

    def evaluate(self, ev_values):
        local = dict(ev_values)
        for iv, mapping in self.r_matrix.items():
            local[iv] = sum(c * ev_values[e] for e, c in mapping.items())
        return float(eval(self.f_expr, EVAL_GLOBALS, local))


class GroupType:
    """Blueprint for a group transformation function."""
    def __init__(self, name):
        self.name = name
        self.f_expr = None

    def evaluate(self, gvar):
        return float(eval(self.f_expr, EVAL_GLOBALS, {"GVAR": gvar}))


class ElementInstance:
    """A concrete element: an ElementType bound to problem variables."""
    def __init__(self, name, type_name):
        self.name = name
        self.type_name = type_name
        self.var_mapping = {}  # {elemental_var_name: problem_var_name}


class Group:
    """An objective or constraint group."""
    def __init__(self, name, gtype):
        self.name = name
        self.gtype = gtype          # 'N','G','L','E'
        self.linear = {}            # {var_name: coefficient}
        self.scale = 1.0
        self.constant = 0.0
        self.elements = {}          # {element_instance_name: weight}
        self.group_type_name = None # name of GroupType, or None (identity)


class SIFProblem:
    """Complete parsed SIF problem."""
    def __init__(self):
        self.name = ""
        self.variables = []
        self.var_index = {}
        self.groups = {}           # ordered dict of Group
        self.element_types = {}
        self.group_types = {}
        self.elements = {}         # ElementInstance objects
        self.start_point = {}      # {var_name: value}
        self.default_lower = -1e20
        self.default_upper = 1e20
        self.lower_bounds = {}
        self.upper_bounds = {}
        self.default_group_type = None
        # Built after finalize()
        self.x0 = None
        self.bl = None
        self.bu = None

    # ---- finalize -------------------------------------------------

    def finalize(self):
        n = len(self.variables)
        self.x0 = np.zeros(n)
        for vn, val in self.start_point.items():
            if vn in self.var_index:
                self.x0[self.var_index[vn]] = val

        self.bl = np.full(n, self.default_lower)
        self.bu = np.full(n, self.default_upper)
        for vn, val in self.lower_bounds.items():
            if vn in self.var_index:
                self.bl[self.var_index[vn]] = val
        for vn, val in self.upper_bounds.items():
            if vn in self.var_index:
                self.bu[self.var_index[vn]] = val

        # Assign default group type where not explicitly set
        if self.default_group_type:
            for g in self.groups.values():
                if g.group_type_name is None:
                    g.group_type_name = self.default_group_type

    # ---- evaluation -----------------------------------------------

    def _eval_element(self, elem, x):
        etype = self.element_types[elem.type_name]
        ev_vals = {}
        for ev_name, pv_name in elem.var_mapping.items():
            ev_vals[ev_name] = x[self.var_index[pv_name]]
        return etype.evaluate(ev_vals)

    def _eval_group(self, group, x):
        # linear part
        lin = sum(c * x[self.var_index[v]] for v, c in group.linear.items())
        # element part
        elem = sum(w * self._eval_element(self.elements[en], x)
                   for en, w in group.elements.items())
        # argument = linear + elements - constant
        arg = lin + elem - group.constant
        # group function
        if group.group_type_name and group.group_type_name in self.group_types:
            result = self.group_types[group.group_type_name].evaluate(arg)
        else:
            result = arg
        # scale
        return result / group.scale

    def objective(self, x):
        return sum(self._eval_group(g, x)
                   for g in self.groups.values() if g.gtype == "N")

    def constraint_funcs(self):
        """Return list of scipy constraint dicts."""
        cons = []
        for g in self.groups.values():
            if g.gtype == "N":
                continue
            if g.gtype == "G":
                cons.append({"type": "ineq",
                             "fun": lambda x, _g=g: self._eval_group(_g, x)})
            elif g.gtype == "L":
                cons.append({"type": "ineq",
                             "fun": lambda x, _g=g: -self._eval_group(_g, x)})
            elif g.gtype == "E":
                cons.append({"type": "eq",
                             "fun": lambda x, _g=g: self._eval_group(_g, x)})
        return cons


# ============================================================
# Parser
# ============================================================

def _preprocess_lines(lines):
    """Extract IE parameters, expand DO/ND loops, strip comments."""
    int_params = {}
    clean = []
    for line in lines:
        raw = line.rstrip("\n")
        if len(raw) >= 3 and raw[1:3] == "IE":
            _, f1, f2, f3, *_ = extract_fields(raw)
            val_str = f3 if f3 else f2
            int_params[f1] = int(val_str)
        else:
            clean.append(raw)

    # Expand DO / ND loops (single nesting level)
    expanded = []
    i = 0
    while i < len(clean):
        line = clean[i]
        ind = line[0:3].strip() if len(line) >= 3 else ""
        if ind == "DO":
            _, loop_var, start_p, _, end_p, *_ = extract_fields(line)
            lo = int_params.get(start_p, int(start_p) if start_p.lstrip("-").isdigit() else 0)
            hi = int_params.get(end_p, int(end_p) if end_p.lstrip("-").isdigit() else 0)
            body = []
            i += 1
            while i < len(clean):
                if clean[i].strip().startswith("ND"):
                    break
                body.append(clean[i])
                i += 1
            for val in range(lo, hi + 1):
                for bline in body:
                    expanded.append(bline.replace(f"({loop_var})", str(val)))
        else:
            expanded.append(line)
        i += 1
    return expanded


def parse_sif(filename):
    with open(filename) as f:
        raw = f.read()

    # Split by ENDATA into sections
    parts = raw.split("ENDATA")
    data_text = parts[0]
    elem_func_text = parts[1] if len(parts) > 1 else ""
    group_func_text = parts[2] if len(parts) > 2 else ""

    prob = SIFProblem()

    # ---- Parse data section ----
    lines = _preprocess_lines(data_text.split("\n"))
    section = None
    for line in lines:
        s = line.strip()
        if not s or s.startswith("*"):
            continue
        if s.startswith("NAME"):
            prob.name = s[4:].strip()
            # Also try column-based extraction
            if not prob.name:
                _, f1, f2, *_ = extract_fields(line)
                prob.name = f2 if f2 else f1
            continue
        if s in DATA_SECTIONS:
            section = s
            continue

        ind, f1, f2, f3, f4, f5, f6 = extract_fields(line)

        # -- VARIABLES --
        if section == "VARIABLES":
            vn = f1
            if vn and vn not in prob.var_index:
                prob.var_index[vn] = len(prob.variables)
                prob.variables.append(vn)

        # -- GROUPS --
        elif section == "GROUPS":
            if ind in ("N", "G", "L", "E"):
                gn = f1
                if gn not in prob.groups:
                    prob.groups[gn] = Group(gn, ind)
                grp = prob.groups[gn]
                if f2 == "'SCALE'" and f3:
                    grp.scale = float(f3)
                elif f2 and f3:
                    grp.linear[f2] = grp.linear.get(f2, 0.0) + float(f3)
                    if f4 and f5:
                        grp.linear[f4] = grp.linear.get(f4, 0.0) + float(f5)
                # Group with no linear terms (e.g. " G  C1")
                # already created above

        # -- CONSTANTS --
        elif section == "CONSTANTS":
            # f1=probname, f2=groupname, f3=value
            if f2 and f3 and f2 in prob.groups:
                prob.groups[f2].constant = float(f3)

        # -- BOUNDS --
        elif section == "BOUNDS":
            if f2 == "'DEFAULT'":
                if ind == "LO":
                    prob.default_lower = float(f3)
                elif ind == "UP":
                    prob.default_upper = float(f3)
                elif ind == "FR":
                    prob.default_lower = -1e20
                    prob.default_upper = 1e20
            elif f2:
                if ind == "LO":
                    prob.lower_bounds[f2] = float(f3)
                elif ind == "UP":
                    prob.upper_bounds[f2] = float(f3)
                elif ind == "FR":
                    prob.lower_bounds[f2] = -1e20
                    prob.upper_bounds[f2] = 1e20
                elif ind == "FX":
                    prob.lower_bounds[f2] = float(f3)
                    prob.upper_bounds[f2] = float(f3)

        # -- START POINT --
        elif section == "START POINT":
            # f1=probname, f2=varname, f3=value
            if f2 and f3:
                prob.start_point[f2] = float(f3)

        # -- ELEMENT TYPE --
        elif section == "ELEMENT TYPE":
            if ind == "EV":
                if f1 not in prob.element_types:
                    prob.element_types[f1] = ElementType(f1)
                et = prob.element_types[f1]
                if f2 and f2 not in et.elemental_vars:
                    et.elemental_vars.append(f2)
                if f4 and f4 not in et.elemental_vars:
                    et.elemental_vars.append(f4)
            elif ind == "IV":
                if f1 not in prob.element_types:
                    prob.element_types[f1] = ElementType(f1)
                et = prob.element_types[f1]
                if f2 and f2 not in et.internal_vars:
                    et.internal_vars.append(f2)
                if f4 and f4 not in et.internal_vars:
                    et.internal_vars.append(f4)

        # -- ELEMENT USES --
        elif section == "ELEMENT USES":
            if ind == "T":
                prob.elements[f1] = ElementInstance(f1, f2)
            elif ind in ("V", "ZV"):
                if f1 in prob.elements:
                    prob.elements[f1].var_mapping[f2] = f4

        # -- GROUP TYPE --
        elif section == "GROUP TYPE":
            if ind == "GV":
                if f1 not in prob.group_types:
                    prob.group_types[f1] = GroupType(f1)

        # -- GROUP USES --
        elif section == "GROUP USES":
            if ind == "T":
                if f1 == "'DEFAULT'":
                    prob.default_group_type = f2
                elif f1 in prob.groups:
                    prob.groups[f1].group_type_name = f2
            elif ind in ("E", "XE", "ZE"):
                if f1 in prob.groups:
                    grp = prob.groups[f1]
                    weight = float(f3) if f3 else 1.0
                    grp.elements[f2] = weight
                    if f4:
                        w2 = float(f5) if f5 else 1.0
                        grp.elements[f4] = w2

    # ---- Parse element function definitions ----
    if elem_func_text.strip():
        _parse_func_section(elem_func_text, prob.element_types, kind="element")

    # ---- Parse group function definitions ----
    if group_func_text.strip():
        _parse_func_section(group_func_text, prob.group_types, kind="group")

    prob.finalize()
    return prob


def _parse_func_section(text, type_dict, kind="element"):
    """Parse ELEMENTS or GROUPS function-definition section."""
    current = None
    for line in text.split("\n"):
        s = line.strip()
        if not s or s.startswith("*"):
            continue
        # Skip section headers
        if s.startswith("ELEMENTS") or s.startswith("GROUPS") or s == "INDIVIDUALS":
            continue

        ind, f1, f2, f3, f4, f5, f6 = extract_fields(line)

        if ind == "T":
            current = f1
            # Ensure type object exists
            if current not in type_dict:
                if kind == "element":
                    type_dict[current] = ElementType(current)
                else:
                    type_dict[current] = GroupType(current)

        elif ind == "R" and current and kind == "element":
            et = type_dict[current]
            if f1 not in et.r_matrix:
                et.r_matrix[f1] = {}
            if f2 and f3:
                et.r_matrix[f1][f2] = float(f3)
            if f4 and f5:
                et.r_matrix[f1][f4] = float(f5)

        elif ind == "F" and current:
            expr = extract_expr(line)
            if expr:
                type_dict[current].f_expr = expr

        # G and H cards are skipped (not needed for function evaluation)


# ============================================================
# Solver
# ============================================================

def solve_problem(prob):
    """Solve a parsed SIF problem with scipy."""
    n = len(prob.variables)

    # Bounds for scipy (None = unbounded)
    bounds = []
    for i in range(n):
        lo = prob.bl[i] if prob.bl[i] > -1e19 else None
        hi = prob.bu[i] if prob.bu[i] < 1e19 else None
        bounds.append((lo, hi))

    constraints = prob.constraint_funcs()

    # Try SLSQP first (handles bounds + constraints well)
    best_result = None
    for method in ["SLSQP"]:
        try:
            res = minimize(
                prob.objective,
                prob.x0,
                method=method,
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 2000, "ftol": 1e-12},
            )
            if best_result is None or res.fun < best_result.fun:
                best_result = res
        except Exception:
            pass

    # If SLSQP didn't converge well, try trust-constr for constrained problems
    if constraints and (best_result is None or not best_result.success):
        try:
            from scipy.optimize import NonlinearConstraint
            # Fallback: try trust-constr
            res2 = minimize(
                prob.objective,
                prob.x0,
                method="trust-constr",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 3000},
            )
            if best_result is None or res2.fun < best_result.fun:
                best_result = res2
        except Exception:
            pass

    if best_result is None:
        raise RuntimeError(f"Failed to solve problem {prob.name}")

    return {
        "optimal_value": float(best_result.fun),
        "optimal_point": best_result.x.tolist(),
    }


# ============================================================
# Main
# ============================================================

def main():
    results = {}
    sif_files = sorted(glob.glob("/app/problems/*.SIF"))
    if not sif_files:
        print("No .SIF files found in /app/problems/", file=sys.stderr)
        sys.exit(1)

    for sif_path in sif_files:
        name = os.path.basename(sif_path)
        print(f"Parsing {name} ...")
        prob = parse_sif(sif_path)
        print(f"  Problem: {prob.name}, n={len(prob.variables)}, "
              f"constraints={sum(1 for g in prob.groups.values() if g.gtype != 'N')}")
        print(f"  Start: {prob.x0}")
        print(f"Solving {prob.name} ...")
        result = solve_problem(prob)
        print(f"  f* = {result['optimal_value']:.8f}")
        print(f"  x* = {result['optimal_point']}")
        results[prob.name] = result

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to /app/results.json ({len(results)} problems)")


if __name__ == "__main__":
    main()
