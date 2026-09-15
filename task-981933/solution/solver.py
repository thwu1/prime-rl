#!/usr/bin/env python3

"""
XCSP3-core constraint solver.
Parses XCSP3 XML instances and solves CSP/COP problems using
backtracking search with forward checking and branch-and-bound.
"""

import xml.etree.ElementTree as ET
import json
import os
import re


def parse_domain(domain_str):
    """Parse domain string like '1..9' or '0 1' into a list of values."""
    domain_str = domain_str.strip()
    if '..' in domain_str:
        lo, hi = domain_str.split('..')
        return list(range(int(lo), int(hi) + 1))
    else:
        return [int(x) for x in domain_str.split()]


def parse_var_list(text):
    """Parse a whitespace-separated list of variable references."""
    return [t.strip() for t in text.strip().split() if t.strip()]


def parse_condition(cond_str):
    """Parse condition like '(eq,15)' into (operator, value)."""
    cond_str = cond_str.strip().strip('()')
    op, val = cond_str.split(',')
    return op.strip(), int(val.strip())


def eval_condition(value, op, target):
    """Evaluate a comparison condition."""
    ops = {
        'eq': lambda a, b: a == b,
        'ne': lambda a, b: a != b,
        'lt': lambda a, b: a < b,
        'le': lambda a, b: a <= b,
        'gt': lambda a, b: a > b,
        'ge': lambda a, b: a >= b,
    }
    return ops[op](value, target)


class IntensionEvaluator:
    """Evaluator for XCSP3 intension functional expressions."""

    VAR_PATTERN = re.compile(r'[a-zA-Z]\w*\[\d+\]')

    def __init__(self, expr_str):
        self.expr_str = expr_str.strip()
        self.vars_used = set(self.VAR_PATTERN.findall(self.expr_str))

    def evaluate(self, assignment):
        return self._eval(self.expr_str, assignment)

    def _eval(self, expr, assignment):
        expr = expr.strip()

        # Variable reference: name[index]
        if self.VAR_PATTERN.fullmatch(expr):
            return assignment[expr]

        # Integer literal
        if re.fullmatch(r'-?\d+', expr):
            return int(expr)

        # Function call: func(arg1, arg2, ...)
        m = re.match(r'^(\w+)\((.+)\)$', expr, re.DOTALL)
        if not m:
            raise ValueError(f"Cannot parse expression: {expr}")

        func = m.group(1)
        raw_args = self._split_args(m.group(2))
        args = [self._eval(a, assignment) for a in raw_args]

        dispatch = {
            'eq': lambda a: a[0] == a[1],
            'ne': lambda a: a[0] != a[1],
            'lt': lambda a: a[0] < a[1],
            'le': lambda a: a[0] <= a[1],
            'gt': lambda a: a[0] > a[1],
            'ge': lambda a: a[0] >= a[1],
            'add': lambda a: a[0] + a[1],
            'sub': lambda a: a[0] - a[1],
            'mul': lambda a: a[0] * a[1],
            'dist': lambda a: abs(a[0] - a[1]),
            'abs': lambda a: abs(a[0]),
            'neg': lambda a: -a[0],
            'and': lambda a: all(a),
            'or': lambda a: any(a),
            'not': lambda a: not a[0],
        }

        if func not in dispatch:
            raise ValueError(f"Unknown function: {func}")
        return dispatch[func](args)

    @staticmethod
    def _split_args(args_str):
        """Split function arguments respecting nested parentheses."""
        args = []
        depth = 0
        current = []
        for ch in args_str:
            if ch == '(':
                depth += 1
                current.append(ch)
            elif ch == ')':
                depth -= 1
                current.append(ch)
            elif ch == ',' and depth == 0:
                args.append(''.join(current).strip())
                current = []
            else:
                current.append(ch)
        tail = ''.join(current).strip()
        if tail:
            args.append(tail)
        return args


class Constraint:
    """Represents a single constraint with a type and parameters."""

    def __init__(self, ctype, **kw):
        self.ctype = ctype
        self.kw = kw
        # Variables referenced by this constraint (for ordering heuristics)
        self.scope = kw.get('scope', [])

    def satisfied(self, assignment):
        """
        Return True if the constraint is satisfied by the (partial) assignment.
        Constraints over not-yet-assigned variables are treated as satisfied
        (forward checking evaluates only when all scope vars are bound).
        """
        if self.ctype == 'allDifferent':
            vals = [assignment[v] for v in self.scope if v in assignment]
            return len(vals) == len(set(vals))

        elif self.ctype == 'sum':
            if not all(v in assignment for v in self.scope):
                return True
            coeffs = self.kw['coeffs']
            total = sum(c * assignment[v] for c, v in zip(coeffs, self.scope))
            op, target = self.kw['condition']
            return eval_condition(total, op, target)

        elif self.ctype == 'intension':
            evaluator = self.kw['evaluator']
            if not all(v in assignment for v in evaluator.vars_used):
                return True
            return bool(evaluator.evaluate(assignment))

        return True


