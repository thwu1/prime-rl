#!/usr/bin/env python3

"""
XCSP3-to-MiniZinc compiler.
Parses XCSP3-core XML instances, generates MiniZinc models,
invokes the MiniZinc/Chuffed toolchain, and writes JSON results.
"""

import xml.etree.ElementTree as ET
import json
import os
import re
import subprocess


# ---------------------------------------------------------------------------
# Domain parsing
# ---------------------------------------------------------------------------

def parse_domain_str(domain_str):
    """Parse XCSP3 domain string into a MiniZinc domain expression."""
    domain_str = domain_str.strip()
    if '..' in domain_str:
        parts = domain_str.split('..')
        lo, hi = int(parts[0].strip()), int(parts[1].strip())
        return f"{lo}..{hi}"
    else:
        vals = sorted(int(x) for x in domain_str.split())
        if vals == list(range(vals[0], vals[-1] + 1)):
            return f"{vals[0]}..{vals[-1]}"
        else:
            return "{" + ", ".join(str(v) for v in vals) + "}"


def parse_var_list(text):
    """Parse whitespace-separated variable references."""
    return [t.strip() for t in text.strip().split() if t.strip()]


def parse_condition(cond_str):
    """Parse XCSP3 condition like '(eq,15)' into (operator, value)."""
    cond_str = cond_str.strip().strip('()')
    parts = cond_str.split(',')
    return parts[0].strip(), int(parts[1].strip())


# Mapping from XCSP3 comparison operators to MiniZinc infix operators
OP_TO_MZN = {
    'eq': '=', 'ne': '!=', 'lt': '<', 'le': '<=', 'gt': '>', 'ge': '>='
}


# ---------------------------------------------------------------------------
# Expression translator: XCSP3 prefix -> MiniZinc infix
# ---------------------------------------------------------------------------

class ExprTranslator:
    """Translates XCSP3 functional expressions to MiniZinc infix notation."""

    VAR_PAT = re.compile(r'[a-zA-Z_]\w*\[\d+\]')

    def translate(self, expr_str):
        return self._t(expr_str.strip())

    def _t(self, e):
        e = e.strip()

        # Variable reference: name[index]
        if self.VAR_PAT.fullmatch(e):
            return e

        # Integer literal
        if re.fullmatch(r'-?\d+', e):
            return e

        # Function call: func(arg1, arg2, ...)
        m = re.match(r'^(\w+)\((.+)\)$', e, re.DOTALL)
        if not m:
            raise ValueError(f"Cannot parse expression: {e}")

        fn = m.group(1)
        args = [self._t(a) for a in self._split(m.group(2))]

        # Comparison operators -> infix
        if fn in OP_TO_MZN and len(args) == 2:
            return f"({args[0]} {OP_TO_MZN[fn]} {args[1]})"

        # Arithmetic operators
        if fn == 'add' and len(args) == 2:
            return f"({args[0]} + {args[1]})"
        if fn == 'sub' and len(args) == 2:
            return f"({args[0]} - {args[1]})"
        if fn == 'mul' and len(args) == 2:
            return f"({args[0]} * {args[1]})"
        if fn == 'dist' and len(args) == 2:
            return f"abs({args[0]} - {args[1]})"
        if fn == 'abs' and len(args) == 1:
            return f"abs({args[0]})"
        if fn == 'neg' and len(args) == 1:
            return f"(-{args[0]})"

        raise ValueError(f"Unknown function: {fn}")

    @staticmethod
    def _split(s):
        """Split function arguments respecting nested parentheses."""
        parts, depth, cur = [], 0, []
        for c in s:
            if c == '(':
                depth += 1
                cur.append(c)
            elif c == ')':
                depth -= 1
                cur.append(c)
            elif c == ',' and depth == 0:
                parts.append(''.join(cur).strip())
                cur = []
            else:
                cur.append(c)
        tail = ''.join(cur).strip()
        if tail:
            parts.append(tail)
        return parts


# ---------------------------------------------------------------------------
# XCSP3-to-MiniZinc compiler
# ---------------------------------------------------------------------------

