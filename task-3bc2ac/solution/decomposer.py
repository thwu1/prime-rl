#!/usr/bin/env python3
"""
Region Decomposition Engine.

Parses pure Python functions, symbolically executes through all branches,
detects infeasible paths via Z3, and generates a region_checker module.
"""

import ast
import copy
import sys
import textwrap

from z3 import And, Int, Not, Or, Solver, sat


class VarSubstituter(ast.NodeTransformer):
    """Replace variable references with their bound expressions."""

    def __init__(self, env):
        self.env = env

    def visit_Name(self, node):
        if node.id in self.env:
            return copy.deepcopy(self.env[node.id])
        return node


def extract_paths(stmts, conditions=None, env=None):
    """Extract all execution paths as (conditions_list, return_expr) tuples.

    Walks through statements, branching at if/else, tracking variable
    assignments as substitutions.
    """
    if conditions is None:
        conditions = []
    if env is None:
        env = {}

    paths = []

    for stmt in stmts:
        if isinstance(stmt, ast.Return):
            sub = VarSubstituter(env)
            expr = sub.visit(copy.deepcopy(stmt.value))
            ast.fix_missing_locations(expr)
            paths.append((list(conditions), expr))
            return paths

        elif isinstance(stmt, ast.Assign):
            target = stmt.targets[0]
            if isinstance(target, ast.Name):
                sub = VarSubstituter(env)
                value = sub.visit(copy.deepcopy(stmt.value))
                ast.fix_missing_locations(value)
                env = dict(env)
                env[target.id] = value

        elif isinstance(stmt, ast.If):
            sub = VarSubstituter(env)
            cond = sub.visit(copy.deepcopy(stmt.test))
            ast.fix_missing_locations(cond)

            # True branch
            true_paths = extract_paths(
                stmt.body, conditions + [cond], dict(env)
            )
            paths.extend(true_paths)

            # False / elif branch
            if stmt.orelse:
                neg_cond = ast.UnaryOp(op=ast.Not(), operand=cond)
                ast.fix_missing_locations(neg_cond)
                false_paths = extract_paths(
                    stmt.orelse, conditions + [neg_cond], dict(env)
                )
                paths.extend(false_paths)

            return paths

    return paths


def ast_to_z3(node, z3_vars):
    """Convert a Python AST expression to a Z3 expression."""
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id in z3_vars:
            return z3_vars[node.id]
        raise ValueError(f"Unknown variable: {node.id}")

    if isinstance(node, ast.BinOp):
        left = ast_to_z3(node.left, z3_vars)
        right = ast_to_z3(node.right, z3_vars)
        op = node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.FloorDiv):
            return left / right
        if isinstance(op, ast.Mod):
            return left % right
        raise ValueError(f"Unsupported BinOp: {type(op).__name__}")

    if isinstance(node, ast.UnaryOp):
        operand = ast_to_z3(node.operand, z3_vars)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.Not):
            return Not(operand)
        if isinstance(node.op, ast.UAdd):
            return operand
        raise ValueError(f"Unsupported UnaryOp: {type(node.op).__name__}")

    if isinstance(node, ast.Compare):
        left = ast_to_z3(node.left, z3_vars)
        result = None
        curr = left
        for op, comparator in zip(node.ops, node.comparators):
            right = ast_to_z3(comparator, z3_vars)
            if isinstance(op, ast.Gt):
                cmp_expr = curr > right
            elif isinstance(op, ast.GtE):
                cmp_expr = curr >= right
            elif isinstance(op, ast.Lt):
                cmp_expr = curr < right
            elif isinstance(op, ast.LtE):
                cmp_expr = curr <= right
            elif isinstance(op, ast.Eq):
                cmp_expr = curr == right
            elif isinstance(op, ast.NotEq):
                cmp_expr = curr != right
            else:
                raise ValueError(f"Unsupported comparison: {type(op).__name__}")
            result = And(result, cmp_expr) if result is not None else cmp_expr
            curr = right
        return result

    if isinstance(node, ast.BoolOp):
        values = [ast_to_z3(v, z3_vars) for v in node.values]
        if isinstance(node.op, ast.And):
            return And(*values)
        if isinstance(node.op, ast.Or):
            return Or(*values)
        raise ValueError(f"Unsupported BoolOp: {type(node.op).__name__}")

    raise ValueError(f"Cannot convert {type(node).__name__}: {ast.dump(node)}")


def is_feasible(conditions, params):
    """Check if the conjunction of conditions is satisfiable using Z3."""
    z3_vars = {p: Int(p) for p in params}
    solver = Solver()
    for cond in conditions:
        try:
            z3_cond = ast_to_z3(cond, z3_vars)
            solver.add(z3_cond)
        except ValueError:
            # If conversion fails, conservatively treat as feasible
            return True
    return solver.check() == sat


def decompose_function(func_def):
    """Compute the region decomposition of a FunctionDef AST node.

    Returns (param_names, feasible_paths) where each feasible path is
    (conditions_list, return_expr_ast).
    """
    params = [arg.arg for arg in func_def.args.args]
    all_paths = extract_paths(func_def.body)
    feasible = [
        (conds, expr) for conds, expr in all_paths if is_feasible(conds, params)
    ]
    return params, feasible


def generate_region_checker(functions_path, output_path):
    """Parse all functions, compute decompositions, write region_checker.py."""
    with open(functions_path) as f:
        source = f.read()
    tree = ast.parse(source)

    func_defs = [
        node for node in ast.iter_child_nodes(tree)
        if isinstance(node, ast.FunctionDef)
    ]

    lines = ['"""Auto-generated region checker."""', ""]

    registry_info = {}  # func_name -> (params, n_regions)

    for func_def in func_defs:
        name = func_def.name
        params, feasible = decompose_function(func_def)
        registry_info[name] = (params, len(feasible))
        param_str = ", ".join(params)

        for i, (conditions, return_expr) in enumerate(feasible):
            # Generate check function
            if conditions:
                parts = [ast.unparse(c) for c in conditions]
                check_body = " and ".join(f"({p})" for p in parts)
            else:
                check_body = "True"

            lines.append(f"def _check_{name}_{i}({param_str}):")
            lines.append(f"    return {check_body}")
            lines.append("")

            # Generate evaluate function
            eval_body = ast.unparse(return_expr)
            lines.append(f"def _eval_{name}_{i}({param_str}):")
            lines.append(f"    return {eval_body}")
            lines.append("")

        print(f"{name}: {len(feasible)} feasible regions "
              f"(out of {len(extract_paths(func_def.body))} total paths)")

    # Build registry
    lines.append("_registry = {")
    for name, (params, n) in registry_info.items():
        entries = ", ".join(
            f'{{"check": _check_{name}_{i}, "evaluate": _eval_{name}_{i}}}'
            for i in range(n)
        )
        lines.append(f'    "{name}": [{entries}],')
    lines.append("}")
    lines.append("")

    # Interface functions
    lines.append("def num_regions(func_name):")
    lines.append('    return len(_registry[func_name])')
    lines.append("")
    lines.append("def check_region(func_name, region_idx, **kwargs):")
    lines.append('    return _registry[func_name][region_idx]["check"](**kwargs)')
    lines.append("")
    lines.append("def evaluate_region(func_name, region_idx, **kwargs):")
    lines.append('    return _registry[func_name][region_idx]["evaluate"](**kwargs)')
    lines.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\nWrote {output_path}")


if __name__ == "__main__":
    generate_region_checker("/app/functions.py", "/app/region_checker.py")