class XCSPInstance:
    """Parsed XCSP3 instance."""

    def __init__(self, xml_path):
        self.variables = {}      # name -> list of domain values
        self.var_order = []      # deterministic variable ordering
        self.constraints = []
        self.objectives = []
        self.instance_type = None
        self._parse(xml_path)

    def _parse(self, path):
        tree = ET.parse(path)
        root = tree.getroot()
        self.instance_type = root.get('type', 'CSP')

        # --- variables ---
        for elem in root.find('variables'):
            if elem.tag == 'array':
                vid = elem.get('id')
                dims = [int(d) for d in re.findall(r'\d+', elem.get('size'))]
                n = 1
                for d in dims:
                    n *= d
                dom = parse_domain(elem.text)
                for i in range(n):
                    name = f"{vid}[{i}]"
                    self.variables[name] = dom[:]
                    self.var_order.append(name)
            elif elem.tag == 'var':
                name = elem.get('id')
                self.variables[name] = parse_domain(elem.text)
                self.var_order.append(name)

        # --- constraints ---
        celem = root.find('constraints')
        if celem is not None:
            for child in celem:
                self._parse_constraint(child)

        # --- objectives ---
        oelem = root.find('objectives')
        if oelem is not None:
            for child in oelem:
                self._parse_objective(child)

    def _parse_constraint(self, elem):
        if elem.tag == 'allDifferent':
            scope = parse_var_list(elem.text)
            self.constraints.append(Constraint('allDifferent', scope=scope))

        elif elem.tag == 'sum':
            scope = parse_var_list(elem.find('list').text)
            ce = elem.find('coeffs')
            coeffs = [int(c) for c in ce.text.split()] if ce is not None else [1] * len(scope)
            condition = parse_condition(elem.find('condition').text)
            self.constraints.append(
                Constraint('sum', scope=scope, coeffs=coeffs, condition=condition)
            )

        elif elem.tag == 'intension':
            ev = IntensionEvaluator(elem.text)
            self.constraints.append(
                Constraint('intension', scope=list(ev.vars_used), evaluator=ev)
            )

        elif elem.tag == 'group':
            tmpl_elem = elem.find('intension')
            if tmpl_elem is not None:
                template = tmpl_elem.text.strip()
                for args_elem in elem.findall('args'):
                    tokens = args_elem.text.strip().split()
                    expr_str = template
                    for idx, tok in enumerate(tokens):
                        expr_str = expr_str.replace(f'%{idx}', tok)
                    ev = IntensionEvaluator(expr_str)
                    self.constraints.append(
                        Constraint('intension', scope=list(ev.vars_used), evaluator=ev)
                    )

    def _parse_objective(self, elem):
        direction = elem.tag  # 'maximize' or 'minimize'
        scope = parse_var_list(elem.find('list').text)
        ce = elem.find('coeffs')
        coeffs = [int(c) for c in ce.text.split()] if ce is not None else [1] * len(scope)
        self.objectives.append({
            'direction': direction,
            'scope': scope,
            'coeffs': coeffs,
        })


class Solver:
    """Backtracking CSP/COP solver with forward checking."""

    def __init__(self, instance):
        self.inst = instance
        self.best_sol = None
        self.best_obj = None

    def solve(self):
        if self.inst.instance_type == 'COP':
            return self._solve_cop()
        return self._solve_csp()

    # ---------- CSP ----------
    def _solve_csp(self):
        assignment = {}
        sol = self._backtrack(assignment, 0)
        if sol is not None:
            return 'SAT', sol, None
        return 'UNSAT', None, None

    def _backtrack(self, assignment, idx):
        if idx == len(self.inst.var_order):
            return dict(assignment)
        var = self.inst.var_order[idx]
        for val in self.inst.variables[var]:
            assignment[var] = val
            if self._consistent(assignment):
                result = self._backtrack(assignment, idx + 1)
                if result is not None:
                    return result
            del assignment[var]
        return None

    # ---------- COP ----------
    def _solve_cop(self):
        self.best_sol = None
        self.best_obj = None
        self._bb({}, 0)
        if self.best_sol is not None:
            return 'OPTIMUM', self.best_sol, self.best_obj
        return 'UNSAT', None, None

    def _bb(self, assignment, idx):
        if idx == len(self.inst.var_order):
            if self._consistent(assignment):
                obj_val = self._eval_objective(assignment)
                if self.best_obj is None or self._is_better(obj_val):
                    self.best_obj = obj_val
                    self.best_sol = dict(assignment)
            return
        var = self.inst.var_order[idx]
        for val in self.inst.variables[var]:
            assignment[var] = val
            if self._consistent(assignment):
                self._bb(assignment, idx + 1)
            del assignment[var]

    def _eval_objective(self, assignment):
        obj = self.inst.objectives[0]
        return sum(c * assignment[v] for c, v in zip(obj['coeffs'], obj['scope']))

    def _is_better(self, val):
        direction = self.inst.objectives[0]['direction']
        if direction == 'maximize':
            return val > self.best_obj
        return val < self.best_obj

    # ---------- consistency ----------
    def _consistent(self, assignment):
        return all(c.satisfied(assignment) for c in self.inst.constraints)


def main():
    instances_dir = '/app/instances'
    results_dir = '/app/results'
    os.makedirs(results_dir, exist_ok=True)

    for fname in sorted(os.listdir(instances_dir)):
        if not fname.endswith('.xml'):
            continue
        xml_path = os.path.join(instances_dir, fname)
        base = fname[:-4]
        out_path = os.path.join(results_dir, f"{base}.json")

        print(f"Solving {fname} ...")
        inst = XCSPInstance(xml_path)
        solver = Solver(inst)
        status, solution, objective = solver.solve()

        result = {"status": status}
        if solution is not None:
            result["solution"] = solution
        if objective is not None:
            result["objective"] = objective

        with open(out_path, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"  -> {status}" + (f"  objective={objective}" if objective is not None else ""))


if __name__ == '__main__':
    main()