class Compiler:
    """Compiles a single XCSP3 XML instance to a MiniZinc model."""

    def __init__(self, xml_path):
        self.tree = ET.parse(xml_path)
        self.root = self.tree.getroot()
        self.instance_type = self.root.get('type', 'CSP')
        self.trans = ExprTranslator()

        self.includes = set()
        self.decls = []
        self.constraints = []
        self.solve_stmt = "solve satisfy;"
        self.obj_expr = None

        # Track all variables in declaration order for output
        self.all_vars = []  # list of (array_id, index) or (var_id, None)

    def compile(self):
        """Generate MiniZinc model string."""
        self._compile_variables()
        self._compile_constraints()
        self._compile_objectives()
        return self._emit()

    def _compile_variables(self):
        for el in self.root.find('variables'):
            if el.tag == 'array':
                vid = el.get('id')
                n = int(re.findall(r'\d+', el.get('size'))[0])
                dom = parse_domain_str(el.text)
                self.decls.append(f"array[0..{n - 1}] of var {dom}: {vid};")
                for i in range(n):
                    self.all_vars.append((vid, i))
            elif el.tag == 'var':
                vid = el.get('id')
                dom = parse_domain_str(el.text)
                self.decls.append(f"var {dom}: {vid};")
                self.all_vars.append((vid, None))

    def _compile_constraints(self):
        cel = self.root.find('constraints')
        if cel is None:
            return
        for ch in cel:
            self._compile_constraint(ch)

    def _compile_constraint(self, el):
        if el.tag == 'allDifferent':
            self.includes.add('alldifferent.mzn')
            vs = parse_var_list(el.text)
            self.constraints.append(
                f"constraint alldifferent([{', '.join(vs)}]);"
            )

        elif el.tag == 'sum':
            scope = parse_var_list(el.find('list').text)
            ce = el.find('coeffs')
            coeffs = (
                [int(c) for c in ce.text.split()]
                if ce is not None
                else [1] * len(scope)
            )
            op, target = parse_condition(el.find('condition').text)

            terms = []
            for c, v in zip(coeffs, scope):
                if c == 1:
                    terms.append(v)
                elif c == -1:
                    terms.append(f"(-{v})")
                else:
                    terms.append(f"{c}*{v}")
            self.constraints.append(
                f"constraint {' + '.join(terms)} {OP_TO_MZN[op]} {target};"
            )

        elif el.tag == 'intension':
            expr = self.trans.translate(el.text)
            self.constraints.append(f"constraint {expr};")

        elif el.tag == 'extension':
            self.includes.add('table.mzn')
            scope = parse_var_list(el.find('list').text)

            sup = el.find('supports')
            conf = el.find('conflicts')

            if sup is not None:
                tuples = self._parse_tuples(sup.text)
                tbl = self._format_table(tuples)
                self.constraints.append(
                    f"constraint table([{', '.join(scope)}], {tbl});"
                )
            elif conf is not None:
                # Negative table: solution must NOT match any conflict tuple
                tuples = self._parse_tuples(conf.text)
                tbl = self._format_table(tuples)
                self.constraints.append(
                    f"constraint not table([{', '.join(scope)}], {tbl});"
                )

        elif el.tag == 'group':
            tmpl_elem = el.find('intension')
            if tmpl_elem is not None:
                template = tmpl_elem.text.strip()
                for args_elem in el.findall('args'):
                    tokens = args_elem.text.strip().split()
                    expr_str = template
                    for idx, tok in enumerate(tokens):
                        expr_str = expr_str.replace(f'%{idx}', tok)
                    mzn_expr = self.trans.translate(expr_str)
                    self.constraints.append(f"constraint {mzn_expr};")

    def _parse_tuples(self, text):
        """Parse XCSP3 tuple format '(v1,v2)(v3,v4)...' into list of lists."""
        tuples = []
        for m in re.finditer(r'\(([^)]+)\)', text):
            tuples.append([int(v.strip()) for v in m.group(1).split(',')])
        return tuples

    def _format_table(self, tuples):
        """Format tuples as MiniZinc 2D array literal [| r1 | r2 | ... |]."""
        if not tuples:
            return "[| |]"
        rows = [", ".join(str(v) for v in t) for t in tuples]
        return "[| " + " | ".join(rows) + " |]"

    def _compile_objectives(self):
        oel = self.root.find('objectives')
        if oel is None:
            return

        for ch in oel:
            direction = ch.tag  # 'maximize' or 'minimize'
            scope = parse_var_list(ch.find('list').text)
            ce = ch.find('coeffs')
            coeffs = (
                [int(c) for c in ce.text.split()]
                if ce is not None
                else [1] * len(scope)
            )
            terms = []
            for c, v in zip(coeffs, scope):
                if c == 1:
                    terms.append(v)
                else:
                    terms.append(f"{c}*{v}")
            obj = ' + '.join(terms)
            self.solve_stmt = f"solve {direction} {obj};"
            self.obj_expr = obj

    def _emit(self):
        """Assemble the complete MiniZinc model string."""
        lines = []

        # Includes
        for inc in sorted(self.includes):
            lines.append(f'include "{inc}";')
        if self.includes:
            lines.append('')

        # Variable declarations
        for d in self.decls:
            lines.append(d)
        lines.append('')

        # Constraints
        for c in self.constraints:
            lines.append(c)
        lines.append('')

        # Solve statement
        lines.append(self.solve_stmt)
        lines.append('')

        # Output statement for parseable results
        parts = ['"SOL\\n"']
        for vname, idx in self.all_vars:
            ref = f"{vname}[{idx}]" if idx is not None else vname
            parts.append(f'"{ref}=", show({ref}), "\\n"')
        if self.obj_expr:
            parts.append(f'"OBJ=", show({self.obj_expr}), "\\n"')
        lines.append(f"output [{', '.join(parts)}];")

        return '\n'.join(lines)


# ---------------------------------------------------------------------------
# MiniZinc output parser
# ---------------------------------------------------------------------------

def parse_minizinc_output(stdout, instance_type):
    """Parse MiniZinc stdout into a result dict."""

    if '=====UNSATISFIABLE=====' in stdout:
        return {'status': 'UNSAT'}

    # Split by solution separator; find the last solution block
    blocks = stdout.split('----------')
    last_sol = None
    for block in blocks:
        if 'SOL' in block:
            last_sol = block

    if last_sol is None:
        return {'status': 'UNSAT'}

    # Parse variable assignments from the last solution
    solution = {}
    objective = None
    for line in last_sol.strip().split('\n'):
        line = line.strip()
        if '=' not in line or line == 'SOL':
            continue
        if line.startswith('OBJ='):
            objective = int(line.split('=', 1)[1])
        elif not line.startswith('---') and not line.startswith('==='):
            key, val = line.split('=', 1)
            solution[key] = int(val)

    if instance_type == 'COP':
        is_optimal = '==========' in stdout
        result = {
            'status': 'OPTIMUM' if is_optimal else 'SAT',
            'solution': solution,
        }
        if objective is not None:
            result['objective'] = objective
        return result

    return {'status': 'SAT', 'solution': solution}


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def main():
    inst_dir = '/app/instances'
    model_dir = '/app/models'
    result_dir = '/app/results'
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(result_dir, exist_ok=True)

    for fname in sorted(os.listdir(inst_dir)):
        if not fname.endswith('.xml'):
            continue
        base = fname[:-4]
        xml_path = os.path.join(inst_dir, fname)
        mzn_path = os.path.join(model_dir, f"{base}.mzn")
        out_path = os.path.join(result_dir, f"{base}.json")

        print(f"Compiling {fname} -> {base}.mzn ...")
        compiler = Compiler(xml_path)
        mzn_code = compiler.compile()

        with open(mzn_path, 'w') as f:
            f.write(mzn_code)

        print(f"  Solving with MiniZinc/Chuffed ...")
        proc = subprocess.run(
            ['minizinc', '--solver', 'chuffed', '--time-limit', '30000', mzn_path],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if proc.returncode != 0 and not proc.stdout.strip():
            print(f"  MiniZinc error: {proc.stderr}")
            result = {'status': 'ERROR', 'error': proc.stderr[:500]}
        else:
            result = parse_minizinc_output(proc.stdout, compiler.instance_type)

        with open(out_path, 'w') as f:
            json.dump(result, f, indent=2)

        status = result['status']
        obj_str = f"  objective={result.get('objective')}" if 'objective' in result else ''
        print(f"  -> {status}{obj_str}")


if __name__ == '__main__':
    main()
